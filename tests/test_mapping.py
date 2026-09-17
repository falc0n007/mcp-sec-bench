"""Tests for the taxonomy mapping layer.

The mapping layer is the part of this benchmark that could most easily cheat
without anyone noticing: a guess in here moves a published recall number and
leaves no trace. So these tests are less about "does it work" than about "does
it refuse" -- refuse to guess a class, refuse to invent a server, refuse to
half-load a malformed file, refuse to score with invented labels.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # allows `pytest tests/` from anywhere
    sys.path.insert(0, str(ROOT))

from runner.corpus import load_corpus  # noqa: E402
from runner.mapping import (  # noqa: E402
    MAPPING_DIR,
    Mapper,
    MappingError,
    MappingEntry,
    MappingRegistry,
    ServerResolver,
    load_mapping_dir,
    load_mapping_file,
    load_schema,
    validate_document,
)
from runner.models import RawFinding  # noqa: E402

EXAMPLE_FILE = MAPPING_DIR / "example-scanner.json"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _entry(label: str, **over) -> dict:
    e = {
        "raw_label": label,
        "decision": "map",
        "mapped_class": "A8",
        "taxonomy_evidence": {
            "present_when_quote": "a caller-supplied value reaches a read operation and no containment check exists",
            "why_satisfied": "the rule reports a caller-controlled path reaching open() with no root check",
        },
        "rationale_id": "MR-testscanner-001",
        "rationale": "Illustrative fixture entry used only by the mapping layer tests.",
        "confidence": "high",
        "decided_on": "2026-09-17",
        "decided_by": "test fixture",
    }
    e.update(over)
    return e


def _doc(**over) -> dict:
    d = {
        "schema_version": "1.0",
        "scanner_id": "testscanner",
        "display_name": "Test Scanner (fixture)",
        "label_provenance": "unverified",
        "label_source_field": "rule_id",
        "matching": {"case_insensitive": False, "strip_surrounding_whitespace": False},
        "entries": [_entry("PATH_TRAVERSAL")],
    }
    d.update(over)
    return d


def _write(tmp_path: Path, doc: dict, name: str = "testscanner.json") -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(doc))
    return p


def _finding(label: str, **over) -> RawFinding:
    kw = {"scanner_id": "testscanner", "raw_label": label}
    kw.update(over)
    return RawFinding(**kw)


@pytest.fixture(scope="module")
def corpus():
    return load_corpus()


@pytest.fixture(scope="module")
def resolver(corpus):
    return ServerResolver.from_corpus(corpus)


def _mapper(path: Path, resolver: ServerResolver, *, stage: str | None = None,
            allow_illustrative: bool = False) -> Mapper:
    f = load_mapping_file(path, allow_illustrative=allow_illustrative)
    registry = MappingRegistry(files={f.scanner_id: f})
    return Mapper(registry, resolver, stage=stage)


# --------------------------------------------------------------------------
# loading and validation
# --------------------------------------------------------------------------

def test_schema_is_a_valid_json_schema():
    import jsonschema

    schema = load_schema()
    jsonschema.validators.validator_for(schema).check_schema(schema)


def test_example_file_conforms_to_the_schema():
    doc = json.loads(EXAMPLE_FILE.read_text())
    validate_document(doc, source=str(EXAMPLE_FILE))


def test_example_file_labels_are_all_marked_illustrative():
    """Nothing in the worked example may be mistakable for a real label."""
    doc = json.loads(EXAMPLE_FILE.read_text())
    assert doc["label_provenance"] == "illustrative-placeholder"
    for e in doc["entries"]:
        assert e["illustrative"] is True, e["raw_label"]
        assert e["raw_label"].startswith("EXAMPLE_"), e["raw_label"]


def test_illustrative_file_refuses_to_load_without_explicit_optin():
    with pytest.raises(MappingError, match="illustrative-placeholder"):
        load_mapping_file(EXAMPLE_FILE)

    f = load_mapping_file(EXAMPLE_FILE, allow_illustrative=True)
    assert f.is_illustrative
    assert len(f.entries) == 7


def test_load_mapping_dir_skips_illustrative_and_records_why():
    registry = load_mapping_dir(MAPPING_DIR)
    assert "example-scanner" not in registry
    assert [p.name for p, _ in registry.skipped] == ["example-scanner.json"]

    registry = load_mapping_dir(MAPPING_DIR, allow_illustrative=True)
    assert "example-scanner" in registry
    assert registry.skipped == []


def test_example_covers_the_four_cases_it_claims_to(tmp_path):
    f = load_mapping_file(EXAMPLE_FILE, allow_illustrative=True)
    by_id = {e.rationale_id: e for e in f.entries}

    # 1:1
    assert by_id["MR-example-scanner-001"].mapped_class == "A8"
    assert by_id["MR-example-scanner-001"].considered_classes == ()
    # spans two classes, split by stage (R3)
    static = by_id["MR-example-scanner-002"]
    runtime = by_id["MR-example-scanner-003"]
    assert static.raw_label == runtime.raw_label
    assert (static.applies_to_stage, static.mapped_class) == ("static", "A1")
    assert (runtime.applies_to_stage, runtime.mapped_class) == ("runtime", "A4")
    assert "R3" in static.resolution_rules
    # deliberately unmapped
    assert by_id["MR-example-scanner-005"].mapped_class is None
    assert by_id["MR-example-scanner-005"].unmapped_reason == "outside-taxonomy-scope"
    # disputed, both positions
    disputed = by_id["MR-example-scanner-007"]
    assert disputed.is_disputed and disputed.publishes_both_positions
    assert disputed.vendor_proposed_class == "A7"


# --------------------------------------------------------------------------
# malformed files fail loudly
# --------------------------------------------------------------------------

@pytest.mark.parametrize("mutate,expected", [
    pytest.param(lambda d: d.pop("entries"), "entries", id="missing-entries"),
    pytest.param(lambda d: d.pop("label_source_field"), "label_source_field",
                 id="missing-label-source-field"),
    pytest.param(lambda d: d.pop("matching"), "matching", id="missing-matching"),
    pytest.param(lambda d: d["entries"][0].__setitem__("mapped_class", "A11"),
                 "mapped_class", id="class-not-in-taxonomy"),
    pytest.param(lambda d: d["entries"][0].pop("taxonomy_evidence"),
                 "taxonomy_evidence", id="mapped-without-present-when-evidence"),
    pytest.param(lambda d: d["entries"][0].__setitem__("rationale_id", "001"),
                 "rationale_id", id="rationale-id-not-stable-format"),
    pytest.param(lambda d: d["entries"][0].__setitem__("decision", "probably"),
                 "decision", id="decision-not-an-enum-value"),
    pytest.param(lambda d: d["entries"][0].__setitem__("status", "disputed"),
                 "dispute", id="disputed-without-both-positions"),
    pytest.param(lambda d: d["entries"][0].__setitem__("considered_classes", [
        {"class": "A10", "why_rejected": "no process execution is reported here at all"}]),
        "resolution_rules", id="span-without-resolution-rule"),
    pytest.param(lambda d: d["entries"][0].__setitem__("rationale", "too short"),
                 "rationale", id="rationale-too-short-to-argue-with"),
    pytest.param(lambda d: d.__setitem__("scanner_id", "Test Scanner"),
                 "scanner_id", id="scanner-id-not-a-row-key"),
    pytest.param(lambda d: d["entries"][0].__setitem__("bonus_field", True),
                 "bonus", id="unknown-field"),
])
def test_malformed_mapping_file_fails_loudly(tmp_path, mutate, expected):
    doc = _doc()
    mutate(doc)
    path = _write(tmp_path, doc)
    with pytest.raises(MappingError) as exc:
        load_mapping_file(path)
    assert expected in str(exc.value)
    assert str(path) in str(exc.value)


def test_unmapped_entry_must_state_a_reason(tmp_path):
    doc = _doc(entries=[_entry("X", decision="unmapped", mapped_class=None,
                               taxonomy_evidence=None)])
    doc["entries"][0].pop("taxonomy_evidence")
    path = _write(tmp_path, doc)
    with pytest.raises(MappingError, match="unmapped_reason"):
        load_mapping_file(path)


def test_not_valid_json_fails_loudly(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text('{"schema_version": "1.0", ')
    with pytest.raises(MappingError, match="not valid JSON"):
        load_mapping_file(p)


def test_missing_file_fails_loudly(tmp_path):
    with pytest.raises(MappingError, match="not found"):
        load_mapping_file(tmp_path / "nope.json")


def test_duplicate_rationale_id_is_rejected(tmp_path):
    doc = _doc(entries=[_entry("A"), _entry("B")])  # same rationale_id
    with pytest.raises(MappingError, match="used twice"):
        load_mapping_file(_write(tmp_path, doc))


def test_duplicate_label_at_same_stage_scope_is_rejected(tmp_path):
    doc = _doc(entries=[_entry("DUP"), _entry("DUP", rationale_id="MR-testscanner-002")])
    with pytest.raises(MappingError, match="duplicate entry"):
        load_mapping_file(_write(tmp_path, doc))


def test_label_cannot_be_both_stage_scoped_and_unscoped(tmp_path):
    doc = _doc(entries=[
        _entry("SPLIT"),
        _entry("SPLIT", rationale_id="MR-testscanner-002", applies_to_stage="static"),
    ])
    with pytest.raises(MappingError, match="stage-scoped"):
        load_mapping_file(_write(tmp_path, doc))


def test_casefold_collision_is_rejected_when_case_insensitive(tmp_path):
    doc = _doc(
        matching={"case_insensitive": True, "strip_surrounding_whitespace": False,
                  "note": "fixture"},
        entries=[_entry("dup"), _entry("DUP", rationale_id="MR-testscanner-002")],
    )
    with pytest.raises(MappingError, match="collide"):
        load_mapping_file(_write(tmp_path, doc))


def test_two_files_claiming_one_scanner_id_is_rejected(tmp_path):
    _write(tmp_path, _doc(), "a.json")
    _write(tmp_path, _doc(), "b.json")
    with pytest.raises(MappingError, match="already defined"):
        load_mapping_dir(tmp_path)


def test_schema_json_itself_is_not_loaded_as_a_mapping(tmp_path):
    (tmp_path / "schema.json").write_text(json.dumps(load_schema()))
    _write(tmp_path, _doc())
    registry = load_mapping_dir(tmp_path)
    assert list(registry.files) == ["testscanner"]


# --------------------------------------------------------------------------
# exact matching
# --------------------------------------------------------------------------

def test_exact_label_matches(tmp_path, resolver):
    m = _mapper(_write(tmp_path, _doc()), resolver)
    out = m.map_finding(_finding("PATH_TRAVERSAL",
                                 file="corpus/a08-unrestricted-file-read/server.py"))
    assert out.mapped_class == "A8"
    assert out.mapped_server == "a08-unrestricted-file-read"
    assert out.mapping_rationale_id == "MR-testscanner-001"
    assert out.is_mapped


@pytest.mark.parametrize("label", [
    "path_traversal",        # case differs
    "PATH TRAVERSAL",        # separator differs
    "PATH_TRAVERSAL ",       # trailing whitespace
    "PATH_TRAVERSAL_TOOL",   # superstring
    "TRAVERSAL",             # substring
])
def test_near_miss_labels_do_not_match_by_default(tmp_path, resolver, label):
    """Default matching is byte-exact. Anything else would be unreviewable."""
    m = _mapper(_write(tmp_path, _doc()), resolver)
    out = m.map_finding(_finding(label))
    assert out.mapped_class is None
    assert out.mapping_rationale_id is None


def test_declared_normalizations_are_opt_in_and_recorded(tmp_path, resolver):
    doc = _doc(matching={"case_insensitive": True,
                         "strip_surrounding_whitespace": True,
                         "note": "observed casing drift between engines"})
    m = _mapper(_write(tmp_path, doc), resolver)
    report = m.map_findings([
        _finding("PATH_TRAVERSAL"),
        _finding("  PATH_TRAVERSAL  "),
        _finding("path_traversal"),
    ])
    assert [f.mapped_class for f in report.mapped] == ["A8", "A8", "A8"]
    # the two non-exact matches are counted so review can see them
    assert sum(report.non_exact_matches.values()) == 2
    assert "exact" not in report.non_exact_matches


def test_normalization_stays_off_unless_declared(tmp_path, resolver):
    m = _mapper(_write(tmp_path, _doc()), resolver)
    report = m.map_findings([_finding("  PATH_TRAVERSAL  ")])
    assert report.mapped[0].mapped_class is None
    assert report.non_exact_matches == {}


# --------------------------------------------------------------------------
# unknown labels: never guess
# --------------------------------------------------------------------------

def test_unknown_label_is_unmapped_and_does_not_guess(tmp_path, resolver):
    """The finding lands squarely on the A8 server, whose only declared class
    is A8, and the table contains exactly one entry -- which is also A8. Every
    available shortcut points the same way. The layer must still refuse."""
    m = _mapper(_write(tmp_path, _doc()), resolver)
    out = m.map_finding(_finding(
        "SOME_LABEL_WE_HAVE_NEVER_SEEN",
        file="corpus/a08-unrestricted-file-read/server.py",
        message="Unsanitized path argument flows into open()",
        severity="high",
    ))
    assert out.mapped_class is None
    assert out.mapping_rationale_id is None
    assert not out.is_mapped
    # the server still resolves: class and server are independent axes
    assert out.mapped_server == "a08-unrestricted-file-read"


def test_unknown_labels_are_reported_not_dropped(tmp_path, resolver):
    m = _mapper(_write(tmp_path, _doc()), resolver)
    report = m.map_findings([
        _finding("PATH_TRAVERSAL", file="corpus/a08-unrestricted-file-read/server.py"),
        _finding("MYSTERY_RULE", message="something we do not model", severity="low"),
        _finding("MYSTERY_RULE", message="second hit"),
        _finding("OTHER_MYSTERY"),
    ])
    assert report.unknown_label_count == 3
    assert set(report.unknown_labels) == {"MYSTERY_RULE", "OTHER_MYSTERY"}
    assert report.unknown_labels["MYSTERY_RULE"].count == 2
    assert report.unknown_labels["MYSTERY_RULE"].reason == "no-entry"
    assert report.has_gaps

    text = report.gap_report()
    assert "MYSTERY_RULE" in text and "x2" in text
    assert "NO MAPPING ENTRY" in text
    assert "something we do not model" in text
    assert report.to_dict()["unknown_label_findings"] == 3


def test_deliberate_unmapped_keeps_its_rationale_id(tmp_path, resolver):
    doc = _doc(entries=[_entry(
        "DEPENDENCY_CVE", decision="unmapped", mapped_class=None,
        unmapped_reason="outside-taxonomy-scope")])
    doc["entries"][0].pop("taxonomy_evidence")
    m = _mapper(_write(tmp_path, doc), resolver)
    report = m.map_findings([_finding("DEPENDENCY_CVE")])
    out = report.mapped[0]
    assert out.mapped_class is None
    assert out.mapping_rationale_id == "MR-testscanner-001"   # traceable blank
    assert not out.is_mapped
    # a decided non-mapping is not a gap in the table
    assert report.unknown_labels == {}
    assert report.explicit_unmapped["MR-testscanner-001"] == 1


def test_scanner_with_no_mapping_file_raises_rather_than_scoring_zero(resolver):
    m = Mapper(MappingRegistry(), resolver)
    with pytest.raises(MappingError, match="no mapping file"):
        m.map_finding(_finding("ANYTHING"))


def test_batch_refuses_mixed_scanners(tmp_path, resolver):
    m = _mapper(_write(tmp_path, _doc()), resolver)
    with pytest.raises(MappingError, match="one scanner at a time"):
        m.map_findings([_finding("PATH_TRAVERSAL"),
                        _finding("PATH_TRAVERSAL", scanner_id="other")])


# --------------------------------------------------------------------------
# stage-scoped entries (rule R3)
# --------------------------------------------------------------------------

def _split_doc() -> dict:
    static = _entry(
        "PROMPT_INJECTION", applies_to_stage="static", mapped_class="A1",
        rationale_id="MR-testscanner-010",
        considered_classes=[{"class": "A4",
                             "why_rejected": "A4 is a return value, not metadata content"}],
        resolution_rules=["R1", "R3"],
    )
    runtime = _entry(
        "PROMPT_INJECTION", applies_to_stage="runtime", mapped_class="A4",
        rationale_id="MR-testscanner-011",
        considered_classes=[{"class": "A1",
                             "why_rejected": "A1 is metadata, reached statically"}],
        resolution_rules=["R1", "R3"],
    )
    return _doc(entries=[static, runtime])


def test_stage_scoped_entries_resolve_by_stage(tmp_path, resolver):
    path = _write(tmp_path, _split_doc())
    assert _mapper(path, resolver, stage="static").map_finding(
        _finding("PROMPT_INJECTION")).mapped_class == "A1"
    assert _mapper(path, resolver, stage="runtime").map_finding(
        _finding("PROMPT_INJECTION")).mapped_class == "A4"


def test_stage_split_without_a_stage_refuses_to_pick(tmp_path, resolver):
    m = _mapper(_write(tmp_path, _split_doc()), resolver)
    report = m.map_findings([_finding("PROMPT_INJECTION")])
    assert report.mapped[0].mapped_class is None
    assert report.unknown_labels["PROMPT_INJECTION"].reason == "stage-required"
    assert "stage-required" in report.gap_report()


# --------------------------------------------------------------------------
# server resolution
# --------------------------------------------------------------------------

@pytest.mark.parametrize("path,expected", [
    ("corpus/a08-unrestricted-file-read/server.py", "a08-unrestricted-file-read"),
    ("/scan/corpus/a01-tool-description-injection/server.py",
     "a01-tool-description-injection"),
    ("./corpus/c03-release-runner/manifest.json", "c03-release-runner"),
    ("corpus/a10b-allowlist-bypass", "a10b-allowlist-bypass"),
    (r"C:\scan\corpus\a09-unrestricted-env-access\server.py",
     "a09-unrestricted-env-access"),
    ("corpus/a04-response-injection/data/cached_feed.json", "a04-response-injection"),
])
def test_path_resolves_to_server(resolver, path, expected):
    server_id, method = resolver.resolve(_finding("X", file=path))
    assert server_id == expected
    assert method == "path-component"


def test_declared_server_id_is_used_when_known(resolver):
    server_id, method = resolver.resolve(
        _finding("X", server_id="a02-rug-pull", file="/elsewhere/thing.py"))
    assert (server_id, method) == ("a02-rug-pull", "declared")


@pytest.mark.parametrize("raw,reason", [
    (_finding("X", file="/opt/site-packages/fastmcp/server.py"),
     "unresolved:path-matches-no-corpus-server"),
    (_finding("X", file="server.py"), "unresolved:path-matches-no-corpus-server"),
    (_finding("X"), "unresolved:no-server-id-and-no-path"),
    (_finding("X", server_id="a99-not-a-server"), "unresolved:unknown-server-id"),
    (_finding("X", file="corpus/a01-tool-description-injection/../a03-tool-shadowing/x.py"),
     "unresolved:path-names-several-servers"),
])
def test_unresolvable_locations_are_explicit_not_crashes(resolver, raw, reason):
    server_id, method = resolver.resolve(raw)
    assert server_id is None
    assert method == reason


def test_finding_with_unresolvable_path_is_handled_and_reported(tmp_path, resolver):
    m = _mapper(_write(tmp_path, _doc()), resolver)
    report = m.map_findings([
        _finding("PATH_TRAVERSAL", file="/opt/venv/lib/python3.13/site-packages/x.py"),
    ])
    out = report.mapped[0]
    assert out.mapped_server is None
    assert not out.is_mapped          # scored `unmapped`: no credit, no penalty
    assert out.mapped_class == "A8"   # the label decision is preserved, not erased
    assert len(report.unresolved_servers) == 1
    assert report.unresolved_servers[0]["reason"] == "unresolved:path-matches-no-corpus-server"
    assert "server unresolved          : 1" in report.gap_report()


def test_resolver_never_falls_back_to_the_only_plausible_server(tmp_path, resolver):
    """A path naming no server must not be attributed to the server whose class
    the label maps to, however obvious the inference looks."""
    m = _mapper(_write(tmp_path, _doc()), resolver)
    out = m.map_finding(_finding("PATH_TRAVERSAL", file="/tmp/unpacked/server.py"))
    assert out.mapped_server is None


def test_resolver_is_built_from_ground_truth(corpus, resolver):
    assert resolver.server_ids == frozenset(corpus.servers)
    assert "a08-unrestricted-file-read" in resolver.server_ids


# --------------------------------------------------------------------------
# disputes survive a round trip
# --------------------------------------------------------------------------

def test_disputed_entry_round_trips_with_both_positions(tmp_path):
    original = load_mapping_file(EXAMPLE_FILE, allow_illustrative=True)
    disputed = original.entry_by_rationale_id("MR-example-scanner-007")
    assert disputed is not None

    doc = json.loads(EXAMPLE_FILE.read_text())
    doc["entries"] = [copy.deepcopy(e.to_dict()) for e in original.entries]
    path = _write(tmp_path, doc, "roundtrip.json")

    reloaded = load_mapping_file(path, allow_illustrative=True)
    again = reloaded.entry_by_rationale_id("MR-example-scanner-007")

    assert again == disputed
    assert again.status == "disputed"
    assert again.publishes_both_positions
    # both positions, not just ours
    assert again.dispute["our_position"] == disputed.dispute["our_position"]
    assert again.dispute["vendor_position"] == disputed.dispute["vendor_position"]
    assert again.dispute["vendor_proposed_class"] == "A7"
    assert again.dispute["scoreboard_note"]
    assert again.dispute["affected_items"] == disputed.dispute["affected_items"]
    assert again.history[0]["governance_ref"] == "governance.md#contesting-a-result"


def test_dispute_does_not_change_the_applied_mapping(tmp_path, resolver):
    """We publish the vendor's reading; we do not quietly apply it."""
    m = _mapper(EXAMPLE_FILE, resolver, allow_illustrative=True)
    m.registry.files["example-scanner"].scanner_id  # sanity
    raw = RawFinding(scanner_id="example-scanner", raw_label="EXAMPLE_ENV_VAR_DISCLOSURE",
                     file="corpus/a09-unrestricted-env-access/server.py")
    report = m.map_findings([raw])
    out = report.mapped[0]
    assert out.mapped_class == "A9"                       # ours
    assert out.mapping_rationale_id == "MR-example-scanner-007"
    assert report.disputed_hits["MR-example-scanner-007"] == 1
    assert "DISPUTED" in report.gap_report()


def test_registry_lists_every_disputed_entry_for_the_scoreboard():
    registry = load_mapping_dir(MAPPING_DIR, allow_illustrative=True)
    disputed = registry.all_disputed()
    assert ("example-scanner", ) == tuple({sid for sid, _ in disputed})
    for _, entry in disputed:
        assert entry.dispute["vendor_position"]
        assert entry.dispute["our_position"]


def test_entry_to_dict_output_still_validates(tmp_path):
    f = load_mapping_file(EXAMPLE_FILE, allow_illustrative=True)
    doc = json.loads(EXAMPLE_FILE.read_text())
    doc["entries"] = [e.to_dict() for e in f.entries]
    validate_document(doc, source="round-tripped example")


def test_mapping_entry_is_immutable():
    e = MappingEntry.from_dict(_entry("X"))
    with pytest.raises(Exception):
        e.mapped_class = "A1"  # type: ignore[misc]
