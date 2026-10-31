# Priors: what we expected before looking, and how the data moved it

Purpose: make the direction and size of every update visible, so a reader can tell evidence from conviction.
Each prior is written as a number or a range with a rough probability, with the information it was based on and
**when it was recorded relative to the data**. A prior recorded after the data is marked as such and should be read as
a reconstruction, not as a forecast.

Timeline (git history is the record):
1. Phase 1 (commits up to `d14ba79`, 2026-10-30): aggregate data seen (NearBlocks, DefiLlama, archival supply,
   census counts, structural organic proxy).
2. Phase 2a, first commit `460d353`: money trails, developer activity and models had been run and seen.
3. **This file, first version: committed before the per-signer histories (Q1) and the NEAR Intents on-chain
   samples (Q2) were analysed.** The fetches were still running; no organic share, cohort retention or on-chain
   Intents volume had been computed.
4. Posterior: filled in the next commits, from `reports/analysis_summary.md` and `reports/models_summary.md`. Numbers
   below are quoted as "`metric_id` = value" exactly as `make reproduce` prints them; `tests/test_thesis_docs.py`
   fails if a quote and the generated value disagree.

## Q1. Is the activity real? (recorded before the per-signer data)

| Quantity | Prior | Basis |
|---|---|---|
| Organic share of transactions, 2026-Q3 (human-like signer, not an incentivized contract, not infrastructure relay) | about 25%, 80% range 10% to 45% | Phase 1: incentivized contracts 42% and infrastructure 19% of 2026-Q3 transactions (census); structural proxy (named, direct, untracked receiver) about 21% of transactions |
| Organic monthly active signers, 2026-Q3 vs 2024-Q3 | lower; P(decline) = 0.75; central guess -40% | NearBlocks active accounts -73% year on year; HOT and KaiChing wind-down removes mostly non-organic accounts, so organic should fall less than the headline |
| Month-3 rolling retention of new signers | 10% to 25%; P(improving over the last 4 cohorts) = 0.35 | Airdrop / tap-to-earn onboarding dominated 2024-2025 cohorts |
| Our daily active signers / NearBlocks active accounts | 0.5 to 0.9 | NearBlocks' definition likely counts receivers too |

## Q2. NEAR Intents on-chain check (recorded before the on-chain samples were analysed)

| Quantity | Prior | Basis |
|---|---|---|
| On-chain one-sided swap volume / DefiLlama volume, median of sampled days | P(0.8 to 1.2) = 0.45, P(< 0.8) = 0.45, P(> 1.2) = 0.10 | DefiLlama reads a NEAR-uploaded Dune table with an unpublished definition; confidential intents are invisible on-chain; a two-sided definition would push the ratio below 0.6 |
| Largest asset's share of gross sold volume | 25% to 45% | Stablecoins (USDC / USDT variants) and BTC dominate cross-chain swaps |

## Q4, Q6 and models (recorded after the phase 2a results for these were seen: reconstructions)

| Question | Reconstructed prior (from phase 1 and PIANO.md, before phase 2a) | Basis |
|---|---|---|
| Q4. DefiLlama Intents revenue vs on-chain flows into the revenue wallets | within 20% (P = 0.7) | the adapter is a short SQL query over public NEAR tables |
| Q4. Where `treasury.near`'s May 2026 outflow went | most likely foundation-controlled accounts or staking; P(trail ends in "unknown") = 0.6 | balance fell by about 18.75M NEAR in one month (phase 1) |
| Q6. NEAR monthly active developers, last 12 months | falling with the sector; NEAR's share of web3 developers flat to down | market downturn in 2026; no NEAR-specific evidence |
| (a) Burn + buybacks vs issuance at current Intents revenue | offsets below 25% of issuance (P = 0.8) | phase 1: Intents revenue about 17% of issuance value, burn about 1% |
| (b) NEAR multiple vs peers | far above peers on chain fees alone; near the peer median once Intents fees are counted | phase 1: fees / market cap 0.04% vs 0.47% with Intents |
| (c) Organic adoption model | log-linear decline fits better out of sample than an S-curve | phase 1 structural proxy -73% over 24 months |
| (d) Real yield | stakers about +2.5% per year in share of float, non-stakers about -2% | 2.5% issuance, 45% staking, small burn and buybacks |

## Posterior: how the data moved each prior

### Q1. Activity (large update, bearish)

- Organic share of transactions, 2026-Q3: prior about 25%; data `q1b.organic_tx_share` = 2.17% (90% CI 0.86% to
  3.70%), and between `q1b.organic_share_strict` = 1.17% and `q1b.organic_share_lenient` = 5.17% across bot thresholds.
  Far below even the low end of the prior range. The phase-1 structural proxy (`q1.organic_proxy_txns_per_day_last_month`
  = 297,665 transactions a day) counted named, direct signers to untracked contracts; signer by signer, most of those
  turn out to be automated accounts or reward programs we had not listed (PlayEmber, Harvest Moon, HOT claims, SWEAT
  and KaiChing namespaces). Organic transactions per day: `q1b.organic_txs_per_day` = 16,630.
- Organic daily active signers: `q1b.organic_das` = 6,437 in 2026-Q3 against `q1b.organic_das_first_full_quarter` =
  23,402 in 2025-Q1 (`q1b.organic_das_change` = -72.49%), with overlapping 90% intervals: the direction matches the
  prior (P(decline) = 0.75), the size is not resolved by the sample. The fitted trend is `mc.organic_das_trend` =
  -37.83% per year; out of sample it beats a random walk only marginally and on very few forecasts (model (c) in
  `reports/models_summary.md`), so it is a description, not a forecast.
- Our daily active real signers / NearBlocks active accounts: prior 0.5 to 0.9; data `q1b.das_to_nearblocks` = 519.23%.
  Wrong sign of the gap: NearBlocks appears to count the relayer of a meta-transaction, not the inner signer, so its
  "active accounts" undercounts accounts and says nothing about their quality.
- Month-3 retention of new signers: not testable with this design (one cohort with at least 20 new-signer draws,
  `q1b.retention_3m_largest_cohort` = 57.73% for 2025-Q1). The prior stays where it was.

### Q2. NEAR Intents (moderate update: activity real, aggregate volume not reproducible one to one)

- Prior P(on-chain / DefiLlama in 0.8 to 1.2) = 0.45, P(< 0.8) = 0.45. Data: the public one-sided volume is
  `q2b.ratio_sample_median` = 46.04% of DefiLlama's figure at the median; counting both legs gives
  `q2b.ratio_two_sided_median` = 92.08%. The "< 0.8" branch happened, and the factor of about two points to a
  definition that counts both sides (or to unobservable confidential volume); no swap escaped the fee-paying frame
  (`q2b.frame_check` = 0). Posterior: the swaps are real and settle on NEAR; the DefiLlama volume series should be read
  as an upper bound, roughly two-sided.
- Largest asset: prior 25% to 45%; data `q2b.top_asset_share` = 47.93% (USDT), slightly above the range and above
  PIANO.md's 40% fragility line.

### Q4, Q6 and models (reconstructed priors: small updates)

- Revenue: prior "within 20%"; data `q4b.revenue_onchain_to_defillama` = 98.68%, tighter than expected. Captured
  revenue is the most trustworthy Intents number.
- Treasury: prior "foundation-controlled accounts or staking, P(unknown) = 0.6"; data `q4b.treasury_outflows_since_apr` =
  30.17M NEAR left `treasury.near`; `q4b.trail_into_staking` = 20.95M NEAR moved into staking pools downstream within
  five hops, the April tranche passes through `nfendowment03.near`, and the rest ends at unlabelled implicit accounts.
  Both branches of the prior happened.
- Developers: prior "falling with the sector"; data `q6.near_mad_yoy` = -36.24%, share of web3 `q6.near_share` = 1.87%
  vs `q6.near_share_year_before` = 2.19%, but relative to the peer chains NEAR's count held up (they fell as much or
  more). Update: none on direction, slightly less bearish on relative position.
- (a) Value accrual: prior "offsets below 25% of issuance"; at current Intents revenue the net-zero point needs
  `ma.net_zero_multiple.0.0249` = 8.072 times today's captured revenue (`ma.net_zero_multiple.0.0159` = 5.118 under the
  HSP-029 target). Consistent with the prior.
- (b) Multiples: prior "near the peer median once Intents fees are counted"; data `mb.fees_plus_intents_fees` = 80.046
  (cheaper than every peer on that basis) vs `mb.chain_fees` = 2,516 on chain fees alone. More favourable than the
  prior, but it rests on Intents fees that NEAR mostly does not capture (`mb.revenue_plus_intents_revenue` = 220).
- (d) Real yield: prior "stakers about +2.5%, non-stakers about -2%"; data `md.real_staker_yield` = 2.51% and
  `md.non_staker` = -2.06%. As expected.

### Net effect

The thesis gets weaker on usage quality (Q1) and on the reliability of the headline Intents volume (Q2), and slightly
stronger on the verifiability of Intents revenue and of treasury reporting (Q4). The dated predictions that will test
the remaining claims are in `thesis/falsifiers.md`.
