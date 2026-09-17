"""The scanner that flags everything: every class on every server.

Expected score: recall 1.0 -- it cannot miss anything -- and precision floored
at `declared / (declared + everything else that is neither tolerated nor n/a)`.

This is the single most important fixture. The benign controls exist to punish
exactly this behaviour, so if the overflagger's precision is not low, the
controls are not working and the benchmark cannot tell a scanner from a
rubber stamp.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...corpus import Corpus
from ...models import CLASS_STAGES, CLASSES, RawFinding
from . import FixtureAdapter


@dataclass
class OverflaggerAdapter(FixtureAdapter):
    scanner_id: str = "fixture-overflagger"
    display_name: str = "Fixture: flags everything"

    def findings(self, corpus: Corpus, stage: str) -> list[RawFinding]:
        out: list[RawFinding] = []
        for server_id in sorted(corpus.servers):
            for cls in CLASSES:
                if stage not in CLASS_STAGES[cls]:
                    continue
                out.append(self._finding(
                    server_id, cls, stage,
                    message=f"possible {cls} (flagged unconditionally)"))
        return out
