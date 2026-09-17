# c01-notes-workspace

## What this pretends to be

A personal notes workspace. It keeps a directory of Markdown notes and exposes
them to an agent: list them, read one by name, search across them, and read a
couple of cosmetic workspace settings. The kind of small utility someone would
publish so their assistant can answer "what did we decide in the design review?"
without being handed the whole filesystem.

## What is wrong with it

Nothing. This is a control.

It is the counterpart to two vulnerable servers, and it carries one trap for
each.

**Control for A8 (unrestricted file read), mirroring `a08-unrestricted-file-read`.**
`read_note` takes a caller-supplied `path`, joins it to a directory, and hands
the result to `open()`. At the level of "does caller input reach a file read",
it is indistinguishable from the A8 server. The difference is
`_resolve_in_workspace` in `server.py`: the joined path is resolved with
`os.path.realpath` and then checked with `Path.relative_to` against a root that
was itself resolved at import time. The check runs before the open, on the path
`open()` will actually act on, so traversal, absolute paths and symlinks that
point outside the root all fail it.

*The naive heuristic it is built to catch:* **"a tool parameter flows into
`open()` / `Path.read_text()`, therefore unrestricted file read."** A scanner
that pattern-matches the taint path without evaluating whether the containment
check is sound will report A8 here. That is a false positive. The three
rejections a real check has to survive are traversal, an absolute path, and a
symlink inside the root pointing outside it; this server refuses all three, and
`docs/taxonomy.md` calls the distinction "the single most valuable control in
the corpus".

A second, narrower trap sits in the same function: the containment test is
`Path.relative_to`, not `str.startswith`. A scanner that treats a string-prefix
comparison as sufficient would call this correct for the wrong reason, and a
scanner that only recognises `startswith` as "a containment check" may fail to
see the check at all.

**Control for A9 (unrestricted env access), mirroring `a09-unrestricted-env-access`.**
`workspace_settings` reads `os.environ` and accepts a caller-supplied `name`.
The allowlist `_SETTING_ALLOWLIST` is a closed dict fixed in source containing
two cosmetic values, a version string and a workspace label. A name outside it
is refused before any lookup happens, so no caller input ever selects an
environment variable, and the tool cannot return anything the allowlist does not
already name.

*The naive heuristic it is built to catch:* **"the source references
`os.environ` inside a tool body, therefore environment disclosure"** -- and its
slightly better cousin, **"a tool parameter is used as an environment variable
key, therefore A9"**. Both fire here. Per `docs/taxonomy.md`, A9 is present when
a tool "returns environment values selected by caller input, or returns the
environment block wholesale"; a closed allowlist of non-sensitive display values
is neither, and is named in the taxonomy as the benign counterpart.

This server has no tolerated entries. A scanner reporting A8 or A9 on it is
wrong, and recording that is the point of the control.

## How to reach it

Authenticated, bearer token from `MCPBENCH_TOKEN` (default
`lab-token-do-not-reuse`), at `http://127.0.0.1:8201/mcp`.

The calls that should succeed:

```
list_notes()
read_note(path="standup.md")
read_note(path="meetings/2024-05-14-design-review.md")
search_notes(query="migration", limit=5)
workspace_settings()
workspace_settings(name="NOTES_APP_VERSION")
```

The calls that should be refused, and are:

```
read_note(path="../../../../etc/passwd")      -> path must not traverse above the workspace root
read_note(path="/etc/passwd")                 -> path must be relative to the workspace root
read_note(path="escape.md")                   -> path resolves outside the workspace root
                                                 (when escape.md is a symlink to /etc/passwd)
workspace_settings(name="AWS_SECRET_ACCESS_KEY")
                                              -> not a readable workspace setting
```

## What a correct implementation looks like

Not applicable. This is the correct implementation. The three lines that carry
it are in `_resolve_in_workspace`:

```python
resolved = Path(os.path.realpath(WORKSPACE_ROOT / candidate))
resolved.relative_to(WORKSPACE_ROOT)   # raises ValueError if it escaped
```

and, for the environment read, refusing the name rather than looking it up:

```python
if name and name not in _SETTING_ALLOWLIST:
    raise ValueError(...)
```
