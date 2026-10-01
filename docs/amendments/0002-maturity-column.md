# Amendment 0002: Provenance fields on the scoreboard

Status: **proposed, not adopted.** Nothing in this file is in force. It becomes
a pull request and waits out the 14-day comment period in
[governance.md](../governance.md#amending-this-policy).

Named "maturity column" in the open question in
[decisions.md](../decisions.md). The name is changed here deliberately:
"maturity" is a judgment, and the proposal is to publish facts.

## Problem

Inclusion is by criteria, and that will not change. The consequence is that a
single-author repository sits in the same table as a commercial vendor's
product, and the table's columns (recall, precision, near miss) say nothing
about which is which. A reader comparing the two without that context is
misled by omission, and nothing in the current scoreboard prevents it. The
no-composite-score rule was made to avoid editorial claims inside numbers; the
absence of context is an editorial claim too, just a quieter one.

The opposite risk is real. A column that reads as "quality", "trust" or
"production readiness" would be an editorial claim, would invite disputes about
categories we cannot defend, and would turn a neutral benchmark into a
reputation system. Any proposal has to be a set of verifiable facts that a
reader cannot mistake for a grade.

## Proposed change

**Recommendation: publish a separate provenance table, built only from
objective fields, directly below the results table. Do not add a column to the
results table, do not sort by it, do not label it maturity.**

### Fields

Each field is a fact with a stated source, collected by a script and dated, not
chosen by hand:

| Field | Definition | Source |
| --- | --- | --- |
| Maintainer type | `vendor` when the scanner's repository or package is published by an organisation that sells a commercial product built around it or a parent product; `community` when it is published by an organisation or a group of people with no commercial product; `individual` when the repository has a single maintainer account. A scanner may be only one of these. | Repository owner type, package registry publisher, and the project's own README, with the citing URL recorded. |
| First public release | Date of the earliest tagged release or registry publication. | Package registry or releases page. |
| Latest release | Date and version of the release scanned. | Same. |
| Release count | Number of tagged releases or registry versions published. | Same. |
| Licence | SPDX identifier. | Repository. |

Not included, on purpose: stars, forks, download counts, contributor counts,
issue activity, "last commit" age, funding, company size, or any score. These
are popularity or activity proxies that read as quality. First release date and
release count are used in their place because they are a bounded, checkable
fact that does not shift with attention.

Release count has a known misreading (more releases looks better). The table
heading says the fields are descriptive and not ordered; the field is kept
because it tells a reader a one-release project from a long-lived one, which is
the context the open question asked for. If comment shows it misleads more than
it informs, drop it and keep the rest.

### Text that goes in scoring.md and governance.md

Addition to the scoreboard description in [scoring.md](../scoring.md), after
"Results format":

> **Provenance table.** The scoreboard carries a second table listing, for
> every scanner including unavailable ones, its maintainer type, first public
> release date, latest release scanned, release count and licence. These are
> descriptive facts about who publishes a tool and how long it has existed. They
> are not a quality rating, are not used to include or exclude any scanner, are
> not used to sort rows, and are never combined with any result. Rows remain
> alphabetical. A maintainer who believes a field is wrong may dispute it through
> the process in [governance.md](../governance.md#contesting-a-result).

Addition to "Which scanners are included" in governance.md:

> Inclusion is by the criteria above and by nothing in the provenance table.

### Code change in `runner/`

- New data file `schema/provenance.schema.json` and a checked-in
  `scanners/provenance.json` (one record per `scanner_id`, each field with a
  `source_url` and `collected_on`). The records are produced by a new
  `tools/collect_provenance.py` that reads registry and repository metadata, so
  the table is reproducible rather than hand-typed. `maintainer_type` is the one
  field that needs a human decision; it is stored with the URL that justifies it.
- `runner/models.py`: a `ScannerProvenance` dataclass; `ScannerReport` gains an
  optional `provenance: ScannerProvenance | None = None`. It is not read by
  `scoring.py` or `aggregate.py`.
- `runner/report.py`: `render_markdown` and `render_text` emit a second table
  after the results table, in the order given by `_sorted_reports` (alphabetical).
  A scanner with no provenance record renders `-`, never an omitted row. The
  footnote gains one sentence that the table is descriptive.
- `runner/results.py` and `schema/results.schema.json`: carry the provenance block
  per scanner so the published JSON matches the rendered table.

No change to scoring, mapping or the corpus.

## Alternatives considered

1. **No column; put the context in prose.** The README and a per-scanner note
   could say "single-author project". Rejected as the default because prose is
   written per scanner, which means the project decides who gets a caveat. A
   fixed table with the same fields for everyone removes that discretion.
2. **A maturity tier (for example "early", "established").** Rejected. Tiers
   are a grade, whatever they are called, and the thresholds are an editorial
   claim we would have to defend scanner by scanner.
3. **Stars, downloads, last-commit age.** Rejected as popularity and activity
   proxies. They also move without the project doing anything, which would
   make the table stale between runs.
4. **Funding or company size.** Rejected as not verifiable from public sources
   by a script, and as a statement about the vendor rather than the tool.
5. **Do nothing.** Reasonable and honest, but it leaves the misreading the open
   question identified. Not preferred.
6. **A column inside the results table.** Rejected: next to the numbers, it
   would be read as an explanation of them. A separate table keeps the facts
   adjacent without being part of the measurement.

## Impact on published results

No recall, precision, near-miss or unmapped figure changes for any scanner, and
no per-class result can flip, so none of the material-change triggers in
governance.md fires. The amendment adds information; it does not change a
published number.

Two handling points regardless:

- The `maintainer_type` classification is a statement about each maintainer.
  Each scanner's record is published with its source URL, so a maintainer who
  disagrees can dispute it after publication and the response is published
  beside it. Nobody is shown it first.
- A scanner whose maintainer type is `vendor` while an adapter was also
  submitted by that vendor is already disclosed on the row; this field is a
  separate fact and does not replace that disclosure.

## Test changes needed

- `tests/test_report.py`, or the nearest equivalent: a provenance table is
  rendered with every scanner, including unavailable ones, in alphabetical
  order, and an absent record renders `-`.
- A test that the rendering order of the results table is unchanged when
  provenance is present (the existing alphabetical-not-by-score guarantee).
- A schema test that `provenance.json` validates and that no field outside the
  list above is accepted, so a popularity metric cannot be added by accident.
- A test that `ScannerReport` without provenance still renders (existing callers
  and fixtures).
- A test that nothing in `scoring.py` or `aggregate.py` imports provenance.
