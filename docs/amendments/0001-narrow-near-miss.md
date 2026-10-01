# Amendment 0001: Narrow the near-miss counter

Status: **proposed, not adopted.** Nothing in this file is in force. It becomes
a pull request, and then waits out the 14-day comment period in
[governance.md](../governance.md#amending-this-policy). Until it merges,
[scoring.md](../scoring.md) and `runner/scoring.py` mean what they say today.

## Problem

[scoring.md](../scoring.md) defines a near miss as a mapped finding on the right
server, wrong class, where the server declares something. That definition counts
every wrong class on every vulnerable server. A scanner that reports all ten
classes on every server earns a near miss on almost every vulnerable server in
the corpus, and the `overflagger` fixture demonstrates exactly that. The counter
rewards indiscriminate reporting, and its name invites the reading "almost
right".

The current mitigation is editorial: never publish `near_miss` without the
false-positive count, never say "almost right". That is a rule about how we
write, not about what the number means, and a vendor quoting the column on its
own is not bound by it. The open question in
[decisions.md](../decisions.md) asks for the definition to be narrowed so the
counter means what it says.

## Candidates, tested against the data model

Both candidates come from the open question. Neither was evaluated against the
runner before it was written down, so this section does that.

### Candidate A: localise the finding to the declared flaw's file

Does the finding model carry a file location for every scanner? **No.**
`RawFinding.file` is optional, and what adapters put in it differs by what the
scanner can see:

- A source-directory scanner reports real paths under the server directory.
  Here the field is usable.
- A live-endpoint scanner has no file. Its adapters set `server_id` and leave
  `file` as `None`, or construct a descriptive hint that is not a path.
- `sentinel-scan-cli` is a live-endpoint scanner whose adapter records `file` as
  the path of the manifest the *adapter generated* from `tools/list`, not a path
  in the corpus. A localisation rule would see a file that is neither the
  declared file nor under the server directory, and would discard every one of
  its near misses. The scanner would be penalised, in a metric, for a property of
  our adapter.

There is a second problem that holds even where paths exist. Every declared item
in the corpus has `location.file == "server.py"`, one entry module per server.
"Localise to the declared flaw's file" therefore reduces to "the finding names
the server's entry module", which is the same information as "the finding is on
the right server" plus an extension check. It would exclude nothing the
overflagger does, since the overflagger's findings can name `server.py` as
easily as anything else. Localising by line (`line_hint` exists in manifests)
would be meaningful, but `line` is `None` for most adapters and line numbers are
fragile across corpus edits.

Candidate A cannot be applied uniformly, penalises runtime scanners for the
absence of a field they cannot populate, and where it can be applied it filters
nothing. **Rejected.**

### Candidate B: require selectivity on that server

Selectivity needs only facts the scorer already holds: the collapsed set of
mapped `(server, class)` keys for the run. It works identically for static and
runtime scanners, needs no new field in `RawFinding`, and does not depend on
adapter behaviour. Its weakness is that it speaks about the scanner's behaviour
on a server, not about where in the server the finding sits. That is fine: the
claim the name makes is "this scanner was close on this server", and
selectivity is a direct test of that claim.

## Proposed change

**Recommendation: Candidate B, with a strict definition.**

### Definition text (replaces the Near miss row and the "A known weakness"
subsection of [scoring.md](../scoring.md))

> | **Near miss** | A mapped finding on the right server, wrong class, where that server declares some class **and** the scanner reported exactly one distinct class on that server in that run, counting every mapped class other than tolerated and not-applicable ones. Scored as a false positive on the reported class, logged in its own counter, earning no credit. A scanner that reports two or more distinct classes on a server has not been selective there, and its wrong-class findings on that server are ordinary false positives. The declared class is scored by the ordinary rules. An item has exactly one outcome, so a near miss never *forces* one. |

Replacement for the weakness subsection:

> #### What the near-miss counter does and does not measure
>
> A near miss records that a scanner, having committed to a single class on a
> server that carries a planted flaw, named the wrong one. It is a count of
> confident misclassifications. It is not partial credit, it does not move
> recall or precision, and it is not evidence of near-competence: a scanner that
> names one wrong class on every server earns one on each. For that reason
> `near_miss` is still never published without the false-positive count beside
> it, and no scoreboard text describes a near miss as "almost right".

The residual weakness is stated in the text on purpose. A scanner that reports
one fixed wrong class everywhere still accumulates near misses. The amendment
removes the cheap route (report everything and collect the counter as a side
effect) but does not make the counter a quality signal. The pairing rule with
false positives stays.

### Code change in `runner/`

Only `runner/scoring.py` changes behaviour.

- In `score_run`, before the loop over `placed` keys that are not declared,
  compute `reported_by_server: dict[str, set[str]]` from the keys of `placed`,
  leaving out any key for which `corpus.is_tolerated` or
  `corpus.is_not_applicable` is true. Declared keys are included, so a scanner
  that found the declared class and also reported a wrong one has two classes on
  that server and the wrong one is not a near miss.
- In that loop's false-positive branch, the `elif corpus.declares_anything(...)`
  becomes `elif corpus.declares_anything(server_id) and reported_by_server.get(server_id) == {cls}`.
  The outcome stays `FALSE_POSITIVE`. `near_miss_count` increments only under the
  narrowed condition, and the `note` text changes to say "near miss: sole class
  reported on this server".
- A non-near-miss false positive on a declaring server gets a plain note such as
  "false positive: one of several classes reported on this server", so the item
  list stays self-explanatory.
- `RunMetrics.near_miss_count`, `ScannerReport.near_miss_mean`, `aggregate.py`
  (`near_miss_mean`), `results.py` and `report.py` are unchanged. The results
  schema is unchanged; only the meaning of an existing field changes, and
  `results.schema.json` field description should be updated accordingly.
- The function-level docstring and the comment block in the false-positive
  branch are rewritten to match the new definition.

No change to `mapping.py`, `corpus.py` or `models.py`.

## Alternatives considered

1. **Candidate A (file localisation).** Rejected above: not populated for
   runtime scanners, populated with an adapter-generated path for at least one,
   and degenerate on a one-module-per-server corpus.
2. **Selectivity with a looser bound (at most two classes).** Rejected. Any
   threshold above one is arbitrary, and the two-class bound still lets a
   scanner emit two wrong classes per server for a doubled counter. "Exactly
   one" has a plain reading and no tunable number to argue about.
3. **Corpus-wide selectivity (the scanner reports fewer than N classes in
   total).** Rejected. It makes one server's classification depend on what
   happened on unrelated servers, which is hard to explain in a dispute.
4. **Delete the counter.** Seriously considered. It carries almost no
   information about a scanner's quality, and the pairing rule exists only to
   limit damage. Rejected for now because the original reason for it still
   holds: right-server-wrong-class is a real and interesting failure mode in a
   category whose taxonomies are mutually disjoint, and the column preserves
   information without moving headline numbers. If the narrowed counter is still
   routinely zero or uninformative after the first full round, deletion should
   be proposed then.
5. **Leave it, rely on the pairing rule.** Rejected as the long-term position.
   The pairing rule binds us, not anyone who quotes the column.

## Impact on published results

No results have been published, so nothing is retroactively changed. Under
[governance.md](../governance.md#amending-this-policy), the rule that matters is
that a changed published number triggers a published correction notice for affected
scanners.

- The change can only lower a near-miss count, never raise it, and affects no
  true-positive, false-positive, false-negative, recall or precision figure. It
  would not move any recall or precision number for any scanner.
- Only a scanner whose near-miss count is currently nonzero can be affected.
  Among the scanners run so far that is `sentinel-scan-cli` only; whether its
  count actually moves depends on how many classes it reports on the servers
  where it was previously credited with one, which has to be recomputed from
  its raw findings with the amended scorer rather than assumed.
- The material-change definition in governance.md (recall moves by 10 points, a
  per-class flip, a mapping change) does not literally cover a near-miss
  change. The amendment's own "no retroactive application" clause does, since a
  published number would change. Recommendation: treat it as covered, and
  publish a correction notice for the affected scanner alongside the amended
  scorer. If the amendment merges before the first publication, there is nothing
  to correct beyond describing the definition in the published methodology.
- Fixtures: `fixture-overflagger` would drop to zero near misses. `fixture-near-miss`
  reports one wrong class per server and keeps its near misses.

## Test changes needed

In `tests/test_scoring.py`:

- The overflagger test (the one asserting `m.near_miss_count > 0`, "every wrong
  class on a vulnerable server") becomes `== 0`, with a comment pointing at this
  amendment. It remains the regression test for the inflation.
- `test_fixture_near_miss_earns_no_credit_and_populates_the_counter` should keep
  passing unchanged (`near_miss_count == false_positives`, notes match count);
  it is the positive control for the narrowed rule.
- New: a scanner reporting one wrong class on a declaring server scores one near
  miss.
- New: a scanner reporting two wrong classes on a declaring server scores zero.
- New: a scanner reporting the declared class plus one wrong class scores zero
  near misses, a true positive, and a false positive.
- New: a tolerated class reported alongside one wrong class does not defeat
  selectivity, and neither does a not-applicable class.
- Worked example 1 in scoring.md and its test (`...fp_plus_fn_plus_near_miss`)
  still hold, because that scenario reports a single wrong class.
- The aggregation test over `near_miss_mean` is unaffected.
