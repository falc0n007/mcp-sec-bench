"""Template MCP server.

Copy this directory, rename it to your server_id, and replace the body. It is a
working, benign server: boot it and smoke test it before you change anything, so
you know the baseline works.

Read corpus/conventions.md first. The rules that bite:
  * exactly one declared flaw (benign controls: zero)
  * self-contained -- no imports from a shared corpus library
  * realistic -- a plausible utility, not an obvious fixture
  * the flaw is the ONLY thing wrong
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

# --- standard auth block; copy verbatim (omit entirely for a06/c04) ---------
_TOKEN = os.environ.get("MCPBENCH_TOKEN", "lab-token-do-not-reuse")
auth = StaticTokenVerifier(tokens={_TOKEN: {"client_id": "lab", "scopes": []}})

mcp = FastMCP(
    "template-service",
    version="1.0.0",
    instructions="A small example service. Replace this with your cover story.",
    auth=auth,
)


@mcp.tool
def server_time(timezone_name: str = "UTC") -> str:
    """Return the current server time in ISO 8601 format.

    Args:
        timezone_name: Currently only "UTC" is supported.
    """
    if timezone_name != "UTC":
        raise ValueError("only UTC is supported")
    return datetime.now(timezone.utc).isoformat()


@mcp.tool
def echo(message: str) -> str:
    """Echo a message back, for connectivity checks.

    Args:
        message: Text to echo. Limited to 500 characters.
    """
    if len(message) > 500:
        raise ValueError("message too long")
    return message


if __name__ == "__main__":
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8299)),
        show_banner=False,
    )
