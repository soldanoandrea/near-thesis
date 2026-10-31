# NEAR on the evidence: verified Intents revenue, thin organic use, and an {{ma.net_zero_multiple.0.0249:x}} gap to cover dilution

*A data-backed long-term thesis on NEAR for the NEAR HACKATHON 2026, track `thesis`. Snapshot as-of {{in.as_of}} (UTC).
Every number in this essay is filled in by `make site` from the tables in `data/processed/`;
[NUMBERS.md](NUMBERS.md) names the table and row behind each one. Charts: [the dashboard](../site/dashboard.html).
Written by an AI agent team with no NEAR position. Not financial advice.*

## Verdict

On the evidence at {{in.as_of}}, NEAR is two businesses of very different quality. The chain's own activity is mostly
not people: organic, human-like signers sent {{q1b.organic_tx_share}} of all transactions in 2026-Q3 (90% interval
{{q1b.organic_tx_share:ci}}), and organic daily active signers averaged {{q1b.organic_das}} ({{q1b.organic_das:ci}}),
against a point estimate of {{q1b.organic_das_first_full_quarter}} in 2025-Q1; the fitted trend, {{mc.organic_das_trend}} a
year, forecasts only slightly better than a random walk. NEAR Intents, the cross-chain swap layer that settles on NEAR,
is real, and its captured revenue checks out: rebuilt from public wallet flows it is {{q4b.revenue_onchain_to_defillama}}
of what DefiLlama reports. Its reported volume does not check out one to one: public on-chain swaps, each counted
once, add up to {{q2b.ratio_sample_median}} of DefiLlama's figure, so the headline volume looks two-sided. Value accrual
does not yet cover issuance: after burn and buybacks the float grows {{sc.status_quo/base.1y.float_cagr}} a year at the
current 2.5% cap, and offsetting that would take {{ma.net_zero_multiple.0.0249:x}} today's Intents revenue
({{ma.net_zero_multiple.0.0159:x}} if HSP-029 cuts issuance to 1.6%). Our long-term case is therefore conditional, not
bullish: it needs Intents revenue to grow several-fold while organic use stops shrinking. Under our stated priors the
probability that burn plus buybacks cover issuance within {{vp.horizon}} years is {{vp.p_offsets_cover}}. The
{{pred.count:int}} dated predictions at the end, hashed and tagged before their outcomes exist, say when we will find out.

## How to read this

- The questions are the seven of [PIANO.md](../PIANO.md), written before the data were fetched: Q1 is the activity
  real, Q2 is NEAR Intents volume real, Q3 does the AI-agent story show up on-chain, Q4 supply and value accrual, Q5
  fees and take rate, Q6 developers, Q7 comparables.
- Evidence grades: **A** means re-runnable from chain data (archival RPC, the FastNear indexer); **B** means an
  aggregator snapshot (DefiLlama, NearBlocks, CoinGecko, Electric Capital). Where we sampled, intervals are 90%
  bootstrap intervals over sampled blocks.
- A falsifier that is **met** counts against the bullish case. The full scorecard is on the
  [dashboard](../site/dashboard.html#scorecard).
- Priors were written down before the per-signer and Intents data were analysed ([priors.md](priors.md); the git
  history shows the order). We quote them where the data moved them.

## Method

**Data.** Only keyless public APIs: NearBlocks, DefiLlama, CoinGecko, NEAR RPC and archival RPC, the FastNear
transactions indexer, Blockscout for Aurora, GitHub, Electric Capital Open Dev Data and the NEAR governance forum.
{{snap.files}} raw files ({{snap.rows}} rows) were fetched between {{snap.first_fetch}} and {{snap.last_fetch}} and
committed with their URL, parameters, fetch time and sha256 in `data/raw/MANIFEST.json`. `make reproduce` rebuilds every
processed table, report, this essay and the dashboard offline, and the tests check that the committed outputs are
byte-identical to what the code produces.

**Sampling.** For activity we draw 30 uniform random blocks per month since 2020 (90 since 2025-11) and keep every
transaction in them. From those we draw 200 transactions per month since 2024-11 (15 before), seeded, and for each
draw we read the real signer's full month from the FastNear indexer: its exact transaction count, up to 200
timestamps, and for subsets its first appearance and its latest receivers and methods. For relayed meta-transactions
the real signer is the inner signer, not the relayer. Distinct active signers are estimated with 1/c weights (a signer
with c transactions is c times as likely to be drawn). The method was validated against exact counts: the census share
of the largest app, HOT, falls inside the sample's 90% interval in {{q1.sample_validation_hot}} of months.

**Bot classification.** A rule-based score on five features (volume, round-the-clock activity, sub-30-second median
gaps, metronome-like regularity, one repeated action) labels a signer *automated* at a score of 2 or more. Signers
mostly calling reward programs (HOT, KaiChing, SWEAT, NEARCrowd, inscriptions and their namespaces) are *incentivized*;
automated signers calling settlement, bridge, MPC or EVM-relay contracts are *infrastructure*; fresh implicit accounts
calling themselves are *account setup*; the rest is *organic*. The score is not trained on labelled data. Moving the
threshold from strict to lenient moves the 2026-Q3 organic share from {{q1b.organic_share_strict}} to
{{q1b.organic_share_lenient}}.

**Reconciliation.** Four independent checks against reported numbers:

- *NEAR Intents volume*: on {{ic.days}} sampled days we counted every fee-paying settlement transaction (the fee
  collector appears in the event logs of exactly those transactions), rebuilt a cluster sample of {{ic.sampled_txs}} of them from DIP-4
  `token_diff` events, netted each account's legs, counted each swap once and priced it with DefiLlama's historical
  prices. A control sample of every `intents.near` transaction in short windows of each day found {{q2b.frame_check}}
  swaps that escaped the fee-paying frame.
- *Captured revenue*: DefiLlama's own rule (NEAR and wNEAR received by the three revenue wallets from outside the set)
  applied to the complete on-chain histories of those wallets.
- *Treasury*: archival month-start balances of `treasury.near` minus its transaction flows recover the protocol
  rewards it receives without a receipt; transfers of 100,000 NEAR or more are followed for up to five hops.
- *Supply*: the per-block identity supply(b) = supply(b-1) - burnt(b) holds exactly, in yoctoNEAR, in
  {{q4.block_identity_pass_rate}} of sampled block pairs; issuance is measured from supply changes at epoch boundaries.

**Models.** Four pure functions with unit tests: a monthly supply recursion under the 2.5% cap and under HSP-029; fee
and revenue multiples against Solana, Sui, Aptos, Ethereum and Tron; adoption models (log-linear, logistic, random
walk) scored by rolling-origin backtests; and staking real yields. Their inputs, assumptions and ranges are printed in
[models_summary.md](../reports/models_summary.md).

**What could not be measured.** Confidential intents, and any swap that does not pay the protocol fee, are invisible
on-chain by design. DefiLlama's Intents volume comes from a NEAR-uploaded Dune table whose definition is not published.
No account carries an entity label, so implicit accounts in the treasury trail are unattributed. Only
{{coh.informative_cohorts}} new-signer cohort has enough draws to measure retention. The lead-lag test of the starter
hypothesis (does Intents volume lead usage better than price?) was not run. Agent activity is measured only through the
Chain Signatures proxy. The HSP-029 vote had not closed at the snapshot. BigQuery, Dune and the Intents Explorer were
not used because they need accounts or keys.

## The evidence, question by question

### Q1. Is the activity real?

Headline activity has collapsed and most of what remains is not people. NearBlocks counts {{q1.txns_30d_avg}}
transactions a day over the last 30 days, down {{q1.txns_30d_avg_yoy:abs}} on a year earlier. In 2026-Q3 the
transactions split by signer class as follows (90% intervals in the
[chart](../site/dashboard.html#card-classes)):

| Class | Share of transactions, 2026-Q3 | 90% interval |
|---|---:|---:|
| Organic (human-like) | {{oq.2026q3.share_organic}} | {{oq.2026q3.share_organic:ci}} |
| Automated (bots) | {{oq.2026q3.share_automated}} | {{oq.2026q3.share_automated:ci}} |
| Incentivized programs | {{oq.2026q3.share_incentivized}} | {{oq.2026q3.share_incentivized:ci}} |
| Infrastructure relays | {{oq.2026q3.share_infrastructure}} | {{oq.2026q3.share_infrastructure:ci}} |
| Account setup | {{oq.2026q3.share_account_setup}} | {{oq.2026q3.share_account_setup:ci}} |

Our prior, recorded before the signer data were analysed, was an organic share of about 25%. The data put it an order
of magnitude lower: {{q1b.organic_txs_per_day}} organic transactions a day out of {{act.2026q3.nb_txns_per_day}}. Most
of the "untracked" traffic that looked organic in aggregate turned out, signer by signer, to be automated accounts or
reward programs we had not listed.

Counting accounts gives a second surprise. All real signers averaged {{q1b.all_das}} a day in 2026-Q3
({{q1b.all_das:ci}}), which is {{q1b.das_to_nearblocks:x}} what NearBlocks reports as active accounts (median of the last
12 months). The gap has the opposite sign to our prior: relayed meta-transactions are signed on the outside by a relayer,
and NearBlocks appears to count the relayer, not the user. Its "active accounts" undercount accounts and say nothing
about their quality.

Organic daily active signers were {{q1b.organic_das}} in 2026-Q3 against {{q1b.organic_das_first_full_quarter}} in
2025-Q1, the first quarter with the full sample design. The point estimates fell {{q1b.organic_das_change:abs}}, but the
2025-Q1 interval ({{q1b.organic_das_first_full_quarter:ci}}) reaches zero, so the sample does not resolve the size of the
decline. The log-linear trend over 2025-01 to 2026-09 is {{mc.organic_das_trend}} a year. Out of sample it barely beats
a random walk: mean absolute log error {{bt.das.loglinear.6m}} against {{bt.das.naive.6m}} at six months
({{bt.das.loglinear.6m.n}} forecasts) and {{bt.das.loglinear.3m}} against {{bt.das.naive.3m}} at three months
({{bt.das.loglinear.3m.n}} forecasts). We read it as a description, not a forecast; extrapolated, it puts organic daily
active signers at {{fc.das.12m}} in a year ({{fc.das.12m:ci}}). Retention cannot carry the case either way: the one
informative cohort (2025-Q1) kept {{q1b.retention_3m_largest_cohort}} of its new signers active three months later
({{q1b.retention_3m_largest_cohort:ci}}).

### Q2. Is NEAR Intents volume what it is reported to be?

DefiLlama reports {{q2.intents_volume_usd_365d}} of NEAR Intents volume over the last 365 days, {{iq.2026q3.volume}} in
2026-Q3 alone, up {{iq.2026q3.volume_qoq}} on the previous quarter after a change of {{iq.2026q2.volume_qoq}} in 2026-Q2. Our on-chain
rebuild on {{ic.days}} sampled days finds public swaps, each counted once, worth {{q2b.ratio_sample_median}} of
DefiLlama's daily figure at the median (from {{ic.ratio_min}} to {{ic.ratio_max}} by day). Counting both legs of every
swap gives {{q2b.ratio_two_sided_median}}, and 100% sits inside the 90% interval on {{ic.days_two_sided_ci_has_100}} of
the {{ic.days}} days. Since no swap escaped our frame, two readings remain: DefiLlama's volume counts roughly both sides
of each swap, or about half of the volume settles where public events cannot see it (confidential intents). Either way
the swaps are real and settle on NEAR, and the reported series is best read as an upper bound. Our prior gave 0.45 to
a ratio below 0.8; that branch happened.

Volume is concentrated: the largest asset, USDT, is {{q2b.top_asset_share}} of sold volume at the median of sampled
days, above the 40% fragility line we set in PIANO.md.

### Q3. Does the AI-agent story show up on-chain?

Only through a proxy. Transactions that reach Chain Signatures (`v1.signer`), the MPC signing service that lets NEAR
accounts and agents sign on other chains, were {{act.2026q3.chain_signatures_share}} of all transactions in 2026-Q3 and
{{q.chain_signatures_txs_last_month}} in 2026-09. That clears the falsifier's 1% line, but we did not attribute any
of it to AI agents. The agent narrative is not measured here, so it carries no weight in this thesis.

### Q4. Supply, value accrual and the treasury

**Issuance.** The cut of the inflation cap from 5% to 2.5% in late October 2025 is visible in the data: realized
supply growth fell from {{q4.supply_growth_prev_365d}} to {{q4.supply_growth_365d}} over consecutive 365-day windows, and
sampled epochs show issuance of {{q4.mint_rate_365d}} a year. Fee burn offsets only {{q4.burn_to_mint_365d}} of what is
minted. {{q4.staking_ratio_last_sample}} of the supply is staked.

**Revenue and buybacks.** Captured Intents revenue rebuilt on-chain is {{q4b.revenue_onchain_to_defillama}} of
DefiLlama's figure over the last six months, and between {{rev.ratio_min}} and {{rev.ratio_max}} in each of the
{{rev.months}} months with revenue ([chart](../site/dashboard.html#card-revenue)). It is the most trustworthy Intents
number we have. Since buybacks started on 2026-02-23 the revenue wallets captured {{q4b.near_captured_since_buybacks}};
the buyback wallet sent only {{bb.sent_out}} onward. The NEAR is bought back and held, not burned, so it shrinks the
float, not the supply. At the last six months' pace that is {{in.buyback_near_per_year_onchain}} a year, or
{{in.buyback_yield_onchain}} of supply.

**Dilution.** Net of burn and buybacks the float grows {{sc.status_quo/base.1y.float_cagr}} a year at the 2.5% cap. A
staker's share of the float grows {{md.real_staker_yield}} a year (5% commission) while a non-staker's shrinks
{{md.non_staker:abs}}. For burn plus buybacks to offset issuance at today's price and take rate, captured revenue would have
to reach {{nz.sq.required_revenue}} a year, against {{in.intents_revenue_annualized_90d}} today: {{ma.net_zero_multiple.0.0249:x}}.
HSP-029, which phases the cap down to 1.6% over 24 months, lowers the bar to {{nz.hsp.required_revenue}}
({{ma.net_zero_multiple.0.0159:x}}); it was in status "{{in.hsp029_status}}" at our snapshot ({{in.hsp029_snapshot_utc}}),
with the vote reported to close on 2026-11-02 ([chart](../site/dashboard.html#card-supply)).

**The treasury.** `treasury.near` receives its share of protocol rewards as the protocol says it should:
{{q4b.treasury_rewards_check}} of the expected amount (median of the last six months). Its outflows are another matter.
It sent out {{q4b.treasury_outflows_since_apr}} in April and May 2026, almost emptying it
([Sankey](../site/dashboard.html#card-treasury)):

- In April, {{tr.apr_tranche}} went to two ecosystem multisigs, then through one implicit account to `opgran01.near`
  and on to `nfendowment03.near`. Amounts grow along the way (`nfendowment03.near` received {{tr.nfendowment03_received}}
  from `opgran01.near`) because these accounts hold other funds; `nfendowment03.near` then sent
  {{tr.nfendowment03_sent}} to {{tr.nfendowment03_recipients:int}} accounts, most of them unlabelled.
- In May, {{tr.may_tranche}} went to one implicit account and on through three or four more implicit accounts to the
  staking pools of p2p-org ({{tr.pool_p2p}}) and figment ({{tr.pool_figment}}): {{q4b.trail_into_staking}} into staking
  in total.

Within five hops no transfer of 100,000 NEAR or more reached an exchange-like account or NEAR Intents
({{tr.exchange_like_stops}} such stops). The rest ends at unlabelled implicit accounts, the largest of which received
{{tr.largest_unfollowed}} beyond the fifth hop. NEAR is fungible, so these are amounts that moved after each receipt,
not the same coins; the names are account ids, not verified entities.

### Q5. Fees and the take rate

The chain itself earns almost nothing: {{q5.chain_fees_usd_30d}} of fees in the last 30 days and {{q5.tx_fees_usd_365d}}
over a year, {{q5.fees_to_mcap}} of market cap annualized. NEAR Intents is where the fees are: {{in.intents_fees_annualized_90d}}
a year annualized from the last 90 days, of which NEAR captures {{in.intents_revenue_annualized_90d}}
({{in.capture_share}}); the rest never reaches NEAR's revenue wallets (DefiLlama's gross fees include the
affiliate fees paid to integrators and front-ends). The captured take rate rose from
{{iq.2026q2.revenue_take_rate}} of volume in 2026-Q2 to {{iq.2026q3.revenue_take_rate}} in 2026-Q3, when revenue grew
{{iq.2026q3.revenue_qoq}} against volume growth of {{iq.2026q3.volume_qoq}}. The falsifier "fees competed away" is not met.

### Q6. Developers

Electric Capital counts {{q6.near_mad}} monthly active NEAR developers in 2026-09, down {{q6.near_mad_yoy:abs}} on a year
earlier, and NEAR's share of all web3 developers fell from {{q6.near_share_year_before}} to {{q6.near_share}}. But the
peer chains lost developers faster: NEAR's count relative to Solana, Sui, Aptos, Base, Ethereum and Tron combined rose
from {{dev.2025q3.to_peers}} to {{dev.2026q3.to_peers}} between 2025-Q3 and 2026-Q3. Core development continues: `nearcore`
commits changed {{q6.nearcore_commits_change}} year on year, from {{q6.nearcore_authors_last12}} authors.

### Q7. Comparables

| Basis (30 days annualized) | NEAR multiple | Peer median | Market cap at the peer median |
|---|---:|---:|---:|
| Chain fees only | {{mb.chain_fees:x}} | {{mv.chain_fees.30d_annualized.peer_median}} | {{mv.chain_fees.30d_annualized.mcap_at_median}} |
| Chain fees + Intents fees | {{mb.fees_plus_intents_fees:x}} | {{mv.fees_plus_intents_fees.30d_annualized.peer_median}} | {{mv.fees_plus_intents_fees.30d_annualized.mcap_at_median}} |
| Chain revenue only | {{mv.chain_revenue.30d_annualized.near}} | {{mv.chain_revenue.30d_annualized.peer_median}} | {{mv.chain_revenue.30d_annualized.mcap_at_median}} |
| Chain revenue + Intents captured revenue | {{mb.revenue_plus_intents_revenue:x}} | {{mv.revenue_plus_intents_revenue.30d_annualized.peer_median}} | {{mv.revenue_plus_intents_revenue.30d_annualized.mcap_at_median}} |

NEAR's market cap was {{in.market_cap}}. On the chain's own fees NEAR is the most expensive chain in the set; counting
Intents it is among the cheapest. On trailing 365-day flows the Intents-inclusive multiples are
{{mv.fees_plus_intents_fees.365d.near}} on fees and {{mv.revenue_plus_intents_revenue.365d.near}} on revenue, because
Intents is young. Which basis is right is the valuation question, and the data cannot settle it alone.

## The bull case

Each claim names the prediction that will test it ([falsifiers.md](falsifiers.md), frozen in
[predictions.csv](predictions.csv)).

1. **NEAR Intents is a real, growing and verifiable revenue line.** Captured revenue reconciles with on-chain flows
   ({{q4b.revenue_onchain_to_defillama}}), it doubled in 2026-Q3 (up {{iq.2026q3.revenue_qoq}} on the quarter), and the take rate rose.
   Tested by P2 (90-day volume to {{pred.P2.date}} at least {{pred.P2.threshold}}), P4 (captured revenue rebuilt on-chain
   for 2026-11 to 2027-04 at least {{pred.P4.threshold}}, checked {{pred.P4.date}}) and P5 (take rate at least
   {{pred.P5.threshold}} on {{pred.P5.date}}).
2. **Counting Intents, NEAR is cheap against its peers.** {{mb.fees_plus_intents_fees:x}} fees against a peer median of
   {{mv.chain_fees.30d_annualized.peer_median}}, and {{mb.revenue_plus_intents_revenue:x}} captured revenue against
   {{mv.chain_revenue.30d_annualized.peer_median}}. Tested by P7: the multiple stays at or below the peer median
   (today {{pred.P7.threshold}}) on {{pred.P7.date}}.
3. **Supply discipline is real and may tighten.** Issuance halved in the data, buybacks take about
   {{in.buyback_yield_onchain}} of supply a year off the market into a held balance, and HSP-029 would lower the offset bar to
   {{ma.net_zero_multiple.0.0159:x}}. First check: the HSP-029 vote, reported to close on 2026-11-02; then the
   structural Q4 falsifier (float dilution above 2% a year), re-measured by every `make refresh`.
4. **NEAR's developer base is holding up relative to its peers** ({{dev.2025q3.to_peers}} to {{dev.2026q3.to_peers}}).
   Tested by P6: at least {{pred.P6.threshold}} of the peer-chain developer count in 2027-Q3, checked {{pred.P6.date}}.
5. **The chain-abstraction rail is used.** Chain Signatures carries {{act.2026q3.chain_signatures_share}} of
   transactions. Tested by P3: at least {{pred.P3.threshold}} transactions in September 2027, checked {{pred.P3.date}}.
6. **The money is traceable.** Treasury rewards reconcile to {{q4b.treasury_rewards_check}}, revenue to
   {{q4b.revenue_onchain_to_defillama}}, and {{q4b.trail_into_staking}} of the 2026 treasury outflows went into staking.

## The bear case

The same weight, the same tests: each claim names the prediction whose failure would confirm it.

1. **Organic usage is small and its point estimates are falling.** {{q1b.organic_tx_share}} of transactions,
   {{q1b.organic_das}} organic daily active signers, trend {{mc.organic_das_trend}} a year. Confirmed if P1 fails:
   organic daily active signers in 2027-Q3 below {{pred.P1.threshold}} (the lower end of today's interval), checked
   {{pred.P1.date}}. P1 is lenient by design; a pass near the threshold would still be a decline.
2. **The headline metrics overstate the economy.** Incentivized programs and bots sent
   {{oq.2026q3.share_incentivized}} and {{oq.2026q3.share_automated}} of 2026-Q3 transactions; NearBlocks' active accounts
   miss real signers by {{q1b.das_to_nearblocks:x}}; DefiLlama's Intents volume is about twice the public one-sided
   volume. No prediction tests a definition; the [Q2 falsifier](../site/dashboard.html#scorecard) on reconstruction is
   already met.
3. **Intents is concentrated.** One asset, USDT, makes up {{q2b.top_asset_share}} of sold volume. A stablecoin-route
   shock would hit P2 and P4 together.
4. **Holders are diluted and will stay so without large revenue growth.** Float dilution {{sc.status_quo/base.1y.float_cagr}}
   a year, non-staker real yield {{md.non_staker}}, offset needs {{ma.net_zero_multiple.0.0249:x}} today's revenue.
   Confirmed if P4 fails (captured revenue below {{pred.P4.threshold}} for 2026-11 to 2027-04).
5. **On its own fees the chain is priced on narrative.** {{mb.chain_fees:x}} annualized chain fees against a peer median
   of {{mv.chain_fees.30d_annualized.peer_median}}, and NEAR captures only {{in.capture_share}} of Intents fees. Confirmed
   if P7 fails at {{pred.P7.date}}.
6. **Developers are leaving in absolute terms**: down {{q6.near_mad_yoy:abs}} in a year. Confirmed if P6 fails at {{pred.P6.date}}.
7. **The treasury is opaque.** {{q4b.treasury_outflows_since_apr}} left `treasury.near` in two months, much of it to
   accounts with no public label. No prediction covers it; a governance disclosure of the recipients would settle it.

## Valuation: ranges and priors, not a price target

We do not give a price target. Three lenses, each with its range.

**Relative value.** At the peer median multiple, NEAR's market cap would be {{mv.chain_fees.30d_annualized.mcap_at_median}}
on chain fees alone and {{mv.revenue_plus_intents_revenue.30d_annualized.mcap_at_median}} on captured revenue including
Intents, against {{in.market_cap}} at the snapshot. A range that wide says the multiple lens is indeterminate until one
decides how much of Intents belongs to NEAR holders. The data verify that the captured part exists; they do not show
that the market should capitalize it at a peer multiple.

**What you have to believe.** For holders to stop being diluted at today's price, captured Intents revenue has to reach
{{nz.sq.required_revenue}} a year ({{ma.net_zero_multiple.0.0249:x}} today) at the 2.5% cap, or {{nz.hsp.required_revenue}}
({{ma.net_zero_multiple.0.0159:x}}) under HSP-029. A higher NEAR price raises the bar in dollars, because buybacks buy
fewer tokens.

**Scenarios with explicit priors.** Model (a) projects float growth over five years for three policies and three paths of
Intents revenue in NEAR terms, from {{sc.status_quo/low.5y.float_cagr}} a year (2.5% cap, revenue changing
{{par.revenue_change.low:sp0}} a year) to {{sc.hsp029_act3m/high.5y.float_cagr}} a year (HSP-029 active after three months,
revenue changing {{par.revenue_change.high:sp0}} a year). Our weights, recorded in
[valuation_priors.toml](valuation_priors.toml) and quoted here as opinions:

| Branch | Prior weight | Why |
|---|---:|---|
| Policy: status quo (2.5% cap) | {{vp.policy.status_quo}} | HSP-029 was still in voting; no data on the outcome |
| Policy: HSP-029 active after 3 months | {{vp.policy.hsp029_act3m}} | one quarter after ratification, as the proposal states |
| Policy: HSP-029 active after 9 months | {{vp.policy.hsp029_act9m}} | slower validator adoption |
| Revenue path: {{par.revenue_change.low:sp0}} a year | {{vp.revenue.low}} | the random walk beats every trend in the backtest, so the direction is unknown |
| Revenue path: flat ({{par.revenue_change.base:sp0}}) | {{vp.revenue.base}} | as above |
| Revenue path: {{par.revenue_change.high:sp0}} a year | {{vp.revenue.high}} | as above |

Weighted, the float grows {{vp.float_cagr_expected}} a year over {{vp.horizon}} years (the branches range from
{{vp.float_cagr_expected:ci}}), and the probability that burn plus buybacks cover issuance in year {{vp.horizon}} is
{{vp.p_offsets_cover}}: only the high-revenue path gets there, under every policy. These weights are the least
evidence-based numbers in this document; change them in the file and `make site` recomputes the result.

## What would change our mind

The bullish case needs the seven claims below to hold on their dates. The thresholds were computed by the pipeline from
the snapshot, not chosen by hand, and frozen in [predictions.csv](predictions.csv) with sha256
`{{pred.sha256}}`, recorded in the annotated git tag `predictions-2026-10-31`. A prediction that fails will be reported,
not removed. Re-check any of them with `make refresh && make reproduce` after its date.

| ID | Claim | Holds if | Check on |
|---|---|---|---|
| P1 | Organic usage stops shrinking | organic daily active signers in 2027-Q3 >= {{pred.P1.threshold}} | {{pred.P1.date}} |
| P2 | Intents volume keeps growing | 90-day volume to 2027-04-30 >= {{pred.P2.threshold}} | {{pred.P2.date}} |
| P3 | Chain Signatures usage grows | v1.signer transactions in 2027-09 >= {{pred.P3.threshold}} | {{pred.P3.date}} |
| P4 | More revenue reaches the buyback wallets | captured revenue 2026-11 to 2027-04 >= {{pred.P4.threshold}} | {{pred.P4.date}} |
| P5 | Fees are not competed away | captured take rate, 90 days to 2027-04-30 >= {{pred.P5.threshold}} | {{pred.P5.date}} |
| P6 | Developer base holds relative to peers | NEAR / peer-chain developers in 2027-Q3 >= {{pred.P6.threshold}} | {{pred.P6.date}} |
| P7 | Counting Intents, NEAR stays cheaper than the median peer | market cap / (chain + Intents fees) <= peer median (today {{pred.P7.threshold}}) | {{pred.P7.date}} |

Decision rule, stated now: if P1, P2 and P4 all hold, we upgrade the case from conditional to supported on usage and
value capture; if P1 and P4 both fail, the long-term case as stated here is falsified. Before those dates, three things
would move us: the HSP-029 result (a pass lowers the offset bar from {{ma.net_zero_multiple.0.0249:x}} to
{{ma.net_zero_multiple.0.0159:x}}); a published definition of DefiLlama's Intents volume (it would tell us whether the
missing half is double counting or confidential flow); and a public account of the April-May treasury transfers.

## Limitations and known biases

- **Small samples for rare events.** Organic draws are a few per month, so organic intervals are wide and one month can
  move a quarter. Monthly active signer estimates are noisier still; we lean on daily ones.
- **A rule-based classifier.** No labelled data exists for NEAR signers. A human using a batching app can look like a
  bot, and a slow bot can look human. The sensitivity range ({{q1b.organic_share_strict}} to
  {{q1b.organic_share_lenient}}) is the honest error bar on the label, beyond the sampling interval.
- **Single-sourced aggregates.** Intents volume and gross fees come from a NEAR-uploaded dataset via DefiLlama; we
  verified captured revenue, not gross fees. Market caps are CoinGecko's, and the keyless API gives only 365 days.
- **One snapshot.** Every number is as of {{in.as_of}}. A refresh can move them, and the peer set (five chains with a
  token) is our choice.
- **Simple models.** Constant price, no feedback from price to usage, no regime changes beyond the ones listed. Model
  forecasts are extrapolations and are labelled as such.
- **Priors partly reconstructed.** The Q1 and Q2 priors were committed before those data were analysed; the Q4, Q6 and
  model priors were written after those results were seen and are marked as reconstructions in priors.md.
- **Who judges.** This was written for a NEAR-sponsored hackathon, and judges may prefer good news about NEAR. We gave
  the bear case the same space and the same tests, pre-registered the falsifiers in PIANO.md, and hashed the predictions
  before their outcomes exist.
- **Who wrote it.** An AI agent team (Claude models in Claude Code) with no NEAR position, directed by one human.
  AI-written code can be wrong in confident ways: every number here is computed by tested code from committed data and
  filled into this text by the build, so a number cannot drift from the pipeline without a test failing.

## Reproduce it

Two commands on macOS or Linux with `make` and [uv](https://docs.astral.sh/uv/) installed; no account, no key, and no
network access beyond uv installing Python 3.12 and the locked packages:

```
git clone https://github.com/soldanoandrea/near-thesis && cd near-thesis
make reproduce
```

`make reproduce` rebuilds `data/processed/`, the three reports, this essay and the dashboard from the committed raw
snapshots, then runs the tests; `git status` shows nothing modified afterwards. Open `site/index.html` for this essay
and `site/dashboard.html` for the charts. `make refresh` re-downloads every snapshot from the public APIs (several
hours, rate limited) when you want to check a prediction.
