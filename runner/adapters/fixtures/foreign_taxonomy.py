"""A scanner speaking a vocabulary deliberately outside our taxonomy.

Expected score: every finding `unmapped`. No true positives, no false
positives, precision `None` (the denominator is empty, and an empty denominator
is not a zero), recall unaffected, and a high unmapped count.

docs/scoring.md: penalising a scanner for finding something real that we did
not think to define would measure our taxonomy, not their tool. A high unmapped
count is a signal to review the taxonomy, and is reported as such.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...corpus import Corpus
from ...models import RawFinding
from . import FixtureAdapter

#: Labels chosen to be plausible scanner output and to have no home in the v1
#: taxonomy -- deliberately not near-synonyms of our classes, because a label
#: that *should* map is a mapping-layer test, not a scorer test.
FOREIGN_LABELS: tuple[str, ...] = (
    "SUPPLY-CHAIN/unpinned-transitive-dep",
    "LICENSE/ambiguous-redistribution",
    "TELEMETRY/undisclosed-collection",
    "CRYPTO/deprecated-hash-in-non-security-path",
)


@dataclass
class ForeignTaxonomyAdapter(FixtureAdapter):
    scanner_id: str = "fixture-foreign"
    display_name: str = "Fixture: foreign taxonomy"

    def findings(self, corpus: Corpus, stage: str) -> list[RawFinding]:
        if stage != "static":
            return []
        out: list[RawFinding] = []
        for i, server_id in enumerate(sorted(corpus.servers)):
            label = FOREIGN_LABELS[i % len(FOREIGN_LABELS)]
            out.append(self._finding(
                server_id, label, "static",
                message="real enough, but not a class this benchmark defines"))
        return out
