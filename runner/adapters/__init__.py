"""Adapter contract.

One adapter per scanner. An adapter's only job is to run its scanner against a
target and translate whatever comes back into RawFinding objects, preserving the
scanner's own vocabulary verbatim.

An adapter MUST NOT:
  * map a finding to our taxonomy -- that is the mapping layer's job, and it is
    kept separate so every mapping decision is reviewable in one place rather
    than buried in per-scanner parsing code
  * silently drop findings it does not understand -- an unrecognised finding
    becomes a RawFinding and is scored `unmapped`, which costs the scanner
    nothing and tells us our taxonomy has a gap
  * modify the corpus

Adapters run their scanner in a container, so a scanner's dependencies never
touch the host and a run is reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from ..models import RawFinding


@dataclass(frozen=True)
class StaticTarget:
    """What a static scanner is pointed at.

    `corpus_dir` is the whole corpus; `server_dirs` lists the individual server
    directories. Some scanners take one path, some take many, and some need a
    config file listing servers -- the adapter decides which to use, and records
    it, because whether a scanner saw one server or all of them determines
    whether it could possibly detect A3 (cross-server shadowing).
    """

    corpus_dir: Path
    server_dirs: tuple[Path, ...]
    scope: str = "corpus"  # "corpus" or "per-server"


@dataclass(frozen=True)
class RuntimeTarget:
    """A live endpoint the scanner may connect to and exercise."""

    server_id: str
    url: str
    token: str | None
    authenticated: bool
    sensitive_tools: tuple[str, ...] = ()


@dataclass
class AdapterResult:
    """What an adapter hands back: findings plus everything needed to reproduce."""

    findings: list[RawFinding]
    raw_output: str = ""
    exit_code: int | None = None
    duration_seconds: float | None = None
    error: str | None = None
    scanner_version: str = "unknown"
    extra: dict = field(default_factory=dict)


@runtime_checkable
class Adapter(Protocol):
    """The interface every scanner adapter implements."""

    #: Stable identifier, used as the scoreboard row key and in results JSON.
    scanner_id: str

    #: Human-readable vendor/product name for the scoreboard.
    display_name: str

    #: Version of the adapter itself, bumped when parsing or invocation changes.
    adapter_version: str

    #: Which stages this scanner attempts. A static-only scanner declares
    #: {"static"} and is NOT penalised for runtime classes: its runtime items
    #: are marked not_attempted and excluded from the denominator.
    stages: frozenset[str]

    #: True if the scanner cannot run at all without an account or token.
    #: Published as a scoreboard column, never a disqualifier.
    requires_signup: bool

    #: Label for this configuration. The default configuration is "default";
    #: a vendor-supplied alternative is published as an ADDITIONAL row.
    config_label: str

    def available(self) -> tuple[bool, str]:
        """Can this adapter run right now? Returns (ok, reason-if-not).

        Used to mark a scoreboard row as unavailable with a stated reason
        rather than silently omitting the scanner.
        """
        ...

    def run_static(self, target: StaticTarget) -> AdapterResult:
        """Scan source. Adapters not declaring "static" may raise."""
        ...

    def run_runtime(self, target: RuntimeTarget) -> AdapterResult:
        """Exercise a live endpoint. Adapters not declaring "runtime" may raise."""
        ...
