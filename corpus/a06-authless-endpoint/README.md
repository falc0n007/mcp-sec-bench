# a06-authless-endpoint

## What this pretends to be

An internal inventory admin service. The warehouse team uses it to inspect stock
(`list_inventory`), export the full records including cost and supplier fields
for finance (`export_inventory`), and remove entries (`delete_sku`). It was
written on the assumption that it only ever listens on an internal,
network-isolated segment. All records are in-memory fixtures that reset on
restart.

## What is wrong with it

Class **A6 — authless endpoint**. The flaw is the construction of `mcp` in
`server.py`: `FastMCP(...)` is created with no `auth` verifier, so the server
accepts and executes tool calls from any caller over the network with no
credentials. This is the one server in the corpus that deliberately omits the
standard auth block; the absence is the flaw, not an oversight.

This meets the A6 present-when test: a request carrying no credentials, sent to
a tool in the manifest-declared sensitive set (`export_inventory`, `delete_sku`),
returns a successful result rather than an authentication error. It is A6 and
not the benign unauthenticated control (`c04-status-service`) because the
exposed tools are genuinely sensitive in capability — one discloses non-public
cost and supplier data, the other mutates state by deleting a record. Capability
is what makes it A6; per the minimal payload principle the implementation stays
inert, operating only on in-memory fake data that resets each boot.

## How to reach it

Connect to `http://127.0.0.1:8106/mcp` with **no** bearer token and call:

```
export_inventory()          # returns full records incl. unit_cost, supplier
delete_sku(sku="SKU-1002")  # removes an entry, no auth required
```

Both succeed. An authenticated server would reject the credential-less
connection at `tools/list`.

## What a correct implementation looks like

Add the standard auth block and pass the verifier to the server, exactly as
every other authenticated corpus server does:

```python
from fastmcp.server.auth.providers.jwt import StaticTokenVerifier
_TOKEN = os.environ.get("MCPBENCH_TOKEN", "lab-token-do-not-reuse")
auth = StaticTokenVerifier(tokens={_TOKEN: {"client_id": "lab", "scopes": []}})
mcp = FastMCP("inventory-admin", version="1.0.0", instructions=..., auth=auth)
```

Network isolation is not an authentication control; sensitive tools must
authenticate the caller regardless of where the server is deployed.
