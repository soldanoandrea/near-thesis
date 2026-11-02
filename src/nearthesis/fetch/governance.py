"""HSP-029 status snapshot (issuance 2.5% -> 1.6%), from the public NEAR governance forum (Discourse JSON, keyless).

Only facts stated in the proposal text are kept: its status field, the cap formula of its Specification section and
its grace period. The vote itself is read on-chain: House of Stake votes live in the `vote.dao` contract on NEAR
mainnet, and its `get_proposal` view returns the status, the veNEAR per option, the quorum and the timelock
(the houseofstake.org page renders the same view client-side).
"""

from __future__ import annotations

import html
import re

import polars as pl

from .. import config, manifest
from ..http import PoliteClient
from .onchain_state import _rpc

TOPIC = "https://gov.near.org/t/42644.json"
VOTE_CONTRACT = "vote.dao"
PROPOSAL_ID = 29
YOCTO = 10 ** 24


def _text(cooked: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", cooked))).strip()


def _field(txt: str, name: str, nxt: str) -> str:
    m = re.search(rf"{name}:\s*(.*?)\s+{nxt}:", txt)
    return m.group(1).strip() if m else ""


def fetch(client: PoliteClient) -> None:
    d = client.get_json(TOPIC)
    txt = _text(d["post_stream"]["posts"][0]["cooked"])
    spec = re.search(r"Specification (cap\(t\).*?interpolated per epoch\.)", txt)
    grace = re.search(r"(Activation occurs [^.]*\.)", txt)
    row = {"topic_url": TOPIC.replace(".json", ""), "title": d["title"], "created_at": d["created_at"],
           "last_posted_at": d.get("last_posted_at") or "", "posts_count": int(d.get("posts_count") or 0),
           "hsp": _field(txt, "HSP", "Title"), "status": _field(txt, "Status", "Track"),
           "decision_type": _field(txt, "Type", "Category"), "discussions_to": _field(txt, "Discussions-to", "Status"),
           "spec_cap_formula": spec.group(1) if spec else "", "activation": grace.group(1) if grace else ""}
    manifest.save_table("governance", "hsp029_status", pl.DataFrame([row]), urls=[TOPIC],
                        notes="HSP-029 proposal metadata from the NEAR governance forum at fetch time (status field of "
                              "the proposal frontmatter, cap formula, activation rule).",
                        http_stats=client.stats_for("gov.near.org"))


def _utc(ns: int) -> str:
    import datetime as dt
    return dt.datetime.fromtimestamp(ns / 1e9, dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_onchain(client: PoliteClient) -> None:
    """HSP-029 vote on `vote.dao` (House of Stake): one keyless `get_proposal` view at the final block."""
    import base64
    import json

    args = base64.b64encode(json.dumps({"proposal_id": PROPOSAL_ID}).encode()).decode()
    res = _rpc(client, "query", {"request_type": "call_function", "finality": "final", "account_id": VOTE_CONTRACT,
                                 "method_name": "get_proposal", "args_base64": args})
    p = json.loads(bytes(res["result"]).decode())
    votes = [int(v["total_venear"]) for v in p["votes"]]  # options in order: For, Against, Abstain
    total = int(p["total_votes"]["total_venear"])
    start = int(p["voting_start_time_ns"])
    end = start + int(p["voting_duration_ns"])
    snap = p["snapshot_and_state"]
    row = {"contract": VOTE_CONTRACT, "proposal_id": int(p["id"]), "status": p["status"], "flow": p.get("flow") or "",
           "voters": int(p["total_votes"]["total_votes"]),
           "venear_for": votes[0] / YOCTO, "venear_against": votes[1] / YOCTO, "venear_abstain": votes[2] / YOCTO,
           "venear_voted": total / YOCTO, "venear_snapshot_total": int(snap["total_venear"]) / YOCTO,
           "snapshot_block_height": int(snap["snapshot"]["block_height"]),
           "quorum_threshold_bps": int(p["quorum_threshold_bps"]), "approval_threshold_bps": int(p["approval_threshold_bps"]),
           "voting_start_utc": _utc(start), "voting_end_utc": _utc(end),
           "timelock_end_utc": _utc(end + int(p.get("timelock_duration_ns") or 0)) if p.get("timelock_duration_ns") else ""}
    manifest.save_table("governance", "hsp029_onchain", pl.DataFrame([row]),
                        urls=[f"{config.load()['endpoints']['rpc']} call_function {VOTE_CONTRACT} get_proposal "
                              f"proposal_id={PROPOSAL_ID} (finality final)"],
                        notes="House of Stake vote on HSP-029, read from the vote.dao contract. veNEAR in whole units; "
                              "options in contract order For, Against, Abstain. Status 'Timelock' = vote passed, Security "
                              "Council veto window open until timelock_end_utc, ratified automatically after it.",
                        http_stats=client.stats_for("free.rpc.fastnear.com"))
