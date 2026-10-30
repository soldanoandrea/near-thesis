"""HSP-029 status snapshot (issuance 2.5% -> 1.6%), from the public NEAR governance forum (Discourse JSON, keyless).

Only facts stated in the proposal text are kept: its status field, the cap formula of its Specification section and
its grace period. The House of Stake voting page (houseofstake.org/proposals/29) is rendered client-side and could
not be read without a browser; the forum's "Status" field is the machine-readable source used here.
"""

from __future__ import annotations

import html
import re

import polars as pl

from .. import manifest
from ..http import PoliteClient

TOPIC = "https://gov.near.org/t/42644.json"


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
