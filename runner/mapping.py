"""The taxonomy mapping layer.

Scanners describe MCP flaws in their own vocabularies, and those vocabularies
are largely disjoint from each other and from ours. This module is the one
place where a scanner's label becomes a class in docs/taxonomy.md -- or is
recorded as `unmapped`, which is a first-class outcome and not a failure.

Three rules govern everything here, and they are rules rather than preferences
because the mapping layer is where a benchmark can most easily cheat:

1. **Never guess.** A label with no mapping entry produces a MappedFinding with
   ``mapped_class=None``. Per docs/scoring.md that is scored `unmapped` and
   costs the scanner neither a true positive nor a false positive. Inferring a
   class -- from the finding's message text, from the server it landed on, from
   what would make a tool look good -- is the exact failure mode this project
   exists to measure, so the mechanism cannot do it even if asked.

2. **Match exactly.** Lookup is byte-exact on ``RawFinding.raw_label`` by
   default. A mapping file may opt into exactly two normalizations, declared in
   its ``matching`` block: ``strip_surrounding_whitespace`` and
   ``case_insensitive``. Nothing else exists. Substring, stemmed, or fuzzy
   matching would make a mapping table impossible to review line by line, and
   an unreviewable table cannot be disputed, which is what governance.md
   promises vendors it can be.

3. **Show the gaps.** Labels seen in real output with no entry are collected,
   counted and reported (:meth:`MappingReport.gap_report`), never silently
   dropped. A gap is a claim about our taxonomy that a reader is entitled to
   check.

Mapping decisions are keyed on the LABEL and on nothing else -- never on which
server the finding landed on. Server resolution happens independently, from the
path the scanner reported, and the two results are combined at the end.

See docs/mapping-rationale.md for the decision procedure the files encode, and
mapping/schema.json for the file format.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .models import CLASSES, MappedFinding, RawFinding

ROOT = Path(__file__).resolve().parent.parent
MAPPING_DIR = ROOT / "mapping"
SCHEMA_PATH = MAPPING_DIR / "schema.json"

#: Labels are looked up under one of these scopes. "any" is the default and the
#: overwhelmingly common case; the stage scopes exist so that a single vendor
#: label covering two of our classes can be split on a fact the runner records
#: (which stage produced the finding) rather than on a judgment about the
#: finding's prose. See rule R3 in docs/mapping-rationale.md.
STAGE_SCOPES = ("any", "static", "runtime")


class MappingError(RuntimeError):
    """A mapping file is malformed, ambiguous, or used in a way that would
    silently corrupt a published number.

    Always raised, never warned: a mapping bug does not announce itself in the
    output, it just moves a scanner's score.
    """


# --------------------------------------------------------------------------
# File format
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class MappingEntry:
    """One decision about one scanner label.

    ``mapped_class is None`` means we looked at this label and decided not to
    place it. That is a different thing from never having seen the label, and
    the two are kept distinct all the way to the report: a deliberate
    non-mapping still carries its ``rationale_id``, so a reader can find the
    reasoning behind the blank.
    """

    raw_label: str
    decision: str  # "map" | "unmapped"
    mapped_class: str | None
    rationale_id: str
    rationale: str
    confidence: str
    decided_on: str
    decided_by: str
    applies_to_stage: str = "any"
    unmapped_reason: str | None = None
    status: str = "accepted"
    dispute_risk: str | None = None
    illustrative: bool = False
    label_note: str | None = None
    taxonomy_evidence: Mapping[str, Any] | None = None
    considered_classes: tuple[Mapping[str, Any], ...] = ()
    resolution_rules: tuple[str, ...] = ()
    reviewed_by: tuple[str, ...] = ()
    dispute: Mapping[str, Any] | None = None
    history: tuple[Mapping[str, Any], ...] = ()

    @property
    def is_disputed(self) -> bool:
        return self.status == "disputed" or self.dispute is not None

    @property
    def publishes_both_positions(self) -> bool:
        """True when governance.md's both-positions outcome applies.

        We were not persuaded, the mapping stands, and the vendor's reading is
        published beside ours on the scoreboard row rather than replaced by our
        resolution of it.
        """
        return bool(self.dispute) and self.dispute.get("outcome") == "both-positions-published"

    @property
    def vendor_proposed_class(self) -> str | None:
        return self.dispute.get("vendor_proposed_class") if self.dispute else None

    @property
    def key(self) -> tuple[str, str]:
        return (self.raw_label, self.applies_to_stage)

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "MappingEntry":
        return cls(
            raw_label=d["raw_label"],
            decision=d["decision"],
            mapped_class=d.get("mapped_class"),
            rationale_id=d["rationale_id"],
            rationale=d["rationale"],
            confidence=d["confidence"],
            decided_on=d["decided_on"],
            decided_by=d["decided_by"],
            applies_to_stage=d.get("applies_to_stage", "any"),
            unmapped_reason=d.get("unmapped_reason"),
            status=d.get("status", "accepted"),
            dispute_risk=d.get("dispute_risk"),
            illustrative=bool(d.get("illustrative", False)),
            label_note=d.get("label_note"),
            taxonomy_evidence=d.get("taxonomy_evidence"),
            considered_classes=tuple(d.get("considered_classes", ())),
            resolution_rules=tuple(d.get("resolution_rules", ())),
            reviewed_by=tuple(d.get("reviewed_by", ())),
            dispute=d.get("dispute"),
            history=tuple(d.get("history", ())),
        )

    def to_dict(self) -> dict[str, Any]:
        """Round-trips back to the on-disk shape, disputes included.

        Used by tests and by the disclosure pack sent to vendors: what they are
        shown has to be exactly what the runner applied.
        """
        out: dict[str, Any] = {
            "raw_label": self.raw_label,
            "applies_to_stage": self.applies_to_stage,
            "decision": self.decision,
            "mapped_class": self.mapped_class,
            "rationale_id": self.rationale_id,
            "rationale": self.rationale,
            "confidence": self.confidence,
            "status": self.status,
            "decided_on": self.decided_on,
            "decided_by": self.decided_by,
        }
        if self.label_note is not None:
            out["label_note"] = self.label_note
        if self.unmapped_reason is not None:
            out["unmapped_reason"] = self.unmapped_reason
        if self.taxonomy_evidence is not None:
            out["taxonomy_evidence"] = dict(self.taxonomy_evidence)
        if self.considered_classes:
            out["considered_classes"] = [dict(c) for c in self.considered_classes]
        if self.resolution_rules:
            out["resolution_rules"] = list(self.resolution_rules)
        if self.dispute_risk is not None:
            out["dispute_risk"] = self.dispute_risk
        if self.illustrative:
            out["illustrative"] = True
        if self.reviewed_by:
            out["reviewed_by"] = list(self.reviewed_by)
        if self.dispute is not None:
            out["dispute"] = dict(self.dispute)
        if self.history:
            out["history"] = [dict(h) for h in self.history]
        return out


@dataclass(frozen=True)
class MatchingPolicy:
    """The only normalization the mapping layer may apply.

    Both flags default off. They exist because some scanners genuinely emit the
    same rule under different casing across versions, and pretending otherwise
    would push adapters into normalising labels themselves -- which is worse,
    because then the normalisation is invisible to review.
    """

    case_insensitive: bool = False
    strip_surrounding_whitespace: bool = False
    note: str | None = None

    @property
    def is_exact(self) -> bool:
        return not (self.case_insensitive or self.strip_surrounding_whitespace)

    def variants(self, label: str) -> list[tuple[str, str]]:
        """Candidate lookup keys for `label`, most exact first.

        Returns (candidate, how) pairs so the report can record that a match
        was not byte-exact. Order matters: an exact hit always wins.
        """
        out = [(label, "exact")]
        stripped = label.strip()
        if self.strip_surrounding_whitespace and stripped != label:
            out.append((stripped, "stripped"))
        if self.case_insensitive:
            out.append((label.casefold(), "casefolded"))
            if self.strip_surrounding_whitespace and stripped != label:
                out.append((stripped.casefold(), "stripped+casefolded"))
        return out


@dataclass
class MappingFile:
    """One scanner's mapping table, loaded and indexed."""

    scanner_id: str
    display_name: str
    label_provenance: str
    label_source_field: str
    matching: MatchingPolicy
    entries: tuple[MappingEntry, ...]
    path: Path | None = None
    scanner_versions: tuple[str, ...] = ()
    adapter_version: str | None = None
    provenance_note: str | None = None
    frozen_for_corpus_version: str | None = None
    notes: tuple[str, ...] = ()
    #: label -> {stage_scope: entry}. Built at load; see _build_index for the
    #: conflicts that are rejected there rather than resolved silently.
    _index: dict[str, dict[str, MappingEntry]] = field(default_factory=dict, repr=False)
    _casefold_index: dict[str, str] = field(default_factory=dict, repr=False)

    @property
    def is_illustrative(self) -> bool:
        return self.label_provenance == "illustrative-placeholder"

    @property
    def disputed_entries(self) -> list[MappingEntry]:
        return [e for e in self.entries if e.is_disputed]

    def entry_by_rationale_id(self, rationale_id: str) -> MappingEntry | None:
        for e in self.entries:
            if e.rationale_id == rationale_id:
                return e
        return None

    def lookup(self, raw_label: str, stage: str | None = None) -> tuple[MappingEntry | None, str]:
        """Find the entry for `raw_label`, or explain why there is none.

        Returns ``(entry, how)`` where `how` is one of:

        ``exact`` / ``stripped`` / ``casefolded`` / ``stripped+casefolded``
            matched, by that route
        ``no-entry``
            the label appears in no entry: a gap in our table, reported
        ``stage-required``
            the label is split across stage-scoped entries (rule R3) and the
            caller did not say which stage produced the finding. We refuse to
            pick one. This is a runner bug when it happens, and it surfaces as
            an unmapped finding plus a loud line in the gap report rather than
            as a coin flip.
        """
        for candidate, how in self.matching.variants(raw_label):
            key = candidate
            if how in ("casefolded", "stripped+casefolded"):
                key = self._casefold_index.get(candidate, "")
            by_stage = self._index.get(key)
            if not by_stage:
                continue
            if "any" in by_stage:
                return by_stage["any"], how
            if stage is None:
                return None, "stage-required"
            entry = by_stage.get(stage)
            if entry is None:
                # Scoped entries exist but none for this stage. Not a guess
                # opportunity: an unmapped finding and a visible gap.
                return None, "no-entry-for-stage"
            return entry, how
        return None, "no-entry"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MappingError(message)


def load_schema(schema_path: Path | None = None) -> dict[str, Any]:
    path = schema_path or SCHEMA_PATH
    try:
        return json.loads(path.read_text())
    except FileNotFoundError as exc:  # pragma: no cover - environment error
        raise MappingError(f"mapping schema not found at {path}") from exc
    except json.JSONDecodeError as exc:
        raise MappingError(f"mapping schema at {path} is not valid JSON: {exc}") from exc


def validate_document(doc: Any, *, source: str, schema: Mapping[str, Any] | None = None) -> None:
    """Validate one mapping document against mapping/schema.json.

    Raises MappingError with the failing JSON path. Loud by design: a mapping
    file that half-loads produces a scoreboard that is wrong in a way nobody
    can see.
    """
    try:
        import jsonschema
    except ModuleNotFoundError as exc:  # pragma: no cover - environment error
        raise MappingError(
            "jsonschema is required to validate mapping files; install it rather "
            "than skipping validation"
        ) from exc

    schema = schema or load_schema()
    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls.check_schema(schema)
    validator = validator_cls(schema)
    errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path))
    if errors:
        first = errors[0]
        where = "/".join(str(p) for p in first.absolute_path) or "<document root>"
        raise MappingError(
            f"{source}: mapping file does not conform to mapping/schema.json "
            f"at {where}: {first.message} ({len(errors)} error(s) total)"
        )


def _build_index(entries: Sequence[MappingEntry], policy: MatchingPolicy,
                 source: str) -> tuple[dict[str, dict[str, MappingEntry]], dict[str, str]]:
    index: dict[str, dict[str, MappingEntry]] = {}
    seen_rationale: dict[str, str] = {}
    for e in entries:
        _require(
            e.applies_to_stage in STAGE_SCOPES,
            f"{source}: entry {e.rationale_id} has unknown applies_to_stage "
            f"{e.applies_to_stage!r}",
        )
        _require(
            e.mapped_class is None or e.mapped_class in CLASSES,
            f"{source}: entry {e.rationale_id} maps to unknown class "
            f"{e.mapped_class!r}",
        )
        _require(
            e.rationale_id not in seen_rationale,
            f"{source}: rationale_id {e.rationale_id} used twice "
            f"(labels {seen_rationale.get(e.rationale_id)!r} and {e.raw_label!r}). "
            "Rationale ids are cited by published numbers and must be unique.",
        )
        seen_rationale[e.rationale_id] = e.raw_label

        by_stage = index.setdefault(e.raw_label, {})
        _require(
            e.applies_to_stage not in by_stage,
            f"{source}: duplicate entry for label {e.raw_label!r} at stage scope "
            f"{e.applies_to_stage!r}. One label, one decision per stage scope.",
        )
        by_stage[e.applies_to_stage] = e

    for label, by_stage in index.items():
        _require(
            not ("any" in by_stage and len(by_stage) > 1),
            f"{source}: label {label!r} has both an 'any' entry and a stage-scoped "
            "entry. Either the label means one thing or it is split by stage; a "
            "mix is ambiguous and would have to be resolved by guessing.",
        )

    casefold_index: dict[str, str] = {}
    if policy.case_insensitive:
        for label in index:
            folded = label.casefold()
            _require(
                folded not in casefold_index or casefold_index[folded] == label,
                f"{source}: case_insensitive matching is on, but labels "
                f"{casefold_index.get(folded)!r} and {label!r} collide when "
                "casefolded. Turn it off or merge the entries.",
            )
            casefold_index[folded] = label
    return index, casefold_index


def load_mapping_file(path: Path, *, schema: Mapping[str, Any] | None = None,
                      allow_illustrative: bool = False) -> MappingFile:
    """Load and validate one mapping file.

    ``allow_illustrative`` must be passed explicitly to load a file whose
    ``label_provenance`` is ``illustrative-placeholder``. Invented labels must
    never reach a scoring run by accident: a scoreboard built on made-up
    vocabulary would be indistinguishable from a real one and would be worse
    than no scoreboard at all.
    """
    try:
        text = path.read_text()
    except FileNotFoundError as exc:
        raise MappingError(f"mapping file not found: {path}") from exc
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MappingError(f"{path}: not valid JSON: {exc}") from exc

    validate_document(doc, source=str(path), schema=schema)

    provenance = doc["label_provenance"]
    if provenance == "illustrative-placeholder" and not allow_illustrative:
        raise MappingError(
            f"{path}: label_provenance is 'illustrative-placeholder'. Its labels are "
            "invented for documentation and must not be used to score anything. Pass "
            "allow_illustrative=True if you are deliberately exercising the format."
        )

    entries = tuple(MappingEntry.from_dict(e) for e in doc["entries"])
    policy = MatchingPolicy(
        case_insensitive=bool(doc["matching"]["case_insensitive"]),
        strip_surrounding_whitespace=bool(doc["matching"]["strip_surrounding_whitespace"]),
        note=doc["matching"].get("note"),
    )
    index, casefold_index = _build_index(entries, policy, source=str(path))

    return MappingFile(
        scanner_id=doc["scanner_id"],
        display_name=doc["display_name"],
        label_provenance=provenance,
        label_source_field=doc["label_source_field"],
        matching=policy,
        entries=entries,
        path=path,
        scanner_versions=tuple(doc.get("scanner_versions", ())),
        adapter_version=doc.get("adapter_version"),
        provenance_note=doc.get("provenance_note"),
        frozen_for_corpus_version=doc.get("frozen_for_corpus_version"),
        notes=tuple(doc.get("notes", ())),
        _index=index,
        _casefold_index=casefold_index,
    )


@dataclass
class MappingRegistry:
    """Every scanner's mapping table, keyed by scanner_id."""

    files: dict[str, MappingFile] = field(default_factory=dict)
    #: (path, reason) for files deliberately not loaded -- currently only
    #: illustrative ones. Surfaced rather than skipped in silence.
    skipped: list[tuple[Path, str]] = field(default_factory=list)

    def __contains__(self, scanner_id: object) -> bool:
        return scanner_id in self.files

    def get(self, scanner_id: str) -> MappingFile | None:
        return self.files.get(scanner_id)

    def require(self, scanner_id: str) -> MappingFile:
        f = self.files.get(scanner_id)
        if f is None:
            raise MappingError(
                f"no mapping file loaded for scanner {scanner_id!r}. Scoring a scanner "
                "with no mapping table would report 0% recall for a tool that was never "
                "mapped, which is a benchmark bug presented as a result."
            )
        return f

    def all_disputed(self) -> list[tuple[str, MappingEntry]]:
        return [(sid, e) for sid, f in sorted(self.files.items())
                for e in f.disputed_entries]


def load_mapping_dir(mapping_dir: Path | None = None, *,
                     allow_illustrative: bool = False) -> MappingRegistry:
    """Load every ``*.json`` mapping file in a directory.

    ``schema.json`` is skipped (it is the schema, not a mapping). Illustrative
    files are skipped unless asked for, and recorded in ``registry.skipped``.
    Anything else that fails to load raises.
    """
    base = mapping_dir or MAPPING_DIR
    if not base.is_dir():
        raise MappingError(f"mapping directory not found: {base}")

    schema = load_schema()
    registry = MappingRegistry()
    for path in sorted(base.glob("*.json")):
        if path.name == "schema.json":
            continue
        try:
            f = load_mapping_file(path, schema=schema, allow_illustrative=allow_illustrative)
        except MappingError as exc:
            if not allow_illustrative and "illustrative-placeholder" in str(exc):
                registry.skipped.append((path, "illustrative placeholder labels"))
                continue
            raise
        if f.scanner_id in registry.files:
            raise MappingError(
                f"{path}: scanner_id {f.scanner_id!r} already defined by "
                f"{registry.files[f.scanner_id].path}"
            )
        registry.files[f.scanner_id] = f
    return registry


# --------------------------------------------------------------------------
# Server resolution
# --------------------------------------------------------------------------

#: How a finding's server was determined. Recorded per finding so a reader can
#: tell a confident attribution from a path-derived one.
RESOLVED_DECLARED = "declared"
RESOLVED_PATH = "path-component"
UNRESOLVED_NO_LOCATION = "unresolved:no-server-id-and-no-path"
UNRESOLVED_UNKNOWN_ID = "unresolved:unknown-server-id"
UNRESOLVED_NO_COMPONENT = "unresolved:path-matches-no-corpus-server"
UNRESOLVED_AMBIGUOUS = "unresolved:path-names-several-servers"


@dataclass(frozen=True)
class ServerResolver:
    """Turns whatever location a scanner reported into a corpus ``server_id``.

    Scanners report file paths, and those paths arrive in whatever shape the
    container mount gave them: absolute, relative, occasionally
    Windows-flavoured. The server id is the corpus directory name, so a path
    belongs to a server exactly when one of its components is a known id.

    Every failure mode returns a reason instead of a server. None of them
    raise, and none of them fall back to "probably the only vulnerable server
    of that class" -- attributing a finding to a server it did not name would
    manufacture true positives.
    """

    server_ids: frozenset[str]

    @classmethod
    def from_corpus(cls, corpus: Any) -> "ServerResolver":
        """Build from a :class:`runner.corpus.Corpus` (or anything with ``.servers``)."""
        return cls(server_ids=frozenset(corpus.servers.keys()))

    @staticmethod
    def _parts(path_str: str) -> list[str]:
        normalised = path_str.replace("\\", "/")
        return [p for p in normalised.split("/") if p not in ("", ".", "..")]

    def resolve(self, raw: RawFinding) -> tuple[str | None, str]:
        """Return ``(server_id, method)``; ``server_id`` is None when unresolved."""
        if raw.server_id:
            if raw.server_id in self.server_ids:
                return raw.server_id, RESOLVED_DECLARED
            # An adapter said which server it scanned and we do not have that
            # server. Never silently coerce: it usually means the adapter and
            # the corpus are out of sync, which would misattribute everything.
            return None, UNRESOLVED_UNKNOWN_ID

        if not raw.file:
            return None, UNRESOLVED_NO_LOCATION

        hits = [p for p in self._parts(raw.file) if p in self.server_ids]
        distinct = sorted(set(hits))
        if not distinct:
            return None, UNRESOLVED_NO_COMPONENT
        if len(distinct) > 1:
            return None, UNRESOLVED_AMBIGUOUS
        return distinct[0], RESOLVED_PATH


# --------------------------------------------------------------------------
# Mapping
# --------------------------------------------------------------------------


@dataclass
class UnknownLabel:
    """A label seen in real output that our table does not cover."""

    raw_label: str
    count: int
    reason: str
    example_message: str = ""
    example_file: str | None = None
    example_severity: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_label": self.raw_label,
            "count": self.count,
            "reason": self.reason,
            "example_message": self.example_message,
            "example_file": self.example_file,
            "example_severity": self.example_severity,
        }


@dataclass
class MappingReport:
    """The result of mapping a batch of findings, plus everything a reviewer
    needs to check the batch without rerunning it.

    The gap fields are the point of this object. A mapping layer that quietly
    drops what it does not recognise looks identical, from the scoreboard, to
    one that recognises everything.
    """

    scanner_id: str
    stage: str | None
    mapped: list[MappedFinding] = field(default_factory=list)
    unknown_labels: dict[str, UnknownLabel] = field(default_factory=dict)
    explicit_unmapped: Counter = field(default_factory=Counter)
    mapped_counts: Counter = field(default_factory=Counter)
    unresolved_servers: list[dict[str, Any]] = field(default_factory=list)
    resolution_methods: Counter = field(default_factory=Counter)
    non_exact_matches: Counter = field(default_factory=Counter)
    disputed_hits: Counter = field(default_factory=Counter)

    @property
    def total(self) -> int:
        return len(self.mapped)

    @property
    def unknown_label_count(self) -> int:
        """Findings whose label has no entry at all -- the reviewable gap."""
        return sum(u.count for u in self.unknown_labels.values())

    @property
    def has_gaps(self) -> bool:
        return bool(self.unknown_labels) or bool(self.unresolved_servers)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scanner_id": self.scanner_id,
            "stage": self.stage,
            "findings": self.total,
            "mapped_by_class": dict(sorted(self.mapped_counts.items())),
            "explicit_unmapped": dict(sorted(self.explicit_unmapped.items())),
            "unknown_labels": [u.to_dict() for u in sorted(
                self.unknown_labels.values(), key=lambda u: (-u.count, u.raw_label))],
            "unknown_label_findings": self.unknown_label_count,
            "unresolved_servers": self.unresolved_servers,
            "resolution_methods": dict(sorted(self.resolution_methods.items())),
            "non_exact_matches": dict(sorted(self.non_exact_matches.items())),
            "disputed_rationale_ids": dict(sorted(self.disputed_hits.items())),
        }

    def gap_report(self) -> str:
        """Human-readable gap report: what this scanner said that we cannot place.

        Written to be pasted into a taxonomy-review issue and into the
        disclosure pack the vendor receives before publication, so a scanner's
        maintainers see exactly which of their labels we ignored and why.
        """
        lines: list[str] = [
            f"Mapping gaps for {self.scanner_id}"
            + (f" (stage: {self.stage})" if self.stage else ""),
            f"  findings mapped to a class : {sum(self.mapped_counts.values())}",
            f"  deliberately unmapped      : {sum(self.explicit_unmapped.values())}",
            f"  NO MAPPING ENTRY           : {self.unknown_label_count}"
            f" across {len(self.unknown_labels)} distinct label(s)",
            f"  server unresolved          : {len(self.unresolved_servers)}",
        ]
        if self.unknown_labels:
            lines.append("")
            lines.append("  Labels with no entry (each needs a decision, not a guess):")
            for u in sorted(self.unknown_labels.values(), key=lambda u: (-u.count, u.raw_label)):
                lines.append(f"    {u.raw_label!r}  x{u.count}  [{u.reason}]")
                if u.example_message:
                    lines.append(f"        e.g. {u.example_message[:160]}")
        if self.unresolved_servers:
            lines.append("")
            lines.append("  Findings whose target server could not be resolved:")
            for item in self.unresolved_servers[:50]:
                lines.append(
                    f"    {item['raw_label']!r} file={item['file']!r} "
                    f"[{item['reason']}]"
                )
        if self.non_exact_matches:
            lines.append("")
            lines.append("  Matched by a declared normalization rather than byte-exactly:")
            for how, n in sorted(self.non_exact_matches.items()):
                lines.append(f"    {how}: {n}")
        if self.disputed_hits:
            lines.append("")
            lines.append("  Findings mapped through a DISPUTED entry "
                         "(both positions published on the scoreboard row):")
            for rid, n in sorted(self.disputed_hits.items()):
                lines.append(f"    {rid}: {n}")
        return "\n".join(lines)


class Mapper:
    """Applies one scanner's mapping table to that scanner's findings.

    Construct with the registry and a resolver; the mapper refuses findings
    from a scanner it has no table for rather than mapping them to nothing and
    publishing the resulting zero.
    """

    def __init__(self, registry: MappingRegistry, resolver: ServerResolver,
                 *, stage: str | None = None) -> None:
        self.registry = registry
        self.resolver = resolver
        #: Default stage for lookups. Only consulted for labels split by stage
        #: under rule R3; ordinary labels ignore it entirely.
        self.stage = stage

    # -- single ----------------------------------------------------------
    def map_finding(self, raw: RawFinding, *, stage: str | None = None,
                    report: MappingReport | None = None) -> MappedFinding:
        """Map one RawFinding. Never raises on unknown input, never guesses.

        The class comes from the label alone and the server from the reported
        location alone; the two are independent, so a finding can be mapped to
        a class with no server (scored `unmapped`, because
        :attr:`MappedFinding.is_mapped` requires both) without the class
        decision being contaminated by where the finding landed.
        """
        mapping_file = self.registry.require(raw.scanner_id)
        effective_stage = stage if stage is not None else self.stage

        server_id, method = self.resolver.resolve(raw)
        entry, how = mapping_file.lookup(raw.raw_label, effective_stage)

        if report is not None:
            report.resolution_methods[method] += 1
            if server_id is None:
                report.unresolved_servers.append({
                    "raw_label": raw.raw_label,
                    "file": raw.file,
                    "line": raw.line,
                    "declared_server_id": raw.server_id,
                    "reason": method,
                    "message": raw.message[:200],
                })

        if entry is None:
            if report is not None:
                self._record_unknown(report, raw, how)
            # No entry: mapped_class stays None. This is the never-guess rule
            # in code. docs/scoring.md scores it `unmapped`: neither a true
            # positive nor a false positive, no cost to the scanner, and a
            # standing invitation to review our taxonomy.
            return MappedFinding(
                finding=raw,
                mapped_class=None,
                mapped_server=server_id,
                mapping_rationale_id=None,
            )

        if report is not None:
            if how != "exact":
                report.non_exact_matches[how] += 1
            if entry.mapped_class is None:
                report.explicit_unmapped[entry.rationale_id] += 1
            else:
                report.mapped_counts[entry.mapped_class] += 1
            if entry.is_disputed:
                report.disputed_hits[entry.rationale_id] += 1

        # A deliberate non-mapping still carries its rationale_id: the blank in
        # the results is traceable to the paragraph that argued for it.
        return MappedFinding(
            finding=raw,
            mapped_class=entry.mapped_class,
            mapped_server=server_id,
            mapping_rationale_id=entry.rationale_id,
        )

    # -- batch -----------------------------------------------------------
    def map_findings(self, findings: Iterable[RawFinding], *,
                     stage: str | None = None) -> MappingReport:
        """Map a batch and return the findings together with the gap record."""
        findings = list(findings)
        effective_stage = stage if stage is not None else self.stage
        scanner_ids = {f.scanner_id for f in findings}
        if len(scanner_ids) > 1:
            raise MappingError(
                "map_findings takes findings from one scanner at a time; got "
                f"{sorted(scanner_ids)}. Mapping tables are per scanner and a mixed "
                "batch would apply the wrong vocabulary to some of them."
            )
        scanner_id = next(iter(scanner_ids), "")
        report = MappingReport(scanner_id=scanner_id, stage=effective_stage)
        for raw in findings:
            report.mapped.append(
                self.map_finding(raw, stage=effective_stage, report=report))
        return report

    def _record_unknown(self, report: MappingReport, raw: RawFinding, reason: str) -> None:
        existing = report.unknown_labels.get(raw.raw_label)
        if existing is None:
            report.unknown_labels[raw.raw_label] = UnknownLabel(
                raw_label=raw.raw_label,
                count=1,
                reason=reason,
                example_message=raw.message,
                example_file=raw.file,
                example_severity=raw.severity,
            )
        else:
            report.unknown_labels[raw.raw_label] = UnknownLabel(
                raw_label=existing.raw_label,
                count=existing.count + 1,
                reason=existing.reason if existing.reason == reason
                else f"{existing.reason}|{reason}",
                example_message=existing.example_message,
                example_file=existing.example_file,
                example_severity=existing.example_severity,
            )


def build_mapper(corpus: Any, *, mapping_dir: Path | None = None,
                 stage: str | None = None,
                 allow_illustrative: bool = False) -> Mapper:
    """Convenience wiring: load the tables, build the resolver from ground truth."""
    registry = load_mapping_dir(mapping_dir, allow_illustrative=allow_illustrative)
    return Mapper(registry, ServerResolver.from_corpus(corpus), stage=stage)


def _main(argv: Sequence[str] | None = None) -> int:  # pragma: no cover - dev tool
    """Validate every mapping file and print a summary. Intended for CI."""
    import argparse

    parser = argparse.ArgumentParser(description="Validate mcp-sec-bench mapping files.")
    parser.add_argument("--mapping-dir", type=Path, default=MAPPING_DIR)
    parser.add_argument("--allow-illustrative", action="store_true")
    args = parser.parse_args(argv)

    try:
        registry = load_mapping_dir(args.mapping_dir,
                                    allow_illustrative=args.allow_illustrative)
    except MappingError as exc:
        print(f"FAIL: {exc}")
        return 1

    for path, reason in registry.skipped:
        print(f"skipped {path.name}: {reason}")
    for scanner_id, f in sorted(registry.files.items()):
        mapped = sum(1 for e in f.entries if e.mapped_class)
        unmapped = sum(1 for e in f.entries if e.mapped_class is None)
        disputed = len(f.disputed_entries)
        print(f"{scanner_id}: {len(f.entries)} entries "
              f"({mapped} mapped, {unmapped} deliberately unmapped, "
              f"{disputed} disputed) provenance={f.label_provenance} "
              f"matching={'exact' if f.matching.is_exact else 'normalized'}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
