# Captured Cisco mcp-scanner output

Every file here except the two prefixed `SYNTHETIC-` is byte-for-byte stdout from
`cisco-ai-mcp-scanner` **4.8.4** running in
`mcp-sec-bench/cisco-mcp-scanner:4.8.4`, captured on 2026-09-17 against the lab
at `corpus_version v1-0f9650d5044b`. They exist so `tests/test_adapter_cisco.py`
can check the parser, and so `mapping/cisco-mcp-scanner.json` can claim
`label_provenance: captured-from-real-output` against something a reviewer can
read.

| File | Invocation | Why it is here |
| --- | --- | --- |
| `remote-a01-yara.json` | `--analyzers yara --raw remote --server-url .../8101/mcp --bearer-token ...` | The central result. Four SAFE verdicts, and the A1 payload reproduced verbatim in `tool_description`. Proof the scanner read the text and did not fire. |
| `remote-a02-yara-call1-clean.json` | same, against 8102 on a freshly restarted instance | `tools/list` call 1 of 4. The clean descriptor, no findings. |
| `remote-a02-yara-call4-mutated.json` | same, `tools/list` call 4 | The mutated descriptor, and the only `PROMPT INJECTION` this corpus produced. |
| `remote-a01-yara-readiness.json` | `--analyzers yara,readiness` | Why `readiness` is not in the default set: HIGH on every tool, 7 findings each, under the literal threat name `unknown`. |
| `instructions-a01-yara.json` | `... instructions --server-url ...` | The `instructions` surface returns `findings` as a LIST, not a mapping. The parser handles both because both are real. |
| `label-probe-yara.json` | `... static --tools label-probe-tools.json` | All seven observable threat names in one capture, including two items carrying two names each. Input is `label-probe-tools.json`, a synthetic descriptor set written to elicit each rule; the corpus triggers only one of the seven. |
| `label-probe-tools.json` | (input) | The synthetic descriptors above. Not corpus content. The AWS key in it is Amazon's published documentation example value and authenticates nowhere. |
| `failed-scan-no-token.{stdout,stderr,exit}` | `remote` against an authenticated server with no token | A failed scan: empty stdout, the error on stderr, exit 1. Distinguishing this from "found nothing" is the adapter's job. |
| `SYNTHETIC-unlabelled-finding.json` | hand-written | Not vendor output. An analyzer block with `total_findings > 0` and no `threat_names`, to exercise the no-silent-drop path. Never seen in 4.8.4 output; the adapter handles it because the adapter contract forbids dropping findings. |
| `SYNTHETIC-malformed.txt` | hand-written | Truncated JSON, to exercise the parse-failure path. |
