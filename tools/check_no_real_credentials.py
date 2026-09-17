"""Fail if any credential-shaped literal in the repo is not a registered
synthetic value.

docs/ethics.md commits to this: the corpus contains planted credentials because
A7 is an attack class, and every one of them must be traceable to
tools/synthetic_credentials.py. A literal that is credential-shaped and
unregistered is assumed to be real until proven otherwise, and fails the build.

Exit 0 means no unregistered credential-shaped literal exists.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from synthetic_credentials import BY_VALUE, REGISTRY  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", "node_modules",
             ".ruff_cache", "results"}
SCAN_SUFFIXES = {".py", ".json", ".md", ".yml", ".yaml", ".toml", ".env",
                 ".txt", ".cfg", ".ini", ".sh", ".example"}

# Credential shapes. Deliberately broad: a false alarm here costs a registry
# entry, a miss costs a leaked secret.
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("github_pat", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("aws_access_key_id", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("stripe_key", re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9]{16,}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9]{32,}\b")),
    ("google_api_key", re.compile(r"\bAIza[A-Za-z0-9_\-]{35}\b")),
    ("private_key_block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b")),
    ("aws_secret_like", re.compile(r"\b(?i:aws_secret_access_key)\b\s*[:=]\s*['\"]([^'\"]{30,})['\"]")),
]

# This file and the generator necessarily contain the patterns themselves.
SELF = {ROOT / "tools" / "check_no_real_credentials.py",
        ROOT / "tools" / "synthetic_credentials.py"}


def main() -> int:
    findings: list[str] = []
    scanned = 0

    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix not in SCAN_SUFFIXES:
            continue
        if path in SELF:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        scanned += 1

        for kind, pattern in PATTERNS:
            for match in pattern.finditer(text):
                value = match.group(0)
                if value in BY_VALUE:
                    continue
                # Placeholders are not credentials.
                body = value.split("_")[-1] if "_" in value else value
                if len(set(body)) <= 2:
                    continue
                if re.search(r"(your|example|placeholder|redacted|xxxx|<|\.\.\.)",
                             value, re.I):
                    continue
                line = text[:match.start()].count("\n") + 1
                rel = path.relative_to(ROOT)
                findings.append(
                    f"{rel}:{line}: unregistered {kind}: {value[:16]}...")

    if findings:
        print(f"FAIL  {len(findings)} unregistered credential-shaped literal(s):\n")
        for f in findings:
            print(f"  - {f}")
        print("\nEvery credential-shaped literal must be minted by")
        print("tools/synthetic_credentials.py and registered there. If this is a")
        print("real credential -- live, expired, or revoked -- it does not belong")
        print("in this repository at all. See docs/ethics.md.")
        return 1

    print(f"PASS  {scanned} files scanned, "
          f"{len(REGISTRY)} registered synthetic values, 0 unregistered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
