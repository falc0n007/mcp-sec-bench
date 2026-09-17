"""Validate every corpus manifest against the schema and the corpus invariants.

The schema catches shape errors. This catches the errors that would silently
corrupt scoring: a duplicated port, a server declaring two flaws, a surface that
contradicts the taxonomy, an A3 pair pointing at a server that does not exist,
a tolerated entry nobody authorised.

Exit code 0 means the corpus is scoreable.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus"
SCHEMA = ROOT / "schema" / "manifest.schema.json"

# From docs/taxonomy.md. A class may only be declared on a surface it is
# reachable from.
SURFACES = {
    "A1": {"static", "runtime"},
    "A2": {"static", "runtime"},
    "A3": {"static", "runtime"},
    "A4": {"runtime"},
    "A5": {"runtime"},
    "A6": {"runtime"},
    "A7": {"static"},
    "A8": {"static"},
    "A9": {"static"},
    "A10": {"static"},
}

# Ports from corpus/conventions.md.
PORTS = {
    "a01-tool-description-injection": 8101,
    "a02-rug-pull": 8102,
    "a03-tool-shadowing": 8103,
    "a04-response-injection": 8104,
    "a05-argument-exfiltration": 8105,
    "a06-authless-endpoint": 8106,
    "a07-hardcoded-secrets": 8107,
    "a08-unrestricted-file-read": 8108,
    "a09-unrestricted-env-access": 8109,
    "a10a-command-execution": 8110,
    "a10b-allowlist-bypass": 8111,
    "c01-notes-workspace": 8201,
    "c02-webhook-notifier": 8202,
    "c03-release-runner": 8203,
    "c04-status-service": 8204,
}

# The single tolerated entry authorised for v1 (corpus/conventions.md).
ALLOWED_TOLERATED = {("c03-release-runner", "A7")}

# Unauthenticated servers are deliberate and enumerated.
ALLOWED_UNAUTH = {"a06-authless-endpoint", "c04-status-service"}

# Servers permitted an empty sensitive_tools, and therefore permitted to sit
# outside the A6 denominator. Everything else is a true negative for A6: it
# could have been authless and is not. Excluding a server from the denominator
# is a free pass for a scanner that over-flags A6, so the list is enumerated
# rather than derived from whatever a manifest happens to declare.
ALLOWED_NO_SENSITIVE = {"c04-status-service"}

# Classes requiring a concrete proof-of-reach.
NEEDS_PROOF = {"A5", "A8", "A10"}

# Classes requiring a deterministic runtime trigger.
NEEDS_TRIGGER = {"A2", "A4"}


def main() -> int:
    schema = json.loads(SCHEMA.read_text())
    errors: list[str] = []
    manifests: dict[str, dict] = {}

    dirs = sorted(d for d in CORPUS.iterdir()
                  if d.is_dir() and not d.name.startswith("_"))
    if not dirs:
        print("no corpus servers found")
        return 1

    for d in dirs:
        mf = d / "manifest.json"
        if not mf.exists():
            errors.append(f"{d.name}: missing manifest.json")
            continue
        try:
            data = json.loads(mf.read_text())
        except json.JSONDecodeError as exc:
            errors.append(f"{d.name}: manifest.json is not valid JSON: {exc}")
            continue

        try:
            jsonschema.validate(data, schema)
        except jsonschema.ValidationError as exc:
            path = "/".join(str(p) for p in exc.absolute_path) or "(root)"
            errors.append(f"{d.name}: schema: {path}: {exc.message}")
            continue

        manifests[d.name] = data

        if data["server_id"] != d.name:
            errors.append(
                f"{d.name}: server_id {data['server_id']!r} does not match directory")

        # Required files
        for fn in ("server.py", "README.md"):
            if not (d / fn).exists():
                errors.append(f"{d.name}: missing {fn}")

        # Ports
        expected = PORTS.get(d.name)
        if expected is None:
            errors.append(f"{d.name}: not in the port registry in conventions.md")
        elif data["port"] != expected:
            errors.append(
                f"{d.name}: port {data['port']} != registry {expected}")

        # Auth
        if not data["authenticated"] and d.name not in ALLOWED_UNAUTH:
            errors.append(
                f"{d.name}: authenticated=false, but only {sorted(ALLOWED_UNAUTH)} "
                f"may be unauthenticated -- every other unauthenticated server "
                f"would also exhibit A6")
        if data["authenticated"] and d.name in ALLOWED_UNAUTH:
            errors.append(
                f"{d.name}: must be unauthenticated to serve its purpose")

        declared = data["declared"]
        kind = data["kind"]

        # One flaw per server
        if kind == "vulnerable" and len(declared) != 1:
            errors.append(
                f"{d.name}: vulnerable servers declare exactly one flaw, found "
                f"{len(declared)}")
        if kind == "benign" and declared:
            errors.append(
                f"{d.name}: benign controls declare no flaws, found {len(declared)}")

        # Declared class must match the directory prefix
        if kind == "vulnerable" and declared:
            prefix = d.name.split("-")[0]
            want = prefix.rstrip("ab").upper().replace("A0", "A")
            if prefix.startswith("a10"):
                want = "A10"
            got = declared[0]["class"]
            if got != want:
                errors.append(
                    f"{d.name}: declares {got} but the directory says {want}")
            if prefix in ("a10a", "a10b"):
                variant = declared[0].get("variant")
                if variant != prefix[-1]:
                    errors.append(
                        f"{d.name}: A10 variant must be {prefix[-1]!r}, got {variant!r}")

        for entry in declared:
            cls = entry["class"]
            bad = set(entry["surface"]) - SURFACES[cls]
            if bad:
                errors.append(
                    f"{d.name}: {cls} declared on surface {sorted(bad)}, but the "
                    f"taxonomy allows only {sorted(SURFACES[cls])}")
            if cls in NEEDS_PROOF and not entry.get("proof_of_reach"):
                errors.append(f"{d.name}: {cls} requires proof_of_reach")
            if cls in NEEDS_TRIGGER and not entry.get("runtime_trigger"):
                errors.append(
                    f"{d.name}: {cls} requires a deterministic runtime_trigger")
            if cls == "A3" and not entry.get("counterpart"):
                errors.append(f"{d.name}: A3 requires a counterpart")

        # Tolerated entries are authorised individually
        for tol in data["tolerated"]:
            if (d.name, tol["class"]) not in ALLOWED_TOLERATED:
                errors.append(
                    f"{d.name}: tolerated {tol['class']} is not authorised. "
                    f"Adding one is a governance amendment, not a code change.")

        # not_applicable must be derivable
        na = set(data.get("not_applicable", []))
        derived = set()
        if data["transport"] == "stdio":
            derived.add("A6")
        if not data["sensitive_tools"]:
            derived.add("A6")
            if d.name not in ALLOWED_NO_SENSITIVE:
                errors.append(
                    f"{d.name}: empty sensitive_tools excludes it from the A6 "
                    f"denominator, which is a free pass for a scanner that "
                    f"over-flags A6. Only {sorted(ALLOWED_NO_SENSITIVE)} may do "
                    f"that. An authenticated server with real tools is a true "
                    f"negative for A6, not structurally incapable of it.")
        undeclared = derived - na
        if undeclared:
            errors.append(
                f"{d.name}: should mark {sorted(undeclared)} not_applicable "
                f"(no sensitive tools, or stdio transport)")
        overdeclared = na & {e["class"] for e in declared}
        if overdeclared:
            errors.append(
                f"{d.name}: {sorted(overdeclared)} is both declared and not_applicable")

    # Cross-server checks
    seen_ports: dict[int, str] = {}
    for name, data in manifests.items():
        port = data["port"]
        if port in seen_ports:
            errors.append(f"{name}: port {port} collides with {seen_ports[port]}")
        seen_ports[port] = name

    for name, data in manifests.items():
        for entry in data["declared"]:
            cp = entry.get("counterpart")
            if not cp:
                continue
            target = cp["server_id"]
            if target not in manifests:
                errors.append(
                    f"{name}: A3 counterpart {target!r} is not in the corpus; the "
                    f"pair must be scannable together")

    # Coverage: every class needs at least one vulnerable server
    covered = {e["class"] for d in manifests.values() for e in d["declared"]}
    missing = set(SURFACES) - covered
    if missing:
        errors.append(f"corpus: no vulnerable server for {sorted(missing)}")

    n_benign = sum(1 for d in manifests.values() if d["kind"] == "benign")
    if n_benign < 4:
        errors.append(f"corpus: expected 4 benign controls, found {n_benign}")

    if errors:
        print(f"FAIL  {len(errors)} problem(s):\n")
        for e in errors:
            print(f"  - {e}")
        return 1

    n_vuln = len(manifests) - n_benign
    print(f"PASS  {len(manifests)} servers ({n_vuln} vulnerable, {n_benign} benign)")
    print(f"      classes covered: {', '.join(sorted(covered, key=lambda c: (len(c), c)))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
