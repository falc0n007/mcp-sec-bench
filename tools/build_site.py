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
- Per-class recall is the primary result, drawn as a detection matrix with
  the figure printed under every mark. Overall recall and precision sit side
  by side. The index prints a range only where runs disagreed and says so
  when none did; scanner pages always print "mean (min-max)".
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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from runner.models import CLASS_STAGES, CLASSES  # noqa: E402
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

#: Short names from docs/taxonomy.md, for the column key and the scanner pages.
CLASS_NAMES: dict[str, str] = {
    "A1": "Tool-description injection",
    "A2": "Rug-pull",
    "A3": "Cross-server tool shadowing",
    "A4": "Response injection",
    "A5": "Argument exfiltration",
    "A6": "Authless endpoint",
    "A7": "Hardcoded secrets",
    "A8": "Unrestricted file read",
    "A9": "Unrestricted env access",
    "A10": "Command execution / allowlist bypass",
}

#: GitHub's anchors for the "## A1 — Tool-description injection" headings.
CLASS_ANCHORS: dict[str, str] = {
    "A1": "a1--tool-description-injection",
    "A2": "a2--rug-pull-mutated-tool-definition-after-trust",
    "A3": "a3--cross-server-tool-shadowing",
    "A4": "a4--response-injection",
    "A5": "a5--argument-exfiltration",
    "A6": "a6--authless-endpoint",
    "A7": "a7--hardcoded-secrets",
    "A8": "a8--unrestricted-file-read",
    "A9": "a9--unrestricted-env-access",
    "A10": "a10--command-execution--allowlist-bypass",
}


def class_groups() -> list[tuple[str, str, list[str]]]:
    """Columns grouped by where a class can be detected (runner/models.py).

    The grouping is information, not decoration: it is the reason a static-only
    or runtime-only scanner has whole blocks it never attempts.
    """
    groups = [
        ("Advertised metadata", "Creditable from source or from a live tools/list.",
         [c for c in CLASSES if CLASS_STAGES[c] == {"static", "runtime"}]),
        ("Live behaviour", "Only observable against a running server.",
         [c for c in CLASSES if CLASS_STAGES[c] == {"runtime"}]),
        ("Source code", "Only visible by reading the server's source.",
         [c for c in CLASSES if CLASS_STAGES[c] == {"static"}]),
    ]
    return [g for g in groups if g[2]]


def _esc(text: Any) -> str:
    return html.escape(str(text), quote=True)


def fmt_stat(block: dict[str, Any] | None) -> str:
    """'0.42', or '0.42 (0.33–0.50)' when the runs disagreed; '-' with no mean.

    When every run produced the same figure the range carries no information,
    so it is dropped from the scoreboard and stated once in the notes instead.
    Scanner pages use fmt_stat_full, which always prints the range.
    """
    if not block or block.get("mean") is None:
        return NO_DATA
    mean, lo, hi = block["mean"], block.get("min"), block.get("max")
    if lo is None or hi is None or lo == hi:
        return f"{mean:.2f}"
    return f"{mean:.2f} ({lo:.2f}–{hi:.2f})"


def fmt_stat_full(block: dict[str, Any] | None) -> str:
    """'0.42 (0.33–0.50)': mean (min–max), always, for the scanner pages."""
    if not block or block.get("mean") is None:
        return NO_DATA
    mean, lo, hi = block["mean"], block.get("min"), block.get("max")
    if lo is None or hi is None:
        return f"{mean:.2f}"
    return f"{mean:.2f} ({lo:.2f}–{hi:.2f})"


def fmt_count(value: float | None) -> str:
    """A per-run mean count without trailing zeros: 40, 1.2, 0.67."""
    if value is None:
        return NO_DATA
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def class_state(scanner: dict[str, Any], cls: str) -> tuple[str, float, str]:
    """(state, fill fraction, label) for one matrix cell.

    States: hit (found in every run), partial, miss (attempted, never found),
    na (never attempted), nodata.
    """
    block = (scanner["metrics"].get("recall_per_class") or {}).get(cls)
    if block is None or block.get("mean") is None:
        # Never attempted is a different fact from attempted and missed.
        if cls in (scanner.get("not_attempted_classes") or []):
            return "na", 0.0, NOT_ATTEMPTED
        return "nodata", 0.0, NO_DATA
    mean = block["mean"]
    state = "hit" if mean >= 1.0 else "miss" if mean <= 0.0 else "partial"
    return state, mean, fmt_stat(block)


def fmt_fp_near_miss(scanner: dict[str, Any]) -> str:
    """False positives and near misses in ONE cell, so neither travels alone."""
    fp = false_positive_mean(scanner)
    if fp is None:
        return NO_DATA
    near = scanner["metrics"].get("near_miss_mean", 0.0)
    fp_word = "false positive" if fp == 1 else "false positives"
    nm_word = "near miss" if near == 1 else "near misses"
    return f"{fmt_count(fp)} {fp_word}, {fmt_count(near)} {nm_word}"


def fmt_unmapped(scanner: dict[str, Any]) -> str:
    return fmt_count(scanner["metrics"].get("unmapped_mean", 0.0))


def fmt_generated(stamp: str) -> str:
    """'17 September 2026, 20:16 UTC' from an ISO-8601 timestamp."""
    try:
        dt = datetime.fromisoformat(stamp).astimezone(timezone.utc)
    except ValueError:
        return stamp
    return f"{dt.day} {dt:%B %Y}, {dt:%H:%M} UTC"


def split_name(scanner: dict[str, Any]) -> tuple[str, str]:
    """('mcp-guard', 'SaravanaGuhan/mcp-guard') from 'mcp-guard (SaravanaGuhan/mcp-guard)'."""
    label = display_label(scanner)
    m = re.match(r"^(.*?) \((.+)\)$", label)
    return (m.group(1), m.group(2)) if m else (label, "")


def _first_sentence(text: str) -> str:
    m = re.match(r"(.+?[.!?])(\s|$)", text.strip(), re.S)
    return m.group(1) if m else text.strip()


def _all_runs_agree(scanners: list[dict[str, Any]]) -> bool:
    for s in scanners:
        m = s.get("metrics") or {}
        blocks = list((m.get("recall_per_class") or {}).values())
        blocks += [m.get("recall_overall"), m.get("precision_overall")]
        for b in blocks:
            if b and b.get("min") is not None and b.get("min") != b.get("max"):
                return False
    return True


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------

STYLE = """
:root {
  --paper: #f7f8f6; --raised: #eef0ed; --ink: #1b2128; --muted: #5d6670;
  --rule: #d6dad8; --signal: #2f5bd3; --hatch: #b9c0c6;
  --caution: #8a5a00; --caution-rule: #d9a33a;
  color-scheme: light;
}
@media (prefers-color-scheme: dark) {
  :root {
    --paper: #12161b; --raised: #1a2027; --ink: #e4e8ec; --muted: #97a1ab;
    --rule: #2b323a; --signal: #86a8ff; --hatch: #46505a;
    --caution: #e7c27a; --caution-rule: #a5782a;
    color-scheme: dark;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 0 1.25rem; background: var(--paper); color: var(--ink);
  font: 16px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
  font-variant-numeric: tabular-nums;
  -webkit-font-smoothing: antialiased;
}
.wrap { max-width: 72rem; margin: 0 auto; padding: 3.5rem 0 4rem; }
a { color: var(--signal); text-underline-offset: .15em; text-decoration-thickness: 1px; }
a:focus-visible { outline: 2px solid var(--signal); outline-offset: 2px; border-radius: 2px; }
h1 { font-size: clamp(2rem, 4vw, 2.75rem); line-height: 1.1; letter-spacing: -.025em; font-weight: 700; margin: 0; }
h2 { font-size: 1.3rem; letter-spacing: -.01em; font-weight: 650; margin: 3.25rem 0 .35rem; }
h3 { font-size: 1rem; font-weight: 600; margin: 2rem 0 .5rem; }
p { max-width: 42rem; margin: .5rem 0; }
.lede { font-size: 1.15rem; color: var(--muted); margin: .6rem 0 1.5rem; max-width: 38rem; }
.facts { display: flex; flex-wrap: wrap; gap: .4rem 2rem; margin: 0 0 1.5rem; padding: 0; list-style: none; font-size: .875rem; }
.facts li { display: flex; flex-direction: column; }
.facts .k { color: var(--muted); font-size: .8rem; }
.facts code { font: inherit; }
.caveat { border-left: 3px solid var(--caution-rule); padding: .15rem 0 .15rem .9rem; color: var(--caution); font-size: .925rem; max-width: 46rem; }
.note { color: var(--muted); font-size: .9rem; }
.scroll { overflow-x: auto; margin: 1.25rem 0 .75rem; }

/* Detection matrix: the one loud element on the page. */
table.matrix { border-collapse: separate; border-spacing: 0; min-width: 100%; }
.matrix th, .matrix td { padding: 0; font-weight: normal; }
.matrix .group th { text-align: left; font-size: .8rem; color: var(--muted); padding: 0 .5rem .35rem; border-bottom: 1px solid var(--rule); }
.matrix .group th + th { border-left: 1.25rem solid var(--paper); }
.matrix .codes th { font-size: .8rem; font-weight: 600; padding: .5rem 0 .6rem; text-align: center; min-width: 3.6rem; }
.matrix .codes th abbr { text-decoration: none; cursor: help; }
.matrix tbody th { text-align: left; padding: .7rem 1.25rem .7rem 0; vertical-align: middle; min-width: 12rem; position: sticky; left: 0; background: var(--paper); z-index: 1; }
.matrix tbody tr + tr > * { border-top: 1px solid var(--rule); }
.matrix td.gap-before, .matrix th.gap-before { padding-left: 1.25rem; }
.name { display: block; font-weight: 600; }
.name a { color: var(--ink); text-decoration: none; }
.name a:hover { color: var(--signal); text-decoration: underline; }
.sub { display: block; color: var(--muted); font-size: .8rem; font-weight: normal; }
.cell { text-align: center; vertical-align: middle; padding: .7rem 0; }
.mark {
  display: block; width: 1.75rem; height: 1.75rem; margin: 0 auto .3rem; border-radius: 3px;
  border: 1.5px solid var(--muted);
  background: linear-gradient(to top, var(--signal) calc(var(--r, 0) * 100%), transparent 0);
}
.cell[data-state="hit"] .mark, .cell[data-state="partial"] .mark { border-color: var(--signal); }
.cell[data-state="na"] .mark {
  border: 1.5px dashed var(--hatch);
  background: repeating-linear-gradient(135deg, var(--hatch) 0 1px, transparent 1px 5px);
}
.cell[data-state="nodata"] .mark { border: 1.5px dotted var(--hatch); }
.v { display: block; font-size: .75rem; color: var(--muted); white-space: nowrap; }
.cell[data-state="hit"] .v, .cell[data-state="partial"] .v { color: var(--ink); font-weight: 600; }
.unavail { text-align: left; color: var(--muted); font-size: .9rem; padding: .7rem 0 .7rem 0; vertical-align: middle; }
.unavail strong { color: var(--ink); font-weight: 600; }

.legend { display: flex; flex-wrap: wrap; gap: .5rem 1.75rem; margin: .5rem 0 0; padding: 0; list-style: none; font-size: .85rem; color: var(--muted); }
.legend li { display: flex; align-items: center; gap: .5rem; }
.legend .cell { padding: 0; display: inline-block; }
.legend .mark { width: 1rem; height: 1rem; margin: 0; border-radius: 2px; }
.key { display: grid; grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr)); gap: 1rem 2rem; margin: 1.75rem 0 0; font-size: .875rem; }
.key h3 { margin: 0 0 .3rem; font-size: .875rem; }
.key p { margin: 0 0 .4rem; color: var(--muted); font-size: .8rem; }
.key dl { display: grid; grid-template-columns: 2.4rem 1fr; gap: .15rem .25rem; margin: 0; }
.key dt { font-weight: 600; } .key dd { margin: 0; }

/* Plain data tables. */
table.data { border-collapse: collapse; width: 100%; font-size: .9rem; }
.data th, .data td { text-align: left; padding: .65rem 1rem .65rem 0; border-bottom: 1px solid var(--rule); vertical-align: top; }
.data thead th { font-size: .8rem; font-weight: 600; color: var(--muted); border-bottom-color: var(--ink); vertical-align: bottom; }
.data td.num, .data th.num { text-align: right; white-space: nowrap; }
.data .fp { white-space: nowrap; padding-left: 1.5rem; }
.overall .name, .overall .sub { white-space: nowrap; }
.overall { min-width: 46rem; }
.narrow { max-width: 44rem; }
.overall th:last-child, .overall td:last-child { width: 100%; }
.data tbody th { font-weight: normal; }
.data tr.unavailable td { color: var(--muted); }
details summary { cursor: pointer; }
details p { font-size: .85rem; color: var(--muted); max-width: 48rem; }

.tag { display: inline-block; font-size: .72rem; color: var(--muted); border: 1px solid var(--rule); border-radius: 999px; padding: 0 .45rem; margin-top: .2rem; white-space: nowrap; font-weight: normal; }
nav { font-size: .9rem; margin-bottom: 2rem; }
dl.facts-list { display: grid; grid-template-columns: max-content 1fr; gap: .35rem 1.5rem; font-size: .9rem; margin: 1.5rem 0 0; }
dl.facts-list dt { color: var(--muted); } dl.facts-list dd { margin: 0; }
footer { margin-top: 4.5rem; padding-top: 1.5rem; border-top: 1px solid var(--rule); font-size: .875rem; color: var(--muted); }
footer h2 { margin: 0 0 .5rem; font-size: 1rem; color: var(--ink); }
ul.links { display: flex; flex-wrap: wrap; gap: .4rem 1.5rem; padding: 0; margin: 0 0 1rem; list-style: none; }
.ext { width: .7em; height: .7em; vertical-align: -.02em; margin-left: .2em; fill: none; stroke: currentColor; stroke-width: 1.6; }
.sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
@media (max-width: 40rem) {
  .wrap { padding-top: 2rem; }
  .matrix tbody th { min-width: 9rem; padding-right: .75rem; }
  .data { font-size: .85rem; }
}
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
    facts = [
        ("Corpus version", f'<code>{_esc(doc["corpus_version"])}</code>'),
        ("Benchmark run", _esc(fmt_generated(doc["generated_at"]))),
        ("Runs per scanner", _esc(doc["runs_per_scanner"])),
    ]
    items = "".join(
        f'<li><span class="k">{k}</span><span>{v}</span></li>' for k, v in facts
    )
    return f'<ul class="facts">{items}</ul>'


def _caveat() -> str:
    return f'<p class="caveat">{_esc(CAVEAT)}</p>'


def _method_footer() -> str:
    items = "".join(
        "<li>"
        + _ext_link(f"{DOCS_URL}/{doc}" + (f"#{anchor}" if anchor else ""), label)
        + "</li>"
        for label, doc, anchor in METHOD_LINKS
    )
    return (
        "<footer><h2>Methodology</h2>"
        f'<ul class="links">{items}</ul>'
        f"<p>Source and raw results: {_ext_link(REPO_URL, 'mcp-sec-bench')}. "
        "This benchmark is vendor-neutral and does not rank scanners; there is "
        "no combined score by design.</p></footer>"
    )


def _stage_tag(scanner: dict[str, Any]) -> str:
    out = ""
    if scanner["metrics"].get("high_variance"):
        out += '<span class="tag">high variance</span> '
    stages = scanner.get("stages_attempted") or []
    if stages and "runtime" not in stages:
        out += '<span class="tag">static only</span>'
    if stages and "static" not in stages:
        out += '<span class="tag">runtime only</span>'
    return out


def _name_block(scanner: dict[str, Any], link_prefix: str = "", tags: bool = True) -> str:
    name, sub = split_name(scanner)
    href = f"{link_prefix}scanners/{scanner_slug(scanner)}.html"
    out = f'<span class="name"><a href="{_esc(href)}">{_esc(name)}</a></span>'
    if sub:
        out += f'<span class="sub">{_esc(sub)}</span>'
    if tags:
        out += _stage_tag(scanner)
    return out


def _mark_cell(scanner: dict[str, Any], cls: str, gap: bool) -> str:
    state, fill, label = class_state(scanner, cls)
    words = {
        "hit": "found in every run", "partial": "found in some runs",
        "miss": "attempted, not found", "na": "not attempted", "nodata": "no data",
    }[state]
    title = f"{cls} {CLASS_NAMES[cls]}: {label} ({words})"
    gap_cls = " gap-before" if gap else ""
    return (
        f'<td class="cell{gap_cls}" data-state="{state}" style="--r:{fill:.3f}" '
        f'title="{_esc(title)}"><span class="mark" aria-hidden="true"></span>'
        f'<span class="v">{_esc(label)}</span>'
        f'<span class="sr"> {_esc(words)}</span></td>'
    )


def _matrix(scanners: list[dict[str, Any]]) -> str:
    groups = class_groups()
    group_row = '<tr class="group"><td></td>' + "".join(
        f'<th scope="colgroup" colspan="{len(cols)}">{_esc(label)}</th>'
        for label, _, cols in groups
    ) + "</tr>"
    codes = []
    for gi, (_, _, cols) in enumerate(groups):
        for ci, c in enumerate(cols):
            gap = " gap-before" if gi > 0 and ci == 0 else ""
            codes.append(
                f'<th scope="col" class="{gap.strip()}"><abbr title="{_esc(CLASS_NAMES[c])}">{c}</abbr></th>'
            )
    code_row = '<tr class="codes"><td></td>' + "".join(codes) + "</tr>"

    rows = []
    for s in scanners:
        reason = unavailable_reason(s)
        head = f'<th scope="row">{_name_block(s)}</th>'
        if reason is not None:
            signup = " Requires an account to run." if s.get("requires_signup") else ""
            rows.append(
                f'<tr>{head}<td class="unavail" colspan="{len(CLASSES)}">'
                f"<strong>Not measured.</strong> {_esc(_first_sentence(reason))}{signup}</td></tr>"
            )
            continue
        cells = []
        for gi, (_, _, cols) in enumerate(groups):
            for ci, c in enumerate(cols):
                cells.append(_mark_cell(s, c, gap=gi > 0 and ci == 0))
        rows.append(f"<tr>{head}{''.join(cells)}</tr>")

    return (
        '<div class="scroll"><table class="matrix">'
        f"<thead>{group_row}{code_row}</thead><tbody>{''.join(rows)}</tbody>"
        "</table></div>"
    )


def _legend() -> str:
    entries = [
        ("hit", 1.0, "Found in every run"),
        ("partial", 0.5, "Found in some runs, filled by recall"),
        ("miss", 0.0, "Attempted, not found"),
        ("na", 0.0, "Not attempted: outside what this scanner reads"),
    ]
    items = "".join(
        f'<li><span class="cell" data-state="{st}" style="--r:{r}">'
        f'<span class="mark" aria-hidden="true"></span></span>{_esc(text)}</li>'
        for st, r, text in entries
    )
    return f'<ul class="legend">{items}</ul>'


def _class_key() -> str:
    blocks = []
    for label, blurb, cols in class_groups():
        rows = "".join(
            f"<dt>{c}</dt><dd>"
            f'<a href="{_esc(DOCS_URL)}/taxonomy.md#{CLASS_ANCHORS[c]}">{_esc(CLASS_NAMES[c])}</a></dd>'
            for c in cols
        )
        blocks.append(
            f"<div><h3>{_esc(label)}</h3><p>{_esc(blurb)}</p><dl>{rows}</dl></div>"
        )
    return f'<div class="key">{"".join(blocks)}</div>'


def _overall_table(scanners: list[dict[str, Any]]) -> str:
    head = (
        "<thead><tr><th scope=\"col\">Scanner</th>"
        '<th scope="col" class="num">Recall</th><th scope="col" class="num">Precision</th>'
        '<th scope="col" class="fp">False positives and near misses, per run</th>'
        '<th scope="col" class="num">Unmapped findings, per run</th>'
        '<th scope="col">Requires signup</th></tr></thead>'
    )
    rows = []
    for s in scanners:
        signup = "yes" if s["requires_signup"] else "no"
        reason = unavailable_reason(s)
        name = f'<th scope="row">{_name_block(s, tags=False)}</th>'
        if reason is not None:
            rows.append(
                f'<tr class="unavailable">{name}<td colspan="4">'
                f"<details><summary>Not measured: {_esc(_first_sentence(reason))}</summary>"
                f"<p>{_esc(reason)}</p></details></td><td>{signup}</td></tr>"
            )
            continue
        m = s["metrics"]
        rows.append(
            f"<tr>{name}"
            f'<td class="num">{_esc(fmt_stat(m.get("recall_overall")))}</td>'
            f'<td class="num">{_esc(fmt_stat(m.get("precision_overall")))}</td>'
            f'<td class="fp">{_esc(fmt_fp_near_miss(s))}</td>'
            f'<td class="num">{fmt_unmapped(s)}</td>'
            f"<td>{signup}</td></tr>"
        )
    return f'<div class="scroll"><table class="data overall">{head}<tbody>{"".join(rows)}</tbody></table></div>'


def render_index(doc: dict[str, Any], scanners: list[dict[str, Any]]) -> str:
    if not scanners:
        content = '<p class="note">No scanner results yet.</p>'
    else:
        agree = (
            f"All {doc['runs_per_scanner']} runs of every scanner produced identical "
            "figures, so no ranges are shown. "
            if _all_runs_agree(scanners) else
            "Where runs disagreed, the range follows the mean as (min–max). "
        )
        content = (
            "<h2>Detection by attack class</h2>"
            '<p class="note">Per-class recall is the primary result: the share of '
            "each class's planted flaws a scanner found. Classes are grouped by where "
            "a flaw can be seen, which is why a scanner that only reads source, or "
            f"only probes a live server, never attempts whole groups. {agree}</p>"
            f"{_matrix(scanners)}{_legend()}{_class_key()}"
            "<h2>Overall recall and precision</h2>"
            '<p class="note">Side by side, never combined into one number. Rows are '
            "alphabetical; position carries no meaning. A near miss is a false "
            "positive on the right server with the wrong class: it earns no credit, "
            "and a large count is not evidence of near-competence. Unmapped findings "
            "matched no attack class and count neither for nor against a scanner. "
            f"{_ext_link(f'{DOCS_URL}/scoring.md', 'How scores work')}</p>"
            f"{_overall_table(scanners)}"
        )
    body = (
        "<header><h1>mcp-sec-bench</h1>"
        '<p class="lede">How well MCP security scanners detect deliberately planted '
        "flaws, measured against the same corpus under the same rules.</p>"
        + _meta(doc) + _caveat() + "</header>" + content + _method_footer()
    )
    return _page("mcp-sec-bench scoreboard", body)


def _outcome_means(scanner: dict[str, Any]) -> dict[str, float]:
    runs = scanner.get("runs", 0)
    counts: dict[str, int] = defaultdict(int)
    for it in scanner.get("items") or []:
        counts[it["outcome"]] += 1
    return {k: v / runs for k, v in counts.items()} if runs else {}


def render_scanner(doc: dict[str, Any], scanner: dict[str, Any]) -> str:
    name, sub = split_name(scanner)
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
        '<nav><a href="../index.html">Back to the scoreboard</a></nav>',
        f"<header><h1>{_esc(name)}</h1>",
        f'<p class="lede">{_esc(sub)}</p>' if sub else "",
        _meta(doc), _caveat(), "</header>",
        f'<dl class="facts-list">{dl}</dl>',
    ]
    if reason is not None:
        parts.append(
            "<h2>Not measured</h2><p>This scanner could not be run, so it has no "
            "scores. That is not the same as finding nothing.</p>"
            f"<p>{_esc(reason)}</p>"
        )
    else:
        m = scanner["metrics"]
        class_rows = "".join(
            f'<tr><th scope="row">{c}</th><td>{_esc(CLASS_NAMES[c])}</td>'
            f'<td class="num">{_esc(fmt_class_full(scanner, c))}</td></tr>'
            for c in CLASSES
        )
        parts.append(
            "<h2>Per-class recall</h2>"
            '<p class="note">Mean over the runs, with (min–max). n/a means the '
            "class is outside what this scanner reads; - means no data.</p>"
            '<div class="scroll"><table class="data narrow"><thead><tr>'
            '<th scope="col">Class</th><th scope="col">Name</th>'
            '<th scope="col" class="num">Recall, mean (min–max)</th></tr></thead>'
            f"<tbody>{class_rows}</tbody></table></div>"
            "<h2>Overall</h2>"
            '<div class="scroll"><table class="data narrow"><tbody>'
            f'<tr><th scope="row">Recall</th><td class="num">{_esc(fmt_stat_full(m.get("recall_overall")))}</td></tr>'
            f'<tr><th scope="row">Precision</th><td class="num">{_esc(fmt_stat_full(m.get("precision_overall")))}</td></tr>'
            f'<tr><th scope="row">False positives and near misses, per run</th>'
            f'<td class="num">{_esc(fmt_fp_near_miss(scanner))}</td></tr>'
            f'<tr><th scope="row">Unmapped findings, per run</th>'
            f'<td class="num">{fmt_unmapped(scanner)}</td></tr>'
            "</tbody></table></div>"
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
    return _page(f"{display_label(scanner)} - mcp-sec-bench", "".join(parts))


def fmt_class_full(scanner: dict[str, Any], cls: str) -> str:
    block = (scanner["metrics"].get("recall_per_class") or {}).get(cls)
    if block is None or block.get("mean") is None:
        if cls in (scanner.get("not_attempted_classes") or []):
            return NOT_ATTEMPTED
        return NO_DATA
    return fmt_stat_full(block)


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
