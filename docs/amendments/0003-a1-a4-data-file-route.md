# Amendment 0003: Location-scoped mapping for the A1/A4 data-file case

Status: **proposed, not adopted.** Nothing in this file is in force. It becomes
a pull request and waits out the 14-day comment period in
[governance.md](../governance.md#amending-this-policy). Because it changes how
labels are mapped, it also needs the corpus-version and published-correction-notice steps
described under Impact.

## Problem

[taxonomy.md](../taxonomy.md) says a scanner that walks non-source data files
and flags the A4 poisoned fixture **does** earn A4 credit. The mapping layer
cannot deliver that. Such a finding arrives in the static stage, with a
generic injection label, and under rule R3 in
[mapping-rationale.md](../mapping-rationale.md) the only way to give a label two
mappings is to split on stage. Static injection labels resolve to A1. So a
legitimate detection of the A4 fixture is scored as:

- a false positive on `(a04-response-injection, A1)`, since that server does not
  declare A1,
- a near miss, because the server declares something,
- and a false negative on `(a04-response-injection, A4)`, unless the runtime
  stage separately finds it.

(The open question in decisions.md describes the false positive as landing on
a01. The finding resolves to the server whose directory contains the data file,
which is the A4 server. The conclusion is the same; the server is not.)

This is the highest-risk boundary in the taxonomy, as mapping-rationale.md
section 11 says. It is a known defect: a correct detection that the benchmark
marks wrong, which is the opposite of what a benchmark is for.

A second defect travels with it. `_stage_credited` in `runner/scoring.py`
resolves the credited stage from the item's declared surfaces, so a static
finding credited to an A4 item (surface `runtime` only) is recorded as
`runtime`. The taxonomy promises "the run record notes which stage the credit
came from". Today it would record the wrong one.

## Options

### Option 1: accept it as a documented defect

Leave the mapping as is, keep the entry in the known-defects list, and state it
beside any scanner whose static stage touches the data directory. The error is
visible (a named near miss on a named item, rule R6), the route is expected to
be rare, and no mapping rule has to be argued about.

Cost: a scanner doing something the taxonomy explicitly calls legitimate is
scored wrong, and the project keeps a promise it cannot honour. For the one
scanner type it affects, a source-directory scanner that reads `data/*.json`,
the benchmark would understate recall on a class that is hard to reach, which is
exactly where the benchmark claims to say something new.

### Option 2: location-scoped mapping entries (recommended)

Extend the R3 mechanism with a second recorded fact. R3 permits a split only on
a fact the runner records, never on finding text. A finding's reported file path
is such a fact: `RawFinding.file` is already recorded, preserved verbatim by the
adapter, and used by `ServerResolver` to resolve the server. The proposal is to
let a mapping entry be scoped by where the finding says it is, in the same
shape as `applies_to_stage`.

The key design constraint is rule R5, "map the label, never the target":
nothing in a mapping decision may reference the corpus, what the manifest
declares, or what a score would become. That excludes the obvious version of
this option, which is to read `runtime_trigger.payload_source` from the A4
manifest and route any finding whose file equals it. That would use the answer
key to decide the mapping and is rejected below. The proposal instead scopes
on a structural property of the path that exists independently of the manifest:
whether the reported file lies in the server's `data/` directory, which
[corpus/conventions.md](../../corpus/conventions.md) already reserves for
fixtures (the A4 payload "lives here, never in server.py").

### Option 3: route on finding text

Detect "response" or "tool output" in the message or evidence. Rejected before
this document was written: it makes entries unreviewable and invites exactly the
overfitting the held-back set exists to detect. Restated here so the choice list
is complete.

### Option 4: credit A1 on the A4 server as A4

Special-case the pair `(a04-response-injection, A1)` in the scorer. Rejected: it
is a corpus-specific exception in code, invisible in the mapping table, and it
rewards a scanner for naming the wrong class on that server and nothing else.

## Proposed change

**Recommendation: Option 2, with the narrow definition below, and Option 1 as
the fallback if public comment shows the location rule cannot be made
unambiguous.**

### Definition text

Addition to rule R3 in [mapping-rationale.md](../mapping-rationale.md), which
becomes "Split a label only on a fact the runner records":

> The recorded facts on which a label may be split are exactly two: the stage
> that produced the finding (`applies_to_stage`), and the location the scanner
> reported for it (`applies_to_location`), which takes the value `any` (the
> default), `data-file` or `source`. A finding is `data-file` when the server
> resolver attributed it to a server by a path component **and** the path
> beneath that server's directory begins with `data/`. A finding is `source`
> when the resolver attributed it by a path component and the path does not. A
> finding the resolver attributed by an adapter-declared `server_id` alone, or
> could not attribute, matches `any` entries only. Two entries may share a label
> only when their stage scopes or their location scopes are disjoint. There is
> still no content-based discriminator.

Addition to the A4 corpus constraint in [taxonomy.md](../taxonomy.md):

> A static finding credited this way is recorded with `stage_credited: static`,
> which is distinct from runtime credit for the same item.

Entries are opt-in per scanner and per label, justified in the mapping file's
rationale like any other. An entry is only written for a label where a scanner
has shown it reports data-file findings, with the evidence of the raw finding
cited.

### Why this passes R5

The rule keys on the label and on the scanner's own reported path. It does not
read `manifest.json`, does not name `a04-response-injection`, and would apply
identically to any server that follows the fixtures-in-`data/` convention.
Two weaker spots are stated openly: the convention itself comes from the
corpus, and a reviewer may reasonably say that is the corpus leaking in. The
answer is that the convention is documented, public, and is the thing that makes
the A4 payload not a source literal, which is already a corpus requirement. If
the held-back set ([0004](0004-held-back-set-and-rotation.md)) follows the same
convention, the rule generalises. If comment disagrees, Option 1 stands.

### Why the path-component restriction matters

Some adapters set `file` to a path that is not in the corpus at all.
`sentinel-scan-cli`'s adapter records the generated manifest it built from
`tools/list` (for example `mcp.json`), and live-endpoint scanners often record
nothing. Extending "a data file" to mean "any non-`.py` file" would send that
scanner's genuine A1 findings on tool descriptors to A4, a serious misclassification
caused by our own adapter. Requiring path-component attribution, which only
happens when the scanner reported a path beneath the server directory,
prevents it.

### Code change in `runner/`

- `mapping/schema.json`: add `applies_to_location` (enum `any`, `data-file`,
  `source`; default `any`) to an entry; entries are keyed on
  `(raw_label, applies_to_stage, applies_to_location)`.
- `runner/mapping.py`:
  - `MappingEntry` gains `applies_to_location: str = "any"`.
  - `ServerResolver.resolve` is extended (or a sibling method added) to return,
    alongside `(server_id, method)`, the path remainder beneath the matched server
    component, so `Mapper.map_finding` can classify the finding as `data-file`,
    `source` or neither. `RESOLVED_PATH` already identifies the path-component
    case.
  - `_build_index` and `MappingFile.lookup` take the location class in addition to
    the stage; lookup tries the specific location scope first, then `any`, so
    existing entries behave exactly as before. The duplicate check in
    `_build_index` rejects overlapping scopes, as it does for stages.
  - `MappingReport` records how many findings were routed by location, so the
    gap report shows it.
- `runner/scoring.py`: `_stage_credited` prefers the finding's own recorded
  stage (`RawFinding.stage`) when it is a valid stage, instead of deriving from
  the item's surfaces. For an A4 item (surface `runtime` only) credited from a
  static finding this records `static`.
- `runner/results.py`: surface `mapping_rationale_id` for location-routed
  findings already works through the existing field; no schema change beyond the
  results note.
- `tools/validate_manifests.py` is not touched; this is not a manifest change.

## Alternatives considered

Options 1, 3 and 4 above. In addition:

- **Read `payload_source` from the manifest.** Rejected as the answer-key
  approach. It is the easiest to implement and the hardest to defend.
- **Drop the A4 data-file promise from taxonomy.md.** A taxonomy narrowing,
  not a fix: it would remove the legitimate detection from scope and then score
  its detection as an error. Rejected, and it would need its own corpus bump.

## Impact on published results

No result has been published, so nothing here is retroactive. Under
[governance.md](../governance.md#amending-this-policy) and its material-change
rules, a change in mapping that affects a tool is a trigger, and per-class
results flipping between detected and missed is another.

- Affected scanners are exactly those whose raw output contains a static
  finding with an injection label attributed to a path beneath a server's
  `data/` directory. Whether any scanner run so far has such a finding is a
  mechanical check against the committed raw output with the amended mapper in
  place; this proposal does not assume the answer. Where none does, no
  published figure changes and no correction notice is owed beyond describing the rule.
- For an affected scanner, the change converts a false positive plus a near miss
  plus a false negative into a true positive on the A4 item. Recall on A4 and
  overall recall can rise, precision can rise, and the per-class A4 result can
  flip from missed to detected. A flip triggers a published correction notice.
- No other scanner's figures move, because entries default to `any`.
- The corpus version does not change (no manifest content changes); the mapping
  files are frozen against the corpus version and gain new entries, which changes
  their own version. This is a mapping change, so the new entry and its rationale
  are published with the scoreboard, and the affected maintainers can dispute
  them after publication.

## Test changes needed

- `tests/test_scoring.py`, mapping tests: a finding at
  `a04-response-injection/data/cached_feed.json` with a static injection label
  maps to A4 under a location-scoped entry and to A1 under a label with no such
  entry.
- A finding at `a04-response-injection/server.py` with the same label still
  maps to A1 (location `source`).
- A finding with only an adapter-declared `server_id` and a non-corpus file path
  such as `/work/mcp.json` never matches a `data-file` entry. This is the
  regression test for the descriptor-manifest scanner.
- A finding that names two servers' paths stays unresolved, as now.
- Loader tests: overlapping `(stage, location)` scopes for one label are
  rejected; `any` remains the default so every existing mapping file loads
  unchanged.
- Scoring: a static-stage finding credited to an A4 item records
  `stage_credited == "static"`, for a scanner attempting both stages and for a
  static-only scanner (the item is credited though its stage was not declared,
  per the existing branch, and the recorded stage is the real one).
- A near-miss regression: after routing, the A4 server shows a true positive and
  no near miss for that finding.
- A mapping-file validator test that an entry using `applies_to_location`
  carries a rationale citing the raw finding path that justified it.
