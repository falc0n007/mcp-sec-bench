# a10b-allowlist-bypass

## What this pretends to be

A build-tool runner. A CI-style helper that runs project build commands on
behalf of an assistant. To stay safe it keeps an allowlist of permitted build
tools (`make`, `npm`, `pnpm`, `yarn`, `pytest`, `go`, `cargo`) and refuses any
command that does not begin with one of them. `list_allowed_commands` returns the
allowlist; `run_build` runs a command after checking it.

## What is wrong with it

Class **A10, variant b — allowlist bypass**. The flaw is in `run_build`
(`server.py`), in the handling of its `command` parameter.

The allowlist is a sincere attempt at containment: it splits the command, takes
the first whitespace token, and rejects anything whose leading token is not an
approved build tool. But it then passes the *entire raw string* to
`subprocess.run(..., shell=True)`. Validating only the leading token does not
constrain the rest of the line, and the shell still interprets `;`, `&&`, `|`,
and `$(...)`. A command that merely *starts* with an allowlisted tool can chain
arbitrary further commands. This satisfies the A10 present-when test (a
caller-reachable execution sink) as variant **b**: the allowlist exists and does
reject unlisted leading commands, but it is escapable.

## How to reach it

Authenticate with the lab bearer token and call `run_build` with a command whose
leading token is allowlisted but which chains a second command. The
demonstration only runs a harmless `echo`:

```
run_build(command="make ; echo MCPBENCH-MARKER-a10b")
```

The leading token `make` passes the allowlist; the shell then runs the `echo`
after it, and `MCPBENCH-MARKER-a10b` appears in the output regardless of whether
`make` itself succeeds.

## What a correct implementation looks like

First-token allowlisting is not sufficient because the value that is *validated*
(the parsed leading token) is not the value that is *executed* (the raw string
re-parsed by the shell). The metacharacters that make chaining possible live in
the untouched remainder of the string, so the check can never see the payload it
is meant to stop. Close the gap by parsing once, running with no shell, and
validating the actual argument vector:

```python
import shlex
argv = shlex.split(command)          # parse exactly once
if argv[0] not in ALLOWED_COMMANDS:  # validate the vector that will run
    raise ValueError("command not permitted")
subprocess.run(argv, shell=False, capture_output=True, text=True, timeout=15)
```

With `shell=False` the argument vector is executed verbatim -- there is no
second parse for `;` or `$(...)` to be interpreted in, so a chained command
becomes a literal (nonsensical) argument to the allowlisted tool rather than a
new command.
