"""Core data model for the runner.

Every type here is fixed by docs/scoring.md. If a change to this file would
change a published number, it is a governance amendment, not a refactor.

The flow is one direction:

    raw scanner output
      -> RawFinding      (adapter parses; still the scanner's own vocabulary)
      -> MappedFinding   (mapping layer; now our taxonomy, or unmapped)
      -> ItemOutcome     (scoring; ground truth applied)
      -> RunMetrics      (one run)
      -> ScannerReport   (N runs, mean and range)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

Stage = Literal["static", "runtime"]

CLASSES: tuple[str, ...] = (
    "A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10",
)

# From docs/taxonomy.md. Which stage can credit which class.
CLASS_STAGES: dict[str, set[str]] = {
    "A1": {"static"},
    "A2": {"static", "runtime"},
    "A3": {"static"},
    "A4": {"runtime"},
    "A5": {"runtime"},
    "A6": {"runtime"},
    "A7": {"static"},
    "A8": {"static"},
    "A9": {"static"},
    "A10": {"static"},
}


class Outcome(str, Enum):
    """The seven outcomes in docs/scoring.md, plus NOT_ATTEMPTED.

    Only TRUE_POSITIVE, FALSE_NEGATIVE and FALSE_POSITIVE move recall or
    precision. The rest exist so that information is preserved without being
    silently folded into a headline number.
    """

    TRUE_POSITIVE = "true_positive"
    FALSE_NEGATIVE = "false_negative"
    FALSE_POSITIVE = "false_positive"
    TOLERATED = "tolerated"
    UNMAPPED = "unmapped"
    NOT_APPLICABLE = "not_applicable"
    NOT_ATTEMPTED = "not_attempted"


@dataclass(frozen=True)
class CorpusItem:
    """One (server, class) pair declared in a manifest. The atom of scoring."""

    server_id: str
    attack_class: str
    surfaces: frozenset[str]
    variant: str | None = None

    @property
    def key(self) -> tuple[str, str]:
        return (self.server_id, self.attack_class)


@dataclass
class RawFinding:
    """One finding, still in the scanner's own vocabulary.

    `raw_label` is whatever the scanner called it -- its rule id, check name, or
    category. The mapping layer's whole job is turning this into one of ours,
    and `raw_label` is what a mapping decision is keyed on, so adapters must
    preserve it verbatim rather than normalising it.
    """

    scanner_id: str
    raw_label: str
    server_id: str | None = None
    file: str | None = None
    line: int | None = None
    message: str = ""
    severity: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class MappedFinding:
    """A RawFinding after the mapping layer has placed it, or failed to."""

    finding: RawFinding
    mapped_class: str | None
    mapped_server: str | None
    mapping_rationale_id: str | None = None

    @property
    def is_mapped(self) -> bool:
        return self.mapped_class is not None and self.mapped_server is not None


@dataclass
class ItemOutcome:
    """The scored result for one (server, class), or one stray finding."""

    server_id: str
    attack_class: str | None
    outcome: Outcome
    stage_credited: str | None = None
    finding_ref: str | None = None
    note: str = ""


@dataclass
class RunMetrics:
    """Metrics for a single run of one scanner.

    Deliberately absent: any composite score, ranking index, or grade. See
    docs/scoring.md -- weighting classes against each other is an editorial
    claim this project does not make.
    """

    recall_per_class: dict[str, float | None]
    recall_overall: float | None
    precision_overall: float | None
    true_positives: int
    false_negatives: int
    false_positives: int
    tolerated_count: int
    unmapped_count: int
    near_miss_count: int
    not_attempted: list[str] = field(default_factory=list)


@dataclass
class ScannerRun:
    """One execution of one scanner in one stage."""

    scanner_id: str
    scanner_version: str
    adapter_version: str
    config_label: str
    stage: str
    run_index: int
    corpus_version: str
    requires_signup: bool
    findings: list[RawFinding] = field(default_factory=list)
    duration_seconds: float | None = None
    exit_code: int | None = None
    error: str | None = None


@dataclass
class ScannerReport:
    """Aggregate across N runs. This is what the scoreboard renders.

    Never a single run: several scanners use LLM-as-judge analyzers and vary run
    to run, so docs/scoring.md requires mean and range over N >= 5.
    """

    scanner_id: str
    scanner_version: str
    adapter_version: str
    config_label: str
    corpus_version: str
    requires_signup: bool
    stages_attempted: list[str]
    runs: int
    recall_per_class_mean: dict[str, float | None]
    recall_per_class_range: dict[str, tuple[float, float] | None]
    recall_overall_mean: float | None
    recall_overall_range: tuple[float, float] | None
    precision_mean: float | None
    precision_range: tuple[float, float] | None
    near_miss_mean: float
    unmapped_mean: float
    high_variance: bool
    variance_detail: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    #: Set when the scanner could not be run at all. The row is still published
    #: carrying this reason -- omitting it would silently turn "we could not run
    #: this" into "this was not considered", which is not a neutral act.
    unavailable_reason: str | None = None
