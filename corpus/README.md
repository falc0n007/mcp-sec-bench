# The corpus

15 MCP servers: 11 with exactly one deliberate flaw each, and 4 benign controls.

Read [conventions.md](conventions.md) before adding or changing anything here.
Ground truth for each server is its `manifest.json`, validated by
`tools/validate_manifests.py`. The definitions being tested against live in
[../docs/taxonomy.md](../docs/taxonomy.md).

## Vulnerable servers

One flaw each. That is what keeps attribution clean when a scanner half-fires.

| Server | Port | Class | Surface | What it pretends to be |
| --- | --- | --- | --- | --- |
| [`a01-tool-description-injection`](a01-tool-description-injection/) | 8101 | A1 | static | Docket, a document summarizing service that stores short text documents in memory and returns extractive summaries and keywords. |
| [`a02-rug-pull`](a02-rug-pull/) | 8102 | A2 | static/runtime | A changelog fetcher that serves and summarises a project's recent release notes. |
| [`a03-tool-shadowing`](a03-tool-shadowing/) | 8103 | A3 | static | Pagelane, an alert routing service that assigns operational alerts to channels by severity policy and keeps a short acknowledgeable history. |
| [`a04-response-injection`](a04-response-injection/) | 8104 | A4 | runtime | A feed digest reader that serves cached third-party news items for an agent to summarize. |
| [`a05-argument-exfiltration`](a05-argument-exfiltration/) | 8105 | A5 | runtime | A spellcheck helper that checks passages against a built-in dictionary and guesses their language. |
| [`a06-authless-endpoint`](a06-authless-endpoint/) | 8106 | A6 | runtime | An internal inventory admin service for the warehouse team to inspect, export, and adjust stock records. |
| [`a07-hardcoded-secrets`](a07-hardcoded-secrets/) | 8107 | A7 | static | A cloud cost reporter that estimates month-to-date spend and attributes it to recent release tags. |
| [`a08-unrestricted-file-read`](a08-unrestricted-file-read/) | 8108 | A8 | static | A support-ticket attachment viewer that reads files a customer attached to a ticket. |
| [`a09-unrestricted-env-access`](a09-unrestricted-env-access/) | 8109 | A9 | static | A deployment configuration inspector that reports runtime facts and looks up named config values. |
| [`a10a-command-execution`](a10a-command-execution/) | 8110 | A10a | static | A repository inspection helper that wraps a few Unix commands to count lines and report disk space. |
| [`a10b-allowlist-bypass`](a10b-allowlist-bypass/) | 8111 | A10b | static | A build-tool runner that executes project build commands restricted to an allowlist of permitted tools. |

## Benign controls

These are what make precision meaningful. Without them a scanner that flags
everything scores perfectly. Each one contains a realistic pattern that looks
suspicious to a naive detector but is genuinely correct, so **a scanner
flagging one is scored as a false positive**.

| Server | Port | Control for | What it pretends to be |
| --- | --- | --- | --- |
| [`c01-notes-workspace`](c01-notes-workspace/) | 8201 | A8, A9 | A personal notes workspace that lists, reads and searches Markdown notes held under one workspace directory. |
| [`c02-webhook-notifier`](c02-webhook-notifier/) | 8202 | A5 (and the A3 shadow target) | A notifier that posts a short message to a webhook endpoint the caller supplies on every call. |
| [`c03-release-runner`](c03-release-runner/) | 8203 | A10, A7 | A release helper that reports the published build's metadata and runs the project's fixed post-deploy smoke check. |
| [`c04-status-service`](c04-status-service/) | 8204 | A6 | A public status endpoint reporting liveness, published version and process uptime, and nothing else. |

Exactly one tolerated finding exists corpus-wide: `c03-release-runner`
tolerates A7 for its high-entropy build-artifact digest, which is genuinely
ambiguous. Everything else flagged on a control is a false positive, by design.

## Verifying

```bash
python tools/validate_manifests.py        # ground truth is well-formed and scoreable
python tools/check_no_real_credentials.py # no unregistered credential-shaped literal
python tools/smoke_server.py --all        # every server boots and matches its manifest
python tools/verify_lab.py                # against a running lab: reachability, egress, sinkhole
```
