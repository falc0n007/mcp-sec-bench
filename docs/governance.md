# Neutrality and governance policy

Status: **in force from 2026-09-17**, written before any scanner was run and
before any result existed.

That ordering is the whole point of this document. A neutrality policy written
after the numbers are in is a defence of the numbers. This one was committed
while the scoreboard was empty, and its constraints were accepted without
knowing who they would inconvenience.

## The no-scanner rule

**This project will never ship its own MCP security scanner.** Not as a
reference implementation, not as a baseline, not as a "just to show what's
possible" demo, not under a different name by the same maintainers while this
benchmark is active.

The moment the project competes in the category it measures, every result it
publishes becomes marketing, and the benchmark's only real asset — being
disinterested — is gone. No technical benefit outweighs that.

This rule is binding on maintainers, is restated in the README, and cannot be
amended by the ordinary amendment process below. Changing it requires archiving
this benchmark and starting a differently-named project, so that no reader ever
finds a scoreboard whose publisher quietly became a competitor.

**If the itch to build a detector persists:** ship it as a separate repository,
under a different name, with no shared maintainers-as-authors claim, after v1 is
stable — and it does not appear on this scoreboard.

## Which scanners are included

Inclusion is by criteria, not invitation. A scanner is eligible when all of the
following hold:

1. **Reproducibly runnable** from a clean environment without a sales call, a
   demo, or a bespoke build.
2. **Publicly obtainable** — open source, source-available, or a free tier that
   anyone can sign up for. An account requirement is allowed; it is disclosed in
   a `requires signup` column rather than being a disqualifier.
3. **Containerizable** so the run is isolated and reproducible.
4. **Produces parseable output** — machine-readable, or stable enough text that
   an adapter can parse it deterministically.
5. **Licensed compatibly** with being run and having its output published.

Out of scope for v1, by category rather than by judgment of quality: commercial
scanners behind a sales process, and runtime gateway or proxy products, which
are a different category needing a different harness. Both exclusions are
recorded in the README so their absence is not read as a verdict.

**Anyone may submit an adapter**, including a vendor for their own tool. Vendor
authorship of an adapter is disclosed on the scoreboard row.

## What vendors can and cannot influence

Vendors **may**:

- Submit or correct an adapter for their own tool.
- Submit an alternative configuration, published as an additional labelled row
  alongside the default row, never replacing it.
- Contest a result through the process below.
- Point out a genuine misconfiguration, a mapping error, or a corpus bug.

Vendors **may not**:

- Influence the corpus, the taxonomy, or the mapping decisions except through
  the public dispute process, where the reasoning is visible to everyone.
- Obtain results before the disclosure window, ahead of other vendors.
- Require changes as a condition of participation, or condition permission-to-
  benchmark on a favourable outcome. We do not seek permission to publish
  measurements of publicly available tools.

## Money

**This project accepts no funding, sponsorship, advertising, consulting
arrangement, or in-kind support from any vendor whose tool is benchmarked, or
from any vendor eligible to be benchmarked.**

No paid tier, no hosted service, no sponsored placement on the scoreboard. If
funding is ever accepted from any source, the source and amount are disclosed
prominently in the README before the next results are published.

## Conflicts of interest

Maintainers disclose, in the repository, any employment, contracting, equity,
advisory, or funding relationship with any benchmarked vendor or eligible
vendor.

A maintainer with a disclosed tie to a scanner **recuses** from: mapping
decisions for that tool, its adapter review, and its dispute resolution. The
recusal is noted in the pull request.

Current disclosures: none. This section is updated before a tie exists, not
after.

## Contesting a result

Any maintainer of a benchmarked scanner, or any member of the public, may
contest a published result.

1. **Open a public issue** citing the `corpus_version`, `scanner_version`,
   `adapter_version`, and the specific item or `mapping_rationale_id` disputed.
   Every published number is traceable to these, by design.
2. **We re-run** the affected configuration and post the raw output.
3. **Misconfiguration or adapter bug** — we fix, re-run, and publish a correction
   entry. The original result stays visible with a pointer to the correction.
4. **Mapping dispute** — the rationale is reviewed in public. If we are
   persuaded, the mapping changes, the corpus version bumps, and every affected
   scanner is re-disclosed. If we are not, **both positions are published
   side by side on the scoreboard row.** A reader is entitled to see the
   disagreement rather than only our resolution of it.
5. **Target response**: acknowledgement within 7 days, resolution or a published
   statement of disagreement within 30.

Disputes are never resolved privately. A correction that only the disputing
vendor knows about is not a correction.

## Disclosure before publication

No result is published before its maintainers have seen it.

- Every scanner's maintainers receive their **full results, the methodology, and
  the exact mapping decisions applied to their tool**, with a **14-day window**
  to respond, correct, or identify a misconfiguration.
- Responses are **published alongside the scores**, unedited except for length,
  with a link to the full text. A maintainer who declines to respond is recorded
  as "no response", with no characterisation of why.
- The window is elapsed time and is not compressed for launch timing.

**Re-disclosure** is triggered when a previously published scanner's score
**materially changes**, defined concretely as any of: overall recall moving by
10 percentage points or more, any per-class result flipping between detected and
missed, or a change in mapping that affects that tool. Materially-changed
results get a fresh 14-day window before republication.

## Publishing and corrections

- Published results are **never silently edited.** Corrections are new, dated,
  versioned entries with a changelog; superseded numbers remain reachable.
- Every scoreboard states the `corpus_version` and the date it was produced.
- Raw scanner output for every published run is committed, so anyone can check
  our arithmetic and our mappings without rerunning anything.

## Corpus integrity

- A **private held-back set** is maintained and never published. Public scores
  are periodically checked against it; a tool that performs markedly better on
  the public corpus than the held-back set is noted on the scoreboard, because
  that gap is the signature of tuning to the benchmark.
- The public corpus **rotates** periodically. Rotation schedules are announced
  in advance and applied to every scanner at once.
- Corpus versions are tagged. A score is only ever comparable to another score
  from the same `corpus_version`, and the scoreboard never places numbers from
  different corpus versions in the same column.

## Amending this policy

Ordinary amendments — everything except the no-scanner rule — follow this path:

1. A pull request stating the change and the reasoning.
2. A minimum **14-day public comment period** before merge.
3. On merge, an entry in [decisions.md](decisions.md) with the date and rationale.
4. **No retroactive application.** Published results keep the rules they were
   produced under. If an amendment would change a published number, the affected
   scanners are re-disclosed before republication.

### Amending the taxonomy

Taxonomy changes follow the same path plus: a corpus version bump, and
re-disclosure to every scanner whose results the change affects. A class
definition is never narrowed or widened in a way that changes an existing
scanner's score without that scanner's maintainers seeing it first.

## What this policy does not promise

Stated plainly, so nobody has to infer it:

- **Not completeness.** A small corpus of deliberately planted flaws is not the
  distribution of real-world MCP servers. Recall here is recall against this
  corpus, and the README says so next to every number.
- **Not a safety certification.** A high score is not an endorsement, and a low
  score is not a claim that a tool is bad at things this benchmark does not
  measure.
- **Not neutrality about the category itself.** We think MCP security tooling
  should be measured. That is a position. It is not a position about which tool
  should win.
