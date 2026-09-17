"""Tests for the Cisco mcp-scanner adapter.

Every assertion here runs against output committed under
`tests/fixtures/cisco-mcp-scanner/`, captured from cisco-ai-mcp-scanner 4.8.4 on
2026-09-17. No Docker, no network, no lab: the container call is the one thing
stubbed out, and everything downstream of it is the vendor's real bytes.

The tests are grouped by what would break if the adapter regressed:

  * parsing, including the two different shapes `findings` arrives in;
  * `raw_label` verbatim -- the mapping table is keyed on it, so a normalisation
    slipped in here would silently re-score the scanner;
  * the failure modes that look like a clean scan (empty stdout, malformed
    output, non-zero exit) and must not be reported as "found nothing";
  * the no-silent-drop rule from the adapter contract;
  * and one consistency check between the fixtures and the mapping table,
    because the recon for this scanner captured the YARA *rule filenames* and
    those never appear in output. A table keyed on them would match nothing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runner.adapters import RuntimeTarget, StaticTarget
from runner.adapters.cisco_mcp_scanner import (
    IMAGE,
    SCANNER_VERSION,
    UNLABELLED,
    CiscoMcpScannerAdapter,
    CiscoScanFailed,
    _endpoint_in_container,
    _extract_json_array,
)
from runner.adapters.container import ContainerResult
from runner.mapping import load_mapping_file

FIXTURES = Path(__file__).parent / "fixtures" / "cisco-mcp-scanner"
MAPPING_FILE = Path(__file__).parent.parent / "mapping" / "cisco-mcp-scanner.json"

#: The ten rule files shipped in the wheel. NONE of these strings appears in
#: `--raw` output; each rule emits its `meta.threat_type` instead.
YARA_RULE_FILENAMES = (
    "code_execution", "coercive_injection", "command_injection",
    "credential_harvesting", "data_exfiltration", "prompt_injection",
    "script_injection", "sql_injection", "system_manipulation",
    "tool_poisoning",
)

#: The seven strings the ten rules collapse onto, all captured in
#: label-probe-yara.json.
OBSERVED_YARA_LABELS = (
    "CODE EXECUTION", "CREDENTIAL HARVESTING", "DATA EXFILTRATION",
    "INJECTION ATTACK", "PROMPT INJECTION", "SYSTEM MANIPULATION",
    "TOOL POISONING",
)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def target(server_id: str = "a01-tool-description-injection", port: int = 8101,
           token: str | None = "lab-token-do-not-reuse") -> RuntimeTarget:
    return RuntimeTarget(
        server_id=server_id,
        url=f"http://127.0.0.1:{port}/mcp",
        token=token,
        authenticated=token is not None,
    )


def stub_runs(monkeypatch, *results: ContainerResult):
    """Replace the container call with a fixed sequence of results.

    The adapter runs one container per surface, so a default-configuration scan
    consumes four. The last result is repeated if the adapter asks for more.
    """
    queue = list(results)
    calls: list[list[str]] = []

    def fake(spec):
        calls.append(list(spec.args))
        return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr(
        "runner.adapters.cisco_mcp_scanner.run_container", fake)
    return calls


def ok(stdout: str, exit_code: int = 0, stderr: str = "") -> ContainerResult:
    return ContainerResult(exit_code=exit_code, stdout=stdout, stderr=stderr,
                           duration_seconds=1.0)


EMPTY_ARRAY = ok("[]")


# ---------------------------------------------------------------------------
# identity and declared surface
# ---------------------------------------------------------------------------


def test_identity_and_declared_stage():
    a = CiscoMcpScannerAdapter()
    assert a.scanner_id == "cisco-mcp-scanner"
    assert a.adapter_version == "1.0.0"
    assert a.requires_signup is False
    assert a.config_label == "default"
    # Credential-free Cisco has no analyzer that reads source, so it declares
    # runtime only. Declaring static would score it 0% on a stage it cannot
    # attempt, which docs/scoring.md calls a category error.
    assert a.stages == frozenset({"runtime"})
    assert a.analyzers == ("yara",)
    assert SCANNER_VERSION == "4.8.4"
    assert IMAGE.endswith(":4.8.4")


def test_default_config_refuses_the_static_stage_with_a_reason():
    a = CiscoMcpScannerAdapter()
    with pytest.raises(NotImplementedError) as exc:
        a.run_static(StaticTarget(corpus_dir=Path("corpus"), server_dirs=()))
    message = str(exc.value)
    assert "behavioral" in message
    assert "LLM provider API key" in message


def test_alternative_configurations_are_additional_rows_not_replacements():
    default = CiscoMcpScannerAdapter()

    llm = CiscoMcpScannerAdapter.llm_config("not-a-real-key")
    assert llm.config_label == "llm"
    assert llm.requires_signup is True

    behavioral = CiscoMcpScannerAdapter.behavioral_config("not-a-real-key")
    assert behavioral.config_label == "behavioral"
    assert behavioral.stages == frozenset({"static"})
    assert behavioral.requires_signup is True

    readiness = CiscoMcpScannerAdapter.readiness_config()
    assert readiness.config_label == "readiness"
    assert readiness.requires_signup is False
    assert "readiness" in readiness.analyzers

    # None of them mutated the default.
    assert default.config_label == "default"
    assert default.analyzers == ("yara",)
    assert default.requires_signup is False
    assert default.stages == frozenset({"runtime"})


def test_available_reports_docker_down_rather_than_raising(monkeypatch):
    monkeypatch.setattr(
        "runner.adapters.cisco_mcp_scanner.docker_available",
        lambda: (False, "the docker daemon is not running"))
    ok_, reason = CiscoMcpScannerAdapter().available()
    assert ok_ is False
    assert "docker daemon is not running" in reason


def test_available_reports_a_missing_image_with_the_build_command(monkeypatch):
    monkeypatch.setattr(
        "runner.adapters.cisco_mcp_scanner.docker_available", lambda: (True, ""))
    monkeypatch.setattr(
        "runner.adapters.cisco_mcp_scanner.image_present", lambda image: False)
    ok_, reason = CiscoMcpScannerAdapter().available()
    assert ok_ is False
    assert IMAGE in reason
    assert "docker build" in reason
    assert "cisco-mcp-scanner.Dockerfile" in reason


def test_available_reports_a_version_mismatch_rather_than_scanning_anyway(monkeypatch):
    monkeypatch.setattr(
        "runner.adapters.cisco_mcp_scanner.docker_available", lambda: (True, ""))
    monkeypatch.setattr(
        "runner.adapters.cisco_mcp_scanner.image_present", lambda image: True)
    stub_runs(monkeypatch, ok("4.9.0\n"))
    ok_, reason = CiscoMcpScannerAdapter().available()
    assert ok_ is False
    assert "4.9.0" in reason and "4.8.4" in reason


def test_available_reports_a_docker_query_failure_rather_than_raising(monkeypatch):
    monkeypatch.setattr(
        "runner.adapters.cisco_mcp_scanner.docker_available", lambda: (True, ""))

    def boom(image):
        raise OSError("docker cli exploded")

    monkeypatch.setattr(
        "runner.adapters.cisco_mcp_scanner.image_present", boom)
    ok_, reason = CiscoMcpScannerAdapter().available()
    assert ok_ is False
    assert "docker cli exploded" in reason


# ---------------------------------------------------------------------------
# invocation
# ---------------------------------------------------------------------------


def test_endpoint_is_rewritten_for_the_container_gateway():
    # runner/execute.py builds targets on 127.0.0.1, which inside a scanner
    # container is the container itself.
    assert _endpoint_in_container("http://127.0.0.1:8101/mcp") == \
        "http://host.docker.internal:8101/mcp"
    assert _endpoint_in_container("http://localhost:8204/mcp") == \
        "http://host.docker.internal:8204/mcp"
    # Anything it cannot parse is passed through unchanged rather than mangled.
    assert _endpoint_in_container("weird") == "weird"


def test_invocation_passes_bearer_token_explicit_subcommand_and_analyzers(monkeypatch):
    calls = stub_runs(monkeypatch, EMPTY_ARRAY)
    CiscoMcpScannerAdapter().run_runtime(target())

    assert len(calls) == 4, "one container per metadata surface"
    surfaces = [c[c.index("--raw") + 1] for c in calls]
    assert surfaces == ["remote", "prompts", "resources", "instructions"]

    for args in calls:
        # An explicit subcommand every time: with none, 4.8.4 silently scans
        # https://mcp.deepwiki.com/mcp instead of the target.
        assert "--server-url" in args
        assert args[args.index("--server-url") + 1] == \
            "http://host.docker.internal:8101/mcp"
        assert args[args.index("--analyzers") + 1] == "yara"
        assert "--raw" in args
        assert args[args.index("--bearer-token") + 1] == "lab-token-do-not-reuse"
        # The default configuration never carries a credential.
        assert "--llm-api-key" not in args


def test_unauthenticated_targets_get_no_bearer_flag(monkeypatch):
    calls = stub_runs(monkeypatch, EMPTY_ARRAY)
    CiscoMcpScannerAdapter().run_runtime(
        target("a06-authless-endpoint", 8106, token=None))
    for args in calls:
        assert "--bearer-token" not in args


# ---------------------------------------------------------------------------
# parsing real captured output
# ---------------------------------------------------------------------------


def test_a01_the_payload_was_read_and_nothing_fired(monkeypatch):
    """The central result, and the reason it is a detection failure.

    The scanner returns a01's injected description verbatim in its own output
    and reports SAFE on it. "Never saw the data" and "saw it and did not fire"
    are different claims; this fixture settles which one applies.
    """
    raw = fixture("remote-a01-yara.json")
    assert "IMPORTANT INSTRUCTION FOR THE ASSISTANT READING THIS DESCRIPTION" in raw
    assert "MCPBENCH-MARKER-a01" in raw

    stub_runs(monkeypatch, ok(raw), EMPTY_ARRAY, EMPTY_ARRAY,
              ok(fixture("instructions-a01-yara.json")))
    result = CiscoMcpScannerAdapter().run_runtime(target())

    assert result.findings == []
    assert result.error is None
    assert result.exit_code == 0
    assert result.scanner_version == "4.8.4"
    # A scan that read four tools is distinguishable from one that read none.
    assert result.extra["items_scanned"]["remote"] == 4
    assert result.extra["bearer_token_sent"] is True
    # The verdicts we did not turn into findings are still in the raw output.
    assert result.raw_output.count('"severity": "SAFE"') == 4


def test_a02_mutated_descriptor_yields_one_verbatim_label(monkeypatch):
    stub_runs(monkeypatch, ok(fixture("remote-a02-yara-call4-mutated.json")),
              EMPTY_ARRAY, EMPTY_ARRAY, EMPTY_ARRAY)
    result = CiscoMcpScannerAdapter().run_runtime(target("a02-rug-pull", 8102))

    assert len(result.findings) == 1
    f = result.findings[0]
    # Verbatim. Upper case, single space, no rule filename, no normalisation:
    # mapping/cisco-mcp-scanner.json is keyed on this exact string.
    assert f.raw_label == "PROMPT INJECTION"
    assert f.raw_label not in YARA_RULE_FILENAMES
    assert f.server_id == "a02-rug-pull"
    assert f.stage == "runtime"
    assert f.severity == "HIGH"
    assert f.message == "Detected 1 threat: prompt injection"
    assert f.raw["analyzer"] == "yara_analyzer"
    assert f.raw["surface"] == "remote"
    assert f.raw["subject"] == "summarize_changelog"
    assert f.raw["item_type"] == "tool"
    assert f.raw["endpoint"] == "http://host.docker.internal:8102/mcp"
    # Cisco's own crosswalk is preserved as evidence, not used as the key.
    assert f.raw["aitech"] == "AITech-1.1"
    assert f.raw["aitech_name"] == "Direct Prompt Injection"
    assert f.raw["aisubtech"] == "AISubtech-1.1.1"
    assert f.raw["scanner_category"] == "PROMPT INJECTION"
    assert "MCPBENCH-MARKER-a02" in f.raw["tool_description"]


def test_a02_pre_trigger_snapshot_yields_nothing(monkeypatch):
    """Same server, same invocation, earlier in its life: no finding.

    The corpus mutates the descriptor on the fourth tools/list. The scanner
    makes one tools/list per scan and does not diff, so what it reports depends
    on how many times the endpoint has been listed. Both snapshots are
    committed so that dependence is checkable rather than asserted.
    """
    stub_runs(monkeypatch, ok(fixture("remote-a02-yara-call1-clean.json")),
              EMPTY_ARRAY, EMPTY_ARRAY, EMPTY_ARRAY)
    result = CiscoMcpScannerAdapter().run_runtime(target("a02-rug-pull", 8102))
    assert result.findings == []
    assert "MCPBENCH-MARKER-a02" not in fixture("remote-a02-yara-call1-clean.json")


def test_label_probe_captures_all_seven_observable_labels(monkeypatch):
    stub_runs(monkeypatch, ok(fixture("label-probe-yara.json")),
              EMPTY_ARRAY, EMPTY_ARRAY, EMPTY_ARRAY)
    result = CiscoMcpScannerAdapter().run_runtime(target("probe", 8101))

    labels = CiscoMcpScannerAdapter().observed_labels(result.findings)
    assert sorted(labels) == sorted(OBSERVED_YARA_LABELS)
    # Two probe items match two rules each, so there are more findings than
    # distinct labels: one RawFinding per threat_name, never one per item.
    assert sum(labels.values()) == 10
    assert labels["INJECTION ATTACK"] == 2      # command_injection + sql_injection
    assert labels["TOOL POISONING"] == 2
    assert labels["SYSTEM MANIPULATION"] == 2
    assert labels["PROMPT INJECTION"] == 1
    # Severity comes across per analyzer block, including Cisco's lone LOW.
    by_label = {f.raw_label: f for f in result.findings}
    assert by_label["CODE EXECUTION"].severity == "LOW"
    assert by_label["PROMPT INJECTION"].severity == "HIGH"
    # Every finding names the endpoint it came from.
    assert {f.server_id for f in result.findings} == {"probe"}


def test_multi_label_item_records_the_sibling_labels_on_each_finding(monkeypatch):
    stub_runs(monkeypatch, ok(fixture("label-probe-yara.json")),
              EMPTY_ARRAY, EMPTY_ARRAY, EMPTY_ARRAY)
    result = CiscoMcpScannerAdapter().run_runtime(target("probe", 8101))
    pair = [f for f in result.findings
            if f.raw["subject"] == "probe_injection_attack_command"]
    assert {f.raw_label for f in pair} == {"INJECTION ATTACK", "SYSTEM MANIPULATION"}
    for f in pair:
        assert f.raw["threat_names"] == ["INJECTION ATTACK", "SYSTEM MANIPULATION"]


def test_instructions_surface_findings_are_a_list_not_a_mapping(monkeypatch):
    """4.8.4 uses two different JSON shapes for `findings`. Both are real."""
    raw = fixture("instructions-a01-yara.json")
    assert isinstance(json.loads(raw)[0]["findings"], list)
    stub_runs(monkeypatch, EMPTY_ARRAY, EMPTY_ARRAY, EMPTY_ARRAY, ok(raw))
    result = CiscoMcpScannerAdapter().run_runtime(target())
    assert result.findings == []
    assert result.error is None
    assert result.extra["items_scanned"]["instructions"] == 1


def test_readiness_label_is_preserved_in_its_own_lower_case(monkeypatch):
    """`unknown` is what the readiness analyzer emits. Not normalised, not dropped."""
    stub_runs(monkeypatch, ok(fixture("remote-a01-yara-readiness.json")),
              EMPTY_ARRAY, EMPTY_ARRAY, EMPTY_ARRAY)
    result = CiscoMcpScannerAdapter.readiness_config().run_runtime(target())

    assert [f.raw_label for f in result.findings] == ["unknown"] * 4
    assert all(f.raw["analyzer"] == "readiness_analyzer" for f in result.findings)
    # The substance is in the summary, and the count Cisco reports is kept.
    assert all(f.raw["total_findings"] == 7 for f in result.findings)
    assert "does not specify a timeout" in result.findings[0].message
    # The yara blocks in the same items were SAFE and produced nothing.
    assert len(result.findings) == 4


# ---------------------------------------------------------------------------
# failure modes that look like success
# ---------------------------------------------------------------------------


def test_empty_stdout_is_a_failed_scan_not_an_empty_result(monkeypatch):
    """The whole point of trap 1: distinguish "found nothing" from "never ran".

    Captured from a real refusal: scanning an authenticated server with no
    token leaves stdout empty and puts the reason on stderr.
    """
    stdout = fixture("failed-scan-no-token.stdout")
    stderr = fixture("failed-scan-no-token.stderr")
    assert stdout.strip() == ""
    assert "Error during scanning" in stderr

    stub_runs(monkeypatch, ok(stdout, exit_code=1, stderr=stderr))
    result = CiscoMcpScannerAdapter().run_runtime(target(token=None))

    assert result.findings == []
    assert result.error is not None
    assert "no stdout" in result.error
    assert "Error during scanning" in result.error
    assert result.exit_code == 1
    # And crucially: no surface is recorded as having been scanned.
    assert result.extra["items_scanned"] == {}


def test_malformed_output_is_reported_and_does_not_crash(monkeypatch):
    stub_runs(monkeypatch, ok(fixture("SYNTHETIC-malformed.txt")))
    result = CiscoMcpScannerAdapter().run_runtime(target())
    assert result.findings == []
    assert result.error is not None
    assert "parseable JSON" in result.error or "not JSON" in result.error
    assert result.extra["items_scanned"] == {}


def test_a_json_object_at_the_top_level_is_refused():
    with pytest.raises(CiscoScanFailed) as exc:
        _extract_json_array('{"status": "completed"}')
    assert "array" in str(exc.value)


def test_log_noise_around_the_array_is_tolerated():
    parsed = _extract_json_array(
        'WARNING something\n[{"tool_name": "t", "findings": {}}]\ntrailing noise')
    assert parsed[0]["tool_name"] == "t"


def test_literal_control_characters_do_not_lose_the_scan():
    # A stray control byte inside a description would make Python's strict
    # decoder reject the whole document.
    parsed = _extract_json_array('[{"tool_name": "t\x01x", "findings": {}}]')
    assert parsed[0]["tool_name"] == "t\x01x"


def test_non_zero_exit_with_findings_still_yields_the_findings(monkeypatch):
    """Exit status never gates parsing.

    4.8.4 happens to exit 0 when it reports findings, but an adapter that threw
    away parseable findings because of a non-zero exit would lose real
    detections the first time the vendor changed that convention.
    """
    stub_runs(monkeypatch,
              ok(fixture("remote-a02-yara-call4-mutated.json"), exit_code=2,
                 stderr="some warning on the way out"),
              EMPTY_ARRAY, EMPTY_ARRAY, EMPTY_ARRAY)
    result = CiscoMcpScannerAdapter().run_runtime(target("a02-rug-pull", 8102))

    assert [f.raw_label for f in result.findings] == ["PROMPT INJECTION"]
    assert result.exit_code == 2
    assert result.error is None  # the output parsed; the exit code is recorded


def test_container_level_failure_is_recorded_per_surface(monkeypatch):
    stub_runs(monkeypatch, ContainerResult(
        exit_code=None, stdout="", stderr="", duration_seconds=0.0,
        error="scanner exceeded 300s and was killed"))
    result = CiscoMcpScannerAdapter().run_runtime(target())
    assert result.findings == []
    assert "exceeded 300s" in result.error
    assert result.error.count("exceeded 300s") == 4  # one per surface


def test_empty_findings_on_a_clean_scan_is_not_an_error(monkeypatch):
    stub_runs(monkeypatch, EMPTY_ARRAY)
    result = CiscoMcpScannerAdapter().run_runtime(target())
    assert result.findings == []
    assert result.error is None
    assert result.extra["items_scanned"] == {s: 0 for s in
                                             ("remote", "prompts", "resources",
                                              "instructions")}


# ---------------------------------------------------------------------------
# the adapter contract: never silently drop a finding
# ---------------------------------------------------------------------------


def test_a_finding_with_no_threat_name_is_surfaced_under_a_sentinel(monkeypatch):
    stub_runs(monkeypatch, ok(fixture("SYNTHETIC-unlabelled-finding.json")),
              EMPTY_ARRAY, EMPTY_ARRAY, EMPTY_ARRAY)
    result = CiscoMcpScannerAdapter().run_runtime(target())

    assert len(result.findings) == 1
    f = result.findings[0]
    assert f.raw_label == UNLABELLED
    assert f.raw["synthetic_label"] is True
    assert "named no threat" in f.raw["synthetic_label_reason"]
    assert f.raw["total_findings"] == 2
    # The sentinel must be unmappable, so it lands in `unmapped` and is
    # reported as a gap rather than being credited or penalised.
    entry, _ = load_mapping_file(MAPPING_FILE).lookup(UNLABELLED, stage="runtime")
    assert entry is None


def test_safe_verdicts_do_not_become_findings(monkeypatch):
    stub_runs(monkeypatch, ok(fixture("remote-a01-yara.json")),
              EMPTY_ARRAY, EMPTY_ARRAY, EMPTY_ARRAY)
    result = CiscoMcpScannerAdapter().run_runtime(target())
    assert result.findings == []


def test_the_adapter_maps_nothing_to_our_taxonomy(monkeypatch):
    """The adapter contract forbids it, and the ban has to be checkable."""
    stub_runs(monkeypatch, ok(fixture("label-probe-yara.json")),
              EMPTY_ARRAY, EMPTY_ARRAY, EMPTY_ARRAY)
    result = CiscoMcpScannerAdapter().run_runtime(target("probe", 8101))
    banned = {"A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10"}
    for f in result.findings:
        assert f.raw_label not in banned
        assert banned.isdisjoint(str(v) for v in f.raw.values())


# ---------------------------------------------------------------------------
# fixtures against the mapping table
# ---------------------------------------------------------------------------


def test_every_label_in_the_fixtures_has_a_mapping_entry():
    mapping = load_mapping_file(MAPPING_FILE)
    observed: set[str] = set()
    for path in sorted(FIXTURES.glob("*.json")):
        if path.name == "label-probe-tools.json":
            continue  # scanner input, not output
        doc = json.loads(path.read_text(), strict=False)
        for item in doc:
            findings = item.get("findings")
            blocks = list(findings.values()) if isinstance(findings, dict) else []
            for block in blocks:
                observed.update(block.get("threat_names") or [])

    assert observed  # the fixtures would otherwise be vacuous
    for label in sorted(observed):
        entry, how = mapping.lookup(label, stage="runtime")
        assert entry is not None, f"no mapping entry for captured label {label!r}"
        assert how == "exact", f"{label!r} matched by {how}, not byte-exactly"


def test_the_mapping_table_is_not_keyed_on_yara_rule_filenames():
    """The trap that would have zeroed this scanner for the wrong reason.

    Recon captured the ten rule filenames from the wheel. None of them is ever
    emitted: each rule reports its `meta.threat_type`, and the ten collapse onto
    seven. A table keyed on the filenames matches nothing and publishes a zero
    that says nothing about detection.
    """
    mapping = load_mapping_file(MAPPING_FILE)
    keys = {e.raw_label for e in mapping.entries}
    assert keys.isdisjoint(YARA_RULE_FILENAMES)
    assert set(OBSERVED_YARA_LABELS) <= keys
    assert "unknown" in keys  # the readiness analyzer's literal label


def test_mapping_table_agrees_with_the_adapter_it_is_keyed_on():
    mapping = load_mapping_file(MAPPING_FILE)
    adapter = CiscoMcpScannerAdapter()
    assert mapping.scanner_id == adapter.scanner_id
    assert mapping.adapter_version == adapter.adapter_version
    assert list(mapping.scanner_versions) == [adapter.scanner_version]
    assert mapping.label_provenance == "captured-from-real-output"
    # Byte-exact matching, as docs/mapping-rationale.md section 5 requires by
    # default: `unknown` and `PROMPT INJECTION` differ in case for real reasons.
    assert mapping.matching.is_exact


def test_only_prompt_injection_is_mapped_and_it_is_mapped_to_a1():
    mapping = load_mapping_file(MAPPING_FILE)
    mapped = {e.raw_label: e.mapped_class for e in mapping.entries
              if e.decision == "map"}
    assert mapped == {"PROMPT INJECTION": "A1"}

    entry = mapping.lookup("PROMPT INJECTION", stage="runtime")[0]
    assert entry.taxonomy_evidence is not None
    assert "tool descriptor" in entry.taxonomy_evidence["present_when_quote"]
    # The classes it plausibly spans are recorded with reasons, not hidden.
    assert {c["class"] for c in entry.considered_classes} == {"A2", "A3", "A4"}
    assert "R1" in entry.resolution_rules

    # Every non-mapped entry states why, and the two hardest say so honestly.
    for e in mapping.entries:
        if e.decision == "unmapped":
            assert e.unmapped_reason
    reasons = {e.raw_label: e.unmapped_reason for e in mapping.entries}
    assert reasons["TOOL POISONING"] == "no-defensible-single-class"
    assert reasons["INJECTION ATTACK"] == "no-defensible-single-class"
    assert reasons["CREDENTIAL HARVESTING"] == "no-defensible-single-class"
