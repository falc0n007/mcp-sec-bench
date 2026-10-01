# Launch write-up

**Status: DRAFT. Not to be published until the disclosure round closes and
corrections are folded in.**

This repository is public. This file therefore contains no scanner scores, no
recall or precision figures, and no per-scanner outcomes. Everything that would
be one is a bracketed placeholder, for example `[RESULT: ...]` or
`[MAINTAINER RESPONSE: ...]`. Fill them from the published scoreboard only, and
only after the window described in [disclosure.md](disclosure.md) has closed.
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

## How the disclosure round deviated from our own policy

[governance.md](governance.md#disclosure-before-publication) commits that every
scanner's maintainers receive their full results, the methodology, and the exact
mapping decisions applied to their tool, with 14 days to respond, before anyone
else sees a number.

**We did not honour that for the first round.** The repository was made public
with preliminary figures already in its commit history. We recorded the
deviation in [decisions.md](decisions.md) and in the README instead of rewording
the policy to match what happened, and we ran the round immediately instead of
retroactively justifying the ordering. Subsequent rounds follow the policy as
written; this does not set a precedent.

What this means for a reader: early figures exist in the commit history and were
seen by the public before the maintainers saw them. Corrections from the round
have been folded in since, and are listed in `[CORRECTIONS: summary of changes
made after maintainer review, with links to the dated entries]`.

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
after the disclosure window closes. Do not write results from memory, from the
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
- `[MAINTAINER RESPONSE: <scanner>, verbatim or linked, or "no response"]`

Cross-scanner observations, only if the data supports them:

- `[RESULT: whether any attack class was detected by more than one scanner]`
- `[RESULT: which classes no scanner detected]`
- `[RESULT: whether the scanners' coverage was disjoint or overlapping]`
- `[RESULT: how the runtime classes (response injection, argument exfiltration,
  authless endpoint) fared compared with the static ones]`
- `[RESULT: any scanner whose run-to-run range exceeded the high-variance
  threshold]`

For each scanner whose maintainers responded, `[MAINTAINER RESPONSE: ramparts]`,
`[MAINTAINER RESPONSE: cisco]`, `[MAINTAINER RESPONSE: mcp-guard]`,
`[MAINTAINER RESPONSE: sentinel-scan-cli]`, and
`[MAINTAINER RESPONSE: snyk-agent-scan]`, quote the response as published on the
scoreboard row, unedited except for length, and say what we changed because of
it. If a mapping dispute is unresolved, show both positions side by side as the
policy requires.

## Add your scanner

If a scanner is missing, add it. The inclusion criteria are fixed and apply to
everyone: reproducibly runnable without a sales call, publicly obtainable,
containerizable, parseable output, and a licence compatible with publishing the
output. An account requirement is disclosed, not disqualifying.

A submission is an adapter, a pinned Dockerfile, a mapping file in which every
label has a written reason, and tests. Vendors may submit for their own tool;
authorship is disclosed on the row. Before any result for your tool is
published, you see it, the methodology, and the mapping decisions applied to it,
and have 14 days to respond. Your response is published next to the score.

The walkthrough is
[adding-a-scanner.md](adding-a-scanner.md).

## How to dispute a result

Open a public issue citing the `corpus_version`, `scanner_version`,
`adapter_version`, and the specific item or `mapping_rationale_id` you dispute.
Every published number is traceable to those.

We re-run the configuration and post the raw output. A misconfiguration or
adapter bug is fixed, re-run, and published as a correction entry with the
original left visible. A mapping dispute is reviewed in public: if we are
persuaded, the mapping changes, the corpus version bumps, and every affected
scanner is re-disclosed; if not, both positions are published side by side on
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

I have to own a process failure: the repo went public with early figures in its
history before the maintainers had seen their results, contrary to the policy
written in the repo. That is logged in docs/decisions.md and the disclosure round
ran afterwards. `[RESULT: one-sentence shape of the finding, filled from the
published scoreboard]`. `[MAINTAINER RESPONSE: link to published responses]`.

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

Disclosure: we did not follow our own policy for the first round. The repo went
public with preliminary figures in its history before maintainers saw their
results. It is recorded in the repo and the 14-day round was run afterwards.
`[MAINTAINER RESPONSE: summary of who responded, from the published scoreboard]`

`[RESULT: one-sentence shape of the finding, filled from the published
scoreboard]`

Corrections and additions welcome, including adapters for scanners we missed:
`[REPO URL]`
