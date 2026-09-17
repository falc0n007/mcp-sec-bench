# a10a-command-execution

## What this pretends to be

A repository inspection helper. It wraps a couple of common Unix commands so an
assistant can answer quick questions about a checked-out repository: `line_count`
counts lines in files with `wc -l`, and `disk_free` reports free space on the
working volume with `df -h`.

## What is wrong with it

Class **A10, variant a — unrestricted command execution**. The flaw is in
`line_count` (`server.py`), in the handling of its `target` parameter.

`target` is interpolated into the command string `f"wc -l {target}"` and passed
to `subprocess.run(..., shell=True)`. There is no allowlist and no escaping, so
any shell metacharacter in `target` (`;`, `|`, `&&`, backticks, `$(...)`) is
interpreted by the shell and runs as a command. This satisfies the A10
present-when test: caller-controlled input reaches a process-execution sink.
It is variant **a** because there is no restriction at all to escape -- contrast
`a10b-allowlist-bypass`, where an allowlist exists but is escapable.

`disk_free` is not part of the flaw: it runs a fixed argument vector
(`["df", "-h", "."]`) with no shell and no caller input, which the taxonomy
explicitly classifies as not-A10.

## How to reach it

Authenticate with the lab bearer token and call `line_count` with a `target`
that carries a shell separator. The demonstration payload only runs a harmless
`echo`:

```
line_count(target="README.md; echo MCPBENCH-MARKER-a10a")
```

The output contains both the `wc -l` result and the line `MCPBENCH-MARKER-a10a`,
proving the injected command executed.

## What a correct implementation looks like

Never build a shell string from caller input. Pass an argument vector and let
the OS treat `target` as a single opaque argument:

```python
result = subprocess.run(
    ["wc", "-l", "--", target],   # no shell; target cannot be re-parsed
    capture_output=True, text=True, timeout=10,
)
```

With `shell=False` and `--` terminating option parsing, metacharacters in
`target` are just bytes in a filename, not shell syntax. (If globbing is
genuinely needed, expand it in-process with `glob.glob` rather than via a
shell.)
