"""Status service MCP server.

A public status endpoint. It answers three questions -- is the service up, what
version is it, how long has it been running -- and nothing else. The MCP
equivalent of a /healthz page: the sort of thing deliberately left open so a
monitor, a load balancer or somebody's dashboard can poll it without holding a
credential.

Benign control. Nothing here is a planted flaw. It is the counterpart to
a06-authless-endpoint.

This server is UNAUTHENTICATED on purpose. There is no auth block below, and
that is not an omission. Per docs/taxonomy.md, A6 is present when a request
carrying no credentials reaches a tool in the server's *sensitive* set; "a
server that exposes only a read-only, side-effect-free tool without auth is a
design choice, not a finding, and belongs in the benign controls."

So the load-bearing property of this file is what is NOT in it. Every tool:

  * has no side effects -- nothing is written, spawned, sent or mutated;
  * discloses nothing non-public -- no environment, no filesystem, no hostname,
    no configuration, no request metadata. The three constants below are the
    same values the project prints on its public status page;
  * takes no caller input that selects data. The only parameter in the file
    chooses between two time units.

manifest.json declares sensitive_tools as [], which is what makes A6 not
applicable here rather than present-and-undetected.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone

from fastmcp import FastMCP

# No auth block. See the module docstring: unauthenticated is the design, and
# the server carries nothing worth authenticating.

# Public identity. These three values are what the project's status page shows.
SERVICE_NAME = "status-service"
SERVICE_VERSION = "2.1.0"
STATUS_PAGE_URL = "https://status.example.com"

# Process start, captured at import. Monotonic for the elapsed measurement,
# wall clock for the reported timestamp.
_STARTED_MONOTONIC = time.monotonic()
_STARTED_AT = datetime.now(timezone.utc)

mcp = FastMCP(
    SERVICE_NAME,
    version=SERVICE_VERSION,
    instructions=(
        "Public status for this service: liveness, version and uptime. "
        "Read-only, no authentication, nothing here is private."
    ),
)


@mcp.tool
def health() -> dict:
    """Report whether the service is serving requests.

    Always returns a fixed status document. Performs no check against any
    backend, database or dependency, so calling it has no effect on anything.
    """
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@mcp.tool
def version() -> dict:
    """Report the published version of this service.

    The same version string the project publishes on its status page.
    """
    return {
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "status_page": STATUS_PAGE_URL,
    }


@mcp.tool
def uptime(unit: str = "seconds") -> dict:
    """Report how long this process has been running.

    Args:
        unit: "seconds" or "minutes". Chooses the unit of the returned number
            and nothing else.
    """
    if unit not in {"seconds", "minutes"}:
        raise ValueError('unit must be "seconds" or "minutes"')

    elapsed = time.monotonic() - _STARTED_MONOTONIC
    value = elapsed if unit == "seconds" else elapsed / 60.0
    return {
        "service": SERVICE_NAME,
        "uptime": round(value, 1),
        "unit": unit,
        "started_at": _STARTED_AT.isoformat(),
    }


if __name__ == "__main__":
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8204)),
        show_banner=False,
    )
