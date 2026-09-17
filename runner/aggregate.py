"""N runs into one ScannerReport: mean and range, never a single run.

docs/scoring.md#nondeterminism: some scanners use LLM-as-judge analyzers and
return different results run to run, so every published number is a mean with
its observed min-max range attached, over N >= 5 runs of a fixed corpus version.

Two things this module is careful about:

* **`None` is not zero.** A class with no attempted items has no recall. It
  stays `None` through the mean rather than being counted as 0.0, which would
  drag the mean down with a fact about the corpus instead of about the scanner.
* **Zero variance is a result.** A deterministic rule-based tool produces a
  range of exactly 0.0 on every class. That is a reportable finding about
  reproducibility, so it is represented explicitly (a width of 0.0 in
  `variance_detail`, plus a note) and never conflated with "no data", which is
  represented by the class being absent from `variance_detail` and `None` in
  the mean.
"""

from __future__ import annotations

from typing import Sequence

from .models import CLASSES, RunMetrics, ScannerReport

#: docs/scoring.md: a range on any per-class recall that *exceeds* 20
#: percentage points is flagged. Exactly 20.0 points is not flagged; the spec
#: says "exceeds".
VARIANCE_THRESHOLD = 0.20

#: Float slack so that 0.8 - 0.6 == 0.20000000000000007 does not trip a
#: threshold the spec puts at exactly 20 points.
_EPS = 1e-9

#: docs/scoring.md: "Every scanner runs N = 5 times minimum".
MIN_RUNS = 5


def mean_range(
    values: Sequence[float | None],
) -> tuple[float | None, tuple[float, float] | None]:
    """Mean and (min, max) over the values that exist.

    Returns `(None, None)` when nothing was observed. `None` entries are
    skipped, not treated as zero.
    """
    present = [v for v in values if v is not None]
    if not present:
        return None, None
    return sum(present) / len(present), (min(present), max(present))


def aggregate(
    runs: Sequence[RunMetrics],
    *,
    scanner_id: str,
    scanner_version: str = "unknown",
    adapter_version: str = "unknown",
    config_label: str = "default",
    corpus_version: str = "unknown",
    requires_signup: bool = False,
    stages_attempted: Sequence[str] = ("static", "runtime"),
    notes: Sequence[str] = (),
) -> ScannerReport:
    """Combine per-run metrics into the row the scoreboard renders."""
    if not runs:
        raise ValueError("cannot aggregate zero runs")

    report_notes: list[str] = list(notes)

    recall_per_class_mean: dict[str, float | None] = {}
    recall_per_class_range: dict[str, tuple[float, float] | None] = {}
    variance_detail: dict[str, float] = {}

    for cls in CLASSES:
        values = [r.recall_per_class.get(cls) for r in runs]
        mean, rng = mean_range(values)
        recall_per_class_mean[cls] = mean
        recall_per_class_range[cls] = rng
        if rng is not None:
            variance_detail[cls] = rng[1] - rng[0]
        present = sum(1 for v in values if v is not None)
        if 0 < present < len(runs):
            report_notes.append(
                f"{cls}: attempted in {present}/{len(runs)} runs; the mean and "
                f"range cover only the runs where it was attempted")

    high_variance = any(
        width - VARIANCE_THRESHOLD > _EPS for width in variance_detail.values()
    )

    recall_overall_mean, recall_overall_range = mean_range(
        [r.recall_overall for r in runs])
    precision_mean, precision_range = mean_range(
        [r.precision_overall for r in runs])

    near_miss_mean = sum(r.near_miss_count for r in runs) / len(runs)
    unmapped_mean = sum(r.unmapped_count for r in runs) / len(runs)

    if len(runs) < MIN_RUNS:
        report_notes.append(
            f"aggregated over {len(runs)} run(s); docs/scoring.md requires "
            f"N >= {MIN_RUNS} for a published result")

    if variance_detail and all(w == 0.0 for w in variance_detail.values()):
        report_notes.append(
            f"zero variance across {len(runs)} runs: every per-class recall was "
            f"identical run to run. Reported as a finding about reproducibility, "
            f"not as an absence of data")

    return ScannerReport(
        scanner_id=scanner_id,
        scanner_version=scanner_version,
        adapter_version=adapter_version,
        config_label=config_label,
        corpus_version=corpus_version,
        requires_signup=requires_signup,
        stages_attempted=list(stages_attempted),
        runs=len(runs),
        recall_per_class_mean=recall_per_class_mean,
        recall_per_class_range=recall_per_class_range,
        recall_overall_mean=recall_overall_mean,
        recall_overall_range=recall_overall_range,
        precision_mean=precision_mean,
        precision_range=precision_range,
        near_miss_mean=near_miss_mean,
        unmapped_mean=unmapped_mean,
        high_variance=high_variance,
        variance_detail=variance_detail,
        notes=report_notes,
    )


def is_deterministic(report: ScannerReport) -> bool:
    """True when every observed metric range has width zero.

    Distinct from `not report.high_variance`, which is merely "not very
    variable". A scanner with no observed data at all is not deterministic --
    it is unmeasured -- so an empty `variance_detail` returns False.
    """
    if not report.variance_detail:
        return False
    widths = list(report.variance_detail.values())
    for rng in (report.recall_overall_range, report.precision_range):
        if rng is not None:
            widths.append(rng[1] - rng[0])
    return all(w == 0.0 for w in widths)
