#!/usr/bin/env bash
# Simulate an automated screener: clone this repo into a temp dir, then run `make reproduce` OFFLINE-capable steps.
# Only `uv sync` touches the network (PyPI); the build itself reads committed data/raw only.
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
git clone --quiet "$SRC" "$TMP/near-thesis"
cd "$TMP/near-thesis"
make reproduce
git status --porcelain | grep -v '^??' && { echo "reproduce changed committed outputs"; exit 1; } || true
echo "fresh clone: make reproduce OK, committed outputs unchanged"
