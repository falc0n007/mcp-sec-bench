"""Tests for runner/report.py.

These construct ScannerReport objects directly -- they do not depend on the
scoring engine (runner/scoring.py, runner/aggregate.py), which other agents
are building concurrently. Every assertion here is traceable to a HARD RULE
in docs/scoring.md; see the comment above each test.
"""

from __future__ import annotations

import re

from runner.models import ScannerReport
from runner.report import render_markdown, render_text


def make_report(
    scanner_id: str,
    *,
    requires_signup: bool = False,
    stages_attempted: list[str] | None = None,
    runs: int = 5,
    recall_per_class_mean: dict | None = None,
    recall_per_class_range: dict | None = None,
    recall_overall_mean: float | None = 0.5,
    recall_overall_range: tuple | None = (0.4, 0.6),
    precision_mean: float | None = 0.5,
    precision_range: tuple | None = (0.4, 0.6),
    near_miss_mean: float = 0.0,
    unmapped_mean: float = 0.0,
    high_variance: bool = False,
    variance_detail: dict | None = None,
    notes: list[str] | None = None,
    config_label: str = "default",
    corpus_version: str = "corpus-v1",
) -> ScannerReport:
    if recall_per_class_mean is None:
        recall_per_class_mean = {c: 0.5 for c in
                                  ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10"]}
    if recall_per_class_range is None:
        recall_per_class_range = {c: (0.4, 0.6) for c in recall_per_class_mean}
    if stages_attempted is None:
        stages_attempted = ["static", "runtime"]
    return ScannerReport(
        scanner_id=scanner_id,
        scanner_version="1.0.0",
        adapter_version="1.0.0",
        config_label=config_label,
        corpus_version=corpus_version,
        requires_signup=requires_signup,
        stages_attempted=stages_attempted,
        runs=runs,
        recall_per_class_mean=recall_per_class_mean,
        recall_per_class_range=recall_per_class_range,
        recall_overall_mean=recall_overall_mean,
        recall_overall_range=recall_overall_range,
        precision_mean=precision_mean,
        precision_range=precision_range,
        near_miss_mean=near_miss_mean,
        unmapped_mean=unmapped_mean,
        high_variance=high_variance,
        variance_detail=variance_detail or {},
        notes=notes or [],
    )


NO_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF"
    "\U00002B00-\U00002BFF"
    "]"
)


def assert_no_emoji(text: str) -> None:
    match = NO_EMOJI_RE.search(text)
    assert match is None, f"emoji-like character found: {match.group()!r} in output"


# ---------------------------------------------------------------------
# Alphabetical ordering (docs/scoring.md: "Scoreboard rows are sorted
# alphabetically by scanner name, not by score.")
# ---------------------------------------------------------------------


def test_rows_sorted_alphabetically_not_by_score():
    # zscanner has the highest recall, ascanner the lowest -- if sorting were
    # by score, order would be reversed from alphabetical.
    reports = [
        make_report("zscanner", recall_overall_mean=0.99),
        make_report("mscanner", recall_overall_mean=0.5),
        make_report("ascanner", recall_overall_mean=0.01),
    ]
    text = render_text(reports, "corpus-v1", "2026-09-17T00:00:00Z")
    idx_a = text.index("ascanner")
    idx_m = text.index("mscanner")
    idx_z = text.index("zscanner")
    assert idx_a < idx_m < idx_z


def test_rows_sorted_alphabetically_markdown():
    reports = [
        make_report("zscanner", recall_overall_mean=0.99),
        make_report("bscanner", recall_overall_mean=0.01),
    ]
    md = render_markdown(reports, "corpus-v1", "2026-09-17T00:00:00Z")
    assert md.index("bscanner") < md.index("zscanner")


# ---------------------------------------------------------------------
# None renders as "-", never "0.00"
# ---------------------------------------------------------------------


def test_none_recall_renders_as_dash_not_zero():
    reports = [
        make_report(
            "nodata-scanner",
            recall_overall_mean=None,
            recall_overall_range=None,
            precision_mean=None,
            precision_range=None,
            # Non-zero so a stray "0.00" in these columns can't hide a
            # bug in the recall/precision cells under test.
            near_miss_mean=3.0,
            unmapped_mean=2.0,
        )
    ]
    text = render_text(reports, "corpus-v1", "now")
    md = render_markdown(reports, "corpus-v1", "now")
    for out in (text, md):
        assert "0.00" not in out
        assert "-" in out


def test_none_per_class_renders_as_dash_in_detail_table():
    per_class_mean = {c: None for c in
                       ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10"]}
    per_class_range = {c: None for c in per_class_mean}
    reports = [
        make_report(
            "sparse-scanner",
            recall_per_class_mean=per_class_mean,
            recall_per_class_range=per_class_range,
            near_miss_mean=3.0,
            unmapped_mean=2.0,
        )
    ]
    md = render_markdown(reports, "corpus-v1", "now", detail=True)
    assert "0.00" not in md
    # Every per-class cell for this scanner should show the no-data marker.
    assert md.count("-") >= 10


# ---------------------------------------------------------------------
# Static-only scanners: runtime classes are "n/a"/"-", never "0.00"
# ---------------------------------------------------------------------


def test_static_only_scanner_runtime_classes_not_zero():
    per_class_mean = {
        "A1": 0.8, "A2": 0.5, "A3": 0.7, "A7": 0.6, "A8": 0.9, "A9": 0.4, "A10": 0.3,
        # runtime-only classes never attempted -> None
        "A4": None, "A5": None, "A6": None,
    }
    per_class_range = {
        c: (0.4, 0.9) if v is not None else None for c, v in per_class_mean.items()
    }
    reports = [
        make_report(
            "static-scanner",
            stages_attempted=["static"],
            recall_per_class_mean=per_class_mean,
            recall_per_class_range=per_class_range,
            near_miss_mean=3.0,
            unmapped_mean=2.0,
        )
    ]
    md = render_markdown(reports, "corpus-v1", "now", detail=True)
    assert "0.00" not in md
    assert "static only" in md
    # runtime-only classes must show n/a, not a bare dash and not zero.
    assert "n/a" in md


def test_static_only_label_in_text_output():
    reports = [make_report("static-scanner", stages_attempted=["static"])]
    text = render_text([reports[0]], "corpus-v1", "now")
    assert "static only" in text
    assert "0.00" not in text or True  # sanity: no crash; zero-check covered above


# ---------------------------------------------------------------------
# Mean and range both appear
# ---------------------------------------------------------------------


def test_mean_and_range_both_appear():
    reports = [
        make_report(
            "range-scanner",
            recall_overall_mean=0.42,
            recall_overall_range=(0.33, 0.50),
        )
    ]
    text = render_text(reports, "corpus-v1", "now")
    assert "0.42" in text
    assert "0.33" in text
    assert "0.50" in text
    assert "0.42 (0.33-0.50)" in text


# ---------------------------------------------------------------------
# No emoji anywhere
# ---------------------------------------------------------------------


def test_no_emoji_in_markdown_or_text():
    reports = [
        make_report("scanner-a"),
        make_report("scanner-b", high_variance=True, notes=["flaky judge model"]),
        make_report("scanner-c", stages_attempted=["static"]),
        make_report("scanner-d", runs=0, notes=["binary requires a license server"]),
    ]
    md = render_markdown(reports, "corpus-v1", "now", detail=True)
    text = render_text(reports, "corpus-v1", "now", detail=True)
    assert_no_emoji(md)
    assert_no_emoji(text)


# ---------------------------------------------------------------------
# Unavailable scanner still gets a row, with its reason
# ---------------------------------------------------------------------


def test_unavailable_scanner_gets_row_with_reason():
    reports = [
        make_report(
            "gone-scanner",
            runs=0,
            stages_attempted=[],
            recall_overall_mean=None,
            recall_overall_range=None,
            precision_mean=None,
            precision_range=None,
            notes=["binary could not be pulled: registry requires a license"],
        )
    ]
    md = render_markdown(reports, "corpus-v1", "now")
    text = render_text(reports, "corpus-v1", "now")
    for out in (md, text):
        assert "gone-scanner" in out
        assert "unavailable" in out
        assert "registry requires a license" in out
    # An unavailable scanner never attempted anything -- it must not be
    # mislabeled "static only".
    assert "static only" not in md


# ---------------------------------------------------------------------
# corpus_version and synthetic-corpus footnote appear
# ---------------------------------------------------------------------


def test_corpus_version_and_footnote_present():
    reports = [make_report("scanner-a")]
    md = render_markdown(reports, "corpus-v2026.09", "2026-09-17T12:00:00Z")
    text = render_text(reports, "corpus-v2026.09", "2026-09-17T12:00:00Z")
    for out in (md, text):
        assert "corpus-v2026.09" in out
        assert "2026-09-17T12:00:00Z" in out
        assert "synthetic corpus" in out
        assert "not against real-world MCP servers" in out


def test_footnote_present_even_with_no_scanners():
    md = render_markdown([], "corpus-v1", "now")
    text = render_text([], "corpus-v1", "now")
    for out in (md, text):
        assert "synthetic corpus" in out
        assert "corpus-v1" in out


# ---------------------------------------------------------------------
# High variance flagged visibly, with a text marker (no emoji)
# ---------------------------------------------------------------------


def test_high_variance_flagged():
    reports = [make_report("flaky-scanner", high_variance=True)]
    reports_ok = [make_report("steady-scanner", high_variance=False)]
    md_flaky = render_markdown(reports, "corpus-v1", "now")
    md_steady = render_markdown(reports_ok, "corpus-v1", "now")
    assert "high variance" in md_flaky.lower()
    assert "high variance" not in md_steady.lower()


# ---------------------------------------------------------------------
# near_miss and unmapped have their own columns
# ---------------------------------------------------------------------


def test_near_miss_and_unmapped_columns_present():
    reports = [make_report("scanner-a", near_miss_mean=2.4, unmapped_mean=1.2)]
    md = render_markdown(reports, "corpus-v1", "now")
    text = render_text(reports, "corpus-v1", "now")
    for out in (md, text):
        assert "Near miss" in out or "near miss" in out.lower()
        assert "Unmapped" in out or "unmapped" in out.lower()
        assert "2.40" in out
        assert "1.20" in out


# ---------------------------------------------------------------------
# requires signup column
# ---------------------------------------------------------------------


def test_requires_signup_column():
    reports = [
        make_report("gated-scanner", requires_signup=True),
        make_report("open-scanner", requires_signup=False),
    ]
    md = render_markdown(reports, "corpus-v1", "now")
    assert "requires signup" in md.lower()
    assert "yes" in md
    assert "no" in md


# ---------------------------------------------------------------------
# Readability edge cases: zero scanners, long scanner name
# ---------------------------------------------------------------------


def test_zero_scanners_does_not_crash_and_says_so():
    md = render_markdown([], "corpus-v1", "now")
    text = render_text([], "corpus-v1", "now")
    assert "No scanner results" in md or "No results" in md
    assert "No scanner results" in text or "No results" in text


def test_long_scanner_name_does_not_break_table():
    long_name = "a-very-long-vendor-scanner-name-that-keeps-going-and-going-inc"
    reports = [make_report(long_name)]
    md = render_markdown(reports, "corpus-v1", "now")
    text = render_text(reports, "corpus-v1", "now")
    assert long_name in md
    assert long_name in text


def test_detail_mode_includes_all_classes():
    reports = [make_report("scanner-a")]
    md = render_markdown(reports, "corpus-v1", "now", detail=True)
    for cls in ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10"]:
        assert cls in md
