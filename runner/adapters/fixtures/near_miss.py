"""A scanner that finds the right servers and names the wrong class, every time.

Expected score: recall 0.0 -- partial credit is none -- one false positive per
distinct wrong `(server, class)` pair, the same number of near misses logged,
and a false negative on every declared item it walked past.

This is worked example 1 generalised over the whole corpus: "right flaw, wrong
class" earns nothing, is visible in its own column, and does not move the
headline numbers in either direction by being approximately right.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...corpus import Corpus
from ...models import CLASS_STAGES, CLASSES, RawFinding
from . import FixtureAdapter


def wrong_class(corpus: Corpus, server_id: str, declared: str, stage: str) -> str | None:
    """A class that is wrong for this server, deterministically chosen.

    Skips anything declared on the server (that would be a true positive),
    anything tolerated (that would be neither), and anything n/a (likewise) --
    so what comes back is unambiguously a false positive, which is what a near
    miss is scored as.
    """
    start = CLASSES.index(declared)
    order = CLASSES[start + 1:] + CLASSES[:start + 1]
    server_declared = corpus.declared_classes(server_id)
    for cls in order:
        if cls in server_declared:
            continue
        if corpus.is_tolerated(server_id, cls) or corpus.is_not_applicable(server_id, cls):
            continue
        if stage not in CLASS_STAGES[cls]:
            continue
        return cls
    return None


@dataclass
class NearMissAdapter(FixtureAdapter):
    scanner_id: str = "fixture-near-miss"
    display_name: str = "Fixture: systematically wrong class"

    def findings(self, corpus: Corpus, stage: str) -> list[RawFinding]:
        out: list[RawFinding] = []
        for item in corpus.items:
            if stage not in item.surfaces:
                continue
            cls = wrong_class(corpus, item.server_id, item.attack_class, stage)
            if cls is None:
                continue
            out.append(self._finding(
                item.server_id, cls, stage,
                message=(f"something is wrong on {item.server_id} "
                         f"(it is {item.attack_class}; reported as {cls})")))
        return out
