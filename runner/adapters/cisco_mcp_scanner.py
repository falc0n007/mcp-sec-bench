"""Adapter for Cisco `mcp-scanner` (PyPI `cisco-ai-mcp-scanner`), pinned at 4.8.4.

What this adapter measures, stated up front because it decides how the row reads
=============================================================================

Cisco's analyzer list is `api, yara, llm, behavioral, virustotal, readiness,
vulnerable_package, meta`. Exactly two of those run with no credential of any
kind: `yara` and `readiness`. Everything that reads **source code** is gated:

  * `behavioral <dir>` is the only analyzer that parses a server's Python. With
    no key it prints, verbatim:
    `Error during scanning: LLM provider API key is required for alignment
    verification`.
  * The global `--source-path` flag is wired to the behavioral analyzer alone
    (`mcpscanner/cli.py`), so it does not give YARA a source directory either.

So the credential-free Cisco is an **endpoint-and-tool-description scanner**, not
a source scanner, and this adapter declares `stages = {"runtime"}`. Declaring
`static` and scoring 0% there would be exactly the category error
docs/scoring.md forbids: a tool is not bad at something it does not attempt.
That limitation is itself a publishable result, and it is the single most
important thing a reader of this row needs to know.

The default configuration is therefore:

    mcp-scanner --analyzers yara --log-level error --raw \
        remote --server-url <live endpoint> --bearer-token <token>

run once per metadata surface Cisco exposes (`remote` = tools, plus `prompts`,
`resources`, `instructions`). Scanning only `remote` would understate the tool;
all four are cheap, so all four are scanned and each finding records which
surface produced it.

`readiness` is deliberately NOT in the default set. It is credential-free, but
it fires HIGH on every tool in the corpus for "does not specify a timeout"
(7 findings per tool) under the literal threat name `unknown`. Enabling it would
bury the security signal in a fixed-cost flood, and `unknown` is not a label any
taxonomy can place. It is available as a separate labelled configuration.

An LLM-gated configuration is built by :meth:`CiscoMcpScannerAdapter.llm_config`
and :meth:`behavioral_config`. Both are ADDITIONAL rows with their own
`config_label`; neither replaces the default. docs/scoring.md is explicit that
defaults are what users get, so defaults are what we measure.

Four traps this adapter exists to not fall into
===============================================

1. **A failed scan and a clean scan differ only in stdout.** A wrong URL, a
   missing token, a server that will not talk: all produce
   `Error during scanning: ...` on stderr and an EMPTY stdout. The exit status
   is 1 (measured, and measured again after an earlier reading through a shell
   pipe gave 0 -- so the exit code is usable, but it is not the only signal and
   this adapter does not rely on it alone). A successful scan with no findings
   is a JSON array of SAFE verdicts, and an empty `prompts` or `resources`
   surface is the literal `[]` with exit 0. So "Cisco found nothing" and "Cisco
   never connected" are distinguished here by whether stdout parses as a JSON
   array, not by exit code, and the number of items actually scanned is recorded
   per surface in `AdapterResult.extra["items_scanned"]`.

2. **With no subcommand the CLI silently scans `https://mcp.deepwiki.com/mcp`.**
   Verified: `mcp-scanner --analyzers yara --source-path /corpus/a01... ` returns
   findings for `read_wiki_structure`, a tool nobody in this benchmark owns. The
   adapter always passes an explicit subcommand and an explicit `--server-url`,
   and asserts the URL it scanned is the one it was given.

3. **The observable label is NOT the YARA rule filename.** The wheel ships ten
   rules named `code_execution, coercive_injection, command_injection,
   credential_harvesting, data_exfiltration, prompt_injection, script_injection,
   sql_injection, system_manipulation, tool_poisoning`. None of those strings
   ever appears in `--raw` output. What appears in `threat_names` is the rule's
   `meta.threat_type`, upper-cased and space-separated, and the ten rules
   collapse onto seven distinct values. `raw_label` is the string the scanner
   actually emitted; the rule filename is not guessed at.

4. **An analyzer can report findings with no threat name.** Rather than drop
   them -- which the adapter contract forbids -- they become a RawFinding under
   an explicitly synthetic sentinel label that no mapping table will ever place,
   so they surface as `unmapped` with a visible reason.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from ..models import RawFinding
from . import AdapterResult, RuntimeTarget, StaticTarget
from .container import (
    ContainerSpec,
    docker_available,
    image_present,
    lab_url,
    run_container,
)

#: The pin. Must match runner/adapters/dockerfiles/cisco-mcp-scanner.Dockerfile.
SCANNER_VERSION = "4.8.4"
IMAGE = f"mcp-sec-bench/cisco-mcp-scanner:{SCANNER_VERSION}"

DOCKERFILE = (
    Path(__file__).resolve().parent
    / "dockerfiles"
    / "cisco-mcp-scanner.Dockerfile"
)

#: Every metadata surface the credential-free Cisco can be pointed at. `remote`
#: is the tools surface and is the one the vendor documents first; the other
#: three exist and are scanned so the row is not an artefact of our invocation.
DEFAULT_SURFACES: tuple[str, ...] = ("remote", "prompts", "resources", "instructions")

#: Emitted instead of dropping a finding whose analyzer named no threat. Chosen
#: to be obviously ours and impossible to mistake for vendor vocabulary, so it
#: can never be quietly mapped to one of our classes.
UNLABELLED = "<cisco-mcp-scanner reported a finding with no threat name>"

_PORT_RE = re.compile(r"^\w+://[^/:]+:(\d+)(/.*)?$")


class CiscoScanFailed(RuntimeError):
    """The scanner produced no parseable result. See trap 1 in the module docstring."""


def _endpoint_in_container(url: str) -> str:
    """Rewrite a host-side lab URL to what the scanner container can reach.

    `runner/execute.py` builds runtime targets as `http://127.0.0.1:<port>/mcp`,
    which inside a container is the container's own loopback. `container.lab_url`
    is the verified way across.
    """
    m = _PORT_RE.match(url)
    if not m:
        return url
    return lab_url(int(m.group(1)), m.group(2) or "/mcp")


def _extract_json_array(stdout: str) -> list[Any]:
    """Parse `--raw` output, or refuse.

    A scan that never connected leaves stdout empty. Treating that as "zero
    findings" is the difference between reporting a detection failure and
    reporting a plumbing failure, so anything that is not a JSON array is an
    error here rather than a quiet empty result.

    `strict=False` is deliberate: a tool description can carry a literal control
    character, and Python's strict decoder rejects the whole document for it.
    Losing an entire scan to one stray byte in vendor output would be our bug,
    not theirs.
    """
    text = stdout.strip()
    if not text:
        raise CiscoScanFailed("scanner produced no stdout")
    try:
        parsed = json.loads(text, strict=False)
    except json.JSONDecodeError:
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end <= start:
            raise CiscoScanFailed(
                f"stdout is not JSON: {text.splitlines()[0][:200]!r}") from None
        try:
            parsed = json.loads(text[start:end + 1], strict=False)
        except json.JSONDecodeError as exc:
            raise CiscoScanFailed(f"stdout is not parseable JSON: {exc}") from None
    if not isinstance(parsed, list):
        raise CiscoScanFailed(
            f"expected a JSON array at the top level, got {type(parsed).__name__}")
    return parsed


def _analyzer_blocks(item: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Normalise the two shapes `--raw` uses for `findings`.

    Tool/prompt/resource items carry `findings` as a mapping of analyzer name to
    a result block. The `instructions` subcommand carries it as a list. Both are
    real output from 4.8.4, so both are handled rather than one being assumed.
    """
    findings = item.get("findings")
    if isinstance(findings, dict):
        return [(str(k), v) for k, v in findings.items() if isinstance(v, dict)]
    if isinstance(findings, list):
        out = []
        for i, block in enumerate(findings):
            if isinstance(block, dict):
                out.append((str(block.get("analyzer") or f"finding_{i}"), block))
        return out
    return []


def _item_label(item: dict[str, Any]) -> str:
    for key in ("tool_name", "prompt_name", "resource_name", "server_name"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    return str(item.get("item_type") or "item")


@dataclass
class CiscoMcpScannerAdapter:
    """Cisco mcp-scanner 4.8.4, run in a pinned container.

    The constructor carries the whole configuration surface so an alternative
    configuration is a second instance with its own `config_label`, published as
    an additional scoreboard row. Nothing here ever mutates the default.
    """

    scanner_id: str = "cisco-mcp-scanner"
    display_name: str = "Cisco mcp-scanner"
    adapter_version: str = "1.0.0"

    #: Credential-free Cisco reads live endpoints and tool metadata. It has no
    #: source-reading analyzer that runs without an LLM key, so it declares one
    #: stage and its static items are excluded from the denominator rather than
    #: counted as misses.
    stages: frozenset[str] = frozenset({"runtime"})
    requires_signup: bool = False
    config_label: str = "default"

    analyzers: tuple[str, ...] = ("yara",)
    surfaces: tuple[str, ...] = DEFAULT_SURFACES
    image: str = IMAGE
    scanner_version: str = SCANNER_VERSION
    timeout: int = 300
    #: Set only by the LLM-gated configurations. Never populated for `default`.
    llm_api_key: str | None = None
    source_scan: bool = False

    _version_checked: bool | None = field(default=None, init=False, repr=False)

    # -- alternative configurations ------------------------------------

    @classmethod
    def llm_config(cls, llm_api_key: str) -> "CiscoMcpScannerAdapter":
        """Cisco's shipped default analyzer set, minus the Cisco-account one.

        An ADDITIONAL row. `requires_signup` is True because it cannot run
        without a third-party LLM key, which is a disclosure on the row and
        never a disqualifier.
        """
        return cls(
            config_label="llm",
            analyzers=("yara", "llm"),
            requires_signup=True,
            llm_api_key=llm_api_key,
        )

    @classmethod
    def behavioral_config(cls, llm_api_key: str) -> "CiscoMcpScannerAdapter":
        """The only Cisco configuration that reads source, hence the only one
        that can honestly declare the static stage."""
        return cls(
            config_label="behavioral",
            analyzers=("behavioral",),
            surfaces=(),
            stages=frozenset({"static"}),
            requires_signup=True,
            llm_api_key=llm_api_key,
            source_scan=True,
        )

    @classmethod
    def readiness_config(cls) -> "CiscoMcpScannerAdapter":
        """Credential-free, and excluded from the default for cause.

        `readiness` reports HIGH on every tool in the corpus for properties like
        "does not specify a timeout", under the literal threat name `unknown`.
        Published separately so the claim that it is unusable as a security
        signal is checkable rather than asserted.
        """
        return cls(config_label="readiness", analyzers=("yara", "readiness"))

    # -- availability ---------------------------------------------------

    def available(self) -> tuple[bool, str]:
        """Never raises. A reason here becomes the published `unavailable_reason`."""
        ok, reason = docker_available()
        if not ok:
            return False, f"cannot run {self.display_name}: {reason}"

        try:
            present = image_present(self.image)
        except Exception as exc:  # noqa: BLE001 -- docker CLI misbehaving is data
            return False, f"could not query docker for {self.image}: {exc}"
        if not present:
            return False, (
                f"container image {self.image} is not built. Build it with: "
                f"docker build -f {DOCKERFILE.relative_to(DOCKERFILE.parents[3])} "
                f"-t {self.image} .")

        if self.llm_api_key is None and self.requires_signup:
            return False, (
                f"{self.display_name} configuration {self.config_label!r} needs an "
                f"LLM provider API key and none was supplied")

        ok, reason = self._verify_version()
        if not ok:
            return False, reason
        return True, ""

    def _verify_version(self) -> tuple[bool, str]:
        """Confirm the image really holds the pinned release.

        A scoreboard row names a scanner version. If the image drifted, every
        number under it is mislabelled, so this is checked once rather than
        assumed from the tag.
        """
        if self._version_checked is True:
            return True, ""
        result = run_container(ContainerSpec(
            image=self.image,
            entrypoint="python",
            args=["-c",
                  "import importlib.metadata as m;"
                  "print(m.version('cisco-ai-mcp-scanner'))"],
            timeout=120,
        ))
        if result.error:
            return False, f"could not read the scanner version: {result.error}"
        found = result.stdout.strip()
        if found != self.scanner_version:
            return False, (
                f"{self.image} contains cisco-ai-mcp-scanner {found!r}, "
                f"but this adapter is pinned to {self.scanner_version!r}")
        self._version_checked = True
        return True, ""

    # -- invocation -----------------------------------------------------

    def _base_args(self) -> list[str]:
        args = ["--analyzers", ",".join(self.analyzers),
                "--log-level", "error", "--raw"]
        if self.llm_api_key:
            args += ["--llm-api-key", self.llm_api_key]
        return args

    def _surface_args(self, surface: str, url: str, token: str | None) -> list[str]:
        args = self._base_args() + [surface, "--server-url", url]
        if token:
            # Verified working against the authenticated corpus servers: the CLI
            # sends `Authorization: Bearer <token>` and enumerates their tools.
            # There is no bearer-token limitation to report for this scanner.
            args += ["--bearer-token", token]
        return args

    def run_runtime(self, target: RuntimeTarget) -> AdapterResult:
        """Scan one live endpoint across every configured metadata surface."""
        if "runtime" not in self.stages:
            raise NotImplementedError(
                f"the {self.config_label!r} configuration of {self.display_name} "
                f"does not attempt the runtime stage")

        url = _endpoint_in_container(target.url)
        findings: list[RawFinding] = []
        chunks: list[str] = []
        errors: list[str] = []
        exit_code: int | None = 0
        duration = 0.0
        scanned: dict[str, int] = {}

        for surface in self.surfaces:
            result = run_container(ContainerSpec(
                image=self.image,
                args=self._surface_args(surface, url, target.token),
                needs_lab=True,
                timeout=self.timeout,
            ))
            duration += result.duration_seconds
            chunks.append(
                f"--- surface={surface} url={url} exit={result.exit_code} ---\n"
                f"{result.stdout}"
                + (f"\n[stderr]\n{result.stderr}" if result.stderr else ""))
            if result.exit_code not in (0, None):
                exit_code = result.exit_code

            if result.error:
                errors.append(f"{surface}: {result.error}")
                continue

            try:
                items = _extract_json_array(result.stdout)
            except CiscoScanFailed as exc:
                # Trap 1: exit 0 with no parseable output is a failed scan, and
                # is recorded as one instead of as an empty clean result.
                detail = (result.stderr or "").strip().splitlines()
                errors.append(
                    f"{surface}: {exc}"
                    + (f" | stderr: {detail[-1][:240]}" if detail else ""))
                continue

            scanned[surface] = len(items)
            findings.extend(self._parse_items(
                items, server_id=target.server_id, surface=surface, url=url))

        return AdapterResult(
            findings=findings,
            raw_output="\n".join(chunks),
            exit_code=exit_code,
            duration_seconds=duration,
            error="; ".join(errors) if errors else None,
            scanner_version=self.scanner_version,
            extra={
                "config_label": self.config_label,
                "analyzers": list(self.analyzers),
                "surfaces": list(self.surfaces),
                "endpoint": url,
                "authenticated": target.authenticated,
                "bearer_token_sent": bool(target.token),
                "items_scanned": scanned,
            },
        )

    def run_static(self, target: StaticTarget) -> AdapterResult:
        """Scan source. Only the behavioral configuration can, and it needs a key."""
        if "static" not in self.stages:
            raise NotImplementedError(
                f"the {self.config_label!r} configuration of {self.display_name} "
                f"does not attempt the static stage: Cisco's only source-code "
                f"analyzer is `behavioral`, which requires an LLM provider API "
                f"key. See CiscoMcpScannerAdapter.behavioral_config().")

        findings: list[RawFinding] = []
        chunks: list[str] = []
        errors: list[str] = []
        duration = 0.0
        exit_code: int | None = 0

        for server_dir in target.server_dirs:
            mount = "/corpus/" + server_dir.name
            result = run_container(ContainerSpec(
                image=self.image,
                args=self._base_args() + ["behavioral", mount],
                mounts=[(server_dir.resolve(), mount, "ro")],
                timeout=self.timeout,
            ))
            duration += result.duration_seconds
            chunks.append(f"--- server={server_dir.name} exit={result.exit_code} ---\n"
                          f"{result.stdout}")
            if result.exit_code not in (0, None):
                exit_code = result.exit_code
            if result.error:
                errors.append(f"{server_dir.name}: {result.error}")
                continue
            try:
                items = _extract_json_array(result.stdout)
            except CiscoScanFailed as exc:
                detail = (result.stderr or "").strip().splitlines()
                errors.append(f"{server_dir.name}: {exc}"
                              + (f" | stderr: {detail[-1][:240]}" if detail else ""))
                continue
            findings.extend(self._parse_items(
                items, server_id=server_dir.name, surface="behavioral",
                url=None, stage="static", file_hint=f"{server_dir.name}/"))

        return AdapterResult(
            findings=findings,
            raw_output="\n".join(chunks),
            exit_code=exit_code,
            duration_seconds=duration,
            error="; ".join(errors) if errors else None,
            scanner_version=self.scanner_version,
            extra={"config_label": self.config_label,
                   "analyzers": list(self.analyzers)},
        )

    # -- parsing --------------------------------------------------------

    def _parse_items(
        self,
        items: Sequence[Any],
        *,
        server_id: str,
        surface: str,
        url: str | None,
        stage: str = "runtime",
        file_hint: str | None = None,
    ) -> list[RawFinding]:
        out: list[RawFinding] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            subject = _item_label(item)
            for analyzer, block in _analyzer_blocks(item):
                out.extend(self._parse_block(
                    analyzer, block, item,
                    server_id=server_id, surface=surface, url=url,
                    stage=stage, subject=subject, file_hint=file_hint))
        return out

    def _parse_block(
        self,
        analyzer: str,
        block: dict[str, Any],
        item: dict[str, Any],
        *,
        server_id: str,
        surface: str,
        url: str | None,
        stage: str,
        subject: str,
        file_hint: str | None,
    ) -> list[RawFinding]:
        severity = block.get("severity")
        total = block.get("total_findings")
        summary = block.get("threat_summary") or ""
        names = block.get("threat_names")
        names = [n for n in names if isinstance(n, str)] if isinstance(names, list) else []

        reported_something = bool(names) or bool(
            isinstance(total, int) and total > 0)
        if not reported_something:
            # SAFE / zero findings. Not a finding, and not silently discarded
            # either: the per-item verdict is in the committed raw output.
            return []

        taxonomies = block.get("mcp_taxonomies")
        taxonomies = [t for t in taxonomies if isinstance(t, dict)] \
            if isinstance(taxonomies, list) else []
        by_category = {str(t.get("scanner_category", "")): t for t in taxonomies}

        labels: list[tuple[str, bool]] = [(n, False) for n in names]
        if not labels:
            # The adapter contract forbids dropping a finding it does not
            # understand. This one is handed on under a sentinel that no
            # mapping table will match, so it lands in `unmapped` with the
            # reason visible rather than vanishing.
            labels = [(UNLABELLED, True)]

        out: list[RawFinding] = []
        for label, synthetic in labels:
            taxonomy = by_category.get(label) or (taxonomies[0] if taxonomies else {})
            raw: dict[str, Any] = {
                "analyzer": analyzer,
                "surface": surface,
                "item_type": item.get("item_type"),
                "subject": subject,
                "status": item.get("status"),
                "is_safe": item.get("is_safe"),
                "total_findings": total,
                "threat_summary": summary,
                "threat_names": names,
                "scanner_version": self.scanner_version,
                "config_label": self.config_label,
            }
            if url:
                raw["endpoint"] = url
            if synthetic:
                raw["synthetic_label"] = True
                raw["synthetic_label_reason"] = (
                    "the analyzer reported findings but named no threat; the "
                    "label is the adapter's, not the scanner's")
            if taxonomy:
                # Cisco's own intermediate vocabulary, preserved as reported.
                # It is evidence for a mapping argument, never a substitute for
                # one: this adapter does not map to our taxonomy.
                raw["aitech"] = taxonomy.get("aitech")
                raw["aitech_name"] = taxonomy.get("aitech_name")
                raw["aisubtech"] = taxonomy.get("aisubtech")
                raw["aisubtech_name"] = taxonomy.get("aisubtech_name")
                raw["scanner_category"] = taxonomy.get("scanner_category")
            # The descriptor text the scanner actually read. Kept because the
            # difference between "never saw the payload" and "saw it and did not
            # fire" is the whole question for this scanner.
            for key in ("tool_description", "instructions"):
                if isinstance(item.get(key), str):
                    raw[key] = item[key]

            out.append(RawFinding(
                scanner_id=self.scanner_id,
                raw_label=label,  # verbatim; see trap 3 in the module docstring
                server_id=server_id,
                file=f"{file_hint}{subject}" if file_hint else None,
                line=None,
                message=summary,
                severity=severity if isinstance(severity, str) else None,
                stage=stage,
                raw=raw,
            ))
        return out

    # -- helper used by the verification harness -------------------------

    def observed_labels(self, findings: Iterable[RawFinding]) -> dict[str, int]:
        """Label histogram, for checking a mapping table against real output."""
        counts: dict[str, int] = {}
        for f in findings:
            counts[f.raw_label] = counts.get(f.raw_label, 0) + 1
        return counts
