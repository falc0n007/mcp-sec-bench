"""Write shields.io endpoint badges, and embeddable Markdown, per scanner.

    python tools/badges.py
    python tools/badges.py --results results/results.json --out public/badges \\
        --site-url https://falc0n007.github.io/mcp-sec-bench

For each scoreboard row this writes `<slug>.json`, a shields.io endpoint
document (schemaVersion 1), and `<slug>.md`, a Markdown snippet a vendor can
paste into a README. `snippets.md` collects every snippet in one file.

A badge deliberately carries NO score, rank, grade, or pass/fail colour.
docs/scoring.md forbids a composite index, and a badge is the one place a
number would be copied out of context and stripped of its caveats. It says
only that the scanner was benchmarked against a named corpus version, or that
it could not be run, and its colour is fixed per state so it cannot be read as
a verdict. The reader clicks through to the scoreboard row for the numbers.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_site import (  # noqa: E402
    DEFAULT_RESULTS, display_label, scanner_slug, sorted_scanners, unavailable_reason,
)
from runner.results import load_results, validate_results  # noqa: E402

DEFAULT_OUT = DEFAULT_RESULTS.parent / "site" / "badges"
DEFAULT_SITE_URL = "https://falc0n007.github.io/mcp-sec-bench"
LABEL = "mcp-sec-bench"

#: Fixed per state, never derived from a number.
COLOR_BENCHMARKED = "blue"
COLOR_UNAVAILABLE = "lightgrey"


def badge_for(scanner: dict[str, Any], corpus_version: str) -> dict[str, Any]:
    """The shields.io endpoint document for one row."""
    if unavailable_reason(scanner) is not None:
        message, color = "unavailable", COLOR_UNAVAILABLE
    else:
        message, color = f"benchmarked · corpus {corpus_version}", COLOR_BENCHMARKED
    return {"schemaVersion": 1, "label": LABEL, "message": message, "color": color}


def snippet_for(scanner: dict[str, Any], site_url: str) -> str:
    """Markdown a vendor can embed; the badge links to that scanner's page."""
    slug = scanner_slug(scanner)
    base = site_url.rstrip("/")
    endpoint = f"{base}/badges/{slug}.json"
    # shields.io needs the endpoint URL percent-encoded as a query value.
    img = f"https://img.shields.io/endpoint?url={quote(endpoint, safe='')}"
    alt = f"{LABEL}: {display_label(scanner)}"
    return f"[![{alt}]({img})]({base}/scanners/{slug}.html)"


def write_badges(
    doc: dict[str, Any], out_dir: Path, site_url: str = DEFAULT_SITE_URL,
    include_fixtures: bool = False,
) -> list[Path]:
    problems = validate_results(doc)
    if problems:
        raise ValueError("results document failed validation: " + "; ".join(problems[:5]))

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    collected: list[str] = [
        "# Badge snippets", "",
        "Paste a snippet into a README. Badges carry no score by design; they link "
        "to the scoreboard row.", "",
    ]
    for s in sorted_scanners(doc, include_fixtures):
        slug = scanner_slug(s)
        badge_path = out_dir / f"{slug}.json"
        badge_path.write_text(
            json.dumps(badge_for(s, doc["corpus_version"]), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        snippet = snippet_for(s, site_url)
        md_path = out_dir / f"{slug}.md"
        md_path.write_text(snippet + "\n", encoding="utf-8")
        written += [badge_path, md_path]
        collected += [f"## {display_label(s)}", "", "```markdown", snippet, "```", ""]

    snippets = out_dir / "snippets.md"
    snippets.write_text("\n".join(collected), encoding="utf-8")
    written.append(snippets)
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--results", default=str(DEFAULT_RESULTS))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--site-url", default=DEFAULT_SITE_URL,
                    help="where the site is published, for the embedded links")
    ap.add_argument("--include-fixtures", action="store_true")
    args = ap.parse_args(argv)

    try:
        written = write_badges(load_results(args.results), Path(args.out),
                               args.site_url, args.include_fixtures)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"wrote {len(written)} files under {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
