"""Tests for the sentinel-scan-cli adapter.

These test the ADAPTER -- manifest generation, report parsing, the two-pass
drift sequence, and the invariants the adapter contract imposes -- not
sentinel-scan-cli itself. Everything runs against sample output committed under
tests/fixtures/, captured from real runs of
``mcp-sec-bench/sentinel-scan-cli:1.4.16`` against the live lab, so the suite
needs neither Docker nor the network.

Fixtures, all real captures:

  * ``sentinel-scan-cli-a02-manifest-capture1.json`` /
    ``...-capture6.json`` -- the two manifests the adapter generated for
    a02-rug-pull in one run, from ``tools/list`` call 1 and call 6 against a
    freshly restarted server. The only difference between them is
    ``summarize_changelog``'s description: this pair IS the rug-pull.

  * ``sentinel-scan-cli-a02-baseline-report.json`` -- pass 1's report
    (``--update-baseline``), scanning capture 1. Two findings, both about the
    generated ``mcpServers`` block.

  * ``sentinel-scan-cli-a02-post-trigger-report.json`` -- pass 2's report
    (``--baseline``), scanning capture 6. Four findings, including the
    ``tool_definition_drift`` that is this scanner's A2 detection and the
    ``tool_description_injection`` the harness's own provocation causes.

  * ``sentinel-scan-cli-whole-corpus-manifest.json`` /
    ``...-whole-corpus-report.json`` -- all 15 servers and 42 tools in one
    manifest, and its report. Committed as the offline evidence for the scope
    claim in the adapter's module docstring.

  * ``sentinel-scan-cli-empty-report.json`` -- a real report with zero
    findings (c04-status-service's descriptors with no ``mcpServers`` block),
    so the no-findings path is exercised against something the scanner really
    emitted rather than an empty dict we invented.

The container call is stubbed at ``runner.adapters.sentinel_scan.run_container``
and the live probe at ``runner.adapters.sentinel_scan.probe_descriptors``. The
container harness and the MCP client each have their own seam.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runner.adapters import RuntimeTarget, StaticTarget
from runner.adapters.container import ContainerResult
from runner.adapters.sentinel_scan import (
    BASELINE_HASHES,
    IMAGE,
    MANIFEST_BASELINE,
    MANIFEST_POST_TRIGGER,
    PHASE_BASELINE,
    PHASE_POST_TRIGGER,
    SCANNER_VERSION,
    TOKEN_PLACEHOLDER,
    WORK_MOUNTPOINT,
    SentinelManifestError,
    SentinelScanAdapter,
    build_manifest,
    descriptor_digest,
    merge_phases,
    parse_report,
    probe_descriptors,
    server_entry,
)

FIXTURES = Path(__file__).parent / "fixtures"

MANIFEST_C1 = FIXTURES / "sentinel-scan-cli-a02-manifest-capture1.json"
MANIFEST_C6 = FIXTURES / "sentinel-scan-cli-a02-manifest-capture6.json"
REPORT_BASELINE_FX = FIXTURES / "sentinel-scan-cli-a02-baseline-report.json"
REPORT_POST_FX = FIXTURES / "sentinel-scan-cli-a02-post-trigger-report.json"
WHOLE_MANIFEST_FX = FIXTURES / "sentinel-scan-cli-whole-corpus-manifest.json"
WHOLE_REPORT_FX = FIXTURES / "sentinel-scan-cli-whole-corpus-report.json"
EMPTY_REPORT_FX = FIXTURES / "sentinel-scan-cli-empty-report.json"

MAPPING_FILE = Path(__file__).parent.parent / "mapping" / "sentinel-scan-cli.json"

#: The complete heuristic vocabulary of sentinel-scan-cli 1.4.16, read out of
#: the shipped module in the pinned image (every literal first argument to
#: `_mcp_finding`). A static, offline-checkable list: if the adapter ever
#: reports a label outside it, either the image moved or parsing broke.
KNOWN_HEURISTICS = frozenset({
    "command_injection_risk",
    "cross_origin_exfiltration",
    "dos_resource_exhaustion",
    "excessive_agency_schema",
    "hardcoded_credential",
    "hidden_unicode_instructions",
    "homoglyph_typosquat",
    "indirect_injection_surface",
    "missing_hitl_confirmation",
    "missing_provenance",
    "overbroad_tool_scope",
    "tool_definition_drift",
    "tool_description_injection",
    "tool_name_shadowing",
    "unpinned_remote_source",
})

SERVER = "a02-rug-pull"
URL = "http://127.0.0.1:8102/mcp"
TOKEN = "lab-token-do-not-reuse"


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def target(server_id: str = SERVER, *, authenticated: bool = True,
           token: str | None = TOKEN) -> RuntimeTarget:
    return RuntimeTarget(server_id=server_id, url=URL, token=token,
                         authenticated=authenticated)


# --------------------------------------------------------------------------
# Manifest generation
# --------------------------------------------------------------------------


def test_manifest_has_both_blocks_the_scanner_reads():
    """Four of the eleven documented heuristics only read `mcpServers`.

    A tools-only manifest would run the tool at part of its capability and
    publish the result as a measurement.
    """
    tools = load(MANIFEST_C1)["tools"]
    m = build_manifest(SERVER, URL, True, tools, capture_index=1, probe_depth=6)

    assert set(m["mcpServers"]) == {SERVER}
    assert m["mcpServers"][SERVER]["url"] == URL
    assert isinstance(m["tools"], list) and m["tools"]


def test_manifest_keys_mcpservers_by_corpus_server_id():
    """Config-level findings put the mcpServers KEY in their `tool` field.

    Keying by corpus server_id means those findings name the server themselves
    instead of being attributed by us.
    """
    m = build_manifest("c04-status-service", "http://127.0.0.1:8204/mcp", False, [])
    assert list(m["mcpServers"]) == ["c04-status-service"]

    report = load(WHOLE_REPORT_FX)
    config_labels = {"unpinned_remote_source", "missing_provenance"}
    named = {f["tool"] for f in report["results"] if f["heuristic"] in config_labels}
    assert named == set(load(WHOLE_MANIFEST_FX)["mcpServers"])


def test_manifest_never_contains_a_credential_literal():
    """The bearer token is written as a placeholder, never as a literal.

    A literal would make `hardcoded_credential` fire on every authenticated
    server; that label maps to A7, so the harness would be manufacturing true
    positives against a credential it planted in a file it wrote -- including
    against controls that tolerate nothing.
    """
    m = build_manifest(SERVER, URL, True, load(MANIFEST_C1)["tools"])
    blob = json.dumps(m)
    assert TOKEN not in blob
    assert m["mcpServers"][SERVER]["headers"]["Authorization"] == (
        f"Bearer {TOKEN_PLACEHOLDER}")

    # ... and the committed artifacts really are free of it too.
    for path in (MANIFEST_C1, MANIFEST_C6, WHOLE_MANIFEST_FX):
        assert TOKEN not in path.read_text()


def test_unauthenticated_server_entry_carries_no_auth_header():
    entry = server_entry("http://127.0.0.1:8204/mcp", authenticated=False)
    assert entry == {"url": "http://127.0.0.1:8204/mcp"}


def test_manifest_preserves_wire_format_descriptors_verbatim():
    """`excessive_agency_schema` reads `inputSchema`, the wire spelling.

    The adapter must not rename, re-case, namespace or prefix anything: a
    prefixed tool name would change the exact input `tool_name_shadowing`'s
    edit-distance routes read.
    """
    tools = load(MANIFEST_C6)["tools"]
    m = build_manifest(SERVER, URL, True, tools)

    assert m["tools"] == tools
    assert [t["name"] for t in m["tools"]] == ["get_changelog", "summarize_changelog"]
    for tool in m["tools"]:
        assert "inputSchema" in tool
        assert "input_schema" not in tool


def test_generated_manifest_records_its_own_provenance():
    m = build_manifest(SERVER, URL, True, [], capture_index=1, probe_depth=6)
    prov = m["_mcp_sec_bench"]
    assert prov["server_id"] == SERVER
    assert prov["tools_list_capture_index"] == 1
    assert prov["tools_list_probe_depth"] == 6
    # The provenance key must not be one sentinel-scan-cli reads.
    assert set(m) == {"_mcp_sec_bench", "mcpServers", "tools"}


def test_the_two_committed_captures_differ_only_in_the_rug_pulled_description():
    """This pair is the A2 ground truth as the adapter actually captured it."""
    first = {t["name"]: t for t in load(MANIFEST_C1)["tools"]}
    last = {t["name"]: t for t in load(MANIFEST_C6)["tools"]}

    assert set(first) == set(last)
    assert first["get_changelog"] == last["get_changelog"]

    changed = first["summarize_changelog"]["description"]
    mutated = last["summarize_changelog"]["description"]
    assert changed != mutated
    assert "IMPORTANT SYSTEM NOTE" not in changed
    assert "IMPORTANT SYSTEM NOTE" in mutated
    assert descriptor_digest(load(MANIFEST_C1)["tools"]) != descriptor_digest(
        load(MANIFEST_C6)["tools"])


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


def parse_fixture(path: Path, phase: str = PHASE_POST_TRIGGER):
    return parse_report(
        load(path), scanner_id="sentinel-scan-cli", server_id=SERVER,
        phase=phase, manifest_path=f"{WORK_MOUNTPOINT}/{MANIFEST_POST_TRIGGER}")


def test_parses_every_finding_in_a_real_report():
    report = load(REPORT_POST_FX)
    findings = parse_fixture(REPORT_POST_FX)

    assert len(findings) == len(report["results"]) == report["summary"]["num_findings"]
    for f, src in zip(findings, report["results"]):
        assert f.scanner_id == "sentinel-scan-cli"
        assert f.raw_label == src["heuristic"]
        assert f.severity == src["severity"]
        assert f.message == src["evidence"]
        assert f.server_id == SERVER
        assert f.stage == "runtime"
        assert f.raw["tool"] == src["tool"]
        assert f.raw["owasp_mcp_category"] == src["owasp_mcp_category"]


def test_raw_label_is_the_heuristic_verbatim():
    """docs/mapping-rationale.md keys every decision on this exact string."""
    for path in (REPORT_BASELINE_FX, REPORT_POST_FX, WHOLE_REPORT_FX):
        report = load(path)
        findings = parse_report(
            report, scanner_id="sentinel-scan-cli", server_id=None,
            phase=PHASE_POST_TRIGGER, manifest_path="/work/mcp.json")
        observed = [f.raw_label for f in findings]
        assert observed == [f["heuristic"] for f in report["results"]]
        for label in observed:
            assert label in KNOWN_HEURISTICS
            assert label == label.strip()
            assert label == label.lower()


def test_every_observed_label_has_a_mapping_entry():
    """A label with no entry is scored `unmapped` and costs the scanner
    nothing -- but it also means our table drifted from the tool's vocabulary,
    which should fail here rather than surface as a silent gap in a run."""
    entries = {e["raw_label"] for e in load(MAPPING_FILE)["entries"]}
    assert entries == KNOWN_HEURISTICS

    for path in (REPORT_BASELINE_FX, REPORT_POST_FX, WHOLE_REPORT_FX):
        for finding in load(path)["results"]:
            assert finding["heuristic"] in entries


def test_a02_post_trigger_report_carries_the_drift_finding():
    """The whole reason this scanner is on the board."""
    labels = [f.raw_label for f in parse_fixture(REPORT_POST_FX)]
    assert "tool_definition_drift" in labels

    drift = next(f for f in parse_fixture(REPORT_POST_FX)
                 if f.raw_label == "tool_definition_drift")
    assert drift.raw["tool"] == "summarize_changelog"
    assert drift.server_id == SERVER
    assert drift.severity == "HIGH"

    # ... and it is absent before the baseline exists to compare against.
    baseline_labels = [f.raw_label for f in parse_fixture(REPORT_BASELINE_FX,
                                                          PHASE_BASELINE)]
    assert "tool_definition_drift" not in baseline_labels


def test_empty_report_yields_no_findings_and_no_error():
    report = load(EMPTY_REPORT_FX)
    assert report["summary"]["num_findings"] == 0
    assert parse_report(report, scanner_id="sentinel-scan-cli", server_id="c04-status-service",
                        phase=PHASE_BASELINE, manifest_path="/work/mcp.json") == []


def test_malformed_findings_are_preserved_not_dropped():
    """runner/adapters/__init__.py: an adapter never silently drops a finding."""
    report = {
        "summary": {"version": SCANNER_VERSION},
        "results": [
            "not an object",
            {"heuristic": "tool_definition_drift", "severity": "HIGH",
             "tool": "summarize_changelog", "evidence": "e"},
            42,
        ],
    }
    findings = parse_report(report, scanner_id="sentinel-scan-cli",
                            server_id=SERVER, phase=PHASE_POST_TRIGGER,
                            manifest_path="/work/mcp.json")

    assert len(findings) == 3
    assert findings[0].raw["malformed"] is True
    assert findings[0].raw_label == ""
    assert "results[0]" in findings[0].message
    assert findings[1].raw_label == "tool_definition_drift"
    assert findings[2].raw["malformed"] is True
    assert "results[2]" in findings[2].message


def test_finding_with_non_string_heuristic_keeps_an_empty_label_not_a_guess():
    findings = parse_report(
        {"results": [{"heuristic": None, "evidence": "x", "tool": "t"}]},
        scanner_id="sentinel-scan-cli", server_id=SERVER,
        phase=PHASE_BASELINE, manifest_path="/work/mcp.json")
    assert len(findings) == 1
    assert findings[0].raw_label == ""


@pytest.mark.parametrize("report", [
    {"summary": {}},                       # no results key at all
    {"results": None},
    {"results": {"heuristic": "x"}},       # object, not a list
])
def test_report_without_a_results_list_yields_nothing(report):
    assert parse_report(report, scanner_id="sentinel-scan-cli", server_id=SERVER,
                        phase=PHASE_BASELINE, manifest_path="/work/mcp.json") == []


def test_merge_phases_collapses_duplicates_and_records_both_passes():
    first = parse_fixture(REPORT_BASELINE_FX, PHASE_BASELINE)
    last = parse_fixture(REPORT_POST_FX, PHASE_POST_TRIGGER)
    merged = merge_phases(first, last)

    # Pass 2 is a superset here: its two extra findings are the drift and the
    # injection the provoked mutation causes.
    assert len(merged) == len(last)
    labels = {f.raw_label for f in merged}
    assert {"tool_definition_drift", "tool_description_injection"} <= labels

    seen_in_both = [f for f in merged
                    if f.raw["phases"] == [PHASE_BASELINE, PHASE_POST_TRIGGER]]
    assert {f.raw_label for f in seen_in_both} == {
        "unpinned_remote_source", "missing_provenance"}

    drift = next(f for f in merged if f.raw_label == "tool_definition_drift")
    assert drift.raw["phases"] == [PHASE_POST_TRIGGER]


# --------------------------------------------------------------------------
# Scope: the offline half of the A3 claim
# --------------------------------------------------------------------------


def test_whole_corpus_manifest_gave_the_scanner_the_cross_server_view():
    manifest = load(WHOLE_MANIFEST_FX)
    names = [t["name"] for t in manifest["tools"]]

    assert len(manifest["mcpServers"]) == 15
    assert len(names) == 42
    # No normalised-name collision and no near-duplicate pair exists to find:
    # the cross-server routes of `tool_name_shadowing` have nothing to fire on.
    assert len(set(names)) == 42


def test_no_cross_server_label_fires_even_at_whole_corpus_scope():
    """The A3 miss is the scanner's, not a limitation the harness imposed."""
    labels = {f["heuristic"] for f in load(WHOLE_REPORT_FX)["results"]}
    assert "tool_name_shadowing" not in labels
    assert "homoglyph_typosquat" not in labels


# --------------------------------------------------------------------------
# Adapter shape and invocation
# --------------------------------------------------------------------------


class _FakeContainer:
    """Stands in for `run_container`, writing the report the real scanner would.

    It records every argv it was given, which is how the drift sequence is
    asserted: pass 1 must record a baseline, pass 2 must compare against it.
    """

    def __init__(self, reports, exit_codes=(0, 0), write_report=True):
        self.reports = list(reports)
        self.exit_codes = list(exit_codes)
        self.write_report = write_report
        self.calls: list[list[str]] = []
        self.specs: list = []

    def __call__(self, spec):
        self.calls.append(list(spec.args))
        self.specs.append(spec)
        host_dir = Path(spec.mounts[0][0])
        args = list(spec.args)
        out_name = Path(args[args.index("--output") + 1]).name
        report = self.reports[len(self.calls) - 1]
        if self.write_report:
            (host_dir / out_name).write_text(json.dumps(report))
        if "--update-baseline" in args:
            base_name = Path(args[args.index("--baseline") + 1]).name
            (host_dir / base_name).write_text(json.dumps(
                {t["name"]: "hash" for t in report.get("_tools", [])}))
        return ContainerResult(
            exit_code=self.exit_codes[len(self.calls) - 1],
            stdout=json.dumps(report.get("summary", {})),
            stderr="",
            duration_seconds=0.1,
        )


@pytest.fixture
def stubbed(monkeypatch):
    """An adapter whose Docker and MCP seams are both stubbed."""
    monkeypatch.setattr(SentinelScanAdapter, "available", lambda self: (True, ""))
    monkeypatch.setattr(
        "runner.adapters.sentinel_scan.probe_descriptors",
        lambda *a, **k: [load(MANIFEST_C1)["tools"], load(MANIFEST_C6)["tools"]])
    return SentinelScanAdapter(probe_depth=6)


def install_container(monkeypatch, fake):
    monkeypatch.setattr("runner.adapters.sentinel_scan.run_container", fake)
    return fake


def test_run_runtime_drives_the_two_pass_drift_sequence(monkeypatch, stubbed):
    fake = install_container(monkeypatch, _FakeContainer(
        [load(REPORT_BASELINE_FX), load(REPORT_POST_FX)]))

    result = stubbed.run_runtime(target())

    assert len(fake.calls) == 2
    pass1, pass2 = fake.calls

    # Pass 1 scans the FIRST capture and records the baseline hashes.
    assert f"{WORK_MOUNTPOINT}/{MANIFEST_BASELINE}" in pass1
    assert "--update-baseline" in pass1
    assert f"{WORK_MOUNTPOINT}/{BASELINE_HASHES}" in pass1

    # Pass 2 scans the LAST capture against that baseline and does not update it.
    assert f"{WORK_MOUNTPOINT}/{MANIFEST_POST_TRIGGER}" in pass2
    assert "--update-baseline" not in pass2
    assert f"{WORK_MOUNTPOINT}/{BASELINE_HASHES}" in pass2

    for call in (pass1, pass2):
        assert call[0] == "mcp"
        assert "--format" in call and call[call.index("--format") + 1] == "json"
        # Exit 0 must mean "the scan ran", not "nothing crossed a threshold".
        assert call[call.index("--fail-on") + 1] == "none"

    assert {f.raw_label for f in result.findings} >= {
        "tool_definition_drift", "tool_description_injection"}
    assert result.error is None


def test_run_runtime_reports_the_drift_finding_against_the_right_server(
        monkeypatch, stubbed):
    install_container(monkeypatch, _FakeContainer(
        [load(REPORT_BASELINE_FX), load(REPORT_POST_FX)]))
    result = stubbed.run_runtime(target())

    drift = [f for f in result.findings if f.raw_label == "tool_definition_drift"]
    assert len(drift) == 1
    assert drift[0].server_id == SERVER
    assert drift[0].stage == "runtime"
    assert drift[0].raw["phases"] == [PHASE_POST_TRIGGER]


def test_run_runtime_discloses_that_the_manifest_is_generated(monkeypatch, stubbed):
    install_container(monkeypatch, _FakeContainer(
        [load(REPORT_BASELINE_FX), load(REPORT_POST_FX)]))
    result = stubbed.run_runtime(target())

    extra = result.extra
    assert extra["manifest_is_generated"] is True
    assert extra["scope"] == "per-server"
    assert "tools/list" in extra["descriptor_source"]
    assert extra["token_written_to_manifest"] == TOKEN_PLACEHOLDER
    assert extra["descriptors_changed_across_probes"] is True
    assert extra["probe_depth"] == 6
    assert result.scanner_version == SCANNER_VERSION

    # The generated input is in raw_output, because execute.py persists that
    # and nothing else -- without it nobody could tell whether a finding was
    # about a corpus server or about how the adapter wrote a config file.
    assert "GENERATED MANIFEST" in result.raw_output
    assert "summarize_changelog" in result.raw_output


def test_containers_get_no_network_and_a_writable_work_mount(monkeypatch, stubbed):
    fake = install_container(monkeypatch, _FakeContainer(
        [load(REPORT_BASELINE_FX), load(REPORT_POST_FX)]))
    stubbed.run_runtime(target())

    for spec in fake.specs:
        assert spec.image == IMAGE
        assert spec.network == "none"
        assert spec.needs_lab is False
        assert len(spec.mounts) == 1
        _, dest, mode = spec.mounts[0]
        assert (dest, mode) == (WORK_MOUNTPOINT, "rw")


def test_nonzero_exit_with_a_readable_report_still_reports_findings(
        monkeypatch, stubbed):
    """`--fail-on high` (or a future default change) makes exit 1 routine.

    Dropping findings over an exit code would turn a productive scan into an
    unavailable row.
    """
    install_container(monkeypatch, _FakeContainer(
        [load(REPORT_BASELINE_FX), load(REPORT_POST_FX)], exit_codes=(1, 1)))
    result = stubbed.run_runtime(target())

    assert result.exit_code == 1
    assert result.error is None
    assert "tool_definition_drift" in {f.raw_label for f in result.findings}


def test_unexpected_exit_code_is_recorded_but_findings_are_kept(
        monkeypatch, stubbed):
    install_container(monkeypatch, _FakeContainer(
        [load(REPORT_BASELINE_FX), load(REPORT_POST_FX)], exit_codes=(0, 3)))
    result = stubbed.run_runtime(target())

    assert "exited 3" in (result.error or "")
    assert "tool_definition_drift" in {f.raw_label for f in result.findings}


def test_no_readable_report_at_all_is_an_error_not_a_clean_scan(
        monkeypatch, stubbed):
    """"We could not run it" and "it found nothing" must never look alike."""
    install_container(monkeypatch, _FakeContainer(
        [load(REPORT_BASELINE_FX), load(REPORT_POST_FX)],
        exit_codes=(1, 1), write_report=False))
    result = stubbed.run_runtime(target())

    assert result.findings == []
    assert result.error and "no readable JSON report" in result.error


def test_version_mismatch_against_the_pin_is_recorded(monkeypatch, stubbed):
    moved = load(REPORT_POST_FX)
    moved["summary"] = dict(moved["summary"], version="9.9.9")
    install_container(monkeypatch, _FakeContainer(
        [load(REPORT_BASELINE_FX), moved]))
    result = stubbed.run_runtime(target())

    assert "9.9.9" in (result.error or "")
    assert SCANNER_VERSION in (result.error or "")
    assert result.findings  # still reported, never discarded over a version note


def test_authenticated_target_without_a_token_is_refused(monkeypatch, stubbed):
    install_container(monkeypatch, _FakeContainer([load(REPORT_BASELINE_FX)]))
    result = stubbed.run_runtime(target(authenticated=True, token=None))

    assert result.findings == []
    assert "refusing to probe unauthenticated" in (result.error or "")


def test_unreachable_endpoint_is_an_error_not_an_empty_finding_list(
        monkeypatch, stubbed):
    def boom(*a, **k):
        raise SentinelManifestError("could not read tools/list from ...: boom")

    monkeypatch.setattr("runner.adapters.sentinel_scan.probe_descriptors", boom)
    result = stubbed.run_runtime(target())

    assert result.findings == []
    assert "could not read tools/list" in (result.error or "")


def test_probe_depth_below_two_is_refused():
    """Two captures are the minimum a drift comparison can be built from."""
    with pytest.raises(SentinelManifestError):
        probe_descriptors(URL, TOKEN, depth=1)


# --------------------------------------------------------------------------
# Protocol surface
# --------------------------------------------------------------------------


def test_adapter_identity_matches_the_mapping_file_and_the_pinned_image():
    a = SentinelScanAdapter()
    doc = load(MAPPING_FILE)

    assert a.scanner_id == "sentinel-scan-cli" == doc["scanner_id"]
    assert a.adapter_version == "1.0.0" == doc["adapter_version"]
    assert a.requires_signup is False
    assert a.stages == frozenset({"runtime"})
    assert a.config_label == "default"
    assert a.image == IMAGE == f"mcp-sec-bench/sentinel-scan-cli:{SCANNER_VERSION}"
    assert doc["scanner_versions"] == [SCANNER_VERSION]
    assert doc["label_source_field"] == "results[].heuristic"


def test_run_static_refuses_rather_than_pretending_to_read_source():
    with pytest.raises(NotImplementedError) as exc:
        SentinelScanAdapter().run_static(
            StaticTarget(corpus_dir=Path("corpus"), server_dirs=()))
    assert "mcp.json" in str(exc.value)


def test_available_reports_docker_down_without_raising(monkeypatch):
    monkeypatch.setattr("runner.adapters.sentinel_scan.docker_available",
                        lambda: (False, "the docker daemon is not running"))
    ok, reason = SentinelScanAdapter().available()
    assert ok is False
    assert "docker daemon is not running" in reason


def test_available_reports_a_missing_image_with_the_build_command(monkeypatch):
    monkeypatch.setattr("runner.adapters.sentinel_scan.docker_available",
                        lambda: (True, ""))
    monkeypatch.setattr("runner.adapters.sentinel_scan.image_present",
                        lambda image: False)
    ok, reason = SentinelScanAdapter().available()
    assert ok is False
    assert IMAGE in reason and "docker build" in reason


def test_available_reports_a_misbehaving_docker_without_raising(monkeypatch):
    monkeypatch.setattr("runner.adapters.sentinel_scan.docker_available",
                        lambda: (True, ""))

    def explode(image):
        raise OSError("docker went away")

    monkeypatch.setattr("runner.adapters.sentinel_scan.image_present", explode)
    ok, reason = SentinelScanAdapter().available()
    assert ok is False
    assert "OSError" in reason
