# Design review, 2024-05-14

Attendees: Priya, Marcus, Wen.

Decision: keep the importer synchronous for now. The async rewrite is real work
and the current p99 is 1.2s, which nobody has complained about.

Action items:
- Marcus: add the partial index on `imports(status, created_at)`.
- Wen: write the runbook entry for a failed nightly import.
- Priya: revisit in four weeks with fresh numbers.
