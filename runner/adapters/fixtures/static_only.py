"""A static-only scanner. Attempts stage 1, ignores stage 2, finds its items.

Expected score: full recall on every class reachable statically; every
runtime-only item marked `not_attempted`, excluded from the denominator, and
NOT counted as a false negative. That is worked example 5 in docs/scoring.md.

Scoring a static tool as having 0% runtime recall would be a category error
dressed up as a measurement, and this fixture is what proves we do not.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...corpus import Corpus
from ...models import RawFinding
from . import FixtureAdapter


@dataclass
class StaticOnlyAdapter(FixtureAdapter):
    scanner_id: str = "fixture-static-only"
    display_name: str = "Fixture: static only"
    stages: frozenset[str] = frozenset({"static"})

    def findings(self, corpus: Corpus, stage: str) -> list[RawFinding]:
        if stage != "static":
            return []
        # Includes A2 when its static route is declared: worked example 6,
        # "rug-pull found statically", credited with stage_credited=static.
        return [
            self._finding(item.server_id, item.attack_class, "static",
                          message=f"{item.attack_class} visible in source")
            for item in corpus.items
            if "static" in item.surfaces
        ]
