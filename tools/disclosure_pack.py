"""Assemble the per-scanner disclosure pack for a maintainer.

docs/governance.md commits to every scanner's maintainers receiving their full
results, the methodology, the exact mapping decisions applied to their tool,
and how it was invoked, before anyone else sees a number. This tool builds that
bundle from a results.json so it is produced the same way for every scanner
rather than assembled by hand.

A pack directory contains:

    results.json   the results document restricted to this one scanner
                   (still valid against schema/results.schema.json)
    mapping.json   the scanner's file from mapping/, rationale included
    adapter/       the adapter source, the shared container helper, and the
                   Dockerfile that defines the scanner image
    PACK.json      corpus_version, generation timestamp, scanner version
    README.md      what each file is, and which known weaknesses apply

The default output is results/local/disclosure/<scanner>/, which is gitignored:
numbers must not be committed before the disclosure window has run.

Usage:
    python tools/disclosure_pack.py --scanner mcp-guard
    python tools/disclosure_pack.py --all
    python tools/disclosure_pack.py --all --results path/to/results.json --out DIR
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runner.results import load_results, validate_results, write_results  # noqa: E402

DEFAULT_RESULTS = ROOT / "results" / "local" / "results.json"
DEFAULT_OUT = ROOT / "results" / "local" / "disclosure"
MAPPING_DIR = ROOT / "mapping"
ADAPTER_DIR = ROOT / "runner" / "adapters"
DOCKERFILE_DIR = ADAPTER_DIR / "dockerfiles"

# scanner_id -> adapter module. Not derivable from the id (sentinel-scan-cli
# lives in sentinel_scan.py), so it is stated, and a test checks it is complete.
ADAPTER_FILES = {
    "cisco-mcp-scanner": "cisco_mcp_scanner.py",
    "mcp-guard": "mcp_guard.py",
    "ramparts": "ramparts.py",
    "sentinel-scan-cli": "sentinel_scan.py",
    "snyk-agent-scan": "snyk_agent_scan.py",
}
# Every adapter shells out through this, so it is part of "how it was invoked".
SHARED_ADAPTER_FILES = ("container.py",)

# The weaknesses docs/disclosure.md says to state proactively. Each entry is
# (text, scanner ids it applies to); None means every scanner.
WEAKNESSES: list[tuple[str, frozenset[str] | None]] = [
    (
        "The corpus is small and synthetic. Recall here is recall against "
        "planted flaws, not against real-world MCP servers.",
        None,
    ),
    (
        "A1 versus A4 is knowingly mis-scored in one case. See the open "
        "question in docs/decisions.md.",
        None,
    ),
    (
        "The near-miss counter is inflatable and is not evidence of "
        "near-competence.",
        None,
    ),
    (
        "Credential-free configuration only. This scanner has analysis that "
        "requires keys we did not supply, which bounds what its row can show.",
        frozenset({"cisco-mcp-scanner", "snyk-agent-scan"}),
    ),
    (
        "A zero for this scanner is a scan-surface limit, not a rule gap: "
        "0.8.8 never reads source or tool return values.",
        frozenset({"ramparts"}),
    ),
    (
        "A zero for this scanner is a rule-coverage gap on text it "
        "demonstrably read, not a scan-surface limit.",
        frozenset({"cisco-mcp-scanner"}),
    ),
]


class PackError(Exception):
    """A pack could not be built; the message says why."""


def scanner_entry(doc: dict[str, Any], scanner_id: str) -> dict[str, Any]:
    """Return the scanner's entry from the results doc, or raise PackError.

    The error lists the ids that are present so a typo is obvious.
    """
    for entry in doc.get("scanners", []):
        if entry.get("scanner_id") == scanner_id:
            return entry
    present = ", ".join(sorted(e.get("scanner_id", "?") for e in doc.get("scanners", [])))
    raise PackError(
        f"unknown scanner id {scanner_id!r}; results contain: {present or '(none)'}"
    )


def slice_results(doc: dict[str, Any], scanner_id: str) -> dict[str, Any]:
    """The results document restricted to one scanner.

    Document-level fields (corpus_version, generated_at, runs_per_scanner,
    schema_version) are kept so the slice validates and stands alone.
    """
    entry = scanner_entry(doc, scanner_id)
    return {**{k: v for k, v in doc.items() if k != "scanners"}, "scanners": [entry]}


def _require(path: Path, what: str) -> Path:
    if not path.is_file():
        raise PackError(f"missing {what}: {path}")
    return path


def applicable_weaknesses(scanner_id: str) -> list[str]:
    return [text for text, ids in WEAKNESSES if ids is None or scanner_id in ids]


def render_readme(entry: dict[str, Any], doc: dict[str, Any]) -> str:
    """The maintainer-facing README. States facts; makes no claims about the tool."""
    sid = entry["scanner_id"]
    weaknesses = "\n".join(f"- {w}" for w in applicable_weaknesses(sid))
    notes = entry.get("notes") or []
    notes_block = "\n".join(f"- {n}" for n in notes) or "- none"
    unavailable = entry.get("unavailable_reason")
    unavailable_block = (
        f"\n## Why there is no result\n\n{unavailable}\n" if unavailable else ""
    )
    return f"""# Disclosure pack: {entry.get("display_name", sid)}

Scanner id `{sid}`, version `{entry.get("scanner_version", "?")}`, adapter
version `{entry.get("adapter_version", "?")}`, configuration
`{entry.get("config_label", "?")}`.
Corpus version `{doc["corpus_version"]}`, results generated
`{doc["generated_at"]}`, {entry.get("runs", 0)} runs.

This is your private pre-publication copy. You have 14 days to check it and
respond; your response is published alongside the scores.
{unavailable_block}
## Files

| File | What it is |
| --- | --- |
| `results.json` | Your slice of the results document: scoreboard metrics, every item outcome, and every finding with its `mapping_rationale_id`. Validates against `schema/results.schema.json` in the repository. |
| `mapping.json` | The mapping applied to your tool: how each of your finding labels was translated to a benchmark class, with the rationale for every label, including the ones left unmapped. The most disputable part of the result. |
| `adapter/{ADAPTER_FILES[sid]}` | The code that invoked your tool and parsed its output. |
| `adapter/container.py` | The shared helper that runs scanner containers. |
| `adapter/{sid}.Dockerfile` | The container definition, with the pinned version. |
| `PACK.json` | Corpus version, generation timestamp, and scanner version, machine readable. |

Methodology (`docs/taxonomy.md`, `docs/scoring.md`) is in the repository
rather than copied here, so it cannot drift from this pack.

## Run notes

{notes_block}

## Known weaknesses that apply to your row

{weaknesses}

## How to dispute

Reply with the finding, item, or mapping entry you believe is wrong and what it
should be. A confirmed error is corrected and republished, with the original
left visible and a pointer to the correction.
"""


def build_pack(doc: dict[str, Any], scanner_id: str, out_root: Path) -> Path:
    """Write the pack for one scanner under out_root/<scanner_id>/; return its path.

    Everything that can be missing is checked before anything is written, so a
    failure never leaves a half-built pack behind.
    """
    entry = scanner_entry(doc, scanner_id)
    if scanner_id not in ADAPTER_FILES:
        raise PackError(f"no adapter registered for {scanner_id!r} in tools/disclosure_pack.py")

    sources = {
        "mapping.json": _require(MAPPING_DIR / f"{scanner_id}.json", "mapping file"),
        f"adapter/{ADAPTER_FILES[scanner_id]}": _require(
            ADAPTER_DIR / ADAPTER_FILES[scanner_id], "adapter source"
        ),
        f"adapter/{scanner_id}.Dockerfile": _require(
            DOCKERFILE_DIR / f"{scanner_id}.Dockerfile", "Dockerfile"
        ),
    }
    for name in SHARED_ADAPTER_FILES:
        sources[f"adapter/{name}"] = _require(ADAPTER_DIR / name, "shared adapter file")

    dest = out_root / scanner_id
    if dest.exists():
        shutil.rmtree(dest)  # regenerate cleanly; a stale file would mislead
    (dest / "adapter").mkdir(parents=True)

    for rel, src in sources.items():
        shutil.copyfile(src, dest / rel)

    write_results(slice_results(doc, scanner_id), dest / "results.json")
    pack_meta = {
        "scanner_id": scanner_id,
        "scanner_version": entry.get("scanner_version"),
        "adapter_version": entry.get("adapter_version"),
        "config_label": entry.get("config_label"),
        "corpus_version": doc["corpus_version"],
        "generated_at": doc["generated_at"],
    }
    (dest / "PACK.json").write_text(json.dumps(pack_meta, indent=2) + "\n")
    (dest / "README.md").write_text(render_readme(entry, doc))
    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--scanner", help="scanner id to build a pack for")
    target.add_argument("--all", action="store_true", help="every scanner in the results")
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    try:
        if not args.results.is_file():
            raise PackError(f"results file not found: {args.results} (run `make scoreboard`)")
        doc = load_results(args.results)
        errors = validate_results(doc)
        if errors:
            raise PackError("results.json fails schema validation:\n  " + "\n  ".join(errors))
        ids = (
            [e["scanner_id"] for e in doc["scanners"]] if args.all else [args.scanner]
        )
        for sid in ids:
            print(f"wrote {build_pack(doc, sid, args.out)}")
    except PackError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
