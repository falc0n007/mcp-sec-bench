"""mcp-guard adapter -- SaravanaGuhan/mcp-guard 2.0.0, MIT.

The first real adapter in this benchmark. mcp-guard was chosen first because it
takes a **source directory**, which is the corpus's native shape, needs no
credentials, and runs fully offline, so it exercises the whole pipeline --
container harness, parsing, mapping layer, credit rules, precision accounting
-- end to end.

Which tool this is
------------------
"mcp-guard" is a squatted name: at least four unrelated projects use it
(docs/scanner-survey.md section 4). This adapter runs
``github.com/SaravanaGuhan/mcp-guard`` and nothing else, pinned to a commit SHA
in ``dockerfiles/mcp-guard.Dockerfile`` because the project is not on PyPI and a
floating ``main`` would mean a published score could not be reproduced.

Static only, and why
--------------------
``stages = {"static"}``. mcp-guard ships a dynamic stage (the ``MCPG-DYN-*``
rule family) behind ``--allow-execute``, and we do not run it. The reason is
structural, not a shortcut: the dynamic stage derives a **stdio** launch command
for the target and speaks JSON-RPC over that pipe. Every server in this corpus
is an **HTTP** server on a declared port. There is no path by which the
``MCPG-DYN-*`` rules can fire against what we have, so running the stage would
produce a guaranteed-empty result that reads on a scoreboard like a tool that
looked and found nothing. Declaring static-only says the true thing instead.

Being static-only is **not a penalty here**. docs/scoring.md excludes a stage a
scanner does not attempt from its denominator, so the runtime classes (A4, A5,
A6) are marked ``not_attempted`` rather than counted as misses. The four classes
mcp-guard's static rules could plausibly reach -- A7, A8, A9, A10 -- are all
static-surface classes in docs/taxonomy.md.

If a future corpus revision adds a stdio-transport server, or if the runner
grows a stdio shim in front of the HTTP servers, this decision should be
revisited and the adapter_version bumped: the mapping table already carries the
``MCPG-DYN-*`` labels so that the day they can fire, they are not silently
dropped.

Scope: whole corpus in one invocation
-------------------------------------
``run_static`` points mcp-guard at the corpus root, not at each server in turn.
Three reasons, in order of weight:

  1. docs/taxonomy.md is explicit that a scanner given one server at a time
     "structurally cannot detect A3", and that this is a fact about the scanner
     only if the harness did not impose it. Whole-corpus scope is the
     configuration that gives the tool its best honest shot.
  2. mcp-guard reports ``evidence.file`` relative to the target root. Scanning
     the corpus root makes every path carry its server directory as a component,
     so server attribution comes from the scanner's own output rather than from
     us knowing which directory we handed it.
  3. It is one container start instead of fifteen.

Verified equivalent: per-server and whole-corpus invocations produce byte-identical
finding sets on corpus v1 (8 findings, same rules, same files, same lines).

A finding whose path matches no corpus directory keeps ``server_id = None``.
Guessing a server would manufacture true positives, so the adapter does not.

Two further behaviours this adapter has to absorb
-------------------------------------------------
  * **Non-zero exit is normal.** mcp-guard exits 1 whenever it reports a finding
    at or above its ``--fail-on`` threshold. Treating that as a crash would turn
    every productive scan into an unavailable row.
  * **``is_mcp_server: false`` on every corpus server.** Its ``detect`` stage
    looks for ``package.json`` / ``pyproject.toml`` / ``requirements.txt`` /
    ``go.mod`` / ``Dockerfile``, and our per-server directories deliberately
    carry none. The static stage runs anyway and finds the flaws, so this is
    cosmetic -- but an adapter that gated on ``is_mcp_server`` would score the
    tool zero for a reason that has nothing to do with its detection. We record
    the flag in ``extra`` and act on nothing.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..models import RawFinding
from . import AdapterResult, RuntimeTarget, StaticTarget
from .container import (
    CORPUS_MOUNTPOINT,
    ContainerSpec,
    corpus_mount,
    docker_available,
    image_present,
    run_container,
)

#: Built from dockerfiles/mcp-guard.Dockerfile. The tag names the scanner
#: version so two scanner versions cannot share an image and be confused for
#: each other on the scoreboard.
IMAGE = "mcp-sec-bench/mcp-guard:2.0.0"

SCANNER_VERSION = "2.0.0"

#: The exact commit this adapter's Dockerfile pins. Published with the row.
PINNED_REF = "e782de38d98219047c4dab3232395d8636c678c3"

BUILD_HINT = (
    "docker build -f runner/adapters/dockerfiles/mcp-guard.Dockerfile "
    f"-t {IMAGE} runner/adapters/dockerfiles"
)

#: --offline is what makes the run credential-free and reproducible: it disables
#: the OSV dependency lookup, the tool's only network call. --no-cache stops a
#: previous run's static cache from changing this one's result. --quiet keeps
#: progress on stderr off stdout, which must be parseable JSON.
SCAN_FLAGS = ("--no-cache", "--offline", "--quiet", "--format", "json")

DEFAULT_TIMEOUT = 900


def _extract_json(text: str) -> dict[str, Any] | None:
    """Pull the report object out of stdout.

    ``--quiet`` should leave stdout as nothing but the report, but a scanner's
    output discipline is not something to rely on: a stray banner line would
    otherwise turn a good scan into an unavailable row. So try the whole string
    first, then the substring from the first brace.
    """
    text = text.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, ValueError):
        pass

    start = text.find("{")
    if start == -1:
        return None
    decoder = json.JSONDecoder()
    try:
        parsed, _ = decoder.raw_decode(text[start:])
    except (json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()):
        return int(value)
    return None


@dataclass
class McpGuardAdapter:
    """Runs mcp-guard's static stage over the corpus and parses its JSON report."""

    scanner_id: str = "mcp-guard"
    display_name: str = "mcp-guard (SaravanaGuhan/mcp-guard)"
    adapter_version: str = "1.0.0"
    stages: frozenset[str] = frozenset({"static"})
    requires_signup: bool = False
    config_label: str = "default"

    image: str = IMAGE
    timeout: int = DEFAULT_TIMEOUT
    notes: list[str] = field(default_factory=list)

    # -- protocol ---------------------------------------------------------

    def available(self) -> tuple[bool, str]:
        """Report why we cannot run, rather than raising.

        docs/governance.md: a scanner we could not run is published with its
        reason. That only works if this method never throws.
        """
        ok, reason = docker_available()
        if not ok:
            return False, f"{reason}; mcp-guard runs in a container"
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
        known = self._known_server_dirs(target)

        spec = ContainerSpec(
            image=self.image,
            args=[CORPUS_MOUNTPOINT, *SCAN_FLAGS],
            # mcp-guard writes nothing to the target, but the corpus is mounted
            # read-only regardless: a scanner that corrupted ground truth would
            # corrupt every later run invisibly. See container.py.
            mounts=[corpus_mount(target.corpus_dir)],
            # It never needs the network in this configuration, so it does not
            # get one. If --offline ever stops covering a call, the scan fails
            # loudly here instead of silently reaching the internet.
            network="none",
            workdir="/tmp",
            timeout=self.timeout,
        )

        run = run_container(spec)

        if run.error and run.exit_code is None:
            return AdapterResult(
                findings=[], raw_output=run.combined, exit_code=None,
                duration_seconds=run.duration_seconds,
                error=run.error, scanner_version=SCANNER_VERSION,
                extra={"image": self.image, "pinned_ref": PINNED_REF},
            )

        report = _extract_json(run.stdout)

        if report is None:
            detail = (run.stderr or run.stdout or "").strip()[:400]
            return AdapterResult(
                findings=[], raw_output=run.combined, exit_code=run.exit_code,
                duration_seconds=run.duration_seconds,
                error=(f"mcp-guard produced no parseable JSON report "
                       f"(exit {run.exit_code})"
                       + (f": {detail}" if detail else "")),
                scanner_version=SCANNER_VERSION,
                extra={"image": self.image, "pinned_ref": PINNED_REF},
            )

        findings, unresolved = self.parse_report(report, known)

        extra: dict[str, Any] = {
            "image": self.image,
            "pinned_ref": PINNED_REF,
            "scope": target.scope,
            "schema_version": report.get("schema_version"),
            "target": report.get("target"),
            "summary": report.get("summary"),
            "stages": report.get("stages"),
            # Recorded, never acted on. See the module docstring.
            "is_mcp_server": (report.get("server_info") or {}).get("is_mcp_server"),
            "detection_notes": (report.get("server_info") or {}).get("detection_notes"),
        }
        if unresolved:
            extra["unresolved_paths"] = sorted(unresolved)

        # A non-zero exit that produced a report is mcp-guard's --fail-on
        # threshold firing, i.e. the scanner working. It is not an error.
        error = None
        if run.exit_code not in (0, 1):
            error = (f"mcp-guard exited {run.exit_code}; a report was still "
                     f"parsed and its findings are included")

        return AdapterResult(
            findings=findings,
            raw_output=run.stdout if not run.stderr else run.combined,
            exit_code=run.exit_code,
            duration_seconds=run.duration_seconds,
            error=error,
            scanner_version=str(report.get("tool_version") or SCANNER_VERSION),
            extra=extra,
        )

    def run_runtime(self, target: RuntimeTarget) -> AdapterResult:
        raise NotImplementedError(
            "mcp-guard's dynamic stage speaks stdio and this corpus speaks HTTP; "
            "see the module docstring. The adapter declares stages={'static'} so "
            "the runner marks runtime items not_attempted rather than missed.")

    # -- parsing ----------------------------------------------------------

    def parse_report(
        self,
        report: dict[str, Any],
        known_servers: frozenset[str] | set[str] = frozenset(),
    ) -> tuple[list[RawFinding], set[str]]:
        """Turn one mcp-guard JSON report into RawFindings.

        Returns ``(findings, unresolved_paths)``. Every element of
        ``report["findings"]`` becomes exactly one RawFinding, including ones
        whose rule id this project has never seen: an unrecognised label becomes
        a finding and is scored ``unmapped``, which costs the scanner nothing
        and tells us our taxonomy has a gap. Dropping it would hide both.
        """
        raw_findings = report.get("findings")
        if not isinstance(raw_findings, list):
            return [], set()

        out: list[RawFinding] = []
        unresolved: set[str] = set()

        for index, item in enumerate(raw_findings):
            if not isinstance(item, dict):
                # Still not dropped: preserved with the label the schema
                # promised and the payload in `raw`.
                out.append(RawFinding(
                    scanner_id=self.scanner_id,
                    raw_label="",
                    message=f"malformed finding at index {index}",
                    stage="static",
                    raw={"malformed": True, "value": repr(item)[:500]},
                ))
                continue

            evidence = item.get("evidence")
            if not isinstance(evidence, dict):
                evidence = {}

            # raw_label is the rule id VERBATIM -- never normalised, never
            # re-cased. The mapping table is keyed on this exact string.
            label = item.get("rule_id")
            if label is None:
                label = evidence.get("rule_id")
            label = label if isinstance(label, str) else ""

            path = evidence.get("file")
            path = path if isinstance(path, str) and path else None

            server_id = self._server_for(path, known_servers)
            if path and server_id is None:
                unresolved.add(path)

            severity = item.get("severity")
            severity = severity if isinstance(severity, str) else None

            message = item.get("description") or item.get("title") or ""
            if not isinstance(message, str):
                message = str(message)

            raw: dict[str, Any] = {
                "rule_id": label,
                "title": item.get("title"),
                "cwe": item.get("cwe"),
                "cvss_vector": item.get("cvss_vector"),
                "cvss_score": item.get("cvss_score"),
                "remediation": item.get("remediation"),
                "references": item.get("references"),
                "aivss": item.get("aivss"),
                "evidence_kind": evidence.get("kind"),
                "evidence_column": evidence.get("column"),
                "matched_source": evidence.get("matched_source"),
                "reported_path": path,
            }
            if server_id is None and path:
                raw["server_unresolved"] = True

            out.append(RawFinding(
                scanner_id=self.scanner_id,
                raw_label=label,
                server_id=server_id,
                file=path,
                line=_as_int(evidence.get("line")),
                message=message,
                severity=severity,
                # Only the static stage is ever run in this configuration; the
                # evidence kind is preserved in `raw` so a future dynamic
                # configuration does not have to re-derive it.
                stage="static",
                raw=raw,
            ))

        return out, unresolved

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _known_server_dirs(target: StaticTarget) -> frozenset[str]:
        return frozenset(p.name for p in target.server_dirs)

    @staticmethod
    def _server_for(path: str | None,
                    known: frozenset[str] | set[str]) -> str | None:
        """Resolve a reported path to a corpus directory name, or to None.

        Mirrors runner.mapping.ServerResolver deliberately: a path belongs to a
        server exactly when one of its components is a known server directory.
        Two different servers in one path, or none, resolves to None. Nothing
        here falls back to "probably the server that has this class" -- that
        would invent true positives out of path parsing.
        """
        if not path or not known:
            return None
        parts = [p for p in path.replace("\\", "/").split("/")
                 if p not in ("", ".", "..")]
        hits = sorted({p for p in parts if p in known})
        if len(hits) != 1:
            return None
        return hits[0]


def build_command() -> list[str]:
    """The exact command that builds this adapter's image. Published with the row."""
    here = Path(__file__).resolve().parent
    return ["docker", "build", "-f",
            str(here / "dockerfiles" / "mcp-guard.Dockerfile"),
            "-t", IMAGE, str(here / "dockerfiles")]
