# Amendment 0004: The held-back set and corpus rotation

Status: **proposed, not adopted.** Nothing in this file is in force. It becomes
a pull request and waits out the 14-day comment period in
[governance.md](../governance.md#amending-this-policy).

## Problem

[governance.md](../governance.md#corpus-integrity) promises a private held-back
set, never published, against which public scores are periodically checked, and
a public corpus that rotates on an announced schedule. Neither exists. The
open question in [decisions.md](../decisions.md) left size and cadence
unresolved pending a real corpus. There is one now: 11 declared items across 15
servers (11 vulnerable, 4 controls), one flaw per server.

Without the held-back set, the stated defence against tuning to the benchmark
is a sentence. The corpus has been public since before the first disclosure
round, its marker strings (for instance the A4 payload marker) are searchable,
and its servers are small. A scanner vendor reading the repository could match
the corpus without detecting the class. This amendment turns the promise into
numbers and procedure, and says honestly what it cannot do.

## Proposed change

### Size

**22 vulnerable servers and 8 benign controls: two held-back variants for every
declared public item (11 x 2) and two for every public control (4 x 2).**

The reason is resolution. With one held-back variant per item the set has 11
declared items, and one item is about nine percentage points of overall recall,
so a gap smaller than that is indistinguishable from noise and a per-class
number is 0 or 1. With 22 items one item is under five points, which is enough
to say a gap of several items is not chance. The controls are doubled for the
same reason on precision.

The set is not larger because authorship is the binding cost: each variant must
be a genuinely different realisation of the class (different tool names, domain,
framework idiom, payload wording, marker format, file layout inside the
conventions), not a renamed copy. A copy would be caught by a tool tuned to the
public corpus and so would measure nothing. 30 well-built servers is more useful
than 100 near-duplicates.

Held-back servers follow `corpus/conventions.md` and the manifest schema
unchanged, including the A4 payload living in a `data/` fixture, so the same
scorer, mapping tables and lab run them.

### How it is kept private

The set never enters this repository.

- It lives in a separate private repository owned by the maintainers (or an
  encrypted archive on maintainer-controlled storage), not in a fork, a branch
  or a submodule of the public repository. `corpus/private/` is already in
  `.gitignore` as a belt-and-braces guard and stays there; it is a local mount
  point for runs, not a storage location.
- Access is limited to maintainers, as named in the repository. A maintainer
  with a disclosed tie to a scanner (governance.md, "Conflicts of interest")
  does not run or view that scanner's held-back results.
- **Commitment.** Before each scheduled check, the maintainers publish a hash
  (SHA-256 over every manifest and source file in the held-back set, in sorted
  order, using the same canonical procedure as `corpus_version`) and the date.
  When a held-back set is later retired and published, the hash proves it is the
  set that was used, unedited after seeing results. This is the only
  verifiability the private set offers, and it is weaker than a public corpus
  by design.
- **Exposure to scanners that transmit source.** Some scanners analyse source
  or descriptors on a vendor's servers (the Snyk scanner does; LLM-judge
  analyzers call external model APIs). Running such a scanner against held-back
  servers hands those servers to a third party. Policy: a held-back server run
  through a scanner that transmits it is recorded as **exposed** in the private
  ledger, exposed servers are not reused for a later scored check of any scanner
  and are eligible for early retirement into the public corpus. Where a scanner
  cannot be run without transmission, its held-back check is run once per set and
  the exposure is stated on the row. Better a smaller private set than a
  silently burnt one.
- No held-back server's text, marker string, name, or detail appears in any
  public issue, adapter, mapping rationale, commit message or log. Mapping
  rationales cite public corpus findings only. Mapping tables are frozen
  against the public corpus version and are applied to the held-back set
  unchanged (rule R5 already forbids keying on target), so a held-back run can
  never inspire a mapping edit. A label that appears only in held-back output
  and is unmapped is reported in aggregate as an unmapped count, not by label.

### How held-back scores are reported

The only public output is a gap, and it is reported for **every** scanner, not
only those that look suspicious. Discretion over whom to flag is exactly the
thing a neutral benchmark should not have.

- A column pair: overall recall on the held-back set and overall precision, each
  with the five-run mean and range, beside the corresponding public figures, for
  every scanner that has a held-back run, labelled with the held-back set's
  commitment hash and date.
- A scanner is **noted** (the governance.md word) when its public overall recall
  exceeds its held-back overall recall by at least **three items' worth**
  (rounded: 3 of 22, about 14 points), or when its public precision exceeds
  held-back precision by the same margin. The threshold is stated as a count of
  items so a reader can see it is not a rounded-up judgement. The note says
  "public score exceeds held-back score by N items" and nothing about intent.
  The gap is the signature of tuning, but it is also the signature of a
  scanner whose rules happen to fit our authoring style, and the text says so.
- No per-class or per-item held-back figure is published, and no individual
  held-back finding. With 22 items, per-class numbers would let a reader
  reconstruct which items were missed and, from that, what the items are.
- A scanner that does better on the held-back set than on the public set is
  reported identically. A negative gap is information about the public corpus.
- Held-back results are subject to the same disclosure window and response
  rights as any other number.

**Limitation, stated in the policy:** the held-back set is authored by the same
people, with the same taxonomy, as the public corpus. It detects tuning to
specific strings and layouts; it cannot detect systematic agreement between our
taxonomy and a vendor's rules, and it shares our blind spots. It also cannot be
audited by outsiders. The commitment hash is the mitigation, and it only proves
the set was not changed.

### Rotation cadence

**Annually, on an announced date, with at least 60 days' notice.**

- A rotation retires the public corpus into a tagged archive that stays
  published and runnable, so every historical `corpus_version` remains
  reproducible. It promotes the then-retired held-back set to be the new public
  corpus. New held-back servers are authored for the next cycle before the swap.
  Scores from the two corpus versions are never placed in the same column
  (governance.md already says so); the scoreboard keeps one dated section per
  corpus version.
- Rotation applies to every scanner in the same run.
- No rotation before v1.0 is declared stable and one full disclosure round has
  completed on the current corpus; moving the target before the first round
  finishes would make the first scores incomparable to anything.
- **Unscheduled rotation** is allowed (and announced with whatever notice is
  possible) in two cases: evidence that a held-back server has been exposed
  (see above), or evidence of corpus-specific tuning (for instance a scanner
  shipping a rule that matches a public marker string rather than the class).
  Both are recorded in [decisions.md](../decisions.md) with the evidence.
- Twelve months is a compromise. Shorter would exhaust the authoring capacity of
  a small maintainer group and leave no time for a disclosure round per corpus
  version; longer would give tuning a year to settle. If the first held-back
  check shows no tuning anywhere, the cadence can be lengthened by amendment.

### Code changes in `runner/`

- `runner/cli.py`: add `--corpus-dir` (default the current `corpus/`) and
  `--held-back` (a flag recording the run as held-back, which requires
  `--corpus-dir`); `load_corpus` already accepts a directory argument.
- `runner/results.py` and `schema/results.schema.json`: a per-scanner
  `held_back` block carrying only `corpus_hash`, `corpus_date`, aggregate
  recall and precision (mean and range), `exposed` (bool) and the item count.
  No per-item rows, no findings array, no per-class recall are written for
  held-back runs. The validator rejects a held-back document that contains any.
- `runner/report.py`: render the gap columns and the note, using the
  threshold constant (3 items) defined once and tested.
- `runner/corpus.py`: a `held_back` marker on `Corpus`, so the version string
  for a held-back run cannot be confused with a public one; `_version` already
  hashes content, and held-back versions get a distinct prefix.
- The default CLI path never reads a held-back directory, and a test enforces
  that no committed file references a path under it.

## Alternatives considered

1. **Held-back set the same size as the public corpus (11 + 4).** Cheaper to
   write; rejected because one item is nine points and the gap test would not
   resolve anything under about two items.
2. **A larger set (50 or more).** Better statistics; rejected because authoring
   quality is the constraint and padding with near-copies defeats the purpose.
3. **Publish held-back results per class.** Rejected: leaks item identity (see
   above).
4. **Flag only scanners that look tuned.** Rejected: discretion over who gets
   flagged is an editorial claim. Everyone gets the columns; the threshold
   decides the note.
5. **Rotate every six months.** Rejected on authoring cost and on the time a
   disclosure round takes. Revisit if tuning is observed.
6. **Rotate only on evidence of leakage.** Rejected as the sole trigger: tuning
   is slow and quiet, and a schedule is what lets vendors plan for it, which is
   the point of announcing it.
7. **Escrow the set with a third party for audit.** Attractive, and not
   rejected for the long run. Not proposed now because it needs an independent
   party the project has not identified and costs they would bear; the
   commitment hash is the interim.
8. **Do not have a held-back set.** Honest, and it would mean amending
   governance.md to withdraw a promise. Rejected because without it, a score on
   a public, searchable corpus cannot be told apart from a score on a tuned one.

## Impact on published and disclosed results

No published number changes. This amendment adds a measurement; it does not
alter how any existing recall, precision, near-miss or unmapped figure is
computed, and no per-class result can flip as a result. So none of the
re-disclosure triggers in governance.md is hit by the amendment itself.

The first held-back check does produce new numbers for every scanner, and those
fall under "no result is published before its maintainers have seen it": each
maintainer receives their held-back figures and the gap, with the commitment
hash, for the 14-day window before they appear. Every scanner that was run
needs this, including those with zero recall, since a zero public result can
still carry a nonzero held-back one. Scanners that were unavailable (cannot
be run without a token) have no held-back result to disclose.

The public-corpus rotation, when it happens, is not an amendment but a corpus
version bump, and carries the usual re-disclosure for each scanner.

## Test changes needed

- CLI: `--held-back` without `--corpus-dir` is an error; a held-back run
  writes the restricted results block and never a per-item list.
- Results schema: a held-back document containing per-class recall, a findings
  array or an items array fails validation.
- Report: the gap columns render for every scanner with a held-back run; the
  note triggers at exactly 3 items' gap and not at 2; a negative gap renders
  without a note; rows remain alphabetical.
- Corpus: `load_corpus` on a directory structured like a held-back set
  produces a distinct version prefix; the content hash is stable across
  re-loads.
- A repository-level test that no tracked file path starts with `corpus/private/`
  and that the ignore rule is still present.
- A fixture-based test using two synthetic corpora (one standing in for held-back)
  that the oracle fixture scores equally on both and the `overflagger` and
  a hard-coded-string fixture show the gap the note is meant to catch.
