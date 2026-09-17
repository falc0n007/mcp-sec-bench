"""Synthetic scanners whose correct score is known before they run.

See `runner/README.md`, "Why synthetic adapters exist": the scoring engine is
the part most likely to be wrong in a way nobody notices, and a real scanner's
output cannot test whether a near miss is scored correctly because we do not
know in advance what it will report. These fixtures do, exactly.

They need no container and no network. They read ground truth and emit
`RawFinding`s directly, which is the one thing a real adapter must never do --
that is the point: a fixture is an instrument for testing the scorer, not a
scanner.

`identity_map` below is a *test* convenience, NOT the mapping layer. The real
mapping layer lives in `runner/mapping.py`, is keyed on documented per-label
rationales, and is frozen before a scoring run. `identity_map` exists only so a
fixture that already speaks our taxonomy can be fed to `score_run` without
dragging that layer into a unit test of the credit rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from ...corpus import Corpus, load_corpus
from ...models import CLASSES, MappedFinding, RawFinding
from .. import AdapterResult, RuntimeTarget, StaticTarget


def identity_map(findings: Iterable[RawFinding]) -> list[MappedFinding]:
    """Treat a raw label that is already one of our class ids as that class.

    Anything else is `unmapped`, which is what the taxonomy gap looks like from
    the scorer's side. A finding with no server is likewise unmapped: a class
    without a server is not an item.
    """
    out: list[MappedFinding] = []
    for f in findings:
        label = f.raw_label.strip().upper()
        if label in CLASSES and f.server_id:
            out.append(MappedFinding(
                finding=f,
                mapped_class=label,
                mapped_server=f.server_id,
                mapping_rationale_id="fixture-identity",
            ))
        else:
            out.append(MappedFinding(
                finding=f, mapped_class=None, mapped_server=None,
                mapping_rationale_id=None,
            ))
    return out


@dataclass
class FixtureAdapter:
    """Base for the synthetic adapters. Implements the `Adapter` protocol."""

    scanner_id: str = "fixture"
    display_name: str = "Fixture"
    adapter_version: str = "1.0"
    stages: frozenset[str] = frozenset({"static", "runtime"})
    requires_signup: bool = False
    config_label: str = "default"
    corpus: Corpus | None = None
    notes: list[str] = field(default_factory=list)

    # -- protocol ---------------------------------------------------------
    def available(self) -> tuple[bool, str]:
        return True, ""

    def run_static(self, target: StaticTarget) -> AdapterResult:
        if "static" not in self.stages:
            raise NotImplementedError(f"{self.scanner_id} does not attempt static")
        return AdapterResult(
            findings=self.findings(self._corpus(target.corpus_dir), "static"),
            scanner_version="fixture",
            exit_code=0,
        )

    def run_runtime(self, target: RuntimeTarget) -> AdapterResult:
        if "runtime" not in self.stages:
            raise NotImplementedError(f"{self.scanner_id} does not attempt runtime")
        findings = [f for f in self.findings(self._corpus(None), "runtime")
                    if f.server_id == target.server_id]
        return AdapterResult(findings=findings, scanner_version="fixture", exit_code=0)

    # -- fixture plumbing -------------------------------------------------
    def _corpus(self, corpus_dir: Path | None) -> Corpus:
        if self.corpus is not None:
            return self.corpus
        return load_corpus(corpus_dir)

    def findings(self, corpus: Corpus, stage: str) -> list[RawFinding]:
        raise NotImplementedError

    def all_findings(self, corpus: Corpus) -> list[RawFinding]:
        """Every finding this fixture produces across the stages it attempts.

        This is what a full run of the fixture hands the scorer.
        """
        out: list[RawFinding] = []
        for stage in ("static", "runtime"):
            if stage in self.stages:
                out.extend(self.findings(corpus, stage))
        return out

    def _finding(self, server_id: str, label: str, stage: str,
                 message: str = "") -> RawFinding:
        return RawFinding(
            scanner_id=self.scanner_id,
            raw_label=label,
            server_id=server_id,
            message=message,
            severity="high",
            raw={"stage": stage, "fixture": self.scanner_id},
        )
