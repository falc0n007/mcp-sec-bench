"""Ground truth, loaded from the corpus manifests.

This module is the only place that reads manifests. Everything downstream
scores against what it returns, so a bug here silently corrupts every number
the benchmark publishes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from .models import CLASS_STAGES, CorpusItem

ROOT = Path(__file__).resolve().parent.parent
CORPUS_DIR = ROOT / "corpus"


@dataclass
class ServerTruth:
    server_id: str
    kind: str
    transport: str
    port: int
    authenticated: bool
    path: Path
    declared: list[CorpusItem] = field(default_factory=list)
    tolerated: set[str] = field(default_factory=set)
    not_applicable: set[str] = field(default_factory=set)
    sensitive_tools: list[str] = field(default_factory=list)

    @property
    def is_benign(self) -> bool:
        return self.kind == "benign"


@dataclass
class Corpus:
    version: str
    servers: dict[str, ServerTruth]

    @property
    def items(self) -> list[CorpusItem]:
        """Every declared (server, class) pair. The scoring denominator."""
        out: list[CorpusItem] = []
        for s in self.servers.values():
            out.extend(s.declared)
        return sorted(out, key=lambda i: (i.server_id, i.attack_class))

    def items_for_stage(self, stage: str) -> list[CorpusItem]:
        """Items a scanner working only in `stage` could possibly find.

        A class reachable from both stages (A2) appears in both.
        """
        return [i for i in self.items if stage in i.surfaces]

    def items_for_stages(self, stages: set[str]) -> list[CorpusItem]:
        return [i for i in self.items if i.surfaces & stages]

    def is_tolerated(self, server_id: str, attack_class: str) -> bool:
        s = self.servers.get(server_id)
        return bool(s and attack_class in s.tolerated)

    def is_not_applicable(self, server_id: str, attack_class: str) -> bool:
        s = self.servers.get(server_id)
        return bool(s and attack_class in s.not_applicable)

    def declares_anything(self, server_id: str) -> bool:
        s = self.servers.get(server_id)
        return bool(s and s.declared)

    def declared_classes(self, server_id: str) -> set[str]:
        s = self.servers.get(server_id)
        return {i.attack_class for i in s.declared} if s else set()


def _version(dirs: list[Path]) -> str:
    """Content hash of every manifest, so a score names the exact ground truth.

    A score is only comparable to another score from the same corpus_version;
    deriving it from content rather than a hand-maintained string means it
    cannot drift out of sync with what was actually scored.
    """
    h = hashlib.sha256()
    for d in sorted(dirs):
        h.update(d.name.encode())
        h.update((d / "manifest.json").read_bytes())
    return "v1-" + h.hexdigest()[:12]


def load_corpus(corpus_dir: Path | None = None) -> Corpus:
    base = corpus_dir or CORPUS_DIR
    dirs = sorted(d for d in base.iterdir()
                  if d.is_dir() and not d.name.startswith("_")
                  and (d / "manifest.json").exists())
    if not dirs:
        raise RuntimeError(f"no corpus servers found under {base}")

    servers: dict[str, ServerTruth] = {}
    for d in dirs:
        m = json.loads((d / "manifest.json").read_text())
        truth = ServerTruth(
            server_id=m["server_id"],
            kind=m["kind"],
            transport=m["transport"],
            port=m["port"],
            authenticated=m["authenticated"],
            path=d,
            tolerated={t["class"] for t in m.get("tolerated", [])},
            not_applicable=set(m.get("not_applicable", [])),
            sensitive_tools=list(m.get("sensitive_tools", [])),
        )
        for entry in m.get("declared", []):
            cls = entry["class"]
            surfaces = frozenset(entry["surface"])
            if not surfaces <= CLASS_STAGES[cls]:
                raise RuntimeError(
                    f"{m['server_id']}: {cls} declared on {sorted(surfaces)}, "
                    f"but the taxonomy allows {sorted(CLASS_STAGES[cls])}")
            truth.declared.append(CorpusItem(
                server_id=m["server_id"],
                attack_class=cls,
                surfaces=surfaces,
                variant=entry.get("variant"),
            ))
        servers[truth.server_id] = truth

    return Corpus(version=_version(dirs), servers=servers)
