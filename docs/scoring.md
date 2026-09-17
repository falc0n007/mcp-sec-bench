# Scoring rules

Status: **locked for v1.** These rules were written before any results existed.
That ordering is the point: see [governance.md](governance.md).

Changes follow the amendment process and never apply retroactively to published
results without re-disclosure.

## The unit of judgment

The atom of scoring is an **item**: a `(server, class)` pair.

A server's ground-truth manifest declares which classes are present on it. The
benchmark's full item set is every declared `(server, class)` pair across the
corpus. Everything below is counted in items, not in findings — a scanner that
reports the same flaw six times has found one item.

## Normalization

Scanners emit findings in their own vocabularies. The mapping layer
(Phase 2) converts each finding to a `(server, class)` pair, or to `unmapped`.

- Mapping is decided per scanner-label, documented with a rationale, and frozen
  before a scoring run.
- A finding that cannot be mapped to a class in this taxonomy is recorded as
  `unmapped` and counts as **neither** a true positive nor a false positive.
  It appears in the results as its own column.

`unmapped` exists because the taxonomy is a v1 draft against a young category.
Penalising a scanner for finding something real that we did not think to define
would measure our taxonomy, not their tool. A high `unmapped` count is a signal
to review the taxonomy, and is reported as such.

## Outcomes

For each item, and each mapped finding:

| Outcome | Condition |
| --- | --- |
| **True positive** | A mapped finding whose `(server, class)` matches a declared item. |
| **False negative** | A declared item with no matching mapped finding. |
| **False positive** | A mapped finding whose `(server, class)` is not declared and is not tolerated. |
| **Near miss** | A mapped finding on the right server, wrong class, where that server *does* declare some class. Scored as a false positive on the reported class, logged in its own counter, and earning no credit. The declared class is then scored by the ordinary rules: a false negative if nothing found it, a true positive if something did. An item has exactly one outcome, so a near miss never *forces* one. |
| **Tolerated** | A mapped finding matching an entry in the server's tolerated set. Neither TP nor FP. |
| **Unmapped** | A finding the mapping layer cannot place. Neither TP nor FP. |
| **Not applicable** | A class the server cannot structurally exhibit. Excluded from that server's denominator entirely. |

Duplicate findings mapping to the same item collapse to one outcome.

### Partial credit: none

A finding earns credit only if it names the **right server and the right class**.

Near misses receive no credit in recall or precision, and are reported in a
dedicated `near_miss` column so the information is visible without moving the
headline numbers. The rationale: a benchmark whose central finding is that
scanner taxonomies are mutually disjoint cannot also award credit for
approximately-right classification without measuring its own mapping generosity
instead of the tools. Deciding this before results exist is what makes it
defensible.

#### A known weakness in this counter

As defined above, *any* wrong class on a server that declares something counts
as a near miss. That makes the counter trivially inflatable: a scanner that
reports every class on every server earns a near miss on almost every server in
the corpus. Measured against the `overflagger` fixture, which does exactly
that, the rule yields 99 near misses alongside 137 false positives and a
precision of 0.07.

So a large near-miss count is **not** evidence of near-competence, and this
project will not present it as such:

- `near_miss` is never published without the false-positive count beside it.
  Read together the inflation is self-evident; read alone it is misleading.
- No scoreboard text describes a near miss as "almost right".

Narrowing the definition -- requiring the finding to localise to the declared
flaw, or requiring the scanner to have been selective on that server -- would
make the counter mean what its name suggests. That is a change to a published
metric's definition, so it goes through the amendment process in
[governance.md](governance.md#amending-this-policy) rather than being decided
here. Logged as an open question in [decisions.md](decisions.md).

### Tolerated findings

A server's manifest may declare a **tolerated set**: classes a defensible
scanner might report on that server without being wrong. The benign control
carrying a high-entropy test fixture, for example, tolerates A7.

Two rules keep this from becoming a thumb on the scale:

1. The tolerated set is frozen when the corpus version is tagged, before any
   scanner runs against it.
2. Adding an entry after results exist requires a governance-logged amendment, a
   version bump of the corpus, and re-disclosure to every affected scanner.

## Metrics

Reported per scanner:

- **Recall, per class** — true positives over declared items in that class,
  excluding `n/a`. The primary number. Per-class rather than aggregate, because
  aggregate recall hides the disjointness that motivates the project.
- **Recall, overall** — across all declared items.
- **Precision, overall** — true positives over (true positives + false
  positives). Tolerated and unmapped findings are excluded from both terms.
- **Near-miss count.**
- **Unmapped count.**
- **Variance** — see below.

### No composite index

The scoreboard reports recall and precision side by side and does **not** compute
a single combined score, ranking index, or letter grade.

A composite would require weighting classes against each other, and any such
weighting is an editorial claim about which attacks matter most — exactly the
kind of judgment a neutral benchmark should not smuggle into a number that gets
screenshotted. Readers who want a single ordering can apply their own weights to
the published per-class table.

Scoreboard rows are sorted alphabetically by scanner name, not by score.

## Stages

Every scanner is scored in two stages, reported separately and combined.

| Stage | Input | Classes reachable |
| --- | --- | --- |
| **Stage 1 — static** | Source tree and packaging metadata | A1, A2, A3, A7, A8, A9, A10 |
| **Stage 2 — runtime** | A live endpoint the scanner may exercise | A1, A2, A3, A4, A5, A6 |

The metadata classes A1, A2 and A3 appear in both stages, because advertised
tool metadata is both written in the source and served by `tools/list`. Credit
from either stage counts once, and the results record which stage produced it.

A scanner that only performs static analysis is **not penalised for Stage 2**.
Its Stage 2 items are marked `not attempted`, excluded from its Stage 2
denominator, and the scoreboard says "static only" next to its name. Scoring a
static tool as having 0% runtime recall would be a category error dressed up as
a measurement.

The combined figure is reported over the union of stages the scanner attempts,
and every published combined number carries the stage coverage alongside it.

## Nondeterminism

Some scanners use LLM-as-judge analyzers and return different results run to run.

- Every scanner runs **N = 5** times minimum against a fixed corpus version.
- Results report **mean and min-max range**, never a single run.
- A scanner whose range on any per-class recall exceeds **20 percentage points**
  is flagged `high variance` on the scoreboard.
- Deterministic rule-based tools produce zero variance. That is a genuine
  finding about reproducibility, reported as such rather than treated as the
  uninteresting default.
- Run seeds, model versions where exposed, and adapter versions are recorded in
  the results JSON so a run can be reconstructed.

## Scanner configuration

- Each scanner runs in its **documented default configuration**. Defaults are
  what users get, so defaults are what we measure.
- A vendor may submit an alternative configuration via adapter pull request. If
  accepted, it is published as an **additional row**, labelled with the
  configuration, never as a replacement for the default row.
- Any configuration requiring a paid tier, a sales call, or a non-public build is
  out of scope; see the inclusion criteria in
  [governance.md](governance.md#which-scanners-are-included).

## Access friction

Scanners that cannot be run without an account are still benchmarked, and the
friction is part of the published result.

- The scoreboard carries a **`requires signup`** column.
- Any capability gated behind a token is noted per class, so a reader can tell
  whether a missed class was a detection failure or an unavailable engine.
- A scanner with a gated engine is run **twice**: once in the ungated
  configuration and once with credentials supplied, published as two rows. The
  ungated row is the default view, because it reflects what someone gets by
  running the tool as published.

## Results format

Each run produces machine-readable JSON alongside the rendered table. The schema
is a Phase 2 deliverable; these fields are required by these rules and are fixed
now:

```
corpus_version, scanner_id, scanner_version, adapter_version,
config_label, stage, run_index, requires_signup,
items[]  -> {server, class, outcome, stage_credited, finding_ref}
findings[] -> {raw_label, mapped_class, mapped_server, mapping_rationale_id}
metrics  -> {recall_per_class, recall_overall, precision_overall,
             near_miss_count, unmapped_count, variance_flag}
stage_coverage, not_attempted[]
```

`mapping_rationale_id` points into the mapping rationale document, so any
published number is traceable to the specific judgment call behind it. That
traceability is what makes the dispute process in
[governance.md](governance.md#contesting-a-result) actionable rather than
rhetorical.

## Worked examples

To remove ambiguity from the cases most likely to be contested:

1. **Right flaw, wrong class.** Scanner reports "prompt injection" on the A8
   unrestricted-file-read server; mapping layer resolves that label to A1.
   Outcome: false positive on `(A8-server, A1)`, false negative on
   `(A8-server, A8)`, near-miss count incremented. No credit.

2. **Right class, wrong server.** Scanner reports A7 on a benign control that
   does not tolerate A7. Outcome: false positive. The A7 item on the vulnerable
   server remains a false negative unless separately found.

3. **Correct find on a tolerated pattern.** Scanner reports A7 on the benign
   control carrying the test fixture hash, which tolerates A7. Outcome:
   tolerated. Precision unaffected in either direction.

4. **Novel true finding.** Scanner reports a real flaw we did not plant and did
   not define. Outcome: `unmapped`, no penalty, taxonomy review triggered.

5. **Static tool, runtime class.** A static-only scanner does not detect A6.
   Outcome: `not attempted`, excluded from its Stage 2 denominator. Not a false
   negative.

6. **Rug-pull found statically.** Scanner flags the call-count branch in source
   without ever connecting. Outcome: true positive on A2, `stage_credited:
   static`.
