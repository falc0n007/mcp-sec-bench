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
| 2026-09-17 | Every corpus server runs authenticated HTTP except a06 and c04 | Auth is load-bearing for A6. If every server were unauthenticated, every server would exhibit A6 and the class would be untestable. All servers therefore require a bearer token except `a06-authless-endpoint` (the flaw itself) and `c04-status-service` (unauthenticated but exposing no sensitive tools, which is the control separating scanners that reason about capability from scanners that flag any open port). Enforced by `tools/validate_manifests.py` and `tools/smoke_server.py`. |
| 2026-09-17 | Lab topology: corpus servers on an internal-only network behind a gateway | Verified empirically that Docker's `internal: true` blocks outbound TCP and DNS, but also prevents publishing ports to the host. Rather than weaken egress blocking by attaching servers to a routable network, a single `gateway` container sits on both networks and forwards each corpus port. Corpus servers never touch the routable network, so the sandboxing commitment in ethics.md holds literally. |
| 2026-09-17 | A2 rug-pull implemented via FastMCP `on_list_tools` middleware | The mutation had to be observable as a genuinely different descriptor across `tools/list` calls, and be visible in source as a branch keyed to call count so the static route can earn credit too. Middleware satisfies both and keeps the decorated tool's own description clean, so the pre-mutation version is unambiguously observable. Verified empirically rather than assumed; the MCP `initialize` handshake does not invoke the hook, so the counter maps 1:1 onto client list calls and N=4 fires deterministically. |
| 2026-09-17 | Exactly one tolerated finding corpus-wide | `c03-release-runner` tolerates A7 for its high-entropy build-artifact digest, which is genuinely ambiguous. Every other suspicious-looking pattern in the controls -- the correctly-rooted file read, the allowlisted env read, the fixed command, the placeholder token -- is scored as a false positive when flagged. Each tolerated entry is a hole in the benchmark's ability to punish over-flagging, so the list is kept at the minimum that honesty requires, and adding to it is a governance amendment rather than a code change. |
| 2026-09-17 | Corpus dependencies pinned in the lab image | `fastmcp==4.0.4` and `httpx==0.28.1`. A corpus version has to rebuild identically or a score is not comparable to itself, let alone across scanners. |
| 2026-09-17 | A6 `not_applicable` is enumerated, not derived from whatever a manifest declares | Two servers had declared an empty `sensitive_tools`, which marked them `not_applicable` for A6 and removed them from that denominator -- a free pass for a scanner that over-flags A6, with the same effect as an unauthorised tolerated entry. An authenticated HTTP server with real tools is a true negative for A6 (it could have been authless and is not), not structurally incapable of it. Only `c04-status-service` may sit outside the denominator, because being unauthenticated with no sensitive capability is the entire point of that control. Enforced by `tools/validate_manifests.py` and negative-tested. |
| 2026-09-17 | Near-miss wording corrected: a near miss never forces a false negative | As written the rule said a near miss is "scored as a false positive on the reported class and a false negative on the declared one", which contradicts the rule that an item has exactly one outcome and that duplicate findings collapse. If the declared class was separately found it is a true positive and cannot simultaneously be a false negative. Reworded so the false negative arises from the ordinary rule when nothing found the class, rather than being imposed by the near miss. This is a clarification to the only self-consistent reading, not a behaviour change; no results exist. Surfaced by the scoring engine implementation. |
| 2026-09-17 | RawFinding carries an explicit `stage` | A2 is creditable from either stage, so a finding on a dual-surface class otherwise has its stage guessed. The field replaces a convention of stashing it in the untyped `raw` dict. |
| 2026-09-17 | `c02-webhook-notifier` carries NO tolerated A5 entry | A label like "outbound network call in a tool" fires identically on c02 and on `a05-argument-exfiltration`; the servers differ in the tool's declared purpose, not in the shape of the code, and the taxonomy is explicit that a declared-destination sender is not A5. Telling them apart is exactly the capability under measurement, so tolerating A5 on c02 would excuse the failure the control exists to catch. It is a false positive. Decided before the corpus was tagged, because the tolerated set freezes at tag time and a later addition would require a governance amendment plus re-disclosure. |
| 2026-09-17 | Mapping keys on the scanner's label, never on the target server | A mapping table that resolved a label differently depending on which server the finding landed on would be teaching the mapper the answer key, which is the overfitting the private held-back set exists to detect. Mappings are frozen against a corpus_version before a run. |

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
- **A1 vs A4 is knowingly mis-scored in one case.** `taxonomy.md` grants A4
  credit to a scanner that walks non-source data files and flags the poisoned
  fixture. Such a finding arrives in the static stage, where the mapping layer
  resolves injection labels to A1 -- so a legitimate A4 detection scores as a
  false positive on a01 plus a near miss on a04. The alternative, discriminating
  on finding text, was rejected as unreviewable. The taxonomy expects this route
  to be rare, so the cost is small, but it is a known defect rather than an
  unknown one. Resolve before Phase 4.
- **Should the near-miss counter be narrowed?** As defined, any wrong class on
  a server that declares something counts, so the counter is trivially
  inflated: the `overflagger` fixture earns 99 near misses alongside 137 false
  positives. A large near-miss count is therefore not evidence of
  near-competence, though its name invites exactly that reading, and a vendor
  could quote it that way. Narrowing it -- requiring the finding to localise to
  the declared flaw's file, or requiring the scanner to have been selective on
  that server -- would make it mean what it says. That changes a published
  metric's definition, so it needs the amendment process rather than a code
  change. Until then `near_miss` is never published without the false-positive
  count beside it, and is never described as "almost right". Resolve before
  Phase 4.
