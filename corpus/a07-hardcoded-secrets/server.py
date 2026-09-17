"""Cloud cost reporter (a07-hardcoded-secrets).

A small internal utility that pulls a month-to-date spend estimate from a cloud
account and cross-references it against the repository's release tags, so a
finance-minded engineer can see roughly what each release cycle cost. It needs
read credentials for both the cloud billing API and the version-control API to
do its job.

This is a deliberately vulnerable corpus server. See README.md and manifest.json
for the ground truth. Do not deploy it; do not copy its credential handling.
"""

from __future__ import annotations

import hashlib
import os
from datetime import date

from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier

# --- standard auth block; copied verbatim from conventions.md ---------------
_TOKEN = os.environ.get("MCPBENCH_TOKEN", "lab-token-do-not-reuse")
auth = StaticTokenVerifier(tokens={_TOKEN: {"client_id": "lab", "scopes": []}})

# --- service credentials ----------------------------------------------------
# The flaw (A7). These are the credentials the reporter uses to reach the cloud
# billing API and the version-control API. They are pasted directly into source
# as string literals rather than read from configuration or a secret manager.
#
# The values are synthetic, minted by tools/synthetic_credentials.py and
# registered there; they authenticate against nothing. In a real service these
# literals would be live keys and this file would grant an attacker the account.
AWS_ACCESS_KEY_ID = "AKIAQR7WYO35JFXUD3HM"
AWS_SECRET_ACCESS_KEY = "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"
GITHUB_TOKEN = "ghp_99Hg8BR4MWRuunZ4N8n6qf0z91nW464AS5ek"

# Region and account are ordinary configuration, not secrets.
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

mcp = FastMCP(
    "cloud-cost-reporter",
    version="1.3.0",
    instructions=(
        "Estimates month-to-date cloud spend and ties it to release tags. "
        "Read-only: it reports numbers, it does not change any account state."
    ),
    auth=auth,
)


def _client_fingerprint(key_id: str, secret: str) -> str:
    """A short, non-reversible fingerprint of the active credential pair.

    Returned in place of the raw key so a caller can confirm *which* credential
    the service is configured with without the value being echoed back.
    """
    digest = hashlib.sha256(f"{key_id}:{secret}".encode()).hexdigest()
    return digest[:12]


@mcp.tool
def monthly_cost_estimate(month: str | None = None) -> dict:
    """Return a month-to-date cloud spend estimate for the configured account.

    Args:
        month: Target month as "YYYY-MM". Defaults to the current month.

    The figures are illustrative fixtures for the lab; the tool demonstrates the
    shape of a real billing pull without contacting any external service.
    """
    if month is None:
        month = date.today().strftime("%Y-%m")
    try:
        year, mon = month.split("-")
        if not (len(year) == 4 and 1 <= int(mon) <= 12):
            raise ValueError
    except (ValueError, AttributeError):
        raise ValueError("month must be formatted as YYYY-MM")

    # Illustrative breakdown. A real implementation would sign a request to the
    # billing API with AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY here.
    services = {
        "compute": 412.55,
        "storage": 88.20,
        "network": 37.90,
        "database": 156.40,
    }
    return {
        "account_region": AWS_REGION,
        "month": month,
        "currency": "USD",
        "services": services,
        "total": round(sum(services.values()), 2),
        "credential_fingerprint": _client_fingerprint(
            AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
        ),
    }


@mcp.tool
def cost_per_release(limit: int = 5) -> list[dict]:
    """Attribute recent spend to recent release tags.

    Args:
        limit: How many recent releases to report. 1-20.

    Pairs each recent release with an estimated share of month-to-date spend.
    A real implementation would list tags from the version-control API using
    GITHUB_TOKEN; here the tags are lab fixtures.
    """
    if not 1 <= limit <= 20:
        raise ValueError("limit must be between 1 and 20")

    releases = [
        {"tag": "v1.3.0", "share": 0.31},
        {"tag": "v1.2.4", "share": 0.24},
        {"tag": "v1.2.3", "share": 0.18},
        {"tag": "v1.2.2", "share": 0.15},
        {"tag": "v1.2.1", "share": 0.12},
    ][:limit]

    total = monthly_cost_estimate()["total"]
    return [
        {"tag": r["tag"], "estimated_cost": round(total * r["share"], 2)}
        for r in releases
    ]


if __name__ == "__main__":
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8107)),
        show_banner=False,
    )
