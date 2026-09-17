# mcp-guard 2.0.0 -- SaravanaGuhan/mcp-guard, MIT.
#
# Pinned to a commit SHA, not a tag and not `main`. The project is not on PyPI,
# so the only install route is a git URL, and a floating ref would mean a
# published score could not be reproduced from this file. Bump the SHA and the
# adapter_version together; docs/governance.md treats a scanner version change
# as a new row, not an edit to an old one.
#
# The scanner runs OFFLINE inside this image: its only network call is the OSV
# dependency lookup, which `--offline` disables. Nothing here needs the network
# at run time, and the container is started without one.

FROM python:3.12-slim

ARG MCP_GUARD_REF=e782de38d98219047c4dab3232395d8636c678c3

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
      "git+https://github.com/SaravanaGuhan/mcp-guard.git@${MCP_GUARD_REF}" \
    && apt-get purge -y git && apt-get autoremove -y

# A scanner is the instrument, not a trusted component: it never needs root and
# never needs to write to the corpus, which is mounted read-only by
# runner/adapters/container.py.
RUN useradd --create-home --uid 10001 scanner
USER scanner
WORKDIR /work

ENTRYPOINT ["mcp-guard"]
CMD ["--help"]
