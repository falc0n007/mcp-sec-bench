"""Tests for the mcp-guard adapter.

These test PARSING, not mcp-guard. They run against a sample report committed
at tests/fixtures/mcp-guard-corpus-scan.json, captured from a real whole-corpus
scan (image mcp-sec-bench/mcp-guard:2.0.0, corpus v1-0f9650d5044b), so the suite
needs neither Docker nor the network -- which is what makes it useful in CI and
what makes a parsing regression visible without a scanner run.

The container call is stubbed at `runner.adapters.mcp_guard.run_container`. The
adapter's own shape is exercised; the container harness has its own seam.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runner.adapters import AdapterResult, StaticTarget
from runner.adapters.container import ContainerResult
from runner.adapters.mcp_guard import IMAGE, McpGuardAdapter
from runner.models import RawFinding

FIXTURE = Path(__file__).parent / "fixtures" / "mcp-guard-corpus-scan.json"

#: The corpus directory names as they stood when the fixture was captured.
CORPUS_DIRS = (
    "a01-tool-description-injection", "a02-rug-pull", "a03-tool-shadowing",
    "a04-response-injection", "a05-argument-exfiltration", "a06-authless-endpoint",
    "a07-hardcoded-secrets", "a08-unrestricted-file-read",
    "a09-unrestricted-env-access", "a10a-command-execution",
    "a10b-allowlist-bypass", "c01-notes-workspace", "c02-webhook-notifier",
    "c03-release-runner", "c04-status-service",
)


@pytest.fixture
def report() -> dict:
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def adapter() -> McpGuardAdapter:
    return McpGuardAdapter()


@pytest.fixture
def target(tmp_path: Path) -> StaticTarget:
    corpus = tmp_path / "corpus"
    dirs = []
    for name in CORPUS_DIRS:
        d = corpus / name
        d.mkdir(parents=True)
        dirs.append(d)
    return StaticTarget(corpus_dir=corpus, server_dirs=tuple(dirs), scope="corpus")


def stub_container(monkeypatch, *, stdout: str, exit_code: int | None = 0,
                   stderr: str = "", error: str | None = None):
    """Replace the container call. Records the spec so invocation can be asserted."""
    seen: dict = {}

    def fake_run(spec):
        seen["spec"] = spec
        return ContainerResult(exit_code=exit_code, stdout=stdout, stderr=stderr,
                               duration_seconds=0.5, error=error)

    monkeypatch.setattr("runner.adapters.mcp_guard.run_container", fake_run)
    return seen


# ---------------------------------------------------------------------------
# Identity and stage declaration
# ---------------------------------------------------------------------------


def test_declares_static_only(adapter):
    """Recon trap 3: the dynamic stage speaks stdio, the corpus speaks HTTP.

    Declaring runtime would produce a guaranteed-empty runtime result that reads
    like a tool that looked and found nothing.
    """
    assert adapter.stages == frozenset({"static"})
    assert "runtime" not in adapter.stages


def test_identity_fields(adapter):
    assert adapter.scanner_id == "mcp-guard"
    assert adapter.adapter_version == "1.0.0"
    assert adapter.requires_signup is False
    assert adapter.config_label == "default"
    assert adapter.display_name


def test_run_runtime_refuses_rather_than_returning_empty(adapter):
    with pytest.raises(NotImplementedError):
        adapter.run_runtime(object())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Parsing the captured sample
# ---------------------------------------------------------------------------


def test_parses_every_finding_in_the_sample(adapter, report):
    findings, unresolved = adapter.parse_report(report, frozenset(CORPUS_DIRS))
    assert len(findings) == len(report["findings"]) == 8
    assert unresolved == set()
    assert all(isinstance(f, RawFinding) for f in findings)
    assert {f.scanner_id for f in findings} == {"mcp-guard"}


def test_raw_label_is_the_rule_id_verbatim(adapter, report):
    """raw_label is what the mapping table is keyed on, so it is never touched."""
    findings, _ = adapter.parse_report(report, frozenset(CORPUS_DIRS))
    expected = [f["rule_id"] for f in report["findings"]]
    assert [f.raw_label for f in findings] == expected

    for f in findings:
        assert f.raw_label == f.raw_label.strip()
        assert f.raw_label.isupper() or "-" in f.raw_label
        # Not normalised in any direction.
        assert f.raw_label.startswith("MCPG-")

    assert {f.raw_label for f in findings} == {
        "MCPG-PY-SHELL-TAINT", "MCPG-SECRET-HARDCODED", "MCPG-PY-PATH-TAINT",
    }


def test_raw_label_survives_a_label_shaped_nothing_like_ours(adapter):
    """An unrecognised rule id is preserved, not normalised and not dropped."""
    weird = "mcpg-Some_New.Rule/2  "
    findings, _ = adapter.parse_report(
        {"findings": [{"rule_id": weird, "evidence": {"file": "x/server.py"}}]},
        frozenset(CORPUS_DIRS))
    assert len(findings) == 1
    assert findings[0].raw_label == weird


def test_location_severity_and_message_are_carried(adapter, report):
    findings, _ = adapter.parse_report(report, frozenset(CORPUS_DIRS))
    by_server = {f.server_id: f for f in findings if f.raw_label == "MCPG-PY-PATH-TAINT"}

    a08 = by_server["a08-unrestricted-file-read"]
    assert a08.file == "a08-unrestricted-file-read/server.py"
    assert a08.line == 85
    assert a08.severity == "high"
    assert "open()" in a08.message
    assert a08.stage == "static"


def test_extra_detail_lands_in_raw_not_in_the_typed_fields(adapter, report):
    """CWE, CVSS and OWASP AIVSS are preserved without inventing model fields."""
    findings, _ = adapter.parse_report(report, frozenset(CORPUS_DIRS))
    shell = next(f for f in findings if f.raw_label == "MCPG-PY-SHELL-TAINT")

    assert shell.raw["cwe"] == "CWE-78"
    assert shell.raw["cvss_vector"].startswith("CVSS:4.0/")
    assert isinstance(shell.raw["cvss_score"], (int, float))
    assert shell.raw["aivss"]["spec"] == "OWASP AIVSS v0.8"
    assert shell.raw["title"]
    assert shell.raw["matched_source"]
    assert shell.raw["evidence_kind"] == "static"


def test_the_sample_reproduces_the_published_per_server_result(adapter, report):
    """The row this adapter publishes, asserted as a table.

    a07 x3, a08, a10a, a10b are true positives; c01 and c03 are the control
    hits. If any of these six lines moves, a published number moves with it.
    """
    findings, _ = adapter.parse_report(report, frozenset(CORPUS_DIRS))
    got: dict[str, list[str]] = {}
    for f in findings:
        got.setdefault(f.server_id or "?", []).append(f.raw_label)

    assert got == {
        "a07-hardcoded-secrets": ["MCPG-SECRET-HARDCODED"] * 3,
        "a08-unrestricted-file-read": ["MCPG-PY-PATH-TAINT"],
        "a10a-command-execution": ["MCPG-PY-SHELL-TAINT"],
        "a10b-allowlist-bypass": ["MCPG-PY-SHELL-TAINT"],
        "c01-notes-workspace": ["MCPG-PY-PATH-TAINT"],
        "c03-release-runner": ["MCPG-SECRET-HARDCODED"],
    }


# ---------------------------------------------------------------------------
# Server resolution: resolve where we can, None where we cannot
# ---------------------------------------------------------------------------


def test_unknown_directory_leaves_server_id_none_and_is_reported(adapter):
    findings, unresolved = adapter.parse_report(
        {"findings": [{"rule_id": "MCPG-PY-PATH-TAINT",
                       "evidence": {"file": "_template/server.py", "line": 3}}]},
        frozenset(CORPUS_DIRS))
    assert findings[0].server_id is None
    assert findings[0].file == "_template/server.py"
    assert findings[0].raw["server_unresolved"] is True
    assert unresolved == {"_template/server.py"}


def test_two_server_names_in_one_path_is_unresolved_not_a_coin_flip(adapter):
    path = "a07-hardcoded-secrets/vendor/c01-notes-workspace/server.py"
    findings, unresolved = adapter.parse_report(
        {"findings": [{"rule_id": "MCPG-SECRET-HARDCODED",
                       "evidence": {"file": path}}]},
        frozenset(CORPUS_DIRS))
    assert findings[0].server_id is None
    assert unresolved == {path}


def test_a_finding_with_no_file_keeps_server_id_none(adapter):
    findings, unresolved = adapter.parse_report(
        {"findings": [{"rule_id": "MCPG-DEP-KNOWN-VULN", "severity": "medium"}]},
        frozenset(CORPUS_DIRS))
    assert len(findings) == 1
    assert findings[0].server_id is None
    assert findings[0].file is None
    assert unresolved == set()


# ---------------------------------------------------------------------------
# Non-zero exit that still produced findings
# ---------------------------------------------------------------------------


def test_exit_one_with_findings_is_a_successful_scan(adapter, target, report, monkeypatch):
    """mcp-guard exits 1 whenever it reports a finding at its --fail-on level.

    Treating that as a crash would turn every productive scan into an
    unavailable row with no findings.
    """
    stub_container(monkeypatch, stdout=json.dumps(report), exit_code=1)
    result = adapter.run_static(target)

    assert isinstance(result, AdapterResult)
    assert result.exit_code == 1
    assert result.error is None
    assert len(result.findings) == 8
    assert result.scanner_version == "2.0.0"


def test_exit_zero_with_no_findings_is_also_fine(adapter, target, monkeypatch):
    clean = {"schema_version": "2.0.0", "tool_version": "2.0.0",
             "summary": {"total": 0}, "findings": []}
    stub_container(monkeypatch, stdout=json.dumps(clean), exit_code=0)
    result = adapter.run_static(target)

    assert result.findings == []
    assert result.error is None


def test_an_unexpected_exit_code_keeps_the_findings_and_says_so(adapter, target,
                                                               report, monkeypatch):
    """Findings are never discarded because of an exit code we did not expect."""
    stub_container(monkeypatch, stdout=json.dumps(report), exit_code=3)
    result = adapter.run_static(target)

    assert len(result.findings) == 8
    assert result.error is not None
    assert "exited 3" in result.error


# ---------------------------------------------------------------------------
# Malformed output
# ---------------------------------------------------------------------------


def test_unparseable_stdout_becomes_an_error_not_a_crash(adapter, target, monkeypatch):
    stub_container(monkeypatch, stdout="Traceback (most recent call last):\n  boom\n",
                   exit_code=2, stderr="ImportError: tree_sitter")
    result = adapter.run_static(target)

    assert result.findings == []
    assert result.error is not None
    assert "no parseable JSON" in result.error
    assert result.raw_output  # kept for the published raw-output archive


def test_empty_stdout_becomes_an_error(adapter, target, monkeypatch):
    stub_container(monkeypatch, stdout="", exit_code=1)
    result = adapter.run_static(target)
    assert result.findings == []
    assert "no parseable JSON" in (result.error or "")


def test_a_banner_line_before_the_json_does_not_lose_the_report(adapter, target,
                                                                report, monkeypatch):
    stub_container(monkeypatch, stdout="scanning...\n" + json.dumps(report), exit_code=1)
    result = adapter.run_static(target)
    assert len(result.findings) == 8


def test_a_json_array_is_not_mistaken_for_a_report(adapter, target, monkeypatch):
    stub_container(monkeypatch, stdout="[1, 2, 3]", exit_code=0)
    result = adapter.run_static(target)
    assert result.findings == []
    assert "no parseable JSON" in (result.error or "")


def test_a_report_whose_findings_key_is_the_wrong_type(adapter):
    findings, unresolved = adapter.parse_report({"findings": "none"}, frozenset())
    assert findings == []
    assert unresolved == set()


def test_a_malformed_finding_is_preserved_rather_than_dropped(adapter):
    """An adapter never silently drops a finding it does not understand."""
    findings, _ = adapter.parse_report(
        {"findings": [
            "not an object",
            {"rule_id": "MCPG-PY-PATH-TAINT", "evidence": {"file": "c01-notes-workspace/s.py"}},
        ]},
        frozenset(CORPUS_DIRS))

    assert len(findings) == 2
    assert findings[0].raw["malformed"] is True
    assert "index 0" in findings[0].message
    assert findings[1].raw_label == "MCPG-PY-PATH-TAINT"


def test_a_finding_with_no_rule_id_falls_back_to_the_evidence_copy(adapter):
    findings, _ = adapter.parse_report(
        {"findings": [{"evidence": {"rule_id": "MCPG-JS-VM-EVAL", "file": "x.js"}}]},
        frozenset(CORPUS_DIRS))
    assert findings[0].raw_label == "MCPG-JS-VM-EVAL"


def test_a_non_integer_line_does_not_crash_the_parse(adapter):
    findings, _ = adapter.parse_report(
        {"findings": [
            {"rule_id": "MCPG-PY-PATH-TAINT", "evidence": {"file": "a.py", "line": "12"}},
            {"rule_id": "MCPG-PY-PATH-TAINT", "evidence": {"file": "b.py", "line": None}},
            {"rule_id": "MCPG-PY-PATH-TAINT", "evidence": {"file": "c.py", "line": "n/a"}},
        ]},
        frozenset(CORPUS_DIRS))
    assert [f.line for f in findings] == [12, None, None]


def test_container_level_failure_is_reported_not_raised(adapter, target, monkeypatch):
    stub_container(monkeypatch, stdout="", exit_code=None,
                   error="the docker daemon is not running")
    result = adapter.run_static(target)
    assert result.findings == []
    assert result.exit_code is None
    assert "docker daemon" in (result.error or "")


# ---------------------------------------------------------------------------
# Invocation: read-only corpus, no network, whole-corpus scope
# ---------------------------------------------------------------------------


def test_the_corpus_is_mounted_read_only(adapter, target, report, monkeypatch):
    """A scanner that wrote to the corpus would corrupt ground truth silently."""
    seen = stub_container(monkeypatch, stdout=json.dumps(report), exit_code=1)
    adapter.run_static(target)

    mounts = seen["spec"].mounts
    assert len(mounts) == 1
    host, dest, mode = mounts[0]
    assert dest == "/corpus"
    assert mode == "ro"
    assert host == target.corpus_dir.resolve()


def test_the_scan_is_offline_and_networkless(adapter, target, report, monkeypatch):
    seen = stub_container(monkeypatch, stdout=json.dumps(report), exit_code=1)
    adapter.run_static(target)

    spec = seen["spec"]
    assert spec.network == "none"
    assert "--offline" in spec.args
    assert "--no-cache" in spec.args
    assert spec.args[:1] == ["/corpus"]
    assert spec.args[spec.args.index("--format") + 1] == "json"
    assert spec.image == IMAGE


def test_the_scan_is_not_gated_on_is_mcp_server(adapter, target, report, monkeypatch):
    """mcp-guard reports is_mcp_server: false for every corpus server.

    Its detect stage wants a package.json / pyproject.toml / Dockerfile and the
    corpus ships none. The static stage runs anyway and finds the flaws, so the
    flag is recorded and acted on nowhere.
    """
    assert report["server_info"]["is_mcp_server"] is False
    stub_container(monkeypatch, stdout=json.dumps(report), exit_code=1)
    result = adapter.run_static(target)

    assert len(result.findings) == 8
    assert result.extra["is_mcp_server"] is False
    assert result.extra["detection_notes"]


# ---------------------------------------------------------------------------
# available()
# ---------------------------------------------------------------------------


def test_available_says_why_when_docker_is_down(adapter, monkeypatch):
    monkeypatch.setattr("runner.adapters.mcp_guard.docker_available",
                        lambda: (False, "the docker daemon is not running"))
    ok, reason = adapter.available()
    assert ok is False
    assert "docker daemon is not running" in reason


def test_available_says_how_to_build_when_the_image_is_missing(adapter, monkeypatch):
    monkeypatch.setattr("runner.adapters.mcp_guard.docker_available", lambda: (True, ""))
    monkeypatch.setattr("runner.adapters.mcp_guard.image_present", lambda image: False)
    ok, reason = adapter.available()
    assert ok is False
    assert IMAGE in reason
    assert "docker build" in reason


def test_available_does_not_raise_when_docker_misbehaves(adapter, monkeypatch):
    monkeypatch.setattr("runner.adapters.mcp_guard.docker_available", lambda: (True, ""))

    def boom(image):
        raise OSError("socket hung up")

    monkeypatch.setattr("runner.adapters.mcp_guard.image_present", boom)
    ok, reason = adapter.available()
    assert ok is False
    assert "socket hung up" in reason


def test_available_is_true_when_docker_and_the_image_are_there(adapter, monkeypatch):
    monkeypatch.setattr("runner.adapters.mcp_guard.docker_available", lambda: (True, ""))
    monkeypatch.setattr("runner.adapters.mcp_guard.image_present", lambda image: True)
    assert adapter.available() == (True, "")


# ---------------------------------------------------------------------------
# The mapping table this adapter's raw_labels are keyed on
# ---------------------------------------------------------------------------


def test_every_observed_label_has_a_mapping_entry(adapter, report):
    """A label we have actually seen fire must not reach the scoreboard as a gap."""
    from runner.mapping import load_mapping_file, load_schema

    root = Path(__file__).resolve().parent.parent
    table = load_mapping_file(root / "mapping" / "mcp-guard.json", schema=load_schema())
    covered = {e.raw_label for e in table.entries}

    findings, _ = adapter.parse_report(report, frozenset(CORPUS_DIRS))
    assert {f.raw_label for f in findings} <= covered


def test_the_mapping_table_is_keyed_on_this_adapter_version(adapter):
    """Changing which field feeds raw_label invalidates the table (schema note)."""
    root = Path(__file__).resolve().parent.parent
    table = json.loads((root / "mapping" / "mcp-guard.json").read_text())
    assert table["scanner_id"] == adapter.scanner_id
    assert table["adapter_version"] == adapter.adapter_version
    assert table["label_source_field"] == "findings[].rule_id"
    assert table["label_provenance"] == "captured-from-real-output"
