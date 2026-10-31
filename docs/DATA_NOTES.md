# Data notes

What each keyless source provided, the quirks found while building the phase-1 data layer, and what could not be
verified. Probes and fetches ran on 2026-10-30 (UTC). Row counts, URLs, parameters, fetch times and sha256 of every
committed file are in `data/raw/MANIFEST.json`; the generated "Raw snapshot inventory" in
`reports/metrics_summary.md` lists rows and covered dates per file. This file contains no computed metrics: those
live in `reports/metrics_summary.md` and `data/processed/`.

Conventions used everywhere:
- **Dates are UTC.** A daily value dated D is either the flow during UTC day D (transactions, fees, volume) or the
  state at 00:00 UTC of D (price, market cap, TVL, supply), following each provider.
- **As-of date** = the last complete UTC day before the earliest fetch of the daily sources. Rows after it are
  dropped so that partial days never enter a sum.
- **Nothing is filled or smoothed.** Missing days stay missing and are counted in `data/processed/series_coverage.csv`.
- **yoctoNEAR** (10^-24 NEAR) integers are stored as strings in `data/raw/` and converted only in processing; the
  supply identities are checked with exact integer arithmetic.

## 1. Sources

### NearBlocks (`data/raw/nearblocks/`, PIANO.md #7, grade B)
- Fetched: `GET https://api.nearblocks.io/v1/charts` (the whole daily history, 2020-07-21 to the day before the fetch,
  in one response) and `GET /v1/stats` (current snapshot). No key. Two requests per refresh, 11 s apart (free plan:
  6 req/min, 333/day, 10k/month, attribution required; attribution is in the README).
- Kept verbatim (all 20 fields, as strings). `total_supply`, `circulating_supply`, `gas_fee`, `txn_fee`,
  `txn_volume` are yoctoNEAR.
- Quirks:
  - `near_price` and `market_cap` are `0` before the token traded (2020-07-21 to mid October 2020). Processing treats
    0 as missing (nulls are visible in `series_coverage.csv`).
  - `near_price` for date D is the price at 00:00 UTC of D: it matches CoinGecko's 00:00 point for the same date, not
    the next one (`tests/test_sanity.py::test_price_sources_agree`).
  - Two fee fields: `gas_fee` (gas used x gas price) and `txn_fee` (fees attributed to transactions). They diverge
    in recent months. We use `txn_fee` / `txn_fee_usd`, which agree with DefiLlama's NEAR chain fees within 5% over
    30 and 365 days (`test_fee_sources_agree_within_5pct`). Both are kept in `daily_long.csv`.
  - `active_accounts` is not documented in detail by NearBlocks (see section 2).

### DefiLlama (`data/raw/defillama/`, #12, grade B)
- Fetched (no key, 1 req/s), for NEAR, Solana, Sui, Aptos, Base, Ethereum, Tron (and Aurora for TVL):
  - `api.llama.fi/v2/historicalChainTvl/<Chain>` -> `chain_tvl_daily.csv`
  - `api.llama.fi/summary/fees/<chain>?dataType=dailyFees|dailyRevenue` (the chain itself, category "Chain") ->
    `chain_fees_daily.csv`
  - `api.llama.fi/overview/dexs/<chain>` (`totalDataChart`; for NEAR also `totalDataChartBreakdown`) ->
    `dex_volume_daily.csv`, `dex_volume_near_by_protocol_daily.csv`
  - `stablecoins.llama.fi/stablecoincharts/<Chain>` (sum over peg types of `totalCirculatingUSD`) ->
    `stablecoins_daily.csv`
  - `api.llama.fi/summary/dexs/near-intents?dataType=dailyVolume` and `summary/fees/near-intents?dataType=dailyFees|
    dailyRevenue|dailyHoldersRevenue` -> `near_intents_daily.csv`
  - `coins.llama.fi/chart/coingecko:<id>?start=..&span=400&period=1d` (paged) -> `coin_prices_daily.csv` (full price
    history, which the keyless CoinGecko API does not give)
  - `api.llama.fi/v2/chains` -> `chains_snapshot.csv` (current TVL of every chain, for rank context)
- Quirks:
  - **NEAR's DEX volume includes NEAR Intents.** On DefiLlama, `overview/dexs/near` counts NEAR Intents (cross-chain
    swaps settled on NEAR) as a NEAR DEX, and it dominates the total. For peer comparisons we also publish
    `dex_volume_ex_intents_usd` (breakdown sum without "NEAR Intents"). The overview total and the sum of its
    breakdown are not always identical on a given day; the ex-Intents series is computed from the breakdown only.
  - **Intents numbers are single-sourced.** DefiLlama's adapter (`dimension-adapters/dexs/near-intents`) reads a
    NEAR-uploaded Dune dataset. We have not reconciled them with on-chain events yet (phase 2, PIANO.md section 3.2).
  - `coins.llama.fi/chart` samples sit near midnight but on either side (for example 00:09:05 or 23:59:56). Processing
    assigns each sample to the nearest 00:00 UTC; with the naive "UTC date of the timestamp" rule about 15% of days
    looked missing and others were duplicated.
  - Chain fee coverage starts at different dates per chain (DefiLlama's own coverage, for example Sui from 2024-07-01).
    Peer ratios are computed at a common as-of date (`peers_as_of`, the last date present in every peer's TVL, fee and
    DEX series).
  - Source gaps kept as is: Solana stablecoins has a long gap in DefiLlama's history; a few peer DEX / fee series and
    early peer prices miss single days. All are listed in the coverage section of the report.

### CoinGecko public API (`data/raw/coingecko/`, #13, grade B)
- Fetched: `GET /api/v3/coins/<id>/market_chart?vs_currency=usd&days=365&interval=daily` for near, solana, sui,
  aptos, ethereum, tron. No key, one request every 7 s.
- Quirks: keyless access refuses ranges older than 365 days (error 10012), so market caps for peers exist only for
  the last 365 days. The last point of each response is the live price at fetch time, not a 00:00 point; it is
  dropped. Base has no native token and is a usage benchmark only (no market cap ratios).

### Aurora (`data/raw/aurora/`, #19, grade B)
- Fetched: Blockscout stats service `GET https://explorer.mainnet.aurora.dev/stats-service/api/v1/lines/{newTxns,
  activeAccounts,newAccounts,txnsFee}?resolution=DAY&from=2020-01-01&to=<fetch date>` and `GET /api/v2/stats`.
- Quirks: `/api/v2/stats/charts/transactions` returns only 30 days; the stats-service lines return the full daily
  history. The current day is flagged `is_approximate` and dropped. Lines start on 2020-01-01 with zeros before
  Aurora launched; leading zeros are trimmed. `txnsFee` is in ETH (Aurora's gas token). Aurora addresses are EVM
  addresses: not additive with NEAR accounts.

### NEAR RPC, current state (`data/raw/rpc/`, #1, #20-#22, grade A)
- Fetched from `https://free.rpc.fastnear.com` (fallback `rpc.mainnet.near.org`): `EXPERIMENTAL_genesis_config`,
  `block {finality: final}`, `EXPERIMENTAL_protocol_config` at that block, `validators [null]` (current epoch, per
  validator stake and production counters), `view_account` for `buybacks.multisignature.near`,
  `fefundsadmin.sputnik-dao.near`, `1csfundsadmin.sputnik-dao.near`, `treasury.near`, and the view call
  `sputnik-dao.near.get_dao_list`.
- These are snapshots at refresh time; they change on every refresh.

### Archival RPC (`data/raw/rpc_archival/`, #2, #20, #21, grade A)
- Fetched from `https://archival-rpc.mainnet.fastnear.com` (fallback `archival-rpc.mainnet.near.org`), one sampled
  epoch every 28 epochs (about 14 days) from genesis: `block`, `validators {epoch_id}`, `EXPERIMENTAL_protocol_config
  {block_id}`. For each sample, epoch E-1 is fully characterized (first block, last block, next epoch's first block)
  plus the block right after its first block, used for an exact identity check. Monthly `view_account` of the four
  wallets above at the first block of each month since 2024-01 -> `treasury_monthly.csv`.
- Identities (exact, yoctoNEAR):
  - within an epoch: `supply(b) = supply(prev(b)) - sum(chunk.balance_burnt for chunks included at b)`
    (verified on every sampled pair, `test_supply_identity_holds_exactly`);
  - mint lands on the first block of an epoch: `mint = supply(first) - supply(prev) + burnt(first)`.
- Quirks found:
  - **`validators` by epoch id is unavailable before epoch 545 (about March 2021) on both FastNear and near.org
    archival nodes** (`UNKNOWN_EPOCH`). For those early samples the epoch boundaries are found by bisection on the
    block-header `epoch_id` (monotone predicate), so supply, mint and burn still cover the whole history, but stake,
    validator count and Nakamoto coefficient are empty before epoch 545.
  - `validators {block_id}` only answers for the last block of an epoch (`VALIDATOR_INFO_UNAVAILABLE` otherwise), so
    we query by `epoch_id` taken from block headers.
  - The sum of `validator_reward_paid_prev_epoch` does not equal the amount minted at the start of the same epoch,
    the next one, or the one before (checked on epochs around height 50,000,000). We do not use it for issuance;
    issuance comes from supply deltas only. We use the map only for the share paid to `treasury.near`.
  - `EXPERIMENTAL_protocol_config` reports `protocol_reward_rate = 0/1` at heights where the rewards map still shows
    `treasury.near` receiving about 10% of the epoch's rewards (October 2021). The field does not describe what was
    paid; the paid share is reported from the rewards map.
  - The genesis config has `max_inflation_rate = 0/1`; protocol config later reports 1/20 and then 1/40. The change
    dates are bracketed by sample dates in `data/processed/protocol_events.csv`.
  - A skipped height comes back as HTTP 422 with a JSON-RPC `UNKNOWN_BLOCK` error body (not HTTP 200 with an
    `error` field, as on other nodes). The client maps JSON-RPC error bodies on 4xx responses to the same
    non-retryable error, and the samplers move to the next existing height.
  - `validators.epoch_start_height` can be a height with no block (for example 61,876,281 is skipped; the epoch's
    first block is 61,876,282). The sampler takes the first existing block at or after it and asserts its epoch id.
  - `status` on the archival endpoint reports an `earliest_block_height` near the head even though old blocks are
    served.
  - **Rate limiting:** FastNear archival answered HTTP 429 at 1 req/s while the FastNear Transactions API was being
    used at the same time from the same machine (FastNear appears to rate-limit across its services). The fetchers
    now space archival calls 1.5 s apart, slow a host down by 25% after each 429, and `make refresh` runs sources
    sequentially. Responses for finalized history are cached in `data/cache/` (not committed), so an interrupted
    refresh resumes without repeating requests.

### FastNear Transactions API (`data/raw/fastnear_tx/`, #5, grade A via indexer)
- Fetched from `https://tx.main.fastnear.com` without a key (the docs recommend one; none was needed):
  - `POST /v0/blocks` -> `month_boundaries.csv`: first block at or after 00:00 UTC of each month (interpolation
    search with a bisection fallback; the final row is 00:00 UTC of the fetch day and closes the partial month).
  - `POST /v0/account {account_id, is_real_receiver: true, from_tx_block_height, to_tx_block_height, limit: 1}` ->
    `monthly_receiver_counts.csv`: `txs_count` is the exact number of matching transactions in the range (not the page
    size) for nine contracts. Four come from PIANO.md (`game.hot.tg`, `aurora`, `v1.signer`, `intents.near`); five
    were added because they dominate the block sample in at least one year: `earn.kaiching` and `wallet.kaiching`
    (KaiChing rewards, the largest receiver in the 2026 sample and the main driver of the April 2026 drop in
    NearBlocks transactions), `token.sweat` (SWEAT), `app.nearcrowd.near` (NEARCrowd, 2021-2022) and
    `inscription.near` (NEAR inscriptions, late 2023). `config/sources.toml` groups them as *incentivized* (HOT,
    KaiChing, SWEAT, NEARCrowd, inscriptions) and *infrastructure* (Aurora relay, Chain Signatures, Intents).
  - **`is_real_receiver` counts involvement, not the top-level receiver.** A transaction is counted for every
    account that receives a receipt in it (cross-contract calls included). Evidence: in January 2026 the counts of
    `earn.kaiching` and `wallet.kaiching` add up to more than all NearBlocks transactions of the month, while in the
    block sample `wallet.kaiching` is the top-level receiver of only a few percent of transactions. Consequences:
    counts of different contracts must not be summed blindly. Group totals add only *primary* contracts (whose
    census/sample ratio is close to 1); `wallet.kaiching` is reported but not added. `data/processed/census_vs_sample.csv`
    gives, per contract, the census count vs the top-level count implied by the block sample.
    `receiver_txs_alltime.csv` is the same count without a range (for the receivers configured at the time of the
    `onchain` step).
  - `POST /v0/block {block_id, with_transactions: true}` -> `block_sample_blocks.csv`, `block_sample_txs.csv`:
    30 uniform random heights per calendar month (numpy `default_rng([20261101, yyyymm])`), every transaction of
    each sampled block (signer, receiver, real signer/receiver after unwrapping meta-transactions, `is_relayed`).
- Quirks found:
  - **`to_tx_block_height` / `to_block_height` are inclusive**, although the OpenAPI spec says exclusive
    (`from = to = 201000000` returns a transaction at height 201000000). The fetcher passes `next_boundary - 1`.
  - `/v0/blocks` returns the newest blocks first unless `desc: false` is sent; with only `from_block_height` it
    returned the chain head.
  - A skipped height returns `{"block": null}`; the sampler moves to the next existing height.
  - Count queries over long ranges are slow server-side (tens of seconds per month for the tracked accounts).
  - Coverage of early history is not documented. Block rows exist from genesis; the earliest `wrap.near` transaction
    returned is at height 29,998,008 (February 2021). The monthly "sample vs NearBlocks" ratio in
    `activity_monthly.csv` is a coverage cross-check between the two indexes.
  - `txs_count` is per transaction and per role filter. The all-time numbers in PIANO.md were role-inclusive (any
    role); ours use `is_real_receiver` only, so they are not comparable one to one.

### FastNear API (`data/raw/fastnear_api/`, #4, grade B)
- `GET https://api.fastnear.com/v1/account/<id>/full` for the four wallets: FT balances (raw units, decimals not
  resolved), NFT contracts, staking pools. Current state only.

### Sources in PIANO.md that this phase does not use
- BigQuery, Dune, NEAR Intents Explorer (need an account, a paid plan or a partner JWT): excluded by decision.
- Artemis (`api.artemisxyz.com`, undocumented keyless endpoint, grade B): not in the agreed source list for this
  phase; its DAU figure appears only in the reconciliation table below, as a PIANO.md pilot reading.
- neardata, Pikespeak, Token Terminal, Messari, Electric Capital / GitHub (developer activity, Q6), NEAR AI Agent
  Market (Q3): not fetched in phase 1.

### Findings that change how PIANO.md assumptions should be read
Numbers are in `reports/metrics_summary.md` under the metric ids given here; they are not repeated in this file.
- **Inflation started later than genesis.** The protocol config reports `max_inflation_rate = 1/20` from early
  epochs, but the first sampled epoch with a non-zero mint starts at the end of October 2020 (`epochs.csv`,
  `reward_formula = none` before that).
- **Two reward formulas.** Up to protocol 44 the mint matches the block-based formula
  (`supply x rate x epoch_length / num_blocks_per_year`); from protocol 45 it matches the time-based formula
  (`supply x rate x epoch_duration / 365 days`). This was inferred from the data, not from nearcore documentation;
  `realized_to_cap` uses the formula in force and `test_supply_ranges` checks it stays within 0.80-1.01.
- **The 2.5% cap is visible in the data.** The `max_inflation_rate` change is bracketed by two samples around
  2025-10-30 (`protocol_events.csv`); realized supply growth before and after is `q4.supply_growth_prev_365d` and
  `q4.supply_growth_365d`.
- **Burn share of fees is above the 70% assumed in PIANO.md** (`q5.burn_share_of_fees_365d`,
  `q5.burn_share_of_gas_fees_365d`). The 30% developer reward applies only to the execution gas of function calls,
  so the burned share of all fees is higher than 70%. Which NearBlocks fee field is the denominator matters.
- **April 2026 structural break.** NearBlocks daily transactions fall sharply between March and April 2026
  (`activity_monthly.csv`, column `nb_txns`). The census shows it is mostly the end of KaiChing (`earn.kaiching`), not HOT. Event windows in phase 2
  should include it next to the inflation cut, the start of buybacks and HSP-029.
- **Buyback wallet.** `buybacks.multisignature.near` has a balance only from April 2026 and grows every month since
  (`treasury_monthly.csv`). `treasury.near` was largely emptied in May 2026 and since then grows by
  about its 10% share of epoch rewards per month (`q4.treasury_median_monthly_change_6m`,
  `q4.treasury_reward_share_last_sample`). Where its NEAR went is not traced in phase 1.

## 2. "Active users": one word, several definitions

| Number | Source | Definition | Produced by this pipeline? |
|---|---|---|---|
| `active_accounts` daily, 30-day average | NearBlocks `/v1/charts` | Distinct NEAR accounts active per UTC day, NearBlocks definition (signer only, or any role, is not documented) | Yes: `q1.active_accounts_30d_avg` in the report |
| Aurora `activeAccounts` daily, 30-day average | Blockscout stats service | Distinct EVM addresses sending transactions on Aurora per day | Yes: `q1.aurora_active_accounts_30d_avg` |
| Artemis DAU (PIANO.md pilot: 66,596 on 2026-10-20) | Artemis, undocumented endpoint | Artemis's daily active addresses for NEAR | No (pilot reading only, not regenerated) |
| Nansen average daily signers, Q3 2026 (PIANO.md pilot: 79,300) | Nansen Q3-2026 report | Distinct transaction signers per day, averaged over the quarter (BigQuery based) | No (report figure, context only) |
| NearBlocks `active_accounts` 30-day average (PIANO.md pilot: 73,294) | NearBlocks | as above | Regenerated by the pipeline; the report value supersedes the pilot reading |

Why they differ: signer vs any-role counting; relayed meta-transactions (the relayer signs the outer transaction,
the user signs the inner delegate action); implicit accounts created in bulk by wallets and games (HOT); calendar
window (single day vs quarter average); and NEAR accounts vs Aurora EVM addresses. The block sample in
`activity_signer_mix_sample.csv` shows how much of the transaction flow comes from implicit vs named and relayed
signers. A per-signer reconciliation needs per-account histories (phase 2).

## 3. What could not be verified

- NearBlocks' exact definitions of `active_accounts`, `txn_fee` vs `gas_fee`, and `market_cap` (circulating supply
  source). We cross-check fees and prices against other sources; account counts have no keyless counterpart.
- DefiLlama's NEAR Intents volume definition: the on-chain check (phase 2a) brackets it (see
  `reports/analysis_summary.md`, Q2) but cannot say whether the remainder is confidential volume or a two-sided count.
  DefiLlama's Intents *revenue* is reproduced from public flows (Q4); its *fees* (gross protocol + affiliate fees)
  come from NEAR-uploaded Dune tables and were not rebuilt.
- Completeness of the FastNear Transactions API index before 2021 (only indirect checks: block rows exist from
  genesis; sample-implied vs NearBlocks transaction totals per month).
- Stake before epoch 545 (archival nodes no longer serve it).
- Why the `validator_reward_paid_prev_epoch` map does not sum to the minted amount of any adjacent epoch.
- Who controls the implicit accounts that received `treasury.near`'s April-May 2026 outflows: account ids carry no
  labels; trails stop at five hops or where no outflow is seen (phase 2a ledger).
- The final HSP-029 vote and its validator adoption: the snapshot (2026-10-30 22:59 UTC) shows status "Voting".
- Electric Capital's classification of repositories into ecosystems (taken as published).
- Market caps older than 365 days for peers (keyless CoinGecko limit).

## 4. Phase 2a sources and quirks (fetched 2026-10-30 and 2026-10-31 UTC)

Computed results are in `reports/analysis_summary.md` and `reports/models_summary.md`; this section only documents
what was fetched and how the sources behave.

### FastNear Transactions API, per-signer histories (`fastnear_tx/signer_*.csv`, `block_sample_extra_*.csv`)
- Draw design (`src/nearthesis/sampling.py`): 60 extra uniform block heights per month from 2025-11 (seed stream
  `[seed, yyyymm, 2]`) widen the 30-block phase-1 sample, because recent months held only ~120-180 sampled
  transactions. Transactions are then drawn without replacement from the pooled sampled transactions of each month
  (200 per month from 2024-11, 15 before; seed stream `[seed, yyyymm, 3]`); the draw is recomputed offline from the
  committed block samples, so the fetcher and the analysis agree by construction. The design started at 60 draws per
  month; a pilot on 2026-09/10 showed that the 1/c account estimators were far too coarse at that size (a single
  signer with one transaction stands for N/n accounts), so the draws were extended to 200. The draw order is a fixed
  permutation, so the first 60 draws of the extended design are exactly the original ones.
- Calls per draw: the monthly count + timestamps for every draw; first appearance and last activity only for the first
  60 draws of a month (cohorts); transaction details only for the first 40.
- The responses were fetched between about 2026-10-30 22:20 and 2026-10-31 01:57 UTC (about 7,000 requests, one at a
  time); the CSVs were then rewritten from the response cache in the delta-encoded format, so the manifest's
  `fetched_at_utc` for the `signer_*` files is the time of that rewrite and their `http` block shows 0 requests. The same
  applies to the NEAR Intents files (fetched between about 22:20 and 23:31 UTC on 2026-10-30, rewritten from cache).
- Per drawn signer: `/v0/account {is_real_signer, month range, limit 200, desc: true}` (exact monthly count +
  timestamps), `/v0/account {limit 1, desc: false}` (first appearance in any role), and for signers new in that month
  `/v0/account {is_real_signer, limit 1, desc: true}` (last signed transaction, for retention). Details of up to 20
  recent transactions per signer-month come from `/v0/transactions`.
- **`/v0/account` returns newest first when `desc` is omitted**, although the OpenAPI spec says oldest first; every
  call sends `desc` explicitly.
- Pages fetched with `resume_token` do not repeat `txs_count`; the first page's count is kept.
- **HTTP 429 came from concurrent requests**, not only from the rate: with three processes spaced 1 s apart in total,
  FastNear still answered 429 when a slow count query was in flight while another request started. The client now
  holds a cross-process lock for the whole duration of a FastNear request (`[http.shared_min_interval_s]`).
- Relayed transactions: `is_real_signer` counts the inner (delegate-action) signer, the same convention as the block
  sample's `real_signer_id`.

### NEAR Intents settlement check (`fastnear_tx/intents_*.csv`, `rpc_archival/intents_fee_collector_balances.csv`,
`oneclick/tokens.csv`, `defillama/coin_prices_intents_days.csv`)
- Contracts, from docs.near-intents.org (Verifier, Events and Fees pages, read 2026-10-30 UTC): `intents.near` is the
  Verifier; swaps emit DIP-4 `token_diff` events (`account_id`, signed `diff` per token, `fees_collected`, optional
  `referral` tag such as `1click-swapkit`); the protocol fee is `fee()` pips (1 pip = 0.0001%) of the sold leg,
  rounded up per leg, paid in-ledger (NEP-245 `mt_transfer`) to `fee_collector()` =
  `7066024d3f20f94de601c003163367873cca78507eeca4df66d9be645f197f05`. Deposits and withdrawals go through
  `omft.near` tokens, `omni.bridge.near` and `v2_1.omni.hot.tg`; most `execute_intents` transactions are signed by
  `intents.near` itself (the relay), so signer-based filters cannot isolate user swaps.
- The fee collector never signs a transaction and appears only in event logs: `/v0/account {is_event_log: true}` over a
  day's height range counts exactly the transactions that paid a protocol fee (the swaps).
- Archival view calls `fee`, `fee_collector`, `mt_tokens_for_owner` and `mt_batch_balance_of` on `intents.near`
  answer at historical heights on the FastNear archival RPC.
- Rounding: the fee is rounded up per leg, so `fee x 10^6` overstates the sold amount for small legs in tokens with few
  decimals (BTC: 1 satoshi of fee stands for 0.01 BTC of volume). The census estimate is corrected with the
  sample's ratio of sold legs to fee-implied legs.
- `https://1click.chaindefuser.com/v0/tokens` answers without the partner JWT (unlike the Explorer API) and gives each
  asset id's decimals, symbol and CoinGecko id. Historical prices come from `coins.llama.fi/prices/historical`.
- A control sample of every transaction touching `intents.near` in 10 short windows per day found no transaction
  with a `token_diff` that did not pay the protocol fee, so the fee-paying frame contains all public swaps.
- The fee collector's balances (archival `mt_batch_balance_of` at the start and end of each day) fall during the day
  for many tokens: it moves or converts what it collects, so balance changes are not a fee census (kept as a
  diagnostic only).
- Not observable: confidential intents and anything that does not pay the protocol fee. DefiLlama's volume comes
  from `dune.near.dataset_near_intents_metrics` (column `volume_amount_usd`), uploaded by the NEAR team; its
  definition is not published.

### Money trails (`fastnear_tx/wallet_flows.csv`, `fastnear_tx/trail_hops.csv`)
- Complete histories (all roles) of `treasury.near`, `buybacks.multisignature.near`, `fefundsadmin.sputnik-dao.near`
  and `1csfundsadmin.sputnik-dao.near`, expanded receipt by receipt: NEAR moved by successful action receipts
  (Transfer and attached deposits; gas refunds from `system` dropped), NEP-141 and NEP-245 events, DIP-4 token_diff
  legs.
- DefiLlama's NEAR Intents revenue adapter (`dimension-adapters/fees/near-intents/index.ts`) defines revenue as NEAR
  Transfer actions and positive `wrap.near` transfers into the three revenue wallets from accounts outside that set;
  `transform/ledgers.py` applies the same rule to the on-chain flows.
- Protocol rewards to `treasury.near` are credited at epoch boundaries without a receipt, so they never appear in the
  transaction history; they are recovered as archival balance change minus transaction flows.
- `treasury.near` is a multisig contract: outflows are `confirm` calls whose receipts carry the transfers.
- Trails follow NEAR transfers of at least 100,000 NEAR, up to five hops, oldest first from the receiving height (up to
  400 later transactions per account). NEAR is fungible: a hop shows what left an account after it received the
  transfer, not that the same coins moved.

### Developer activity (`github/*.csv`, `opendevdata/eco_mads_monthly.csv`)
- GitHub REST API without a token: 60 requests/hour per IP (headers `x-ratelimit-*`); `stats/contributors` and
  `stats/participation` answer 202 while GitHub computes them (retried after 30 s); `stats/contributors` lists the
  top 100 contributors only. Its 52-week sum and `stats/participation` differ by up to about 35% for some repositories
  (ratio published per repository); we report contributor-stats numbers.
- `near/near-sdk-js` is archived. The `nearai` repositories are the most-starred non-fork, non-archived repositories
  pushed in the last 365 days at fetch time.
- Electric Capital Open Dev Data (CC BY 4.0) publishes a manifest (`https://data.opendevdata.org/manifest.json`) of
  parquet files; `eco_mads.parquet` (76 MB) is read with HTTP range requests for eight ecosystem ids only (NEAR 2817,
  Solana 391, Sui 9547, Aptos 9601, Base 13317, Ethereum 2, Tron 10, "All Web3 Ecosystems" 7164). Its `all_devs` and
  `num_commits` columns are 28-day rolling values, so month-end rows are used (the stored monthly sum of
  `num_commits` is not meaningful and is not used).

### Governance (`governance/hsp029_status.csv`)
- HSP-029 text and status come from the Discourse JSON of `https://gov.near.org/t/42644` (frontmatter `Status:`).
  The House of Stake page `houseofstake.org/proposals/29` renders client-side and returned only its title without a
  browser, so the final vote result (reported to close 2026-11-02) is not in the snapshot.
