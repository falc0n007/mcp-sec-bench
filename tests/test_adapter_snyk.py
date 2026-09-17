"""Tests for the Snyk agent-scan adapter.

No Docker, no network. Two things this suite exists to nail down, because
getting either wrong would be a real incident rather than a cosmetic bug:

1. **`available()` returns `(False, reason)` promptly when `SNYK_TOKEN` is
   unset, naming the variable, and never raises.** This is the whole point
   of the adapter: docs/governance.md says a scanner we cannot run is
   published WITH its reason rather than omitted, and that only works if
   this method is reliable.
2. **`SNYK_TOKEN` never appears anywhere this adapter hands back or writes
   to disk** -- not in the generated mcpServers config (which is mounted
   read-only into a container and, in a real run, sits in a temp dir), not
   in `AdapterResult.raw_output`, not in `.error`, not in `.extra`. A run
   is simulated with the container call stubbed, including a worst-case
   scenario where the underlying tool's own stdout echoes the token back,
   to prove the adapter's redaction actually strips it rather than merely
   not adding it.

Parsing is tested against a fixture that is explicitly synthetic and
unverified (tests/fixtures/snyk-agent-scan-synthetic-unverified.json) --
SNYK_TOKEN gates all analysis and this project never obtained one, so
agent-scan 0.6.3's real --json shape has never been observed. See
mapping/snyk-agent-scan.json and runner/adapters/snyk_agent_scan.py's module
docstring for what "unverified" means here and what happens once a token
exists.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runner.adapters import AdapterResult, RuntimeTarget, StaticTarget
from runner.adapters.container import ContainerResult, ContainerSpec
from runner.adapters.snyk_agent_scan import (
    CONFIG_FILENAME,
    IMAGE,
    TOKEN_ENV_VAR,
    SnykAgentScanAdapter,
)
from runner.models import RawFinding

FIXTURE = Path(__file__).parent / "fixtures" / "snyk-agent-scan-synthetic-unverified.json"

FAKE_TOKEN = "sk-fake-should-never-leak-c0ffee12345"  # nosec: not a real credential


@pytest.fixture
def report() -> dict:
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def adapter() -> SnykAgentScanAdapter:
    return SnykAgentScanAdapter()


@pytest.fixture
def target() -> RuntimeTarget:
    return RuntimeTarget(
        server_id="a07-hardcoded-secrets",
        url="http://host.docker.internal:8107/mcp",
        token="lab-token-do-not-reuse",
        authenticated=True,
    )


def stub_container(monkeypatch, *, stdout: str, exit_code: int | None = 0,
                   stderr: str = "", error: str | None = None,
                   on_call=None):
    """Replace the container call. Records the spec so it can be asserted
    against, and optionally runs `on_call(spec)` before returning -- used to
    inspect the generated config file's contents while it still exists
    (run_runtime deletes its temp dir in a `finally` right after the call).
    """
    seen: dict = {}

    def fake_run(spec: ContainerSpec) -> ContainerResult:
        seen["spec"] = spec
        if on_call is not None:
            on_call(spec)
        return ContainerResult(exit_code=exit_code, stdout=stdout, stderr=stderr,
                               duration_seconds=0.5, error=error)

    monkeypatch.setattr("runner.adapters.snyk_agent_scan.run_container", fake_run)
    return seen


# ---------------------------------------------------------------------------
# Identity and the defining constraint: available()
# ---------------------------------------------------------------------------


def test_identity_fields(adapter):
    assert adapter.scanner_id == "snyk-agent-scan"
    assert adapter.adapter_version == "1.0.0"
    assert adapter.config_label == "default"
    assert adapter.display_name


def test_requires_signup_is_true(adapter):
    assert adapter.requires_signup is True


def test_available_false_when_token_unset(monkeypatch, adapter):
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)
    ok, reason = adapter.available()
    assert ok is False
    assert isinstance(reason, str) and reason


def test_available_reason_names_the_env_var(monkeypatch, adapter):
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)
    ok, reason = adapter.available()
    assert ok is False
    assert "SNYK_TOKEN" in reason
    # Something a scoreboard reader can act on: the env var name and the
    # fact that it gates ALL analysis, not merely an optional extra.
    assert "gates" in reason.lower() or "all analysis" in reason.lower()


def test_available_does_not_raise_when_token_unset(monkeypatch, adapter):
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)
    try:
        adapter.available()
    except Exception as exc:  # pragma: no cover - the assertion is the point
        pytest.fail(f"available() raised {type(exc).__name__}: {exc}")


def test_available_never_touches_docker_when_token_missing(monkeypatch, adapter):
    """The token check runs first and alone. If docker_available() or
    image_present() were ever called before the token check, a slow or
    misbehaving Docker daemon could delay or corrupt the one signal that
    matters most on this row -- the token reason."""
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)

    def boom(*a, **kw):
        raise AssertionError("docker_available() must not be called before the token check")

    monkeypatch.setattr("runner.adapters.snyk_agent_scan.docker_available", boom)
    monkeypatch.setattr("runner.adapters.snyk_agent_scan.image_present", boom)

    ok, reason = adapter.available()
    assert ok is False
    assert "SNYK_TOKEN" in reason


def test_available_true_when_token_set_and_docker_and_image_present(monkeypatch, adapter):
    monkeypatch.setenv(TOKEN_ENV_VAR, FAKE_TOKEN)
    monkeypatch.setattr("runner.adapters.snyk_agent_scan.docker_available", lambda: (True, ""))
    monkeypatch.setattr("runner.adapters.snyk_agent_scan.image_present", lambda image: True)
    ok, reason = adapter.available()
    assert ok is True
    assert reason == ""


def test_available_false_when_image_missing(monkeypatch, adapter):
    monkeypatch.setenv(TOKEN_ENV_VAR, FAKE_TOKEN)
    monkeypatch.setattr("runner.adapters.snyk_agent_scan.docker_available", lambda: (True, ""))
    monkeypatch.setattr("runner.adapters.snyk_agent_scan.image_present", lambda image: False)
    ok, reason = adapter.available()
    assert ok is False
    assert IMAGE in reason


def test_run_static_refuses_rather_than_returning_empty(adapter, tmp_path):
    target = StaticTarget(corpus_dir=tmp_path, server_dirs=(), scope="corpus")
    with pytest.raises(NotImplementedError):
        adapter.run_static(target)


def test_run_runtime_refuses_when_token_unset_without_touching_container(
    monkeypatch, adapter, target
):
    monkeypatch.delenv(TOKEN_ENV_VAR, raising=False)

    def boom(spec):
        raise AssertionError("run_container must not be called without a token")

    monkeypatch.setattr("runner.adapters.snyk_agent_scan.run_container", boom)

    result = adapter.run_runtime(target)
    assert isinstance(result, AdapterResult)
    assert result.findings == []
    assert result.error is not None
    assert "SNYK_TOKEN" in result.error


# ---------------------------------------------------------------------------
# The token must never leak
# ---------------------------------------------------------------------------


def test_token_never_written_into_generated_config(monkeypatch, adapter, target):
    """The generated mcpServers config carries the LAB's bearer token
    (target.token) for authenticating to the corpus server -- never
    SNYK_TOKEN. Checked both on the config-building helper directly and by
    inspecting the actual file on disk during a stubbed run, before the
    adapter's cleanup deletes it."""
    monkeypatch.setenv(TOKEN_ENV_VAR, FAKE_TOKEN)
    monkeypatch.setattr("runner.adapters.snyk_agent_scan.docker_available", lambda: (True, ""))
    monkeypatch.setattr("runner.adapters.snyk_agent_scan.image_present", lambda image: True)

    config = SnykAgentScanAdapter._build_mcp_servers_config(target)
    config_text = json.dumps(config)
    assert FAKE_TOKEN not in config_text
    assert TOKEN_ENV_VAR not in config_text
    # It DOES carry the lab token, which is not secret in this project (the
    # corpus's own fixed, disclosed lab credential) and is what the scanner
    # needs to authenticate to the target.
    assert target.token in config_text

    seen_config_contents: dict = {}

    def inspect_config_on_disk(spec: ContainerSpec) -> None:
        host_dir, _dest, _mode = spec.mounts[0]
        config_path = host_dir / CONFIG_FILENAME
        seen_config_contents["text"] = config_path.read_text()
        # Confirm the env var IS how the token reaches the container --
        # that is the one sanctioned channel -- and nowhere else.
        assert spec.env.get(TOKEN_ENV_VAR) == FAKE_TOKEN

    stub_container(monkeypatch, stdout=json.dumps({"findings": []}),
                   on_call=inspect_config_on_disk)

    adapter.run_runtime(target)

    assert "text" in seen_config_contents, "run_container was never called"
    assert FAKE_TOKEN not in seen_config_contents["text"]
    assert TOKEN_ENV_VAR not in seen_config_contents["text"]


def test_token_never_appears_in_raw_output_or_error(monkeypatch, adapter, target):
    """Worst case: the underlying tool's own stdout/stderr echoes the token
    back (a bug in agent-scan itself, or a verbose/debug mode). The adapter
    must still not hand it back to the caller."""
    monkeypatch.setenv(TOKEN_ENV_VAR, FAKE_TOKEN)
    monkeypatch.setattr("runner.adapters.snyk_agent_scan.docker_available", lambda: (True, ""))
    monkeypatch.setattr("runner.adapters.snyk_agent_scan.image_present", lambda image: True)

    leaking_stdout = (
        f"connecting with token {FAKE_TOKEN}\n"
        + json.dumps({"findings": []})
    )
    stub_container(monkeypatch, stdout=leaking_stdout,
                   stderr=f"debug: SNYK_TOKEN={FAKE_TOKEN}")

    result = adapter.run_runtime(target)

    assert FAKE_TOKEN not in result.raw_output
    assert FAKE_TOKEN not in (result.error or "")
    assert FAKE_TOKEN not in json.dumps(result.extra)
    for finding in result.findings:
        assert FAKE_TOKEN not in finding.message
        assert FAKE_TOKEN not in json.dumps(finding.raw)


def test_token_never_appears_in_error_path_output(monkeypatch, adapter, target):
    """Same guarantee on the no-parseable-JSON error path."""
    monkeypatch.setenv(TOKEN_ENV_VAR, FAKE_TOKEN)
    monkeypatch.setattr("runner.adapters.snyk_agent_scan.docker_available", lambda: (True, ""))
    monkeypatch.setattr("runner.adapters.snyk_agent_scan.image_present", lambda image: True)

    stub_container(monkeypatch, stdout=f"not json, token was {FAKE_TOKEN}",
                   stderr=f"fatal: bad token {FAKE_TOKEN}", exit_code=1)

    result = adapter.run_runtime(target)

    assert result.findings == []
    assert result.error is not None
    assert FAKE_TOKEN not in result.error
    assert FAKE_TOKEN not in result.raw_output


def test_token_refusal_marker_detected_even_with_token_set(monkeypatch, adapter, target):
    """If agent-scan itself prints its tokenless-refusal message despite a
    token being set (rejected/expired/invalid token), the adapter must
    surface an error rather than silently reporting zero findings, which
    would be indistinguishable from a genuine clean scan."""
    monkeypatch.setenv(TOKEN_ENV_VAR, FAKE_TOKEN)
    monkeypatch.setattr("runner.adapters.snyk_agent_scan.docker_available", lambda: (True, ""))
    monkeypatch.setattr("runner.adapters.snyk_agent_scan.image_present", lambda image: True)

    stub_container(
        monkeypatch,
        stdout=(
            "To use Agent Scan, set the SNYK_TOKEN environment variable. "
            "To get a token, go to https://app.snyk.io/account "
            "(API Token -> KEY -> click to show)."
        ),
        exit_code=1,
    )

    result = adapter.run_runtime(target)
    assert result.findings == []
    assert result.error is not None
    assert "refus" in result.error.lower() or "reject" in result.error.lower()
    assert FAKE_TOKEN not in result.error


# ---------------------------------------------------------------------------
# Parsing: defensive by necessity (label vocabulary is unverified)
# ---------------------------------------------------------------------------


def test_parse_report_preserves_all_findings(adapter, report):
    findings, extra = adapter.parse_report(report, "some-server")
    assert len(findings) == 3
    assert extra["matched_container_key"] == "findings"


def test_parse_report_verbatim_raw_label(adapter, report):
    findings, _extra = adapter.parse_report(report, "some-server")
    labels = [f.raw_label for f in findings]
    assert "secret detection" in labels
    assert "prompt injection" in labels
    # Verbatim: not upper-cased, not renamed, not stripped of spaces.
    assert "Secret Detection" not in labels
    assert "secret-detection" not in labels


def test_parse_report_all_findings_are_runtime_stage(adapter, report):
    findings, _extra = adapter.parse_report(report, "some-server")
    assert all(f.stage == "runtime" for f in findings)


def test_parse_report_assigns_server_id(adapter, report):
    findings, _extra = adapter.parse_report(report, "a07-hardcoded-secrets")
    assert all(f.server_id == "a07-hardcoded-secrets" for f in findings)


def test_parse_report_unanticipated_shape_not_dropped(adapter, report):
    """The third fixture entry deliberately carries none of the label
    fields this adapter looks for. It must still become a RawFinding, not
    vanish, per runner/adapters/__init__.py's contract."""
    findings, _extra = adapter.parse_report(report, "some-server")
    unrecognised = [f for f in findings if f.raw.get("totally_unrecognised_shape") is True]
    assert len(unrecognised) == 1
    finding = unrecognised[0]
    assert isinstance(finding, RawFinding)
    # No recognised label field was present; raw_label falls back to empty
    # rather than being invented, and the whole item survives in `raw` so a
    # human (or the mapping gap report) can still see it.
    assert finding.raw_label == ""
    assert finding.raw["nested_payload"]["value"] == 42


def test_parse_report_malformed_item_not_dropped(adapter):
    payload = {"findings": ["not-a-dict-finding", 42, None]}
    findings, _extra = adapter.parse_report(payload, "some-server")
    assert len(findings) == 3
    assert all(f.raw.get("malformed") is True for f in findings)


def test_parse_report_top_level_array(adapter):
    payload = [
        {"risk_indicator": "secret detection", "message": "x"},
        {"category": "prompt injection", "message": "y"},
    ]
    findings, extra = adapter.parse_report(payload, "some-server")
    assert len(findings) == 2
    assert extra["matched_container_key"] == "<top-level array>"
    assert {f.raw_label for f in findings} == {"secret detection", "prompt injection"}


def test_parse_report_no_recognised_container_does_not_fabricate_findings(adapter):
    """Unrelated top-level metadata (e.g. only scan_metadata, no findings
    array under any guessed key) must not be turned into a finding out of
    guesswork -- it is recorded for inspection and reported as zero
    findings, honestly."""
    payload = {"scan_metadata": {"cli_version": "0.6.3"}}
    findings, extra = adapter.parse_report(payload, "some-server")
    assert findings == []
    assert extra["matched_container_key"] is None
    assert "top_level_keys" in extra


def test_parse_report_label_field_priority(adapter):
    """When multiple candidate label fields are present, the first in
    priority order wins, and it is preserved verbatim."""
    payload = {"findings": [{"risk_indicator": "secret detection", "type": "should-not-win"}]}
    findings, _extra = adapter.parse_report(payload, "some-server")
    assert findings[0].raw_label == "secret detection"


# ---------------------------------------------------------------------------
# End-to-end run_runtime happy path (container stubbed)
# ---------------------------------------------------------------------------


def test_run_runtime_end_to_end_with_fixture(monkeypatch, adapter, target, report):
    monkeypatch.setenv(TOKEN_ENV_VAR, FAKE_TOKEN)
    monkeypatch.setattr("runner.adapters.snyk_agent_scan.docker_available", lambda: (True, ""))
    monkeypatch.setattr("runner.adapters.snyk_agent_scan.image_present", lambda image: True)

    stub_container(monkeypatch, stdout=json.dumps(report), exit_code=0)

    result = adapter.run_runtime(target)
    assert isinstance(result, AdapterResult)
    assert result.error is None
    assert len(result.findings) == 3
    assert result.scanner_version == "0.6.3"
    assert FAKE_TOKEN not in result.raw_output


def test_run_runtime_never_raises_on_docker_error(monkeypatch, adapter, target):
    monkeypatch.setenv(TOKEN_ENV_VAR, FAKE_TOKEN)
    monkeypatch.setattr("runner.adapters.snyk_agent_scan.docker_available", lambda: (True, ""))
    monkeypatch.setattr("runner.adapters.snyk_agent_scan.image_present", lambda image: True)

    def fake_run(spec):
        return ContainerResult(exit_code=None, stdout="", stderr="", duration_seconds=0.1,
                               error="the docker daemon is not running")

    monkeypatch.setattr("runner.adapters.snyk_agent_scan.run_container", fake_run)

    result = adapter.run_runtime(target)
    assert result.findings == []
    assert result.error == "the docker daemon is not running"
