"""The perfect scanner: finds every declared item, exactly, and nothing else.

Expected score: recall 1.0 in every class that has an attempted item,
precision 1.0, zero false positives, zero near misses, zero unmapped.

If this fixture ever scores below 1.0, the bug is in the scorer, not the
scanner -- there is no scanner.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...corpus import Corpus
from ...models import RawFinding
from . import FixtureAdapter


@dataclass
class OracleAdapter(FixtureAdapter):
    scanner_id: str = "fixture-oracle"
    display_name: str = "Fixture: oracle"

    def findings(self, corpus: Corpus, stage: str) -> list[RawFinding]:
        # An item reachable from both stages (A2) is reported in both, which
        # also exercises the rule that duplicates collapse to one item.
        return [
            self._finding(item.server_id, item.attack_class, stage,
                          message=f"declared {item.attack_class} on {item.server_id}")
            for item in corpus.items
            if stage in item.surfaces
        ]
