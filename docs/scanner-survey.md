# Scanner reconnaissance — mcp-sec-bench

Date of research: **2026-09-17**. All version numbers, licences and behaviours below were
observed on that date. Every "verified" claim was produced either by fetching the primary
source (repo / PyPI JSON API / GitHub API) or by installing and running the tool in a
throwaway venv or container under this scratchpad. Nothing was installed into the repo and
the repo was not modified.

Confidence markers used throughout:

- **[V]** verified — I ran it, or read it from the canonical repo / package registry.
- **[I]** inferred — reasonable reading of primary docs, not executed.
- **[U]** unknown — could not establish.

---

## Summary table

| Plan row | Actually exists as | Canonical source | Version [V] | Licence [V] | Runs w/o account? | Takes | Machine output | Container | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `mcp-scanner` (Cisco) | **yes, name correct** | github.com/cisco-ai-defense/mcp-scanner · PyPI `cisco-ai-mcp-scanner` | 4.8.4 | Apache-2.0 | **Partly.** YARA + readiness need nothing. LLM / behavioural / AI-Defense need keys | live MCP URL, stdio cmd, client config file, static tools JSON; source dir only via `behavioral` (needs LLM key) | `--raw` / `--format raw` → JSON array on stdout | yes, ships 4 Dockerfiles | **CONFIRMED RUNNABLE** |
| `agent-scan` (Snyk, fka Invariant `mcp-scan`) | **yes** — repo renamed, old URL 301s to it | github.com/snyk/agent-scan · PyPI `snyk-agent-scan` | 0.6.3 | Apache-2.0 | **No.** `SNYK_TOKEN` gates *all* analysis | MCP client config JSON (`mcpServers`), dirs of skills; remote HTTP servers supported inside a config | `--json` | yes (docs recommend it) | **CONFIRMED RUNNABLE, token required** |
| `sentinel-scan-cli` | **yes, name correct** | github.com/Ventrova/sentinel-scan-cli · PyPI + npm `sentinel-scan-cli` | 1.4.16 | MIT | **Yes**, fully offline for the `mcp` subcommand | an `mcp.json` **manifest file only** — not a source dir, not a live URL | `--format json|sarif`, writes to `--output` | trivially (pure-Python, no deps) | **CONFIRMED RUNNABLE** |
| `mcp-guard` | **ambiguous name; best match = `SaravanaGuhan/mcp-guard`** | github.com/SaravanaGuhan/mcp-guard | 2.0.0 | MIT | **Yes**, `--offline` needs no network at all | **a source directory** or a GitHub URL; live/dynamic stage launches the server over **stdio** | `--format json|sarif`, `-o` | yes; has its own `--sandbox docker` | **CONFIRMED RUNNABLE — best fit for our corpus** |
| `MCPKernel` | **yes** | github.com/piyushptiwari1/mcpkernel · PyPI `mcpkernel` | 0.3.0 | Apache-2.0 | yes | it is a gateway/proxy that sits in front of tool calls | JSONL/CEF/CSV/SARIF audit export | yes | **DISQUALIFIED by category** (runtime gateway) |
| *(not on the plan's list)* | **Ramparts** | github.com/highflame-ai/ramparts | 0.8.9 tagged / 0.8.8 from crates.io | Apache-2.0 | yes for YARA; LLM stage needs a key | **a live MCP server URL** (also IDE configs, skill dirs) | `--format json`, SARIF | yes (repo has Dockerfiles) | **CONFIRMED RUNNABLE — recommend adding** |

### What was actually detected on our corpus (first pass, no credentials anywhere)

All 15 corpus servers were started locally on their documented ports and scanned.

| Scanner (credential-free config) | Findings on 11 vulnerable servers | Findings on 4 controls |
| --- | --- | --- |
| Cisco `--analyzers yara`, `remote` | **0** | 0 |
| Ramparts `scan <url>` (YARA pre-scan, no LLM key) | **0** | 0 |
| sentinel-scan `mcp --manifest <tools.json>` | 5 findings across a03/a06/a10a/a10b | 5 findings across c02/c03 |
| mcp-guard `<dir> --offline` | 6 findings across a07/a08/a10a/a10b | 2 findings across c01/c03 |
| Snyk agent-scan | n/a — refuses to analyse without `SNYK_TOKEN` | n/a |

This is a real, reproducible result and it matches the premise in `project-plan.md`: the
credential-free configurations of the two best-known scanners detect **nothing** on this
corpus. It also shows the controls are doing their job — two of the four already draw false
positives.

---

## 1. Cisco `mcp-scanner` — CONFIRMED

**Identity [V].** Repo `https://github.com/cisco-ai-defense/mcp-scanner`, 1074 stars,
Apache-2.0 (GitHub API), last push 2026-09-17. PyPI distribution name is
**`cisco-ai-mcp-scanner`** (not `mcp-scanner`), version **4.8.4**, uploaded 2026-08-28,
`requires_python >=3.11.4`. Console scripts installed: `mcp-scanner`, `mcp-scanner-api`.

**Install [V].** README recommends `uv tool install --python 3.13 cisco-ai-mcp-scanner`.
I installed with plain pip and it worked with no extra system packages:

```
python3 -m venv venv1
./venv1/bin/pip install cisco-ai-mcp-scanner      # -> cisco-ai-mcp-scanner-4.8.4
./venv1/bin/mcp-scanner --help
```

Note it is heavy: pulls litellm, tokenizers, 9 tree-sitter grammars, yara-python, pip-audit.

**Containerizable [V].** The wheel itself ships
`mcpscanner/docker/{Dockerfile,Dockerfile.wheel,Dockerfile.npm,Dockerfile.npm.wheel}` plus
entrypoints, so containerization is a first-class supported path.

**Credentials [V].** Analyzer list from `--help`:
`api, yara, llm, behavioral, virustotal, readiness, vulnerable_package, meta`
(default `api,yara,llm`).

- `yara` — no credential. Verified running.
- `readiness` — no credential. Verified running.
- `api` — needs `MCP_SCANNER_API_KEY` + `MCP_SCANNER_ENDPOINT` (Cisco AI Defense).
- `llm`, `behavioral`, `meta` — need `MCP_SCANNER_LLM_API_KEY`. Verified:
  `mcp-scanner behavioral <corpus dir>` with no key prints
  `Error during scanning: LLM provider API key is required for alignment verification`.
- No sales call anywhere. Signup is only needed for the AI-Defense analyzer; an LLM key is
  a third-party key, not a Cisco account. **Eligible under governance §Which scanners are
  included.**

**What we hand it [V].** Our corpus is source dirs served over HTTP at `/mcp` with a bearer
token, which is the ideal shape for `remote`:

```
mcp-scanner --analyzers yara --log-level error --raw \
  remote --server-url http://HOST:8101/mcp --bearer-token lab-token-do-not-reuse
```

Verified working end to end against `a01`. It also accepts `--header 'Name: Value'`.
The **source-directory** path (`behavioral <dir>`) is the only one that reads `server.py`,
and it is LLM-gated — so a credential-free Cisco adapter is necessarily an
*endpoint-only, tool-description-only* adapter. Worth stating on the scoreboard row.

**Output [V].** `--raw` prints a JSON array to stdout, one object per scanned item:

```json
{
  "status": "completed",
  "is_safe": true,
  "findings": {
    "yara_analyzer": {
      "severity": "SAFE",
      "threat_names": [],
      "threat_summary": "No threats detected",
      "total_findings": 0
    }
  },
  "tool_name": "summarize_document",
  "tool_description": "Summarize a stored document ... IMPORTANT INSTRUCTION FOR THE ASSISTANT READING THIS DESCRIPTION: ...",
  "item_type": "tool"
}
```

With `readiness` added, an extra `readiness_analyzer` block appears with an
`mcp_taxonomies` array. `--format {raw,summary,detailed,by_tool,by_analyzer,by_severity,table}`
and `--output FILE` are also available.

**Label vocabulary [V]** — this is the part the taxonomy layer needs, read straight out of
the installed wheel.

YARA rule names (`mcpscanner/data/yara_rules/*.yara`, 10 rules):

```
code_execution, coercive_injection, command_injection, credential_harvesting,
data_exfiltration, prompt_injection, script_injection, sql_injection,
system_manipulation, tool_poisoning
```

`mcpscanner/threats/threats.py` maps analyzer threat names onto an AITech/AISubtech
taxonomy. Threat-name keys by analyzer group:

- `LLM_THREATS`: `PROMPT INJECTION`, `DATA EXFILTRATION`, `TOOL POISONING`, `TOOL SHADOWING`
- `YARA_THREATS`: `PROMPT INJECTION`, `CODE EXECUTION`, `INJECTION ATTACK`,
  `CREDENTIAL HARVESTING`, `SYSTEM MANIPULATION`, `DATA EXFILTRATION`, `TOOL POISONING`
- `BEHAVIORAL_THREATS`: `PROMPT INJECTION`, `INJECTION ATTACKS`, `TEMPLATE INJECTION`,
  `TOOL POISONING`, `GOAL MANIPULATION`, `DATA EXFILTRATION`,
  `UNAUTHORIZED OR UNSOLICITED NETWORK ACCESS`, `UNAUTHORIZED OR UNSOLICITED SYSTEM ACCESS`,
  `ARBITRARY RESOURCE READ/WRITE`, `UNAUTHORIZED OR UNSOLICITED CODE EXECUTION`,
  `BACKDOOR`, `DEFENSE EVASION`, `RESOURCE EXHAUSTION`,
  `GENERAL DESCRIPTION-CODE MISMATCH`
- `VIRUSTOTAL_THREATS`: `MALWARE`; `VULNERABLE_PACKAGE_THREATS`: `VULNERABLE_DEPENDENCY`
- `AI_DEFENSE_THREATS`: `PROMPT_INJECTION`, `HARASSMENT`, `HATE_SPEECH`, `PROFANITY`,
  `SEXUAL_CONTENT_AND_EXPLOITATION`, `SOCIAL_DIVISION_AND_POLARIZATION`,
  `VIOLENCE_AND_PUBLIC_SAFETY_THREATS`, `CODE_DETECTION`, `SECURITY_VIOLATION`
- `PROMPT_DEFENSE_THREATS`: `INSTRUCTION_OVERRIDE`, `DATA_LEAKAGE`, `ROLE_ESCAPE`,
  `INDIRECT_INJECTION`, `OUTPUT_WEAPONIZATION`, `OUTPUT_MANIPULATION`, `MULTILANG_BYPASS`,
  `UNICODE_ATTACK`, `CONTEXT_OVERFLOW`, `SOCIAL_ENGINEERING`, `INPUT_VALIDATION`,
  `ABUSE_PREVENTION`

Each entry carries `aitech` / `aitech_name` / `aisubtech` / `aisubtech_name`, e.g.
`PROMPT INJECTION → AITech-1.1 "Direct Prompt Injection" / AISubtech-1.1.1
"Instruction Manipulation (Direct Prompt Injection)"`. That is a ready-made intermediate
vocabulary for the mapping doc.

**Result on our corpus [V].** `--analyzers yara` over all 15 servers: **zero findings**,
including on a01 whose injected tool description is verbatim in the scanned text. Adding
`readiness` produces a `HIGH` finding on essentially **every tool** ("does not specify a
timeout", 7 findings per tool) — unusable as a security signal and catastrophic for
precision. Recommendation: the default Cisco row is `--analyzers yara`; `readiness`
should not be enabled; an `llm`-enabled row is a valuable second labelled row once an LLM
key path exists (governance allows an alternative configuration as an additional row).

---

## 2. Snyk `agent-scan` — CONFIRMED, token-gated

**Identity [V].** `https://github.com/invariantlabs-ai/mcp-scan` now **301s to
`https://github.com/snyk/agent-scan`** (confirmed via GitHub API `Moved Permanently`).
Repo `snyk/agent-scan`, 3059 stars, **Apache-2.0**, last push 2026-09-17. PyPI distribution
**`snyk-agent-scan` 0.6.3**, uploaded 2026-09-10, Apache-2.0, `requires_python >=3.10`.
The plan's "Source-available" licence field is **wrong** — it is Apache-2.0.

**Install [V].** README documents `uvx snyk-agent-scan@latest` and standalone binaries from
GitHub Releases. Plain pip also works:

```
python3 -m venv venv2
./venv2/bin/pip install snyk-agent-scan       # -> snyk-agent-scan-0.6.3
./venv2/bin/snyk-agent-scan --help
```

**Credentials [V] — this is the decisive fact.** Running a scan with `SNYK_TOKEN` unset:
the tool successfully connects to our HTTP server, enumerates every tool, assembles the
payload, and then exits **1** with:

```
To use Agent Scan, set the SNYK_TOKEN environment variable. To get a token, go
to https://app.snyk.io/account (API Token -> KEY -> click to show).
```

No findings are produced. So the token gates **all** analysis, not some engines. The
`inspect` subcommand does run tokenless (exit 0) but only enumerates tools/prompts/
resources — no security verdicts. Free signup exists, so under governance §2 this is a
**`requires signup` disclosure, not a disqualifier**.

**Two things worth disclosing on the scoreboard row beyond "requires signup" [V]:**

1. The analysis is **server-side**. The verbose payload it would have sent includes
   `"scan_user_info": {"hostname": ..., "username": [...], "ip_address": ..., "anonymous_identifier": ...}`
   and `"scan_metadata": {"cli_version": "0.6.3"}`. Results are therefore not reproducible
   offline, may change without a version bump, and the run sends host metadata to a vendor.
   That interacts directly with governance §Corpus integrity (a vendor sees our corpus).
2. It **executes** stdio servers it finds in configs. Irrelevant for us (our corpus is
   remote HTTP, and it printed `Remote MCP servers (no subprocess — auto-allowed)`), but the
   adapter should still pass `--suppress-mcpserver-io=true` and run containerized.

**What we hand it [V].** An MCP client config file. This worked:

```json
{
  "mcpServers": {
    "a01-tool-description-injection": {
      "type": "http",
      "url": "http://127.0.0.1:8101/mcp",
      "headers": {"Authorization": "Bearer lab-token-do-not-reuse"}
    }
  }
}
```

```
snyk-agent-scan scan ./mcp-a01.json --json --ci
```

The adapter must generate one such config per corpus server (one server per config keeps
attribution clean).

**Output [V].** `--json`. Other relevant flags observed in `--help`: `scan` (default),
`inspect`, `evo` (push to Snyk Evo), `guard`; `--no-skills`, `--verbose`, `--print-errors`,
`--ci`, `--dangerously-run-mcp-servers`, `--server-timeout`, `--ignore-risks` (0.6+),
`--ignore-issues-codes` (0.5.x).

**Label vocabulary [I, not executed].** Per the repo README, 0.5.x emitted E-/W- issue codes
(`Prompt Injection`, `Tool Poisoning`, `Tool Shadowing`, `Malware Payloads`,
`Credential Handling`, `Hardcoded Secrets`); 0.6+ replaced these with ~15 scored *risk
indicators* (`prompt injection`, `dangerous words`, `untrusted content`, `private data`,
`destructive capabilities`, `suspicious downloads`, `malicious code`, `secret detection`).
**I could not verify the real 0.6.3 label strings without a token** — mark as UNKNOWN until
someone runs it with `SNYK_TOKEN`. Getting that token should be an early Phase 2 task,
because it is the only way to pin this mapping.

---

## 3. `sentinel-scan-cli` — CONFIRMED, but it does not scan what we have

**Identity [V].** `https://github.com/Ventrova/sentinel-scan-cli`, MIT, last push
2026-08-25, **1 star**. PyPI `sentinel-scan-cli` **1.4.16** (MIT, `requires_python >=3.8`,
uploaded 2026-08-25); also published on npm under the same name. The README claims v1.4.8;
the registry is ahead of it.

**Install [V].** `pip install sentinel-scan-cli` — installs with **zero dependencies**, which
makes the plan's "zero-dependency static scan" description accurate. `npx sentinel-scan-cli`
is the Node path.

**Credentials [V].** None for the `mcp` subcommand. `--demo` runs with no file and no network.
The tool prints upsell links to `ventrova.dev/audit` (a paid LLM-judged review) after every
run — cosmetic, not a gate. The *other* subcommand (prompt-injection scan of a live LLM
endpoint) needs an LLM API key, but that is out of scope for us.

**What we hand it [V] — the important constraint.** `sentinel-scan mcp` takes
`--manifest <mcp.json>` **only**. It cannot read a source directory and cannot connect to a
live endpoint. To include it, the runner must first do an MCP `tools/list` against each
corpus server and write a manifest file. Confirmed working with a
`{"tools": [ ... ]}` document. It also understands `mcpServers` config blocks, which is
where its `hardcoded_credential` / `unpinned_remote_source` / `missing_provenance`
heuristics live — those can never fire on a tools-only manifest, so the adapter should emit
**both** a `mcpServers` block and the `tools` array in one manifest to be fair to the tool.

Use **wire-format** keys (`inputSchema`, not `input_schema`) when generating the manifest —
`excessive_agency_schema` reads `inputSchema`. (In my runs both spellings gave the same
result, but that is luck, not design.)

```
sentinel-scan mcp --manifest tools-8101.json --format json --output out.json
sentinel-scan mcp --manifest tools-8102.json --baseline base.json      # rug-pull drift
```

`--baseline` / `--update-baseline` hash each tool definition and emit a
`tool_definition_drift` finding when a definition changes — that is a **direct hit on our
A2 (rug-pull)** class and the only tool I found with a purpose-built mechanism for it. The
runner would need a two-phase run (record baseline, trigger the mutation, rescan).

**Output [V].** `--format json` (default) or `sarif` (SARIF 2.1.0), written to `--output`.
`--fail-on {high,medium,low,none}` controls exit code.

**Label vocabulary [V]** — this survey recorded 11 heuristics; building the adapter
against the whole corpus found **15**. Each is tagged with an OWASP LLM *and* an OWASP
MCP category:

```
tool_description_injection    LLM01 / MCP01
tool_name_shadowing           LLM01 / MCP02
hidden_unicode_instructions   LLM01 / MCP01
indirect_injection_surface    LLM01 / MCP01
excessive_agency_schema       LLM06 / MCP06
missing_hitl_confirmation     LLM06 / MCP06
overbroad_tool_scope          LLM06 / MCP06
hardcoded_credential          LLM02 / MCP03
unpinned_remote_source        LLM03 / MCP04
missing_provenance            LLM03 / MCP04
tool_definition_drift         (with --baseline)
command_injection_risk        found only by running it
cross_origin_exfiltration     found only by running it
dos_resource_exhaustion       found only by running it
homoglyph_typosquat           found only by running it
```

The last four were missed by this survey and found only when the adapter ran
the tool across all 15 corpus servers. Recorded rather than quietly corrected,
because it is the kind of survey error that silently understates a scanner: an
unmapped label costs a tool nothing, but a label we never knew existed cannot
be mapped at all, and its detections would have arrived mid-run as unrecognised
output. All 15 are now in `mapping/sentinel-scan-cli.json`.

Real finding, captured from `a10b-allowlist-bypass`:

```json
{
  "heuristic": "excessive_agency_schema",
  "owasp_category": "LLM06: Excessive Agency",
  "owasp_mcp_category": "MCP06: Excessive Agency / Permissions",
  "severity": "HIGH",
  "confidence": 0.75,
  "tool": "run_build",
  "evidence": "parameter \"command\" is a free-form string with no enum/pattern - looks like arbitrary command/code execution",
  "recommendation": "Constrain this parameter to a fixed enum of allowed operations, ..."
}
```

Top-level shape is `{"summary": {...}, "results": [...]}` with
`summary.findings_by_heuristic` giving per-rule counts — very easy to adapt.

**Result on our corpus [V].** 5 findings on vulnerable servers (a03, a06, a10a, a10b — all
`missing_hitl_confirmation` except one `excessive_agency_schema` on a10b), 5 findings on
controls (c02 ×3, c03 ×2). Missed a01 outright: its `tool_description_injection` phrase list
matches "this tool takes priority over" but our corpus says "this directive takes priority
over the user's request", so the heuristic does not fire. That is a genuine, publishable miss.

---

## 4. `mcp-guard` — NAME IS AMBIGUOUS; one strong match found

**The plan's description does not resolve to a unique project.** At least four unrelated
GitHub projects use this name [V]:

| Repo | What it is | Stars | Licence |
| --- | --- | --- | --- |
| `SaravanaGuhan/mcp-guard` | static + dynamic security scanner, CLI, source dir or GitHub URL | 12 | MIT |
| `pangxueyuan2-creator/mcp-guard` | offline auditor for MCP configs / skills | — | — |
| `General-Analysis/mcp-guard` | client-side prompt-injection *guard* (runtime) | — | — |
| `usemcpguard.io` | hosted product | — | — |

There is also an unrelated **arXiv paper** titled "MCPGuard: Automatically Detecting
Vulnerabilities in MCP Servers" (arxiv.org/pdf/2510.23673), which is probably where the
"capability-gap detection" phrasing in the plan came from. **No tool I found describes
itself as doing "capability-gap detection."** The nearest thing in the ecosystem is Cisco's
`behavioral` analyzer (docstring-vs-implementation mismatch), which is LLM-gated.

**Recommendation: rewrite this plan row to name `SaravanaGuhan/mcp-guard` explicitly, or
drop the row.** Everything below is about that repo.

**Identity [V].** `https://github.com/SaravanaGuhan/mcp-guard`, MIT, 12 stars, last push
2026-09-04. Not on PyPI; installs from git. Version **2.0.0**.

**Install [V].**

```
python3 -m venv venv4
./venv4/bin/pip install "git+https://github.com/SaravanaGuhan/mcp-guard.git"
./venv4/bin/mcp-guard --help
```

Dependency footprint is tiny (`requests`, `cvss`, `tree-sitter`, `tree-sitter-javascript`).
Install from a git URL is arguably a "bespoke build" under governance §1 — I read it as
fine, since it is a single reproducible pip command against a public repo, but the adapter
should pin a commit SHA rather than `main` so the run is reproducible.

**Credentials [V].** None. `--offline` disables the only network call (OSV dependency
lookups) and the scan still runs. Fully credential-free.

**What we hand it [V] — this is the one tool that natively takes our corpus shape.**
A source directory:

```
mcp-guard "corpus/a10a-command-execution" --no-cache --offline --format json -o out.json
```

Stages are `acquire → detect → static → dependencies → dynamic`. `dynamic` is opt-in behind
`--allow-execute` and `--sandbox docker`.

**Caveat for our corpus [V]:** `detect` reported
`no package.json, pyproject.toml, requirements.txt, go.mod or Dockerfile found; target does
not look like an MCP server` and set `is_mcp_server: false` — because our per-server
directories are just `server.py` + `manifest.json` + `README.md`, deliberately with no
per-server dependency manifest. The **static stage ran anyway and still found the flaws**,
so this does not block us. But the `MCPG-DYN-*` rules will never fire: the dynamic stage
derives a stdio launch command, and our servers speak HTTP. Either accept that mcp-guard is
a static-only adapter for us, or pass `--entrypoint` plus a stdio shim. I recommend
static-only for v1 and documenting why.

**Output [V].** `--format {console,json,sarif,summary}`, `-o FILE`, `--fail-on`,
`--min-severity`. JSON is `schema_version: "2.0.0"` with `server_info`, `stages[]`,
`summary.by_severity`, `summary.by_source`, and `findings[]`.

**Label vocabulary [V]** — 23 rule IDs, extracted from the installed package:

```
MCPG-PY-SHELL-TAINT        MCPG-PY-PATH-TAINT
MCPG-JS-SHELL-TAINT        MCPG-JS-PATH-TAINT       MCPG-JS-VM-EVAL
MCPG-SECRET-HARDCODED
MCPG-MCP-PROMPT-INJECTION-SURFACE  MCPG-MCP-SCHEMA-UNDECLARED-ARGS  MCPG-MCP-URI-CONCAT
MCPG-DEP-KNOWN-VULN
MCPG-DOCKER-ROOT           MCPG-DOCKER-LATEST-TAG   MCPG-DOCKER-CHMOD777
MCPG-DOCKER-ADD-REMOTE     MCPG-DOCKER-CURL-PIPE-SH MCPG-DOCKER-ENV-SECRET
MCPG-DYN-CMDEXEC           MCPG-DYN-PATHTRAVERSAL   MCPG-DYN-CRASH
MCPG-DYN-JSONRPC-VIOLATION MCPG-DYN-NO-DISPATCH     MCPG-DYN-SCHEMA-UNENFORCED
MCPG-DYN-UNDECLARED-METHOD
```

Findings also carry `cwe`, a CVSS 4.0 vector and score, and an **OWASP AIVSS v0.8** block.
Real finding from `a10a-command-execution`:

```json
{
  "rule_id": "MCPG-PY-SHELL-TAINT",
  "title": "Request-derived value reaches a shell/eval sink (Python): subprocess.run()",
  "description": "Value derived from a parameter of line_count() reaches subprocess.run() without validation.",
  "cwe": "CWE-78",
  "cvss_vector": "CVSS:4.0/AV:L/AC:L/AT:N/PR:N/UI:N/VC:H/VI:H/VA:H/SC:H/SI:H/SA:H",
  "cvss_score": 9.4,
  "severity": "critical",
  "evidence": {"file": "server.py", "line": 70, "column": 14,
               "matched_source": "result = subprocess.run(\n        f\"wc -l {target}\",\n        shell=True, ...", "kind": "static"}
}
```

and from `a07-hardcoded-secrets`:

```json
{
  "rule_id": "MCPG-SECRET-HARDCODED",
  "title": "Hardcoded credential (AWS access key id)",
  "cwe": "CWE-798", "severity": "high", "cvss_score": 8.8,
  "evidence": {"file": "server.py", "line": 34,
               "matched_source": "AWS_ACCESS_KEY_ID = \"AKIAQR7WYO35JFXUD3HM\""}
}
```

**Full first-pass result over the corpus [V]** (`--offline --no-cache --format json`):

| Server | findings | rules |
| --- | --- | --- |
| a01 tool-description-injection | 0 | — |
| a02 rug-pull | 0 | — |
| a03 tool-shadowing | 0 | — |
| a04 response-injection | 0 | — |
| a05 argument-exfiltration | 0 | — |
| a06 authless-endpoint | 0 | — |
| a07 hardcoded-secrets | **3** | `MCPG-SECRET-HARDCODED` ×3 (high) |
| a08 unrestricted-file-read | **1** | `MCPG-PY-PATH-TAINT` (high) |
| a09 unrestricted-env-access | 0 | — |
| a10a command-execution | **1** | `MCPG-PY-SHELL-TAINT` (critical) |
| a10b allowlist-bypass | **1** | `MCPG-PY-SHELL-TAINT` (critical) |
| c01 notes-workspace | 1 **(FP)** | `MCPG-PY-PATH-TAINT` (high) |
| c02 webhook-notifier | 0 | — |
| c03 release-runner | 1 **(FP)** | `MCPG-SECRET-HARDCODED` (high) |
| c04 status-service | 0 | — |

Those two control hits are exactly the "realistic-but-safe patterns that naively look
suspicious" the corpus was built for — check them against each control's
`manifest.json` tolerated-findings list before calling them false positives on the
scoreboard.

---

## 5. `MCPKernel` — EXISTS, but DISQUALIFIED by category

**Identity [V].** `https://github.com/piyushptiwari1/mcpkernel`, Apache-2.0 (confirmed via
GitHub API *and* the PyPI classifier), 2 stars, last push 2026-06-16. PyPI `mcpkernel`
**0.3.0**, uploaded 2026-05-25, `requires_python >=3.12`. Install: `pip install "mcpkernel[all]"`.
So every field in the plan's row is correct.

**Why it is nonetheless out.** Its own PyPI summary is
*"Open-source MCP/A2A security gateway — policy enforcement, taint tracking, sandboxed
execution, deterministic envelopes, and Sigstore audit for every AI agent tool call."*
`governance.md` §Which scanners are included says, in terms:
*"Out of scope for v1, by category rather than by judgment of quality: … runtime gateway or
proxy products, which are a different category needing a different harness."*
MCPKernel is precisely that. The plan already half-flags this ("Candidate — runtime harness
may differ"); the governance doc settles it.

It does ship scan-shaped subcommands (`scan-skill`, `poison-scan`, `agent-scan`, `discover`)
[I, from the README — I did not install it], so if you *want* a runtime row later, this is a
reasonable candidate for a separate v1.1 runtime harness. For v1 the honest answer is:
**disqualified by category, recorded in the README so its absence is not read as a verdict.**

Secondary consideration: 2 stars and a single author. Popularity is not an inclusion
criterion and should not be one, but it is worth knowing before spending adapter effort.

---

## 6. Ramparts — NOT ON THE PLAN'S LIST, recommend adding

**Identity [V].** `https://github.com/highflame-ai/ramparts`, **Apache-2.0**, 96 stars, last
push 2026-09-10, latest release tag **v0.8.9**. Rust. Not on PyPI or npm. `cargo install
ramparts` fetched **0.8.8** from crates.io, i.e. crates.io lags the git tag — pin the
version explicitly in the adapter.

**Install [V].** No prebuilt binaries are attached to the GitHub release. I built and ran it
in a container (no Rust on this machine):

```
docker run --rm -v OUT:/out rust:slim sh -c \
  "apt-get update && apt-get install -y pkg-config libssl-dev cmake build-essential && \
   cargo install ramparts --root /out"
# then run it on debian:trixie-slim with libssl3 + ca-certificates
```

Build takes ~10 minutes. Note the binary needs glibc ≥ 2.38, so `debian:bookworm-slim` will
not run a `rust:slim`-built binary — use trixie or build in the final image.
**Containerizable: yes, verified.**

**Credentials [V].** Core scan ran with no key of any kind. The LLM stage is silently skipped
when no provider is configured — no warning in stderr, no entry in the `errors` array. That
silence is a trap for an adapter: it looks like a clean scan.

**A second and worse trap [V]:** `cargo install` does **not** ship the YARA rules. The first
run warned:

```
WARN No YARA rules directory found. Pattern-based detection is DISABLED for this run.
Searched $RAMPARTS_RULES_DIR, the executable directory, ~/.ramparts/rules, and ./rules.
```

The rules live in `rules/pre/*.yar` in the source tarball. The adapter must download the
matching source tag and set `RAMPARTS_RULES_DIR`, or pattern detection is off and the tool
scores zero for reasons that have nothing to do with its detection quality. **This alone
justifies the disclosure round.**

**What we hand it [V].** A live MCP server URL — the best fit of any tool here for our
runtime stage:

```
ramparts scan http://HOST:8101/mcp \
  --auth-headers "Authorization: Bearer lab-token-do-not-reuse" --format json
```

Also `scan-config` (IDE config files) and `skills scan <path>`. Other flags: `--only
tools,prompts,resources`, `--timeout`, `--http-timeout`, `--report`.

**Output [V].** `--format {json,raw,table,text}` plus SARIF 2.1.0 per the README. JSON shape:

```json
{
  "url": "...", "status": "Success", "response_time_ms": 56,
  "server_info": {"name": "docket-summarizer", "version": "1.2.0", "capabilities": [...]},
  "tools": [ {"name": ..., "description": ..., "input_schema": ...} ],
  "security_issues": {"tool_issues": [], "prompt_issues": [], "resource_issues": [],
                      "tool_analysis_details": {}},
  "yara_results": [{"target_type": "summary", "target_name": "pre-scan",
                    "rule_name": "YARA_PRE_SCAN_SUMMARY",
                    "context": "Pre-scan completed: 15 rules executed on 4 items"}],
  "errors": [], "ramparts_version": "0.8.8", "ramparts_commit": "..."
}
```

**Label vocabulary [V]** — 40 YARA rule names across `rules/pre/*.yar` (v0.8.9). The ones
relevant to our taxonomy:

```
PromptInjectionSignature, IndirectPromptInjection, CoerciveInjection, UnicodeSteganography,
CrossOriginEscalation, CapabilityInflation, AutonomyAbuse, CommandInjection, SQLInjection,
PathTraversalVulnerability, SecretsLeakage, EnvironmentVariableLeakage, SSHKeyExposure,
PEMFileAccess, CovertExfiltration, MCPConfigRisk, NetworkReconnaissance, BackdoorPersistence,
SkillCredentialHarvesting, SkillSystemManipulation, SkillToolChainingExfiltration
```

(plus malware/webshell/cryptominer families: `PHPWebshell*`, `ASPXWebshell`, `JSPWebshell`,
`PythonWebshell`, `ReverseShell`, `InfoStealer`, `KeyloggerIndicators`, `RansomwareBehavior`,
`C2FrameworkIndicators`, `ExploitFramework`, `OffensiveToolReferences`, `PhishingKit`,
`PrivilegeEscalationTools`, `CryptoMinerSoftware`, `CryptoMiningPools`,
`CryptoStratumProtocol`, `CryptoCoinjacking`, `HackTools`.)
The README also documents OWASP MCP Top 10 (`MCP01`–`MCP10`) and Agentic Skills Top 10
(`AST01`–`AST10`) tags, plus drift findings `MCPConfigChanged` / `MCPToolChanged` /
`SkillContentChanged` — the latter being another A2 (rug-pull) mechanism. [I, not observed
in my runs because nothing matched.]

**Result on our corpus [V].** With rules correctly wired: **0 findings on all 15 servers.**
`CapabilityInflation` and `CoerciveInjection` did not fire on a01. Reproducible, and a
legitimate published result.

---

## Other candidates found and triaged

Searched independently; these came up and were **not** pursued. All [V] via GitHub API.

| Project | Stars | Licence | Why not (yet) |
| --- | --- | --- | --- |
| `adudley78/mcp-audit` (PyPI `mcp-audit-scanner`) | 3 | Apache-2.0 | Scans *client config files*, not servers or source. Emits SARIF/JSON/CycloneDX. Plausible future row; low signal for our corpus shape. |
| `rob925/mcp-shield` | 1 | MIT | Static heuristics on configs; overlaps sentinel-scan-cli with less structure. |
| `sophiacave/mcp-shield` | 0 | none | **No licence file → fails governance §5.** Exclude. |
| `Abanoub-Rodolf/mcp-scan` | 1 | MIT | Name collides with the Invariant tool; config-file scanner. Would confuse the scoreboard. |
| `badchars/mcp-security-scanner`, `airblackbox/mcp-security-scanner`, `beejak/mcp-sentinel`, `shuka0158/mcp-sentinel`, `Spoonbillguru666/sentinel`, `robdtaylor/sentinel-mcp` | — | mixed | Long tail of similarly named single-author projects. Not triaged individually. |
| `vaultmcp/vault` | — | — | Runtime proxy → out by category, same as MCPKernel. |
| MCPSafetyScanner, CyberMCP, MasterMCP | — | — | Referenced in academic comparisons; mostly agentic/LLM-driven and need model access. Not triaged. [U] |

**A note on the ecosystem that matters for Phase 3/4:** "MCP security scanner" is a heavily
squatted name space. Several of the plan's rows are single-author repos with 0–12 stars
(`sentinel-scan-cli`: 1, `mcpkernel`: 2, `mcp-guard`: 12) sitting next to Cisco (1074) and
Snyk (3059). That is not a reason to exclude them — governance inclusion is by criteria, not
popularity, and the benchmark is more interesting for including small tools — but the
scoreboard should carry stars/last-commit or an equivalent maturity column so a reader is not
misled into thinking these are peers.

---

## Recommendation: which adapters to build first

Build these **four**, in this order. Three is the launch floor; this set gives three
credential-free adapters plus the one that needs a token.

1. **mcp-guard (`SaravanaGuhan/mcp-guard` 2.0.0)** — *build first.* It is the only tool that
   takes our corpus in its native shape (a source directory), needs no credentials, runs
   fully offline, emits stable structured JSON with a fixed 23-rule ID vocabulary, and
   already produces both true positives (a07, a08, a10a, a10b) and control false positives
   (c01, c03). It will exercise the entire pipeline — mapping layer, credit rules, precision
   accounting — on day one. Pin a commit SHA.
2. **Cisco `cisco-ai-mcp-scanner` 4.8.4** — *build second.* Highest-profile tool in the
   category, Apache-2.0, installs cleanly, ships its own Dockerfiles, and its
   `remote --analyzers yara` path is credential-free against our live endpoints. It carries a
   ready-made AITech/AISubtech mapping table in the wheel, which is a gift to the mapping doc.
   Accept that the credential-free row will likely score 0 and say so plainly.
3. **Ramparts 0.8.8/0.8.9** — *build third, and add it to the plan.* Apache-2.0, actively
   maintained, the only tool whose primary input is a live MCP URL, and a genuinely
   independent third vendor — which matters for the neutrality story far more than adding
   another config-file scanner. Adapter must ship the YARA rules and set
   `RAMPARTS_RULES_DIR`, and pin the crates.io version.
4. **Snyk `agent-scan` 0.6.3** — *build fourth,* as soon as someone obtains a free
   `SNYK_TOKEN`. Highest-starred tool in the category and the tool the plan's own evidence
   section is built around; skipping it would be conspicuous. Flag `requires signup` **and**
   `analysis performed server-side / host metadata transmitted` on the row.

**sentinel-scan-cli** is a reasonable fifth but I would not spend Phase 2 time on it before
the four above: it needs the runner to synthesise a manifest file, it is a 1-star project,
and the CLI injects marketing URLs into output. Its one strong argument is `--baseline`,
which is a purpose-built **A2 rug-pull** detector — if A2 coverage turns out to be zero
across the other four, promote it.

**Do not build** an MCPKernel adapter for v1 — disqualified by category under
`governance.md`.

### Concrete plan-table corrections

- `agent-scan` licence is **Apache-2.0**, not "Source-available". [V]
- `mcp-scanner` PyPI name is **`cisco-ai-mcp-scanner`**. [V]
- `mcp-guard` needs a specific repo named; as written the row is unresolvable, and no tool
  in the ecosystem advertises "capability-gap detection". [V]
- `sentinel-scan-cli` is **manifest-file-only** — it reads neither a source dir nor a live
  endpoint, contradicting the implicit assumption that a static scanner takes a directory. [V]
- Cisco's **source-directory** analyzer is LLM-gated, so "No for core (YARA/static)" is
  right about the endpoint path and wrong about the source path. [V]
- Add a **Ramparts** row. [V]

---

## Artifacts left in the scratchpad

```
scratchpad/
  venv1/   cisco-ai-mcp-scanner 4.8.4
  venv2/   snyk-agent-scan 0.6.3
  venv3/   sentinel-scan-cli 1.4.16
  venv4/   mcp-guard 2.0.0
  venv_corpus/  fastmcp 4.0.4 (used only to run our own corpus servers locally)
  ramparts-out/bin/ramparts (linux/arm64, glibc>=2.38), ramparts-out/rules/
  cisco/*.json         Cisco yara scans, 15 servers
  sentinel/*.json      sentinel-scan mcp scans, 15 servers
  mcpguard/*.json      mcp-guard source scans, 15 servers
  ramparts-out/r2-*.json  Ramparts scans with rules wired, 15 servers
  manifests/*.json     tools/list manifests generated per server
  snyk-notoken.err     the SNYK_TOKEN refusal, verbatim
```

Nothing was written to the repository. All corpus servers started for this work were stopped.
