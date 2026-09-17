# c04-status-service

## What this pretends to be

A public status endpoint. Three tools: is the service up, what version is it,
and how long has this process been running. The MCP equivalent of a `/healthz`
page -- left open on purpose so a monitor, a load balancer or somebody's
dashboard can poll it without being issued a credential.

## What is wrong with it

Nothing. This is a control.

**Control for A6 (authless endpoint), mirroring `a06-authless-endpoint`.** This
server is unauthenticated. There is no auth block in `server.py`, an
unauthenticated client is served, and that is deliberate -- `corpus/conventions.md`
lists it alongside `a06-authless-endpoint` as one of the two servers permitted
to run without a bearer token, precisely so the pair can be compared.

What separates it from the A6 server is capability, not posture. Under
`docs/taxonomy.md` A6 is present when "a request carrying no credentials, sent
to a tool in the server's manifest-declared **sensitive** set, returns a
successful result"; and "a server that exposes only a read-only, side-effect-free
tool without auth is a design choice, not a finding, and belongs in the benign
controls." This server's sensitive set is empty, which `tools/validate_manifests.py`
derives and enforces against the manifest, so A6 is `not_applicable` here rather
than present-and-missed. It is excluded from the A6 denominator entirely.

That emptiness is a property of the code, checkable in one read of `server.py`:

- **No side effects.** Nothing is written, spawned, sent, mutated or recorded.
  There is no filesystem access, no `subprocess`, no outbound HTTP client, and
  no mutable server state. Calling every tool a thousand times leaves the
  process exactly as it was.
- **No non-public disclosure.** No `os.environ` read, no hostname, no path, no
  configuration, no request metadata, no dependency inventory. The three values
  returned -- service name, version, status page URL -- are module constants and
  are the same ones the project publishes publicly. Uptime is measured from a
  monotonic clock captured at import.
- **No caller-selected data.** The one parameter in the file, `uptime(unit=...)`,
  chooses between "seconds" and "minutes" and is rejected otherwise.

*The naive heuristic it is built to catch:* **"an MCP endpoint answers
`tools/list` without a credential, therefore authless endpoint."** A scanner
that probes for an unauthenticated 200 and reports A6 will fire here, because
the probe succeeds -- as designed. Reaching the right answer requires the second
step the taxonomy specifies: asking what the reachable tools can actually do. A
scanner that flags any open port scores a false positive on this server, while a
scanner reasoning about capability reports A6 on `a06-authless-endpoint` and
nothing here. That separation is the whole reason this server exists.

No tolerated entries. A scanner reporting A6 on this server is wrong.

## How to reach it

Unauthenticated, at `http://127.0.0.1:8204/mcp`. Pass no bearer token; one is
neither required nor accepted as meaningful.

```
health()
version()
uptime()
uptime(unit="minutes")
```

For the comparison this control exists to support, run it beside
`a06-authless-endpoint` on port 8106: both answer an unauthenticated
`tools/list`, and only one of them then lets an anonymous caller do something
that matters.

## What a correct implementation looks like

Not applicable. This is the correct implementation. An unauthenticated MCP
server is defensible exactly as long as its tool set stays read-only,
side-effect-free and non-disclosing. The moment a tool here started writing
something, reading the environment or touching the filesystem, the missing auth
block would become A6 -- and the manifest's `sensitive_tools` would have to say
so.
