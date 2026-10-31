- **Organic use is about 2% of NEAR's transactions.** Human-like signers sent {{q1b.organic_tx_share}} of transactions in
  2026-Q3 (90% interval {{q1b.organic_tx_share:ci}}); organic daily active signers were {{q1b.organic_das}}
  ({{q1b.organic_das:ci}}) against {{q1b.organic_das_first_full_quarter}} in 2025-Q1, a trend of {{mc.organic_das_trend}} a
  year that barely beats a random walk out of sample. NearBlocks' "active accounts" undercount real signers
  {{q1b.das_to_nearblocks:x}}, because relayed transactions hide the user behind the relayer.
- **NEAR Intents is real, its revenue checks out, its volume looks two-sided.** Public on-chain swaps counted once add up
  to {{q2b.ratio_sample_median}} of DefiLlama's volume on {{ic.days}} sampled days ({{q2b.ratio_two_sided_median}} counting
  both legs); captured revenue rebuilt from the revenue wallets is {{q4b.revenue_onchain_to_defillama}} of DefiLlama's.
- **Holders are still diluted.** {{q4b.near_captured_since_buybacks}} has been bought back and held since 2026-02-23, yet
  the float grows {{sc.status_quo/base.1y.float_cagr}} a year at the 2.5% cap; offsetting that needs
  {{ma.net_zero_multiple.0.0249:x}} today's Intents revenue ({{ma.net_zero_multiple.0.0159:x}} under HSP-029, in vote at the
  snapshot). Stakers gain {{md.real_staker_yield}} a year in share of the float; non-stakers lose {{md.non_staker:abs}}.
- **The valuation depends on whether Intents counts.** NEAR's market cap is {{mb.chain_fees:x}} its annualized chain fees
  (peer median {{mv.chain_fees.30d_annualized.peer_median}}) but {{mb.fees_plus_intents_fees:x}} counting Intents fees.
  Developers fell {{q6.near_mad_yoy:abs}} in a year to {{q6.near_mad}} monthly actives, less than the peer chains did.
- **The treasury moved {{q4b.treasury_outflows_since_apr}} in April-May 2026**; {{q4b.trail_into_staking}} of it reached
  the p2p-org and figment staking pools within five hops, the rest ends at unlabelled accounts. Verdict: a conditional
  case, not a bullish one. {{fs.met:int}} of {{fs.rows:int}} pre-registered falsifiers are met, and
  {{pred.count:int}} dated predictions are frozen (sha256 `{{pred.sha256}}`, git tag `predictions-2026-10-31`).
