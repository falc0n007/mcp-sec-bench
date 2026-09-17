# The lab

Brings the whole corpus online in one command, sandboxed.

```bash
docker compose -f lab/docker-compose.yml up --build -d
```

Then verify it is actually what it claims to be:

```bash
.venv/bin/python tools/verify_lab.py
```

Tear down with `docker compose -f lab/docker-compose.yml down`.

## What is running

17 containers: 11 vulnerable servers, 4 benign controls, a sinkhole, and a
gateway. Ports are listed in [../corpus/conventions.md](../corpus/conventions.md)
and bound to `127.0.0.1` only.

Every server speaks MCP over HTTP at `/mcp`. All but two require a bearer token,
default `lab-token-do-not-reuse`, overridable with `MCPBENCH_TOKEN`:

```bash
MCPBENCH_TOKEN=something-else docker compose -f lab/docker-compose.yml up -d
```

That token is lab configuration, not a secret, and deliberately not an A7
instance -- it arrives as config rather than as a hardcoded literal.

## Network design

This is the part that implements the sandboxing commitment in
[../docs/ethics.md](../docs/ethics.md), so it is worth understanding rather than
copying.

```
  host ──▶ gateway ──▶ [ lab network, internal: true ]
           (edge +           │
            lab)             ├── 11 vulnerable servers
                             ├── 4 benign controls
                             └── sinkhole
```

- Corpus servers are attached **only** to `lab`, which is `internal: true`.
  Verified in `tools/verify_lab.py`: outbound TCP fails and DNS does not
  resolve.
- Docker will not publish ports from an internal network to the host, so
  `gateway` is attached to both networks and forwards each corpus port through.
  It is the only container touching `edge`, so no corpus server can reach the
  internet.
- `sinkhole` is the only destination reachable from `lab`. It records
  exfiltration attempts and drops them, which is what makes A5 observable
  without anything leaving.

Containers run as `nobody`, read-only, with `no-new-privileges`.

## The sinkhole

```
POST /collect    record an attempt, 204
GET  /captures   everything recorded, as JSON
POST /reset      clear the log, 204
GET  /health     liveness
```

Inspect what a run captured:

```bash
curl -s http://127.0.0.1:8900/captures | python3 -m json.tool
```

## A trap worth knowing about

`http.server.HTTPServer.server_bind` calls `socket.getfqdn()`, which performs a
reverse DNS lookup. The lab blocks DNS by design, so the stock implementation
**hangs before it ever listens** -- no error, no output, just a process that
never binds. `lab/sinkhole/sinkhole.py` overrides `server_bind` to skip it.

Anything added to this lab that uses `http.server` needs the same treatment.
Uvicorn, which FastMCP uses, is unaffected.

## Talking to a server

```python
import asyncio
from fastmcp import Client
from fastmcp.client.auth import BearerAuth

async def main():
    async with Client("http://127.0.0.1:8108/mcp",
                      auth=BearerAuth("lab-token-do-not-reuse")) as c:
        print([t.name for t in await c.list_tools()])

asyncio.run(main())
```

`a06-authless-endpoint` (8106) and `c04-status-service` (8204) take no auth --
that is the point of both.

## Rebuilding after a corpus change

The image bakes in `corpus/`, so a source change needs a rebuild:

```bash
docker compose -f lab/docker-compose.yml up --build -d
```
