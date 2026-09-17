"""The credit rules for a single run.

This module is the literal implementation of `docs/scoring.md`. Every branch
below corresponds to a sentence there; where the spec is silent the code says
so in a comment and picks the reading that cannot be mistaken for a judgment
about a scanner's quality.

Two invariants hold everywhere:

1. **The atom is an item** -- a `(server, class)` pair. Findings are collapsed
   to items before anything is counted, so a scanner that reports the same flaw
   six times has found one item.
2. **No composite.** Recall and precision are reported side by side and never
   combined. Adding a single score, index, or grade here would be a governance
   violation, not a feature; see `docs/scoring.md#no-composite-index`.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from .corpus import Corpus
from .models import (
    CLASSES,
    CorpusItem,
    ItemOutcome,
    MappedFinding,
    Outcome,
    RunMetrics,
)

ALL_STAGES: frozenset[str] = frozenset({"static", "runtime"})

ItemKey = tuple[str, str]


def _finding_ref(mf: MappedFinding) -> str:
    """A short, stable pointer back to the finding that produced an outcome."""
    f = mf.finding
    parts = [f.scanner_id or "?", f.raw_label]
    if f.file:
        parts.append(f"{f.file}:{f.line}" if f.line is not None else f.file)
    return "|".join(parts)


def _stage_credited(item: CorpusItem, mf: MappedFinding, stages: frozenset[str]) -> str:
    """Which stage gets credit for finding `item`.

    docs/scoring.md: "A2 appears in both; credit from either stage counts once,
    and the results record which stage produced it." Nothing in the model
    An adapter states the stage on `RawFinding.stage`; the older
    `raw["stage"]` convention is still honoured. Absent either, the stage is
    derived: if only one surface of the item is in play there is no ambiguity,
    and if both are, the earlier stage is recorded (worked example 6 credits
    the static route).
    """
    usable = set(item.surfaces) & stages
    hint = getattr(mf.finding, "stage", None)
    if hint not in usable and isinstance(mf.finding.raw, dict):
        hint = mf.finding.raw.get("stage")
    if hint in usable:
        return str(hint)
    if len(usable) == 1:
        return next(iter(usable))
    if usable:
        return "static" if "static" in usable else sorted(usable)[0]
    # Found on a surface the scanner said it would not attempt: see the
    # not-attempted handling in score_run.
    if hint in item.surfaces:
        return str(hint)
    return "static" if "static" in item.surfaces else sorted(item.surfaces)[0]


def collapse(mapped_findings: Iterable[MappedFinding]) -> tuple[
    dict[ItemKey, MappedFinding], dict[ItemKey, int], list[MappedFinding]
]:
    """Collapse findings to items.

    Returns (first finding per item, how many findings hit that item, the
    findings the mapping layer could not place).

    "Duplicate findings mapping to the same item collapse to one outcome."
    The *first* finding is kept so `finding_ref` points somewhere real and the
    result is order-deterministic. Unmapped findings cannot be collapsed --
    they have no item to collapse onto -- so they are counted per finding.
    """
    placed: dict[ItemKey, MappedFinding] = {}
    counts: dict[ItemKey, int] = {}
    unmapped: list[MappedFinding] = []
    for mf in mapped_findings:
        if not mf.is_mapped:
            unmapped.append(mf)
            continue
        key: ItemKey = (str(mf.mapped_server), str(mf.mapped_class))
        counts[key] = counts.get(key, 0) + 1
        placed.setdefault(key, mf)
    return placed, counts, unmapped


def score_run(
    corpus: Corpus,
    mapped_findings: Sequence[MappedFinding],
    stages_attempted: Iterable[str] | None = None,
) -> tuple[list[ItemOutcome], RunMetrics]:
    """Score one run of one scanner.

    `stages_attempted` is what the adapter declares it attempts. Items on a
    stage the scanner does not attempt are `not_attempted`, excluded from the
    denominator, and explicitly NOT false negatives (worked example 5).
    """
    stages = ALL_STAGES if stages_attempted is None else frozenset(stages_attempted)
    bad = stages - ALL_STAGES
    if bad:
        raise ValueError(f"unknown stage(s): {sorted(bad)}")
    if not stages:
        raise ValueError("a scanner must attempt at least one stage")

    placed, dup_counts, unmapped = collapse(mapped_findings)

    declared: dict[ItemKey, CorpusItem] = {item.key: item for item in corpus.items}

    outcomes: list[ItemOutcome] = []
    tp_keys: set[ItemKey] = set()
    fn_keys: set[ItemKey] = set()
    not_attempted_keys: set[ItemKey] = set()

    # --- declared items -------------------------------------------------
    for key in sorted(declared):
        item = declared[key]
        server_id, cls = key
        attempted = bool(item.surfaces & stages)
        mf = placed.get(key)

        if mf is not None:
            # A true positive: right server, right class.
            #
            # If the item's surfaces do not intersect the attempted stages but
            # the scanner reported it anyway, the spec has nothing to say --
            # `not attempted` exists to avoid penalising a tool, and withholding
            # credit for a correct find would be a penalty. The item is scored
            # as found and leaves the not-attempted list.
            tp_keys.add(key)
            note = "" if attempted else (
                "credited although the adapter does not declare this stage")
            outcomes.append(ItemOutcome(
                server_id=server_id,
                attack_class=cls,
                outcome=Outcome.TRUE_POSITIVE,
                stage_credited=_stage_credited(item, mf, stages),
                finding_ref=_finding_ref(mf),
                note=note + (f" ({dup_counts[key]} findings collapsed)"
                             if dup_counts.get(key, 0) > 1 else ""),
            ))
        elif attempted:
            fn_keys.add(key)
            outcomes.append(ItemOutcome(
                server_id=server_id,
                attack_class=cls,
                outcome=Outcome.FALSE_NEGATIVE,
                stage_credited=None,
                finding_ref=None,
            ))
        else:
            not_attempted_keys.add(key)
            outcomes.append(ItemOutcome(
                server_id=server_id,
                attack_class=cls,
                outcome=Outcome.NOT_ATTEMPTED,
                stage_credited=None,
                finding_ref=None,
                note=(f"reachable only from {sorted(item.surfaces)}; "
                      f"scanner attempts {sorted(stages)}"),
            ))

    # --- mapped findings that are not declared items --------------------
    fp_count = 0
    tolerated_count = 0
    near_miss_count = 0
    for key in sorted(k for k in placed if k not in declared):
        server_id, cls = key
        mf = placed[key]
        ref = _finding_ref(mf)
        known_server = server_id in corpus.servers

        if known_server and corpus.is_tolerated(server_id, cls):
            tolerated_count += 1
            outcomes.append(ItemOutcome(
                server_id=server_id, attack_class=cls,
                outcome=Outcome.TOLERATED, finding_ref=ref,
                note="in the server's frozen tolerated set",
            ))
            continue

        if known_server and corpus.is_not_applicable(server_id, cls):
            # "A finding reported on an n/a class is likewise neither TP nor FP."
            outcomes.append(ItemOutcome(
                server_id=server_id, attack_class=cls,
                outcome=Outcome.NOT_APPLICABLE, finding_ref=ref,
                note="class the server cannot structurally exhibit",
            ))
            continue

        fp_count += 1
        note = ""
        if not known_server:
            # Underspecified in docs/scoring.md. Read literally: the pair is
            # neither declared nor tolerated, so it is a false positive.
            note = "server is not in the corpus"
        elif corpus.declares_anything(server_id):
            # Near miss: right server, wrong class, server declares something.
            # Scored as a false positive here; the false negative on the
            # declared class falls out of the declared-item pass above, which
            # is the only self-consistent reading given that one item has
            # exactly one outcome.
            near_miss_count += 1
            note = ("near miss: right server, wrong class; declared "
                    f"{sorted(corpus.declared_classes(server_id))}")
        outcomes.append(ItemOutcome(
            server_id=server_id, attack_class=cls,
            outcome=Outcome.FALSE_POSITIVE, finding_ref=ref, note=note,
        ))

    # --- unmapped -------------------------------------------------------
    for mf in unmapped:
        outcomes.append(ItemOutcome(
            server_id=mf.mapped_server or mf.finding.server_id or "?",
            attack_class=None,
            outcome=Outcome.UNMAPPED,
            finding_ref=_finding_ref(mf),
            note=f"raw_label={mf.finding.raw_label!r} not placed in the taxonomy",
        ))

    metrics = _metrics(
        corpus=corpus,
        declared=declared,
        tp_keys=tp_keys,
        fn_keys=fn_keys,
        not_attempted_keys=not_attempted_keys,
        fp_count=fp_count,
        tolerated_count=tolerated_count,
        unmapped_count=len(unmapped),
        near_miss_count=near_miss_count,
    )
    return outcomes, metrics


def _metrics(
    *,
    corpus: Corpus,
    declared: dict[ItemKey, CorpusItem],
    tp_keys: set[ItemKey],
    fn_keys: set[ItemKey],
    not_attempted_keys: set[ItemKey],
    fp_count: int,
    tolerated_count: int,
    unmapped_count: int,
    near_miss_count: int,
) -> RunMetrics:
    """Recall per class, recall overall, precision overall. Nothing else.

    `None` rather than `0.0` whenever a denominator is empty: "no items" and
    "found none of the items" are different facts, and collapsing them would
    let an empty class masquerade as a total failure (or, once averaged, drag a
    mean toward zero for a class that was never in play).
    """
    recall_per_class: dict[str, float | None] = {}
    for cls in CLASSES:
        denom = 0
        num = 0
        for key, item in declared.items():
            if item.attack_class != cls:
                continue
            if key in not_attempted_keys:
                continue
            if corpus.is_not_applicable(key[0], cls):
                continue  # defensive: declared and n/a is a manifest error
            denom += 1
            if key in tp_keys:
                num += 1
        recall_per_class[cls] = (num / denom) if denom else None

    attempted_total = len(tp_keys) + len(fn_keys)
    recall_overall = (len(tp_keys) / attempted_total) if attempted_total else None

    precision_denom = len(tp_keys) + fp_count
    precision_overall = (len(tp_keys) / precision_denom) if precision_denom else None

    return RunMetrics(
        recall_per_class=recall_per_class,
        recall_overall=recall_overall,
        precision_overall=precision_overall,
        true_positives=len(tp_keys),
        false_negatives=len(fn_keys),
        false_positives=fp_count,
        tolerated_count=tolerated_count,
        unmapped_count=unmapped_count,
        near_miss_count=near_miss_count,
        not_attempted=[f"{s}:{c}" for s, c in sorted(not_attempted_keys)],
    )
