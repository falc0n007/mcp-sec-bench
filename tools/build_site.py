"""Render a results.json into a static scoreboard site.

    python tools/build_site.py                       # results/local/results.json
    python tools/build_site.py --results results/results.json --out public/

Output is plain HTML with inline CSS: no JavaScript, no external hosts, no
build step, so the directory can be served by anything and still renders
offline. One `index.html` carries the scoreboard; each scanner row also gets
`scanners/<slug>.html` with the detail behind its numbers.

This module is presentation only, like runner/report.py, and obeys the same
binding rules from docs/scoring.md and docs/governance.md:

- Rows sort alphabetically by scanner id, never by score. There is no
  composite score, ranking, or grade anywhere on the page.
- Per-class recall is the primary table. Overall recall and precision sit side
  by side; every figure with a range reads "mean (min-max)" over the runs.
- A class a scanner structurally cannot attempt reads "n/a", never "0.00".
  A statistic with no data reads "-", never "0.00".
- near_miss is only ever rendered in the same cell as the false-positive count,
  and is never described as "almost right".
- A scanner that could not be run still gets a row, carrying its reason.
- The corpus version and generation time are printed on every page, together
  with the caveat that this is a small synthetic corpus, not a safety
  certification.

The input is validated against schema/results.schema.json before anything is
written, so a malformed document fails loudly rather than rendering a
plausible-looking page.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from runner.models import CLASSES  # noqa: E402
from runner.results import load_results, validate_results  # noqa: E402

REPO_URL = "https://github.com/falc0n007/mcp-sec-bench"
DOCS_URL = f"{REPO_URL}/blob/main/docs"
DEFAULT_RESULTS = ROOT / "results" / "local" / "results.json"
DEFAULT_OUT = ROOT / "results" / "local" / "site"

NOT_ATTEMPTED = "n/a"
NO_DATA = "-"

CAVEAT = (
    "Recall is measured against a small synthetic corpus of deliberately "
    "vulnerable MCP servers, not against real-world MCP servers in the wild. "
    "A high score here is not a safety certification."
)

#: (label, doc, anchor) -- the methodology a reader needs to interpret a number.
METHOD_LINKS = [
    ("Scoring", "scoring.md", ""),
    ("Attack taxonomy", "taxonomy.md", ""),
    ("Governance and dispute process", "governance.md", "contesting-a-result"),
    ("Mapping rationale", "mapping-rationale.md", ""),
    ("Decision log", "decisions.md", ""),
]


# --------------------------------------------------------------------------
# Data helpers (shared with tools/badges.py)
# --------------------------------------------------------------------------


def scanner_slug(scanner: dict[str, Any]) -> str:
    """Stable, filesystem- and URL-safe id for one scoreboard row.

    A scanner run under a non-default config is a separate row (docs/governance.md
    treats a configuration change as a new row), so the label is part of the slug.
    """
    parts = [scanner["scanner_id"]]
    label = scanner.get("config_label") or ""
    if label and label != "default":
        parts.append(label)
    return re.sub(r"[^a-z0-9._-]+", "-", "-".join(parts).lower()).strip("-")


def display_label(scanner: dict[str, Any]) -> str:
    label = scanner.get("display_name") or scanner["scanner_id"]
    config = scanner.get("config_label") or ""
    if config and config != "default":
        label = f"{label} ({config})"
    return label


def unavailable_reason(scanner: dict[str, Any]) -> str | None:
    """The reason a scanner could not be run, or None if it produced runs.

    Mirrors runner/report.py: a zero-run row is unavailable even if the reason
    field is missing, so a scanner can never silently vanish from the page.
    """
    if scanner.get("unavailable_reason"):
        return scanner["unavailable_reason"]
    if scanner.get("runs", 0) > 0:
        return None
    return "; ".join(scanner.get("notes") or []) or "unavailable"


def sorted_scanners(
    doc: dict[str, Any], include_fixtures: bool = False
) -> list[dict[str, Any]]:
    """Rows in the only permitted order: alphabetical, never by score.

    Fixture adapters (`fixture-*`) exist to test the harness. They are not
    scanners, so they stay off the published page unless asked for.
    """
    rows = [
        s for s in doc["scanners"]
        if include_fixtures or not s["scanner_id"].startswith("fixture-")
    ]
    return sorted(rows, key=lambda s: (s["scanner_id"].lower(), s.get("config_label", "")))


def false_positive_mean(scanner: dict[str, Any]) -> float | None:
    """Mean false-positive count per run, from the per-run items.

    results.json carries near_miss_mean in `metrics` but the false-positive
    count only as items, so it is recomputed here. None when the document was
    written without item detail, in which case near_miss is not shown at all.
    """
    items = scanner.get("items")
    runs = scanner.get("runs", 0)
    if not items or runs <= 0:
        return None
    per_run: dict[int, int] = defaultdict(int)
    for it in items:
        if it["outcome"] == "false_positive":
            per_run[it["run_index"]] += 1
    return sum(per_run.values()) / runs


# --------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------


def _esc(text: Any) -> str:
    return html.escape(str(text), quote=True)


def fmt_stat(block: dict[str, Any] | None) -> str:
    """'0.42 (0.33-0.50)', or '-' when there is no mean to show."""
    if not block or block.get("mean") is None:
        return NO_DATA
    mean, lo, hi = block["mean"], block.get("min"), block.get("max")
    if lo is None or hi is None:
        return f"{mean:.2f}"
    return f"{mean:.2f} ({lo:.2f}-{hi:.2f})"


def fmt_class_cell(scanner: dict[str, Any], cls: str) -> str:
    block = (scanner["metrics"].get("recall_per_class") or {}).get(cls)
    if block is None or block.get("mean") is None:
        # Never attempted is a different fact from attempted and missed.
        if cls in (scanner.get("not_attempted_classes") or []):
            return NOT_ATTEMPTED
        return NO_DATA
    return fmt_stat(block)


def fmt_fp_near_miss(scanner: dict[str, Any]) -> str:
    """False positives and near misses in ONE cell, so neither travels alone."""
    fp = false_positive_mean(scanner)
    if fp is None:
        return NO_DATA
    near = scanner["metrics"].get("near_miss_mean", 0.0)
    return f"{fp:.2f} false positives; {near:.2f} near miss"


def fmt_unmapped(scanner: dict[str, Any]) -> str:
    return f"{scanner['metrics'].get('unmapped_mean', 0.0):.2f}"


def _first_sentence(text: str) -> str:
    m = re.match(r"(.+?[.!?])(\s|$)", text.strip(), re.S)
    return m.group(1) if m else text.strip()


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------

STYLE = """
:root {
  --bg: #fbfaf8; --fg: #1d1c1a; --muted: #67645e; --rule: #dedbd4;
  --surface: #f3f1ec; --accent: #1f5f8b; --warn-bg: #f7eed8; --warn-fg: #6b4b05;
  color-scheme: light;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #161514; --fg: #e8e6e1; --muted: #a09c93; --rule: #34322e;
    --surface: #1e1d1b; --accent: #7db7e0; --warn-bg: #2d2615; --warn-fg: #e6cf8f;
    color-scheme: dark;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 0 1.25rem; background: var(--bg); color: var(--fg);
  font: 16px/1.55 ui-serif, Georgia, "Iowan Old Style", "Times New Roman", serif;
}
.wrap { max-width: 68rem; margin: 0 auto; padding: 2.5rem 0 4rem; }
h1 { font-size: 1.9rem; line-height: 1.2; margin: 0 0 .4rem; letter-spacing: -.01em; }
h2 { font-size: 1.2rem; margin: 2.6rem 0 .6rem; }
p { max-width: 46rem; }
a { color: var(--accent); }
.sans, table, .meta, .caveat, nav, footer, .tag {
  font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
.meta { color: var(--muted); font-size: .85rem; margin: 0 0 1.4rem; }
.meta span + span::before { content: "\\00b7"; margin: 0 .55rem; }
.caveat {
  background: var(--warn-bg); color: var(--warn-fg); border-radius: 4px;
  padding: .7rem .95rem; font-size: .88rem; max-width: none; margin: 1rem 0 0;
}
.scroll { overflow-x: auto; margin: .6rem 0 .4rem; }
table { border-collapse: collapse; width: 100%; font-size: .85rem; }
th, td { text-align: left; padding: .5rem .65rem; border-bottom: 1px solid var(--rule); vertical-align: top; }
th { font-weight: 600; color: var(--muted); font-size: .76rem; text-transform: uppercase; letter-spacing: .04em; white-space: nowrap; }
td.num { font-variant-numeric: tabular-nums; white-space: nowrap; }
tr.unavailable td { background: var(--surface); }
.note { color: var(--muted); font-size: .82rem; max-width: 46rem; }
.tag { display: inline-block; border: 1px solid var(--rule); border-radius: 3px; padding: 0 .35rem; font-size: .72rem; color: var(--muted); margin-left: .3rem; white-space: nowrap; }
details summary { cursor: pointer; }
details p { font-size: .82rem; color: var(--muted); }
nav { font-size: .85rem; margin-bottom: 1.6rem; }
footer { margin-top: 3.5rem; padding-top: 1rem; border-top: 1px solid var(--rule); font-size: .82rem; color: var(--muted); }
ul.links { padding-left: 1.1rem; font-family: ui-sans-serif, system-ui, sans-serif; font-size: .9rem; }
.ext { width: .75em; height: .75em; vertical-align: -.05em; margin-left: .2em; fill: none; stroke: currentColor; stroke-width: 1.6; }
dl { display: grid; grid-template-columns: max-content 1fr; gap: .3rem 1.2rem; font-size: .88rem; font-family: ui-sans-serif, system-ui, sans-serif; }
dt { color: var(--muted); } dd { margin: 0; }
""".strip()

ICON_DEFS = (
    '<svg width="0" height="0" style="position:absolute" aria-hidden="true">'
    '<symbol id="ext" viewBox="0 0 16 16"><path d="M9 2h5v5M14 2 7 9M12 10v3.5a.5.5 0 0 1-.5.5h-8'
    "a.5.5 0 0 1-.5-.5v-8a.5.5 0 0 1 .5-.5H7\"/></symbol></svg>"
)


def _ext_link(href: str, text: str) -> str:
    return (
        f'<a href="{_esc(href)}" rel="noopener">{_esc(text)}'
        f'<svg class="ext" aria-hidden="true"><use href="#ext"/></svg></a>'
    )


def _page(title: str, body: str) -> str:
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{_esc(title)}</title>\n<style>\n{STYLE}\n</style>\n</head>\n<body>\n"
        f'{ICON_DEFS}\n<div class="wrap">\n{body}\n</div>\n</body>\n</html>\n'
    )


def _meta(doc: dict[str, Any]) -> str:
    return (
        '<p class="meta">'
        f'<span>Corpus version <code>{_esc(doc["corpus_version"])}</code></span>'
        f'<span>Generated {_esc(doc["generated_at"])}</span>'
        f'<span>{_esc(doc["runs_per_scanner"])} runs per scanner</span></p>'
    )


def _caveat() -> str:
    return f'<p class="caveat">{_esc(CAVEAT)}</p>'


def _method_footer(prefix: str = "") -> str:
    items = "".join(
        "<li>"
        + _ext_link(f"{DOCS_URL}/{doc}" + (f"#{anchor}" if anchor else ""), label)
        + "</li>"
        for label, doc, anchor in METHOD_LINKS
    )
    return (
        "<footer><h2 style=\"margin-top:0\">Methodology</h2>"
        f'<ul class="links">{items}</ul>'
        f"<p>Source and raw results: {_ext_link(REPO_URL, 'mcp-sec-bench')}. "
        "This benchmark is vendor-neutral and does not rank scanners; there is "
        "no combined score by design.</p></footer>"
    )


def _flags(scanner: dict[str, Any]) -> str:
    out = ""
    if scanner["metrics"].get("high_variance"):
        out += '<span class="tag">high variance</span>'
    stages = scanner.get("stages_attempted") or []
    if stages and "runtime" not in stages:
        out += '<span class="tag">static only</span>'
    if stages and "static" not in stages:
        out += '<span class="tag">runtime only</span>'
    return out


def _unavailable_cell(reason: str) -> str:
    return (
        "<details><summary>Unavailable: "
        f"{_esc(_first_sentence(reason))}</summary><p>{_esc(reason)}</p></details>"
    )


def _row_name(scanner: dict[str, Any]) -> str:
    href = f"scanners/{scanner_slug(scanner)}.html"
    return f'<a href="{_esc(href)}">{_esc(display_label(scanner))}</a>{_flags(scanner)}'


def _index_table(scanners: list[dict[str, Any]]) -> str:
    head = (
        "<tr><th>Scanner</th><th>Requires signup</th><th>Runs</th>"
        "<th>Recall (overall)</th><th>Precision (overall)</th>"
        "<th>False positives and near miss</th><th>Unmapped</th></tr>"
    )
    rows = []
    for s in scanners:
        signup = "yes" if s["requires_signup"] else "no"
        reason = unavailable_reason(s)
        if reason is not None:
            rows.append(
                f'<tr class="unavailable"><td>{_row_name(s)}</td><td>{signup}</td>'
                f'<td class="num">0</td><td colspan="4">{_unavailable_cell(reason)}</td></tr>'
            )
            continue
        m = s["metrics"]
        rows.append(
            f"<tr><td>{_row_name(s)}</td><td>{signup}</td>"
            f'<td class="num">{_esc(s["runs"])}</td>'
            f'<td class="num">{_esc(fmt_stat(m.get("recall_overall")))}</td>'
            f'<td class="num">{_esc(fmt_stat(m.get("precision_overall")))}</td>'
            f'<td class="num">{_esc(fmt_fp_near_miss(s))}</td>'
            f'<td class="num">{fmt_unmapped(s)}</td></tr>'
        )
    return f'<div class="scroll"><table>{head}{"".join(rows)}</table></div>'


def _class_table(scanners: list[dict[str, Any]]) -> str:
    head = "<tr><th>Scanner</th>" + "".join(f"<th>{c}</th>" for c in CLASSES) + "</tr>"
    rows = []
    for s in scanners:
        if unavailable_reason(s) is not None:
            cells = f'<td colspan="{len(CLASSES)}">unavailable, reason given below</td>'
        else:
            cells = "".join(
                f'<td class="num">{_esc(fmt_class_cell(s, c))}</td>' for c in CLASSES
            )
        rows.append(f"<tr><td>{_row_name(s)}</td>{cells}</tr>")
    return f'<div class="scroll"><table>{head}{"".join(rows)}</table></div>'


def render_index(doc: dict[str, Any], scanners: list[dict[str, Any]]) -> str:
    if not scanners:
        content = '<p class="note">No scanner results yet.</p>'
    else:
        content = (
            "<h2>Per-class recall</h2>"
            '<p class="note">The primary number. Each cell is the fraction of that '
            "attack class's corpus items the scanner found, as mean (min-max) over "
            "the runs. Aggregate recall hides how little the scanners' taxonomies "
            f"overlap. {_ext_link(f'{DOCS_URL}/taxonomy.md', 'Class definitions')}. "
            "<strong>n/a</strong> means the scanner never attempted that class "
            "(for example a static-only scanner and a runtime-only class), which is "
            "different from attempting it and missing. <strong>-</strong> means no "
            "data.</p>"
            f"{_class_table(scanners)}"
            "<h2>Overall recall and precision</h2>"
            '<p class="note">Shown side by side and never combined into one number. '
            "Rows are alphabetical; position carries no meaning. Near misses are "
            "false positives on the right server with the wrong class; they earn no "
            "credit, and a large count is not evidence of near-competence. "
            f"{_ext_link(f'{DOCS_URL}/scoring.md', 'How scores work')}.</p>"
            f"{_index_table(scanners)}"
        )
    body = (
        "<h1>mcp-sec-bench scoreboard</h1>"
        + _meta(doc) + _caveat() + content + _method_footer()
    )
    return _page("mcp-sec-bench scoreboard", body)


def _outcome_means(scanner: dict[str, Any]) -> dict[str, float]:
    runs = scanner.get("runs", 0)
    counts: dict[str, int] = defaultdict(int)
    for it in scanner.get("items") or []:
        counts[it["outcome"]] += 1
    return {k: v / runs for k, v in counts.items()} if runs else {}


def render_scanner(doc: dict[str, Any], scanner: dict[str, Any]) -> str:
    name = display_label(scanner)
    reason = unavailable_reason(scanner)
    facts = [
        ("Scanner id", scanner["scanner_id"]),
        ("Scanner version", scanner["scanner_version"]),
        ("Adapter version", scanner["adapter_version"]),
        ("Configuration", scanner.get("config_label") or "default"),
        ("Requires signup", "yes" if scanner["requires_signup"] else "no"),
        ("Stages attempted", ", ".join(scanner.get("stages_attempted") or []) or "none"),
        ("Runs", scanner["runs"]),
    ]
    na = scanner.get("not_attempted_classes") or []
    if na:
        facts.append(("Classes not attempted", ", ".join(na)))
    dl = "".join(f"<dt>{_esc(k)}</dt><dd>{_esc(v)}</dd>" for k, v in facts)

    parts = [
        '<nav><a href="../index.html">Scoreboard</a></nav>',
        f"<h1>{_esc(name)}</h1>",
        _meta(doc), _caveat(), f"<dl>{dl}</dl>",
    ]
    if reason is not None:
        parts.append(
            "<h2>Unavailable</h2><p>This scanner could not be run, so it has no "
            "scores. That is not the same as finding nothing.</p>"
            f"<p>{_esc(reason)}</p>"
        )
    else:
        m = scanner["metrics"]
        parts.append(
            "<h2>Per-class recall</h2>"
            '<div class="scroll"><table><tr><th>Class</th><th>Recall, mean (min-max)</th></tr>'
            + "".join(
                f'<tr><td>{c}</td><td class="num">{_esc(fmt_class_cell(scanner, c))}</td></tr>'
                for c in CLASSES
            )
            + "</table></div>"
            "<h2>Overall</h2>"
            '<div class="scroll"><table>'
            f'<tr><td>Recall</td><td class="num">{_esc(fmt_stat(m.get("recall_overall")))}</td></tr>'
            f'<tr><td>Precision</td><td class="num">{_esc(fmt_stat(m.get("precision_overall")))}</td></tr>'
            f'<tr><td>False positives and near miss, mean per run</td>'
            f'<td class="num">{_esc(fmt_fp_near_miss(scanner))}</td></tr>'
            f'<tr><td>Unmapped findings, mean per run</td>'
            f'<td class="num">{fmt_unmapped(scanner)}</td></tr>'
            "</table></div>"
        )
        if m.get("high_variance"):
            detail = m.get("variance_detail") or {}
            extra = "".join(f"<li>{_esc(k)}: {_esc(v)}</li>" for k, v in detail.items())
            parts.append(
                "<h2>Variance</h2><p>Flagged high variance: results differed "
                "materially between runs.</p>" + (f"<ul>{extra}</ul>" if extra else "")
            )
    notes = scanner.get("notes") or []
    if notes:
        parts.append(
            "<h2>Notes</h2><ul>" + "".join(f"<li>{_esc(n)}</li>" for n in notes) + "</ul>"
        )
    parts.append(_method_footer())
    return _page(f"{name} - mcp-sec-bench", "".join(parts))


def build_site(
    doc: dict[str, Any], out_dir: Path, include_fixtures: bool = False
) -> list[Path]:
    """Write the site; return every file written. Raises ValueError if `doc`
    does not validate, before anything is written."""
    problems = validate_results(doc)
    if problems:
        raise ValueError("results document failed validation: " + "; ".join(problems[:5]))

    scanners = sorted_scanners(doc, include_fixtures)
    out_dir = Path(out_dir)
    (out_dir / "scanners").mkdir(parents=True, exist_ok=True)

    written = [out_dir / "index.html"]
    written[0].write_text(render_index(doc, scanners), encoding="utf-8")
    for s in scanners:
        path = out_dir / "scanners" / f"{scanner_slug(s)}.html"
        path.write_text(render_scanner(doc, s), encoding="utf-8")
        written.append(path)
    # Pages must serve files starting with an underscore or dot as-is.
    nojekyll = out_dir / ".nojekyll"
    nojekyll.write_text("", encoding="utf-8")
    written.append(nojekyll)
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--results", default=str(DEFAULT_RESULTS))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--include-fixtures", action="store_true",
                    help="also render fixture-* harness adapters (off by default)")
    args = ap.parse_args(argv)

    doc = load_results(args.results)
    try:
        written = build_site(doc, Path(args.out), args.include_fixtures)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"wrote {len(written)} files under {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
