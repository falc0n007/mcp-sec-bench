# Decision log

Dated record of choices and the reasoning behind them, so the reasoning survives
the people who made it. Append; do not rewrite.

| Date | Decision | Reasoning |
| --- | --- | --- |
| 2026-09-16 | Build the benchmark, not the cross-server detector | Lower competition, higher citation potential, and a clear neutrality story. The detector would need a test corpus anyway — a smaller version of Phase 1 — so the benchmark is the better first move and the detector can follow as a separate repo. |
| 2026-09-16 | Never ship our own scanner | Competing in the measured category collapses the benchmark's value. Elevated to a binding, non-amendable rule in `governance.md`. |
| 2026-09-16 | Python-only corpus for v1 | Keeps Phase 1 finishable. TypeScript is a v2 conversation. |
| 2026-09-17 | Repo name: `mcp-sec-bench` | Short enough to type and say, and reads as a benchmark rather than a scanner. Resolves an open question from the plan. |
| 2026-09-17 | License: MIT | Maximally permissive and the lower-friction choice for a corpus and harness that people should be able to lift freely. Apache 2.0's patent grant was the alternative considered; with no novel detection technique being published here, the grant secures little that matters, and MIT's familiarity lowers the barrier to vendors vendoring the corpus into their own CI. |
| 2026-09-17 | Live-endpoint (runtime) stage ships in v1 | A4, A5, and A6 are structurally unreachable by static analysis, which is precisely what no existing comparison measures. Cutting them would make v1 another static comparison and forfeit the project's main claim to saying something new. Accepted cost: more Phase 1 corpus and lab work. |
| 2026-09-17 | No partial credit; near misses logged separately | A finding counts only if it names the right server and the right class. Awarding partial credit for right-server-wrong-class would measure the generosity of our own mapping layer rather than the tools — untenable for a project whose central finding is that scanner taxonomies are mutually disjoint. Near misses are reported in their own column so the information is preserved without moving the headline numbers. |
| 2026-09-17 | No composite score or ranking index | Any single number requires weighting attack classes against each other, which is an editorial claim about which attacks matter most. Recall and precision are published side by side, per class, and scoreboard rows sort alphabetically rather than by score. Readers who want an ordering can apply their own weights. |
| 2026-09-17 | Static-only scanners are not penalised for runtime classes | Their Stage 2 items are marked `not attempted` and excluded from the denominator. Scoring a static tool as 0% runtime recall would be a category error presented as a measurement. |
| 2026-09-17 | Unmapped findings are neither true nor false positives | The taxonomy is a v1 draft against a young category. Penalising a scanner for finding something real that we failed to define would measure our taxonomy rather than their tool. High unmapped counts are published as a signal to revise the taxonomy. |
| 2026-09-17 | Scanners measured in default configuration; vendor configs are additional rows | Defaults are what users actually get. Vendor-supplied configurations are published alongside, labelled, never replacing the default row. |
| 2026-09-17 | Gated scanners are benchmarked, with the friction published | An account requirement is disclosed in a `requires signup` column rather than being a disqualifier, and gated tools are run twice — ungated and credentialed — as two rows, with the ungated row as the default view. Excluding them would leave a major tool off the board; hiding the friction would misrepresent what a user gets. |
| 2026-09-17 | Corpus grows to 11 vulnerable servers, not ~8 | The plan scoped ~8 vulnerable servers against 10 attack classes, which would force classes to share a server and break the one-flaw-per-server rule that keeps attribution clean when a scanner half-fires. A10 splits into two servers (unrestricted execution, allowlist bypass), giving 11 plus the shadowed-target fixture for A3. Marginal cost once the FastMCP template exists; ambiguous attribution is not recoverable later. |
| 2026-09-17 | No funding from any benchmarked or benchmarkable vendor | The only asset this project has is being disinterested. Any funding from any source, if ever accepted, is disclosed in the README before the next results publish. |
| 2026-09-17 | Mapping disputes that do not resolve are published as both positions | Where we are not persuaded by a vendor's objection, the scoreboard row carries both positions rather than only our resolution. Readers are entitled to see the disagreement. |
| 2026-09-17 | Coordinated disclosure is kept separate from benchmark results | A genuine vulnerability found in a real scanner or server goes to its maintainers privately and is never published as a benchmark result. Conflating measurement with disclosure would make maintainers reluctant to engage at all. |

## Open questions

Carried forward. Resolved entries move into the table above with a date.

- Contact route for the Snyk-absorbed tool — maintainer email or Snyk's security
  channel? Resolve in Phase 3.
- Do we benchmark runtime proxy and gateway products at all, or is that a
  separate harness and a separate project? Excluded from v1; revisit after v1.0
  ships.
- Rotation cadence for the public corpus, and the size of the private held-back
  set. Needs a real corpus to reason about; resolve in Phase 1.
- Whether `unmapped` findings should eventually graduate into new taxonomy
  classes automatically, or only by amendment. Revisit once there is run data.
