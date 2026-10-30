# NEAR thesis data layer. Keyless: no accounts, no API keys, no .env.
#   make setup      install the locked environment (uv)
#   make reproduce  OFFLINE: rebuild data/processed + reports/metrics_summary.md from committed data/raw, then test
#   make test       run the test suite (manifest sha256, schemas, gaps, sanity ranges, determinism)
#   make refresh    ONLINE: re-download every raw snapshot from public keyless APIs (~1.5 h, rate limited)
#   make verify     check data/raw against data/raw/MANIFEST.json

UV ?= uv
export POLARS_MAX_THREADS ?= 1
export PYTHONHASHSEED = 0

.PHONY: setup reproduce build test refresh fetch verify clean-cache

setup:
	$(UV) sync --frozen

build: setup
	$(UV) run --frozen python -m nearthesis build

reproduce: build test

test: setup
	$(UV) run --frozen pytest -q

verify: setup
	$(UV) run --frozen python -m nearthesis verify

refresh: setup
	$(UV) run --frozen python -m nearthesis refresh
	$(UV) run --frozen python -m nearthesis build

fetch: refresh

clean-cache:
	rm -rf data/cache
