# Contributing

The full "add your scanner" guide is a Phase 4 deliverable. Until then, the
rules that already bind contributions are the ones below, because they were
fixed in Phase 0 and are not negotiated case by case.

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
authorship is disclosed on the scoreboard row. Adapters run the scanner in its
**documented default configuration**; alternative configurations are published
as additional labelled rows, never as replacements.

## Disputing a published result

Open a public issue citing the `corpus_version`, `scanner_version`,
`adapter_version`, and the specific item or `mapping_rationale_id` disputed.
Disputes are never resolved privately. See
[governance.md](docs/governance.md#contesting-a-result).

## The one thing we will not merge

A scanner. See [the no-scanner rule](docs/governance.md#the-no-scanner-rule).
Detection logic does not belong in this repository in any form, however small,
however clearly labelled as a baseline.
