"""Execution orchestration: run an adapter N times and collect raw findings.

Separate from scoring on purpose. This module knows how to invoke scanners and
nothing about whether their output is right; scoring knows the credit rules and
nothing about how a scanner was invoked. Keeping the seam there is what lets the
credit rules be tested against synthetic adapters.

Two rules here carry policy rather than convenience:

  * A scanner that cannot run still produces a row, carrying the reason. The
    alternative -- omitting it -- would silently turn "we could not run this"
    into "this tool was not considered", which is not a neutral act.

  * A stage an adapter does not attempt is recorded as not attempted, never as
    a run that found nothing. docs/scoring.md is explicit that scoring a static
    tool as 0% runtime recall is a category error presented as a measurement.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from .adapters import Adapter, AdapterResult, RuntimeTarget, StaticTarget
from .corpus import Corpus
from .models import ScannerRun

DEFAULT_RUNS = 5  # docs/scoring.md: N >= 5, mean and range, never a single run.


@dataclass
class ExecutionPlan:
    corpus: Corpus
    runs: int = DEFAULT_RUNS
    stages: frozenset[str] = frozenset({"static", "runtime"})
    lab_host: str = "127.0.0.1"
    lab_token: str = "lab-token-do-not-reuse"
    raw_dir: Path | None = None


@dataclass
class ExecutionOutcome:
    """Everything one scanner produced, plus why it did not produce more."""

    scanner_id: str
    display_name: str
    scanner_version: str
    adapter_version: str
    config_label: str
    requires_signup: bool
    stages_attempted: list[str]
    runs: list[ScannerRun] = field(default_factory=list)
    unavailable_reason: str | None = None
    notes: list[str] = field(default_factory=list)


def static_target(corpus: Corpus, scope: str = "corpus") -> StaticTarget:
    dirs = tuple(sorted(s.path for s in corpus.servers.values()))
    root = dirs[0].parent if dirs else Path("corpus")
    return StaticTarget(corpus_dir=root, server_dirs=dirs, scope=scope)


def runtime_targets(corpus: Corpus, plan: ExecutionPlan) -> list[RuntimeTarget]:
    out = []
    for s in sorted(corpus.servers.values(), key=lambda x: x.server_id):
        if s.transport != "http":
            continue
        out.append(RuntimeTarget(
            server_id=s.server_id,
            url=f"http://{plan.lab_host}:{s.port}/mcp",
            token=plan.lab_token if s.authenticated else None,
            authenticated=s.authenticated,
            sensitive_tools=tuple(s.sensitive_tools),
        ))
    return out


def _persist(plan: ExecutionPlan, adapter: Adapter, stage: str, idx: int,
             result: AdapterResult) -> None:
    """Keep every scanner's raw output.

    docs/governance.md commits to publishing this so anyone can check our
    arithmetic and our mappings without rerunning anything.
    """
    if not plan.raw_dir or not result.raw_output:
        return
    d = plan.raw_dir / adapter.scanner_id / adapter.config_label
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{stage}-run{idx}.txt").write_text(result.raw_output)


def execute(adapter: Adapter, plan: ExecutionPlan) -> ExecutionOutcome:
    """Run one adapter across every stage it attempts, `plan.runs` times each."""
    available, reason = adapter.available()
    attempted = sorted(set(adapter.stages) & set(plan.stages))

    outcome = ExecutionOutcome(
        scanner_id=adapter.scanner_id,
        display_name=getattr(adapter, "display_name", adapter.scanner_id),
        scanner_version="unknown",
        adapter_version=adapter.adapter_version,
        config_label=adapter.config_label,
        requires_signup=adapter.requires_signup,
        stages_attempted=attempted,
    )

    if not available:
        outcome.unavailable_reason = reason
        outcome.notes.append(
            "Published with no scores. A scanner we could not run is reported "
            "as such rather than omitted.")
        return outcome

    skipped = sorted(set(plan.stages) - set(adapter.stages))
    if skipped:
        outcome.notes.append(
            f"Does not attempt {', '.join(skipped)}; those items are excluded "
            f"from its denominator rather than counted as misses.")

    for stage in attempted:
        for idx in range(1, plan.runs + 1):
            started = time.monotonic()
            try:
                if stage == "static":
                    result = adapter.run_static(static_target(plan.corpus))
                else:
                    result = _run_runtime_stage(adapter, plan)
            except Exception as exc:  # an adapter crash is data, not a stop
                result = AdapterResult(
                    findings=[], exit_code=None,
                    error=f"{type(exc).__name__}: {exc}")

            elapsed = result.duration_seconds
            if elapsed is None:
                elapsed = time.monotonic() - started

            if result.scanner_version and result.scanner_version != "unknown":
                outcome.scanner_version = result.scanner_version

            _persist(plan, adapter, stage, idx, result)
            outcome.runs.append(ScannerRun(
                scanner_id=adapter.scanner_id,
                scanner_version=outcome.scanner_version,
                adapter_version=adapter.adapter_version,
                config_label=adapter.config_label,
                stage=stage,
                run_index=idx,
                corpus_version=plan.corpus.version,
                requires_signup=adapter.requires_signup,
                findings=list(result.findings),
                duration_seconds=elapsed,
                exit_code=result.exit_code,
                error=result.error,
            ))

    return outcome


def _run_runtime_stage(adapter: Adapter, plan: ExecutionPlan) -> AdapterResult:
    """Exercise every live server, folding the results into one run.

    A runtime scan is per-endpoint, but a run is the unit scoring counts, so the
    per-server results are combined here rather than in the adapter.
    """
    findings = []
    chunks: list[str] = []
    errors: list[str] = []
    version = "unknown"

    for target in runtime_targets(plan.corpus, plan):
        try:
            r = adapter.run_runtime(target)
        except Exception as exc:
            errors.append(f"{target.server_id}: {type(exc).__name__}: {exc}")
            continue
        findings.extend(r.findings)
        if r.raw_output:
            chunks.append(f"===== {target.server_id} =====\n{r.raw_output}")
        if r.error:
            errors.append(f"{target.server_id}: {r.error}")
        if r.scanner_version and r.scanner_version != "unknown":
            version = r.scanner_version

    return AdapterResult(
        findings=findings,
        raw_output="\n".join(chunks),
        error="; ".join(errors) if errors else None,
        scanner_version=version,
    )
