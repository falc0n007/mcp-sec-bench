"""Publish the static scoreboard to GitHub Pages from a local benchmark run.

The benchmark runs only on the maintainer's machine, so publishing is local
too: this builds the site and badges from a results.json, refuses to continue
if anything credential-shaped reached the output, and commits the result onto
the `gh-pages` branch, which GitHub Pages serves.

The guard matters because raw scanner output quotes the corpus's planted A7
credentials verbatim. The site is built from aggregate results and should never
carry them, but "should" is not a check, and these values trip GitHub secret
scanning. Every registered synthetic value, and anything shaped like a common
key format, stops the publish.

The branch is never force-pushed: each publish is a new commit on gh-pages, so
every scoreboard that was ever public stays in the history.

Usage:
    python tools/publish_site.py                  # build, check, commit, push
    python tools/publish_site.py --dry-run        # build and check only
    python tools/publish_site.py --results path/to/results.json
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from synthetic_credentials import BY_VALUE  # noqa: E402

BRANCH = "gh-pages"
DEFAULT_RESULTS = ROOT / "results" / "local" / "results.json"

# Shapes of real credential formats. Broad on purpose: a false alarm costs a
# look at the file; a miss publishes a key-shaped string to the world.
KEY_SHAPES = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{36}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"(sk|rk)_(live|test)_[A-Za-z0-9]{10,}"),
    re.compile(r"xox[abpr]-[A-Za-z0-9-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]


def scan_for_credentials(site_dir: Path) -> list[str]:
    """Return one problem line per credential-like hit under site_dir."""
    problems = []
    for path in sorted(site_dir.rglob("*")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(site_dir)
        for value, value_id in BY_VALUE.items():
            if value in text:
                problems.append(f"{rel}: registered synthetic value {value_id}")
        for shape in KEY_SHAPES:
            if shape.search(text):
                problems.append(f"{rel}: matches key shape {shape.pattern}")
    return problems


def build(results: Path, out: Path, site_url: str | None) -> None:
    """Render the site and badges into out."""
    py = sys.executable
    subprocess.run([py, str(ROOT / "tools" / "build_site.py"),
                    "--results", str(results), "--out", str(out)], check=True)
    badge_cmd = [py, str(ROOT / "tools" / "badges.py"),
                 "--results", str(results), "--out", str(out / "badges")]
    if site_url:
        badge_cmd += ["--site-url", site_url]
    subprocess.run(badge_cmd, check=True)


def _git(*args: str, cwd: Path = ROOT, capture: bool = False) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, check=True, text=True,
                          capture_output=capture)
    return done.stdout.strip() if capture else ""


def default_site_url() -> str | None:
    """https://<owner>.github.io/<repo>, derived from the origin remote."""
    try:
        url = _git("remote", "get-url", "origin", capture=True)
    except subprocess.CalledProcessError:
        return None
    m = re.search(r"github\.com[:/]([^/]+)/([^/.]+)", url)
    return f"https://{m.group(1)}.github.io/{m.group(2)}" if m else None


def commit_and_push(site_dir: Path, message: str) -> None:
    """Commit site_dir as the whole content of gh-pages, then push."""
    on_remote = _remote_has_branch()
    if on_remote:
        _git("fetch", "-q", "origin", BRANCH)
    with tempfile.TemporaryDirectory(prefix="gh-pages-") as tmp:
        wt = Path(tmp) / "wt"
        if on_remote:
            _git("worktree", "add", "-B", BRANCH, str(wt), f"origin/{BRANCH}")
        else:
            _git("worktree", "add", "--orphan", "-b", BRANCH, str(wt))
        try:
            for child in wt.iterdir():
                if child.name == ".git":
                    continue
                shutil.rmtree(child) if child.is_dir() else child.unlink()
            shutil.copytree(site_dir, wt, dirs_exist_ok=True)
            _git("add", "-A", cwd=wt)
            if not _git("status", "--porcelain", cwd=wt, capture=True):
                print("gh-pages already matches this build; nothing to publish.")
                return
            _git("commit", "-q", "-m", message, cwd=wt)
            _git("push", "origin", BRANCH, cwd=wt)
        finally:
            _git("worktree", "remove", "--force", str(wt))


def _remote_has_branch() -> bool:
    out = _git("ls-remote", "--heads", "origin", BRANCH, capture=True)
    return bool(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    ap.add_argument("--site-url", default=None,
                    help="public URL of the site, for badge links "
                         "(default: derived from the origin remote)")
    ap.add_argument("--dry-run", action="store_true",
                    help="build and check, but do not commit or push")
    args = ap.parse_args(argv)

    if not args.results.is_file():
        print(f"no results at {args.results}; run `make scoreboard` first",
              file=sys.stderr)
        return 1
    doc = json.loads(args.results.read_text())
    site_url = args.site_url or default_site_url()

    with tempfile.TemporaryDirectory(prefix="site-") as tmp:
        site_dir = Path(tmp) / "site"
        build(args.results, site_dir, site_url)

        problems = scan_for_credentials(site_dir)
        if problems:
            print("refusing to publish: credential-like content in the site:",
                  file=sys.stderr)
            for p in problems:
                print(f"  - {p}", file=sys.stderr)
            return 1
        print("credential check: clean")

        if args.dry_run:
            print("dry run: site built and checked, not published")
            return 0

        source = _git("rev-parse", "--short", "HEAD", capture=True)
        message = (f"Publish scoreboard, corpus {doc.get('corpus_version')}, "
                   f"generated {doc.get('generated_at')}, from {source}")
        commit_and_push(site_dir, message)
    if site_url:
        print(f"published: {site_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
