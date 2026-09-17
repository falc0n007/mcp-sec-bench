# sentinel-scan-cli 1.4.16 -- Ventrova/sentinel-scan-cli, MIT.
#
# Build:
#   docker build -f runner/adapters/dockerfiles/sentinel-scan-cli.Dockerfile \
#                -t mcp-sec-bench/sentinel-scan-cli:1.4.16 \
#                runner/adapters/dockerfiles
#
# One pinned PyPI release and nothing else. The version below is the single
# source of truth for the pin; the adapter asserts that the scanner's own
# output reports it and records the discrepancy if it does not, because a
# score published under the wrong version number is not reproducible.
#
# The package installs with ZERO dependencies (verified 2026-09-17: the wheel
# is a single module, sentinel_scan.py). `--only-binary=:all:` is kept anyway:
# a build that silently falls back to compiling an sdist is a build whose
# result depends on the host toolchain.
#
# The `mcp` subcommand this adapter runs makes no network calls, executes no
# server and calls no LLM -- it is a static scan of a manifest file. The
# adapter therefore starts this container with `--network none`, so if a
# future release ever grows a network call the scan fails loudly here instead
# of quietly reaching the internet (the tool prints upsell URLs to
# ventrova.dev after every run; they are text, and nothing fetches them).

FROM python:3.13-slim-bookworm

RUN pip install --no-cache-dir --only-binary=:all: \
        sentinel-scan-cli==1.4.16 \
 && python -c "import importlib.metadata as m; assert m.version('sentinel-scan-cli') == '1.4.16'" \
 && sentinel-scan mcp --help > /dev/null

# The scanner is the subject of the measurement, not trusted infrastructure.
# It also has to WRITE: `--output` and `--update-baseline` both write files, so
# the adapter bind-mounts a host temp directory at /work read-write. That
# directory is created per run and never points into the repository or the
# corpus; the corpus is not mounted into this container at all, because
# sentinel-scan-cli cannot read a source tree.
RUN useradd --create-home --uid 10001 scanner
USER scanner
WORKDIR /work

ENTRYPOINT ["sentinel-scan"]
CMD ["mcp", "--help"]
