# MCP Security Benchmark — Project Plan & Tracker

> **Tracked copy.** This is the originating plan, kept in the repo as the source of
> record for phases and scope. Where it disagrees with a Phase 0 document, the Phase 0
> document wins: [taxonomy.md](taxonomy.md), [scoring.md](scoring.md),
> [governance.md](governance.md), [ethics.md](ethics.md). Decisions made since are in
> [decisions.md](decisions.md).

2026-09-16 · @Someone

## Project summary

A vendor-neutral benchmark suite for MCP security scanners: a corpus of deliberately vulnerable MCP servers, a reproducible runner, and a public scoreboard.

**Pitch:** nobody knows how well MCP security scanners actually work. This measures it.

**The core constraint:** we do not ship our own scanner. Ever. The moment this project also competes in the category it measures, the benchmark becomes marketing and its value collapses. Every scope decision downstream defers to this rule.

**Why a benchmark rather than another scanner:** the scanner and gateway slots are already occupied several times over. The measurement slot is empty, and benchmarks in immature security categories tend to get cited, linked from every comparison post, and adopted as the default reference.

## Why this project

The evidence that justifies building it, kept here so the pitch doesn't drift:

- **Detection quality is poor and unmeasured.** An independent run against a vulnerable-server corpus produced recall of 0%, 4.2%, and 16.7% for MCPScan, Cisco's scanner, and Invariant/Snyk respectively, with precision of 0%, 50%, and 33%.
- **The tools don't overlap.** That same run found completely disjoint taxonomies between scanners — they are complementary rather than redundant, which means no single tool's output tells you your coverage.
- **The category is young.** Independent write-ups describe MCP security scanning as a real but immature tooling category as of mid-2026.
- **Existing benchmark data is self-interested.** The one public comparison comes from a repo whose own tool scores 100%. That is exactly the vacuum a neutral benchmark fills.
- **Supply outpaces review.** MCP servers are published faster than they are reviewed and installed faster than they are scanned, with attacks landing at the package registry, tool description, tool argument, response, and agent-tool trust boundary.
- **A distribution shift just happened.** Invariant Labs' mcp-scan (2,000+ stars) was absorbed into Snyk and now requires an account and API token to run at all — so comparisons written against the old standalone CLI are stale, and there is appetite for no-account tooling.

## Scope for v1

Deliberately small. The instinct to broaden is the main schedule risk.

**In scope**

- Python MCP servers only (FastMCP-based)
- \~8 vulnerable servers, one flaw each
- \~4 benign control servers
- 3–4 scanners with working adapters
- 8–10 attack classes
- Static/source-path scanning plus one live-endpoint stage

**Out of scope for v1**

- Our own scanner — permanently out, not just for v1
- Non-Python server implementations (TypeScript corpus is a v2 conversation)
- Commercial scanners that cannot be run reproducibly without a sales call
- Runtime gateway products (different category; measuring them needs a different harness)
- Performance or latency benchmarking — this measures detection, not speed
- Any hosted service, dashboard-with-login, or paid tier

## Attack class taxonomy (v1 draft)

Anchored to vocabulary already in the literature rather than invented. Each needs a definition precise enough that "did the scanner catch it?" has one answer. Definitions were filled in Phase 0 and now live in [taxonomy.md](taxonomy.md), which supersedes this table.

| ID | Class | Reachable by | Definition status |
| --- | --- | --- | --- |
| A1 | Tool-description injection | Static | Locked (see taxonomy.md) |
| A2 | Rug-pull (mutated tool definition after trust) | Static + runtime | Locked (see taxonomy.md) |
| A3 | Cross-server tool shadowing | Static | Locked (see taxonomy.md) |
| A4 | Response injection (poisoned data in a legitimate response) | Runtime only | Locked (see taxonomy.md) |
| A5 | Argument exfiltration | Runtime only | Locked (see taxonomy.md) |
| A6 | Authless endpoint | Runtime only | Locked (see taxonomy.md) |
| A7 | Hardcoded secrets | Static | Locked (see taxonomy.md) |
| A8 | Unrestricted file read | Static | Locked (see taxonomy.md) |
| A9 | Unrestricted env access | Static | Locked (see taxonomy.md) |
| A10 | Command execution / allowlist bypass | Static | Locked (see taxonomy.md) |

The runtime-only rows matter disproportionately: they are what a static scan structurally cannot reach, and they are where the benchmark says something no existing comparison does.

## Phase 0 — Scope and neutrality design

**Weeks 1–2 · \~15 hrs · full-time equivalent: 2 days**

The decisions here determine whether the project is credible, and they are cheap to get wrong later.

- Lock the taxonomy: 8–10 classes, each defined unambiguously (see table above)
- Write the neutrality policy **before any results exist** — who can submit a scanner, how a vendor contests a result, what the disclosure window is
- Write the ethics and scope note: sandboxed targets, defensive research framing, no payloads aimed at deployed servers
- Choose license (MIT or Apache 2.0) and repo name
- Confirm the no-scanner rule in writing in the README

**Done when:** taxonomy doc, scoring rules, and governance policy are committed to the repo.

## Phase 1 — The corpus

**Weeks 3–5 · \~30 hrs · full-time equivalent: 4 days**

- **\~8 vulnerable servers**, one flaw each. One flaw per server keeps attribution clean when a scanner half-fires.
- **\~4 benign control servers.** The part most benchmarks skip, and what makes precision meaningful — without controls, a scanner that flags everything scores perfectly. Include realistic-but-safe patterns that naively look suspicious, documented as expected false positives.
- **Ground-truth manifest** (JSON per server): which classes are present, where, and any tolerated findings.
- **Sandboxing**: docker-compose, egress blocked, no real credentials, payloads that trigger detection without doing anything genuinely harmful.

**Done when:** `docker compose up` brings the whole lab online and each server's README explains its flaw.

**Watch out:** writing a *convincingly realistic* vulnerable server is much harder than writing a vulnerable one. This is where the 30% schedule buffer gets spent.

## Phase 2 — Runner and normalization

**Weeks 5–8 · \~40 hrs · full-time equivalent: 5–6 days**

The real engineering. The taxonomy mapping is harder than the plumbing.

- **Per-scanner adapters**, each installing and running in its own container.
- **Taxonomy mapping layer.** Scanners use completely disjoint vocabularies, so every tool's labels need mapping to ours. Expect this to be judgment-heavy and to need a documented rationale per mapping — that document is itself a contribution.
- **Credit rules.** A finding counts only if it names the right server *and* the right class. Partial credit is a rabbit hole: decide once, write it down.
- **Nondeterminism handling.** Some scanners use LLM-as-judge analyzers, so results vary run to run. Run each scanner 5+ times, report mean and spread, never a single number. Deterministic rule-based tools score zero variance, which is itself a useful signal.
- **Auth friction.** At least one major scanner now requires an account token to run at all, so the runner needs a documented credentials path and should mark results as "requires signup."
- **Output**: machine-readable results JSON plus a rendered table.

**Done when:** one command produces a reproducible scoreboard from a clean checkout.

## Phase 3 — Private disclosure round

**Weeks 8–10 · \~10 hrs active, 2 weeks elapsed**

Do not skip this. It is the difference between "independent benchmark" and "hit piece."

Email every scanner's maintainers with:

1. Their full results
2. The methodology and the exact mapping decisions applied to their tool
3. A 14-day window to respond, correct a mapping, or point out a misconfiguration

Publish their responses alongside the scores.

Two reasons this pays: maintainers who were consulted tend to link to the benchmark afterward, and at least one will probably find a genuine error in the setup — which is the point.

**Done when:** the window closes and corrections are folded in.

**Note:** this is elapsed time that cannot be compressed. Going full-time does not shorten it.

## Phase 4 — Public launch

**Weeks 10–12 · \~25 hrs · full-time equivalent: 3 days**

- Repo public, MIT or Apache 2.0
- **Scoreboard table at the top of the README** — this is the artifact people screenshot and link
- Static scoreboard site via GitHub Pages, regenerated by Actions
- **Launch writeup** leading with methodology and limitations rather than rankings. Given how bad the published recall figures already are, the results look damning on their own; understating them reads as more credible than hyping them.
- Post to r/netsec, Show HN, and MCP/agent-security communities
- "How to add your scanner" prominent in the README
- **Ship a badge** scanners can embed — the growth loop: every vendor who embeds it links back

**Done when:** v1.0 tagged, site live, submission path documented.

## Phase 5 — Maintenance

**Ongoing · \~4 hrs/month**

- Monthly automated re-run — recurring results are recurring reach
- Quarterly corpus additions as new attack classes appear
- **Hold back a private test set** and rotate the public one periodically, or tools will tune to the benchmark and the numbers stop meaning anything
- Triage adapter submissions from vendors
- Re-run disclosure for any scanner whose score materially drops

## Timeline

Assumes \~10 hrs/week (evenings plus part of a weekend).

| Phase | Part-time (\~10 hr/wk) | Full-time |
| --- | --- | --- |
| 0 — Scope & neutrality | Weeks 1–2 | 2 days |
| 1 — Corpus | Weeks 3–5 | 4 days |
| 2 — Runner & normalization | Weeks 5–8 | 5–6 days |
| 3 — Disclosure round | Weeks 8–10 (mostly waiting) | 2 weeks elapsed |
| 4 — Launch | Weeks 10–12 | 3 days |
| **To public v1** | **\~12 weeks** | **\~3 weeks work + 2 weeks disclosure** |

Add 30% realistically. Corpus design always overruns.

The disclosure window is elapsed time that cannot be compressed, so going full-time helps less than the table suggests.

## Scanners in the benchmark

Candidates for v1. Verify every field before relying on it — this is a starting list, not confirmed research.

| Scanner | Vendor | License | Account needed to run | Approach | Adapter status |
| --- | --- | --- | --- | --- | --- |
| mcp-scanner | Cisco | Apache 2.0 | No for core (YARA/static); yes for LLM-judge and threat-intel extras | Multi-engine: YARA, LLM-as-judge, behavioral | Not started |
| agent-scan (fka Invariant mcp-scan) | Snyk | Source-available | Yes — SNYK\_TOKEN required | Static manifest/description analysis, tool hashing, shadowing checks | Not started |
| sentinel-scan-cli | Community | MIT | No | Zero-dependency static scan | Not started |
| mcp-guard | Community | TBC | No | Capability-gap detection, source + live endpoint | Not started |
| MCPKernel | Community | Apache 2.0 | No | Runtime proxy: policy, taint tracking, sandboxing | Candidate — runtime harness may differ |

Three working adapters is the floor for launch. If only three land, ship anyway.

## Task tracker

**Phase 0 — Scope and neutrality**

- [x] Define all 10 attack classes precisely
- [x] Write neutrality and governance policy
- [x] Write ethics/scope note (sandbox, defensive framing)
- [x] Pick license and repo name
- [x] Commit no-scanner rule to README

**Phase 1 — Corpus**

- [x] Scaffold FastMCP server template
- [x] Build 8 vulnerable servers, one flaw each (built 11 - see decisions.md)
- [x] Build 4 benign control servers with suspicious-looking-but-safe patterns
- [x] Write ground-truth manifest schema
- [x] Write per-server manifests and READMEs
- [x] docker-compose lab with egress blocked
- [x] Verify no real credentials anywhere in the corpus

**Phase 2 — Runner**

- [ ] Runner skeleton and results JSON schema
- [ ] Adapter: Cisco mcp-scanner
- [ ] Adapter: Snyk agent-scan (with token path)
- [ ] Adapter: sentinel-scan-cli
- [ ] Adapter: mcp-guard
- [ ] Taxonomy mapping layer + per-mapping rationale doc
- [ ] Credit rules implemented and documented
- [ ] N=5 repeat runs with mean/spread reporting
- [ ] Live-endpoint stage for runtime-only classes
- [ ] Scoreboard renderer (table + JSON)

**Phase 3 — Disclosure**

- [ ] Draft disclosure email template
- [ ] Identify maintainer contacts for each scanner
- [ ] Send results with 14-day window
- [ ] Log responses
- [ ] Fold in corrections

**Phase 4 — Launch**

- [ ] README with scoreboard at top
- [ ] GitHub Pages site + Actions regeneration
- [ ] "Add your scanner" contribution guide
- [ ] Embeddable badge
- [ ] Launch writeup (methodology-first)
- [ ] Post: Show HN
- [ ] Post: r/netsec
- [ ] Post: MCP/agent-security communities
- [ ] Tag v1.0

**Phase 5 — Ongoing**

- [ ] Monthly re-run scheduled in Actions
- [ ] Private held-back test set created
- [ ] Quarterly corpus review scheduled

## Risks and mitigations

| Risk | Why it matters | Mitigation |
| --- | --- | --- |
| Scope creep into building a scanner | The single biggest threat. Every benchmark author eventually thinks "I could detect this better." Doing it destroys the neutrality claim. | No-scanner rule written into the README in Phase 0. If the itch persists, ship it as a separate repo under a different name, after v1 is stable. |
| Dual-use perception | Publishing a library of vulnerable MCP servers can read as offensive tooling and get amplified as criticism instead of work. | Sandboxed lab, minimal payloads, explicit ethics/scope note from day one, defensive-research framing in the launch post. |
| Maintainer hostility | A public scoreboard that makes tools look bad invites pushback. | Phase 3 disclosure round handles almost all of this. Publish their responses alongside scores. |
| Too few working adapters | Three tools is a thin scoreboard. | Ship anyway. An incomplete benchmark that exists beats a complete one that doesn't. |
| Mapping disputes | Disjoint taxonomies mean every mapping is a judgment call someone can contest. | Document rationale per mapping; make the mapping file a first-class, reviewable artifact. |
| Benchmark overfitting | Once tools tune to the corpus, scores stop meaning anything. | Private held-back set, periodic rotation of the public corpus. |

## Decision log

Dated record of choices, so future-you knows why. Append as you go.

| Date | Decision | Reasoning |
| --- | --- | --- |
| 2026-09-16 | Build the benchmark, not the cross-server detector | Benchmark has lower competition, higher citation potential, and a clear neutrality story. The detector would need a test corpus anyway — i.e. a smaller version of Phase 1 — so the benchmark is the better first move and the detector can follow as a separate repo. |
| 2026-09-16 | Never ship our own scanner | Competing in the measured category collapses the benchmark's value. |
| 2026-09-16 | Python-only corpus for v1 | Keeps Phase 1 finishable. TypeScript is a v2 conversation. |

## Open questions

- Repo name — worth picking something that doesn't read as a scanner
- MIT vs Apache 2.0 (Apache's patent grant may matter more in a security context)
- Does the live-endpoint stage ship in v1, or does v1 stay source-only and runtime classes land in v1.1?
- Do we benchmark runtime proxies at all, or is that a separate harness and a separate project?
- Partial credit: is a scanner that finds the right server but the wrong class worth anything?
- Contact route for the Snyk-absorbed tool — maintainer email or Snyk's security channel?
