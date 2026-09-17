# Base image for every corpus server.
#
# One image holds the whole corpus; each compose service selects a server with
# working_dir plus command. That is one build instead of fifteen.
#
# Static scanning happens against the source tree, not this image, so sharing a
# base does not weaken the per-directory isolation that corpus/conventions.md
# requires.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /lab

# Pinned for reproducibility: a corpus version must rebuild identically.
RUN pip install --no-cache-dir "fastmcp==4.0.4" "httpx==0.28.1"

COPY corpus/ /lab/corpus/

# The corpus runs deliberately vulnerable code. Drop privileges; the lab network
# blocks egress independently.
USER nobody

CMD ["python", "--version"]
