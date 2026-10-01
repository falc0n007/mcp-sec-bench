# Contributing

The rules that bind contributions were fixed in Phase 0 and are not negotiated
case by case. To add a scanner, start with
[docs/adding-a-scanner.md](docs/adding-a-scanner.md).

## Read first

- [Ethics and scope](docs/ethics.md) — what the corpus may and may not contain.
- [Neutrality and governance](docs/governance.md) — who gets benchmarked and how
  results are disputed.
- [Attack class taxonomy](docs/taxonomy.md) and [scoring rules](docs/scoring.md)
  — the definitions any corpus or adapter contribution has to satisfy.

## Hard limits on corpus contributions

A contribution is refused, without exception, if it targets a real or deployed
server, includes a working exploit for unpatched real software, contains live
command-and-control, performs credential harvesting, carries any real credential
(live, expired, or revoked), or includes malware, destructive payloads, or
persistence mechanisms.

**The minimal payload principle governs everything else:** a payload only has to
be *detectable*, never *effective*. A change that makes a payload more effective
without making it more detectable will be rejected.

## Corpus servers

- One flaw per server. This keeps attribution clean when a scanner half-fires.
- Every server ships a ground-truth manifest and a README explaining its flaw.
- Benign controls are as important as vulnerable servers. A realistic pattern
  that naively looks suspicious is a contribution, not a distraction — it is
  what makes precision mean anything.

## Adapters

Anyone may submit an adapter, including a vendor for their own tool. Vendor
authorship is disclosed on the scoreboard row. A submission is four things: an
adapter implementing the contract in `runner/adapters/__init__.py`, a Dockerfile
pinned to an exact version or commit in `runner/adapters/dockerfiles/`, a
mapping file in `mapping/` in which every label (including the ones left
unmapped) carries a written rationale, and tests modelled on
`tests/test_adapter_*.py`.

- Adapters never map findings to our taxonomy, never drop output they do not
  understand, and never write to the corpus.
- Adapters run the scanner in its **documented default configuration**.
  Alternative configurations are published as additional labelled rows, never
  as replacements.
- A scanner that needs an account is benchmarked, and the requirement is
  published as a column.
- Results are published without pre-publication review by maintainers. If you
  disagree with one, dispute it after publication (below); your response is
  published alongside the score.

The step-by-step guide, with the exact files and commands, is
[docs/adding-a-scanner.md](docs/adding-a-scanner.md).

## Disputing a published result

Open a public issue citing the `corpus_version`, `scanner_version`,
`adapter_version`, and the specific item or `mapping_rationale_id` disputed.
Disputes are never resolved privately. See
[governance.md](docs/governance.md#contesting-a-result).

## The one thing we will not merge

A scanner. See [the no-scanner rule](docs/governance.md#the-no-scanner-rule).
Detection logic does not belong in this repository in any form, however small,
however clearly labelled as a baseline.
