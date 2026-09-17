"""Tests for the credit rules.

The six `test_worked_example_*` cases are the ones docs/scoring.md pins by
name, because they are the cases a vendor will argue about. They run against a
small hand-built corpus rather than the real one so that the expected numbers
stay pinned to the spec while the corpus keeps growing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runner.aggregate import VARIANCE_THRESHOLD, aggregate, is_deterministic, mean_range
from runner.corpus import Corpus, ServerTruth, load_corpus
from runner.models import CorpusItem, MappedFinding, Outcome, RawFinding, RunMetrics
from runner.scoring import score_run

from runner.adapters.fixtures import identity_map
from runner.adapters.fixtures.foreign_taxonomy import ForeignTaxonomyAdapter
from runner.adapters.fixtures.near_miss import NearMissAdapter
from runner.adapters.fixtures.oracle import OracleAdapter
from runner.adapters.fixtures.overflagger import OverflaggerAdapter
from runner.adapters.fixtures.static_only import StaticOnlyAdapter

BOTH = ("static", "runtime")


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _server(server_id: str, kind: str = "vulnerable", *, declared=(),
            tolerated=(), not_applicable=()) -> ServerTruth:
    truth = ServerTruth(
        server_id=server_id, kind=kind, transport="http", port=8100,
        authenticated=True, path=Path("/nonexistent") / server_id,
        tolerated=set(tolerated), not_applicable=set(not_applicable),
    )
    for cls, surfaces in declared:
        truth.declared.append(CorpusItem(
            server_id=server_id, attack_class=cls,
            surfaces=frozenset(surfaces)))
    return truth


@pytest.fixture
def mini() -> Corpus:
    """A miniature of the real corpus, carrying one of each interesting shape.

    a02 is reachable from both stages, a06 only from runtime, c03 tolerates A7,
    c04 cannot structurally exhibit A6, and c01 is a clean control.
    """
    servers = [
        _server("a01-tool-description-injection", declared=[("A1", ["static"])]),
        _server("a02-rug-pull", declared=[("A2", ["static", "runtime"])]),
        _server("a06-authless-endpoint", declared=[("A6", ["runtime"])]),
        _server("a07-hardcoded-secrets", declared=[("A7", ["static"])]),
        _server("a08-unrestricted-file-read", declared=[("A8", ["static"])]),
        _server("c01-notes-workspace", kind="benign"),
        _server("c03-release-runner", kind="benign", tolerated=["A7"]),
        _server("c04-status-service", kind="benign", not_applicable=["A6"]),
    ]
    return Corpus(version="v1-test", servers={s.server_id: s for s in servers})


def mf(server: str | None, cls: str | None, *, label: str | None = None,
       stage: str | None = None, scanner: str = "t") -> MappedFinding:
    """A MappedFinding, built directly. The mapping layer is another module."""
    raw = RawFinding(
        scanner_id=scanner, raw_label=label or (cls or "?"),
        server_id=server, raw={"stage": stage} if stage else {})
    mapped = cls is not None and server is not None
    return MappedFinding(
        finding=raw,
        mapped_class=cls if mapped else None,
        mapped_server=server if mapped else None,
        mapping_rationale_id="test" if mapped else None,
    )


def outcome_for(outcomes, server: str, cls: str | None) -> list[Outcome]:
    return [o.outcome for o in outcomes
            if o.server_id == server and o.attack_class == cls]


# --------------------------------------------------------------------------
# the six worked examples in docs/scoring.md
# --------------------------------------------------------------------------

def test_worked_example_1_right_flaw_wrong_class_is_fp_plus_fn_plus_near_miss(mini):
    """1. Scanner reports "prompt injection" on the A8 server; mapping resolves
    it to A1. False positive on (A8-server, A1), false negative on
    (A8-server, A8), near-miss count incremented. No credit."""
    srv = "a08-unrestricted-file-read"
    outcomes, m = score_run(mini, [mf(srv, "A1", label="prompt-injection")], BOTH)

    assert outcome_for(outcomes, srv, "A1") == [Outcome.FALSE_POSITIVE]
    assert outcome_for(outcomes, srv, "A8") == [Outcome.FALSE_NEGATIVE]
    assert m.near_miss_count == 1
    assert m.false_positives == 1
    assert m.true_positives == 0
    # No credit, in either direction.
    assert m.recall_per_class["A8"] == 0.0
    assert m.recall_per_class["A1"] == 0.0  # a01's A1 item was not found either
    assert m.precision_overall == 0.0


def test_worked_example_2_right_class_wrong_server_is_a_false_positive(mini):
    """2. Scanner reports A7 on a benign control that does not tolerate A7.
    False positive. The A7 item on the vulnerable server remains a false
    negative unless separately found."""
    outcomes, m = score_run(mini, [mf("c01-notes-workspace", "A7")], BOTH)

    assert outcome_for(outcomes, "c01-notes-workspace", "A7") == [Outcome.FALSE_POSITIVE]
    assert outcome_for(outcomes, "a07-hardcoded-secrets", "A7") == [Outcome.FALSE_NEGATIVE]
    assert m.false_positives == 1
    assert m.true_positives == 0
    assert m.recall_per_class["A7"] == 0.0
    # c01 declares nothing, so this is not a near miss: there is no right
    # answer on that server to have nearly hit.
    assert m.near_miss_count == 0


def test_worked_example_3_tolerated_pattern_leaves_precision_untouched(mini):
    """3. Scanner reports A7 on the benign control that tolerates A7.
    Outcome: tolerated. Precision unaffected in either direction."""
    baseline = [mf("a07-hardcoded-secrets", "A7")]
    with_tolerated = baseline + [mf("c03-release-runner", "A7")]

    _, m0 = score_run(mini, baseline, BOTH)
    outcomes, m1 = score_run(mini, with_tolerated, BOTH)

    assert outcome_for(outcomes, "c03-release-runner", "A7") == [Outcome.TOLERATED]
    assert m1.tolerated_count == 1
    assert m1.false_positives == 0
    assert m1.true_positives == m0.true_positives
    assert m1.precision_overall == m0.precision_overall == 1.0
    assert m1.recall_overall == m0.recall_overall


def test_worked_example_4_novel_true_finding_is_unmapped_and_costs_nothing(mini):
    """4. Scanner reports a real flaw we did not plant and did not define.
    Outcome: unmapped, no penalty, taxonomy review triggered."""
    findings = [
        mf("a07-hardcoded-secrets", "A7"),
        mf(None, None, label="SUPPLY-CHAIN/unpinned-transitive-dep"),
    ]
    outcomes, m = score_run(mini, findings, BOTH)

    assert [o.outcome for o in outcomes if o.attack_class is None] == [Outcome.UNMAPPED]
    assert m.unmapped_count == 1
    assert m.false_positives == 0
    # Excluded from BOTH terms of precision: one TP, one unmapped -> 1.0.
    assert m.precision_overall == 1.0


def test_worked_example_5_static_tool_runtime_class_is_not_attempted(mini):
    """5. A static-only scanner does not detect A6. Outcome: not attempted,
    excluded from its Stage 2 denominator. Not a false negative."""
    findings = [mf(i.server_id, i.attack_class, stage="static")
                for i in mini.items if "static" in i.surfaces]
    outcomes, m = score_run(mini, findings, ["static"])

    assert outcome_for(outcomes, "a06-authless-endpoint", "A6") == [Outcome.NOT_ATTEMPTED]
    assert "a06-authless-endpoint:A6" in m.not_attempted
    assert m.false_negatives == 0
    # A6 had no attempted item, so it has no recall -- not zero recall.
    assert m.recall_per_class["A6"] is None
    assert m.recall_overall == 1.0
    assert m.precision_overall == 1.0


def test_worked_example_6_rug_pull_found_statically_is_a_true_positive(mini):
    """6. Scanner flags the call-count branch in source without ever
    connecting. True positive on A2, stage_credited: static."""
    outcomes, m = score_run(
        mini, [mf("a02-rug-pull", "A2", stage="static")], ["static"])

    a2 = [o for o in outcomes if o.server_id == "a02-rug-pull"]
    assert len(a2) == 1
    assert a2[0].outcome == Outcome.TRUE_POSITIVE
    assert a2[0].stage_credited == "static"
    assert m.recall_per_class["A2"] == 1.0
    assert m.true_positives == 1


def test_a2_credit_counts_once_when_reported_in_both_stages(mini):
    """"A2 appears in both; credit from either stage counts once."" """
    outcomes, m = score_run(mini, [
        mf("a02-rug-pull", "A2", stage="static"),
        mf("a02-rug-pull", "A2", stage="runtime"),
    ], BOTH)
    assert len([o for o in outcomes if o.server_id == "a02-rug-pull"]) == 1
    assert m.true_positives == 1
    assert m.recall_per_class["A2"] == 1.0


# --------------------------------------------------------------------------
# edge cases
# --------------------------------------------------------------------------

def test_no_findings_is_all_false_negatives_and_undefined_precision(mini):
    outcomes, m = score_run(mini, [], BOTH)
    assert m.true_positives == 0
    assert m.false_negatives == len(mini.items)
    assert m.recall_overall == 0.0
    # TP + FP == 0: precision is undefined, not zero.
    assert m.precision_overall is None
    assert all(o.outcome == Outcome.FALSE_NEGATIVE for o in outcomes)


def test_duplicate_findings_on_one_item_collapse_to_one_outcome(mini):
    dupes = [mf("a07-hardcoded-secrets", "A7", label=f"rule-{i}") for i in range(6)]
    outcomes, m = score_run(mini, dupes, BOTH)

    scored = [o for o in outcomes if o.server_id == "a07-hardcoded-secrets"]
    assert len(scored) == 1
    assert scored[0].outcome == Outcome.TRUE_POSITIVE
    assert m.true_positives == 1
    assert m.precision_overall == 1.0
    assert "6 findings collapsed" in scored[0].note


def test_duplicate_false_positives_also_collapse_to_one_item(mini):
    dupes = [mf("c01-notes-workspace", "A7", label=f"rule-{i}") for i in range(4)]
    _, m = score_run(mini, dupes, BOTH)
    assert m.false_positives == 1


def test_finding_on_a_server_that_does_not_exist(mini):
    """Underspecified in docs/scoring.md; read literally, the pair is neither
    declared nor tolerated, so it is a false positive -- and never a near miss,
    since an unknown server declares nothing."""
    outcomes, m = score_run(mini, [mf("z99-not-a-server", "A7")], BOTH)
    stray = [o for o in outcomes if o.server_id == "z99-not-a-server"]
    assert stray[0].outcome == Outcome.FALSE_POSITIVE
    assert "not in the corpus" in stray[0].note
    assert m.false_positives == 1
    assert m.near_miss_count == 0


def test_class_with_an_empty_denominator_is_none_not_zero(mini):
    _, m = score_run(mini, [], BOTH)
    # No server in the mini corpus declares A5.
    assert m.recall_per_class["A5"] is None
    # "no items" and "found none of the items" must not collapse into one value.
    assert m.recall_per_class["A5"] != 0.0
    # A class that does have an item, and was missed, is 0.0.
    assert m.recall_per_class["A1"] == 0.0


def test_finding_on_a_not_applicable_class_is_neither_tp_nor_fp(mini):
    outcomes, m = score_run(mini, [mf("c04-status-service", "A6")], BOTH)
    assert outcome_for(outcomes, "c04-status-service", "A6") == [Outcome.NOT_APPLICABLE]
    assert m.false_positives == 0
    assert m.true_positives == 0
    assert m.precision_overall is None


def test_unmapped_findings_are_excluded_from_both_precision_terms(mini):
    findings = [mf(None, None, label=f"FOREIGN-{i}") for i in range(10)]
    _, m = score_run(mini, findings, BOTH)
    assert m.unmapped_count == 10
    assert m.precision_overall is None
    assert m.false_positives == 0


def test_not_attempted_items_are_excluded_from_recall_overall(mini):
    """A static-only scanner finding nothing is scored on its static items
    only: its runtime-only items never enter the denominator."""
    _, m = score_run(mini, [], ["static"])
    static_items = [i for i in mini.items if "static" in i.surfaces]
    assert m.false_negatives == len(static_items)
    assert len(m.not_attempted) == len(mini.items) - len(static_items)
    assert m.recall_overall == 0.0


def test_correct_find_outside_declared_stages_is_still_credited(mini):
    """Underspecified: `not attempted` exists so a tool is not penalised, so a
    correct find is credited even when the adapter did not declare that stage."""
    outcomes, m = score_run(
        mini, [mf("a06-authless-endpoint", "A6", stage="runtime")], ["static"])
    a6 = [o for o in outcomes if o.server_id == "a06-authless-endpoint"]
    assert a6[0].outcome == Outcome.TRUE_POSITIVE
    assert "a06-authless-endpoint:A6" not in m.not_attempted
    assert m.recall_per_class["A6"] == 1.0


def test_unknown_stage_is_rejected(mini):
    with pytest.raises(ValueError):
        score_run(mini, [], ["stage-3"])
    with pytest.raises(ValueError):
        score_run(mini, [], [])


def test_no_composite_score_is_exposed_anywhere(mini):
    """docs/scoring.md#no-composite-index. A composite would be a governance
    violation, so its absence is asserted rather than assumed."""
    _, m = score_run(mini, [], BOTH)
    banned = ("score", "index", "grade", "rank", "f1", "composite")
    assert not [f for f in vars(m) if any(b in f.lower() for b in banned)]


# --------------------------------------------------------------------------
# fixtures: synthetic scanners whose correct score is known in advance
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def real() -> Corpus:
    return load_corpus()


def _run(adapter, corpus: Corpus):
    return score_run(corpus, identity_map(adapter.all_findings(corpus)), adapter.stages)


def test_fixture_oracle_scores_perfectly(real):
    outcomes, m = _run(OracleAdapter(), real)
    assert m.recall_overall == 1.0
    assert m.precision_overall == 1.0
    assert m.true_positives == len(real.items)
    assert m.false_negatives == 0
    assert m.false_positives == 0
    assert m.near_miss_count == 0
    assert m.unmapped_count == 0
    assert m.not_attempted == []
    for cls, r in m.recall_per_class.items():
        assert r in (1.0, None), cls
    assert all(o.outcome == Outcome.TRUE_POSITIVE for o in outcomes)


def test_fixture_overflagger_has_full_recall_and_floored_precision(real):
    """The controls exist to punish flagging everything. If this precision is
    not low, the controls are not working."""
    _, m = _run(OverflaggerAdapter(), real)

    assert m.recall_overall == 1.0
    assert m.false_negatives == 0

    # Recompute the expectation straight from ground truth, independently of
    # the scorer, so the assertion survives the corpus growing.
    declared = {i.key for i in real.items}
    expected_fp = 0
    for sid, s in real.servers.items():
        for cls in ("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10"):
            if (sid, cls) in declared or cls in s.tolerated or cls in s.not_applicable:
                continue
            expected_fp += 1
    assert m.false_positives == expected_fp
    assert m.precision_overall == pytest.approx(
        len(declared) / (len(declared) + expected_fp))
    assert m.precision_overall < 0.25
    assert m.near_miss_count > 0  # every wrong class on a vulnerable server


def test_fixture_static_only_is_not_penalised_for_stage_two(real):
    adapter = StaticOnlyAdapter()
    _, m = _run(adapter, real)

    static_items = [i for i in real.items if "static" in i.surfaces]
    runtime_only = [i for i in real.items if "static" not in i.surfaces]

    assert m.true_positives == len(static_items)
    assert m.false_negatives == 0
    assert m.false_positives == 0
    assert m.recall_overall == 1.0
    assert m.precision_overall == 1.0
    assert sorted(m.not_attempted) == sorted(
        f"{i.server_id}:{i.attack_class}" for i in runtime_only)
    for i in runtime_only:
        # Runtime-only classes have no denominator here, so no recall at all.
        if not any(x.attack_class == i.attack_class and "static" in x.surfaces
                   for x in real.items):
            assert m.recall_per_class[i.attack_class] is None


def test_fixture_static_only_refuses_the_runtime_stage(real):
    from runner.adapters import RuntimeTarget
    with pytest.raises(NotImplementedError):
        StaticOnlyAdapter().run_runtime(RuntimeTarget(
            server_id="a06-authless-endpoint", url="http://localhost:8106",
            token=None, authenticated=False))


def test_fixture_foreign_taxonomy_is_all_unmapped_and_costs_nothing(real):
    adapter = ForeignTaxonomyAdapter()
    findings = adapter.all_findings(real)
    _, m = _run(adapter, real)

    assert m.unmapped_count == len(findings) == len(real.servers)
    assert m.true_positives == 0
    assert m.false_positives == 0
    assert m.near_miss_count == 0
    # No penalty: precision is undefined, not zero.
    assert m.precision_overall is None
    assert m.recall_overall == 0.0


def test_fixture_near_miss_earns_no_credit_and_populates_the_counter(real):
    outcomes, m = _run(NearMissAdapter(), real)

    assert m.true_positives == 0
    assert m.recall_overall == 0.0
    assert m.precision_overall == 0.0
    assert m.false_negatives == len(real.items)
    assert m.false_positives > 0
    assert m.near_miss_count == m.false_positives
    assert all(r in (0.0, None) for r in m.recall_per_class.values())
    near = [o for o in outcomes if "near miss" in o.note]
    assert len(near) == m.near_miss_count


# --------------------------------------------------------------------------
# aggregation across N runs
# --------------------------------------------------------------------------

def _metrics(per_class: dict[str, float | None], *, recall=None, precision=None,
             near_miss=0, unmapped=0) -> RunMetrics:
    return RunMetrics(
        recall_per_class=per_class, recall_overall=recall,
        precision_overall=precision, true_positives=0, false_negatives=0,
        false_positives=0, tolerated_count=0, unmapped_count=unmapped,
        near_miss_count=near_miss)


def test_aggregate_reports_mean_and_range_never_a_single_run():
    runs = [
        _metrics({"A1": 0.0}, recall=0.0, precision=0.5, near_miss=1, unmapped=2),
        _metrics({"A1": 0.5}, recall=0.5, precision=0.5, near_miss=3, unmapped=0),
        _metrics({"A1": 1.0}, recall=1.0, precision=0.5, near_miss=2, unmapped=4),
    ]
    rep = aggregate(runs, scanner_id="s", stages_attempted=["static"])

    assert rep.runs == 3
    assert rep.recall_per_class_mean["A1"] == pytest.approx(0.5)
    assert rep.recall_per_class_range["A1"] == (0.0, 1.0)
    assert rep.recall_overall_mean == pytest.approx(0.5)
    assert rep.recall_overall_range == (0.0, 1.0)
    assert rep.precision_mean == 0.5
    assert rep.precision_range == (0.5, 0.5)
    assert rep.near_miss_mean == pytest.approx(2.0)
    assert rep.unmapped_mean == pytest.approx(2.0)
    assert any("N >= 5" in n for n in rep.notes)


def test_high_variance_flag_is_exclusive_at_exactly_twenty_points():
    assert VARIANCE_THRESHOLD == 0.20
    # Exactly 20 points: the spec says "exceeds", so this is not flagged. The
    # subtraction 0.8 - 0.6 is not exactly 0.2 in binary floating point, which
    # is precisely why the comparison carries a tolerance.
    at = aggregate([_metrics({"A1": 0.6}), _metrics({"A1": 0.8})], scanner_id="s")
    assert at.variance_detail["A1"] == pytest.approx(0.20)
    assert at.high_variance is False

    over = aggregate([_metrics({"A1": 0.6}), _metrics({"A1": 0.81})], scanner_id="s")
    assert over.high_variance is True

    under = aggregate([_metrics({"A1": 0.6}), _metrics({"A1": 0.79})], scanner_id="s")
    assert under.high_variance is False


def test_high_variance_triggers_on_any_single_class():
    runs = [
        _metrics({"A1": 1.0, "A7": 0.0}, recall=0.5),
        _metrics({"A1": 1.0, "A7": 1.0}, recall=1.0),
    ]
    rep = aggregate(runs, scanner_id="s")
    assert rep.variance_detail["A1"] == 0.0
    assert rep.variance_detail["A7"] == 1.0
    assert rep.high_variance is True


def test_deterministic_scanner_reports_zero_variance_as_a_finding():
    runs = [_metrics({"A1": 1.0, "A7": 0.5}, recall=0.75, precision=1.0)
            for _ in range(5)]
    rep = aggregate(runs, scanner_id="s")

    assert rep.high_variance is False
    # Zero variance is representable and distinct from missing data.
    assert rep.variance_detail["A1"] == 0.0
    assert rep.variance_detail["A7"] == 0.0
    assert rep.recall_per_class_range["A1"] == (1.0, 1.0)
    assert is_deterministic(rep) is True
    assert any("zero variance" in n for n in rep.notes)
    assert not any("N >= 5" in n for n in rep.notes)


def test_a_class_with_no_attempted_items_stays_none_and_does_not_drag_the_mean():
    runs = [_metrics({"A1": 1.0, "A6": None}) for _ in range(5)]
    rep = aggregate(runs, scanner_id="s")

    assert rep.recall_per_class_mean["A6"] is None
    assert rep.recall_per_class_range["A6"] is None
    # Missing data is absent from variance_detail; zero variance is a 0.0 in it.
    assert "A6" not in rep.variance_detail
    assert rep.variance_detail["A1"] == 0.0
    assert is_deterministic(rep) is True


def test_mean_skips_none_runs_rather_than_counting_them_as_zero():
    runs = [_metrics({"A1": None}), _metrics({"A1": 1.0}), _metrics({"A1": 1.0})]
    rep = aggregate(runs, scanner_id="s")
    assert rep.recall_per_class_mean["A1"] == 1.0
    assert rep.recall_per_class_range["A1"] == (1.0, 1.0)
    assert any("attempted in 2/3 runs" in n for n in rep.notes)


def test_mean_range_helper_on_empty_and_all_none():
    assert mean_range([]) == (None, None)
    assert mean_range([None, None]) == (None, None)
    assert mean_range([0.0, 1.0]) == (0.5, (0.0, 1.0))


def test_aggregate_refuses_zero_runs():
    with pytest.raises(ValueError):
        aggregate([], scanner_id="s")


def test_unmeasured_scanner_is_not_called_deterministic():
    rep = aggregate([_metrics({"A1": None}) for _ in range(5)], scanner_id="s")
    assert rep.variance_detail == {}
    assert is_deterministic(rep) is False
    assert rep.high_variance is False


def test_aggregating_real_fixture_runs_end_to_end(real):
    """The oracle is deterministic by construction: five runs, zero variance."""
    runs = []
    for _ in range(5):
        _, m = _run(OracleAdapter(), real)
        runs.append(m)
    rep = aggregate(runs, scanner_id="fixture-oracle",
                    corpus_version=real.version, stages_attempted=["static", "runtime"])
    assert rep.recall_overall_mean == 1.0
    assert rep.recall_overall_range == (1.0, 1.0)
    assert rep.precision_mean == 1.0
    assert rep.high_variance is False
    assert is_deterministic(rep) is True
