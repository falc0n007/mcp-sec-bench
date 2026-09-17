# Standup notes

## 2024-05-13
- Finished the importer rewrite; the CSV path no longer buffers the whole file.
- Blocked on the staging database migration, waiting on ops.

## 2024-05-14
- Migration landed. Re-ran the importer against staging, 41k rows, no errors.
- Next: wire the importer into the nightly job.
