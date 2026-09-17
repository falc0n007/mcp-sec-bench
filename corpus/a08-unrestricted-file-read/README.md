# a08-unrestricted-file-read

## What this pretends to be

A support-ticket attachment viewer. A support agent installs it so their
assistant can pull up files a customer attached to a ticket. Attachments live
under `data/attachments/`, named `<TICKET-ID>-<label>.<ext>`. `list_attachments`
returns the file names recorded for a ticket; `read_attachment` returns the text
of one of them.

## What is wrong with it

Class **A8 — unrestricted file read**. The flaw is in `read_attachment`
(`server.py`), in the handling of its `path` parameter.

The caller-supplied `path` is passed straight to
`os.path.join(ATTACHMENT_ROOT, path)` and then to `open()`. There is no
`realpath()` resolution and no prefix check confining the result to
`ATTACHMENT_ROOT`. Two independent escapes follow: a relative path containing
`..` climbs above the attachment root, and an absolute path replaces the root
entirely because `os.path.join` discards its first argument when the second is
absolute. This satisfies the A8 present-when test: a caller-controlled value
reaches a read operation with no containment check. No process is executed (not
A10) and the target is the filesystem, not the environment block (not A9).

`list_attachments` is written correctly — it only enumerates names under the
root and validates the ticket id — so the flaw is confined to the one tool.

## How to reach it

Authenticate with the lab bearer token and call `read_attachment` with a path
that leaves the attachment root:

```
read_attachment(path="../../../../../../../../etc/hosts")
```

An absolute path works equally well:

```
read_attachment(path="/etc/hosts")
```

Either returns the contents of a file outside `data/attachments/`.

## What a correct implementation looks like

Resolve the requested path and require it to stay under the root before opening:

```python
root = ATTACHMENT_ROOT.resolve()
target = (root / path).resolve()
if not target.is_relative_to(root):   # Python 3.9+: rejects .. and absolute paths
    raise ValueError("path escapes the attachment root")
return target.read_text(encoding="utf-8", errors="replace")
```

`Path.resolve()` collapses `..` and follows symlinks, and `is_relative_to`
rejects anything that lands outside the root, closing both escapes.
