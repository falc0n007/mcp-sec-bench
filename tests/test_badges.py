"""Tests for tools/badges.py.

The binding rule: a badge never carries a score, rank, or verdict colour.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import badges  # noqa: E402

from tests.test_build_site import CORPUS, _report, make_doc  # noqa: E402

SITE = "https://example.test/bench/"


@pytest.fixture()
def out(tmp_path):
    badges.write_badges(make_doc(), tmp_path, SITE)
    return tmp_path


def _load(out: Path, slug: str) -> dict:
    return json.loads((out / f"{slug}.json").read_text(encoding="utf-8"))


def test_endpoint_schema(out):
    b = _load(out, "alpha-scan")
    assert b["schemaVersion"] == 1
    assert b["label"] == "mcp-sec-bench"
    assert set(b) == {"schemaVersion", "label", "message", "color"}


def test_benchmarked_message_names_corpus_version(out):
    assert _load(out, "alpha-scan")["message"] == f"benchmarked · corpus {CORPUS}"


def test_unavailable_message(out):
    b = _load(out, "gamma-scan")
    assert b["message"] == "unavailable"
    assert b["color"] == "lightgrey"


def test_badge_never_carries_a_number_or_depends_on_scores(tmp_path):
    # Two scanners with wildly different scores must get identical badges bar
    # nothing: no digits except inside the corpus version, one colour.
    doc = make_doc([
        _report("hi-scan", recall_overall_mean=1.0, recall_overall_range=(1.0, 1.0)),
        _report("lo-scan", recall_overall_mean=0.0, recall_overall_range=(0.0, 0.0)),
    ], items={})
    badges.write_badges(doc, tmp_path, SITE)
    hi, lo = _load(tmp_path, "hi-scan"), _load(tmp_path, "lo-scan")
    assert hi == lo
    assert re.sub(re.escape(CORPUS), "", hi["message"]).strip().startswith("benchmarked")
    assert "%" not in hi["message"]


def test_snippet_links_to_scanner_page_and_endpoint(out):
    snippet = (out / "alpha-scan.md").read_text(encoding="utf-8").strip()
    m = re.fullmatch(r"\[!\[([^\]]*)\]\(([^)]+)\)\]\(([^)]+)\)", snippet)
    assert m, snippet
    alt, img, link = m.groups()
    assert link == "https://example.test/bench/scanners/alpha-scan.html"
    assert "Alpha-Scan" in alt
    q = parse_qs(urlparse(img).query)
    assert q["url"] == ["https://example.test/bench/badges/alpha-scan.json"]


def test_snippets_file_lists_every_scanner(out):
    text = (out / "snippets.md").read_text(encoding="utf-8")
    for slug in ("alpha-scan", "gamma-scan", "zeta-scan"):
        assert f"/scanners/{slug}.html" in text


def test_fixtures_excluded_by_default(tmp_path):
    doc = make_doc([_report("fixture-oracle"), _report("real-scan")], items={})
    badges.write_badges(doc, tmp_path, SITE)
    assert not (tmp_path / "fixture-oracle.json").exists()
    assert (tmp_path / "real-scan.json").exists()


def test_invalid_document_refused(tmp_path):
    doc = make_doc()
    del doc["scanners"]
    with pytest.raises(ValueError):
        badges.write_badges(doc, tmp_path / "b", SITE)
