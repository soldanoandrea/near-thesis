# Submission template (NOT sent)

Fields and constraints from https://nearhackathon.com/HACKATHON.md as read on 2026-10-31 (the sibling project
Allowance recorded the same field list that day in its `docs/SUBMISSION.md`); **re-read HACKATHON.md before
submitting**. Nothing here has been sent. The submission is `POST https://nearhackathon.com/api/applications` with
`Content-Type: application/json`, body <= 12,000 bytes, only these fields (the `website` field is a spam trap: never
include it). The project description goes in `idea` (20-2000 characters). An agent may prepare the final JSON and print
it in full; it is sent only after the human says yes.

```json
{
  "requestId": "<HUMAN: generate one UUID at submission time (uuidgen) and reuse it on retries>",
  "projectName": "near-thesis: NEAR on the evidence",
  "leadName": "<HUMAN: 2-80 characters>",
  "email": "<HUMAN: contact email, max 160 characters, at most 2 submissions per email>",
  "size": "<HUMAN: one of \"1\", \"2 - 4\", \"4 - 6\", \"6 - 8\", \"8+\">",
  "tracks": ["thesis"],
  "nearAddress": "<HUMAN: your mainnet NEAR account for the prize payout, created by you in a wallet>",
  "projectUrl": "https://github.com/soldanoandrea/near-thesis",
  "demoUrl": "<HUMAN: https URL of your public X post with the video>",
  "idea": "A data-backed, re-runnable long-term thesis on NEAR, judged on evidence. Every number is rebuilt from keyless public data, mostly NEAR's own chain: archival RPC block headers (supply, burn, staking), the FastNear indexer (per-signer histories, wallet flows) and DIP-4 settlement events on intents.near. At the {{in.as_of}} snapshot, organic human-like signers sent {{q1b.organic_tx_share}} of transactions in 2026-Q3 (90% interval {{q1b.organic_tx_share:ci}}) and NearBlocks' active accounts undercount real signers {{q1b.das_to_nearblocks:x}}, because relayers hide users. NEAR Intents swaps are real, but counted once they are {{q2b.ratio_sample_median}} of DefiLlama's volume ({{q2b.ratio_two_sided_median}} two-sided); captured revenue rebuilt from the revenue wallets matches at {{q4b.revenue_onchain_to_defillama}}, and {{q4b.near_captured_since_buybacks}} has been bought back and held. Holders are still diluted: the float grows {{sc.status_quo/base.1y.float_cagr}} a year, and offsetting it needs {{ma.net_zero_multiple.0.0249:x}} today's Intents revenue ({{ma.net_zero_multiple.0.0159:x}} under HSP-029). treasury.near sent {{q4b.treasury_outflows_since_apr}} in April-May 2026; {{q4b.trail_into_staking}} reached staking pools within five hops. The verdict is conditional, not bullish. The repo has a static dashboard (eight charts, each saying what it shows and what it does not), a thesis whose numbers are filled in from the data by the build, a falsifier scorecard, {{pred.count:int}} dated predictions frozen with a sha256 in a git tag, and one command, make reproduce, that rebuilds everything offline and tests that it is byte-identical.",
  "consent": "<HUMAN: true only after you heard the contact notice verbatim and agreed>"
}
```

`tracks` is `["thesis"]` only (allowed values as recorded: `defi`, `thesis`, `privacy`, `business`, `swarms`, `security`,
`agents`, `realworld`, `games`, `nfts`, `memecoins`, `social`, `open`). `tests/test_site.py` checks that this JSON parses,
that `idea` is 20-2000 characters and that no `website` field is present.

## Fields only the human provides

| Field | Constraint | Note |
|---|---|---|
| `requestId` | UUID | generate once at submission time, reuse it on retries (400/503) |
| `leadName` | 2-80 chars | |
| `email` | valid, <= 160 chars | at most 2 submissions per email (this and Allowance) |
| `size` | `1`, `2 - 4`, `4 - 6`, `6 - 8`, `8+` | one human with AI agents disclosed in the README; your call |
| `nearAddress` | 2-64 chars, lowercase, **mainnet** named or implicit account | created by you in a wallet; never invented by an agent |
| `projectUrl` | public repo URL, <= 300 chars, unique per repository | prefilled; the repository must be public by 2026-11-14T23:59:00Z |
| `demoUrl` | public X post URL, <= 300 chars | see [DEMO_POST.md](DEMO_POST.md); the post must include the video |
| `consent` | `true` only after the notice | the agent reads you the contact notice from the "Consent" section of HACKATHON.md word for word, at submission time |

## Before sending: checklist for the human

- [ ] Submission window: 2026-11-01T00:00:00Z to 2026-11-14T23:59:00Z (00:59 CET on Nov 15).
- [ ] Make the repository public (`gh repo edit soldanoandrea/near-thesis --visibility public` or the GitHub UI) and
      push `main`. Agents committed locally and pushed nothing.
- [ ] Push the predictions tag so the commitment is public: `git push origin predictions-2026-10-31`. Its sha256
      (`{{pred.sha256}}`) is also in `thesis/THESIS.md`, `thesis/falsifiers.md` and the dashboard.
- [ ] Enable GitHub Pages (Settings -> Pages -> Source: GitHub Actions); the workflow `.github/workflows/pages.yml`
      publishes `site/` on push to main. Keep it up until at least 2026-11-18, ideally 2026-11-25.
- [ ] Publish the X post from [DEMO_POST.md](DEMO_POST.md) with `docs/media/demo.mp4` attached; put its URL in `demoUrl`.
- [ ] Confirm the disclosure: THESIS.md and the README say the authors are an AI agent team with no NEAR position,
      directed by one human. If you hold NEAR, edit `thesis/THESIS.in.md` and run `make site`.
- [ ] Both READMEs name each other: this one names Allowance (https://github.com/soldanoandrea/allowance); Allowance's
      README names near-thesis.
- [ ] HSP-029: the vote was reported to close on 2026-11-02, after the snapshot. The thesis states the status at the
      snapshot ("{{in.hsp029_status}}"); refreshing the governance snapshot would change committed data and is optional.
- [ ] Final JSON printed in full and approved by you; then sent once. Responses: 201 saved; 400 fix the listed fields and
      resend with the same `requestId`; 403 closed, do not retry; 409 repo/email limit reached, ask, do not change link
      or email; 413 shorten `idea`; 503 wait a minute and resend with the same `requestId`.
