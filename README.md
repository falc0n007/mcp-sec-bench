# mcp-sec-bench

**A vendor-neutral benchmark for MCP security scanners.**

Nobody knows how well MCP security scanners actually work. This measures it.

`mcp-sec-bench` is a corpus of deliberately vulnerable MCP servers, a
reproducible runner, and a public scoreboard. It is not a scanner, and it will
never become one.

---

## We do not ship a scanner. Ever.

**This project will never publish its own MCP security scanner** — not as a
reference implementation, not as a baseline, not as a demonstration, not under
another name by the same maintainers.

A benchmark that also competes in the category it measures is marketing. The
only asset this project has is being disinterested, so the rule is binding,
restated in [governance.md](docs/governance.md#the-no-scanner-rule), and
explicitly **not amendable** by the ordinary process. Changing it means
archiving this benchmark and starting a differently-named project, so that no
reader ever finds a scoreboard whose publisher quietly became a competitor.

---

## Scoreboard

**No results are published yet, and that is deliberate.**

The runner works and produces scores. They are withheld because
[governance.md](docs/governance.md#disclosure-before-publication) commits to
something stricter than publishing when ready: every scanner's maintainers
receive their full results, the methodology, and the exact mapping decisions
applied to their tool, with **14 days** to respond, before anyone else sees a
number. That round has not run.

Publishing first and disclosing afterwards would make this a different kind of
project than the one described below, so the scoreboard lands here when Phase 3
closes and not before.

What is already public and reviewable is everything the numbers will be
produced by:

| Document | What it fixes |
| --- | --- |
| [Attack class taxonomy](docs/taxonomy.md) | The 10 classes, defined so that "did the scanner catch it?" has one answer |
| [Scoring rules](docs/scoring.md) | What counts as a hit, a miss, and a false positive |
| [Neutrality and governance](docs/governance.md) | Who gets benchmarked, how a vendor contests a result, the disclosure window |
| [Ethics and scope](docs/ethics.md) | Why a vulnerable-server corpus exists and what constrains it |
| [Decision log](docs/decisions.md) | Every choice made so far, dated, with reasoning |
| [Project plan](docs/project-plan.md) | Phases, timeline, and task tracker |
| [The corpus](corpus/README.md) | 11 vulnerable servers, 4 benign controls, and what each one is for |
| [The lab](lab/README.md) | Bringing the sandboxed corpus online, and how egress is contained |
| [The runner](runner/README.md) | How scanner output becomes a score, and the separations that keep it reviewable |
| [Mapping rationale](docs/mapping-rationale.md) | Every decision translating a scanner's vocabulary into ours |
| [Scanner survey](docs/scanner-survey.md) | What each candidate scanner actually is, verified by installing and running it |

## Why this exists

- **Detection quality is poor and unmeasured.** An independent run against a
  vulnerable-server corpus reported recall of 0%, 4.2%, and 16.7% across three
  scanners, with precision of 0%, 50%, and 33%.
- **The tools do not overlap.** That same run found completely disjoint
  taxonomies between scanners. They are complementary rather than redundant,
  which means no single tool's output tells you your coverage.
- **The existing comparison is self-interested.** The one public benchmark comes
  from a repository whose own tool scores 100%.
- **Supply outpaces review.** MCP servers are published faster than they are
  reviewed and installed faster than they are scanned.

Verify these figures before relying on them. Re-establishing them under a
reproducible method is the entire point of the project.

## What v1 measures

Ten attack classes across a Python corpus, in two stages:

| Stage | Classes |
| --- | --- |
| **Static** — source tree and packaging metadata | A1 tool-description injection, A2 rug-pull, A3 cross-server shadowing, A7 hardcoded secrets, A8 unrestricted file read, A9 unrestricted env access, A10 command execution / allowlist bypass |
| **Runtime** — a live endpoint the scanner may exercise | A1 tool-description injection, A2 rug-pull, A3 cross-server shadowing, A4 response injection, A5 argument exfiltration, A6 authless endpoint |

The runtime classes carry the project. A4, A5, and A6 are structurally
unreachable by static analysis, and they are where this benchmark says something
no existing comparison does.

Scanners that only do static analysis are **not penalised** for the runtime
stage. Their runtime items are marked `not attempted` and excluded from the
denominator, and the scoreboard labels them "static only."

## How scores will be reported

- **Recall per class and precision, side by side.** No composite index, no
  ranking number, no letter grade — any single figure would require weighting
  attack classes against each other, which is an editorial claim about which
  attacks matter most. Rows sort alphabetically, not by score.
- **Mean and range over 5+ runs.** Several scanners use LLM-as-judge analyzers
  and vary run to run. A single number would be a fiction.
- **No partial credit.** A finding counts only if it names the right server and
  the right class. Near misses are logged in their own column.
- **Access friction is a published column.** Scanners requiring an account are
  benchmarked, and the requirement is part of the result.

Full rules: [scoring.md](docs/scoring.md).

## Ethics in one paragraph

This repository contains deliberately vulnerable MCP servers, built to be
*found* rather than to be effective. Payloads are minimal by construction — an
injection emits a benign marker, an exfiltration flaw reaches a sandbox-local
sinkhole that logs and drops it. Everything runs in an ephemeral lab with egress
blocked. No real credentials exist anywhere in the corpus, and CI fails if one
appears. Do not deploy these servers anywhere reachable. The full note, including
an honest account of the dual-use tradeoff, is in [ethics.md](docs/ethics.md).

## Status

| Phase | State |
| --- | --- |
| 0 — Scope and neutrality design | **Complete** |
| 1 — Corpus | **Complete** |
| 2 — Runner and normalization | **Complete** |
| 3 — Private disclosure round | Next |
| 4 — Public launch | Not started |

## Running it

From a clean checkout:

```bash
make setup      # venv plus pinned dependencies
make images     # lab and scanner images, all from pinned Dockerfiles
make lab-up     # corpus online, egress blocked
make verify     # manifests, credentials, every server, the lab, the tests
make scoreboard # run the benchmark and render the result
```

`make scoreboard` writes to `results/local/`, which is gitignored, so a
development run can never be mistaken for a published score.

Four adapters are wired: three run credential-free, and one is published as
unavailable because a token gates all of its analysis. A scanner we cannot run
still gets a row carrying the reason, because omitting it would quietly turn
"we could not run this" into "this was not considered".

## Adding your scanner

The submission path is a Phase 4 deliverable, but the inclusion criteria are
already fixed and are not negotiated case by case — a scanner is eligible when
it is reproducibly runnable without a sales call, publicly obtainable,
containerizable, produces parseable output, and is licensed compatibly with
having its output published. An account requirement is disclosed, not
disqualifying.

Anyone may submit an adapter, including a vendor for their own tool; vendor
authorship is disclosed on the scoreboard row. See
[governance.md](docs/governance.md#which-scanners-are-included).

**Before any result is published, its scanner's maintainers receive their full
results, the methodology, and the exact mapping decisions applied to their tool,
with 14 days to respond. Responses are published alongside the scores.**

## License

MIT. See [LICENSE](LICENSE).
