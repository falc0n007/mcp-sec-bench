"""Internal inventory admin service.

A back-office service the warehouse team uses to inspect and adjust stock
records. It was written on the assumption that it only ever listens on an
internal, network-isolated segment, so it carries no authentication of its own.

All records are in-memory fixtures that reset on restart; nothing here touches a
real datastore. See README.md for what is actually wrong with it.

NOTE: this server intentionally omits the standard auth block. The absence of
authentication is the planted flaw (class A6), not an oversight to be fixed.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from fastmcp import FastMCP

mcp = FastMCP(
    "inventory-admin",
    version="1.0.0",
    instructions=(
        "Internal inventory administration for the warehouse team. Inspect, "
        "export, and adjust stock records. Assumes a network-isolated segment."
    ),
    # No auth: see module docstring and README.md.
)

# In-memory fixture data. Fake SKUs with non-public cost and supplier fields,
# so export is a genuinely sensitive capability -- but the data is inert and
# resets every boot.
_INVENTORY: dict[str, dict] = {
    "SKU-1001": {
        "name": "M4 hex bolt, 20mm",
        "on_hand": 4200,
        "unit_cost": 0.03,
        "supplier": "Northgate Fasteners",
        "reorder_point": 1000,
    },
    "SKU-1002": {
        "name": "Nitrile glove, size L",
        "on_hand": 180,
        "unit_cost": 0.11,
        "supplier": "Meridian Safety Supply",
        "reorder_point": 500,
    },
    "SKU-1003": {
        "name": "Thermal label roll, 4x6",
        "on_hand": 76,
        "unit_cost": 8.40,
        "supplier": "Cascade Print Media",
        "reorder_point": 40,
    },
}


@mcp.tool
def list_inventory() -> dict:
    """List each SKU with its name and quantity on hand.

    A summary view without cost or supplier fields.
    """
    return {
        "count": len(_INVENTORY),
        "items": [
            {"sku": sku, "name": rec["name"], "on_hand": rec["on_hand"]}
            for sku, rec in _INVENTORY.items()
        ],
    }


@mcp.tool
def export_inventory() -> dict:
    """Export the full inventory records, including cost and supplier fields.

    Intended for the finance team's monthly reconciliation.
    """
    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "count": len(_INVENTORY),
        "records": [{"sku": sku, **rec} for sku, rec in _INVENTORY.items()],
    }


@mcp.tool
def delete_sku(sku: str) -> dict:
    """Delete an inventory entry by its SKU.

    Args:
        sku: The SKU identifier to remove, e.g. "SKU-1002".
    """
    if not isinstance(sku, str) or not sku.strip():
        raise ValueError("sku must be a non-empty string")
    if sku not in _INVENTORY:
        raise ValueError(f"no such sku {sku!r}")
    removed = _INVENTORY.pop(sku)
    return {"deleted": sku, "name": removed["name"], "remaining": len(_INVENTORY)}


if __name__ == "__main__":
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 8106)),
        show_banner=False,
    )
