# Demo video script (under 3 minutes)

`make video` renders [media/demo.mp4](media/demo.mp4) from this storyline (scenes and durations in
`scripts/video/render.sh`; the terminal scene in [demo.tape](demo.tape)). The video is silent: each frame carries its
own heading and the dashboard card's one-sentence caption. The voice-over lines below are for a narrated version; their
numbers are filled in by `make site` from the same tables as the charts. Snapshot as-of {{in.as_of}}.

| Time | Scene | On screen | Voice-over (optional) |
|---|---|---|---|
| 0:00 | Title | Dashboard headline tiles (`dashboard.html#capture=hero`) | "Is there a data-backed long-term case for NEAR? We rebuilt the numbers from the chain and kept the ones that survived." |
| 0:07 | Reproduce | Terminal, fresh clone, played at 2x: `make reproduce` rebuilds tables, reports, the essay and the site offline, then {{fs.rows:int}} falsifiers are scored and the tests pass; `git status` shows nothing changed; the predictions hash and tag | "No keys, no accounts. One command rebuilds every number, chart and sentence from committed snapshots, and the tests check it is byte-identical." |
| 0:44 | 1. Organic use is small | Signer classes with 90% intervals | "Signer by signer, organic human-like use is {{q1b.organic_tx_share}} of NEAR's transactions in 2026-Q3, between {{q1b.organic_tx_share:ci}}. The rest is reward programs, bots and relays." |
| 0:57 | 1. Organic use is small | Daily active signers, log scale | "Organic daily active signers: {{q1b.organic_das}}, between {{oq.from2025q3.das_organic_min}} and {{oq.from2025q3.das_organic_max}} in every quarter since 2025-Q3: small, with no clear trend since mid-2025. And NearBlocks' active accounts miss real signers by {{om.das_to_nearblocks.last6:x}}: relayers hide them." |
| 1:10 | 2. Intents is real; half its volume is not visible | On-chain rebuild vs DefiLlama, {{ic.days}} sampled days | "We rebuilt NEAR Intents swaps from settlement events. Counted once, they are {{q2b.ratio_sample_median:p0}} of DefiLlama's volume; counted on both legs, {{q2b.ratio_two_sided_median:p0}}. The swaps are real; the rest is two-sided counting or flow public events cannot see." |
| 1:25 | 3. Captured revenue checks out | Monthly revenue, DefiLlama vs on-chain | "Captured revenue is different: rebuilt from the revenue wallets it matches DefiLlama at {{q4b.revenue_onchain_to_defillama:p1}}, and since {{rev.src.recent.first_month}} {{rev.src_intents_share.recent:p1}} of it comes straight from the Intents contract. {{q4b.near_captured_since_buybacks}} has reached the revenue wallets since buybacks began, and is held." |
| 1:37 | 4. Treasury trail | Sankey of `treasury.near` outflows | "{{q4b.treasury_outflows_since_apr}} left the treasury in April and May. {{q4b.trail_into_staking}} reached staking pools within five hops; the rest ends at unlabelled accounts." |
| 1:50 | 5. Dilution | Supply fans, 2.5% vs HSP-029 | "Holders are still diluted: the float grows {{sc.status_quo/base.1y.float_cagr}} a year. Offsetting it needs {{ma.net_zero_multiple.0.0249:x}} today's Intents revenue ({{ma.net_zero_multiple_half_price.0.0249:x}} at half the price, {{ma.net_zero_multiple_365d.0.0249:x}} against last year's revenue), or {{ma.net_zero_multiple.0.0159:x}} if HSP-029 passes." |
| 2:02 | 5. Valuation | Multiples vs peers, log scale | "On its own fees NEAR trades at {{mb.chain_fees:x}}; counting Intents fees, {{mb.fees_plus_intents_fees:x}}. The valuation depends on how much of Intents belongs to holders." |
| 2:12 | 6. Path to yes | Organic signers, captured revenue and float dilution against the frozen thresholds | "What would confirm the case by late 2027: at least {{pred.P1.threshold}} organic daily active signers in 2027-Q3, at least {{pred.P4.threshold}} of captured revenue over the six months to 2027-04, and dilution below 2% a year." |
| 2:24 | 6. What would change our mind | Dated predictions table with sha256 and tag | "{{pred.count:int}} dated predictions, thresholds computed by the pipeline, hashed and tagged today. If organic use and captured revenue both fail by their dates, the case is falsified." |
| 2:37 | Close | NEAR's role, reproduce command, links | "Built at NEAR HACKATHON. Every number comes from NEAR itself: archival RPC, the FastNear indexer and NEAR Intents settlement events." |

Total: about 2 minutes 45 seconds (`ffprobe` prints the exact duration at the end of `make video`).

## How it is made

1. `scripts/video/screenshots.sh` opens `site/dashboard.html#capture=<card>&note=<heading>` in headless Chrome at
   1280x720 and saves one PNG per scene (the same mechanism writes `docs/media/screens/`, without headings).
2. VHS records [demo.tape](demo.tape) in a fresh clone of HEAD (so no local paths show): `make reproduce` filtered to
   its build steps, three headline numbers and the test summary; then `git status`, the predictions hash and the tag.
3. ffmpeg plays the terminal at 2x, holds each PNG for its scene length with a short fade, and joins everything into an
   H.264 MP4 with no audio, under 3 minutes and 25 MB.

Requirements: VHS (with ttyd), ffmpeg, Google Chrome or Chromium, and the network for Plotly.js from cdnjs. None of this
is needed to reproduce the thesis itself.
