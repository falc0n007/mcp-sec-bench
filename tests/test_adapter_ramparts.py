"""Tests for the Ramparts adapter.

These test PARSING and the TRAP 1 guard, not ramparts itself. They run against
sample outputs committed under tests/fixtures/, captured from a real run of
`ramparts scan` (image mcp-sec-bench/ramparts:0.8.8, rules vendored from git
tag v0.8.8 of github.com/highflame-ai/ramparts) against the live lab -- so the
suite needs neither Docker nor the network, which is what makes it useful in
CI and what makes a parsing or trap-guard regression visible without a
scanner run.

Fixtures:
  * ramparts_a01_clean_rules_loaded.json -- real capture, rules verifiably
    loaded (YARA_PRE_SCAN_SUMMARY reports 15 rule files), zero findings. This
    is what every one of the 15 corpus servers actually produced.
  * ramparts_a01_rules_not_loaded.json -- real capture with
    RAMPARTS_RULES_DIR pointed at a directory that does not exist. Exit 0,
    `errors: []`, `yara_results: []`, no warning anywhere in the JSON --
    reproduces TRAP 1 (docs/scanner-survey.md) exactly. The only place the
    problem is visible at all is a stderr WARN line this test also feeds in.
  * ramparts_a01_synthetic_findings.json -- HAND-CONSTRUCTED (not a real
    corpus capture; the real corpus run never produced a finding). Reuses the
    real capture's server_info/tools/summary shape and injects two yara_results
    entries with real, verbatim YARA rule identifiers so the finding-parsing
    path has something to parse. Marked as such in the fixture's own
    `_fixture_note` field.

The container call is stubbed at `runner.adapters.ramparts.run_container`. The
adapter's own shape is exercised; the container harness has its own seam.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runner.adapters import AdapterResult, RuntimeTarget, StaticTarget
from runner.adapters.container import ContainerResult
from runner.adapters.ramparts import (
    IMAGE,
    RAMPARTS_RULES_TAG,
    RAMPARTS_VERSION,
    RULES_DIR_IN_CONTAINER,
    RampartsAdapter,
    RampartsRulesNotLoaded,
    _verify_rules_loaded,
)
from runner.models import RawFinding

FIXTURES = Path(__file__).parent / "fixtures"
CLEAN_FIXTURE = FIXTURES / "ramparts_a01_clean_rules_loaded.json"
NO_RULES_FIXTURE = FIXTURES / "ramparts_a01_rules_not_loaded.json"
SYNTHETIC_FIXTURE = FIXTURES / "ramparts_a01_synthetic_findings.json"

#: The 40 YARA rule identifiers actually compiled into
#: runner/adapters/dockerfiles/ramparts.Dockerfile's image, extracted with
#: `grep -h '^rule ' rules/pre/*.yar` at git tag v0.8.8 of
#: github.com/highflame-ai/ramparts (the exact tag the Dockerfile vendors).
#: A static, offline-checkable list -- no Docker or network needed to assert
#: mapping/ramparts.json covers all of it.
ALL_VENDORED_RULE_NAMES = frozenset({
    "ASPXWebshell", "AutonomyAbuse", "BackdoorPersistence", "C2FrameworkIndicators",
    "CapabilityInflation", "CoerciveInjection", "CommandInjection", "CovertExfiltration",
    "CrossOriginEscalation", "CryptoCoinjacking", "CryptoMinerSoftware",
    "CryptoMiningPools", "CryptoStratumProtocol", "EnvironmentVariableLeakage",
    "ExploitFramework", "IndirectPromptInjection", "InfoStealer", "JSPWebshell",
    "KeyloggerIndicators", "MCPConfigRisk", "NetworkReconnaissance",
    "OffensiveToolReferences", "PEMFileAccess", "PHPWebshellGeneric",
    "PHPWebshellKnown", "PHPWebshellObfuscated", "PathTraversalVulnerability",
    "PhishingKit", "PrivilegeEscalationTools", "PromptInjectionSignature",
    "PythonWebshell", "RansomwareBehavior", "ReverseShell", "SQLInjection",
    "SSHKeyExposure", "SecretsLeakage", "SkillCredentialHarvesting",
    "SkillSystemManipulation", "SkillToolChainingExfiltration", "UnicodeSteganography",
})

TOKEN = "lab-token-do-not-reuse"


def load_fixture(path: Path) -> dict:
    return json.loads(path.read_text())


@pytest.fixture
def adapter() -> RampartsAdapter:
    return RampartsAdapter()


@pytest.fixture
def authed_target() -> RuntimeTarget:
    return RuntimeTarget(
        server_id="a01-tool-description-injection",
        url="http://host.docker.internal:8101/mcp",
        token=TOKEN,
        authenticated=True,
    )


@pytest.fixture
def unauthed_target() -> RuntimeTarget:
    return RuntimeTarget(
        server_id="a06-authless-endpoint",
        url="http://host.docker.internal:8106/mcp",
        token=None,
        authenticated=False,
    )


def stub_container(monkeypatch, *, stdout: str, exit_code: int | None = 0,
                   stderr: str = "", error: str | None = None):
    """Replace the container call. Records the spec so invocation can be asserted."""
    seen: dict = {}

    def fake_run(spec):
        seen["spec"] = spec
        return ContainerResult(exit_code=exit_code, stdout=stdout, stderr=stderr,
                               duration_seconds=0.5, error=error)

    monkeypatch.setattr("runner.adapters.ramparts.run_container", fake_run)
    monkeypatch.setattr("runner.adapters.ramparts.docker_available", lambda: (True, ""))
    monkeypatch.setattr("runner.adapters.ramparts.image_present", lambda image: True)
    return seen


# ---------------------------------------------------------------------------
# Identity and stage declaration
# ---------------------------------------------------------------------------


def test_identity_fields(adapter):
    assert adapter.scanner_id == "ramparts"
    assert adapter.adapter_version == "1.0.0"
    assert adapter.requires_signup is False
    assert adapter.config_label == "default"
    assert adapter.display_name


def test_declares_runtime_only(adapter):
    """Ramparts' primary and only input this adapter exercises is a live URL."""
    assert adapter.stages == frozenset({"runtime"})
    assert "static" not in adapter.stages


def test_run_static_refuses_rather_than_returning_empty(adapter):
    with pytest.raises(NotImplementedError):
        adapter.run_static(StaticTarget(corpus_dir=Path("."), server_dirs=()))


# ---------------------------------------------------------------------------
# TRAP 1: the rules-not-loaded guard
# ---------------------------------------------------------------------------


def test_verify_rules_loaded_true_on_the_real_clean_capture():
    payload = load_fixture(CLEAN_FIXTURE)
    check = _verify_rules_loaded(payload)
    assert check.loaded is True
    assert check.rule_files_loaded == 15
    assert "15 rules executed" in check.summary_context


def test_verify_rules_loaded_false_when_the_summary_entry_is_absent():
    """The exact TRAP 1 shape: no RAMPARTS_RULES_DIR -> no summary entry at all."""
    payload = load_fixture(NO_RULES_FIXTURE)
    assert payload["yara_results"] == []  # sanity: reproduces the trap
    assert payload["errors"] == []  # and it is invisible in errors[] too
    check = _verify_rules_loaded(payload)
    assert check.loaded is False
    assert check.rule_files_loaded is None
    assert "YARA_PRE_SCAN_SUMMARY" in check.reason


def test_verify_rules_loaded_false_on_a_zero_rule_count_summary():
    """A summary entry CAN exist with zero rules compiled; must still refuse."""
    payload = {"yara_results": [{
        "target_type": "summary", "target_name": "pre-scan",
        "rule_name": "YARA_PRE_SCAN_SUMMARY",
        "context": "Pre-scan completed: 0 rules executed on 4 items",
    }]}
    check = _verify_rules_loaded(payload)
    assert check.loaded is False
    assert check.rule_files_loaded == 0


def test_verify_rules_loaded_false_when_context_does_not_parse():
    payload = {"yara_results": [{
        "rule_name": "YARA_PRE_SCAN_SUMMARY", "context": "something unexpected",
    }]}
    check = _verify_rules_loaded(payload)
    assert check.loaded is False


def test_run_runtime_refuses_findings_when_rules_did_not_load(adapter, authed_target,
                                                              monkeypatch):
    """The core TRAP 1 defence: never publish 0 findings from a disabled engine."""
    no_rules_json = NO_RULES_FIXTURE.read_text()
    stub_container(
        monkeypatch, stdout=no_rules_json, exit_code=0,
        stderr=("WARN No YARA rules directory found. Pattern-based detection is "
                "DISABLED for this run."),
    )
    result = adapter.run_runtime(authed_target)

    assert isinstance(result, AdapterResult)
    assert result.findings == []
    assert result.error is not None
    assert "REFUSING to report findings" in result.error
    assert "TRAP 1" in result.error
    assert result.extra["rules_loaded"] is False
    assert result.extra["rule_files_loaded"] is None


def test_the_guard_exception_class_exists_and_is_informative():
    """A dedicated exception, not a bare bool, so the guard can't be quietly
    removed by deleting a stray `if` -- see the module docstring."""
    exc = RampartsRulesNotLoaded("no summary entry")
    assert "no summary entry" in str(exc)
    assert issubclass(RampartsRulesNotLoaded, RuntimeError)


def test_run_runtime_with_rules_loaded_and_zero_findings_is_not_an_error(
        adapter, authed_target, monkeypatch):
    """This is what every one of the 15 corpus servers actually produced.

    Zero findings with rules PROVABLY loaded is a real, reportable result --
    it must not be confused with (and must not trigger) the TRAP 1 guard.
    """
    stub_container(monkeypatch, stdout=CLEAN_FIXTURE.read_text(), exit_code=0)
    result = adapter.run_runtime(authed_target)

    assert result.error is None
    assert result.findings == []
    assert result.extra["rules_loaded"] is True
    assert result.extra["rule_files_loaded"] == 15
    assert result.scanner_version == "0.8.8"


# ---------------------------------------------------------------------------
# Parsing findings
# ---------------------------------------------------------------------------


def test_parses_the_synthetic_findings_fixture(adapter, authed_target, monkeypatch):
    stub_container(monkeypatch, stdout=SYNTHETIC_FIXTURE.read_text(), exit_code=0)
    result = adapter.run_runtime(authed_target)

    assert result.error is None
    assert len(result.findings) == 2
    assert all(isinstance(f, RawFinding) for f in result.findings)
    assert all(f.scanner_id == "ramparts" for f in result.findings)
    assert all(f.server_id == "a01-tool-description-injection" for f in result.findings)
    assert all(f.stage == "runtime" for f in result.findings)


def test_raw_label_is_the_yara_rule_name_verbatim(adapter, authed_target, monkeypatch):
    """raw_label is what the mapping table is keyed on -- never touched."""
    stub_container(monkeypatch, stdout=SYNTHETIC_FIXTURE.read_text(), exit_code=0)
    result = adapter.run_runtime(authed_target)

    labels = [f.raw_label for f in result.findings]
    assert labels == ["PromptInjectionSignature", "CoerciveInjection"]
    for label in labels:
        assert label == label.strip()
        assert label in ALL_VENDORED_RULE_NAMES


def test_severity_and_message_are_carried(adapter, authed_target, monkeypatch):
    stub_container(monkeypatch, stdout=SYNTHETIC_FIXTURE.read_text(), exit_code=0)
    result = adapter.run_runtime(authed_target)

    prompt_injection = next(f for f in result.findings
                            if f.raw_label == "PromptInjectionSignature")
    assert prompt_injection.severity == "HIGH"
    assert "store_document" in prompt_injection.message
    assert prompt_injection.raw["target_type"] == "tool"


def test_pre_scan_summary_row_is_never_turned_into_a_finding(adapter, authed_target,
                                                              monkeypatch):
    """The summary row is metadata about the run, consumed by the TRAP 1 guard,
    never a security finding in its own right."""
    stub_container(monkeypatch, stdout=SYNTHETIC_FIXTURE.read_text(), exit_code=0)
    result = adapter.run_runtime(authed_target)
    assert all(f.raw_label != "YARA_PRE_SCAN_SUMMARY" for f in result.findings)


def test_every_rule_this_adapter_could_ever_report_has_a_mapping_entry():
    """A label ramparts could genuinely emit must not reach the scoreboard as a
    silent gap. Static/offline: compares the vendored rule-name list against
    mapping/ramparts.json, no Docker or network needed."""
    from runner.mapping import load_mapping_file, load_schema

    root = Path(__file__).resolve().parent.parent
    table = load_mapping_file(root / "mapping" / "ramparts.json", schema=load_schema())
    covered = {e.raw_label for e in table.entries}
    assert covered == ALL_VENDORED_RULE_NAMES


def test_the_mapping_table_is_keyed_on_this_adapter_version(adapter):
    root = Path(__file__).resolve().parent.parent
    table = json.loads((root / "mapping" / "ramparts.json").read_text())
    assert table["scanner_id"] == adapter.scanner_id
    assert table["adapter_version"] == adapter.adapter_version
    assert table["label_source_field"] == "yara_results[].rule_name"


# ---------------------------------------------------------------------------
# Non-zero exit that still produced a valid, rules-loaded result
# ---------------------------------------------------------------------------


def test_nonzero_exit_with_valid_rules_loaded_output_is_success(adapter, authed_target,
                                                                monkeypatch):
    stub_container(monkeypatch, stdout=SYNTHETIC_FIXTURE.read_text(), exit_code=1)
    result = adapter.run_runtime(authed_target)

    assert result.error is None
    assert result.exit_code == 1
    assert len(result.findings) == 2
    assert result.extra.get("nonzero_exit_with_valid_output") is True


def test_scan_status_failure_is_flagged_even_with_rules_loaded(adapter, authed_target,
                                                                monkeypatch):
    """ramparts' own ScanStatus enum reports a non-Success outcome (e.g. it could
    not reach the server) as a single-key object -- must not be read as a clean
    scan just because rules loaded and JSON parsed."""
    payload = json.loads(CLEAN_FIXTURE.read_text())
    payload["status"] = {"ConnectionError": "connection refused"}
    stub_container(monkeypatch, stdout=json.dumps(payload), exit_code=0)
    result = adapter.run_runtime(authed_target)

    assert result.error is not None
    assert "ConnectionError" in result.error
    assert "connection refused" in result.error
    assert result.extra["ramparts_status"] == "ConnectionError"


# ---------------------------------------------------------------------------
# Malformed output
# ---------------------------------------------------------------------------


def test_unparseable_stdout_becomes_an_error_not_a_crash(adapter, authed_target,
                                                         monkeypatch):
    stub_container(monkeypatch, stdout="thread 'main' panicked at ...\n",
                   exit_code=101, stderr="segfault or similar")
    result = adapter.run_runtime(authed_target)

    assert result.findings == []
    assert result.error is not None
    assert "could not parse ramparts JSON" in result.error
    assert result.raw_output


def test_empty_stdout_becomes_an_error(adapter, authed_target, monkeypatch):
    stub_container(monkeypatch, stdout="", exit_code=1)
    result = adapter.run_runtime(authed_target)
    assert result.findings == []
    assert "no stdout output" in (result.error or "")


def test_a_json_array_is_not_mistaken_for_a_report(adapter, authed_target, monkeypatch):
    stub_container(monkeypatch, stdout="[1, 2, 3]", exit_code=0)
    result = adapter.run_runtime(authed_target)
    assert result.findings == []
    assert "expected an object" in (result.error or "")


def test_container_level_failure_is_reported_not_raised(adapter, authed_target,
                                                         monkeypatch):
    stub_container(monkeypatch, stdout="", exit_code=None,
                  error="the docker daemon is not running")
    result = adapter.run_runtime(authed_target)
    assert result.findings == []
    assert result.exit_code is None
    assert "docker daemon" in (result.error or "")


def test_a_malformed_yara_result_entry_is_skipped_not_crashing(adapter, authed_target,
                                                               monkeypatch):
    """Entries missing rule_name, or not objects at all, do not crash parsing."""
    payload = json.loads(CLEAN_FIXTURE.read_text())
    payload["yara_results"] = [
        payload["yara_results"][0],  # the real summary row -- rules stay "loaded"
        "not an object",
        {"target_type": "tool", "target_name": "x"},  # no rule_name
        {"target_type": "tool", "target_name": "y", "rule_name": "SecretsLeakage",
         "context": "ctx"},
    ]
    stub_container(monkeypatch, stdout=json.dumps(payload), exit_code=0)
    result = adapter.run_runtime(authed_target)

    assert result.error is None
    assert len(result.findings) == 1
    assert result.findings[0].raw_label == "SecretsLeakage"


# ---------------------------------------------------------------------------
# Invocation: auth headers, env, lab reachability
# ---------------------------------------------------------------------------


def test_authenticated_target_passes_the_bearer_token(adapter, authed_target,
                                                       monkeypatch):
    seen = stub_container(monkeypatch, stdout=CLEAN_FIXTURE.read_text(), exit_code=0)
    adapter.run_runtime(authed_target)

    spec = seen["spec"]
    assert spec.args[0] == "scan"
    assert spec.args[1] == authed_target.url
    assert "--auth-headers" in spec.args
    idx = spec.args.index("--auth-headers")
    assert spec.args[idx + 1] == f"Authorization: Bearer {TOKEN}"


def test_unauthenticated_target_omits_auth_headers_entirely(adapter, unauthed_target,
                                                             monkeypatch):
    """a06-authless-endpoint / c04-status-service take no auth -- the token must
    never be sent to a server that doesn't expect one."""
    seen = stub_container(monkeypatch, stdout=CLEAN_FIXTURE.read_text(), exit_code=0)
    adapter.run_runtime(unauthed_target)

    spec = seen["spec"]
    assert "--auth-headers" not in spec.args
    assert TOKEN not in spec.args


def test_authenticated_with_no_token_is_refused_not_silently_scanned(adapter,
                                                                     monkeypatch):
    """A bug that drops the token must fail loudly, not scan unauthenticated."""
    seen = stub_container(monkeypatch, stdout=CLEAN_FIXTURE.read_text(), exit_code=0)
    broken_target = RuntimeTarget(
        server_id="a01-tool-description-injection",
        url="http://host.docker.internal:8101/mcp",
        token=None,
        authenticated=True,
    )
    result = adapter.run_runtime(broken_target)
    assert "spec" not in seen  # container never invoked
    assert result.error is not None
    assert "no token" in result.error


def test_rules_dir_env_is_set_explicitly_on_every_run(adapter, authed_target,
                                                       monkeypatch):
    """Belt-and-suspenders with the image's own default -- see module docstring."""
    seen = stub_container(monkeypatch, stdout=CLEAN_FIXTURE.read_text(), exit_code=0)
    adapter.run_runtime(authed_target)
    assert seen["spec"].env["RAMPARTS_RULES_DIR"] == RULES_DIR_IN_CONTAINER


def test_the_scan_reaches_the_lab_gateway(adapter, authed_target, monkeypatch):
    seen = stub_container(monkeypatch, stdout=CLEAN_FIXTURE.read_text(), exit_code=0)
    adapter.run_runtime(authed_target)
    assert seen["spec"].needs_lab is True
    assert seen["spec"].image == IMAGE


def test_extra_records_the_pinned_rules_provenance(adapter, authed_target,
                                                    monkeypatch):
    """docs/scanner-survey.md TRAP 1: the report must show which rules dir and
    tag were used, not just that rules loaded."""
    stub_container(monkeypatch, stdout=CLEAN_FIXTURE.read_text(), exit_code=0)
    result = adapter.run_runtime(authed_target)

    assert result.extra["rules_dir"] == RULES_DIR_IN_CONTAINER
    assert result.extra["rules_tag"] == RAMPARTS_RULES_TAG
    assert result.extra["ramparts_version_pinned"] == RAMPARTS_VERSION


# ---------------------------------------------------------------------------
# available()
# ---------------------------------------------------------------------------


def test_available_says_why_when_docker_is_down(adapter, monkeypatch):
    monkeypatch.setattr("runner.adapters.ramparts.docker_available",
                        lambda: (False, "the docker daemon is not running"))
    ok, reason = adapter.available()
    assert ok is False
    assert "docker daemon is not running" in reason


def test_available_says_how_to_build_when_the_image_is_missing(adapter, monkeypatch):
    monkeypatch.setattr("runner.adapters.ramparts.docker_available", lambda: (True, ""))
    monkeypatch.setattr("runner.adapters.ramparts.image_present", lambda image: False)
    ok, reason = adapter.available()
    assert ok is False
    assert IMAGE in reason
    assert "docker build" in reason


def test_available_is_true_when_docker_and_the_image_are_there(adapter, monkeypatch):
    monkeypatch.setattr("runner.adapters.ramparts.docker_available", lambda: (True, ""))
    monkeypatch.setattr("runner.adapters.ramparts.image_present", lambda image: True)
    assert adapter.available() == (True, "")


def test_run_runtime_reports_unavailable_rather_than_raising(adapter, authed_target,
                                                              monkeypatch):
    monkeypatch.setattr("runner.adapters.ramparts.docker_available",
                        lambda: (False, "the docker daemon is not running"))
    result = adapter.run_runtime(authed_target)
    assert result.findings == []
    assert "docker daemon is not running" in (result.error or "")
