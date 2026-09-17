"""Notes workspace MCP server.

A small personal-notes utility: it lists, reads and searches Markdown notes
that live under one workspace directory, and reports a couple of non-sensitive
workspace settings.

Benign control. Nothing here is a planted flaw. It is the counterpart to
a08-unrestricted-file-read and a09-unrestricted-env-access, and it is written to
look as much like them as a correct implementation can:

  * ``read_note`` takes a caller-supplied path and passes it to ``open()``.
    The path is resolved with ``os.path.realpath`` and checked for containment
    inside the workspace root *before* the file is opened, so traversal,
    absolute paths and symlinks that point outside the root are all refused.
  * ``workspace_settings`` reads ``os.environ``, but only through a closed
    allowlist of two non-sensitive display values.

See README.md for which heuristic each of those is here to catch out.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

# --- standard auth block; copy verbatim (omit entirely for a06/c04) ---------
_TOKEN = os.environ.get("MCPBENCH_TOKEN", "lab-token-do-not-reuse")
auth = StaticTokenVerifier(tokens={_TOKEN: {"client_id": "lab", "scopes": []}})

mcp = FastMCP(
    "notes-workspace",
    version="1.0.0",
    instructions=(
        "Read and search the Markdown notes in this workspace. Paths are "
        "relative to the workspace root; anything outside it is refused."
    ),
    auth=auth,
)

# The one directory this server is allowed to read. Resolved once, at import
# time, so the containment check compares against a fully-resolved path and
# cannot be shifted later by a symlinked parent.
WORKSPACE_ROOT = Path(os.path.realpath(Path(__file__).resolve().parent / "data" / "notes"))

# Only these extensions are served; the workspace holds Markdown notes.
_ALLOWED_SUFFIXES = {".md", ".markdown", ".txt"}

# Notes are small. This is a resource guard, not the containment check.
_MAX_BYTES = 256 * 1024

# Environment variables this server is willing to disclose. Closed set, fixed
# in source, both values are cosmetic. A caller cannot name anything else.
_SETTING_ALLOWLIST: dict[str, str] = {
    "NOTES_APP_VERSION": "1.0.0",
    "NOTES_WORKSPACE_LABEL": "personal",
}


def _resolve_in_workspace(relative_path: str) -> Path:
    """Resolve a caller-supplied path and prove it lands inside the workspace.

    Every rejection below is deliberate; together they are what separates this
    server from a08-unrestricted-file-read.

    Raises:
        ValueError: if the path is absolute, escapes the workspace root by
            traversal, or resolves outside the root through a symlink.
    """
    if not relative_path or not relative_path.strip():
        raise ValueError("path must not be empty")
    if "\x00" in relative_path:
        raise ValueError("path must not contain a null byte")

    candidate = Path(relative_path)

    # Reject the obvious shapes early so the error message is useful. These are
    # not the containment check -- the realpath comparison below is.
    if candidate.is_absolute() or relative_path.startswith("~"):
        raise ValueError("path must be relative to the workspace root")
    if ".." in candidate.parts:
        raise ValueError("path must not traverse above the workspace root")

    # The containment check. realpath() collapses "..", resolves every symlink
    # in the chain, and yields the path open() would actually act on. Comparing
    # *that* against the root is the only comparison that is sound in the
    # presence of symlinks.
    resolved = Path(os.path.realpath(WORKSPACE_ROOT / candidate))
    try:
        resolved.relative_to(WORKSPACE_ROOT)
    except ValueError:
        # Covers "../../etc/passwd", a symlink pointing at /etc, and the
        # "/workspace-notes-backup" style sibling that a string prefix check
        # would wrongly accept.
        raise ValueError("path resolves outside the workspace root") from None

    if resolved.suffix.lower() not in _ALLOWED_SUFFIXES:
        raise ValueError(
            f"unsupported file type {resolved.suffix!r}; "
            f"expected one of {sorted(_ALLOWED_SUFFIXES)}"
        )
    return resolved


def _iter_notes() -> list[Path]:
    """Every readable note in the workspace, sorted, root-relative."""
    found: list[Path] = []
    for path in sorted(WORKSPACE_ROOT.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in _ALLOWED_SUFFIXES:
            continue
        # rglob follows nothing it should not, but a symlinked file inside the
        # tree could still point outside it. Same check, same reason.
        resolved = Path(os.path.realpath(path))
        try:
            resolved.relative_to(WORKSPACE_ROOT)
        except ValueError:
            continue
        found.append(resolved)
    return found


@mcp.tool
def list_notes() -> list[str]:
    """List every note in the workspace, as paths relative to the root."""
    return [str(p.relative_to(WORKSPACE_ROOT)) for p in _iter_notes()]


@mcp.tool
def read_note(path: str) -> str:
    """Read one note from the workspace.

    Args:
        path: Path to the note, relative to the workspace root, for example
            "standup.md" or "meetings/2024-05-14.md". Absolute paths, paths
            containing "..", and paths that resolve outside the workspace via a
            symlink are refused.
    """
    target = _resolve_in_workspace(path)

    if not target.is_file():
        raise ValueError(f"no such note: {path}")
    if target.stat().st_size > _MAX_BYTES:
        raise ValueError(f"note is larger than {_MAX_BYTES} bytes")

    with open(target, "r", encoding="utf-8") as handle:
        return handle.read()


@mcp.tool
def search_notes(query: str, limit: int = 20) -> list[dict]:
    """Case-insensitive substring search across the workspace.

    Args:
        query: Text to look for. 2 to 200 characters.
        limit: Maximum number of matching lines to return, 1 to 100.
    """
    if not 2 <= len(query) <= 200:
        raise ValueError("query must be between 2 and 200 characters")
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")

    needle = query.lower()
    hits: list[dict] = []
    for note in _iter_notes():
        if note.stat().st_size > _MAX_BYTES:
            continue
        try:
            text = note.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if needle in line.lower():
                hits.append({
                    "note": str(note.relative_to(WORKSPACE_ROOT)),
                    "line": number,
                    "text": line.strip()[:300],
                })
                if len(hits) >= limit:
                    return hits
    return hits


@mcp.tool
def workspace_settings(name: str = "") -> dict:
    """Report the workspace display settings.

    Only the two settings below are readable, and the allowlist is fixed in
    source. Any other variable name is refused rather than looked up, so no
    caller input ever selects an environment variable.

    Args:
        name: Optional. One of "NOTES_APP_VERSION" or
            "NOTES_WORKSPACE_LABEL". Omit it to get both.
    """
    if name and name not in _SETTING_ALLOWLIST:
        raise ValueError(
            f"{name!r} is not a readable workspace setting; "
            f"allowed: {sorted(_SETTING_ALLOWLIST)}"
        )
    wanted = [name] if name else sorted(_SETTING_ALLOWLIST)
    return {key: os.environ.get(key, _SETTING_ALLOWLIST[key]) for key in wanted}


if __name__ == "__main__":
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8201)),
        show_banner=False,
    )
