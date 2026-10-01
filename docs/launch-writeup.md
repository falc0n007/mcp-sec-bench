# Launch write-up

**Status: DRAFT. Not to be published until the publishing run has produced the
scoreboard and every `[RESULT: ...]` placeholder below has been filled from it.**

This repository is public. This file therefore contains no scanner scores, no
recall or precision figures, and no per-scanner outcomes. Everything that would
be one is a bracketed placeholder, for example `[RESULT: ...]`. Fill them from
the published scoreboard only.
Before publishing, search this file for `[` and confirm none remain.

---

# Measuring MCP security scanners: method first, results second

## The problem

Teams are being told to scan MCP servers before they install them, and there are
now several tools that say they do this. There is no neutral measurement of how
well any of them works.

The evidence that exists is thin and mostly self-interested. The one public
comparison we found comes from a repository whose own tool scores 100%. An
independent run against a vulnerable-server corpus found poor detection and
found that the scanners' vocabularies did not overlap at all, which would mean
they are complementary rather than redundant. We have not re-established those
figures and ask you not to rely on them; re-establishing them under a
reproducible method is the point of this project.

## What we built

`mcp-sec-bench` is a corpus, a runner, and a set of written rules. It is not a
scanner and will never become one. The project's only asset is being
disinterested, so shipping a detector, even as a baseline, is ruled out
permanently in [governance.md](governance.md#the-no-scanner-rule).

- **A corpus of 11 deliberately vulnerable MCP servers and 4 benign controls.**
  One flaw per server so attribution stays clean. The controls are realistic
  patterns that naively look suspicious, because without them precision means
  nothing.
- **Ten attack classes**, defined in [taxonomy.md](taxonomy.md) so that "did the
  scanner catch it?" has one answer: tool-description injection, rug-pull,
  cross-server shadowing, response injection, argument exfiltration, authless
  endpoint, hardcoded secrets, unrestricted file read, unrestricted environment
  access, and command execution or allowlist bypass.
- **Two stages.** A static stage (source tree and packaging metadata) and a
  live-endpoint stage the scanner may exercise. Several classes are only
  reachable at runtime; those are where we expect the comparison to say
  something existing ones do not.
- **N = 5 runs** per scanner, reported as mean and range. Several scanners use
  LLM-as-judge analyzers and vary between runs, so one number would be a
  fiction.
- **A runner** that executes each scanner in a container from a pinned
  Dockerfile, with the corpus mounted read-only, and commits the raw output for
  every published run.

Everything that produces a number was written down before any scanner was run:
the [taxonomy](taxonomy.md), the [scoring rules](scoring.md), the
[governance policy](governance.md), and the procedure for
[mapping](mapping-rationale.md) each scanner's labels onto our classes.

## The scoring rules that matter

Full rules are in [scoring.md](scoring.md). The ones that change how a result
should be read:

- **No partial credit.** A finding counts only if it names the right server and
  the right class. A right-server, wrong-class finding is a false positive on
  the class it reported and is logged in a separate near-miss counter.
- **No composite score.** Recall per class and precision are reported side by
  side. Any single number would need us to weight attack classes against each
  other, which is an editorial claim about which attacks matter most. Rows sort
  alphabetically, never by score.
- **Static-only tools are not penalised for runtime classes.** Their runtime
  items are marked not attempted and left out of the denominator, and the row is
  labelled "static only". The reverse holds for runtime-only tools.
- **Unmapped findings count as neither a true positive nor a false positive.**
  Scanners report real things our ten classes do not define, and punishing that
  would measure our taxonomy rather than their tool. It costs the scanner
  nothing in precision, but it is not free: an item the scanner may truly have
  found stays a false negative.
- **Defaults only.** Each scanner runs in its documented default configuration.
  A vendor's alternative configuration is published as an additional labelled
  row, never in place of the default.
- **Access friction is a column.** A scanner that needs an account is measured
  and the requirement is published. A tool we could not run still gets a row
  carrying the reason, because omitting it would quietly turn "we could not run
  this" into "we did not consider this".

## Which kind of zero

A zero recall is not one claim. Before any zero is described, we say which kind
it is:

1. **The scanner never reads the surface where the flaw lives.** It was working
   as designed and this benchmark measured something outside its scan surface.
2. **The scanner read the text and has no rule for it.** It saw the flaw and did
   not recognise it. This is a coverage gap.
3. **Our setup broke the scanner.** This is our bug, not a result, and the first
   thing we check. One adapter in this repository exists in its current shape
   because a default install silently ran with detection disabled and reported
   zero findings that looked exactly like a clean scan.

Collapsing these into one number is unfair to every tool involved. Where a
scanner scored zero on a class, the write-up states which kind, with the
evidence.

## Results were published without pre-publication review

[governance.md](governance.md#publication-and-right-of-reply) originally
committed that every scanner's maintainers would see their full results, the
methodology and the mapping decisions applied to their tool, with 14 days to
respond, before anyone else saw a number. **We did not do that.** On 2026-09-30
the project owner decided not to run the round, and the results were published
without any maintainer seeing them first. We recorded the change in
[decisions.md](decisions.md) rather than leaving the old text standing, and we
say plainly that it was an owner decision made without the public comment period
the policy prescribes for its own amendment.

What this means for a reader: a vendor saw its numbers at the same moment you
did, and an error in our setup would be caught after publication, not before.
Any maintainer or member of the public can dispute a result (see
[How to dispute a result](#how-to-dispute-a-result)). Corrections are published
as dated entries with the original left visible, and a response from a scanner's
maintainers is published alongside its scores.

## Known limitations

State these before reading any result. They are copied from
[disclosure.md](disclosure.md#known-weaknesses-to-state-proactively) and are not
softened.

- **The corpus is small and synthetic.** Recall here is recall against 11 planted
  flaws, not against real-world MCP servers.
- **A1 versus A4 is knowingly mis-scored in one case.** The taxonomy grants A4
  credit to a scanner that walks non-source data files and flags the poisoned
  fixture. Such a finding arrives in the static stage, where the mapping layer
  resolves injection labels to A1, so a legitimate A4 detection scores as a
  false positive on one server plus a near miss on another. The alternative,
  discriminating on finding text, was rejected as unreviewable. See the open
  question in [decisions.md](decisions.md).
- **The near-miss counter is inflatable** and is not evidence of near-competence.
  A scanner that reports every class on every server earns near misses almost
  everywhere. The counter is never published without the false-positive count
  beside it, and no text describes a near miss as "almost right".
- **Credential-free configurations only.** Where part of a scanner's analysis
  sits behind a key we did not supply, the row measures what a user gets without
  one. That bounds what those rows can show. One scanner's entire analysis is
  gated this way and its row is published as unavailable, with the reason.
- **A zero needs its cause stated.** See above.

Beyond that list, two things the data cannot tell you. A high score is not an
endorsement and a low score is not a claim that a tool is bad at things this
benchmark does not measure. And the mapping from a scanner's labels to our
classes is a set of judgment calls, each written down with its reasoning, and
we expect some to be wrong.

## Results

*Everything below is a placeholder to be filled from the published scoreboard
from the publishing run. Do not write results from memory, from the
commit history, or from the preliminary figures.*

Corpus version `[CORPUS_VERSION]`, produced `[DATE]`, `[N]` scanners measured.

The shape of what to report, one scanner at a time, in alphabetical order:

- `[RESULT: <scanner> overall recall, mean and range over 5 runs]`
- `[RESULT: <scanner> overall precision, mean and range]`
- `[RESULT: <scanner> per-class recall, the classes it detected and the classes
  it missed]`
- `[RESULT: <scanner> kind of zero, for each class it missed: scan surface,
  rule coverage, or our setup]`
- `[RESULT: <scanner> unmapped count, near-miss count with false-positive count
  beside it]`
- `[RESULT: <scanner> requires signup, stages attempted, config label]`

Cross-scanner observations, only if the data supports them:

- `[RESULT: whether any attack class was detected by more than one scanner]`
- `[RESULT: which classes no scanner detected]`
- `[RESULT: whether the scanners' coverage was disjoint or overlapping]`
- `[RESULT: how the runtime classes (response injection, argument exfiltration,
  authless endpoint) fared compared with the static ones]`
- `[RESULT: any scanner whose run-to-run range exceeded the high-variance
  threshold]`

If a scanner's maintainers have submitted a response, quote it as published on
the scoreboard row, unedited except for length, and say what we changed because
of it. If a mapping dispute is unresolved, show both positions side by side as
the policy requires.

## Add your scanner

If a scanner is missing, add it. The inclusion criteria are fixed and apply to
everyone: reproducibly runnable without a sales call, publicly obtainable,
containerizable, parseable output, and a licence compatible with publishing the
output. An account requirement is disclosed, not disqualifying.

A submission is an adapter, a pinned Dockerfile, a mapping file in which every
label has a written reason, and tests. Vendors may submit for their own tool;
authorship is disclosed on the row. A result for your tool can be disputed
after publication like any other, and a response from you is published next to
the score.

The walkthrough is
[adding-a-scanner.md](adding-a-scanner.md).

## How to dispute a result

Open a public issue citing the `corpus_version`, `scanner_version`,
`adapter_version`, and the specific item or `mapping_rationale_id` you dispute.
Every published number is traceable to those.

We re-run the configuration and post the raw output. A misconfiguration or
adapter bug is fixed, re-run, and published as a correction entry with the
original left visible. A mapping dispute is reviewed in public: if we are
persuaded, the mapping changes, the corpus version bumps, and a correction
notice is published for every affected scanner; if not, both positions are published side by side on
the row. We aim to acknowledge within 7 days and to resolve or publish a
statement of disagreement within 30. Disputes are never settled privately,
because a correction only the disputing vendor knows about is not a correction.

## What we will not do

Ship a scanner. Take money from any vendor measured or eligible to be measured.
Edit a published result silently. Publish a number from one corpus version
beside a number from another.

Repository: `[REPO URL]`

---

# Variants

Both variants follow the same rule as the post: no numbers in this file.
Placeholders are filled at publication, from the published scoreboard only.

## Show HN

**Title**

Show HN: A vendor-neutral benchmark for MCP security scanners (we don't ship one)

**First comment**

I built mcp-sec-bench because I could not find a neutral measurement of how well
MCP security scanners work. The one public comparison I found comes from a repo
whose own tool tops it.

It is a corpus of 11 deliberately vulnerable MCP servers plus 4 benign controls,
ten attack classes, a static stage and a live-endpoint stage, and a runner that
executes each scanner from a pinned container five times and reports mean and
range. It is not a scanner and the repo's governance forbids it ever becoming
one.

Choices you may disagree with, so you can argue with them directly: no partial
credit, no composite score (rows sort alphabetically), static-only tools are not
penalised for runtime classes, and findings we cannot map to a class count as
neither hits nor false positives. Each scanner's labels are mapped to our
classes in a reviewable file with a reason per label.

Limits, up front: the corpus is small and synthetic, so recall here is recall
against planted flaws and not against real servers. One A1 versus A4 case is
knowingly mis-scored. The near-miss counter is inflatable. Default,
credential-free configurations only. When a scanner scores zero I say whether it
never reads that surface or read it and has no rule, because those are different
claims.

I have to own a process failure: the results were published without the
pre-publication review by maintainers that the policy in the repo originally
promised. I decided not to run it, and that is logged in docs/decisions.md. Any
maintainer can dispute a result in public. `[RESULT: one-sentence shape of the
finding, filled from the published scoreboard]`.

If your scanner is missing, there is a walkthrough for adding it, and if a
result of yours is wrong, a public dispute process that ends with both positions
shown if we disagree. `[REPO URL]`

## r/netsec

**Title**

mcp-sec-bench: a neutral, reproducible benchmark for MCP security scanners, with
the methodology and its known flaws up front

**Body**

Nobody has a neutral measurement of how well MCP security scanners detect what
they claim to, so this project builds one. It is a corpus (11 deliberately
vulnerable MCP servers, 4 benign controls), a taxonomy of ten attack classes
(tool-description injection, rug-pull, cross-server shadowing, response
injection, argument exfiltration, authless endpoint, hardcoded secrets,
unrestricted file read, unrestricted env access, command execution), a runner,
and written scoring rules. It never ships its own scanner, and the governance
doc makes that rule non-amendable.

Method, briefly: static and live-endpoint stages; every scanner runs from a
pinned container, in its documented default configuration, five times; mean and
range are reported; no partial credit; no composite score; a scanner is not
penalised for a stage it does not attempt; unmapped findings are neither true
nor false positives. The mapping from each scanner's labels to our classes is
the most contestable part, so it is one file per scanner with a rationale per
label, and disputes end with both positions published.

Limitations: small synthetic corpus; one A1 versus A4 case knowingly mis-scored;
inflatable near-miss counter; credential-free configurations only; and a zero
is described as scan-surface, rule-coverage, or our-setup, not as one number.

Disclosure: we did not follow our own original policy. Results are published
without pre-publication review by maintainers; the owner dropped that round on
2026-09-30 and it is recorded in the repo. Anyone can dispute a result, and
maintainers' responses are published beside the scores.

`[RESULT: one-sentence shape of the finding, filled from the published
scoreboard]`

Corrections and additions welcome, including adapters for scanners we missed:
`[REPO URL]`
