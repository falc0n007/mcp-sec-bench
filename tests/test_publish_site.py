"""The publish guard: nothing credential-shaped reaches GitHub Pages."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import publish_site  # noqa: E402
from synthetic_credentials import get  # noqa: E402


def _site(tmp_path: Path, text: str) -> Path:
    site = tmp_path / "site"
    (site / "scanners").mkdir(parents=True)
    (site / "index.html").write_text("<p>scoreboard</p>")
    (site / "scanners" / "x.html").write_text(text)
    return site


def test_clean_site_passes(tmp_path):
    assert publish_site.scan_for_credentials(_site(tmp_path, "<p>ok</p>")) == []


def test_registered_synthetic_value_blocks(tmp_path):
    site = _site(tmp_path, f"<pre>{get('a07-aws-secret')}</pre>")
    problems = publish_site.scan_for_credentials(site)
    assert any("a07-aws-secret" in p for p in problems)
    assert all(p.startswith("scanners/x.html") for p in problems)


def test_unregistered_key_shape_blocks(tmp_path):
    site = _site(tmp_path, "key AKIA" + "Q" * 16 + " end")
    problems = publish_site.scan_for_credentials(site)
    assert problems and "AKIA" in problems[0]


def test_private_key_header_blocks(tmp_path):
    site = _site(tmp_path, "-----BEGIN RSA PRIVATE KEY-----")
    assert publish_site.scan_for_credentials(site)


def test_badge_json_is_scanned(tmp_path):
    site = _site(tmp_path, "<p>ok</p>")
    (site / "badges").mkdir()
    (site / "badges" / "x.json").write_text('{"message": "ghp_' + "a" * 36 + '"}')
    assert publish_site.scan_for_credentials(site)


def test_missing_results_fails(tmp_path, capsys):
    assert publish_site.main(["--results", str(tmp_path / "nope.json"),
                              "--dry-run"]) == 1
    assert "no results" in capsys.readouterr().err
