"""Boot one corpus server and check it behaves the way its manifest claims.

Usage:  python tools/smoke_server.py corpus/a08-unrestricted-file-read
        python tools/smoke_server.py --all

Checks, per server:
  * it starts and serves MCP over HTTP on its registered port
  * tools/list succeeds and returns at least one tool
  * every tool named in sensitive_tools actually exists
  * auth matches the manifest: an unauthenticated client is refused by an
    authenticated server, and accepted by an unauthenticated one

This is liveness, not flaw verification. Each flaw is proven by its own
proof_of_reach in the manifest.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = str(ROOT / ".venv" / "bin" / "python")
TOKEN = "lab-token-do-not-reuse"


def _free(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def _ephemeral() -> int:
    """Claim a free port from the OS and release it.

    The smoke test launches its own process, so the registered lab port is
    irrelevant here -- and binding it would make this tool unusable whenever the
    lab is running, since Docker holds 8101-8204 then. Port-matches-registry is
    validate_manifests.py's job, not this one's.
    """
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait(port: int, timeout: float = 25.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if not _free(port):
            return True
        time.sleep(0.25)
    return False


async def _probe(url: str, token: str | None):
    from fastmcp import Client
    from fastmcp.client.auth import BearerAuth
    auth = BearerAuth(token) if token else None
    async with Client(url, auth=auth) as c:
        return [t.name for t in await c.list_tools()]


def check(server_dir: Path) -> list[str]:
    name = server_dir.name
    manifest = json.loads((server_dir / "manifest.json").read_text())
    port = _ephemeral()
    authed = manifest["authenticated"]
    url = f"http://127.0.0.1:{port}/mcp"
    problems: list[str] = []

    env = {**os.environ, "PORT": str(port), "MCPBENCH_TOKEN": TOKEN,
           "SINKHOLE_URL": "http://127.0.0.1:8900/collect",
           "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen(
        [PY, "server.py"], cwd=server_dir, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        if not _wait(port):
            proc.terminate()
            out = (proc.stdout.read() if proc.stdout else "")[-1500:]
            return [f"{name}: did not listen on {port} within 25s\n{out}"]

        try:
            tools = asyncio.run(_probe(url, TOKEN if authed else None))
        except Exception as exc:
            return [f"{name}: tools/list failed: {type(exc).__name__}: {exc}"]

        if not tools:
            problems.append(f"{name}: exposes no tools")

        missing = [t for t in manifest["sensitive_tools"] if t not in tools]
        if missing:
            problems.append(
                f"{name}: sensitive_tools names {missing} but the server does "
                f"not expose them")

        # Auth posture must match the manifest.
        try:
            asyncio.run(_probe(url, None))
            unauth_ok = True
        except Exception:
            unauth_ok = False

        if authed and unauth_ok:
            problems.append(
                f"{name}: manifest says authenticated, but an unauthenticated "
                f"client was served -- this server would also exhibit A6")
        if not authed and not unauth_ok:
            problems.append(
                f"{name}: manifest says unauthenticated, but an unauthenticated "
                f"client was refused")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    return problems


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    if argv[0] == "--all":
        targets = sorted(d for d in (ROOT / "corpus").iterdir()
                         if d.is_dir() and not d.name.startswith("_"))
    else:
        targets = [Path(a).resolve() for a in argv]

    all_problems: list[str] = []
    for t in targets:
        if not (t / "manifest.json").exists():
            all_problems.append(f"{t.name}: no manifest.json")
            continue
        found = check(t)
        status = "FAIL" if found else "ok"
        print(f"  [{status:4}] {t.name}")
        all_problems.extend(found)

    if all_problems:
        print(f"\nFAIL  {len(all_problems)} problem(s):\n")
        for p in all_problems:
            print(f"  - {p}")
        return 1
    print(f"\nPASS  {len(targets)} server(s) live and consistent with manifest")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
