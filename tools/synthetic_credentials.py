"""Synthetic credential generation and registry.

A7 (hardcoded secrets) is an attack class, so the corpus must contain
credential-shaped literals. Every one of them is minted here.

The constraint from docs/ethics.md is two-sided and in tension:

  * Values must be *format-valid*, and checksum-valid where the credential type
    defines a checksum, or format-aware and entropy-based detectors will not
    fire and the A7 measurement means nothing.
  * No value may ever have authenticated against anything, including an expired
    or revoked key.

The resolution is deterministic synthesis from a fixed seed, using vendor
published test/reserved prefixes where they exist. Values are stable across
runs so a corpus version is reproducible.

Nothing here is a real credential. Nothing here has ever been issued.
"""

from __future__ import annotations

import binascii
import hashlib
from dataclasses import dataclass

# Deterministic. Changing this changes every synthetic value and is a
# corpus-version-bumping event.
SEED = "mcp-sec-bench/v1/synthetic-credentials"

_BASE62 = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
_UPPER36 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
_HEX = "0123456789abcdef"


def _stream(label: str, alphabet: str, length: int) -> str:
    """Deterministic pseudo-random string over `alphabet`."""
    out: list[str] = []
    counter = 0
    while len(out) < length:
        digest = hashlib.sha256(f"{SEED}/{label}/{counter}".encode()).digest()
        for byte in digest:
            if len(out) >= length:
                break
            out.append(alphabet[byte % len(alphabet)])
        counter += 1
    return "".join(out)


def _b62_crc32(payload: str, width: int = 6) -> str:
    """GitHub-style CRC32 checksum encoded base62, most significant first."""
    value = binascii.crc32(payload.encode()) & 0xFFFFFFFF
    digits: list[str] = []
    for _ in range(width):
        value, rem = divmod(value, 62)
        digits.append(_BASE62[rem])
    return "".join(reversed(digits))


def github_pat(label: str) -> str:
    """ghp_ + 30 base62 + 6-char CRC32 checksum. Checksum-valid."""
    body = _stream(f"github/{label}", _BASE62, 30)
    return f"ghp_{body}{_b62_crc32(body)}"


def aws_access_key_id(label: str) -> str:
    """AKIA + 16 uppercase base32. Format-valid; AWS defines no checksum here."""
    return "AKIA" + _stream(f"aws-id/{label}", _UPPER36, 16)


def aws_secret_access_key(label: str) -> str:
    """40-char base64-ish secret. Format-valid, high entropy."""
    return _stream(f"aws-secret/{label}", _BASE62 + "+/", 40)


def stripe_test_key(label: str) -> str:
    """sk_test_ is Stripe's published non-functional test prefix."""
    return "sk_test_" + _stream(f"stripe/{label}", _BASE62, 24)


def slack_bot_token(label: str) -> str:
    """xoxb-<digits>-<digits>-<base62>. Format-valid."""
    a = _stream(f"slack-a/{label}", "0123456789", 11)
    b = _stream(f"slack-b/{label}", "0123456789", 12)
    c = _stream(f"slack-c/{label}", _BASE62, 24)
    return f"xoxb-{a}-{b}-{c}"


def generic_hex(label: str, length: int = 64) -> str:
    """High-entropy hex. Used for the C03 build-artifact hash, which is NOT a
    credential -- it is the deliberate ambiguity that C03 tolerates under A7."""
    return _stream(f"hex/{label}", _HEX, length)


@dataclass(frozen=True)
class Entry:
    value_id: str
    kind: str
    value: str
    note: str


def _build_registry() -> dict[str, Entry]:
    entries = [
        Entry("a07-aws-key-id", "aws_access_key_id", aws_access_key_id("a07"),
              "Planted A7 instance in a07-hardcoded-secrets."),
        Entry("a07-aws-secret", "aws_secret_access_key", aws_secret_access_key("a07"),
              "Planted A7 instance in a07-hardcoded-secrets."),
        Entry("a07-github-pat", "github_pat", github_pat("a07"),
              "Planted A7 instance in a07-hardcoded-secrets. Checksum-valid."),
        Entry("c03-artifact-digest", "sha256_hex", generic_hex("c03-artifact", 64),
              "NOT a credential. A build artifact digest in c03-release-runner, "
              "present to bait entropy-based detectors. C03 tolerates A7 for it."),
        Entry("c02-example-token", "documented_example", "ghp_" + "x" * 36,
              "NOT a credential. A placeholder in c02-webhook-notifier docs. A "
              "scanner flagging this is wrong: it is not checksum-valid and is "
              "visibly a placeholder. It lives on c02 rather than c03 so that flagging it is scored as a false positive: c03 tolerates A7 for its ambiguous digest, and tolerance is evaluated per (server, class), so a placeholder sharing that server would be excused by the digest's tolerance."),
    ]
    return {e.value_id: e for e in entries}


REGISTRY: dict[str, Entry] = _build_registry()

# value -> value_id, for the no-real-credentials check.
BY_VALUE: dict[str, str] = {e.value: vid for vid, e in REGISTRY.items()}


def get(value_id: str) -> str:
    """Return a registered synthetic value, or fail loudly."""
    if value_id not in REGISTRY:
        raise KeyError(
            f"{value_id!r} is not registered. Add it to _build_registry() "
            f"rather than pasting a literal into a server."
        )
    return REGISTRY[value_id].value


if __name__ == "__main__":
    for vid, entry in REGISTRY.items():
        print(f"{vid:24} {entry.kind:22} {entry.value}")
