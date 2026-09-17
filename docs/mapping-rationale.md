# Taxonomy mapping rationale

Status: **mechanism and procedure locked; label tables empty.**

This document is the public record of every judgment call that converts a
scanner's own vocabulary into the classes in [taxonomy.md](taxonomy.md). It is
written before any scanner label has been captured, for the same reason
[scoring.md](scoring.md) and [governance.md](governance.md) were written before
any result existed: a procedure published after the numbers is a defence of the
numbers.

Machine-readable form: one file per scanner under `mapping/`, conforming to
[`mapping/schema.json`](../mapping/schema.json). Applied by
[`runner/mapping.py`](../runner/mapping.py). Every mapped finding in the results
JSON carries the `mapping_rationale_id` of the entry that placed it, so any
number on the scoreboard traces back to a specific paragraph here that a reader
can disagree with.

---

## 1. Why mapping is unavoidable

Scanners in this category do not share a vocabulary. The independent run that
motivated this project found the taxonomies of the tools it compared to be
**completely disjoint** — the tools are complementary rather than redundant, and
no single tool's output tells you your coverage. That is the project's central
empirical claim, and it has a direct consequence: there is no common vocabulary
to normalise into. We have to pick one and map onto it.

So we map onto ours, and the mapping becomes the most contestable artifact the
benchmark produces. A scanner's published recall depends on it. A vendor who
disagrees with one line here can move their own number. That is exactly why the
mapping lives in reviewable files with per-entry reasoning rather than inside
per-scanner parsing code, and why [`runner/README.md`](../runner/README.md)
forbids adapters from mapping: one file to read, one place to argue with.

Three things follow, and they are the load-bearing commitments of this document:

- **Our taxonomy is not privileged, it is just fixed.** A label that does not
  fit is evidence about our ten classes, not a deficiency in the scanner.
- **A mapping is an argument, not a lookup.** Every entry states what it cites
  and what it rejected.
- **Being wrong in public is the design.** The dispute path in section 8 ends
  with both positions on the scoreboard, not with our resolution of them.

## 2. What a mapping decision is keyed on

A mapping entry is keyed on the scanner's **raw label, verbatim** — the exact
string in the output field named by the file's `label_source_field` (a rule id,
a check name, a category). Adapters must preserve it unaltered; the mapping
layer matches on it byte-exactly.

A mapping decision may **not** be keyed on:

- **which server the finding landed on** — that would let the corpus's ground
  truth decide the mapping, which is circular and would manufacture true
  positives;
- **the finding's free-text message** — a substring rule over prose is not
  reviewable, and its accuracy would be a property of our reading rather than
  of the tool's detection;
- **severity, confidence scores, or anything else the scanner attaches** —
  these vary by configuration and version and would silently re-map a tool when
  it ships a new default.

The class comes from the label. The server comes from the reported location
(section 6). The two are resolved independently and combined at the end.

## 3. The decision procedure

Applied in order. Every entry records which rules it used in
`resolution_rules`.

**R1 — Cite the present-when test, or do not map.**
A label maps to a class only if the property the label reports satisfies that
class's *Present when* test in [taxonomy.md](taxonomy.md). The entry quotes the
test and states how it is satisfied (`taxonomy_evidence`, required by the
schema for every mapped entry). If no class's test is satisfied by what the
label reports, the label is `unmapped`. Reaching for "closest in spirit" is how
a mapping layer starts measuring itself.

**R2 — The taxonomy's own "Not this class" clause settles a span.**
When two tests look satisfied, check whether one class explicitly disclaims the
case. Several of ours do: A8 disclaims reads that happen through a subprocess
(that is A10); A9 disclaims the credential literal (that is A7); A1 disclaims
the payload that only appears after a state change (that is A2) and the one
that names another server's tool (that is A3). A disclaimer is cheap for a
reviewer to check — quote it and the entry is settled.

**R3 — Split a label only on a fact the runner records.**
Some single vendor labels genuinely cover two of our classes. The only
permitted way to give one label two mappings is to scope entries by the
**stage** that produced the finding (`applies_to_stage`), because the stage is
a hard fact recorded in the run, not a judgment about the finding's content.
This is the mechanism for the coarse "prompt injection" shape that covers both
metadata payloads (A1, static) and return-value payloads (A4, runtime). Two
entries may share a label only when their stage scopes are disjoint; the loader
rejects any other duplicate. There is **no** content-based discriminator, by
decision and not by omission — a substring rule over finding text would make
every entry using it unreviewable.

**R4 — When nothing distinguishes, leave it unmapped.**
If more than one class's test is satisfied, no disclaimer settles it, and no
stage split applies, the label is `unmapped` with reason
`no-defensible-single-class`. It is not mapped to the least-bad option.
`unmapped` costs the scanner nothing in precision (section 7); choosing wrong
costs it a false positive and a near miss, and costs the benchmark its claim to
be measuring the tool rather than our reading of it.

**R5 — Map the label, never the target.**
Nothing in a mapping decision may reference the corpus: not which server a
finding hit, not what the manifest declares there, not what the scanner's score
would become. Mapping tables are written and **frozen against a
`corpus_version` before the scoring run** (`frozen_for_corpus_version`), which
is what makes this rule checkable rather than a promise.

**R6 — Prefer the error you can see.**
Where a residual error is unavoidable — R3's stage split misfiles the rare
scanner that reads a poisoned fixture file during a static scan, for instance —
choose the option whose failure surfaces in the published table as a near miss
on a named item, and write the failure mode into the entry's rationale. An
error a reader can find and dispute is categorically better than one absorbed
into a heuristic.

### Review checklist applied to every entry

1. Does it quote the present-when test it relies on?
2. Would we accept this same mapping if it lowered a favoured tool's score, and
   if it raised a disfavoured one's? A mapping that only reads well in one
   direction is not a mapping.
3. Does the rationale answer the strongest objection, or only assert?
4. Is the author free of a disclosed tie to this vendor
   ([governance.md](governance.md#conflicts-of-interest) requires recusal)?
5. Is `dispute_risk` honest? Under-marking it hides the invitation to contest.

## 4. Evidence a decision must cite

The schema enforces most of this; the rest is review practice.

| Field | Required when | Why |
| --- | --- | --- |
| `raw_label` | always | Exact, verbatim. The thing being mapped. |
| `label_source_field` (file level) | always | A reviewer cannot check a match without knowing which output field was matched. |
| `taxonomy_evidence.present_when_quote` | `decision: map` | The test from taxonomy.md, quoted. R1. |
| `taxonomy_evidence.why_satisfied` | `decision: map` | How the label's reported property satisfies it. |
| `considered_classes[].why_rejected` | label spans classes | The spanning is the interesting part; it must not be hidden by a one-line table row. |
| `resolution_rules` | `considered_classes` present | Which of R1–R6 decided it. |
| `unmapped_reason` | `decision: unmapped` | Distinguishes "outside our scope" from "our taxonomy cannot place this". |
| `rationale` | always | The prose a disputing vendor argues with. |
| `confidence`, `dispute_risk` | always / recommended | Our own estimate of how solid and how contestable the call is. |
| `decided_on`, `decided_by` | always | Attribution and recusal. |
| `label_provenance` (file level) | always | Whether these labels were captured from output we ran, taken from docs, or are placeholders. |

## 5. Matching: exact by default

Lookup is **byte-exact** on the raw label. A mapping file may opt into exactly
two normalizations, declared in its `matching` block and applied in that order:

| Flag | Effect | When it is justified |
| --- | --- | --- |
| `strip_surrounding_whitespace` | Leading/trailing whitespace removed before comparison. Interior whitespace never touched. | The scanner pads labels in its text output. |
| `case_insensitive` | Unicode casefold both sides. | The scanner's own casing varies between versions or engines. |

Both default to false, both are recorded per file with a `note` giving the
observed instability that justifies them, and any match that was not
byte-exact is counted in the run's mapping report. Nothing else exists — no
substring, prefix, stemming, edit distance, or embedding similarity. Fuzzy
matching would mean no reviewer could predict what a table does, and a table
whose behaviour cannot be predicted cannot be disputed.

Case-folding that would make two distinct labels collide is a load error, not a
silent merge.

## 6. Resolving the server

A finding names a class and a target, and [scoring.md](scoring.md) credits only
a finding that gets **both** right. Scanners report file paths, so the mapping
layer resolves a path to a corpus `server_id`: the server id is the corpus
directory name, and a path belongs to a server exactly when one of its path
components is a known id. Paths arrive in whatever shape the container mount
produced, so separators are normalised and `.`/`..` segments dropped — this is
path parsing, not label matching, and the exactness rule in section 5 does not
apply to it.

Four outcomes are recorded explicitly rather than guessed at:

| Situation | Result |
| --- | --- |
| Adapter declared a `server_id` we know | resolved (`declared`) |
| Path contains exactly one known server id | resolved (`path-component`) |
| Adapter declared a server id we do not have | **unresolved** — usually adapter/corpus drift, never coerced |
| Path names no known server, or names two | **unresolved** |

An unresolved finding keeps whatever class its label maps to, but has no
server, so `MappedFinding.is_mapped` is false and scoring treats it as
`unmapped` — no credit, no penalty. It is listed individually in the run's
mapping report. **We never attribute a finding to a server it did not name**,
even when only one server in the corpus could plausibly be meant: that would
invent true positives out of our own knowledge of the ground truth, which is
R5's prohibition in its most tempting form.

## 7. `unmapped` is a measurement of us

From [scoring.md](scoring.md#normalization): an unmapped finding is **neither a
true positive nor a false positive**. It appears in its own column. It does not
touch precision.

Two distinct things land there, and the results keep them apart:

- **Deliberately unmapped** — we saw the label and decided not to place it
  (`decision: unmapped`). The finding still carries the `rationale_id`, so the
  blank in the results is traceable to the paragraph that argued for it.
- **No mapping entry** — the label is not in our table at all. This is a gap,
  it is reported per label with counts and an example
  (`MappingReport.gap_report()`), and it goes into the disclosure pack the
  vendor receives before publication so they can see exactly which of their
  output we ignored.

**A high unmapped count is a signal to revise our taxonomy, not a mark against
the scanner.** Stated as plainly as possible because it is the thing most
likely to be misread from a scoreboard: the ten classes are a v1 draft against
a young category, and a tool that keeps reporting real problems we did not
think to define is telling us our denominator is too small. The scoreboard
reports unmapped counts as a taxonomy-review trigger, and the README says so
next to the column. Nobody is ranked by it.

What `unmapped` does cost the scanner is recall: the item it may genuinely have
found stays a false negative. That asymmetry is real, it is disclosed to the
vendor during the 14-day window, and it is the price of not guessing.

## 8. Disputes, and publishing both positions

[governance.md](governance.md#contesting-a-result) lets any vendor, or any
member of the public, contest a mapping by citing its `mapping_rationale_id`.
Every published number carries one, by design.

1. **Public issue** naming the `corpus_version`, `scanner_version`,
   `adapter_version`, and the `mapping_rationale_id`.
2. **Public review** of the rationale. Never a private resolution.
3. **If we are persuaded**: the entry changes, an `history` record is appended
   with the reason and the governance reference (published results are never
   silently edited), the corpus version bumps, and every affected scanner is
   re-disclosed with a fresh 14-day window.
4. **If we are not persuaded**: the entry is marked `status: disputed`, the
   vendor's position is recorded **in their words** alongside ours in the
   entry's `dispute` block with `outcome: both-positions-published`, and the
   scoreboard row carries the `scoreboard_note` stating both readings and which
   items would move under theirs. A reader is entitled to see the disagreement
   rather than only our resolution of it.

The `dispute` block records `affected_items` — the concrete `(server, class)`
items whose outcome changes under the vendor's reading — so the stake of the
disagreement is a fact a reader can check rather than a rhetorical position.

A worked example of the both-positions shape is
[`mapping/example-scanner.json`](../mapping/example-scanner.json),
`MR-example-scanner-007`.

## 9. Change control

- A mapping table is **frozen against a `corpus_version` before a scoring
  run**. Mid-run edits are not a thing that can happen quietly.
- `rationale_id`s are never reused and never renumbered. A published number
  points at one.
- Entries are superseded, never deleted: `status: withdrawn` plus a `history`
  record.
- A mapping change that moves a published score triggers re-disclosure under
  [governance.md](governance.md#disclosure-before-publication).
- Illustrative placeholder files cannot be loaded into a scoring run without an
  explicit opt-in flag, so invented labels cannot reach a scoreboard by
  accident.

---

## 10. Per-scanner mapping tables

> **Empty by design, as of 2026-09-17.** No scanner's output vocabulary has
> been captured yet, and which of the candidate tools exist and run
> reproducibly is still being verified. **This section stays empty until an
> adapter has run the tool and its raw output is committed.** Nothing below is
> a real label. Inventing plausible-looking vendor labels would poison the
> benchmark at precisely its most contestable point, so the placeholder tables
> carry no rows rather than illustrative ones; the illustrative rows live in
> `mapping/example-scanner.json`, prefixed `EXAMPLE_` so they cannot be
> mistaken for a vocabulary.

Each table is generated from that scanner's file in `mapping/` and has these
columns:

| Raw label (verbatim) | Stage scope | Class | Rationale | Confidence | Status |
| --- | --- | --- | --- | --- | --- |

Candidate scanners, named in [project-plan.md](project-plan.md) as a starting
list and **not yet verified to exist, be obtainable, or be runnable**:

### mcp-scanner (Cisco) — *unverified candidate*

Mapping file: not created. Labels captured: none. Adapter: not started.

| Raw label (verbatim) | Stage scope | Class | Rationale | Confidence | Status |
| --- | --- | --- | --- | --- | --- |
| *(no labels captured)* | | | | | |

Expected to need the R3 stage split if a single label covers its YARA, LLM-judge
and behavioural engines; noted as an expectation, not a finding.

### agent-scan / Invariant mcp-scan (Snyk) — *unverified candidate*

Mapping file: not created. Labels captured: none. Adapter: not started.

| Raw label (verbatim) | Stage scope | Class | Rationale | Confidence | Status |
| --- | --- | --- | --- | --- | --- |
| *(no labels captured)* | | | | | |

`requires signup` applies if a token is needed to run at all; that is a
scoreboard column, not a mapping concern.

### sentinel-scan-cli (community) — *unverified candidate*

Mapping file: not created. Labels captured: none. Adapter: not started.

| Raw label (verbatim) | Stage scope | Class | Rationale | Confidence | Status |
| --- | --- | --- | --- | --- | --- |
| *(no labels captured)* | | | | | |

### mcp-guard (community) — *unverified candidate*

Mapping file: not created. Labels captured: none. Adapter: not started.

| Raw label (verbatim) | Stage scope | Class | Rationale | Confidence | Status |
| --- | --- | --- | --- | --- | --- |
| *(no labels captured)* | | | | | |

### Disputed entries across all scanners

| Scanner | Rationale | Our class | Vendor's class | Outcome | Scoreboard note |
| --- | --- | --- | --- | --- | --- |
| *(none — no results published yet)* | | | | | |

---

## 11. Class boundaries we expect to be contested

Recorded now, before any dispute exists, so that when one arrives it is visible
that we anticipated the boundary rather than discovered it under pressure. Each
of these is a place where a shipping scanner's vocabulary is coarser than our
line, which means the mapping — not the tool — will decide the number.

1. **A1 vs A4 — metadata payload vs return-value payload.** Most tools ship one
   "prompt injection" concept. Our split is by *where the text lives*, which is
   a distinction their label does not carry. R3's stage split is the mitigation
   and it is imperfect in a documented direction: taxonomy.md explicitly allows
   A4 credit to a scanner that walks non-source data files, and such a finding
   arrives in the static stage. **Highest-risk boundary in the taxonomy.**
2. **A1 vs A3 — general agent-directed payload vs cross-server shadowing.** A3
   requires a reference to another server's tool. A scanner scanning one server
   at a time structurally cannot see it, and a scanner that flags the text
   without noting the cross-reference will be mapped A1 and score a near miss
   on the A3 server. The runner records scan scope precisely so this can be read
   as a scope fact rather than a detection failure.
3. **A7 vs A9 — the secret's origin.** "Credential exposure" is a single
   concept in most vocabularies; we split the literal in source (A7) from the
   channel that leaks the environment (A9). Worked through as the disputed
   example entry, because it is the most likely first real dispute.
4. **A8 vs A10 — file read via subprocess.** Settled cleanly by A8's own
   disclaimer, but a tool reporting `subprocess` + a path will look like both,
   and a tool that reports only the data-flow sink may name neither.
5. **A2 static vs runtime, and A2 vs A1.** A scanner that flags a call-count
   branch may label it "suspicious logic" rather than anything injection-shaped;
   a scanner that diffs descriptors at runtime may label it "tool changed". The
   same class arrives under two unrelated vocabularies, and one of them may be
   too coarse to satisfy R1 at all.
6. **A5 vs "not this class" for declared destinations.** A5 turns on whether the
   destination is *declared*, which is a property of the server's stated purpose
   rather than of the code. A scanner reporting "outbound network call in tool"
   cannot carry that distinction, so it will fire identically on the A5 server
   and on the C2 benign webhook control. Expect the same label to be a true
   positive on one and a false positive on the other — which is the control
   working as designed, and will nonetheless be argued about.
7. **A6 `n/a` versus missed.** Not a mapping boundary but a neighbouring one: a
   stdio server cannot exhibit A6 and is excluded from the denominator. A
   scanner whose auth label fires on stdio servers produces findings with
   nowhere to land.
8. **Generic app-sec labels inside MCP scanners.** Dependency CVEs, SSRF, SQL
   injection: real findings, deliberately outside our scope boundary, and they
   will dominate the unmapped column for any tool that bundles a general static
   analyser. That is a fact about our taxonomy's scope, and section 7 is how it
   gets read.
