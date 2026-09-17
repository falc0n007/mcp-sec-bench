"""Tests for runner/results.py.

Builds ScannerReport (and the per-run ItemOutcome / MappedFinding detail
behind it) directly, without depending on scoring.py / aggregate.py /
mapping.py / report.py -- those are owned by other agents and may not exist
yet.
"""

from __future__ import annotations

import json

import pytest

from runner.models import ItemOutcome, MappedFinding, Outcome, RawFinding, ScannerReport
from runner.results import build_results, load_results, validate_results, write_results


# ---------------------------------------------------------------------------
# Sample data shared across tests
# ---------------------------------------------------------------------------


def _scanner_alpha() -> ScannerReport:
    """A normal scanner: two runs, real metrics, some variance."""
    return ScannerReport(
        scanner_id="alpha-scan",
        scanner_version="2.3.1",
        adapter_version="1.0.0",
        config_label="default",
        corpus_version="corpus-abc123",
        requires_signup=False,
        stages_attempted=["static", "runtime"],
        runs=2,
        recall_per_class_mean={"A1": 1.0, "A2": 0.5, "A7": 0.0},
        recall_per_class_range={"A1": (1.0, 1.0), "A2": (0.0, 1.0), "A7": (0.0, 0.0)},
        recall_overall_mean=0.5,
        recall_overall_range=(0.3333, 0.6667),
        precision_mean=0.8,
        precision_range=(0.75, 0.85),
        near_miss_mean=0.5,
        unmapped_mean=0.0,
        high_variance=True,
        variance_detail={"A2": 1.0},
        notes=["config uses vendor default ruleset"],
    )


def _scanner_beta_no_findings() -> ScannerReport:
    """A scanner that ran but found nothing attempted in-scope: every mean is
    None, which must survive as JSON null, not 0."""
    return ScannerReport(
        scanner_id="beta-scan",
        scanner_version="0.9.0",
        adapter_version="1.0.0",
        config_label="default",
        corpus_version="corpus-abc123",
        requires_signup=False,
        stages_attempted=["static"],
        runs=1,
        recall_per_class_mean={"A1": None, "A7": None},
        recall_per_class_range={"A1": None, "A7": None},
        recall_overall_mean=None,
        recall_overall_range=None,
        precision_mean=None,
        precision_range=None,
        near_miss_mean=0.0,
        unmapped_mean=0.0,
        high_variance=False,
    )


def _scanner_gamma_unavailable() -> ScannerReport:
    """A scanner that could not be run at all -- still published, per the
    schema's `unavailable_reason` description, rather than omitted."""
    return ScannerReport(
        scanner_id="gamma-scan",
        scanner_version="unknown",
        adapter_version="1.0.0",
        config_label="default",
        corpus_version="corpus-abc123",
        requires_signup=True,
        stages_attempted=[],
        # Zero, not one: a scanner that could not be run has no runs. The schema
        # previously required runs >= 1, which forced this sample to claim a
        # run that never happened.
        runs=0,
        recall_per_class_mean={},
        recall_per_class_range={},
        recall_overall_mean=None,
        recall_overall_range=None,
        precision_mean=None,
        precision_range=None,
        near_miss_mean=0.0,
        unmapped_mean=0.0,
        high_variance=False,
    )


def _alpha_items() -> list[tuple[int, ItemOutcome]]:
    return [
        (0, ItemOutcome("srv-a", "A1", Outcome.TRUE_POSITIVE, stage_credited="static", finding_ref="f0")),
        (0, ItemOutcome("srv-a", "A2", Outcome.FALSE_NEGATIVE)),
        (1, ItemOutcome("srv-a", "A1", Outcome.TRUE_POSITIVE, stage_credited="static", finding_ref="f1")),
        (1, ItemOutcome("srv-b", "A7", Outcome.FALSE_POSITIVE, note="near miss vs A1")),
    ]


def _alpha_findings() -> list[tuple[int, MappedFinding]]:
    return [
        (
            0,
            MappedFinding(
                finding=RawFinding(
                    scanner_id="alpha-scan",
                    raw_label="TOOL_DESC_INJECTION",
                    server_id="srv-a",
                    file="server.py",
                    line=42,
                    message="tool description contains hidden instructions",
                    severity="high",
                ),
                mapped_class="A1",
                mapped_server="srv-a",
                mapping_rationale_id="MR-0001",
            ),
        ),
        (
            1,
            MappedFinding(
                finding=RawFinding(
                    scanner_id="alpha-scan",
                    raw_label="SOME_UNKNOWN_RULE",
                    server_id="srv-b",
                    message="novel finding not in taxonomy",
                ),
                mapped_class=None,
                mapped_server=None,
                mapping_rationale_id=None,
            ),
        ),
    ]


def _build_sample_doc() -> dict:
    reports = [_scanner_alpha(), _scanner_beta_no_findings(), _scanner_gamma_unavailable()]
    return build_results(
        reports=reports,
        corpus_version="corpus-abc123",
        generated_at="2026-09-17T12:00:00Z",
        runs_per_scanner=2,
        per_scanner_items={"alpha-scan": _alpha_items()},
        per_scanner_findings={"alpha-scan": _alpha_findings()},
        unavailable_reasons={"gamma-scan": "requires a paid API key not provided in CI"},
        display_names={"alpha-scan": "Alpha Scan", "beta-scan": "Beta Scan"},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_sample_document_validates_against_real_schema():
    doc = _build_sample_doc()
    errors = validate_results(doc)
    assert errors == []


def test_none_metrics_serialize_to_null_never_zero():
    doc = _build_sample_doc()
    beta = next(s for s in doc["scanners"] if s["scanner_id"] == "beta-scan")
    metrics = beta["metrics"]

    assert metrics["recall_overall"] == {"mean": None, "min": None, "max": None}
    assert metrics["precision_overall"] == {"mean": None, "min": None, "max": None}
    assert metrics["recall_per_class"]["A1"] == {"mean": None, "min": None, "max": None}
    assert metrics["recall_per_class"]["A7"] == {"mean": None, "min": None, "max": None}

    # None must never be silently coerced into 0 / 0.0 anywhere in this block.
    def assert_no_bare_zero_stand_in(obj):
        for v in obj.values() if isinstance(obj, dict) else obj:
            if isinstance(v, dict):
                assert_no_bare_zero_stand_in(v)

    for cls_metrics in metrics["recall_per_class"].values():
        for key in ("mean", "min", "max"):
            assert cls_metrics[key] is None


def test_round_trip_write_then_load_is_equivalent(tmp_path):
    doc = _build_sample_doc()
    out = tmp_path / "results.json"
    write_results(doc, out)
    loaded = load_results(out)
    assert loaded == doc


def test_determinism_same_input_twice_is_byte_identical(tmp_path):
    doc1 = _build_sample_doc()
    doc2 = _build_sample_doc()

    out1 = tmp_path / "a.json"
    out2 = tmp_path / "b.json"
    write_results(doc1, out1)
    write_results(doc2, out2)

    assert out1.read_bytes() == out2.read_bytes()


def test_determinism_independent_of_caller_iteration_order(tmp_path):
    """Feeding the same logical data in a different order (reversed report
    list, reversed items/findings) must still produce identical bytes --
    ordering in the output is normalized, not inherited from the caller."""
    reports_forward = [_scanner_alpha(), _scanner_beta_no_findings(), _scanner_gamma_unavailable()]
    reports_backward = list(reversed(reports_forward))

    doc_forward = build_results(
        reports=reports_forward,
        corpus_version="corpus-abc123",
        generated_at="2026-09-17T12:00:00Z",
        runs_per_scanner=2,
        per_scanner_items={"alpha-scan": _alpha_items()},
        per_scanner_findings={"alpha-scan": _alpha_findings()},
        unavailable_reasons={"gamma-scan": "requires a paid API key not provided in CI"},
        display_names={"alpha-scan": "Alpha Scan", "beta-scan": "Beta Scan"},
    )
    doc_backward = build_results(
        reports=reports_backward,
        corpus_version="corpus-abc123",
        generated_at="2026-09-17T12:00:00Z",
        runs_per_scanner=2,
        per_scanner_items={"alpha-scan": list(reversed(_alpha_items()))},
        per_scanner_findings={"alpha-scan": list(reversed(_alpha_findings()))},
        unavailable_reasons={"gamma-scan": "requires a paid API key not provided in CI"},
        display_names={"alpha-scan": "Alpha Scan", "beta-scan": "Beta Scan"},
    )

    out_forward = tmp_path / "forward.json"
    out_backward = tmp_path / "backward.json"
    write_results(doc_forward, out_forward)
    write_results(doc_backward, out_backward)

    assert out_forward.read_bytes() == out_backward.read_bytes()


def test_written_file_has_stable_formatting(tmp_path):
    doc = _build_sample_doc()
    out = tmp_path / "results.json"
    write_results(doc, out)
    text = out.read_text(encoding="utf-8")

    assert text.endswith("\n")
    assert not text.endswith("\n\n")
    # sorted keys: top-level "corpus_version" must precede "generated_at"
    assert text.index('"corpus_version"') < text.index('"generated_at"')


def test_validate_results_reports_bad_outcome_value():
    doc = _build_sample_doc()
    doc["scanners"][0]["items"][0]["outcome"] = "definitely_not_a_real_outcome"
    errors = validate_results(doc)
    assert errors, "expected at least one validation error"
    assert any("outcome" in e for e in errors)


def test_validate_results_reports_missing_required_field():
    doc = _build_sample_doc()
    del doc["scanners"][0]["scanner_version"]
    errors = validate_results(doc)
    assert errors
    assert any("scanner_version" in e for e in errors)


def test_validate_results_reports_unexpected_extra_property():
    doc = _build_sample_doc()
    doc["scanners"][0]["totally_made_up_field"] = "nope"
    errors = validate_results(doc)
    assert errors
    assert any("totally_made_up_field" in e or "additional propert" in e.lower() for e in errors)


def test_validate_results_returns_multiple_errors_at_once():
    doc = _build_sample_doc()
    doc["scanners"][0]["items"][0]["outcome"] = "not_a_real_outcome"
    del doc["scanners"][0]["scanner_version"]
    errors = validate_results(doc)
    assert len(errors) >= 2


def test_valid_minimal_document_has_no_errors():
    doc = {
        "schema_version": "1.0",
        "corpus_version": "corpus-abc123",
        "generated_at": "2026-09-17T12:00:00Z",
        "scanners": [],
    }
    assert validate_results(doc) == []


def test_mapping_rationale_id_survives_into_output():
    doc = _build_sample_doc()
    alpha = next(s for s in doc["scanners"] if s["scanner_id"] == "alpha-scan")
    findings_by_label = {f["raw_label"]: f for f in alpha["findings"]}

    mapped = findings_by_label["TOOL_DESC_INJECTION"]
    assert mapped["mapping_rationale_id"] == "MR-0001"
    assert mapped["mapped_class"] == "A1"
    assert mapped["mapped_server"] == "srv-a"

    unmapped = findings_by_label["SOME_UNKNOWN_RULE"]
    assert unmapped["mapping_rationale_id"] is None
    assert unmapped["mapped_class"] is None


def test_unavailable_scanner_is_published_not_omitted():
    doc = _build_sample_doc()
    scanner_ids = {s["scanner_id"] for s in doc["scanners"]}
    assert "gamma-scan" in scanner_ids

    gamma = next(s for s in doc["scanners"] if s["scanner_id"] == "gamma-scan")
    assert gamma["unavailable_reason"] == "requires a paid API key not provided in CI"
    assert gamma["stages_attempted"] == []


def test_not_attempted_derived_from_stages_attempted():
    doc = _build_sample_doc()
    beta = next(s for s in doc["scanners"] if s["scanner_id"] == "beta-scan")
    # beta only attempts "static"; A4/A5/A6 require runtime per CLASS_STAGES.
    assert "A6" in beta["not_attempted_classes"]
    assert "A4" in beta["not_attempted_classes"]
    assert "A1" not in beta["not_attempted_classes"]


def test_outcome_enum_serializes_to_string_value():
    doc = _build_sample_doc()
    alpha = next(s for s in doc["scanners"] if s["scanner_id"] == "alpha-scan")
    outcomes = {item["outcome"] for item in alpha["items"]}
    assert outcomes <= {o.value for o in Outcome}
    assert "true_positive" in outcomes


def test_scanners_sorted_by_scanner_id():
    doc = _build_sample_doc()
    ids = [s["scanner_id"] for s in doc["scanners"]]
    assert ids == sorted(ids)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
