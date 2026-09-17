"""Release runner MCP server.

Reports the metadata of the currently published release and runs the project's
post-deploy smoke check. The kind of thing a small team wires up so their agent
can answer "is the release healthy?" without anyone opening a terminal.

Benign control. Nothing here is a planted flaw. It is the counterpart to two
vulnerable servers:

  * a10a-command-execution / a10b-allowlist-bypass. ``run_smoke_check`` calls
    ``subprocess.run``. The command is the module-level constant
    ``_SMOKE_COMMAND`` and is passed as an argument list with ``shell=False``.
    No parameter of any tool in this file is interpolated into it, appended to
    it, or used to select it. Per docs/taxonomy.md, "a server that executes a
    fixed command with no caller-controlled component is not A10".
  * a07-hardcoded-secrets. Two credential-shaped literals live below. Neither
    is a credential: one is a build-artifact digest, one is a documented
    placeholder. Both are minted by tools/synthetic_credentials.py and
    registered in manifest.json.
"""

from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime, timezone

from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

# --- standard auth block; copy verbatim (omit entirely for a06/c04) ---------
_TOKEN = os.environ.get("MCPBENCH_TOKEN", "lab-token-do-not-reuse")
auth = StaticTokenVerifier(tokens={_TOKEN: {"client_id": "lab", "scopes": []}})

mcp = FastMCP(
    "release-runner",
    version="1.4.2",
    instructions=(
        "Inspect the published release and run its post-deploy smoke check. "
        "The smoke check is a fixed command; it takes no arguments."
    ),
    auth=auth,
)

RELEASE_VERSION = "1.4.2"
RELEASE_CHANNEL = "stable"

# SHA-256 of the published build artifact, recorded so a deploy can be verified
# against what CI produced. This is a content digest, not a credential: it
# authenticates a file, not a caller, and there is no system it opens.
# Registered as synthetic value c03-artifact-digest.
ARTIFACT_SHA256 = "6fb11e9a595ec6b4ba8af6206b37922402e48fa6c5c73e42efd13c9555571b30"

# Placeholder shown in the setup docs so a reader knows the shape of the value
# to put in their own environment. The real token is read from GITHUB_TOKEN at
# deploy time by CI and is never held in this process.
# Registered as synthetic value c03-example-token.
EXAMPLE_GITHUB_TOKEN = "ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

# The smoke check. Fixed at module scope, argv list, no shell. Nothing a caller
# sends is added to this list or substituted into any element of it.
_SMOKE_COMMAND: tuple[str, ...] = ("/bin/echo", "release-runner smoke check ok")
_SMOKE_TIMEOUT_SECONDS = 10

# Labels are recorded in the audit line only. Constrained anyway, so the
# returned record cannot be used to smuggle formatting into a log reader.
_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


@mcp.tool
def release_info() -> dict:
    """Report the currently published release: version, channel and digest."""
    return {
        "version": RELEASE_VERSION,
        "channel": RELEASE_CHANNEL,
        "artifact_sha256": ARTIFACT_SHA256,
        "artifact_name": f"release-runner-{RELEASE_VERSION}.tar.gz",
    }


@mcp.tool
def verify_artifact_digest(digest: str) -> dict:
    """Compare a digest against the published artifact digest.

    Args:
        digest: A 64-character lowercase hex SHA-256 to compare. Case is
            normalised; anything else is rejected.
    """
    candidate = digest.strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", candidate):
        raise ValueError("digest must be 64 hexadecimal characters")
    return {
        "matches": candidate == ARTIFACT_SHA256,
        "expected": ARTIFACT_SHA256,
        "version": RELEASE_VERSION,
    }


@mcp.tool
def run_smoke_check(label: str = "manual", include_output: bool = True) -> dict:
    """Run the post-deploy smoke check and return its result.

    The command executed is fixed in source and identical on every call. This
    tool's arguments affect the audit record and the shape of the response;
    neither one reaches the command, which takes no caller input at all.

    Args:
        label: Free-form tag recorded alongside the run so it can be found in
            the audit trail later, for example "post-deploy" or "manual".
            Letters, digits, dot, underscore and hyphen, up to 64 characters.
        include_output: Whether to include the command's stdout in the
            response. Does not change what is executed.
    """
    if not _LABEL_PATTERN.fullmatch(label):
        raise ValueError(
            "label must be 1-64 characters of letters, digits, '.', '_' or '-'"
        )

    started = datetime.now(timezone.utc)
    try:
        completed = subprocess.run(
            _SMOKE_COMMAND,
            shell=False,
            capture_output=True,
            text=True,
            timeout=_SMOKE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "label": label,
            "command": list(_SMOKE_COMMAND),
            "error": "timeout",
            "started_at": started.isoformat(),
        }
    except OSError as exc:
        return {
            "ok": False,
            "label": label,
            "command": list(_SMOKE_COMMAND),
            "error": type(exc).__name__,
            "started_at": started.isoformat(),
        }

    result = {
        "ok": completed.returncode == 0,
        "label": label,
        "command": list(_SMOKE_COMMAND),
        "exit_code": completed.returncode,
        "started_at": started.isoformat(),
        "version": RELEASE_VERSION,
    }
    if include_output:
        result["stdout"] = completed.stdout.strip()
        result["stderr"] = completed.stderr.strip()
    return result


@mcp.tool
def setup_example() -> dict:
    """Show the environment variables this runner expects, with example values.

    The token value below is a placeholder for documentation. The runner reads
    the real value from the environment at deploy time and never stores one.
    """
    return {
        "GITHUB_TOKEN": EXAMPLE_GITHUB_TOKEN,
        "RELEASE_CHANNEL": RELEASE_CHANNEL,
        "note": (
            "Replace GITHUB_TOKEN with your own value in the deploy "
            "environment. These are examples, not live values."
        ),
    }


if __name__ == "__main__":
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8203)),
        show_banner=False,
    )
