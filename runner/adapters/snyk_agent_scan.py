"""Adapter for Snyk agent-scan 0.6.3 (formerly Invariant Labs `mcp-scan`),
`pip install snyk-agent-scan`, Apache-2.0.

Read docs/scanner-survey.md's "Snyk `agent-scan` -- CONFIRMED, token-gated"
section before touching this file. The load-bearing fact from that recon,
reproduced here because this whole adapter exists to defend it:

    Running a scan with `SNYK_TOKEN` unset, the tool connects to the target,
    enumerates every tool, assembles the payload, and then exits 1 with:

        To use Agent Scan, set the SNYK_TOKEN environment variable. To get
        a token, go to https://app.snyk.io/account (API Token -> KEY ->
        click to show).

    No findings are produced. The token gates ALL analysis, not some
    engines. The `inspect` subcommand runs tokenless but only enumerates
    tools/prompts/resources -- no security verdicts.

We do not have a `SNYK_TOKEN` and this project will not create a Snyk
account to get one. Per docs/governance.md's "Which scanners are included"
and its `unavailable_reason` handling, that makes this scanner's scoreboard
row **unavailable with a stated reason**, published rather than omitted --
omitting it would silently turn "we could not run this" into "this tool was
not considered", which is not neutral. `available()` is this adapter's most
important method for exactly that reason: it must return `(False, reason)`
promptly, precisely, and without ever touching the network or a container,
because there is nothing a token-gated scan could legitimately do without
the token.

Everything below `available()` -- config generation, the container spec, the
parser -- is written to work the moment a `SNYK_TOKEN` exists in the
environment, so that turning this row into real numbers is "set the
variable and run it" rather than "write the adapter". See the module-level
docstring note at the bottom of this file for exactly what a future
maintainer needs to do.

Two disclosures that belong on the scoreboard row alongside the reason,
because they are both material to a reader deciding whether to obtain a
token and run this scanner at all:

  1. **Analysis is server-side.** The payload agent-scan assembles (per
     recon) includes `scan_user_info` (hostname, username, IP,
     anonymous_identifier) and `scan_metadata` (cli_version), sent to Snyk.
     A run is not reproducible offline, may change without a version bump,
     and sends host metadata -- and, unavoidably, everything about our
     corpus servers it inspects -- to a vendor. Recorded in
     `SERVER_SIDE_ANALYSIS_NOTE` below and surfaced in `AdapterResult.extra`
     on every real run.
  2. **It executes stdio servers named in a config.** Irrelevant to this
     corpus (every server here is remote HTTP; recon observed agent-scan
     print "Remote MCP servers (no subprocess -- auto-allowed)" for exactly
     this shape), but this adapter never emits a config entry with anything
     other than `"type": "http"`, and deliberately never passes
     `--dangerously-run-mcp-servers` -- there is nothing in this benchmark's
     configs that flag would be needed for, and omitting it is one more
     margin against ever accidentally launching a subprocess from inside a
     scanner container.

Label vocabulary is UNVERIFIED
-------------------------------
docs/scanner-survey.md could not verify 0.6.3's real finding-label strings
without a token: it only has the vendor's own description of the ~15 scored
"risk indicators" 0.6+ uses (`prompt injection`, `dangerous words`,
`untrusted content`, `private data`, `destructive capabilities`,
`suspicious downloads`, `malicious code`, `secret detection`), and does not
know the exact JSON field name(s) or casing 0.6.3's `--json` output actually
uses for them. `mapping/snyk-agent-scan.json` reflects that: its
`label_provenance` is `"unverified"`, never `"captured-from-real-output"`.

Because of that uncertainty, `parse_report` below is maximally defensive: it
tries several plausible container keys and several plausible per-item label
fields, and a finding whose shape matches none of them is still emitted as a
`RawFinding` (raw_label may be empty, the whole item is preserved in `raw`)
rather than dropped. Per runner/adapters/__init__.py, an unrecognised finding
costs the scanner nothing -- it scores `unmapped` -- and dropping it would
hide a taxonomy gap instead of revealing one.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..models import RawFinding
from . import AdapterResult, RuntimeTarget, StaticTarget
from .container import ContainerSpec, docker_available, image_present, run_container

# ---------------------------------------------------------------------------
# Pinned build identity. Must match
# runner/adapters/dockerfiles/snyk-agent-scan.Dockerfile.
# ---------------------------------------------------------------------------

SCANNER_VERSION = "0.6.3"

IMAGE = f"mcp-sec-bench/snyk-agent-scan:{SCANNER_VERSION}"

DOCKERFILE_PATH = Path(__file__).parent / "dockerfiles" / "snyk-agent-scan.Dockerfile"

BUILD_HINT = (
    "docker build -f runner/adapters/dockerfiles/snyk-agent-scan.Dockerfile "
    f"-t {IMAGE} runner/adapters/dockerfiles"
)

#: The exact env var name a scoreboard reader needs to set. Named once here
#: so the reason text in `available()` and every test that checks it agree.
TOKEN_ENV_VAR = "SNYK_TOKEN"

#: Where the generated mcpServers config is mounted inside the container.
CONFIG_MOUNTPOINT = "/scan-config"
CONFIG_FILENAME = "mcp-servers.json"

DEFAULT_CONTAINER_TIMEOUT_SECS = 180

#: Verified by recon (docs/scanner-survey.md) to be the exact message
#: agent-scan prints, on stdout, when it ran WITHOUT a token: it still
#: enumerates tools and assembles a payload, then refuses at the last step.
#: Matched defensively (substring) so this adapter can tell "the token was
#: rejected mid-run" apart from "the JSON just didn't parse" even though it
#: should never observe this path itself (available() gates on the token
#: first). A future run with an invalid/expired token could still hit it.
TOKEN_REFUSAL_MARKER = "set the SNYK_TOKEN environment variable"

SERVER_SIDE_ANALYSIS_NOTE = (
    "snyk-agent-scan analysis is SERVER-SIDE: the scan payload it assembles "
    "(per docs/scanner-survey.md recon) includes scan_user_info (hostname, "
    "username, ip_address, anonymous_identifier) and scan_metadata "
    "(cli_version), sent to Snyk. A run is not reproducible offline, may "
    "change without a version bump, and shares information about the target "
    "(here, a corpus server) with a vendor. Material to disclose alongside "
    "any published number for this row."
)


def _redact(text: str | None, token: str | None) -> str:
    """Strip a live SNYK_TOKEN value out of text before it can reach anything
    this adapter returns (raw_output, error messages, AdapterResult.extra).

    Belt-and-suspenders: nothing this adapter writes should ever contain the
    token in the first place (it goes to the container only via
    ContainerSpec.env, never into the generated config file, never into a
    log call), but the underlying tool's own stdout/stderr is not something
    we control, so anything that reaches us from the container is scrubbed
    on the way out regardless.
    """
    if not text:
        return text or ""
    if not token:
        return text
    return text.replace(token, "<SNYK_TOKEN redacted>")


def _extract_json(text: str) -> Any | None:
    """Pull a JSON value out of stdout, tolerating a stray banner line.

    Mirrors mcp_guard.py's `_extract_json`, written locally rather than
    imported: each adapter owns its own parsing per house style, and this
    one additionally has to accept a bare JSON array at the top level, which
    mcp-guard's report shape never does.
    """
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    for opener, decoder_kind in (("{", dict), ("[", list)):
        start = text.find(opener)
        if start == -1:
            continue
        decoder = json.JSONDecoder()
        try:
            parsed, _ = decoder.raw_decode(text[start:])
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, decoder_kind):
            return parsed
    return None


#: Top-level keys this adapter will look under for a findings array, tried in
#: this order. UNVERIFIED -- guessed from common shapes in this category
#: (mcp-guard uses "findings", ramparts uses "yara_results" /
#: "security_issues"), not from anything observed in agent-scan's own
#: output. Kept as a tuple, not a single guess, precisely because a wrong
#: single guess would silently produce zero findings on a real run and read
#: exactly like a clean scan.
_CANDIDATE_CONTAINER_KEYS = (
    "findings", "risks", "risk_indicators", "issues", "results", "items",
)

#: Per-item fields this adapter will check, in order, for the label to
#: preserve verbatim in RawFinding.raw_label. UNVERIFIED for the same reason
#: as above. "risk_indicator" and "category" are the closest readings of the
#: vendor vocabulary docs/scanner-survey.md could recover
#: (`prompt injection`, `secret detection`, etc. are described as named risk
#: indicators); the rest are defensive fallbacks carried over from this
#: project's other adapters' own label fields in case 0.6.3's real shape
#: turns out closer to one of them.
_CANDIDATE_LABEL_FIELDS = (
    "risk_indicator", "indicator", "category", "type", "issue_type",
    "rule_id", "code", "id", "name",
)

_CANDIDATE_SEVERITY_FIELDS = ("severity", "risk_level", "level")
_CANDIDATE_MESSAGE_FIELDS = ("message", "description", "summary", "detail")


def _first_str(item: dict[str, Any], fields: tuple[str, ...]) -> str | None:
    for f in fields:
        v = item.get(f)
        if isinstance(v, str) and v:
            return v
    return None


@dataclass
class SnykAgentScanAdapter:
    """Runs Snyk agent-scan 0.6.3 against one live corpus server.

    Declares stages={"runtime"} only. agent-scan's documented input is an
    mcpServers config file, which for a remote target means a URL it
    connects to and enumerates over the wire -- the same surface
    taxonomy.md calls `runtime` for A1/A2/A3 (served over `tools/list`) and
    the only surface it has for A4/A5/A6. The tool does have a
    directory/"skills" scanning mode (`--no-skills` implies a default-on
    static-ish surface per docs/scanner-survey.md), but this corpus's
    servers are remote HTTP with no local skills directory to hand it, so
    this adapter does not exercise that path -- see run_static below,
    which mirrors RampartsAdapter's refusal for the identical reason.
    """

    scanner_id: str = "snyk-agent-scan"
    display_name: str = "Snyk agent-scan (fka Invariant Labs mcp-scan)"
    adapter_version: str = "1.0.0"
    stages: frozenset[str] = frozenset({"runtime"})
    requires_signup: bool = True
    config_label: str = "default"

    image: str = IMAGE
    container_timeout: int = DEFAULT_CONTAINER_TIMEOUT_SECS
    notes: list[str] = field(default_factory=lambda: [SERVER_SIDE_ANALYSIS_NOTE])

    # -- protocol -----------------------------------------------------

    def available(self) -> tuple[bool, str]:
        """The decisive check for this adapter. See the module docstring.

        Checked in this order, and the token check runs FIRST and alone --
        before docker_available() or image_present() are even called --
        because a missing token is the defining constraint (per the task
        brief: "a SNYK_TOKEN gates ALL analysis - verified by recon, not
        just the extras") and the reason a reader needs is about the token,
        not about whether Docker happens to be installed on this particular
        host. Never raises: every branch returns, nothing here can throw
        past this method's boundary.
        """
        token = os.environ.get(TOKEN_ENV_VAR)
        if not token or not token.strip():
            return False, (
                f"{TOKEN_ENV_VAR} is not set. snyk-agent-scan 0.6.3 gates ALL "
                "analysis behind this token, confirmed by recon "
                "(docs/scanner-survey.md): run without it, the tool still "
                "connects to the target and enumerates its tools, then exits 1 "
                "printing 'To use Agent Scan, set the SNYK_TOKEN environment "
                "variable. To get a token, go to https://app.snyk.io/account "
                "(API Token -> KEY -> click to show).' and produces no "
                "findings. This adapter does not attempt a tokenless partial "
                "scan -- there is nothing a partial run of this tool would "
                "legitimately measure. Set SNYK_TOKEN (free signup) to enable "
                "this row. Note before doing so: " + SERVER_SIDE_ANALYSIS_NOTE
            )

        ok, reason = docker_available()
        if not ok:
            return False, f"{reason}; snyk-agent-scan runs in a container"
        try:
            present = image_present(self.image)
        except Exception as exc:  # docker present but misbehaving
            return False, (f"could not inspect the {self.image} image "
                           f"({type(exc).__name__}: {exc})")
        if not present:
            return False, (f"the {self.image} image is not built. Build it with: "
                           f"{BUILD_HINT}")
        return True, ""

    def run_static(self, target: StaticTarget) -> AdapterResult:
        raise NotImplementedError(
            "SnykAgentScanAdapter declares stages={'runtime'} only. agent-scan's "
            "documented input is an mcpServers config file; for a directory/"
            "skills-dir target it has a static-ish scanning surface, but this "
            "corpus's servers are remote HTTP with no local skills directory, "
            "so that path is never exercised here. See the module docstring."
        )

    def run_runtime(self, target: RuntimeTarget) -> AdapterResult:
        ok, reason = self.available()
        if not ok:
            # Never falls back to a partial/tokenless scan (see available()).
            return AdapterResult(findings=[], error=reason)

        token = os.environ.get(TOKEN_ENV_VAR, "")

        config_dir = Path(tempfile.mkdtemp(prefix="snyk-agent-scan-config-"))
        try:
            config_path = config_dir / CONFIG_FILENAME
            try:
                config_path.write_text(
                    json.dumps(self._build_mcp_servers_config(target), indent=2)
                )
            except OSError as exc:
                return AdapterResult(
                    findings=[],
                    error=f"could not write scan config: {type(exc).__name__}: {exc}",
                )

            spec = ContainerSpec(
                image=self.image,
                args=[
                    "scan",
                    f"{CONFIG_MOUNTPOINT}/{CONFIG_FILENAME}",
                    "--json",
                    "--ci",
                    "--suppress-mcpserver-io=true",
                ],
                env={
                    # SNYK_TOKEN goes to the container ONLY through this env
                    # mapping -- never written into the generated config
                    # file above, never interpolated into `args`, never
                    # passed to any logging call. container.py's
                    # build_command() places it on the `docker run`
                    # argv (-e KEY=VALUE); that is the only env-passing
                    # mechanism run_container exposes and this adapter does
                    # not modify runner/adapters/container.py to add
                    # another one. It never reaches raw_output, error, or
                    # extra below -- those are built from run.stdout/stderr
                    # only, and are scrubbed via _redact regardless.
                    TOKEN_ENV_VAR: token,
                },
                mounts=[(config_dir, CONFIG_MOUNTPOINT, "ro")],
                # No `network=` override: leaving it unset means no
                # `--network` flag is passed to `docker run` at all, i.e.
                # docker's default bridge network, which keeps outbound
                # internet reachable -- required once a real token is set,
                # since agent-scan's analysis is server-side (see
                # SERVER_SIDE_ANALYSIS_NOTE) and needs to reach Snyk.
                # needs_lab=True adds the host.docker.internal mapping so
                # the container can still reach the corpus lab. Same
                # configuration RampartsAdapter uses for the same reason.
                needs_lab=True,
                timeout=self.container_timeout,
            )

            run = run_container(spec)
        finally:
            shutil.rmtree(config_dir, ignore_errors=True)

        raw_output = _redact(run.combined, token)

        if run.error and run.exit_code is None:
            return AdapterResult(
                findings=[], raw_output=raw_output, exit_code=None,
                duration_seconds=run.duration_seconds,
                error=_redact(run.error, token),
                scanner_version=SCANNER_VERSION,
                extra={"image": self.image, "server_side_analysis": SERVER_SIDE_ANALYSIS_NOTE},
            )

        stdout = run.stdout.strip()
        if TOKEN_REFUSAL_MARKER in run.combined:
            # A token was set (available() checked) but agent-scan still hit
            # its own tokenless-refusal path -- e.g. an invalid/expired
            # token, or a token rejected server-side. Surfaced as an error,
            # never as a silent zero-findings result: a wrong-token run and
            # a genuine clean scan must not look the same.
            return AdapterResult(
                findings=[], raw_output=raw_output, exit_code=run.exit_code,
                duration_seconds=run.duration_seconds,
                error=(
                    "agent-scan printed its token-refusal message despite a "
                    f"{TOKEN_ENV_VAR} being set for this run -- treat the token "
                    "as rejected (invalid, expired, or revoked), not as a clean "
                    "scan. Refusing to report zero findings as if this were a "
                    "genuine result."
                ),
                scanner_version=SCANNER_VERSION,
                extra={"image": self.image, "server_side_analysis": SERVER_SIDE_ANALYSIS_NOTE},
            )

        payload = _extract_json(stdout)
        if payload is None:
            detail = _redact((run.stderr or run.stdout or "").strip()[:400], token)
            return AdapterResult(
                findings=[], raw_output=raw_output, exit_code=run.exit_code,
                duration_seconds=run.duration_seconds,
                error=(f"snyk-agent-scan produced no parseable JSON output "
                       f"(exit {run.exit_code})"
                       + (f": {detail}" if detail else "")),
                scanner_version=SCANNER_VERSION,
                extra={"image": self.image, "server_side_analysis": SERVER_SIDE_ANALYSIS_NOTE},
            )

        findings, extra = self.parse_report(payload, target.server_id)
        extra["image"] = self.image
        extra["server_side_analysis"] = SERVER_SIDE_ANALYSIS_NOTE
        extra["server_id"] = target.server_id
        extra["url"] = target.url

        error = None
        if run.exit_code not in (0, None):
            error = (f"snyk-agent-scan exited {run.exit_code}; a report was still "
                     f"parsed and its findings (if any) are included")

        return AdapterResult(
            findings=findings,
            raw_output=raw_output,
            exit_code=run.exit_code,
            duration_seconds=run.duration_seconds,
            error=error,
            scanner_version=SCANNER_VERSION,
            extra=extra,
        )

    # -- config generation ----------------------------------------------

    @staticmethod
    def _build_mcp_servers_config(target: RuntimeTarget) -> dict[str, Any]:
        """The mcpServers config JSON agent-scan expects, one server per
        file for clean attribution (docs/scanner-survey.md's own worked
        example uses this shape).

        `target.token` is the CORPUS LAB's bearer token for this server
        (e.g. "lab-token-do-not-reuse"), never SNYK_TOKEN -- the two must
        never be confused. Only ever "type": "http" is emitted: this
        adapter never hands agent-scan a stdio launch command, so
        `--dangerously-run-mcp-servers` is never needed and never passed.
        """
        server: dict[str, Any] = {"type": "http", "url": target.url}
        if target.authenticated:
            if not target.token:
                raise ValueError(
                    f"RuntimeTarget for {target.server_id!r} is marked "
                    "authenticated=True but carries no token -- refusing to "
                    "scan unauthenticated by accident."
                )
            server["headers"] = {"Authorization": f"Bearer {target.token}"}
        return {"mcpServers": {target.server_id: server}}

    # -- parsing ----------------------------------------------------------

    def parse_report(
        self, payload: Any, server_id: str
    ) -> tuple[list[RawFinding], dict[str, Any]]:
        """Turn one agent-scan JSON payload into RawFindings.

        Defensive by necessity (see module docstring): the real 0.6.3
        output shape has not been observed. Every element found under any
        of `_CANDIDATE_CONTAINER_KEYS` (or, if the payload is itself a bare
        list, every element of it) becomes exactly one RawFinding. A label
        is read from the first of `_CANDIDATE_LABEL_FIELDS` present and
        preserved VERBATIM in raw_label; an item with none of those fields
        still becomes a RawFinding (raw_label="") with the whole item kept
        in `raw` rather than being dropped -- per runner/adapters/__init__.py,
        an unrecognised finding costs the scanner nothing (scored
        `unmapped`) and dropping it would hide a gap instead of showing one.

        Returns (findings, extra) where `extra` records which container key
        (if any) was matched, for anyone auditing this adapter's guesses
        against real output the day a token becomes available.
        """
        extra: dict[str, Any] = {}
        items: list[Any] | None = None
        matched_key: str | None = None

        if isinstance(payload, list):
            items = payload
            matched_key = "<top-level array>"
        elif isinstance(payload, dict):
            extra["top_level_keys"] = sorted(payload.keys())
            for key in _CANDIDATE_CONTAINER_KEYS:
                value = payload.get(key)
                if isinstance(value, list):
                    items = value
                    matched_key = key
                    break

        extra["matched_container_key"] = matched_key

        if items is None:
            # No recognised findings container. Per the module docstring we
            # do not fabricate a finding out of unrelated top-level
            # metadata (cli_version, scan_user_info, ...); we record the
            # payload's shape for a human to inspect and report zero
            # findings for this run, honestly, rather than guessing.
            if isinstance(payload, dict):
                extra["unparsed_payload_preview"] = json.dumps(payload)[:2000]
            return [], extra

        findings: list[RawFinding] = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                findings.append(RawFinding(
                    scanner_id=self.scanner_id,
                    raw_label="",
                    server_id=server_id,
                    message=f"malformed finding at index {index} in {matched_key!r}",
                    stage="runtime",
                    raw={"malformed": True, "value": repr(item)[:500]},
                ))
                continue

            label = _first_str(item, _CANDIDATE_LABEL_FIELDS) or ""
            severity = _first_str(item, _CANDIDATE_SEVERITY_FIELDS)
            message = _first_str(item, _CANDIDATE_MESSAGE_FIELDS) or ""

            findings.append(RawFinding(
                scanner_id=self.scanner_id,
                raw_label=label,
                server_id=server_id,
                message=message,
                severity=severity,
                stage="runtime",
                raw=item,
            ))

        return findings, extra


def build_command() -> list[str]:
    """The exact command that builds this adapter's image. Published with the row."""
    here = Path(__file__).resolve().parent
    return ["docker", "build", "-f",
            str(here / "dockerfiles" / "snyk-agent-scan.Dockerfile"),
            "-t", IMAGE, str(here / "dockerfiles")]


# ---------------------------------------------------------------------------
# For a future maintainer with a SNYK_TOKEN
# ---------------------------------------------------------------------------
#
# 1. `export SNYK_TOKEN=...` (free signup at https://app.snyk.io/account) and
#    build the image: see build_command() / BUILD_HINT above.
# 2. Run this adapter against one or more corpus servers. `available()` will
#    now return (True, ""); `run_runtime` will produce real `raw_output`.
# 3. Commit that raw output under tests/fixtures/ (following the pattern of
#    tests/fixtures/mcp-guard-corpus-scan.json / ramparts_a01_*.json), then:
#      a. Update `_CANDIDATE_CONTAINER_KEYS` / `_CANDIDATE_LABEL_FIELDS`
#         above to match the REAL shape (they are guesses today; keep the
#         defensive fallback behaviour, just reorder or extend the tuples).
#      b. Rewrite mapping/snyk-agent-scan.json: flip `label_provenance` to
#         "captured-from-real-output", set `provenance_note` to point at the
#         committed fixture, and re-derive every entry's `raw_label` from
#         labels actually observed rather than from vendor prose. Every
#         entry currently in that file is `unverified` / `provisional` and
#         must be treated as informed guesses, not ground truth, until this
#         step happens.
#      c. Add a parsing test against the new fixture alongside the existing
#         synthetic one in tests/test_adapter_snyk.py (keep the synthetic
#         fixture too -- it documents the defensive-parsing contract
#         independent of what agent-scan's real shape turns out to be).
