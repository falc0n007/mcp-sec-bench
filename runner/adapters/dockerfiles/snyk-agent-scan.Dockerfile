# Snyk agent-scan 0.6.3 -- github.com/snyk/agent-scan (formerly Invariant
# Labs' `mcp-scan`), PyPI `snyk-agent-scan`, Apache-2.0.
#
# THE DEFINING CONSTRAINT (see runner/adapters/snyk_agent_scan.py and
# docs/scanner-survey.md): a SNYK_TOKEN environment variable gates ALL
# analysis this tool performs, not just an optional extra. Without it the
# tool still connects to a target and enumerates its tools, then exits 1
# refusing to produce any findings. This image builds and ships the tool
# regardless, so that the adapter's run path is real and ready the moment a
# token exists -- it never bakes a token into the image (that would be a
# permanent leak into every layer) and never expects one at build time.
#
# Pinned to an exact PyPI release, not a floating `@latest` / `uvx
# snyk-agent-scan@latest` as the README's own quick-start suggests: a
# floating install would mean a published (or future) score could not be
# reproduced from this file. Bump SNYK_AGENT_SCAN_VERSION and this adapter's
# adapter_version together; docs/governance.md treats a scanner version
# change as a new row, not an edit to an old one.

FROM python:3.12-slim

ARG SNYK_AGENT_SCAN_VERSION=0.6.3

RUN pip install --no-cache-dir "snyk-agent-scan==${SNYK_AGENT_SCAN_VERSION}"

# A scanner is the instrument under test, not trusted infrastructure: it
# never needs root, and the only thing it is ever pointed at from this
# project is a read-only mounted config file (runner/adapters/container.py
# mounts the generated mcpServers config at /scan-config:ro).
RUN useradd --create-home --uid 10001 scanner
USER scanner
WORKDIR /work

# No ENV for SNYK_TOKEN here, deliberately: the token is supplied per
# invocation by the adapter via `docker run -e SNYK_TOKEN=...`, never baked
# into the image, never given a default, and never logged by anything this
# Dockerfile does.
ENTRYPOINT ["snyk-agent-scan"]
CMD ["--help"]
