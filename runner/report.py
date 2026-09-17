"""Scoreboard rendering.

Turns `list[ScannerReport]` (runner/models.py, fixed by docs/scoring.md) into
the Markdown table published at the top of the README and the site, and a
plain-text table for terminal output.

Everything here is presentation. It makes no scoring judgments -- it only
formats numbers that RunMetrics/ScannerReport already computed. The hard
rules this module exists to enforce (docs/scoring.md):

- No composite score, ranking index, or letter grade. Recall and precision
  are shown side by side, never combined.
- Rows sort alphabetically by scanner id, never by score.
- Every number that has a range shows "mean (min-max)", never a bare mean.
- A static-only scanner's runtime classes render as "n/a", never "0.00".
- A None mean (nothing attempted / no declared items) renders as "-", never
  "0.00".
- near_miss and unmapped get their own columns.
- high_variance rows are flagged with a plain-text marker. No emojis, ever.
- A scanner with no runs at all (unavailable) still gets a row.
- corpus_version and a generation timestamp are printed with every table,
  plus a footnote that recall is against a small synthetic corpus, not
  real-world MCP servers (docs/governance.md, "What this policy does not
  promise").
"""

from __future__ import annotations

from runner.models import CLASSES, ScannerReport

NOT_ATTEMPTED = "n/a"
NO_DATA = "-"
HIGH_VARIANCE_MARKER = "[high variance]"
STATIC_ONLY_MARKER = "static only"

FOOTNOTE = (
    "Recall is measured against a small synthetic corpus of deliberately "
    "vulnerable MCP servers, not against real-world MCP servers in the wild. "
    "A high score here is not a safety certification; see docs/governance.md "
    '("What this policy does not promise").'
)

def _runtime_only_classes() -> frozenset[str]:
    from runner.models import CLASS_STAGES

    return frozenset(cls for cls, stages in CLASS_STAGES.items() if stages == {"runtime"})


def _is_static_only(report: ScannerReport) -> bool:
    """True if this scanner only ever attempted the static stage."""

    return "runtime" not in report.stages_attempted


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return NO_DATA
    return f"{value:.2f}"


def _fmt_range(rng: tuple[float, float] | None) -> str:
    if rng is None:
        return ""
    lo, hi = rng
    return f"({lo:.2f}-{hi:.2f})"


def _fmt_mean_range(mean: float | None, rng: tuple[float, float] | None) -> str:
    """'0.42 (0.33-0.50)', or '-' when there is no mean to show."""

    if mean is None:
        return NO_DATA
    r = _fmt_range(rng)
    return f"{mean:.2f} {r}".rstrip() if r else f"{mean:.2f}"


def _fmt_class_cell(report: ScannerReport, cls: str) -> str:
    """One per-class recall cell.

    A class the scanner never attempted (structurally, because it is
    runtime-only and the scanner is static-only) renders as "n/a" -- never
    "0.00", which would misrepresent "did not try" as "tried and failed".
    """

    mean = report.recall_per_class_mean.get(cls)
    if mean is None:
        if _is_static_only(report) and cls in _runtime_only_classes():
            return NOT_ATTEMPTED
        return NO_DATA
    rng = report.recall_per_class_range.get(cls)
    return _fmt_mean_range(mean, rng)


def _scanner_label(report: ScannerReport) -> str:
    label = report.scanner_id
    if report.config_label and report.config_label not in ("default", ""):
        label = f"{label} ({report.config_label})"
    # Only scanners that actually ran are "static only" -- a scanner that
    # could not be run at all has no stages_attempted, but that is a
    # different fact (unavailable) and gets its own reason column, not this
    # marker.
    if report.runs > 0 and _is_static_only(report):
        label = f"{label} - {STATIC_ONLY_MARKER}"
    return label


def _high_variance_suffix(report: ScannerReport) -> str:
    return f" {HIGH_VARIANCE_MARKER}" if report.high_variance else ""


def _unavailable(report: ScannerReport) -> str | None:
    """Return the unavailable_reason if this report represents a scanner that
    could not be run at all, else None.

    The explicit `unavailable_reason` field is authoritative. A report with
    zero runs is still treated as unavailable even without one, so a scanner
    can never silently vanish from the scoreboard through a missing field.
    """

    if report.unavailable_reason:
        return report.unavailable_reason
    if report.runs > 0:
        return None
    if report.notes:
        return "; ".join(report.notes)
    return "unavailable"


def _sorted_reports(reports: list[ScannerReport]) -> list[ScannerReport]:
    # HARD RULE: alphabetical by scanner id, never by score.
    return sorted(reports, key=lambda r: r.scanner_id.lower())


def _header_block(corpus_version: str, generated_at: str) -> list[str]:
    return [
        f"Corpus version: `{corpus_version}`",
        f"Generated: {generated_at}",
    ]


# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------


def _escape_md(text: str) -> str:
    return text.replace("|", "\\|")


def render_markdown(
    reports: list[ScannerReport],
    corpus_version: str,
    generated_at: str,
    detail: bool = False,
) -> str:
    """Render the GitHub-flavoured Markdown scoreboard.

    `detail=True` adds a second table with per-class recall, one column per
    attack class (A1..A10) -- the primary number per docs/scoring.md, since
    aggregate recall hides the disjointness the project exists to show.
    """

    lines: list[str] = []
    lines.extend(_header_block(corpus_version, generated_at))
    lines.append("")

    if not reports:
        lines.append("_No scanner results yet._")
        lines.append("")
        lines.append(f"> {FOOTNOTE}")
        return "\n".join(lines) + "\n"

    sorted_reports = _sorted_reports(reports)

    headers = [
        "Scanner",
        "Requires signup",
        "Runs",
        "Recall (overall)",
        "Precision (overall)",
        "Near miss",
        "Unmapped",
        "Notes",
    ]
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

    for report in sorted_reports:
        reason = _unavailable(report)
        if reason is not None:
            lines.append(
                "| "
                + " | ".join(
                    [
                        _escape_md(_scanner_label(report)),
                        "yes" if report.requires_signup else "no",
                        "0",
                        NO_DATA,
                        NO_DATA,
                        NO_DATA,
                        NO_DATA,
                        _escape_md(f"unavailable: {reason}"),
                    ]
                )
                + " |"
            )
            continue

        notes = list(report.notes)
        if report.high_variance:
            notes.append(HIGH_VARIANCE_MARKER)
        note_cell = "; ".join(notes) if notes else ""

        row = [
            _escape_md(_scanner_label(report)),
            "yes" if report.requires_signup else "no",
            str(report.runs),
            _fmt_mean_range(report.recall_overall_mean, report.recall_overall_range),
            _fmt_mean_range(report.precision_mean, report.precision_range),
            f"{report.near_miss_mean:.2f}",
            f"{report.unmapped_mean:.2f}",
            _escape_md(note_cell),
        ]
        lines.append("| " + " | ".join(row) + " |")

    lines.append("")
    lines.append(f"> {FOOTNOTE}")

    if detail:
        lines.append("")
        lines.append(_render_detail_markdown(sorted_reports))

    return "\n".join(lines) + "\n"


def _render_detail_markdown(sorted_reports: list[ScannerReport]) -> str:
    lines: list[str] = []
    lines.append("### Per-class recall")
    lines.append("")
    lines.append(
        "Per-class recall is the primary number (docs/scoring.md): aggregate "
        "recall hides the disjointness between scanner taxonomies that "
        "motivates this project."
    )
    lines.append("")

    headers = ["Scanner"] + list(CLASSES)
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

    for report in sorted_reports:
        if _unavailable(report) is not None:
            row = [_escape_md(_scanner_label(report))] + [NO_DATA] * len(CLASSES)
            lines.append("| " + " | ".join(row) + " |")
            continue
        row = [_escape_md(_scanner_label(report))]
        for cls in CLASSES:
            row.append(_escape_md(_fmt_class_cell(report, cls)))
        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


# --------------------------------------------------------------------------
# Plain text
# --------------------------------------------------------------------------


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - len(text))


def _render_text_table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def render_row(cells: list[str]) -> str:
        return "  ".join(_pad(c, widths[i]) for i, c in enumerate(cells)).rstrip()

    lines = [render_row(headers), render_row(["-" * w for w in widths])]
    for row in rows:
        lines.append(render_row(row))
    return "\n".join(lines)


def render_text(
    reports: list[ScannerReport],
    corpus_version: str,
    generated_at: str,
    detail: bool = False,
) -> str:
    """Render a plain-text scoreboard table for terminal output."""

    lines: list[str] = []
    lines.extend(_header_block(corpus_version, generated_at))
    lines.append("")

    if not reports:
        lines.append("No scanner results yet.")
        lines.append("")
        lines.append(FOOTNOTE)
        return "\n".join(lines) + "\n"

    sorted_reports = _sorted_reports(reports)

    headers = [
        "Scanner",
        "Signup",
        "Runs",
        "Recall (overall)",
        "Precision (overall)",
        "Near miss",
        "Unmapped",
        "Notes",
    ]
    rows: list[list[str]] = []
    for report in sorted_reports:
        reason = _unavailable(report)
        if reason is not None:
            rows.append(
                [
                    _scanner_label(report),
                    "yes" if report.requires_signup else "no",
                    "0",
                    NO_DATA,
                    NO_DATA,
                    NO_DATA,
                    NO_DATA,
                    f"unavailable: {reason}",
                ]
            )
            continue

        notes = list(report.notes)
        if report.high_variance:
            notes.append(HIGH_VARIANCE_MARKER)

        rows.append(
            [
                _scanner_label(report),
                "yes" if report.requires_signup else "no",
                str(report.runs),
                _fmt_mean_range(report.recall_overall_mean, report.recall_overall_range),
                _fmt_mean_range(report.precision_mean, report.precision_range),
                f"{report.near_miss_mean:.2f}",
                f"{report.unmapped_mean:.2f}",
                "; ".join(notes),
            ]
        )

    lines.append(_render_text_table(headers, rows))
    lines.append("")
    lines.append(FOOTNOTE)

    if detail:
        lines.append("")
        lines.append(_render_detail_text(sorted_reports))

    return "\n".join(lines) + "\n"


def _render_detail_text(sorted_reports: list[ScannerReport]) -> str:
    lines = ["Per-class recall (primary number; see docs/scoring.md):", ""]
    headers = ["Scanner"] + list(CLASSES)
    rows: list[list[str]] = []
    for report in sorted_reports:
        if _unavailable(report) is not None:
            rows.append([_scanner_label(report)] + [NO_DATA] * len(CLASSES))
            continue
        row = [_scanner_label(report)]
        for cls in CLASSES:
            row.append(_fmt_class_cell(report, cls))
        rows.append(row)
    lines.append(_render_text_table(headers, rows))
    return "\n".join(lines)
