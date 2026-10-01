# Amendments

Proposals to change how the benchmark measures, written down before anyone
decides them. Nothing in this directory is in force. A file here is a draft of a
pull request, kept in the open so the reasoning is reviewable and the open
questions in [decisions.md](../decisions.md) have a concrete answer to argue
with.

## Process

[governance.md](../governance.md#amending-this-policy) sets the rules, and they
are not repeated here beyond what a reader needs:

1. A pull request states the change and the reasoning. These files are that
   statement, and the pull request carries the doc and code changes they
   describe.
2. A minimum 14-day public comment period before merge.
3. On merge, a dated entry in decisions.md, and the matching open question is
   removed.
4. No retroactive application. Published results keep the rules they were
   produced under; if an amendment would change a published number, the affected
   scanners get a published correction notice when the new number is republished,
   with the superseded number left visible.

Taxonomy changes additionally bump the corpus version. The no-scanner rule
cannot be amended at all.

Each proposal follows one shape: Status, Problem, Proposed change (the new
definition text, and the code change by function name), Alternatives considered,
Impact on published results, and Test changes. Files are numbered
in the order proposed and never renumbered. A proposal that is adopted, rejected
or withdrawn has its Status line updated with the date and a link to the
decision, and the file stays.

Concrete per-scanner figures do not appear in these files. They describe impact
qualitatively, because the numbers belong to the published scoreboard, not to a
design document.

## Index

| File | Proposal | Status |
| --- | --- | --- |
| [0001-narrow-near-miss.md](0001-narrow-near-miss.md) | Count a near miss only when the scanner reported exactly one class on that server; file localisation rejected because not every adapter carries a usable path. | proposed |
| [0002-maturity-column.md](0002-maturity-column.md) | A separate, descriptive provenance table (maintainer type, first release, latest release, release count, licence); no grade, no popularity metrics, no effect on inclusion. | proposed |
| [0003-a1-a4-data-file-route.md](0003-a1-a4-data-file-route.md) | Let a mapping entry be scoped by reported file location (data-file or source) as well as stage, so a legitimate A4 data-file detection is not scored as A1. | proposed |
| [0004-held-back-set-and-rotation.md](0004-held-back-set-and-rotation.md) | A private held-back set of 22 vulnerable and 8 benign servers, reported only as a gap for every scanner, and annual announced rotation. | proposed |
