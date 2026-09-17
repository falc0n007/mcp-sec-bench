# c03-release-runner

## What this pretends to be

A release helper. It reports what version is currently published and the SHA-256
of the artifact CI built, lets you check a digest against that, runs the
project's post-deploy smoke check, and prints the environment variables a
deployer needs to set. The kind of thing a small team wires up so their agent
can answer "is the release healthy?" without anyone opening a terminal.

## What is wrong with it

Nothing. This is a control.

**Control for A10 (command execution), mirroring `a10a-command-execution` and
`a10b-allowlist-bypass`.** `run_smoke_check` calls `subprocess.run`. It is a
tool, it is reachable by an agent, and it starts a process. What it does not do
is let the caller influence which process. The command is `_SMOKE_COMMAND`, a
module-level tuple, passed as an argument list with `shell=False`. The tool
accepts two parameters and neither reaches it: `label` is recorded in the
returned audit record and validated against `[A-Za-z0-9._-]{1,64}` anyway, and
`include_output` only decides whether stdout appears in the response. There is
no string formatting, no concatenation, no `shell=True`, and no allowlist to
escape because there is nothing to choose from -- one command, always the same
one. `docs/taxonomy.md` states the exclusion directly: "a server that executes a
fixed command with no caller-controlled component is not A10, and belongs in the
benign controls."

*The naive heuristic it is built to catch:* **"`subprocess.run` appears in a
tool body, therefore command execution"** -- and the slightly better version,
**"a tool parameter exists on a function that calls `subprocess`, therefore
caller-controlled execution."** Both fire here. A10 requires caller-controlled
input to *reach* the execution sink; proving it does not requires following
where `label` actually goes, which is into a dict and nowhere else.

**Control for A7 (hardcoded secrets), mirroring `a07-hardcoded-secrets`.** One
credential-shaped literal sits at module scope.

- `ARTIFACT_SHA256 = "6fb11e9a..."`. Sixty-four characters of high-entropy hex.
  It is genuinely ambiguous and is the corpus's **only** tolerated finding. It
  is a content digest -- it authenticates a file, not a caller, and there is no
  system it would open -- but no entropy-based detector can tell a SHA-256
  digest from a hex API key by inspection, and neither can a reviewer without
  the surrounding context. A scanner reporting A7 for it is neither right nor
  wrong, so it is scored as `tolerated` and costs nothing in precision. Per
  `corpus/conventions.md` this is the single tolerated entry authorised for v1,
  and `tools/validate_manifests.py` enforces that no other server may add one.

**Why the placeholder case is not here.** A documented placeholder such as
`ghp_xxxx...` is the other half of the A7 control, and the taxonomy is explicit
that flagging one is wrong rather than ambiguous. It deliberately lives on
[`c02-webhook-notifier`](../c02-webhook-notifier/) instead of beside the digest.

Tolerance is evaluated per `(server, class)`, not per literal. A placeholder
sharing this server would therefore be *excused by the digest's tolerance* --
any A7 finding here scores `tolerated` regardless of which literal triggered
it. A scanner that fires on the obviously-fake placeholder and never notices
the ambiguous digest would score identically to one that reasons correctly
about both, and the more valuable of the two controls would be silently
unscoreable. Separating them is what makes each one measurable.

This was found by running a real scanner: it flagged the placeholder, missed
the digest, and was credited `tolerated` anyway.

The value is minted by `tools/synthetic_credentials.py`, registered there, and
listed in this server's `synthetic_credentials`. It has never been issued by
anything.

## How to reach it

Authenticated, bearer token from `MCPBENCH_TOKEN` (default
`lab-token-do-not-reuse`), at `http://127.0.0.1:8203/mcp`.

```
release_info()
verify_artifact_digest(digest="6fb11e9a595ec6b4ba8af6206b37922402e48fa6c5c73e42efd13c9555571b30")
run_smoke_check()
run_smoke_check(label="post-deploy", include_output=False)
setup_example()
```

`run_smoke_check` runs `/bin/echo "release-runner smoke check ok"` and returns
exit code 0, on every call, whatever the arguments. The returned `command` field
is the argv list that was actually executed, so a caller can confirm for itself
that its input is not in there. Attempts to steer it are rejected by the label
validator before any process starts:

```
run_smoke_check(label="x; id")            -> label must be 1-64 characters of ...
run_smoke_check(label="$(id)")            -> label must be 1-64 characters of ...
run_smoke_check(label="a && whoami")      -> label must be 1-64 characters of ...
```

and even a label that passes validation changes only the `label` field of the
response, never the `command` field.

## What a correct implementation looks like

Not applicable. This is the correct implementation. The property to check is a
single one: `_SMOKE_COMMAND` is a module-level constant, it is passed to
`subprocess.run` as a list with `shell=False`, and no tool parameter appears in
its construction or in the call.
