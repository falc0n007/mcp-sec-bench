# Ramparts adapter image for mcp-sec-bench.
#
# TRAP (see docs/scanner-survey.md, Ramparts section): `cargo install ramparts`
# does NOT vendor the tool's YARA rules. Without them, the scanner's pattern
# engine silently runs with zero compiled rules and produces "0 findings" that
# is visually indistinguishable from a genuine clean scan. This Dockerfile
# builds the pinned ramparts binary AND bakes in the matching rules/pre/*.yar
# from the same source tag, so the rules travel with the image rather than
# depending on anything present (or absent) on the host or at scan time.
#
# Versions are pinned deliberately:
#   - RAMPARTS_VERSION is the crates.io release `cargo install ramparts`
#     resolves to (0.8.8 as of the 2026-09-17 recon in docs/scanner-survey.md).
#   - RAMPARTS_RULES_TAG is the git tag whose rules/pre/*.yar we vendor.
#     Verified (2026-09-17) that the v0.8.8 and v0.8.9 tags point at the
#     identical commit (70457dbf2b64c92bb4601951bc74d36d6dbf7551) -- same blob
#     shas for all 15 rule files -- so "the matching source tag" is
#     unambiguous here. If a future ramparts release moves the tags apart,
#     bump RAMPARTS_RULES_TAG to track RAMPARTS_VERSION, not the other way
#     round.

FROM rust:slim-trixie AS builder

ARG RAMPARTS_VERSION=0.8.8
ARG RAMPARTS_RULES_TAG=v0.8.8

RUN apt-get update && apt-get install -y --no-install-recommends \
        pkg-config libssl-dev cmake build-essential ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Build the pinned ramparts binary from crates.io. --locked is intentionally
# NOT used: crates.io source packages for ramparts do not ship a Cargo.lock,
# and a bare `cargo install ramparts --version X` is exactly what the recon
# in docs/scanner-survey.md ran and is what an operator following the
# README would do -- this build should reproduce that path, not a stricter one.
RUN cargo install ramparts --version "${RAMPARTS_VERSION}" --root /out

# Fetch ONLY rules/pre/*.yar from the matching source tag on GitHub (never
# from crates.io, which does not ship them at all -- that omission is the
# trap this Dockerfile exists to close).
RUN mkdir -p /rules/pre \
    && curl -fsSL "https://github.com/highflame-ai/ramparts/archive/refs/tags/${RAMPARTS_RULES_TAG}.tar.gz" \
         -o /tmp/ramparts-src.tar.gz \
    && tar -xzf /tmp/ramparts-src.tar.gz -C /tmp \
    && SRC_DIR=$(find /tmp -maxdepth 1 -type d -name 'ramparts-*') \
    && test -d "${SRC_DIR}/rules/pre" \
    && cp "${SRC_DIR}"/rules/pre/*.yar /rules/pre/ \
    && RULE_COUNT=$(ls /rules/pre/*.yar | wc -l) \
    && echo "vendored ${RULE_COUNT} YARA rule files from ${RAMPARTS_RULES_TAG}" \
    && test "${RULE_COUNT}" -gt 0 \
    && rm -rf /tmp/ramparts-src.tar.gz "${SRC_DIR}"

# Record exactly what was baked in, so the adapter can read it back at
# runtime and put it in AdapterResult.extra without re-deriving it.
RUN echo "${RAMPARTS_VERSION}" > /rules/RAMPARTS_VERSION \
    && echo "${RAMPARTS_RULES_TAG}" > /rules/RAMPARTS_RULES_TAG \
    && ls /rules/pre/*.yar | xargs -n1 basename | sort > /rules/RULE_FILES.txt

# ---------------------------------------------------------------------------
# Final image. debian:trixie-slim, not bookworm: the binary built above links
# against a glibc newer than bookworm ships (verified in docs/scanner-survey.md
# -- a rust:slim-built binary needs glibc >= 2.38, which bookworm-slim lacks).
FROM debian:trixie-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates libssl3 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /out/bin/ramparts /usr/local/bin/ramparts
COPY --from=builder /rules /opt/ramparts-rules

# The adapter always passes --auth-headers / --format explicitly and always
# sets RAMPARTS_RULES_DIR itself (belt-and-suspenders with this default), but
# the default is set here too so a manual `docker run` of this image without
# the adapter's env still loads rules rather than silently disabling
# detection -- reproducing TRAP 1 by hand should take real effort.
ENV RAMPARTS_RULES_DIR=/opt/ramparts-rules

LABEL org.mcp-sec-bench.scanner="ramparts" \
      org.mcp-sec-bench.ramparts-version="0.8.8" \
      org.mcp-sec-bench.rules-tag="v0.8.8"

ENTRYPOINT ["ramparts"]
