# The runner

Turns scanner output into a scoreboard, reproducibly.

```
raw scanner output
  -> RawFinding     adapters/      the scanner's own vocabulary, preserved verbatim
  -> MappedFinding  mapping.py     our taxonomy, or `unmapped`
  -> ItemOutcome    scoring.py     ground truth applied; the credit rules
  -> RunMetrics     scoring.py     one run
  -> ScannerReport  aggregate.py   N runs, mean and range
  -> scoreboard     report.py      table and JSON
```

Every type in that pipeline is defined in [models.py](models.py) and fixed by
[../docs/scoring.md](../docs/scoring.md).

## The separations that matter

**Adapters never map.** An adapter translates its scanner's output into
`RawFinding` and stops. Mapping to our taxonomy happens in one place so that
every judgment call is reviewable together rather than buried across a dozen
parsers -- and so a vendor disputing a mapping has one file to read.

**Ground truth is loaded once.** [corpus.py](corpus.py) is the only module that
reads manifests.

**Scoring never sees a scanner.** The credit rules operate on mapped findings
and ground truth, nothing else. That is what lets the engine be tested against
synthetic adapters whose results are known in advance, rather than only against
whatever a real scanner happens to emit.

## Why synthetic adapters exist

`adapters/fixtures/` holds scanners that are not real: one that finds
everything, one that flags everything, one that only does static analysis, one
whose labels are deliberately foreign to our taxonomy.

They exist because the scoring engine is the part most likely to be wrong in a
way nobody notices. A real scanner's output cannot test whether a near miss is
scored correctly, because we do not know in advance what it will report. A
fixture whose expected outcome is known exactly can.

## Reproducibility

Every published number carries `corpus_version` (a content hash of the
manifests), `scanner_version`, `adapter_version`, and `config_label`. A score is
only comparable to another score from the same `corpus_version`.

Findings carry `mapping_rationale_id`, so any number on the scoreboard traces
back to the specific judgment call behind it. That traceability is what makes
the dispute process in [../docs/governance.md](../docs/governance.md) actionable
rather than rhetorical.
