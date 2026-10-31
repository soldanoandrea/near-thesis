# Demo post for X (draft, for the human to publish)

Not posted. The rules ask for a public X post that says the project was built at NEAR HACKATHON, tags @NEARProtocol and
#NEARHackathon, explains NEAR's concrete role and attaches the demo video (screenshots alone are not enough). An X post
carries either one video or up to four images, not both: attach [media/demo.mp4](media/demo.mp4) to the main post and
put the chart in the first reply. Numbers below are filled in by `make site` from the snapshot as-of {{in.as_of}}.

## Main post (under 280 characters; attach media/demo.mp4)

```
Is NEAR's activity real? Rebuilt from NEAR's own chain data (archival RPC, intents.near events): {{q1b.organic_tx_share}} of txs are organic, NearBlocks undercounts users {{q1b.das_to_nearblocks:x}}, Intents revenue checks out on-chain.

Built at NEAR HACKATHON @NEARProtocol #NEARHackathon
https://github.com/soldanoandrea/near-thesis
```

## Optional thread

Reply 1 (attach [media/screens/classes.png](media/screens/classes.png), the one chart):

```
Who sends NEAR's transactions, 2026-Q3, signer by signer: organic {{oq.2026q3.share_organic}} ({{oq.2026q3.share_organic:ci}}), reward programs {{oq.2026q3.share_incentivized}}, bots {{oq.2026q3.share_automated}}, relays {{oq.2026q3.share_infrastructure}}. 90% intervals from a seeded block sample, no API keys.
```

Reply 2:

```
NEAR Intents swaps are real, but counted once they are {{q2b.ratio_sample_median:p0}} of DefiLlama's volume ({{q2b.ratio_two_sided_median:p0}} two-sided). Captured revenue rebuilt from the revenue wallets: {{q4b.revenue_onchain_to_defillama:p1}}. {{q4b.near_captured_since_buybacks}} bought back, float still +{{sc.status_quo/base.1y.float_cagr}}/yr.
```

Reply 3:

```
{{pred.count:int}} dated predictions, hashed and tagged before the outcomes exist. If organic use and captured revenue both miss by {{pred.P1.date}}, the case is falsified. One command rebuilds every number: make reproduce
```

Optional tags: @NearBuilders. Do not add claims that are not in the repository.
