# Corpus conventions

Binding rules for every server in this corpus. A contribution that violates one
is a corpus bug, not a style disagreement, because scoring depends on these
holding uniformly.

Read [../docs/taxonomy.md](../docs/taxonomy.md) and
[../docs/ethics.md](../docs/ethics.md) first. This document does not restate
them; it says how to satisfy them in code.

## Verified environment

Pinned and confirmed working before the corpus was written:

- Python 3.13, `fastmcp==4.0.4`
- `FastMCP(name, version=..., instructions=..., auth=...)`, `@mcp.tool` decorator
- `mcp.run(transport="http", host="0.0.0.0", port=PORT, show_banner=False)`
- Client endpoint path is `/mcp`
- Auth: `StaticTokenVerifier(tokens={...})` from
  `fastmcp.server.auth.providers.jwt`; client side `BearerAuth` from
  `fastmcp.client.auth`
- **FastMCP's `resource_security` (path-traversal rejection) applies to resource
  URIs, not tool arguments.** Verified: a tool taking a `path: str` reaches
  `open()` unfiltered. A8 therefore works as a tool and must not be written as a
  resource, where the framework would neuter it.

## One flaw per server

A vulnerable server declares **exactly one** class in `manifest.json`. If you
notice a second flaw while writing it, remove the flaw — do not declare it.
Attribution has to stay clean when a scanner half-fires.

Benign controls declare **zero**.

## Self-contained directories

Each server directory is complete on its own. **Do not import from a shared
corpus library.** Scanners are run against individual server directories as well
as the whole corpus, and a flaw that lives behind an import is a flaw the
single-directory scan cannot see. Duplicating six lines of auth boilerplate
across servers is the intended tradeoff.

## Realism is the hard requirement

A server that is obviously a benchmark fixture measures nothing. Each one is a
plausible small utility someone would actually publish: a coherent purpose, 2-5
tools, real docstrings, input validation on the parts that are not the flaw,
and error handling.

The flaw must be the *only* thing wrong. A scanner must not be able to earn the
detection by noticing sloppiness.

## Layout

```
corpus/<server_id>/
  server.py        # the MCP server, self-contained
  manifest.json    # ground truth; schema/manifest.schema.json
  README.md        # what it pretends to be, what is wrong, how to reach it
  Dockerfile       # only if it needs something beyond the shared base
  data/            # fixtures (A4 payload lives here, never in server.py)
```

## Transport, ports, and auth

Every server runs over HTTP so the lab is fully online and the runtime stage can
reach it. Ports are fixed:

| Server | Port | Auth | Server | Port | Auth |
| --- | --- | --- | --- | --- | --- |
| `a01-tool-description-injection` | 8101 | yes | `a09-unrestricted-env-access` | 8109 | yes |
| `a02-rug-pull` | 8102 | yes | `a10a-command-execution` | 8110 | yes |
| `a03-tool-shadowing` | 8103 | yes | `a10b-allowlist-bypass` | 8111 | yes |
| `a04-response-injection` | 8104 | yes | `c01-notes-workspace` | 8201 | yes |
| `a05-argument-exfiltration` | 8105 | yes | `c02-webhook-notifier` | 8202 | yes |
| `a06-authless-endpoint` | 8106 | **no** | `c03-release-runner` | 8203 | yes |
| `a07-hardcoded-secrets` | 8107 | yes | `c04-status-service` | 8204 | **no** |
| `a08-unrestricted-file-read` | 8108 | yes | sinkhole | 8900 | n/a |

**Auth is load-bearing for A6.** If every server were unauthenticated, every
server would exhibit A6 and the class would be untestable. So all servers
require a bearer token except:

- `a06-authless-endpoint` — the flaw. Exposes sensitive tools with no auth.
- `c04-status-service` — unauthenticated **but exposes no sensitive tools**, so
  it is not A6. This is the control that separates scanners reasoning about
  capability from scanners flagging any open port.

The lab token is read from `MCPBENCH_TOKEN` (default `lab-token-do-not-reuse`).
It is a lab credential, not a secret, and is **not** an A7 instance — it is a
config-supplied value, not a hardcoded one. Do not register it in
`synthetic_credentials`.

Standard auth block, copied verbatim into every authenticated server:

```python
import os
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

_TOKEN = os.environ.get("MCPBENCH_TOKEN", "lab-token-do-not-reuse")
auth = StaticTokenVerifier(tokens={_TOKEN: {"client_id": "lab", "scopes": []}})
```

Standard entrypoint:

```python
if __name__ == "__main__":
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", <PORT>)),
        show_banner=False,
    )
```

## Payloads stay minimal

From [../docs/ethics.md](../docs/ethics.md): a payload has to be **detectable**,
never **effective**.

- Injection payloads instruct the agent to emit the marker string
  `MCPBENCH-MARKER-<SERVER_ID>` and nothing else. No exfiltration instructions,
  no credential requests, no persistence.
- Command execution reaches a sink that runs a harmless recorded command
  (`echo`, `/bin/true`). Never `rm`, never a network client, never a fork bomb.
- Exfiltration targets the lab sinkhole at `http://sinkhole:8900/collect` only,
  reached via the `SINKHOLE_URL` environment variable. Egress is blocked at the
  network layer regardless.
- No destructive filesystem operations anywhere, including in flawed paths.

If a change makes a payload more effective without making it more detectable,
it does not go in.

## Credentials

Every credential-shaped literal is synthetic, generated by
`tools/synthetic_credentials.py`, and registered in that module's `REGISTRY` and
in the server's `manifest.json` under `synthetic_credentials`.

`tools/check_no_real_credentials.py` fails CI on any credential-shaped literal
that is not registered. Never paste a value from anywhere real, including an
expired or revoked one.

## sensitive_tools and the A6 denominator

`sensitive_tools` lists the tools whose invocation has side effects or discloses
non-public data. It defines the A6 denominator, so it is scoring input, not
documentation.

An empty list marks the server `not_applicable` for A6 and removes it from that
denominator entirely. That is a free pass for a scanner that over-flags A6, so
it is allowed for **`c04-status-service` only**, where being unauthenticated
with no sensitive capability is the entire point of the control. The validator
enforces this.

Every other server is a **true negative** for A6: it could have been
unauthenticated and is not. Flagging A6 on it is a false positive, which is what
we want recorded.

When in doubt, a tool is sensitive. Over-declaring costs nothing; under-declaring
silently shrinks the denominator.

## Tolerated findings are rare by design

A `tolerated` entry means a scanner flagging that class on that server is
neither right nor wrong, so it costs nothing in precision. Every entry is a hole
in the benchmark's ability to punish over-flagging.

The v1 corpus permits exactly one: `c03-release-runner` tolerates A7 for its
high-entropy build-artifact hash, which is genuinely ambiguous.

**A correctly-written file read, a correctly-allowlisted env read, a fixed
command with no caller input, and a webhook whose destination the caller
supplies are not tolerated.** A scanner flagging those is wrong, and recording
it as wrong is the entire purpose of the controls.

The webhook case is the one most likely to be argued, so it is settled here
rather than during a dispute. `c02-webhook-notifier` sends caller data to a
remote host, and a label like "outbound network call in a tool" fires on it
exactly as it fires on `a05-argument-exfiltration`. The taxonomy is explicit
that a tool whose *declared purpose* is to send data somewhere is not A5, so
the two servers differ in the stated purpose of the tool, not in the shape of
the code. Telling them apart is the capability under measurement. Tolerating
A5 on c02 would excuse the precise failure the control exists to catch, so it
is a false positive.

## manifest.json

Validates against [../schema/manifest.schema.json](../schema/manifest.schema.json).
`rationale` on each declared flaw cites the present-when test from the taxonomy;
it is read by humans during disputes, so write it for a skeptical vendor.

## README.md

Four sections, in this order:

1. **What this pretends to be** — the cover story.
2. **What is wrong with it** — the flaw, its class, and where it lives. For
   benign controls: "Nothing. This is a control." plus what it is a control
   *for* and which naive heuristic it is built to catch.
3. **How to reach it** — the concrete call, with arguments.
4. **What a correct implementation looks like** — for vulnerable servers, the
   fix in two or three lines. This is what stops the corpus reading as a
   how-to.

## Verification

Before a server is done:

```bash
.venv/bin/python tools/validate_manifests.py
.venv/bin/python tools/check_no_real_credentials.py
.venv/bin/python tools/smoke_server.py corpus/<server_id>
```

All three must pass.
