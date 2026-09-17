"""One command, one scoreboard.

    python -m runner.cli --scanners fixtures --runs 5

docs/project-plan.md fixes the bar for Phase 2: "one command produces a
reproducible scoreboard from a clean checkout." This is that command.

The pipeline is assembled here and nowhere else. Each stage is a module that
knows nothing about the ones on either side of it, which is what lets the
credit rules be tested against synthetic adapters and the renderer against
hand-built reports.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .adapters.fixtures import identity_map
from .adapters.fixtures.foreign_taxonomy import ForeignTaxonomyAdapter
from .adapters.fixtures.near_miss import NearMissAdapter
from .adapters.fixtures.oracle import OracleAdapter
from .adapters.fixtures.overflagger import OverflaggerAdapter
from .adapters.fixtures.static_only import StaticOnlyAdapter
from .adapters.cisco_mcp_scanner import CiscoMcpScannerAdapter
from .adapters.mcp_guard import McpGuardAdapter
from .adapters.ramparts import RampartsAdapter
from .aggregate import aggregate
from .corpus import load_corpus
from .execute import DEFAULT_RUNS, ExecutionPlan, execute
from .mapping import Mapper, ServerResolver, load_mapping_dir
from .models import ScannerReport
from .report import render_markdown, render_text
from .results import build_results, validate_results, write_results
from .scoring import score_run

ROOT = Path(__file__).resolve().parent.parent

FIXTURES = [OracleAdapter, OverflaggerAdapter, StaticOnlyAdapter,
            ForeignTaxonomyAdapter, NearMissAdapter]

#: Real adapters, in the order docs/project-plan.md records. A scanner we cannot
#: run is still listed and still publishes a row carrying its reason, because
#: governance.md requires that rather than a quiet omission.
REAL_ADAPTERS: list = [CiscoMcpScannerAdapter, McpGuardAdapter, RampartsAdapter]


def _adapters(selection: str) -> list:
    if selection == "fixtures":
        return [cls() for cls in FIXTURES]
    if selection == "real":
        return [cls() for cls in REAL_ADAPTERS]
    if selection == "all":
        return [cls() for cls in FIXTURES + REAL_ADAPTERS]
    wanted = {s.strip() for s in selection.split(",") if s.strip()}
    chosen = [cls() for cls in FIXTURES + REAL_ADAPTERS
              if cls().scanner_id in wanted]
    if not chosen:
        raise SystemExit(f"no adapter matched {selection!r}")
    return chosen


def _map_findings(adapter, findings, corpus, stage, mapper):
    """Fixtures speak our taxonomy already; real scanners go through mapping.

    The split is explicit rather than a fallback so that a real adapter can
    never silently get the identity treatment, which would hand it a perfect
    mapping it did not earn.
    """
    if adapter.scanner_id.startswith("fixture-"):
        return identity_map(findings)
    if mapper is None:
        raise SystemExit(
            f"{adapter.scanner_id}: no mapping files loaded. A real scanner "
            f"without a mapping table would score 0% for reasons that are ours, "
            f"not its own.")
    return mapper.map_findings(findings, stage=stage).mapped


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="runner", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scanners", default="fixtures",
                    help="'fixtures', 'real', 'all', or a comma-separated list of scanner ids")
    ap.add_argument("--runs", type=int, default=DEFAULT_RUNS,
                    help=f"runs per scanner (default {DEFAULT_RUNS}; docs/scoring.md requires >= 5)")
    ap.add_argument("--stages", default="static,runtime")
    # Defaults to a scratch path that is gitignored. A publishing run targets
    # results/ explicitly, so a fixture run can never be mistaken for a
    # published score, and published raw output is committed deliberately
    # rather than by accident.
    ap.add_argument("--out", default=str(ROOT / "results" / "local"))
    ap.add_argument("--detail", action="store_true", help="also print per-class recall")
    ap.add_argument("--lab-host", default="127.0.0.1")
    ap.add_argument("--lab-token", default="lab-token-do-not-reuse")
    ap.add_argument("--no-reset", action="store_true",
                    help="do not restart the corpus between runtime runs; runs "
                         "then share state and the spread is not attributable "
                         "to the scanner")
    args = ap.parse_args(argv)

    corpus = load_corpus()
    stages = frozenset(s.strip() for s in args.stages.split(",") if s.strip())
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.runs < 5:
        print(f"note: --runs {args.runs} is below the minimum of 5 in "
              f"docs/scoring.md; results are not publishable\n", file=sys.stderr)

    try:
        registry = load_mapping_dir()
        mapper = Mapper(registry, ServerResolver.from_corpus(corpus))
    except Exception as exc:
        registry, mapper = None, None
        print(f"note: no mapping tables loaded ({type(exc).__name__}); "
              f"fixtures will still run\n", file=sys.stderr)

    plan = ExecutionPlan(corpus=corpus, runs=args.runs, stages=stages,
                         lab_host=args.lab_host, lab_token=args.lab_token,
                         raw_dir=out_dir / "raw",
                         reset_between_runs=not args.no_reset)

    reports: list[ScannerReport] = []
    per_items: dict[str, list] = {}
    per_findings: dict[str, list] = {}

    for adapter in _adapters(args.scanners):
        outcome = execute(adapter, plan)

        if outcome.unavailable_reason:
            reports.append(ScannerReport(
                scanner_id=outcome.scanner_id, scanner_version=outcome.scanner_version,
                adapter_version=outcome.adapter_version, config_label=outcome.config_label,
                corpus_version=corpus.version, requires_signup=outcome.requires_signup,
                stages_attempted=[], runs=0,
                recall_per_class_mean={}, recall_per_class_range={},
                recall_overall_mean=None, recall_overall_range=None,
                precision_mean=None, precision_range=None,
                near_miss_mean=0.0, unmapped_mean=0.0, high_variance=False,
                display_name=outcome.display_name, notes=list(outcome.notes),
                unavailable_reason=outcome.unavailable_reason))
            continue

        # A run is one pass across every stage the scanner attempts, so the
        # per-stage executions at the same index are folded together before
        # scoring rather than being scored as separate runs.
        by_index: dict[int, list] = defaultdict(list)
        for run in outcome.runs:
            mapped = _map_findings(adapter, run.findings, corpus, run.stage, mapper)
            by_index[run.run_index].extend(mapped)

        metrics_per_run = []
        items_acc, findings_acc = [], []
        for idx in sorted(by_index):
            mapped = by_index[idx]
            outcomes, metrics = score_run(corpus, mapped, outcome.stages_attempted)
            metrics_per_run.append(metrics)
            items_acc.extend((idx, o) for o in outcomes)
            findings_acc.extend((idx, m) for m in mapped)

        if not metrics_per_run:
            continue

        report = aggregate(
            metrics_per_run, scanner_id=outcome.scanner_id,
            scanner_version=outcome.scanner_version,
            adapter_version=outcome.adapter_version,
            config_label=outcome.config_label, corpus_version=corpus.version,
            requires_signup=outcome.requires_signup,
            stages_attempted=outcome.stages_attempted, notes=outcome.notes)
        report.display_name = outcome.display_name
        reports.append(report)
        per_items[outcome.scanner_id] = items_acc
        per_findings[outcome.scanner_id] = findings_acc

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    doc = build_results(reports, corpus.version, generated_at, args.runs,
                        per_scanner_items=per_items,
                        per_scanner_findings=per_findings)
    problems = validate_results(doc)
    if problems:
        print("results document failed validation:", file=sys.stderr)
        for p in problems[:20]:
            print(f"  - {p}", file=sys.stderr)
        return 1

    json_path = out_dir / "results.json"
    md_path = out_dir / "scoreboard.md"
    write_results(doc, json_path)
    md_path.write_text(render_markdown(reports, corpus.version, generated_at,
                                       detail=True))

    print(render_text(reports, corpus.version, generated_at, detail=args.detail))
    print(f"\nresults: {json_path.relative_to(ROOT)}")
    print(f"scoreboard: {md_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
