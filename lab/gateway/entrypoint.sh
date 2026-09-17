#!/bin/sh
# Lab gateway.
#
# Corpus servers sit on an `internal: true` network so they cannot reach the
# internet. Docker will not publish ports from an internal network to the host,
# so nothing on it would be reachable for development or for the Phase 2 runner.
#
# This container bridges the two: it is attached to both the internal lab
# network and the default bridge, publishes every corpus port, and forwards each
# to the corresponding service.
#
# socat resolves the target at connection time rather than at startup, so the
# gateway does not care what order services come up in.
set -eu

forward() {
    port="$1"
    target="$2"
    socat -d TCP-LISTEN:"$port",fork,reuseaddr TCP:"$target":"$port" &
    echo "[gateway] :$port -> $target:$port"
}

forward 8101 a01-tool-description-injection
forward 8102 a02-rug-pull
forward 8103 a03-tool-shadowing
forward 8104 a04-response-injection
forward 8105 a05-argument-exfiltration
forward 8106 a06-authless-endpoint
forward 8107 a07-hardcoded-secrets
forward 8108 a08-unrestricted-file-read
forward 8109 a09-unrestricted-env-access
forward 8110 a10a-command-execution
forward 8111 a10b-allowlist-bypass
forward 8201 c01-notes-workspace
forward 8202 c02-webhook-notifier
forward 8203 c03-release-runner
forward 8204 c04-status-service
forward 8900 sinkhole

echo "[gateway] ready"
wait
