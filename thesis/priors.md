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
4. Posterior columns: filled in a later commit, from `reports/analysis_summary.md` and `reports/models_summary.md`.

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

## Posterior

To be filled from the generated reports once the Q1 and Q2 data are analysed (next commit).
