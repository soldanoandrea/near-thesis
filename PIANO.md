# NEAR Investment Thesis: build plan

Track `thesis`, NEAR HACKATHON, Nov 1–14, 2026. Prepared on 2026-10-30. This is a plan only: no code has been written and no accounts have been created.

"Verified" in this document means I fetched the docs page or called the endpoint on 2026-10-30, between about 19:15 and 19:30 UTC. The figures quoted are what those calls returned. The pipeline will compute them again; none of them will be hard-coded.

## 0. Constraints that shape the plan

**Rules** ([HACKATHON.md](https://nearhackathon.com/HACKATHON.md)):
- Submissions open 2026-11-01 and close 2026-11-14 at 23:59 UTC. The repo must be public by then. A submission cannot be edited afterwards.
- The README must give "do X, see Y" steps. It must also list every library and all AI-generated code.
- Claude Code and Codex screen projects for reproducibility. A human jury decides.
- A hosted demo is optional. If we host one, it must stay up at least until 11-18, ideally until 11-25.
- One person can submit at most two projects, and each README must name the other one. This applies if `produzione/near-agent-vault` is submitted too.
- The X post needs a video and must explain NEAR's concrete role.

**Track prompt** ([tracks/02-thesis.md](https://github.com/nearai/near-hackathon-prompt-examples/blob/main/tracks/02-thesis.md)):
- Run BigQuery SQL on `bigquery-public-data.crypto_near_mainnet_us`, always filtered on `block_date`.
- Pull swap volume from the NEAR Intents Explorer API, using a JWT.
- One command rebuilds every chart.
- A static page shows each chart with its query and one plain-language sentence.
- `THESIS.md` covers the claim, the evidence for and against it, and what result would change our mind.
- Never invent numbers.
- Starter hypothesis: *"cross-chain volume through NEAR Intents is a better leading indicator of real network usage than token price"*.

**Design decision: the default path needs no keys.**
- BigQuery needs a Google Cloud account. The Dune API is not available on the free plan. The Intents Explorer needs a partner JWT. All three become optional enrichers that are skipped cleanly when no credentials are present.
- If Andrea approves any key, it is injected from 1Password at runtime (`op run --env-file=.env.tpl -- make fetch-keyed`). Keys are never written to a `.env` file.

## 1. Data sources

**Tier** shows how reproducible a source is:
- **A**: documented and works without a key. Fully reproducible.
- **B**: works without a key but is undocumented or fragile. We snapshot it and use it only as a cross-check.
- **C**: needs an account, a key or a paid plan. Optional.

| # | Source | Endpoint / docs | Key? · limits | History | Provides | Status 2026-10-30 · Tier |
|---|---|---|---|---|---|---|
| 1 | NEAR RPC (FastNear free, near.org) | `https://free.rpc.fastnear.com`, `https://rpc.mainnet.near.org`; [providers list](https://docs.near.org/api/rpc/providers) | No key. Limits not published. "Never load test a shared public endpoint" | Recent blocks only (earliest ≈ block 222.19M) | `status`, block header `total_supply`, `validators`, `EXPERIMENTAL_protocol_config`, view calls | Verified (nearcore 2.14.0, protocol 86) · **A** |
| 2 | Archival RPC | `https://archival-rpc.mainnet.fastnear.com`, `https://archival-rpc.mainnet.near.org` | No key worked. NEAR's endpoint is "severely rate limited". The providers page lists FastNear archival as paid-only, yet it answered without a key | Full (block 50,000,000 tested) | Supply, stake and protocol config at any height (one sample per epoch) | Verified · **A** (fragile) |
| 3 | Other public RPCs | dRPC `near.drpc.org` (~2,100 CU/s), Intear `rpc.intea.rs`, 1RPC (200 req/day) | No key | Recent | Fallbacks | dRPC OK. BlockPI returned 503 · **A** |
| 4 | FastNear API | `https://api.fastnear.com/v1` ([docs](https://docs.fastnear.com)) | No key worked. FastNear recommends using one | Current state | FT and NFT holdings, staking positions per account | Verified · **A** |
| 5 | FastNear Transactions API | `https://tx.main.fastnear.com` ([OpenAPI](https://docs.fastnear.com/openapi/transactions.yaml)) | The docs say to send a key, but calls without one worked. `limit` ≤200 per page, block-range filters, up to 20 tx hashes per call | Not stated (ClickHouse-backed) | Account history with role flags (`is_real_signer`, `is_delegated_signer`, `is_event_log`), receipts, `txs_count` | Verified · **B** |
| 6 | neardata | `https://mainnet.neardata.xyz` ([docs](https://docs.fastnear.com/neardata)) | No key. Redirects must be followed | Old blocks served (height 50M tested) | Full blocks with shards, receipts and logs | Verified · **A** |
| 7 | NearBlocks API | `https://api.nearblocks.io/v1` ([pricing](https://nearblocks.io/apis)) | Free plan: 6 req/min, 333/day, 10k/month, attribution required. `/v1/charts` worked without a key | **2,292 daily rows, 2020-07-21 → 2026-10-29** | 20 fields: txns, active/new accounts, total/circulating supply, fees (USD), price, active/new contracts | Verified · **A** |
| 8 | BigQuery public dataset | `bigquery-public-data.crypto_near_mainnet_us` ([docs](https://docs.near.org/data-infrastructure/big-query)) | Google Cloud account. 1 TB/month free, then $6.25/TB (NEAR docs, 2023 price) | Historical. Start date not stated | Tables: `transactions`, `receipt_actions`, `receipt_origin`, `execution_outcomes`, `account_changes`, … | Docs verified. **Freshness unverified**: NEAR Lake was deprecated on 2026-03-24. Nansen's Q3-2026 report says it used BigQuery · **C** |
| 9 | Pikespeak | `https://api.pikespeak.ai` ([docs](https://docs.near.org/tools/ecosystem-apis/pikespeak-api)) | Needs an `x-api-key` and an account | n/a | Wallet, validator and dApp aggregates | Returned 401 "Missing x-api-key header" · **C** (skip) |
| 10 | Flipside | — | — | — | Was a NEAR SQL source | Free Studio shut down ([Dune migration guide](https://docs.dune.com/learning/flipside-migration-guide)). `docs.flipsidecrypto.xyz` no longer resolves · **not usable** |
| 11 | Dune | [NEAR catalog](https://docs.dune.com/data-catalog/near/overview): `near.actions`, `near.logs`, `near.function_call`, `near.ft_transfers`, balances, circulating supply. NEAR-uploaded `dune.near.dataset_near_intents_{metrics,fees,protocol_fees}`. [Dashboard](https://dune.com/near/near-intents) | API needs a trial or paid plan ([limits](https://docs.dune.com/api-reference/overview/rate-limits)) | Not stated | Intents volume and fees (the upstream source for DefiLlama) | Docs verified · **C** |
| 12 | DefiLlama | `api.llama.fi`, `stablecoins.llama.fi`, `coins.llama.fi` | No key | NEAR TVL from 2021-08-20 · chain fees from 2020-10-14 (via Allium) · stablecoins from 2022-07-10 · Intents volume from 2024-12-10 | TVL, fees, revenue, DEX volume, stablecoins, prices, peer chains | Verified · **A**. The Intents numbers come from the NEAR-uploaded Dune data ([adapter source](https://github.com/DefiLlama/dimension-adapters/blob/master/dexs/near-intents/index.ts)) |
| 13 | CoinGecko / CMC / CoinPaprika | `api.coingecko.com/api/v3` | CoinGecko works without a key but **only for the last 365 days** (error 10012). CMC needs a key (401). CoinPaprika works without a key | 365 days on CoinGecko. Use DefiLlama coins or NearBlocks for full price history | Price, market cap, volume | Verified · **A**/**C** |
| 14 | Token Terminal | [NEAR page](https://tokenterminal.com/explorer/projects/near-protocol) | Paid API (returned 403) | — | Fees and revenue, standardised | Web page OK · **C** (cross-check by hand) |
| 15 | Artemis | [asset page](https://classic.artemis.ai/asset/near), [API docs](https://app.artemis.xyz/docs/artemis-api/endpoints) | Officially needs a key. `api.artemisxyz.com/data/{DAU,FEES,MC}?symbols=near,solana,sui,aptos,base` answered without one | Rows from 2020 (null early values) | DAU, fees, market cap for NEAR and peers | Verified but undocumented · **B** |
| 16 | NEAR Intents | Explorer API `explorer.near-intents.org/api/v0` ([docs](https://docs.near-intents.org/integration/distribution-channels/1click-api/explorer/introduction)). On-chain events from `intents.near` ([events](https://docs.near-intents.org/integration/verifier-contract/events)). [Fees](https://docs.near-intents.org/resources/fees). [revenue.near.org](https://revenue.near.org) | Explorer: partner JWT from partners.near-intents.org (sign-in), 1 request per 5 s, 1Click swaps only. Events: no key | Explorer depth not stated | DIP-4 events `token_diff`, `intents_executed`, `mt_mint`/`mt_burn`/`mt_transfer`. Fee wallets | Explorer returned `MISSING_TOKEN`. The revenue page says "Figures shown are illustrative" · **C** / on-chain **A** |
| 17 | Rhea (ex-Ref) | DefiLlama (Rhea Dex, Rhea Lend, RHEA LST). `indexer.ref.finance`, `api.rhea.finance` ("ref datacenter API") | No key, undocumented | Unknown | Pools and prices (current) | Verified · **A** via DefiLlama, **B** direct |
| 18 | HOT Wallet | No public stats API found. On-chain contract `game.hot.tg` | — | Full, via chain data | Mining and gamified activity share | `txs_count` = 2,173,322,127 (FastNear tx API) · **A**/**B** |
| 19 | Aurora | Blockscout `explorer.mainnet.aurora.dev/api/v2` + DefiLlama | No key | Full | EVM activity, TVL ($4.08M) | Verified · **A** |
| 20 | Staking / validators | RPC `validators` + archival sampling. [nearscope.net](https://nearscope.net) | No key. Nearscope has no documented API | Per epoch | Stake, validator count, Nakamoto coefficient | 381 validators, 593.5M NEAR staked · **A** |
| 21 | Tokenomics / governance | Protocol config via RPC. [HSP-029 coverage](https://thedefiant.io/news/blockchains/near-opens-vote-to-cut-token-issuance-to-1-6). [tokenomist.ai](https://tokenomist.ai/near) (paid API) | — | — | `max_inflation_rate`: 1/20 at height 160M, 1/40 at height 200M and now. `protocol_reward_rate` = 0. Epoch length 43,200 | Verified · **A** |
| 22 | Sputnik DAO / treasuries | `sputnik-dao.near` view calls. Revenue wallets `fefundsadmin.sputnik-dao.near`, `1csfundsadmin.sputnik-dao.near`, `buybacks.multisignature.near` | No key | Full | DAO count (2,043), proposals, revenue sweeps, buybacks | Verified · **A** |
| 23 | Developer activity | Electric Capital [Open Dev Data](https://github.com/electric-capital/crypto-ecosystems) (`uvx open-dev-data download`, CC-BY-4.0, about 100 GB full, with a lite version). GitHub REST API | No key. GitHub allows 60 req/h without a token (verified) | Multi-year | Ecosystem → repos taxonomy, developer activity, commits | Verified. **The NEAR ecosystem key and its metric tables still need checking** · **A** |
| 24 | NEAR AI / agents | Agent Market `market.near.ai` ([OpenAPI](https://market.near.ai/openapi.json); `GET /v1/agents` is public). Chain Signatures contract `v1.signer`. [Staking for inference](https://docs.near.ai/cloud/staking-for-inference/overview) | No key for the catalogue. The job board needs auth | Unknown | Agent listings (off-chain, UUIDs), MPC signing requests (on-chain) | `v1.signer` `txs_count` = 12,659,746. The staking pool account is not documented · **B** |
| 25 | Reports | Nansen [Q3-2026](https://nansen.ai/post/near-q3-2026-report), [Q2-2026](https://nansen.ai/post/nansen-near-quarterly-report-q2-2026). [Messari](https://messari.io/project/near-protocol) | Messari's API needs a key | — | Context and benchmarks only. No 2026 Messari NEAR quarterly report found | **context only** |

### 1.1 Pilot readings from the 2026-10-30 probes (to be regenerated)

- **Realized supply growth** (NearBlocks `total_supply`):
  - +5.008% from 2024-10-29 to 2025-10-29.
  - +2.465% from 2025-10-31 to 2026-10-29.
  - This matches the 5% → 2.5% inflation cap shown in the protocol config history. The cut went live 2025-10-30.
- **Burn vs. issuance:**
  - Chain gas fees over 30 days: about $200k (NearBlocks) and $202k (DefiLlama). The two sources agree.
  - 70% of gas fees is burned, about $140k. Issuance is about 32.8M NEAR/yr, roughly $11.7M per month at $4.27. **Burn offsets about 1% of issuance.**
- **NEAR Intents, last 30 days** (DefiLlama):
  - Volume $3.89B, fees $6.16M, captured revenue $2.18M.
  - Captured revenue is about **19% of monthly issuance value**.
  - All-time: $35.7B volume, $57.6M fees.
  - The buyback wallet holds 2.135M NEAR (RPC).
- **Staking ratio:** about 45% (593.5M staked out of 1,310.4M supply).
- **"Active users" depends on the source:**
  - NearBlocks `active_accounts`, 30-day average: 73,294.
  - Artemis DAU on 2026-10-20: 66,596.
  - Nansen's Q3 average of daily signers: 79,300.

## 2. Thesis architecture

Each question lists metrics, sources, a model and a falsifier. We will set the falsifier thresholds and commit them in `config/predictions.yaml` **before** running the analysis. A failed falsifier is reported, not hidden.

**Q1. Is the activity real, or mostly bots and gamified farming?**
- *Metrics:*
  - Transactions and active accounts.
  - Share of transactions touching `game.hot.tg`, relayer transactions (`is_delegated_signer`), implicit vs. named accounts, single-contract concentration.
  - Fee-paying vs. sponsored transactions.
- *Sources:* NearBlocks charts (#7); a stratified random sample of blocks per month (#6/#5); BigQuery per-account features when available (#8).
- *Model:*
  - Rule-based bot score per signer: regular timing (coefficient of variation of gaps between transactions), method diversity, counterparty entropy, account age.
  - Decompose activity into HOT, other bots and residual "organic" activity, with bootstrap confidence intervals.
  - Monthly cohort retention curves for new accounts, with and without HOT.
- *Falsifier:* organic active accounts show no growth over the last 24 months, **and** month-3 cohort retention does not improve.

**Q2. Is NEAR Intents volume real, growing, durable, and is it a leading indicator?**
- *Metrics:*
  - Daily volume, fees and captured revenue.
  - Volume concentration by asset and chain (Herfindahl index).
  - Share of volume through near.com.
  - Confidential vs. public volume.
- *Sources:* DefiLlama (#12), on-chain `token_diff` events (#5/#6), the Dune dashboard (#11, optional).
- *Model:*
  - Fit a logistic or Gompertz S-curve to cumulative volume, compared against an exponential baseline using a rolling-origin backtest.
  - For the starter hypothesis: lead-lag cross-correlation and Granger tests on log-differences (Intents volume → organic actives vs. price → organic actives), with an out-of-sample comparison of forecast error.
- *Falsifier:*
  - 90-day volume falls for two consecutive quarters; **or**
  - the top asset accounts for more than 40% of volume (fragility); **or**
  - our reconstructed on-chain volume differs from reported volume by more than 20% on sampled days; **or**
  - price leads usage better than Intents volume does.

**Q3. Does the AI-agent story show up on-chain?**
- *Metrics:*
  - Chain Signature (`v1.signer`) requests per day.
  - Intents solver accounts and their transaction share.
  - Stake in NEAR AI inference pools, once the pool is identified.
  - Agent Market catalogue size and delivered-job counts. These are off-chain and labelled as such.
  - Share of transactions signed by function-call access keys.
- *Sources:* #5, #24, #2.
- *Model:* growth rates plus an "evidence ratio": activity we can attribute to agents divided by all fee-paying activity.
- *Falsifier:* activity attributable to agents stays below 1% of fee-paying transactions and does not grow quarter on quarter. In that case the AI leg is narrative only.

**Q4. Supply dynamics: inflation vs. burn vs. buyback, staking, unlocks, treasury.**
- *Metrics:*
  - `total_supply` per epoch, gas burn, and NEAR bought back per month.
  - Staking ratio, circulating vs. total supply.
  - Balances of known treasury and foundation accounts.
- *Sources:* #1, #2, #7, #12, #22.
- *Model:*
  - An accounting identity: Δsupply = issuance − burn. Tested per epoch.
  - Supply projection under 2.5% issuance vs. **HSP-029** (1.6% phased in over 24 months; the vote is reported to close around Nov 2, 2026).
  - A "net-zero threshold" surface: the Intents volume × take rate × price at which burn plus buyback equals issuance.
- *Falsifier:* net dilution after buybacks stays above 2%/yr and the threshold needs more than 10× current volume at the current take rate.

**Q5. Fee revenue and value accrual.**
- *Metrics:*
  - Gas fees vs. Intents fees.
  - Take rate (captured revenue ÷ volume) over time.
  - Holder yield (buyback + burn) ÷ market cap vs. the dilution rate.
- *Sources:* #12, #22, #13.
- *Model:*
  - Monte Carlo valuation using explicit priors in `config/priors.yaml`: volume growth, take rate, issuance path, buyback share, exit multiple.
  - A reverse-DCF "what you have to believe": the volume path implied by today's market cap.
- *Falsifier:* the take rate shrinks as volume grows, so revenue growth stays below volume growth for 3 or more quarters (fees are being competed away).

**Q6. Developer activity.**
- *Metrics:*
  - Monthly active developers and NEAR's share of all crypto developers.
  - Core repository cadence (nearcore, intents).
  - New and active contracts.
- *Sources:* #23, #7.
- *Model:* trend and share analysis, plus a peer panel regression of usage on developer counts lagged 2–4 quarters.
- *Falsifier:* NEAR's share of developers falls for 4 or more consecutive quarters while peers' shares rise.

**Q7. Comparables (Solana, Sui, Aptos, Base; Ethereum and Tron as anchors).**
- *Metrics:* DAU, fees, TVL, stablecoin market cap, DEX volume, market cap and FDV.
- *Sources:* #12, #15, #13.
- *Model:*
  - Cross-sectional regression of log(market cap) on log(fees), log(DAU) and log(stablecoins), giving NEAR's residual with a prediction interval.
  - A Metcalfe-style fit, market cap ∝ DAU^α, where α is estimated rather than assumed.
  - Base has no native token. We keep it as a usage benchmark only, outside the valuation fit.
- *Falsifier:* NEAR's residual is positive (rich) under every specification. That would mean the valuation rests on narrative.

**Q8. Risks and falsifiable predictions.**
- We publish `predictions.yaml` with dated, numeric predictions for 2027-02-28 and 2027-10-31, taken from the 80% intervals of the model outputs (not chosen by hand).
- We record its SHA-256 hash in the git tag.
- Optionally, we anchor the hash in a NEAR transaction. This needs a NEAR account, so it requires Andrea's approval.

## 3. Originality angle

1. **An activity decomposition that needs no keys.** We estimate the shares of HOT, relayer, bot and organic activity from a stratified random sample of blocks, with confidence intervals. Anyone can re-run it without BigQuery.
2. **An independent check of the Intents numbers.** DefiLlama's Intents volume is a NEAR-uploaded Dune dataset. We rebuild sampled days independently from `token_diff` and `mt_*` events and publish the ratio between the two.
3. **A value-flow ledger.** Monthly Sankey chart: issuance to validators, gas split 70% burn / 30% contract developers, Intents fees to the front-end and 1Click wallets, then to buybacks. Every flow is traced to account IDs.
4. **A metric reconciliation table.** It explains why NearBlocks, Artemis and Nansen report different "users", with a definition next to each number.
5. **Pre-registered falsifiers, hashed before the results are known.**
6. **A clear treatment of policy changes.** We use event windows around the 2025-10-30 inflation halving, the 2026-02-23 start of Intents buybacks and HSP-029, and we state the confounders.

**How we present uncertainty:**
- Every chart card carries the source endpoint, `fetched_at`, the query or code link, a one-sentence finding, a 90% CI or scenario band, and an **evidence grade**: A = on-chain and re-runnable; B = aggregator; C = self-reported or unverifiable.
- The bear case gets its own tab with the same prominence as the bull case.
- Valuation is shown as fan charts, never as a single price target.
- We include a "not financial advice" disclaimer.

## 4. Repo and tooling

- Python 3.12 with **uv** (`uv.lock` committed).
- Libraries: httpx and tenacity for fetching, polars, duckdb and pyarrow for data, statsmodels, scipy and numpy for models, pandera for schemas, plotly and jinja2 for the site, pytest for tests. All of them are listed in the README.

```
near-thesis/
  README.md  THESIS.md  LICENSE(MIT)  Makefile  pyproject.toml  uv.lock
  config/{sources,priors,predictions}.yaml   .env.tpl (op:// refs only)
  src/near_thesis/fetch/   one module per source; raw → data/raw/<src>/*.parquet
  src/near_thesis/{transform,models,viz,site}/
  sql/bigquery/*.sql       (block_date-filtered; dry-run bytes printed first)
  data/raw/ + MANIFEST.json (url, params, fetched_at, sha256)   data/processed/
  tests/   site/ (generated)   .github/workflows/{ci,pages}.yml
```

**Make targets:**
- `make reproduce`: `uv sync --frozen`, then transform, models, tests and site, all **offline from the committed raw data**. It prints a key-results table and writes `site/index.html`. This is the "see Y" the judge checks.
- `make fetch`: refreshes the raw data from the A and B sources that need no key.
- `make verify-live`: fetches a small fresh sample and compares it with the snapshot within a tolerance.
- `make fetch-keyed`: optional BigQuery, Dune and Intents Explorer fetches. Skipped when no credentials are set.

**Caching:** fetches are idempotent and resumable. Raw responses are cached by a hash of URL and parameters. Backoff starts at 1 req/s, or slower where limits are published. Committed data should stay under 50 MB.

**Dashboard:** static HTML generated by Python with Plotly, so there is no Node toolchain and it opens locally. It deploys to GitHub Pages through Actions and stays up past 11-25. After the `hackathon-submission` tag, nothing more is pushed to `main`.

**Tests:**
- Schema checks, date continuity and no duplicates.
- Supply identity holds per epoch.
- Cross-source fees (NearBlocks vs. DefiLlama) agree within 5%.
- Manifest checksums match.
- Models are deterministic with fixed seeds (golden outputs).
- gitleaks scan for secrets in CI.

## 5. Schedule

| Day | Milestone |
|---|---|
| Nov 1 | Repo skeleton, uv, Makefile, CI, LICENSE. `make probe` writes a source-status table. Andrea decides on BigQuery, Dune and the JWT. Freeze the falsifier thresholds. |
| Nov 2 | Fetchers for the aggregate sources (NearBlocks, DefiLlama ×5, coins, Aurora, CoinGecko) plus the manifest and integrity tests. Snapshot HSP-029 status. |
| Nov 3 | Archival epoch sampler from genesis: supply, stake, validators, protocol config. Supply identity tests. |
| Nov 4 | Revenue and buyback ledger: wallet histories, sweeps, NEAR bought. Reconcile with DefiLlama. Sputnik DAO stats. |
| Nov 5 | Stratified block sampler, bot score, activity decomposition with confidence intervals. Cohorts via BigQuery if approved. |
| Nov 6 | Intents check: sample `intents.near` transactions, parse events, price them, compare with reported volume. Concentration analysis. |
| Nov 7 | Agent fingerprints (Chain Signatures, solvers, Agent Market snapshot) and developer activity (Open Dev Data, GitHub). |
| Nov 8 | Peer panel. Cross-sectional regression and Metcalfe fits. |
| Nov 9 | S-curves with backtests, Granger lead-lag tests, supply scenarios (2.5% vs. 1.6%), Monte Carlo and reverse DCF. |
| Nov 10 | Dashboard build with evidence grades. `predictions.yaml` hashed. Pages deploy. |
| Nov 11 | `THESIS.md` (claim, evidence for and against, what would change our mind), reconciliation table, bear-case tab. |
| Nov 12 | README written for agents. Fresh-clone run by Claude Code and Codex in a clean environment, then fixes. |
| Nov 13 | Dashboard polish (mobile, dark mode). Record the video. |
| Nov 14 | Andrea approves the X post and the form payload. Tag `hackathon-submission`. Submit well before 23:59 UTC. |

**Video, 3 minutes or less:**
- 0:00–0:15: the question and "judged on evidence".
- 0:15–0:45: fresh clone, run `make reproduce`, the dashboard opens.
- 0:45–1:40: three findings: organic activity, the Intents check, the issuance vs. burn and buyback ledger.
- 1:40–2:15: valuation fan chart and "what you have to believe".
- 2:15–2:45: the bear case, the falsifiers and the predictions hash.
- 2:45–3:00: NEAR's role and links.

## 6. Risks and what cannot be verified

- **BigQuery freshness and access.** It needs a Google Cloud account, and whether data is still flowing after NEAR Lake's deprecation is unconfirmed. Mitigation: `MAX(block_date)` check on Day 1, otherwise the keyless sampling path.
- **Single-sourced Intents numbers.** DefiLlama, revenue.near.org and the Dune dashboard all rely on data uploaded by the NEAR team. revenue.near.org labels its figures "illustrative". Confidential intents (about $144–160M in TVL) cannot be observed by design, so our check covers public intents only.
- **Fragile access without keys.** FastNear archival and tx APIs, the near.org archival RPC (severely rate limited), NearBlocks (6 req/min) and Artemis (undocumented) may throttle or close. Mitigation: committed snapshots and polite rate limits.
- **CoinGecko only gives 365 days without a key.** We use DefiLlama coins or NearBlocks for full price history.
- **Metric definitions differ:** accounts, signers and addresses are counted differently by each source. The `txs_count` figures from FastNear are role-inclusive counts, not shares of all transactions.
- **Agent activity is hard to observe.** The Agent Market is off-chain (UUID accounts, platform escrow). The NEAR AI staking pool is not documented. Activity in trusted execution environments and confidential payments is invisible to us.
- **Unverified claims from secondary sources** (we will not use them as inputs): the April 2026 Rhea Lend exploit, Electric Capital's NEAR developer counts, HOT user counts, and Flipside's sale to SonarX.
- **Small samples and regime changes:** the halving, the buybacks, HSP-029 and possibly sharding upgrades. Reflexivity between price and activity.
- **Compliance.** No secrets anywhere in git history. Keys stay in 1Password. A second project means each README names the other. The X post and the submission go out only after Andrea gives explicit approval. The payout needs a mainnet NEAR account.
