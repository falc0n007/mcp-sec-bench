"""Tests for tools/build_site.py.

Documents are built through runner.results.build_results from hand-made
ScannerReports, so every fixture is schema-valid by construction. Each
assertion traces to a binding rule in docs/scoring.md or docs/governance.md.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import build_site  # noqa: E402

from runner.models import ItemOutcome, Outcome, ScannerReport  # noqa: E402
from runner.results import build_results  # noqa: E402

CORPUS = "v1-testcorpus"


def _report(scanner_id: str, **kw) -> ScannerReport:
    base = dict(
        scanner_id=scanner_id, scanner_version="1.0.0", adapter_version="1.0.0",
        config_label="default", corpus_version=CORPUS, requires_signup=False,
        stages_attempted=["static"], runs=5,
        recall_per_class_mean={"A1": 0.4, "A7": 0.0, "A4": None},
        recall_per_class_range={"A1": (0.2, 0.6), "A7": (0.0, 0.0), "A4": None},
        recall_overall_mean=0.3, recall_overall_range=(0.2, 0.4),
        precision_mean=0.75, precision_range=(0.6, 0.9),
        near_miss_mean=1.0, unmapped_mean=2.0, high_variance=False,
        display_name=scanner_id.title(),
    )
    base.update(kw)
    return ScannerReport(**base)


def make_doc(reports=None, items=None) -> dict:
    if reports is None:
        reports = [
            _report("zeta-scan", precision_mean=0.1, precision_range=(0.1, 0.1)),
            _report("alpha-scan", recall_overall_mean=0.9, recall_overall_range=(0.8, 1.0)),
            _report(
                "gamma-scan", runs=0, requires_signup=True, stages_attempted=[],
                recall_per_class_mean={}, recall_per_class_range={},
                recall_overall_mean=None, recall_overall_range=None,
                precision_mean=None, precision_range=None, near_miss_mean=0.0,
                unmapped_mean=0.0, unavailable_reason="SNYK_TOKEN is not set. More text.",
            ),
        ]
    if items is None:
        items = {
            "alpha-scan": [
                (i, ItemOutcome("srv", "A1", Outcome.FALSE_POSITIVE)) for i in range(5)
            ] + [(0, ItemOutcome("srv2", "A2", Outcome.FALSE_POSITIVE))],
        }
    return build_results(
        reports, CORPUS, "2026-01-01T00:00:00+00:00", 5, per_scanner_items=items
    )


@pytest.fixture()
def site(tmp_path):
    build_site.build_site(make_doc(), tmp_path)
    return tmp_path


def _index(site: Path) -> str:
    return (site / "index.html").read_text(encoding="utf-8")


def _row_order(page: str) -> list[str]:
    return re.findall(r'href="scanners/([^"]+)\.html"', page)


def test_writes_index_and_one_page_per_scanner(site):
    assert (site / "index.html").exists()
    for slug in ("alpha-scan", "zeta-scan", "gamma-scan"):
        assert (site / "scanners" / f"{slug}.html").exists()


def test_rows_sorted_alphabetically_never_by_score(site):
    # zeta has the lower recall and alpha the higher: any score sort would
    # move them. Alphabetical puts alpha first, in both tables.
    order = _row_order(_index(site))
    firsts = [s for i, s in enumerate(order) if s not in order[:i]]
    assert firsts == ["alpha-scan", "gamma-scan", "zeta-scan"]
    # Both tables repeat the same order.
    assert order == ["alpha-scan", "gamma-scan", "zeta-scan"] * 2


def test_no_composite_score_or_script(site):
    page = _index(site).lower()
    for word in ("composite", "overall score", "grade"):
        assert word not in page
    assert "<script" not in page


def test_caveat_and_corpus_version_on_every_page(site):
    for page in [site / "index.html", *(site / "scanners").glob("*.html")]:
        text = page.read_text(encoding="utf-8")
        assert "small synthetic corpus" in text
        assert "not a safety certification" in text
        assert CORPUS in text


def test_mean_and_range_shown_where_runs_disagree(site):
    # alpha's A1 ranged 0.20-0.60 over the runs: the index shows the range.
    assert "0.40 (0.20\u201360)" not in _index(site)  # guard against a bad dash
    assert "0.40 (0.20\u20130.60)" in _index(site)
    assert "Where runs disagreed" in _index(site)


def test_scanner_page_always_shows_mean_and_range(site):
    alpha = (site / "scanners" / "alpha-scan.html").read_text(encoding="utf-8")
    assert "Recall, mean (min\u2013max)" in alpha
    assert "0.00 (0.00\u20130.00)" in alpha  # a real zero stays a zero (A7)


def test_identical_runs_drop_ranges_and_say_so(tmp_path):
    steady = _report(
        "steady-scan",
        recall_per_class_mean={"A1": 0.5}, recall_per_class_range={"A1": (0.5, 0.5)},
        recall_overall_range=(0.3, 0.3), precision_range=(0.75, 0.75),
    )
    build_site.build_site(make_doc(reports=[steady], items={}), tmp_path)
    page = _index(tmp_path)
    assert "produced identical figures, so no ranges are shown" in page
    assert not re.search(r"0\.50 \(\d", page)
    steady_page = (tmp_path / "scanners" / "steady-scan.html").read_text(encoding="utf-8")
    assert "0.50 (0.50\u20130.50)" in steady_page


def test_recall_and_precision_side_by_side_not_combined(site):
    page = _index(site)
    assert '>Recall</th><th scope="col" class="num">Precision</th>' in page


def test_not_attempted_is_na_and_missing_is_dash(site):
    # A4 is runtime-only, so for this static scanner it is not attempted.
    alpha = (site / "scanners" / "alpha-scan.html").read_text(encoding="utf-8")
    assert re.search(r'<th scope="row">A4</th><td>[^<]+</td><td class="num">n/a</td>', alpha)
    # A2 has no entry at all and is creditable by static: no data, not n/a.
    assert re.search(r'<th scope="row">A2</th><td>[^<]+</td><td class="num">-</td>', alpha)


def test_matrix_distinguishes_not_attempted_from_missed(site):
    page = _index(site)
    row = page[page.index('href="scanners/alpha-scan.html"'):]
    row = row[: row.index("</tr>")]
    states = re.findall(r'data-state="(\w+)"[^>]*title="(A\d+) ', row)
    by_class = {c: st for st, c in states}
    assert by_class["A4"] == "na"
    assert by_class["A2"] == "nodata"
    assert by_class["A7"] == "miss"
    assert by_class["A1"] == "partial"


def test_near_miss_always_beside_false_positive_count(site):
    page = _index(site)
    # alpha: items give (5 + 1) false positives over 5 runs = 1.2 per run.
    assert "1.2 false positives, 1 near miss" in page
    # Every near-miss mention is in a cell that also names false positives.
    for cell in re.findall(r"<td[^>]*>([^<]*near miss[^<]*)</td>", page):
        assert "false positive" in cell
    assert "almost right" not in page.lower()


def test_near_miss_hidden_without_item_detail(tmp_path):
    build_site.build_site(make_doc(items={}), tmp_path)
    page = _index(tmp_path)
    assert "near miss</td>" not in page


def test_unavailable_row_shows_reason_and_signup(site):
    page = _index(site)
    assert "Not measured: SNYK_TOKEN is not set." in page
    assert "SNYK_TOKEN is not set. More text." in page
    gamma = (site / "scanners" / "gamma-scan.html").read_text(encoding="utf-8")
    assert "SNYK_TOKEN is not set. More text." in gamma
    assert "Requires signup</dt><dd>yes" in gamma


def test_requires_signup_column(site):
    assert '<th scope="col">Requires signup</th>' in _index(site)


def test_methodology_links_point_at_github(site):
    page = _index(site)
    assert "https://github.com/falc0n007/mcp-sec-bench/blob/main/docs/scoring.md" in page


def test_no_external_hosts_besides_github_links(site):
    for page in [site / "index.html", *(site / "scanners").glob("*.html")]:
        text = page.read_text(encoding="utf-8")
        assert not re.search(r"<(script|link|img)[^>]+(src|href)=\"https?://", text)
        assert "@import" not in text


def test_no_emoji(site):
    for page in [site / "index.html", *(site / "scanners").glob("*.html")]:
        text = page.read_text(encoding="utf-8")
        assert not re.search("[\U0001F000-\U0001FFFF\u2600-\u27BF]", text)


def test_dark_mode_and_viewport(site):
    page = _index(site)
    assert "prefers-color-scheme: dark" in page
    assert 'name="viewport"' in page


def test_html_is_escaped(tmp_path):
    doc = make_doc([_report("x-scan", display_name="<img src=x onerror=alert(1)>")], items={})
    build_site.build_site(doc, tmp_path)
    assert "<img src=x" not in _index(tmp_path)
    assert "&lt;img src=x" in _index(tmp_path)


def test_fixtures_hidden_by_default(tmp_path):
    doc = make_doc([_report("fixture-oracle"), _report("real-scan")], items={})
    build_site.build_site(doc, tmp_path)
    assert not (tmp_path / "scanners" / "fixture-oracle.html").exists()
    assert (tmp_path / "scanners" / "real-scan.html").exists()
    other = tmp_path / "all"
    build_site.build_site(doc, other, include_fixtures=True)
    assert (other / "scanners" / "fixture-oracle.html").exists()


def test_non_default_config_is_a_separate_row(tmp_path):
    doc = make_doc(
        [_report("a-scan"), _report("a-scan", config_label="strict")], items={}
    )
    build_site.build_site(doc, tmp_path)
    assert (tmp_path / "scanners" / "a-scan.html").exists()
    assert (tmp_path / "scanners" / "a-scan-strict.html").exists()


def test_invalid_document_is_refused_before_writing(tmp_path):
    doc = make_doc()
    del doc["corpus_version"]
    out = tmp_path / "out"
    with pytest.raises(ValueError):
        build_site.build_site(doc, out)
    assert not out.exists()


def test_empty_scoreboard_renders(tmp_path):
    build_site.build_site(make_doc([], items={}), tmp_path)
    assert "No scanner results yet" in _index(tmp_path)
