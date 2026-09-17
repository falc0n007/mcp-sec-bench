# Cisco mcp-scanner, pinned.
#
# Cisco ships four Dockerfiles inside the wheel
# (mcpscanner/docker/{Dockerfile,Dockerfile.wheel,Dockerfile.npm,Dockerfile.npm.wheel}).
# We do not use them, for one reason that matters to reproducibility: those files
# build from the repository working tree at whatever commit you happen to have,
# and the npm variants add a Node toolchain this benchmark never exercises. This
# file installs one pinned PyPI release and nothing else, so a run from a clean
# checkout in six months resolves to the same scanner.
#
# Build:
#   docker build -f runner/adapters/dockerfiles/cisco-mcp-scanner.Dockerfile \
#                -t mcp-sec-bench/cisco-mcp-scanner:4.8.4 .
#
# The version below is the single source of truth for the pin; the adapter
# asserts the running scanner reports it, and refuses to record a scan under a
# version it did not verify.

FROM python:3.13-slim-bookworm

# cisco-ai-mcp-scanner pulls yara-python, tokenizers, litellm and nine
# tree-sitter grammars. Wheels exist for linux/amd64 and linux/arm64 for all of
# them at this pin, so no compiler is installed: a build that silently starts
# compiling from sdist is a build whose result depends on the host toolchain.
RUN pip install --no-cache-dir --only-binary=:all: \
        cisco-ai-mcp-scanner==4.8.4 \
 && python -c "import importlib.metadata as m; assert m.version('cisco-ai-mcp-scanner') == '4.8.4'" \
 && mcp-scanner --help > /dev/null

# The scanner is the subject of the measurement, not trusted infrastructure.
RUN useradd --create-home --uid 10001 scanner
USER scanner
WORKDIR /work

ENTRYPOINT ["mcp-scanner"]
