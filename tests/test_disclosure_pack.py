"""Tests for tools/disclosure_pack.py, against a small synthetic results file.

The real results are gitignored until the disclosure window has run, so nothing
here reads them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runner.results import load_results, validate_results
from tools import disclosure_pack as dp

FIXTURE = Path(__file__).parent / "fixtures" / "disclosure_pack" / "results.json"


@pytest.fixture()
def doc():
    return load_results(FIXTURE)


def test_fixture_is_schema_valid(doc):
    assert validate_results(doc) == []


def test_slice_keeps_only_requested_scanner(doc):
    sliced = dp.slice_results(doc, "mcp-guard")
    assert [s["scanner_id"] for s in sliced["scanners"]] == ["mcp-guard"]
    assert sliced["corpus_version"] == doc["corpus_version"]
    assert validate_results(sliced) == []


def test_unknown_scanner_fails_loudly(doc, tmp_path):
    with pytest.raises(dp.PackError, match="unknown scanner id 'nope'"):
        dp.build_pack(doc, "nope", tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_build_pack_contents(doc, tmp_path):
    dest = dp.build_pack(doc, "mcp-guard", tmp_path)
    assert dest == tmp_path / "mcp-guard"
    for rel in (
        "results.json",
        "mapping.json",
        "PACK.json",
        "README.md",
        "adapter/mcp_guard.py",
        "adapter/container.py",
        "adapter/mcp-guard.Dockerfile",
    ):
        assert (dest / rel).is_file(), rel
    sliced = load_results(dest / "results.json")
    assert len(sliced["scanners"]) == 1
    assert sliced["scanners"][0]["findings"][0]["mapping_rationale_id"] == "MR-mcp-guard-001"
    meta = json.loads((dest / "PACK.json").read_text())
    assert meta["corpus_version"] == "v1-synthetic0000"
    assert meta["generated_at"] == "2026-01-01T00:00:00+00:00"
    # The mapping is a verbatim copy, not a regeneration.
    assert (dest / "mapping.json").read_bytes() == (dp.MAPPING_DIR / "mcp-guard.json").read_bytes()


def test_readme_lists_applicable_weaknesses_only(doc, tmp_path):
    dest = dp.build_pack(doc, "ramparts", tmp_path)
    readme = (dest / "README.md").read_text()
    assert "scan-surface limit" in readme
    assert "Credential-free" not in readme
    assert "small and synthetic" in readme


def test_rebuild_removes_stale_files(doc, tmp_path):
    dest = dp.build_pack(doc, "ramparts", tmp_path)
    (dest / "stale.txt").write_text("x")
    dp.build_pack(doc, "ramparts", tmp_path)
    assert not (dest / "stale.txt").exists()


def test_every_adapter_registered_and_present():
    for sid, module in dp.ADAPTER_FILES.items():
        assert (dp.ADAPTER_DIR / module).is_file(), sid
        assert (dp.DOCKERFILE_DIR / f"{sid}.Dockerfile").is_file(), sid
        assert (dp.MAPPING_DIR / f"{sid}.json").is_file(), sid


def test_main_all(tmp_path, capsys):
    rc = dp.main(["--all", "--results", str(FIXTURE), "--out", str(tmp_path)])
    assert rc == 0
    assert {p.name for p in tmp_path.iterdir()} == {"mcp-guard", "ramparts"}


def test_main_unknown_scanner_exits_nonzero(tmp_path, capsys):
    rc = dp.main(["--scanner", "nope", "--results", str(FIXTURE), "--out", str(tmp_path)])
    assert rc == 1
    assert "unknown scanner id" in capsys.readouterr().err


def test_main_missing_results_exits_nonzero(tmp_path, capsys):
    rc = dp.main(["--all", "--results", str(tmp_path / "absent.json"), "--out", str(tmp_path)])
    assert rc == 1
    assert "results file not found" in capsys.readouterr().err
