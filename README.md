# NEAR thesis: reproducible, keyless data layer

Data layer and first-pass metrics for a data-backed, long-term investment thesis on NEAR
(NEAR HACKATHON, Nov 1-14 2026, track `thesis`: "judged on the evidence, not the conviction").

- **Keyless by design.** Every source is a public API that answers without an account or API key:
  NearBlocks, DefiLlama, CoinGecko (365-day public window), NEAR archival RPC (FastNear, near.org fallback),
  FastNear account/transactions APIs, Aurora Blockscout, and on-chain view calls (Sputnik DAO). No `.env`,
  no secrets, no Google Cloud, no Dune, no partner tokens.
- **Offline reproduction.** All raw snapshots are committed in `data/raw/` with a `MANIFEST.json`
  (source URL, parameters, fetch time UTC, row count, sha256). `make reproduce` rebuilds every processed table
  and the metrics report from those files without touching the network.
- **No invented numbers.** Every figure in `reports/metrics_summary.md` is computed by `src/nearthesis/`
  from `data/raw/`; the tests check that the committed outputs are exactly what the code produces.

The full plan (questions, metrics, falsifiers, risks) is in [`PIANO.md`](PIANO.md). Source quirks and what could
not be verified are in [`docs/DATA_NOTES.md`](docs/DATA_NOTES.md).

## Reproduce (for automated screeners): do X, see Y

Requirements: macOS or Linux, `make`, and [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`).
uv installs Python 3.12 and the locked dependencies itself.

| Step | Do | See |
|---|---|---|
| 1 | `git clone <repo> && cd near-thesis` | `PIANO.md`, `data/raw/MANIFEST.json`, `Makefile` |
| 2 | `make setup` | `uv sync --frozen` creates `.venv/` from `uv.lock` (only step that uses the network: PyPI) |
| 3 | `make reproduce` | A "Key results (first pass)" table printed to the terminal, then `[build] as-of <date>; wrote ... files`, then pytest ending in `passed` |
| 4 | open `reports/metrics_summary.md` | Tables per thesis question (Q1 activity, Q2 Intents, Q3 agents footprint, Q4 supply, Q5 fees, Q7 peers), supply by year, activity by quarter, peer comparison, series coverage |
| 5 | `git status` | Nothing modified: the rebuilt `data/processed/*.csv` and report are byte-identical to the committed ones |
| 6 (optional) | `make verify` | `[verify] OK`: every raw file matches its sha256 in the manifest |
| 7 (optional, online) | `make refresh` | Re-downloads every snapshot from the public APIs (about 2 hours because of polite rate limits), rewrites the manifest, rebuilds |

`scripts/fresh_clone_check.sh` runs steps 1-5 in a temporary clone. `uv run python scripts/probe_sources.py`
prints a one-request-per-source status table.

## What is in the repo

```
PIANO.md                 plan (sources, questions Q1-Q8, falsifiers, risks)
config/sources.toml      endpoints, per-host rate limits, peer chains, sampling parameters (seeded)
src/nearthesis/
  http.py                polite client: per-host minimum interval, retries (tenacity), immutable-response cache
  manifest.py            MANIFEST.json writer (url, params, fetched_at_utc, rows, sha256)
  fetch/                 one module per source (network, used by `make refresh` only)
  transform/             raw -> tidy tables (daily long table, epoch supply accounting, activity decomposition)
  metrics.py             first-pass metrics, peer table, price-normalized ratios
  report.py, pipeline.py reports/metrics_summary.md and the offline build
data/raw/                committed snapshots (CSV) + MANIFEST.json
data/processed/          rebuilt by `make reproduce` (CSV, committed so they can be inspected without running anything)
reports/metrics_summary.md   generated report
tests/                   manifest integrity, schemas, no-gap checks, sanity ranges, cross-source agreement, determinism
docs/DATA_NOTES.md       per-source notes, quirks, the "active users" ambiguity table, unverified items
scripts/                 source probe, fresh-clone check
```

Key processed tables:

| File | Grain | Content |
|---|---|---|
| `daily_long.csv` | date x chain x metric x source | every daily series (NEAR, Solana, Sui, Aptos, Base, Ethereum, Tron, Aurora), explicit units, no filling |
| `near_daily_wide.csv` | date | the NEAR rows of `daily_long.csv`, one column per metric__source |
| `series_coverage.csv` | series | span, missing days, nulls, longest gap |
| `epochs.csv` | sampled epoch | exact mint, burn, net issuance, annualized rates, realized/cap, staking ratio, validators, Nakamoto coefficient, per-block supply identity |
| `burn_vs_fees_epochs.csv` | sampled epoch | exact burn vs NearBlocks fees prorated to the epoch window |
| `activity_monthly.csv` | month | NearBlocks totals, exact census of txs to 9 contracts grouped as incentivized (HOT, KaiChing, SWEAT, NEARCrowd, inscriptions) and infrastructure (Aurora, Chain Signatures, Intents), sample shares with 90% CIs, organic proxy |
| `activity_quarterly_sample.csv` | quarter | stratified sample shares (relayed, implicit signers, ...) with bootstrap 90% CIs |
| `peers_snapshot.csv` | chain | TVL, stablecoins, fees, DEX volume, market cap, price-normalized ratios, YoY |
| `ratios_daily.csv` | date x chain x ratio | fees/market cap, TVL/market cap, stablecoins/market cap, DEX volume/TVL |
| `metrics_first_pass.csv` | metric | every headline number with window, source and evidence grade |

## Data provenance

Grades: **A** = on-chain, re-runnable from chain data; **B** = aggregator or undocumented endpoint (snapshotted).
Row counts, URLs, parameters and fetch times are in `data/raw/MANIFEST.json`.

| Raw folder | Source (PIANO.md #) | Endpoints | Key? | Limit we respect | Grade | Feeds |
|---|---|---|---|---|---|---|
| `nearblocks/` | NearBlocks (#7) | `/v1/charts`, `/v1/stats` | none | 6 req/min (we wait 11 s), 2 requests per refresh | B | daily txs, active/new accounts, supply, fees, price |
| `defillama/` | DefiLlama (#12) | `historicalChainTvl`, `summary/fees/<chain>`, `overview/dexs/<chain>`, `stablecoincharts`, `summary/{dexs,fees}/near-intents`, `coins.llama.fi/chart`, `v2/chains` | none | 1 req/s | B | TVL, chain fees/revenue, DEX volume, stablecoins, Intents, full price history |
| `coingecko/` | CoinGecko public (#13) | `/coins/<id>/market_chart?days=365` | none | 1 req / 7 s | B | market caps (365 days) |
| `aurora/` | Aurora Blockscout (#19) | `stats-service/api/v1/lines/*`, `/api/v2/stats` | none | 1 req/s | B | Aurora txs, active accounts, fees |
| `rpc/` | NEAR RPC (#1, #20-#22) | `EXPERIMENTAL_genesis_config`, `EXPERIMENTAL_protocol_config`, `validators`, `block`, `view_account`, `sputnik-dao.near get_dao_list` | none | 1 req/s | A | current stake, validators, protocol config, treasury balances, DAO count |
| `rpc_archival/` | Archival RPC (#2, #20, #21) | `block`, `validators`, `EXPERIMENTAL_protocol_config`, `view_account` at historical heights | none | 1 req / 1.5 s | A | per-epoch supply, mint, burn, stake; monthly treasury balances |
| `fastnear_tx/` | FastNear Transactions API (#5) | `/v0/blocks`, `/v0/block`, `/v0/account` | none | 1 req/s | A (chain data via an indexer) | month boundaries, exact monthly counts per contract, stratified block sample |
| `fastnear_api/` | FastNear API (#4) | `/v1/account/<id>/full` | none | 1 req/s | B | treasury token holdings |

Attribution: daily NEAR network data by [NearBlocks](https://nearblocks.io) (required by its free plan);
DeFi data by [DefiLlama](https://defillama.com); market data by [CoinGecko](https://www.coingecko.com);
RPC and indexer data by [FastNear](https://fastnear.com); Aurora data by Blockscout.

## Libraries

Runtime: [httpx](https://www.python-httpx.org) (HTTP), [tenacity](https://tenacity.readthedocs.io) (retries),
[polars](https://pola.rs) (tables), [numpy](https://numpy.org) (bootstrap). Test: [pytest](https://pytest.org).
Build backend: hatchling. Standard library: `tomllib`, `json`, `hashlib`, `fcntl`. Exact versions are pinned in `uv.lock`.

## AI-generated code

All code, tests and documentation in this repository (everything except `PIANO.md`, which was written with AI
assistance as a plan) were written by an AI coding agent (Claude, via Claude Code) under the direction of the
author, and reviewed by running the pipeline and the tests. The numbers are not AI-generated: they are computed by
the code from the committed public-API snapshots.

## License

MIT, see [`LICENSE`](LICENSE). Not financial advice.
