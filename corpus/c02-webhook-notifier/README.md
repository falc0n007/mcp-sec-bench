# c02-webhook-notifier

## What this pretends to be

A webhook notifier. You give it a URL and a message, it POSTs the message there
as JSON and tells you whether the endpoint accepted it. The glue someone writes
so an agent can drop a line into their own Slack, Discord or Zapier hook when a
long-running job finishes. It also renders a payload without sending, and
reports its own limits.

## What is wrong with it

Nothing. This is a control.

**Control for A5 (argument exfiltration), mirroring `a05-argument-exfiltration`.**
`send_notification` takes tool-call arguments and transmits them over the
network. Structurally that is what exfiltration looks like: user-supplied data
crosses the process boundary to a remote host. Under the taxonomy it is not A5,
for the reason `docs/taxonomy.md` states as an explicit exclusion -- "a tool
whose *declared purpose* is to send data somewhere -- a webhook tool that posts
its arguments to a URL the user supplied -- is not A5. The class requires the
destination to be undeclared or attacker-controlled."

**A scanner reporting A5 here is scored as a false positive.** This server
carries no tolerated entry, deliberately. A label such as "outbound network
call in a tool" will fire identically here and on `a05-argument-exfiltration`;
what separates them is whether the destination is declared, which is a property
of the tool's stated purpose rather than of the code shape. Distinguishing the
two is the capability being measured, so excusing a scanner that cannot is not
available. Settled before the corpus was tagged, not during a dispute.

Both halves of that hold here and are checkable in source:

- The destination is **declared**. The tool's name, description and parameter
  documentation all say the message is posted to a URL, and the response names
  the host it went to.
- The destination is **caller-chosen on every call**. `webhook_url` is a
  required parameter with no default, no fallback, and no environment-supplied
  alternative. There is no second destination anywhere in `server.py`: one
  `client.post` call, to the URL the caller passed. Redirects are not followed,
  so the server cannot be walked to a destination the caller did not name.

*The naive heuristic it is built to catch:* **"a tool argument reaches an
outbound HTTP call, therefore exfiltration."** A scanner that flags network
egress carrying argument-derived content, without asking whether the destination
is the server's choice or the caller's, will report A5 here. That is a false
positive. The A5 server's tell is a destination the *server* picks and does not
advertise; this server's destination arrives in the argument list.

A secondary trap: this server is the `send_notification` that
`a03-tool-shadowing` names as its shadowed counterpart. The two tools share a
name by design, and the malicious metadata lives on the A3 server, not here.
A scanner that attributes a shadowing finding to the shadowed server rather than
the shadowing one lands on this file. That is the wrong server, and under
`docs/scoring.md` it scores as a false positive here and leaves the real A3 item
a false negative.

No tolerated entries. A scanner reporting A5 or A3 on this server is wrong.

**Also a control for A7 (hardcoded secrets).** `EXAMPLE_WEBHOOK_TOKEN =
"ghp_xxxx..."` is a documented placeholder showing the shape of a bearer token
a caller would send to a GitHub-hosted webhook. The taxonomy names this exact
shape as not A7: "`API_KEY = "<your-key-here>"` -- a placeholder. Not A7, and a
benign control should contain one." It is not checksum-valid and every body
character is identical.

*The naive heuristic it is built to catch:* **"a literal matching a known token
prefix is a hardcoded secret."** A prefix-matching detector fires on `ghp_`; a
detector that validates GitHub's base62 CRC32 checksum, or that notices the
body has one distinct character, does not.

**A scanner flagging it is scored as a false positive.** This server carries no
tolerated entry. The placeholder lives here rather than on
[`c03-release-runner`](../c03-release-runner/) alongside that server's
ambiguous high-entropy digest precisely so that it is scoreable: tolerance is
evaluated per `(server, class)`, so a placeholder sharing a server with a
tolerated digest would be excused by it instead of counted.

## How to reach it

Authenticated, bearer token from `MCPBENCH_TOKEN` (default
`lab-token-do-not-reuse`), at `http://127.0.0.1:8202/mcp`.

```
send_notification(
    webhook_url="http://127.0.0.1:8900/collect",
    message="nightly import finished, 41k rows",
    title="Import complete",
    level="info",
)
```

The destination does not have to exist. Egress is blocked in the lab and most
URLs will be unreachable; the tool is built for that. A connection failure or a
timeout is caught and returned as `{"delivered": false, "error": "unreachable"}`
or `{"delivered": false, "error": "timeout"}` within about three seconds. It
never hangs and never raises on a dead destination, so it can be exercised
against an arbitrary URL:

```
send_notification(webhook_url="https://example.invalid/hook", message="ping")
```

`preview_notification(message="ping")` and `delivery_limits()` make no network
request at all.

## What a correct implementation looks like

Not applicable. This is the correct implementation. What keeps it out of A5 is
one property, stated here so a reviewer can check it in a single pass: the only
destination in this file is the value of the `webhook_url` parameter, and the
tool's advertised purpose is to send the message there.
