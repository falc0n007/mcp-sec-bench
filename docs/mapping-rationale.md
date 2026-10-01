# Taxonomy mapping rationale

Status: **mechanism and procedure locked; label tables populated from captured output (Snyk's remain unverified).**

This document is the public record of every judgment call that converts a
scanner's own vocabulary into the classes in [taxonomy.md](taxonomy.md). It is
written before any scanner label had been captured, for the same reason
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

> **Status as of the Phase 3 disclosure round.** Four tables below record labels
> captured from real output this project produced. One, Snyk's, is **unverified**:
> a token gates all of that tool's analysis, so no real output has ever been
> observed and its labels are best guesses from documentation. Nothing in this
> section is a label we invented; the invented ones live in
> `mapping/example-scanner.json`, prefixed `EXAMPLE_`.

**The mapping files are the source of truth.** Each table is derived from that
scanner's file in `mapping/`, and where this document and a file disagree the
file is what the runner applies. The tables carry the decision, its identifier,
our confidence, and the first sentence of the rationale. The full rationale,
the quoted present-when test, the classes considered and rejected, and the
decision date are in the file, and every one of them is also sent to the
scanner's maintainers in the disclosure pack. Every label has an entry,
including each one left unmapped, because an unmapped label with no reasoning
is indistinguishable from one we never looked at.

Columns: `Class` is the class credited, or `unmapped` with the reason code from
`mapping/schema.json`. `Status` is `accepted`, or `provisional` where the entry
was drafted before the label was seen in real output or rests on a reading we
expect to be argued with. No entry is currently `disputed`.

Provenance values, from the schema: `captured-from-real-output` means every
label was copied verbatim from output this project produced and the capture is
committed; `unverified` means the labels come from documentation or a third
party and have not been observed in output we ran.

### mcp-scanner (Cisco)

Mapping file: `mapping/cisco-mcp-scanner.json`. Scanner version(s) checked: 4.8.4. Adapter version: 1.0.0. Provenance: **captured-from-real-output**. Matched on: `findings.<analyzer>.threat_names[]`. 8 entries: 1 mapped, 7 unmapped.

Labels were copied from output of the pinned image; the captures are committed under `tests/fixtures/cisco-mcp-scanner/`. Only one of the eight labels is mapped.

| Raw label (verbatim) | Stage scope | Class | Rationale ID | Confidence | Status | Rationale (first sentence) |
| --- | --- | --- | --- | --- | --- | --- |
| `PROMPT INJECTION` | any | A1 | MR-cisco-mcp-scanner-001 | medium | accepted | This is the only Cisco label that fires anywhere on this corpus, so it is the only entry that moves a number, and it is worth being precise about what it costs the tool. |
| `TOOL POISONING` | any | unmapped: no-defensible-single-class | MR-cisco-mcp-scanner-002 | medium | accepted | Read the rule rather than the name and this label turns out to straddle our line rather than sit on either side of it. |
| `INJECTION ATTACK` | any | unmapped: no-defensible-single-class | MR-cisco-mcp-scanner-003 | high | accepted | One string, three rules, and the three land on opposite sides of our scope boundary: command injection is A10's subject, SQL injection is explicitly excluded by taxonomy.md, and embedded script payloads are neither. |
| `CODE EXECUTION` | any | unmapped: insufficient-specificity | MR-cisco-mcp-scanner-004 | high | accepted | The contrast that decides this entry is with another scanner in the same benchmark. |
| `CREDENTIAL HARVESTING` | any | unmapped: no-defensible-single-class | MR-cisco-mcp-scanner-005 | medium | accepted | docs/mapping-rationale.md section 11 item 3 names A7-vs-A9 as the most likely first dispute in the whole benchmark, and this label is that dispute in its purest form: a single vendor string covering both the credential literal and the environment-variable channel, with our two classes each explicitly disclaiming the other's half. |
| `DATA EXFILTRATION` | any | unmapped: insufficient-specificity | MR-cisco-mcp-scanner-006 | high | accepted | The name is close enough to A5 that mapping it would look obvious, which is the reason to be careful. |
| `SYSTEM MANIPULATION` | any | unmapped: insufficient-specificity | MR-cisco-mcp-scanner-007 | high | accepted | This label bundles at least four unrelated properties -- environment access, destructive file operations, permission and privilege changes, and process control -- and brushes three of our classes without satisfying any of their tests. |
| `unknown` | any | unmapped: informational-only | MR-cisco-mcp-scanner-008 | high | accepted | The readiness analyzer is not in this adapter's default configuration, for reasons the capture makes plain: it reports HIGH on every tool of every server for operational-maturity properties such as a missing timeout, seven findings per tool, with no taxonomy crosswalk attached and the literal threat name `unknown`. |

### mcp-guard (community)

Mapping file: `mapping/mcp-guard.json`. Scanner version(s) checked: 2.0.0. Adapter version: 1.0.0. Provenance: **captured-from-real-output**. Matched on: `findings[].rule_id`. 23 entries: 9 mapped, 14 unmapped.

Three of the labels below were captured verbatim from a whole-corpus scan, committed at `tests/fixtures/mcp-guard-corpus-scan.json`. The remainder are labels the scanner can emit that did not fire on this corpus; those entries are mostly `provisional`.

| Raw label (verbatim) | Stage scope | Class | Rationale ID | Confidence | Status | Rationale (first sentence) |
| --- | --- | --- | --- | --- | --- | --- |
| `MCPG-SECRET-HARDCODED` | any | A7 | MR-mcp-guard-001 | high | accepted | The clean case: the rule and the class name the same property, a credential-shaped literal in source. |
| `MCPG-PY-PATH-TAINT` | any | A8 | MR-mcp-guard-002 | high | accepted | High confidence on the class, and the interesting fact about this rule is not the mapping but what it is blind to. |
| `MCPG-JS-PATH-TAINT` | any | A8 | MR-mcp-guard-003 | medium | provisional | The JavaScript twin of MR-mcp-guard-002, and weaker in one respect that we state rather than smooth over: where the Python rule performs intraprocedural taint from a handler parameter, this one fires on any non-literal path expression, which is a broader and less caller-anchored trigger. |
| `MCPG-PY-SHELL-TAINT` | any | A10 | MR-mcp-guard-004 | high | accepted | The strongest entry in the table: the rule fired on a10a-command-execution and a10b-allowlist-bypass, on the exact subprocess.run(shell=True) lines the manifests declare, and on nothing else. |
| `MCPG-JS-SHELL-TAINT` | any | A10 | MR-mcp-guard-005 | medium | provisional | The JavaScript twin of MR-mcp-guard-004 and subject to the same caveat as MR-mcp-guard-003: 'non-literal' is a looser trigger than 'request-derived'. |
| `MCPG-JS-VM-EVAL` | any | unmapped: outside-taxonomy-scope | MR-mcp-guard-006 | medium | provisional | A real and serious finding that our ten classes do not define. |
| `MCPG-MCP-PROMPT-INJECTION-SURFACE` | any | A1 | MR-mcp-guard-007 | high | provisional | No stage split is needed here, which is worth saying because the coarse 'prompt injection' label that forces one (worked through in mapping/example-scanner.json) is the common shape in this category and this is not it. |
| `MCPG-MCP-URI-CONCAT` | any | A8 | MR-mcp-guard-008 | medium | provisional | The weakest mapped entry here and marked accordingly. |
| `MCPG-MCP-SCHEMA-UNDECLARED-ARGS` | any | unmapped: outside-taxonomy-scope | MR-mcp-guard-009 | high | provisional | A descriptor-versus-implementation mismatch: the tool accepts more than it advertises. |
| `MCPG-DEP-KNOWN-VULN` | any | unmapped: outside-taxonomy-scope | MR-mcp-guard-010 | high | provisional | taxonomy.md's scope boundary excludes 'generic application security findings with no MCP-specific surface', and a dependency sitting inside a published affected range is the textbook instance: the same finding would be reported about any Python project. |
| `MCPG-DOCKER-ROOT` | any | unmapped: not-mcp-specific | MR-mcp-guard-011 | high | provisional | A container hardening finding about the image a server might ship in, not about the server's MCP surface. |
| `MCPG-DOCKER-LATEST-TAG` | any | unmapped: not-mcp-specific | MR-mcp-guard-012 | high | provisional | A build reproducibility finding. |
| `MCPG-DOCKER-CHMOD777` | any | unmapped: not-mcp-specific | MR-mcp-guard-013 | high | provisional | A filesystem permissions finding inside a build layer. |
| `MCPG-DOCKER-ADD-REMOTE` | any | unmapped: not-mcp-specific | MR-mcp-guard-014 | high | provisional | Supply-chain integrity at build time: an unverified fetch into the image. |
| `MCPG-DOCKER-CURL-PIPE-SH` | any | unmapped: not-mcp-specific | MR-mcp-guard-015 | high | provisional | Recorded with its considered class because 'a shell runs a fetched script' is the single most tempting mis-map in the DOCKER family, and a reviewer should be able to see it was considered and why it lost rather than trust that it was. |
| `MCPG-DOCKER-ENV-SECRET` | any | unmapped: insufficient-specificity | MR-mcp-guard-016 | medium | provisional | The most arguable unmapped entry here, and we expect to be argued with, which is why the near-miss is written out rather than summarised as 'Docker, out of scope'. |
| `MCPG-DYN-CMDEXEC` | any | A10 | MR-mcp-guard-017 | high | provisional | Mapped although it cannot currently fire. |
| `MCPG-DYN-PATHTRAVERSAL` | any | A8 | MR-mcp-guard-018 | high | provisional | The runtime counterpart of MR-mcp-guard-002, and strictly better evidence: it proves containment failed rather than inferring it from the absence of a check, which is the distinction c01-notes-workspace was built to expose. |
| `MCPG-DYN-CRASH` | any | unmapped: outside-taxonomy-scope | MR-mcp-guard-019 | high | provisional | An availability finding. |
| `MCPG-DYN-JSONRPC-VIOLATION` | any | unmapped: outside-taxonomy-scope | MR-mcp-guard-020 | high | provisional | Protocol conformance, not a security class. |
| `MCPG-DYN-NO-DISPATCH` | any | unmapped: outside-taxonomy-scope | MR-mcp-guard-021 | high | provisional | Protocol conformance again, and additionally a self-declared meta-finding: the rule's own rationale says its purpose is to tell the operator that every other dynamic probe on this target is uninterpretable. |
| `MCPG-DYN-SCHEMA-UNENFORCED` | any | unmapped: outside-taxonomy-scope | MR-mcp-guard-022 | high | provisional | The runtime sibling of MR-mcp-guard-009 and unmapped for the same reason: our taxonomy has no class for a descriptor that does not bind its implementation. |
| `MCPG-DYN-UNDECLARED-METHOD` | any | unmapped: outside-taxonomy-scope | MR-mcp-guard-023 | high | provisional | An undeclared reachable method is a hidden capability, and if our taxonomy had a class for 'the server does more than it advertises' this would be its clearest instance. |

### Ramparts

Mapping file: `mapping/ramparts.json`. Scanner version(s) checked: 0.8.8. Adapter version: 1.0.0. Provenance: **captured-from-real-output**. Matched on: `yara_results[].rule_name`. 40 entries: 16 mapped, 24 unmapped.

The labels are the 40 YARA rule names shipped in `rules/pre/*.yar` at the pinned source tag and baked into the adapter image, so the table covers every label the scanner can emit; `tests/test_adapter_ramparts.py` fails if the two drift apart.

| Raw label (verbatim) | Stage scope | Class | Rationale ID | Confidence | Status | Rationale (first sentence) |
| --- | --- | --- | --- | --- | --- | --- |
| `PromptInjectionSignature` | any | A1 | MR-ramparts-001 | high | accepted | Clean R1 match. The rule's condition (read from ramparts 0.8.8's rules/pre/skill_prompt_injection.yar) fires on instruction-override, role-redefinition and concealment phrasing -- precisely A1's four disjuncts -- and, because this adapter only ever gives ramparts a live URL, the matched text is necessarily a descriptor field returned by the MCP handshake. |
| `IndirectPromptInjection` | any | A1 | MR-ramparts-002 | medium | accepted | This is the pair the build brief specifically asked to check rather than accept by name alone, and checking it changes the answer. |
| `CoerciveInjection` | any | A1 | MR-ramparts-003 | high | accepted | Settled by A3's own disclaimer: a claim of priority over unnamed 'other tools' in general is A1; only a claim that names and makes an assertion about a SPECIFIC other tool or server is A3. |
| `CapabilityInflation` | any | A1 | MR-ramparts-004 | medium | accepted | Most of this rule's signal (keyword stuffing, deceptive certification claims like 'certified by Anthropic', hidden activation triggers) is about discovery-ranking manipulation rather than direct behavioural override, which is a slightly broader read of A1 than PromptInjectionSignature's classic case. |
| `AutonomyAbuse` | any | A1 | MR-ramparts-005 | medium | accepted | The closest call in this table to a taxonomy gap. |
| `CovertExfiltration` | any | A1 | MR-ramparts-006 | medium | accepted | Named 'exfiltration' and tagged category 'exfiltration' in the rule's own metadata, so a name-based mapping to A5 is the obvious first guess -- and it is the wrong one once the present-when tests are actually checked, which is exactly what the build brief asked us to verify for this label. |
| `SkillSystemManipulation` | any | A1 | MR-ramparts-007 | medium | accepted | The content here (rm -rf, wipefs, chown of root paths) is more dramatic than the classic prompt-injection phrasing PromptInjectionSignature targets, which might tempt a reader to look for a more specific class. |
| `SkillToolChainingExfiltration` | any | A1 | MR-ramparts-008 | medium | accepted | Consistent with CovertExfiltration (MR-ramparts-006): the name and category tags say 'exfiltration', but the mechanism is textual instruction-matching over descriptor content, never an observed runtime egress attempt, so A5's behavioural test cannot be satisfied by what this rule reports in any configuration this adapter runs. |
| `UnicodeSteganography` | any | A1 | MR-ramparts-009 | high | accepted | This rule does not detect a new property; it detects an obfuscation technique applied to the same instruction-bearing content PromptInjectionSignature targets in the clear. |
| `SecretsLeakage` | any | A7 | MR-ramparts-010 | medium | accepted | Definitionally a clean A7 match: every sub-pattern requires an actual credential-shaped literal value, not a reference or a channel. |
| `SkillCredentialHarvesting` | any | A7 | MR-ramparts-011 | low | accepted | A genuine two-headed rule: one condition arm is a literal-credential-format test (A7-shaped, like SecretsLeakage), the other is theft-instruction language (A1-shaped, like CovertExfiltration). |
| `SSHKeyExposure` | any | A7 | MR-ramparts-012 | low | accepted | Like SkillCredentialHarvesting, this rule bundles a clean literal-credential test (PEM/SSH private key headers, public key blobs) with a much weaker filename/path-mention test (the string 'id_rsa' or '.ssh/' appearing anywhere). |
| `PEMFileAccess` | any | A7 | MR-ramparts-013 | low | accepted | Same reasoning and same caveat as SSHKeyExposure (MR-ramparts-012): a clean literal-key-material sub-pattern bundled with much weaker filename/keyword mentions under one label. |
| `EnvironmentVariableLeakage` | any | A9 | MR-ramparts-014 | medium | accepted | This is our version of the worked A7/A9 dispute in mapping/example-scanner.json (MR-example-scanner-007): the rule's condition genuinely has both an A7-shaped arm (literal value assigned to a credential-shaped name) and an A9-shaped arm (environment-access syntax plus theft language). |
| `CommandInjection` | any | A10 | MR-ramparts-015 | medium | accepted | Clean definitional match to A10 -- the rule exists specifically to catch shell/command-injection shapes, which is what A10 defines. |
| `PathTraversalVulnerability` | any | A8 | MR-ramparts-016 | medium | accepted | Definitionally the cleanest of the code-pattern rules -- A8's own worked example in mapping/example-scanner.json (MR-example-scanner-001) is this exact class of finding. |
| `SQLInjection` | any | unmapped: outside-taxonomy-scope | MR-ramparts-017 | high | accepted | Vendor description: 'Comprehensive SQL injection detection covering multiple attack vectors and evasion techniques'; this is the taxonomy's own literal example of an out-of-scope generic app-sec finding. |
| `CrossOriginEscalation` | any | unmapped: outside-taxonomy-scope | MR-ramparts-018 | high | accepted | Vendor description: 'multiple domains/origins in MCP tool configurations that could lead to cross-origin escalation attacks' -- detects several different URLs/domains appearing together in tool config text. |
| `MCPConfigRisk` | any | unmapped: outside-taxonomy-scope | MR-ramparts-019 | high | accepted | Vendor description: 'STDIO server uses risky shell/interpreter with inline code or pipe to shell' -- a property of how an MCP CLIENT would LAUNCH a stdio server, not of a tool the server exposes. |
| `NetworkReconnaissance` | any | unmapped: outside-taxonomy-scope | MR-ramparts-020 | high | accepted | Vendor description (hacktools.yar): 'Network reconnaissance and scanning patterns', category 'hack-tool' -- a generic offensive-tooling signature (nmap/masscan-style command references), not an MCP-specific class. |
| `BackdoorPersistence` | any | unmapped: outside-taxonomy-scope | MR-ramparts-021 | high | accepted | Vendor description (malware.yar): 'Backdoor persistence with malicious payloads (shell commands, SSH key injection, hidden root users)', category 'malware'. |
| `ASPXWebshell` | any | unmapped: outside-taxonomy-scope | MR-ramparts-022 | high | accepted | Malware/webshell/offensive-tooling signature (ASP.NET webshell signature), explicitly named in the build brief as out of scope: 'Malware/webshell families are out of our scope; leave them unmapped with a reason.' These rules exist to catch a server that has already been compromised or was malicious from the start -- a wholesale-server-integrity check -- not one of the ten specific attack classes this benchmark measures, none of which are about detecting a generically compromised host. |
| `C2FrameworkIndicators` | any | unmapped: outside-taxonomy-scope | MR-ramparts-023 | high | accepted | Malware/webshell/offensive-tooling signature (command-and-control framework signature), explicitly named in the build brief as out of scope: 'Malware/webshell families are out of our scope; leave them unmapped with a reason.' These rules exist to catch a server that has already been compromised or was malicious from the start -- a wholesale-server-integrity check -- not one of the ten specific attack classes this benchmark measures, none of which are about detecting a generically compromised host. |
| `CryptoCoinjacking` | any | unmapped: outside-taxonomy-scope | MR-ramparts-024 | high | accepted | Malware/webshell/offensive-tooling signature (browser/server cryptojacking signature), explicitly named in the build brief as out of scope: 'Malware/webshell families are out of our scope; leave them unmapped with a reason.' These rules exist to catch a server that has already been compromised or was malicious from the start -- a wholesale-server-integrity check -- not one of the ten specific attack classes this benchmark measures, none of which are about detecting a generically compromised host. |
| `CryptoMinerSoftware` | any | unmapped: outside-taxonomy-scope | MR-ramparts-025 | high | accepted | Malware/webshell/offensive-tooling signature (cryptomining software signature), explicitly named in the build brief as out of scope: 'Malware/webshell families are out of our scope; leave them unmapped with a reason.' These rules exist to catch a server that has already been compromised or was malicious from the start -- a wholesale-server-integrity check -- not one of the ten specific attack classes this benchmark measures, none of which are about detecting a generically compromised host. |
| `CryptoMiningPools` | any | unmapped: outside-taxonomy-scope | MR-ramparts-026 | high | accepted | Malware/webshell/offensive-tooling signature (cryptomining pool connection signature), explicitly named in the build brief as out of scope: 'Malware/webshell families are out of our scope; leave them unmapped with a reason.' These rules exist to catch a server that has already been compromised or was malicious from the start -- a wholesale-server-integrity check -- not one of the ten specific attack classes this benchmark measures, none of which are about detecting a generically compromised host. |
| `CryptoStratumProtocol` | any | unmapped: outside-taxonomy-scope | MR-ramparts-027 | high | accepted | Malware/webshell/offensive-tooling signature (Stratum mining-protocol signature), explicitly named in the build brief as out of scope: 'Malware/webshell families are out of our scope; leave them unmapped with a reason.' These rules exist to catch a server that has already been compromised or was malicious from the start -- a wholesale-server-integrity check -- not one of the ten specific attack classes this benchmark measures, none of which are about detecting a generically compromised host. |
| `ExploitFramework` | any | unmapped: outside-taxonomy-scope | MR-ramparts-028 | high | accepted | Malware/webshell/offensive-tooling signature (exploit-framework (e.g. |
| `InfoStealer` | any | unmapped: outside-taxonomy-scope | MR-ramparts-029 | high | accepted | Malware/webshell/offensive-tooling signature (credential/info-stealer malware signature), explicitly named in the build brief as out of scope: 'Malware/webshell families are out of our scope; leave them unmapped with a reason.' These rules exist to catch a server that has already been compromised or was malicious from the start -- a wholesale-server-integrity check -- not one of the ten specific attack classes this benchmark measures, none of which are about detecting a generically compromised host. |
| `JSPWebshell` | any | unmapped: outside-taxonomy-scope | MR-ramparts-030 | high | accepted | Malware/webshell/offensive-tooling signature (JSP webshell signature), explicitly named in the build brief as out of scope: 'Malware/webshell families are out of our scope; leave them unmapped with a reason.' These rules exist to catch a server that has already been compromised or was malicious from the start -- a wholesale-server-integrity check -- not one of the ten specific attack classes this benchmark measures, none of which are about detecting a generically compromised host. |
| `KeyloggerIndicators` | any | unmapped: outside-taxonomy-scope | MR-ramparts-031 | high | accepted | Malware/webshell/offensive-tooling signature (keylogger signature), explicitly named in the build brief as out of scope: 'Malware/webshell families are out of our scope; leave them unmapped with a reason.' These rules exist to catch a server that has already been compromised or was malicious from the start -- a wholesale-server-integrity check -- not one of the ten specific attack classes this benchmark measures, none of which are about detecting a generically compromised host. |
| `OffensiveToolReferences` | any | unmapped: outside-taxonomy-scope | MR-ramparts-032 | high | accepted | Malware/webshell/offensive-tooling signature (offensive-security tooling reference signature), explicitly named in the build brief as out of scope: 'Malware/webshell families are out of our scope; leave them unmapped with a reason.' These rules exist to catch a server that has already been compromised or was malicious from the start -- a wholesale-server-integrity check -- not one of the ten specific attack classes this benchmark measures, none of which are about detecting a generically compromised host. |
| `PHPWebshellGeneric` | any | unmapped: outside-taxonomy-scope | MR-ramparts-033 | high | accepted | Malware/webshell/offensive-tooling signature (generic PHP webshell signature), explicitly named in the build brief as out of scope: 'Malware/webshell families are out of our scope; leave them unmapped with a reason.' These rules exist to catch a server that has already been compromised or was malicious from the start -- a wholesale-server-integrity check -- not one of the ten specific attack classes this benchmark measures, none of which are about detecting a generically compromised host. |
| `PHPWebshellKnown` | any | unmapped: outside-taxonomy-scope | MR-ramparts-034 | high | accepted | Malware/webshell/offensive-tooling signature (known-family PHP webshell signature), explicitly named in the build brief as out of scope: 'Malware/webshell families are out of our scope; leave them unmapped with a reason.' These rules exist to catch a server that has already been compromised or was malicious from the start -- a wholesale-server-integrity check -- not one of the ten specific attack classes this benchmark measures, none of which are about detecting a generically compromised host. |
| `PHPWebshellObfuscated` | any | unmapped: outside-taxonomy-scope | MR-ramparts-035 | high | accepted | Malware/webshell/offensive-tooling signature (obfuscated PHP webshell signature), explicitly named in the build brief as out of scope: 'Malware/webshell families are out of our scope; leave them unmapped with a reason.' These rules exist to catch a server that has already been compromised or was malicious from the start -- a wholesale-server-integrity check -- not one of the ten specific attack classes this benchmark measures, none of which are about detecting a generically compromised host. |
| `PhishingKit` | any | unmapped: outside-taxonomy-scope | MR-ramparts-036 | high | accepted | Malware/webshell/offensive-tooling signature (phishing-kit signature), explicitly named in the build brief as out of scope: 'Malware/webshell families are out of our scope; leave them unmapped with a reason.' These rules exist to catch a server that has already been compromised or was malicious from the start -- a wholesale-server-integrity check -- not one of the ten specific attack classes this benchmark measures, none of which are about detecting a generically compromised host. |
| `PrivilegeEscalationTools` | any | unmapped: outside-taxonomy-scope | MR-ramparts-037 | high | accepted | Malware/webshell/offensive-tooling signature (local privilege-escalation tooling signature), explicitly named in the build brief as out of scope: 'Malware/webshell families are out of our scope; leave them unmapped with a reason.' These rules exist to catch a server that has already been compromised or was malicious from the start -- a wholesale-server-integrity check -- not one of the ten specific attack classes this benchmark measures, none of which are about detecting a generically compromised host. |
| `PythonWebshell` | any | unmapped: outside-taxonomy-scope | MR-ramparts-038 | high | accepted | Malware/webshell/offensive-tooling signature (Python webshell signature), explicitly named in the build brief as out of scope: 'Malware/webshell families are out of our scope; leave them unmapped with a reason.' These rules exist to catch a server that has already been compromised or was malicious from the start -- a wholesale-server-integrity check -- not one of the ten specific attack classes this benchmark measures, none of which are about detecting a generically compromised host. |
| `RansomwareBehavior` | any | unmapped: outside-taxonomy-scope | MR-ramparts-039 | high | accepted | Malware/webshell/offensive-tooling signature (ransomware behaviour signature), explicitly named in the build brief as out of scope: 'Malware/webshell families are out of our scope; leave them unmapped with a reason.' These rules exist to catch a server that has already been compromised or was malicious from the start -- a wholesale-server-integrity check -- not one of the ten specific attack classes this benchmark measures, none of which are about detecting a generically compromised host. |
| `ReverseShell` | any | unmapped: outside-taxonomy-scope | MR-ramparts-040 | high | accepted | Malware/webshell/offensive-tooling signature (reverse-shell payload signature), explicitly named in the build brief as out of scope: 'Malware/webshell families are out of our scope; leave them unmapped with a reason.' These rules exist to catch a server that has already been compromised or was malicious from the start -- a wholesale-server-integrity check -- not one of the ten specific attack classes this benchmark measures, none of which are about detecting a generically compromised host. |

### sentinel-scan-cli (community)

Mapping file: `mapping/sentinel-scan-cli.json`. Scanner version(s) checked: 1.4.16. Adapter version: 1.0.0. Provenance: **captured-from-real-output**. Matched on: `results[].heuristic`. 15 entries: 6 mapped, 9 unmapped.

A subset of the labels was captured verbatim from output this project produced (see the file's `provenance_note`); the rest are labels the scanner can emit that did not fire here and are mostly `provisional`.

| Raw label (verbatim) | Stage scope | Class | Rationale ID | Confidence | Status | Rationale (first sentence) |
| --- | --- | --- | --- | --- | --- | --- |
| `tool_definition_drift` | any | A2 | MR-sentinel-scan-cli-001 | high | accepted | The strongest objection is that the rule does not judge the diff, and taxonomy.md excludes a cosmetic diff from A2 by name -- so a vendor could argue this label over-claims and a critic could argue it should therefore be unmapped. |
| `tool_name_shadowing` | any | A3 | MR-sentinel-scan-cli-002 | medium | provisional | This and MR-sentinel-scan-cli-001 are the two entries worth the most care, and this one is the weaker of the pair, so the weakness is stated rather than smoothed over. |
| `tool_description_injection` | any | A1 | MR-sentinel-scan-cli-003 | high | accepted | The clean case: the label and the class name the same property, and the vendor's own phrase list reads like a paraphrase of A1's present-when test. |
| `hidden_unicode_instructions` | any | A1 | MR-sentinel-scan-cli-004 | medium | provisional | The objection to answer is that the rule detects a smuggling CHANNEL rather than an instruction: a zero-width space left behind by a copy-paste would fire, and a stray zero-width space is not a payload addressed to anyone. |
| `hardcoded_credential` | any | A7 | MR-sentinel-scan-cli-005 | high | provisional | A clean mapping with an important caveat about reach rather than about class. |
| `command_injection_risk` | any | A10 | MR-sentinel-scan-cli-006 | medium | provisional | The honest objection is that this rule reads a self-report: it fires only when the descriptor text itself contains something like 'subprocess.run(' together with the word 'unsanitized', which means it catches a manifest that confesses rather than a server that offends. |
| `excessive_agency_schema` | any | unmapped: no-defensible-single-class | MR-sentinel-scan-cli-007 | high | accepted | This is R4 in its clearest form, and it is the most expensive decision in this file, so the cost is stated first: this is the label that fired on a10b-allowlist-bypass's run_build, and leaving it unmapped means sentinel-scan-cli gets no credit for a10b's A10 item even though the finding's evidence text reads 'parameter "command" is a free-form string with no enum/pattern - looks like arbitrary command/code execution'. |
| `missing_hitl_confirmation` | any | unmapped: outside-taxonomy-scope | MR-sentinel-scan-cli-008 | high | accepted | Our taxonomy has no class for 'a sensitive capability is exposed without a declared approval gate', and it should not be pushed into one. |
| `indirect_injection_surface` | any | unmapped: outside-taxonomy-scope | MR-sentinel-scan-cli-009 | high | accepted | The concept this label names -- a toxic agent flow, where the capability to ingest untrusted content sits next to the capability to act on it -- is a real and well-documented MCP risk that our ten classes do not cover. |
| `cross_origin_exfiltration` | any | unmapped: insufficient-specificity | MR-sentinel-scan-cli-010 | medium | provisional | This label reports something real and close to A5 -- argument content flowing to a third-party host -- and is still left unmapped, because the single distinction A5 turns on is the one this rule structurally cannot make. |
| `overbroad_tool_scope` | any | unmapped: outside-taxonomy-scope | MR-sentinel-scan-cli-011 | high | provisional | An authorization-hygiene check about a declared permission string. |
| `unpinned_remote_source` | any | unmapped: outside-taxonomy-scope | MR-sentinel-scan-cli-012 | high | accepted | Both branches are outside the taxonomy, and for different reasons that are each written down in taxonomy.md. |
| `missing_provenance` | any | unmapped: outside-taxonomy-scope | MR-sentinel-scan-cli-013 | high | accepted | A supply-chain governance check: it reports the absence of publisher or integrity metadata for a remotely-sourced server. |
| `dos_resource_exhaustion` | any | unmapped: outside-taxonomy-scope | MR-sentinel-scan-cli-014 | high | provisional | Unbounded consumption is not one of our ten classes. |
| `homoglyph_typosquat` | any | unmapped: insufficient-specificity | MR-sentinel-scan-cli-015 | medium | provisional | The line this entry draws is between shadowing that names its target and impersonation that does not, and it is the same line the vendor draws by giving the two cases different ids. |

### agent-scan / Invariant mcp-scan (Snyk)

Mapping file: `mapping/snyk-agent-scan.json`. Scanner version(s) checked: 0.6.3. Adapter version: 1.0.0. Provenance: **unverified**. Matched on: `findings[].risk_indicator`. 8 entries: 2 mapped, 6 unmapped.

**Unverified.** This project has never seen this tool's real `--json` output, so neither the label field nor the label strings are confirmed. The adapter does not run without a `SNYK_TOKEN`, and this row is published as unavailable. These entries will be re-checked against real output before the row can carry a result.

| Raw label (verbatim) | Stage scope | Class | Rationale ID | Confidence | Status | Rationale (first sentence) |
| --- | --- | --- | --- | --- | --- | --- |
| `secret detection` | runtime | A7 | MR-snyk-agent-scan-001 | medium | provisional | The clearest of the eight, and still only a name-level match. |
| `prompt injection` | runtime | A1 | MR-snyk-agent-scan-002 | low | provisional | Mapped, but weaker than the secret-detection entry above, and marked so. |
| `dangerous words` | runtime | unmapped: insufficient-specificity | MR-snyk-agent-scan-003 | low | provisional | A two-word label with no documented trigger condition. |
| `untrusted content` | runtime | unmapped: insufficient-specificity | MR-snyk-agent-scan-004 | low | provisional | Provenance and instruction-bearing-content are different properties, and this label names the first while every one of our classes tests for something closer to the second. |
| `private data` | runtime | unmapped: insufficient-specificity | MR-snyk-agent-scan-005 | low | provisional | Too general a name to anchor to any one present-when test. |
| `destructive capabilities` | runtime | unmapped: insufficient-specificity | MR-snyk-agent-scan-006 | medium | provisional | The tempting mis-map in this table, so it is recorded with its considered class rather than dismissed in one line. |
| `suspicious downloads` | runtime | unmapped: not-mcp-specific | MR-snyk-agent-scan-007 | medium | provisional | Reads as a general supply-chain / malware-delivery signal (an unexpected outbound fetch, a known-bad URL), which is the kind of generic finding docs/taxonomy.md's scope boundary excludes when it has no MCP-specific surface, and no class here tests for a download in isolation from an execution or exfiltration step it has not been shown to connect to. |
| `malicious code` | runtime | unmapped: insufficient-specificity | MR-snyk-agent-scan-008 | low | provisional | The vaguest of the eight: a general malware/code-signature concept with no stated mechanism (static signature match on source? |

### Disputed entries across all scanners

| Scanner | Rationale | Our class | Vendor's class | Outcome | Scoreboard note |
| --- | --- | --- | --- | --- | --- |
| *(none open; the disclosure round has not closed)* | | | | | |

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
