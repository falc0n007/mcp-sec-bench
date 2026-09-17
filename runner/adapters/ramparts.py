"""Adapter for Ramparts (highflame-ai/ramparts), an independent-vendor MCP
security scanner that scans a LIVE MCP URL.

Read docs/scanner-survey.md's Ramparts section before touching this file --
in particular **TRAP 1**, reproduced here because it is the single most
important fact this adapter has to defend against:

    `cargo install ramparts` does NOT ship its YARA rules. Without them the
    scanner's pattern engine runs with detection completely disabled and
    still exits 0 with a well-formed JSON payload reporting zero findings --
    a result that is visually indistinguishable from a genuine clean scan.
    The warning ramparts prints when this happens goes to stderr at `warn!`
    level only; it is NOT recorded in the JSON `errors[]` array. The LLM
    stage has the identical silent-skip shape when no LLM key is configured
    (verified against ramparts 0.8.8 source, see the loader in `src/scanner.rs`).

This adapter closes the trap two ways:

  1. The image built from `dockerfiles/ramparts.Dockerfile` bakes
     `rules/pre/*.yar` from the ramparts source tag matching the pinned
     crates.io version straight into the image and sets
     `RAMPARTS_RULES_DIR` as the image default. `run_runtime` sets the same
     env var again explicitly on every container invocation, so the check
     below is never depending on an image default nobody re-verifies.
  2. `run_runtime` parses ramparts' own JSON output for the
     `YARA_PRE_SCAN_SUMMARY` entry every `scan` run produces when (and only
     when) the pre-scan YARA middleware was actually registered, and refuses
     to return findings -- returns an `AdapterResult.error` instead -- if
     that entry is missing or reports zero compiled rule files. This check
     is unconditional: it runs before any finding is trusted, on every call,
     and is not behind a flag. See `_verify_rules_loaded` and
     `RampartsRulesNotLoaded`.

Everything ramparts reports through `yara_results` (and, defensively,
`security_issues.*_issues` from its LLM stage, in case a future run has an
LLM key configured) is preserved as a RawFinding with `raw_label` set to the
scanner's own rule identifier verbatim, per runner/adapters/__init__.py: this
adapter never maps to our taxonomy and never silently drops a finding it does
not understand.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..models import RawFinding
from . import AdapterResult, RuntimeTarget, StaticTarget
from .container import (
    ContainerSpec,
    docker_available,
    image_present,
    lab_url,
    run_container,
)

# --------------------------------------------------------------------------
# Pinned build identity. Must match runner/adapters/dockerfiles/ramparts.Dockerfile.
# --------------------------------------------------------------------------

#: crates.io release `cargo install ramparts` resolves to, and the version
#: string ramparts itself reports in ScanResult.ramparts_version.
RAMPARTS_VERSION = "0.8.8"

#: git tag whose rules/pre/*.yar are baked into the image. Verified
#: (docs/scanner-survey.md, 2026-09-17) that v0.8.8 and v0.8.9 point at the
#: identical commit -- same blob sha for every one of the 15 rule files --
#: so pinning to v0.8.8 here carries the same rules v0.8.9 would.
RAMPARTS_RULES_TAG = "v0.8.8"

IMAGE = f"mcp-sec-bench/ramparts:{RAMPARTS_VERSION}"

DOCKERFILE_PATH = Path(__file__).parent / "dockerfiles" / "ramparts.Dockerfile"

#: Where the image bakes the rules. Set again explicitly on every container
#: run (belt-and-suspenders with the image's own ENV default) so the guard
#: below is checking a value this adapter asserted, not one it hoped for.
RULES_DIR_IN_CONTAINER = "/opt/ramparts-rules"

DEFAULT_SCAN_TIMEOUT_SECS = 60
DEFAULT_HTTP_TIMEOUT_SECS = 20
DEFAULT_CONTAINER_TIMEOUT_SECS = 180

_PRE_SCAN_SUMMARY_RULE_NAME = "YARA_PRE_SCAN_SUMMARY"
_RULES_EXECUTED_RE = re.compile(r"(\d+)\s+rules executed")


class RampartsRulesNotLoaded(RuntimeError):
    """Raised internally when ramparts' YARA pattern engine did not load any
    rules for this run.

    This is the guard against TRAP 1 (see module docstring). It exists as its
    own exception, checked unconditionally at one call site in
    `run_runtime`, specifically so nobody can "temporarily" comment out a
    stray `if` and quietly let an empty-rules scan report as a clean pass --
    removing the guard means deleting or catching this exception, which is a
    visible, reviewable change rather than a one-line accident.
    """


@dataclass
class _RulesLoadedCheck:
    loaded: bool
    rule_files_loaded: int | None
    summary_context: str | None
    reason: str


def _verify_rules_loaded(payload: dict[str, Any]) -> _RulesLoadedCheck:
    """Inspect a parsed ramparts JSON scan result for proof that the YARA
    pre-scan middleware actually ran with a non-empty rule set.

    Ramparts only ever appends a `YARA_PRE_SCAN_SUMMARY` entry to
    `yara_results` from the branch that runs when the pre-scan YaraScanner
    was constructed successfully (see `analyze_pre_scan` / `ScanPhase::PreScan`
    in ramparts' `src/scanner.rs` 0.8.8). If `resolve_rules_dir()` found
    nothing, that branch of the middleware chain is never registered at all,
    so the summary entry is simply absent -- not present-with-zero. If a
    directory was found but happened to compile zero rules, the entry IS
    present but its `context` reads "0 rules executed on N items". Both are
    treated as detection-disabled; only a summary entry reporting a positive
    file count counts as proof rules loaded.
    """
    yara_results = payload.get("yara_results")
    if not isinstance(yara_results, list):
        return _RulesLoadedCheck(
            False, None, None,
            "ramparts JSON output has no 'yara_results' array at all -- "
            "cannot confirm the YARA pre-scan even ran.",
        )

    summary = next(
        (r for r in yara_results
         if isinstance(r, dict) and r.get("rule_name") == _PRE_SCAN_SUMMARY_RULE_NAME),
        None,
    )
    if summary is None:
        return _RulesLoadedCheck(
            False, None, None,
            f"no '{_PRE_SCAN_SUMMARY_RULE_NAME}' entry in yara_results. Ramparts only "
            "emits this entry when the pre-scan YARA middleware was registered, which "
            "only happens when resolve_rules_dir() found a directory containing a "
            "'pre' subdirectory. Its absence means RAMPARTS_RULES_DIR (or any of "
            "ramparts' other search locations) did not resolve to a rules directory "
            "for this run -- pattern-based detection was disabled for the whole scan.",
        )

    context = summary.get("context", "") or ""
    m = _RULES_EXECUTED_RE.search(context)
    rule_files_loaded = int(m.group(1)) if m else None

    if rule_files_loaded is None:
        return _RulesLoadedCheck(
            False, None, context,
            f"'{_PRE_SCAN_SUMMARY_RULE_NAME}' entry present but its context "
            f"({context!r}) did not match the expected 'N rules executed on M items' "
            "shape -- cannot confirm a positive rule count, so this run is not "
            "trusted as having rules loaded.",
        )

    if rule_files_loaded <= 0:
        return _RulesLoadedCheck(
            False, rule_files_loaded, context,
            f"'{_PRE_SCAN_SUMMARY_RULE_NAME}' reports {rule_files_loaded} rule files "
            "executed. The rules directory was found but compiled zero rules -- "
            "pattern-based detection was effectively disabled for this scan.",
        )

    return _RulesLoadedCheck(True, rule_files_loaded, context, "rules loaded")


def _parse_auth_header_arg(target: RuntimeTarget) -> list[str]:
    """`--auth-headers` args for authenticated servers; empty for the two
    lab servers that take no auth (a06-authless-endpoint / c04-status-service).
    Deciding this from `target.authenticated` rather than "token is truthy"
    means an adapter bug that drops the token on an authenticated target
    fails loudly (ramparts gets a 401 and reports it) instead of silently
    scanning unauthenticated and looking like a clean run.
    """
    if not target.authenticated:
        return []
    if not target.token:
        raise ValueError(
            f"RuntimeTarget for {target.server_id!r} is marked authenticated=True "
            "but carries no token -- refusing to scan unauthenticated by accident."
        )
    return ["--auth-headers", f"Authorization: Bearer {target.token}"]


def _extract_status(payload: dict[str, Any]) -> tuple[str, str | None]:
    """ramparts' `ScanStatus` is a Rust enum: the `Success` unit variant
    serializes as the bare string "Success"; the other variants
    (`Failed`, `Timeout`, `ConnectionError`, `AuthenticationError`) carry a
    message and serialize as a single-key object, e.g. {"ConnectionError": "..."}.
    """
    status = payload.get("status")
    if isinstance(status, str):
        return status, None
    if isinstance(status, dict) and status:
        name, detail = next(iter(status.items()))
        return name, str(detail)
    return "Unknown", None


def _findings_from_yara_results(
    yara_results: list[Any], server_id: str
) -> list[RawFinding]:
    findings: list[RawFinding] = []
    for entry in yara_results:
        if not isinstance(entry, dict):
            continue
        rule_name = entry.get("rule_name")
        if rule_name is None:
            continue
        # The pre/post-scan summary rows are metadata about the run, not a
        # security finding -- they are consumed by _verify_rules_loaded and
        # recorded in AdapterResult.extra, never turned into a RawFinding.
        if rule_name in (_PRE_SCAN_SUMMARY_RULE_NAME, "YARA_POST_SCAN_SUMMARY"):
            continue
        rule_metadata = entry.get("rule_metadata") or {}
        findings.append(
            RawFinding(
                scanner_id="ramparts",
                raw_label=rule_name,  # verbatim, e.g. "PromptInjectionSignature"
                server_id=server_id,
                message=entry.get("context", "") or "",
                severity=rule_metadata.get("severity"),
                stage="runtime",
                raw=entry,
            )
        )
    return findings


def _findings_from_security_issues(
    security_issues: dict[str, Any] | None, server_id: str
) -> list[RawFinding]:
    """Defensive parsing of ramparts' LLM-analyzer output.

    TRAP 1's second half: the LLM stage skips silently (no warning, no
    `errors[]` entry) when no LLM provider is configured, which is the only
    configuration this adapter runs -- so in every run we actually produce,
    these arrays are expected to be empty. They are still parsed rather than
    ignored, per the adapter contract (never silently drop a finding this
    adapter doesn't understand): if a future run does have an LLM key wired
    in and this stage produces output, it is captured rather than lost.
    """
    if not security_issues:
        return []
    findings: list[RawFinding] = []
    for bucket, target_field in (
        ("tool_issues", "tool_name"),
        ("prompt_issues", "prompt_name"),
        ("resource_issues", "resource_uri"),
    ):
        for entry in security_issues.get(bucket, None) or []:
            if not isinstance(entry, dict):
                continue
            issue_type = entry.get("issue_type")
            if issue_type is None:
                continue
            findings.append(
                RawFinding(
                    scanner_id="ramparts",
                    raw_label=(
                        issue_type if isinstance(issue_type, str)
                        else json.dumps(issue_type, sort_keys=True)
                    ),
                    server_id=server_id,
                    message=entry.get("message", "") or entry.get("description", "") or "",
                    severity=entry.get("severity"),
                    stage="runtime",
                    raw=entry,
                )
            )
    return findings


class RampartsAdapter:
    """Adapter for Ramparts 0.8.8, scanning a live MCP endpoint over HTTP."""

    scanner_id = "ramparts"
    display_name = "Ramparts"
    adapter_version = "1.0.0"
    stages = frozenset({"runtime"})
    requires_signup = False
    config_label = "default"

    def __init__(
        self,
        image: str = IMAGE,
        scan_timeout: int = DEFAULT_SCAN_TIMEOUT_SECS,
        http_timeout: int = DEFAULT_HTTP_TIMEOUT_SECS,
        container_timeout: int = DEFAULT_CONTAINER_TIMEOUT_SECS,
    ) -> None:
        self.image = image
        self.scan_timeout = scan_timeout
        self.http_timeout = http_timeout
        self.container_timeout = container_timeout

    # -- Adapter protocol ---------------------------------------------

    def available(self) -> tuple[bool, str]:
        ok, reason = docker_available()
        if not ok:
            return False, f"docker unavailable: {reason}"
        if not image_present(self.image):
            return False, (
                f"image {self.image} is not built. Build it with: "
                f"docker build -f {DOCKERFILE_PATH} -t {self.image} ."
            )
        return True, ""

    def run_static(self, target: StaticTarget) -> AdapterResult:
        raise NotImplementedError(
            "RampartsAdapter declares stages={'runtime'} only -- ramparts' primary "
            "input is a live MCP URL (see docs/scanner-survey.md). It does have a "
            "`scan-config` / `skills scan` static-ish surface, but this adapter does "
            "not exercise it; do not call run_static on this adapter."
        )

    def run_runtime(self, target: RuntimeTarget) -> AdapterResult:
        ok, reason = self.available()
        if not ok:
            return AdapterResult(findings=[], error=reason)

        try:
            auth_args = _parse_auth_header_arg(target)
        except ValueError as exc:
            return AdapterResult(findings=[], error=str(exc))

        args = [
            "scan",
            target.url,
            "--format", "json",
            "--timeout", str(self.scan_timeout),
            "--http-timeout", str(self.http_timeout),
            *auth_args,
        ]

        spec = ContainerSpec(
            image=self.image,
            args=args,
            env={
                # Explicit, on top of the image's own default -- see module
                # docstring. This is the env var ramparts' resolve_rules_dir()
                # checks first, ahead of every other search location.
                "RAMPARTS_RULES_DIR": RULES_DIR_IN_CONTAINER,
            },
            needs_lab=True,
            timeout=self.container_timeout,
        )

        result = run_container(spec)

        if result.error is not None and not result.stdout.strip():
            # Docker-level failure (daemon down, image gone, timeout) with no
            # output to parse at all.
            return AdapterResult(
                findings=[],
                raw_output=result.combined,
                exit_code=result.exit_code,
                duration_seconds=result.duration_seconds,
                error=result.error,
            )

        stdout = result.stdout.strip()
        if not stdout:
            return AdapterResult(
                findings=[],
                raw_output=result.combined,
                exit_code=result.exit_code,
                duration_seconds=result.duration_seconds,
                error=(
                    "ramparts produced no stdout output "
                    f"(exit_code={result.exit_code}). stderr: {result.stderr[:2000]}"
                ),
            )

        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            return AdapterResult(
                findings=[],
                raw_output=result.combined,
                exit_code=result.exit_code,
                duration_seconds=result.duration_seconds,
                error=f"could not parse ramparts JSON output: {exc}",
            )

        if not isinstance(payload, dict):
            return AdapterResult(
                findings=[],
                raw_output=result.combined,
                exit_code=result.exit_code,
                duration_seconds=result.duration_seconds,
                error=f"ramparts JSON output was a {type(payload).__name__}, expected an object",
            )

        scanner_version = payload.get("ramparts_version") or "unknown"
        commit = payload.get("ramparts_commit")
        if commit and commit != "unknown":
            scanner_version = f"{scanner_version}+{commit}"

        # -- The TRAP 1 guard. Unconditional; runs before any finding from
        # this payload is trusted, on every single call. --------------
        rules_check = _verify_rules_loaded(payload)
        extra: dict[str, Any] = {
            "rules_dir": RULES_DIR_IN_CONTAINER,
            "rules_tag": RAMPARTS_RULES_TAG,
            "ramparts_version_pinned": RAMPARTS_VERSION,
            "rules_loaded": rules_check.loaded,
            "rule_files_loaded": rules_check.rule_files_loaded,
            "pre_scan_summary_context": rules_check.summary_context,
            "server_id": target.server_id,
            "url": target.url,
            "authenticated": target.authenticated,
        }

        if not rules_check.loaded:
            note = RampartsRulesNotLoaded(rules_check.reason)
            return AdapterResult(
                findings=[],
                raw_output=result.combined,
                exit_code=result.exit_code,
                duration_seconds=result.duration_seconds,
                scanner_version=scanner_version,
                error=(
                    "REFUSING to report findings: ramparts' YARA pattern engine did not "
                    f"load any rules for this run. {rules_check.reason} Publishing an "
                    "empty finding list here would be indistinguishable from a genuine "
                    "clean scan and would be a false result about this vendor -- see "
                    "TRAP 1 in docs/scanner-survey.md. "
                    f"({type(note).__name__}: {note})"
                ),
                extra=extra,
            )

        status_name, status_detail = _extract_status(payload)
        errors_list = payload.get("errors") or []
        extra["ramparts_status"] = status_name
        extra["ramparts_status_detail"] = status_detail
        extra["ramparts_errors"] = errors_list

        findings = _findings_from_yara_results(
            payload.get("yara_results") or [], target.server_id
        )
        findings += _findings_from_security_issues(
            payload.get("security_issues"), target.server_id
        )

        adapter_error: str | None = None
        if status_name != "Success":
            # The scan ran and produced valid JSON with rules loaded, but
            # ramparts itself reports the connection/auth attempt failed.
            # Findings (if any survived) are still reported -- never dropped
            # -- but the run is flagged so this isn't mistaken for a clean
            # scan of a reachable server.
            adapter_error = (
                f"ramparts reported scan status {status_name!r}"
                + (f": {status_detail}" if status_detail else "")
            )
        elif result.exit_code not in (0, None):
            # Handle a non-zero exit that still produced a parseable,
            # rules-loaded result as success, per the adapter contract --
            # but note the discrepancy rather than hiding it.
            extra["nonzero_exit_with_valid_output"] = True

        return AdapterResult(
            findings=findings,
            raw_output=result.combined,
            exit_code=result.exit_code,
            duration_seconds=result.duration_seconds,
            error=adapter_error,
            scanner_version=scanner_version,
            extra=extra,
        )
