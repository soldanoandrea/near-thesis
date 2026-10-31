# NEAR thesis data layer. Keyless: no accounts, no API keys, no .env.
#   make setup      install the locked environment (uv)
#   make reproduce  OFFLINE: rebuild data/processed, the reports, thesis/THESIS.md and site/ from committed data/raw, then test
#   make site       OFFLINE: rebuild thesis/THESIS.md and the static dashboard site/ from data/processed
#   make test       run the test suite (manifest sha256, schemas, gaps, sanity ranges, determinism)
#   make refresh    ONLINE: re-download every raw snapshot from public keyless APIs (~2 h, rate limited)
#   make verify     check data/raw against data/raw/MANIFEST.json

UV ?= uv
export POLARS_MAX_THREADS ?= 1
export PYTHONHASHSEED = 0

.PHONY: setup reproduce build site test refresh fetch verify clean-cache

setup:
	$(UV) sync --frozen

build: setup
	$(UV) run --frozen python -m nearthesis build

site: setup
	$(UV) run --frozen python -m nearthesis site

reproduce: build site test

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
