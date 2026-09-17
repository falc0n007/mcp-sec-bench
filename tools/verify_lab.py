"""End-to-end verification that the running lab is what docs/ethics.md promises.

Run after `docker compose -f lab/docker-compose.yml up -d`.

Four things must hold, and all four are load-bearing:

  1. Every corpus server is reachable from the host through the gateway, with
     the auth posture its manifest declares.
  2. Corpus servers cannot reach the internet. This is the sandboxing
     commitment, not a nice-to-have.
  3. Corpus servers cannot resolve DNS.
  4. The sinkhole is reachable from the lab network and records exfiltration
     attempts, so A5 is observable without anything leaving.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "lab-token-do-not-reuse"

failures: list[str] = []
passes: list[str] = []


def ok(msg: str) -> None:
    passes.append(msg)
    print(f"  [ok  ] {msg}")


def bad(msg: str) -> None:
    failures.append(msg)
    print(f"  [FAIL] {msg}")


def manifests() -> list[dict]:
    out = []
    for d in sorted((ROOT / "corpus").iterdir()):
        if d.is_dir() and not d.name.startswith("_") and (d / "manifest.json").exists():
            out.append(json.loads((d / "manifest.json").read_text()))
    return out


async def list_tools(url: str, token: str | None) -> list[str]:
    from fastmcp import Client
    from fastmcp.client.auth import BearerAuth
    async with Client(url, auth=BearerAuth(token) if token else None) as c:
        return [t.name for t in await c.list_tools()]


def dexec(container: str, code: str) -> tuple[int, str]:
    p = subprocess.run(
        ["docker", "exec", container, "python", "-c", code],
        capture_output=True, text=True, timeout=60)
    return p.returncode, (p.stdout + p.stderr).strip()


def main() -> int:
    mans = manifests()

    print("\n1. Reachability through the gateway")
    for m in mans:
        url = f"http://127.0.0.1:{m['port']}/mcp"
        token = TOKEN if m["authenticated"] else None
        try:
            tools = asyncio.run(list_tools(url, token))
            if tools:
                ok(f"{m['server_id']:32} :{m['port']}  {len(tools)} tools")
            else:
                bad(f"{m['server_id']}: reachable but exposes no tools")
        except Exception as exc:
            bad(f"{m['server_id']}: unreachable on :{m['port']} -- "
                f"{type(exc).__name__}: {str(exc)[:90]}")

    print("\n2. Auth posture through the gateway")
    for m in mans:
        url = f"http://127.0.0.1:{m['port']}/mcp"
        try:
            asyncio.run(list_tools(url, None))
            served = True
        except Exception:
            served = False
        if m["authenticated"] and served:
            bad(f"{m['server_id']}: served an unauthenticated caller; it would "
                f"also exhibit A6")
        elif not m["authenticated"] and not served:
            bad(f"{m['server_id']}: refused an unauthenticated caller but "
                f"declares authenticated=false")
        else:
            ok(f"{m['server_id']:32} auth posture matches manifest "
               f"({'required' if m['authenticated'] else 'open by design'})")

    print("\n3. Egress containment (the sandboxing commitment)")
    probes = ["mcpbench-a05-argument-exfiltration",
              "mcpbench-a10a-command-execution",
              "mcpbench-c01-notes-workspace"]
    for c in probes:
        rc, out = dexec(c, (
            "import socket; socket.setdefaulttimeout(5)\n"
            "try:\n"
            "    socket.create_connection(('1.1.1.1',443)); print('REACHABLE')\n"
            "except Exception as e: print('blocked:'+type(e).__name__)"))
        if "REACHABLE" in out:
            bad(f"{c}: reached the public internet -- egress is NOT contained")
        elif "blocked:" in out:
            ok(f"{c:42} outbound TCP blocked ({out.split('blocked:')[1]})")
        else:
            bad(f"{c}: egress probe inconclusive: {out[:90]}")

        rc, out = dexec(c, (
            "import socket\n"
            "try: print('RESOLVED '+socket.gethostbyname('example.com'))\n"
            "except Exception as e: print('blocked:'+type(e).__name__)"))
        if "RESOLVED" in out:
            bad(f"{c}: resolved public DNS -- egress is NOT contained")
        elif "blocked:" in out:
            ok(f"{c:42} DNS blocked ({out.split('blocked:')[1]})")
        else:
            bad(f"{c}: DNS probe inconclusive: {out[:90]}")

    print("\n4. Sinkhole reachable from the lab, and A5 observable")
    rc, out = dexec("mcpbench-a05-argument-exfiltration", (
        "import urllib.request,json\n"
        "print(urllib.request.urlopen('http://sinkhole:8900/health',timeout=5).status)"))
    if out.strip().endswith("200"):
        ok("sinkhole reachable from inside the lab network")
    else:
        bad(f"sinkhole not reachable from the lab: {out[:120]}")

    try:
        urllib.request.urlopen(urllib.request.Request(
            "http://127.0.0.1:8900/reset", data=b""), timeout=10)
        before = json.load(urllib.request.urlopen(
            "http://127.0.0.1:8900/captures", timeout=10))["count"]
    except Exception as exc:
        bad(f"sinkhole control endpoints unreachable from host: {exc}")
        before = None

    if before is not None:
        a05 = next((m for m in mans if m["server_id"].startswith("a05")), None)
        try:
            from fastmcp import Client
            from fastmcp.client.auth import BearerAuth

            async def call():
                url = f"http://127.0.0.1:{a05['port']}/mcp"
                async with Client(url, auth=BearerAuth(TOKEN)) as c:
                    tools = [t.name for t in await c.list_tools()]
                    target = "spellcheck" if "spellcheck" in tools else tools[0]
                    schema = next(t for t in await c.list_tools()
                                  if t.name == target).input_schema
                    args = {}
                    for prop, spec in (schema.get("properties") or {}).items():
                        if spec.get("type") == "string":
                            args[prop] = "canary text for lab verification"
                            break
                    return await c.call_tool(target, args)

            asyncio.run(call())
            after = json.load(urllib.request.urlopen(
                "http://127.0.0.1:8900/captures", timeout=10))
            if after["count"] > before:
                body = after["captures"][-1].get("body_json")
                ok(f"A5 exfiltration attempt captured at the sinkhole: "
                   f"{json.dumps(body)[:100]}")
            else:
                bad("A5 called but the sinkhole captured nothing -- the flaw "
                    "does not fire inside the lab")
        except Exception as exc:
            bad(f"A5 in-lab check failed: {type(exc).__name__}: {str(exc)[:110]}")

    print(f"\n{'=' * 62}")
    if failures:
        print(f"FAIL  {len(failures)} problem(s), {len(passes)} check(s) passed:\n")
        for f in failures:
            print(f"  - {f}")
        return 1
    print(f"PASS  all {len(passes)} lab checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
