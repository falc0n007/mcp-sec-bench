"""Serialize the runner's in-memory results into the published JSON document,
and read that document back.

Input shapes come from runner/models.py (fixed, not owned by this module):
`ScannerReport` is the per-scanner aggregate across N runs; `ItemOutcome` and
`MappedFinding` are the per-run detail that ScannerReport itself does not
carry (it holds only mean/range). Callers that have that per-run detail pass
it in via `per_scanner_items` / `per_scanner_findings`, keyed by scanner_id,
as `(run_index, outcome_or_finding)` pairs -- the pairing is necessary because
neither ItemOutcome nor MappedFinding/RawFinding carries its own run_index.

The output shape is schema/results.schema.json. See docs/scoring.md's
"Results format" section for why each field exists, and runner/README.md's
"Reproducibility" section for why corpus_version / scanner_version /
adapter_version / config_label / mapping_rationale_id are load-bearing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import jsonschema

from runner.models import CLASS_STAGES, ItemOutcome, MappedFinding, Outcome, ScannerReport

SCHEMA_VERSION = "1.0"
_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema" / "results.schema.json"
_ROUND_NDIGITS = 4

ItemRun = tuple[int, ItemOutcome]
FindingRun = tuple[int, MappedFinding]


def _round(value: float | None) -> float | None:
    """Round to a fixed precision so results are stable across platforms.

    None is preserved as None (never coerced to 0.0) -- None and zero are
    different facts throughout this project (see docs/scoring.md), and
    conflating "no attempted item in this class" with "zero recall" would
    corrupt the published numbers.
    """
    if value is None:
        return None
    return round(float(value), _ROUND_NDIGITS)


def _range_obj(
    mean: float | None, rng: tuple[float, float] | None
) -> dict[str, float | None]:
    """Build the {mean, min, max} shape schema/results.schema.json requires.

    `rng` is the (min, max) tuple ScannerReport carries alongside a mean, or
    None when no range was computed. A None mean always means "nothing to
    report" (no attempted item / no runs), so min/max stay None too. A
    present mean with no range (e.g. a single run, where min == max == mean)
    falls back to (mean, mean) rather than null -- there being only one
    observation is not the same fact as the range being unknown.
    """
    if mean is None:
        return {"mean": None, "min": None, "max": None}
    lo, hi = rng if rng is not None else (mean, mean)
    return {"mean": _round(mean), "min": _round(lo), "max": _round(hi)}


def _outcome_value(outcome: Outcome | str) -> str:
    return outcome.value if isinstance(outcome, Outcome) else str(outcome)


def _item_to_dict(run_index: int, item: ItemOutcome) -> dict[str, Any]:
    return {
        "run_index": run_index,
        "server": item.server_id,
        "class": item.attack_class,
        "outcome": _outcome_value(item.outcome),
        "stage_credited": item.stage_credited,
        "finding_ref": item.finding_ref,
        "note": item.note or "",
    }


def _finding_to_dict(run_index: int, mapped: MappedFinding) -> dict[str, Any]:
    raw = mapped.finding
    return {
        "run_index": run_index,
        "raw_label": raw.raw_label,
        "mapped_class": mapped.mapped_class,
        "mapped_server": mapped.mapped_server,
        "mapping_rationale_id": mapped.mapping_rationale_id,
        "file": raw.file,
        "line": raw.line,
        "severity": raw.severity,
        "message": raw.message or "",
    }


def _not_attempted_classes(stages_attempted: Sequence[str]) -> list[str]:
    """Classes this scanner's attempted stages can never credit.

    Derived from CLASS_STAGES (docs/taxonomy.md, fixed in models.py) rather
    than from per-item data: a static-only scanner cannot credit A6 no
    matter what any individual item says, and this stays true across every
    run, so it belongs to the scanner-level aggregate rather than needing to
    be threaded through per-run items.
    """
    stages = set(stages_attempted)
    return sorted(cls for cls, required in CLASS_STAGES.items() if not (required & stages))


def _metrics_dict(report: ScannerReport) -> dict[str, Any]:
    recall_per_class: dict[str, Any] = {}
    for cls, mean in report.recall_per_class_mean.items():
        rng = report.recall_per_class_range.get(cls)
        recall_per_class[cls] = _range_obj(mean, rng)

    metrics: dict[str, Any] = {
        "recall_per_class": recall_per_class,
        "recall_overall": _range_obj(report.recall_overall_mean, report.recall_overall_range),
        "precision_overall": _range_obj(report.precision_mean, report.precision_range),
        "near_miss_mean": _round(report.near_miss_mean),
        "unmapped_mean": _round(report.unmapped_mean),
        "high_variance": bool(report.high_variance),
    }
    if report.variance_detail:
        metrics["variance_detail"] = {
            k: _round(v) for k, v in sorted(report.variance_detail.items())
        }
    return metrics


def build_results(
    reports: Sequence[ScannerReport],
    corpus_version: str,
    generated_at: str,
    runs_per_scanner: int,
    per_scanner_items: Mapping[str, Sequence[ItemRun]] | None = None,
    per_scanner_findings: Mapping[str, Sequence[FindingRun]] | None = None,
    unavailable_reasons: Mapping[str, str] | None = None,
    display_names: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Assemble the full results document matching schema/results.schema.json.

    `per_scanner_items` / `per_scanner_findings` map scanner_id to that
    scanner's per-run detail (see module docstring). `unavailable_reasons`
    and `display_names` map scanner_id to the optional per-scanner fields the
    schema allows but ScannerReport does not carry -- ScannerReport is the
    scoring pipeline's aggregate and has no notion of "could not run at all"
    or of a human-facing name, so a caller that knows those facts (e.g. the
    orchestrator that tried and failed to launch a scanner) supplies them
    here instead.

    Output ordering is normalized (scanners by scanner_id/config_label,
    items/findings by run_index and then identifying fields) regardless of
    the order callers pass data in, so that determinism does not depend on
    callers maintaining a stable iteration order of their own.
    """
    per_scanner_items = per_scanner_items or {}
    per_scanner_findings = per_scanner_findings or {}
    unavailable_reasons = unavailable_reasons or {}
    display_names = display_names or {}

    scanners: list[dict[str, Any]] = []
    for report in reports:
        items_runs = list(per_scanner_items.get(report.scanner_id, ()))
        findings_runs = list(per_scanner_findings.get(report.scanner_id, ()))

        scanner_doc: dict[str, Any] = {
            "scanner_id": report.scanner_id,
            "scanner_version": report.scanner_version,
            "adapter_version": report.adapter_version,
            "config_label": report.config_label,
            "requires_signup": bool(report.requires_signup),
            "stages_attempted": list(report.stages_attempted),
            "runs": report.runs,
            "metrics": _metrics_dict(report),
        }

        # The model fields are authoritative; the caller maps remain as an
        # override for an orchestrator that knows more than the report does.
        display_name = display_names.get(report.scanner_id) or report.display_name
        if display_name:
            scanner_doc["display_name"] = display_name
        reason = (unavailable_reasons.get(report.scanner_id)
                  or report.unavailable_reason)
        if reason:
            scanner_doc["unavailable_reason"] = reason

        not_attempted = _not_attempted_classes(report.stages_attempted)
        if not_attempted:
            scanner_doc["not_attempted_classes"] = not_attempted

        items_sorted = sorted(
            items_runs,
            key=lambda ri: (ri[0], ri[1].server_id, ri[1].attack_class or ""),
        )
        scanner_doc["items"] = [_item_to_dict(idx, item) for idx, item in items_sorted]

        findings_sorted = sorted(
            findings_runs,
            key=lambda rf: (
                rf[0],
                rf[1].finding.raw_label,
                rf[1].finding.file or "",
                rf[1].finding.line or 0,
            ),
        )
        scanner_doc["findings"] = [
            _finding_to_dict(idx, mapped) for idx, mapped in findings_sorted
        ]

        if report.notes:
            scanner_doc["notes"] = list(report.notes)

        scanners.append(scanner_doc)

    scanners.sort(key=lambda s: (s["scanner_id"], s["config_label"]))

    return {
        "schema_version": SCHEMA_VERSION,
        "corpus_version": corpus_version,
        "generated_at": generated_at,
        "runs_per_scanner": runs_per_scanner,
        "scanners": scanners,
    }


def write_results(doc: dict[str, Any], path: str | Path) -> None:
    """Write `doc` as deterministic, stable JSON: sorted keys, indent 2,
    trailing newline. Byte-identical for byte-identical input so that a
    committed diff always reflects a real change.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")


def load_results(path: str | Path) -> dict[str, Any]:
    """Read back a results document written by write_results (or anything
    else emitting schema-shaped JSON)."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_schema() -> dict[str, Any]:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def validate_results(doc: dict[str, Any]) -> list[str]:
    """Validate `doc` against schema/results.schema.json.

    Returns a list of "<json-pointer>: <problem>" strings, one per schema
    violation, sorted by location -- empty when the document is valid. A
    list rather than a raised exception so a caller (e.g. a CLI that just
    produced a bad document) can report every problem at once instead of
    fixing them one exception at a time.
    """
    schema = _load_schema()
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(doc), key=lambda e: [str(p) for p in e.path])
    messages = []
    for err in errors:
        pointer = "/" + "/".join(str(p) for p in err.path)
        messages.append(f"{pointer}: {err.message}")
    messages.extend(_check_stat_invariants(doc))
    return sorted(messages)


def _check_stat_invariants(doc: dict[str, Any]) -> list[str]:
    """Check what JSON Schema cannot express about a {mean, min, max} block.

    Two ways a caller can emit a schema-valid but meaningless statistic:
    min > mean > max, and a partially-null block. The second matters most --
    a null mean beside a populated min would read as "no data" in one column
    and "we measured something" in the next, and a reader has no way to tell
    which is true. Both are caught here rather than shipped.
    """
    problems: list[str] = []
    for i, scanner in enumerate(doc.get("scanners") or []):
        # A zero-run row is how an unavailable scanner is published. Without a
        # reason it is just an empty score, which reads as "this tool found
        # nothing" rather than "we could not run it" -- the exact conflation
        # governance.md refuses.
        if scanner.get("runs") == 0 and not scanner.get("unavailable_reason"):
            problems.append(
                f"/scanners/{i}: runs is 0 but no unavailable_reason is set; a "
                f"scanner that could not be run must publish why")
        if scanner.get("runs", 0) > 0 and scanner.get("unavailable_reason"):
            problems.append(
                f"/scanners/{i}: has both completed runs and an "
                f"unavailable_reason; one of them is wrong")
        metrics = scanner.get("metrics") or {}
        blocks: list[tuple[str, Any]] = [
            (f"/scanners/{i}/metrics/recall_overall", metrics.get("recall_overall")),
            (f"/scanners/{i}/metrics/precision_overall", metrics.get("precision_overall")),
        ]
        for cls, block in (metrics.get("recall_per_class") or {}).items():
            blocks.append((f"/scanners/{i}/metrics/recall_per_class/{cls}", block))

        for pointer, block in blocks:
            if not isinstance(block, dict):
                continue
            mean, lo, hi = block.get("mean"), block.get("min"), block.get("max")
            present = [v is not None for v in (mean, lo, hi)]
            if any(present) and not all(present):
                problems.append(
                    f"{pointer}: partially-null statistic "
                    f"(mean={mean}, min={lo}, max={hi}); either all three are "
                    f"null or all three are populated")
                continue
            if all(present) and not (lo <= mean <= hi):
                problems.append(
                    f"{pointer}: min <= mean <= max violated "
                    f"(mean={mean}, min={lo}, max={hi})")
    return problems
