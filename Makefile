# mcp-sec-bench
#
# Phase 2's bar is "one command produces a reproducible scoreboard from a clean
# checkout". These targets are that command, and the steps it needs first.
#
#   make setup       create the venv and install pinned dependencies
#   make images      build the lab and the scanner adapter images
#   make lab-up      bring the corpus online, egress blocked
#   make verify      every correctness check the project has
#   make scoreboard  run the benchmark and render the scoreboard
#   make all         setup + images + lab-up + verify + scoreboard
#
# Scanner images are built from pinned Dockerfiles. Building them is separate
# from `setup` because it takes a while and needs a running Docker daemon.

PY      := .venv/bin/python
PIP     := .venv/bin/pip
COMPOSE := docker compose -f lab/docker-compose.yml
DOCKERFILES := runner/adapters/dockerfiles

.DEFAULT_GOAL := help
.PHONY: help setup images lab-up lab-down lab-restart verify test scoreboard clean all

help:
	@grep -E '^#   make [a-z-]+' Makefile | sed 's/^#   /  /'

setup:
	python3 -m venv .venv
	$(PIP) install --quiet --upgrade pip
	$(PIP) install --quiet -r requirements.txt
	@echo "venv ready: $(PY)"

images:
	$(COMPOSE) build
	docker build -f $(DOCKERFILES)/mcp-guard.Dockerfile \
		-t mcp-sec-bench/mcp-guard:2.0.0 .
	docker build -f $(DOCKERFILES)/ramparts.Dockerfile \
		-t mcp-sec-bench/ramparts:0.8.8 .
	docker build -f $(DOCKERFILES)/cisco-mcp-scanner.Dockerfile \
		-t mcp-sec-bench/cisco-mcp-scanner:4.8.4 .
	docker build -f $(DOCKERFILES)/sentinel-scan-cli.Dockerfile \
		-t mcp-sec-bench/sentinel-scan-cli:1.4.16 .
	docker build -f $(DOCKERFILES)/snyk-agent-scan.Dockerfile \
		-t mcp-sec-bench/snyk-agent-scan:0.6.3 .
	@echo "scanner images built"

lab-up:
	$(COMPOSE) up -d
	@echo "lab up; verify with: make verify"

lab-down:
	$(COMPOSE) down

lab-restart:
	$(COMPOSE) restart

# Everything that can be wrong, checked. Ground truth first: a bad manifest
# silently corrupts every number downstream.
verify:
	$(PY) tools/validate_manifests.py
	$(PY) tools/check_no_real_credentials.py
	$(PY) tools/smoke_server.py --all
	$(PY) tools/verify_lab.py
	$(PY) -m pytest tests/ -q

test:
	$(PY) -m pytest tests/ -q

# Writes to results/local/, which is gitignored. A publishing run targets
# results/ explicitly so a dev run can never be mistaken for a published score.
scoreboard:
	$(PY) -m runner.cli --scanners all --runs 5 --detail

clean:
	rm -rf .venv results/local __pycache__ .pytest_cache
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +

all: setup images lab-up verify scoreboard
