"""Money trails (PIANO.md Q4, phase 2a): every value movement of the NEAR revenue / buyback / treasury wallets, and
where large treasury outflows went next, from the FastNear Transactions API (keyless).

1. `wallet_flows.csv`: all transactions involving each tracked wallet (/v0/account, all roles, paged oldest first),
   expanded with /v0/transactions (20 per call) into one row per value movement touching the wallet:
     * NEAR moved by successful action receipts (Transfer deposits and FunctionCall attached deposits); gas refunds
       (predecessor `system`) are dropped;
     * NEP-141 `ft_transfer` / `ft_mint` / `ft_burn` events (token = the emitting contract);
     * NEP-245 `mt_transfer` / `mt_mint` / `mt_burn` events of intents.near (token = the multi-token id);
     * DIP-4 `token_diff` events of intents.near (swaps inside NEAR Intents, one row per token leg).
2. `trail_hops.csv`: for outflows of at least `min_near` NEAR from treasury.near since `trail_from`, the recipient's
   next transactions (up to 400, oldest first from the receiving height) are expanded the same way and its large NEAR
   outflows are followed, up to `max_depth` hops. A trail stops at a staking pool, a lockup, an account with more than
   `busy_account_txs` transactions (exchange-like: individual deposits cannot be attributed), or the depth limit; the
   stop reason is recorded so the report can say "unknown" where public data ends.
"""

from __future__ import annotations

import json
import sys

import polars as pl

from .. import config, manifest
from ..http import PoliteClient

HOST = "tx.main.fastnear.com"
FRESH_S = 7 * 86400
WALLETS = ["treasury.near", "buybacks.multisignature.near", "fefundsadmin.sputnik-dao.near",
           "1csfundsadmin.sputnik-dao.near"]
TRAIL = {"from_wallet": "treasury.near", "trail_from": "2026-04-01", "min_near": 100_000, "max_depth": 5,
         "busy_account_txs": 20_000, "max_txs_per_account": 400}
FLOW_SCHEMA = {"wallet": pl.Utf8, "tx_hash": pl.Utf8, "receipt_id": pl.Utf8, "block_height": pl.Int64,
               "block_timestamp_ns": pl.Utf8, "kind": pl.Utf8, "direction": pl.Utf8, "counterparty": pl.Utf8,
               "asset": pl.Utf8, "amount_raw": pl.Utf8, "method": pl.Utf8, "tx_signer": pl.Utf8,
               "tx_receiver": pl.Utf8}


def _success(outcome: dict) -> bool:
    st = outcome.get("status") or {}
    return isinstance(st, dict) and ("SuccessValue" in st or "SuccessReceiptId" in st)


def _events(logs: list[str]):
    for lg in logs:
        if lg.startswith("EVENT_JSON:"):
            try:
                yield json.loads(lg[len("EVENT_JSON:"):])
            except ValueError:
                continue


def flows_of_tx(t: dict, wallets: set[str]) -> list[dict]:
    """Value movements touching any account in `wallets` inside one transaction (see module docstring)."""
    tr = t["transaction"]
    base = {"tx_hash": tr["hash"], "tx_signer": tr["signer_id"], "tx_receiver": tr["receiver_id"]}
    out = []

    def add(wallet, direction, counterparty, asset, amount, kind, rc, method=""):
        if amount in (None, "0", 0, ""):
            return
        out.append({"wallet": wallet, **base, "receipt_id": rc["receipt"]["receipt_id"],
                    "block_height": int(rc["execution_outcome"]["block_height"]),
                    "block_timestamp_ns": str(rc["execution_outcome"]["block_timestamp"]), "kind": kind,
                    "direction": direction, "counterparty": counterparty, "asset": asset, "amount_raw": str(amount),
                    "method": method})

    for rc in t.get("receipts") or []:
        r = rc["receipt"]
        oc = rc["execution_outcome"]["outcome"]
        ok = _success(oc)
        pred, recv = r["predecessor_id"], r["receiver_id"]
        act = (r.get("receipt") or {}).get("Action")
        if act and ok and pred != "system":
            for a in act.get("actions") or []:
                if not isinstance(a, dict):
                    continue
                (k, v), = a.items()
                dep, meth = None, ""
                if k == "Transfer":
                    dep = v.get("deposit")
                elif k == "FunctionCall":
                    dep, meth = v.get("deposit"), v.get("method_name", "")
                if dep and int(dep) > 0:
                    kind = "near_transfer" if k == "Transfer" else "near_call_deposit"
                    if recv in wallets:
                        add(recv, "in", pred, "NEAR", dep, kind, rc, meth)
                    if pred in wallets:
                        add(pred, "out", recv, "NEAR", dep, kind, rc, meth)
        if not ok:
            continue
        executor = oc.get("executor_id", recv)
        for e in _events(oc.get("logs") or []):
            std, ev, data = e.get("standard"), e.get("event"), e.get("data") or []
            if std == "nep141":
                for d in data:
                    amt = d.get("amount")
                    if ev == "ft_transfer":
                        if d.get("new_owner_id") in wallets:
                            add(d["new_owner_id"], "in", d.get("old_owner_id", ""), executor, amt, "ft_transfer", rc)
                        if d.get("old_owner_id") in wallets:
                            add(d["old_owner_id"], "out", d.get("new_owner_id", ""), executor, amt, "ft_transfer", rc)
                    elif ev in ("ft_mint", "ft_burn") and d.get("owner_id") in wallets:
                        add(d["owner_id"], "in" if ev == "ft_mint" else "out", executor, executor, amt, ev, rc)
            elif std == "nep245":
                for d in data:
                    ids, amts = d.get("token_ids") or [], d.get("amounts") or []
                    for tok, amt in zip(ids, amts):
                        asset = f"{executor}:{tok}"
                        if ev == "mt_transfer":
                            if d.get("new_owner_id") in wallets:
                                add(d["new_owner_id"], "in", d.get("old_owner_id", ""), asset, amt, "mt_transfer", rc)
                            if d.get("old_owner_id") in wallets:
                                add(d["old_owner_id"], "out", d.get("new_owner_id", ""), asset, amt, "mt_transfer", rc)
                        elif ev in ("mt_mint", "mt_burn") and d.get("owner_id") in wallets:
                            add(d["owner_id"], "in" if ev == "mt_mint" else "out", executor, asset, amt, ev, rc)
            elif std == "dip4" and ev == "token_diff":
                for d in data:
                    if d.get("account_id") in wallets:
                        for tok, amt in (d.get("diff") or {}).items():
                            a = int(amt)
                            add(d["account_id"], "in" if a > 0 else "out", executor, f"{executor}:{tok}", str(abs(a)),
                                "token_diff", rc)
    return out


class Trails:
    def __init__(self, client: PoliteClient):
        self.c = client
        self.base = config.load()["endpoints"]["fastnear_tx"]

    def history(self, account: str, from_height: int | None = None, max_rows: int | None = None) -> tuple[list[dict], int]:
        """Account rows oldest first (all roles), following resume tokens. Returns (rows, txs_count)."""
        rows, token, count = [], None, 0
        while True:
            body = {"account_id": account, "limit": 200, "desc": False}
            if from_height is not None:
                body["from_tx_block_height"] = from_height
            if token:
                body["resume_token"] = token
            d = self.c.post_json(f"{self.base}/v0/account", body, max_age_s=FRESH_S)
            count = int(d["txs_count"]) if "txs_count" in d else count
            page = d.get("account_txs") or []
            rows += page
            token = d.get("resume_token")
            if not page or not token or len(page) < 200 or (max_rows and len(rows) >= max_rows):
                break
        return (rows[:max_rows] if max_rows else rows), count

    def details(self, hashes: list[str]) -> list[dict]:
        out = []
        uniq = list(dict.fromkeys(hashes))
        for i in range(0, len(uniq), 20):
            d = self.c.post_json(f"{self.base}/v0/transactions", {"tx_hashes": uniq[i:i + 20]}, immutable=True)
            out += d.get("transactions") or []
        return out


def classify(acc: str) -> str:
    """Counterparty class from the account id alone (no off-chain labels)."""
    import re
    if acc in WALLETS:
        return "treasury" if acc == "treasury.near" else "revenue_wallet"
    if acc == "intents.near":
        return "intents"
    if acc == "system":
        return "protocol"
    if acc == "wrap.near" or acc.endswith(".omft.near") or acc.endswith(".factory.bridge.near"):
        return "token_contract"
    if re.search(r"\.(poolv1|pool)\.near$", acc) or ".pool." in acc:
        return "staking_pool"
    if acc.endswith(".lockup.near"):
        return "lockup"
    if acc.endswith(".sputnik-dao.near"):
        return "sputnik_dao"
    if acc.endswith(".multisignature.near") or acc.endswith(".multisig.near"):
        return "multisig"
    if re.fullmatch(r"[0-9a-f]{64}", acc):
        return "implicit_near"
    if re.fullmatch(r"0x[0-9a-f]{40}", acc):
        return "implicit_eth"
    return "named_other"


def fetch(client: PoliteClient) -> None:
    tr = Trails(client)
    wallets = set(WALLETS)
    all_flows, counts = [], {}
    for w in WALLETS:
        rows, n = tr.history(w)
        counts[w] = n
        txs = tr.details([r["transaction_hash"] for r in rows])
        before = len(all_flows)
        for t in txs:
            all_flows += [f for f in flows_of_tx(t, {w}) if f["wallet"] == w]
        print(f"  {w}: {len(rows)} txs (txs_count {n}), {len(all_flows) - before} flows", file=sys.stderr, flush=True)
    fdf = pl.DataFrame(all_flows, schema=FLOW_SCHEMA).unique(maintain_order=True)
    manifest.save_table("fastnear_tx", "wallet_flows", fdf, urls=[f"{tr.base}/v0/account", f"{tr.base}/v0/transactions"],
                        params={"wallets": WALLETS, "txs_count_at_fetch": counts},
                        sort_by=["wallet", "block_height", "tx_hash", "receipt_id", "kind", "asset", "direction",
                                 "counterparty", "amount_raw"],
                        notes="One row per value movement touching a tracked wallet (NEAR deposits of successful action "
                              "receipts excluding gas refunds; NEP-141, NEP-245 and DIP-4 token_diff events). amount_raw "
                              "in the asset's smallest unit (NEAR: yocto).",
                        http_stats=client.stats_for(HOST))

    # 2. follow large NEAR outflows of the treasury -------------------------------------------------------------
    import datetime as dt
    t_from = int(dt.datetime.fromisoformat(TRAIL["trail_from"]).replace(tzinfo=dt.UTC).timestamp() * 1e9)
    start = fdf.filter((pl.col("wallet") == TRAIL["from_wallet"]) & (pl.col("direction") == "out")
                       & (pl.col("asset") == "NEAR") & (pl.col("block_timestamp_ns").cast(pl.Int64) >= t_from))
    frontier = [(0, TRAIL["from_wallet"], r["counterparty"], int(r["amount_raw"]), r["block_height"], r["tx_hash"])
                for r in start.iter_rows(named=True) if int(r["amount_raw"]) >= TRAIL["min_near"] * 10**24]
    hops, seen = [], set()
    while frontier:
        depth, src, acc, amount, height, txh = frontier.pop(0)
        cls = classify(acc)
        stop, nxt = "", []
        if (acc, height) in seen:
            stop = "already_traced"
        elif cls in ("staking_pool", "lockup", "intents", "token_contract", "revenue_wallet"):
            stop = f"terminal:{cls}"
        else:
            seen.add((acc, height))
            rows, n = tr.history(acc, from_height=height, max_rows=TRAIL["max_txs_per_account"])
            if n > TRAIL["busy_account_txs"]:
                stop = f"busy_account:{n}_txs_after_receipt"
            else:
                out_rows = [r for r in rows if r.get("is_predecessor") or r.get("is_signer")]
                txs = tr.details([r["transaction_hash"] for r in out_rows])
                fl = [f for t in txs for f in flows_of_tx(t, {acc}) if f["wallet"] == acc and f["direction"] == "out"]
                big = [f for f in fl if f["asset"] == "NEAR" and int(f["amount_raw"]) >= TRAIL["min_near"] * 10**24]
                if depth + 1 >= TRAIL["max_depth"]:
                    stop = "depth_limit"
                for f in fl:
                    hops.append({"depth": depth + 1, "source": src, "account": acc, "account_class": cls,
                                 "received_tx": txh, "received_height": height, "received_near_yocto": str(amount),
                                 "out_tx": f["tx_hash"], "out_height": f["block_height"],
                                 "out_timestamp_ns": f["block_timestamp_ns"], "out_kind": f["kind"],
                                 "out_method": f["method"], "out_counterparty": f["counterparty"],
                                 "out_counterparty_class": classify(f["counterparty"]), "out_asset": f["asset"],
                                 "out_amount_raw": f["amount_raw"], "account_txs_after_receipt": n, "stop_reason": ""})
                if not fl:
                    stop = "no_outflow_seen" if n <= TRAIL["max_txs_per_account"] else "outflow_beyond_window"
                if not stop:
                    nxt = [(depth + 1, acc, f["counterparty"], int(f["amount_raw"]), f["block_height"], f["tx_hash"])
                           for f in big]
        if stop:
            hops.append({"depth": depth + 1, "source": src, "account": acc, "account_class": cls, "received_tx": txh,
                         "received_height": height, "received_near_yocto": str(amount), "out_tx": "", "out_height": None,
                         "out_timestamp_ns": "", "out_kind": "", "out_method": "", "out_counterparty": "",
                         "out_counterparty_class": "", "out_asset": "", "out_amount_raw": "",
                         "account_txs_after_receipt": None, "stop_reason": stop})
        frontier += nxt
        print(f"  trail depth {depth + 1} {acc} ({cls}): {stop or f'{len(nxt)} large outflows followed'}",
              file=sys.stderr, flush=True)
    hdf = pl.DataFrame(hops, schema={"depth": pl.Int64, "source": pl.Utf8, "account": pl.Utf8, "account_class": pl.Utf8,
                                     "received_tx": pl.Utf8, "received_height": pl.Int64,
                                     "received_near_yocto": pl.Utf8, "out_tx": pl.Utf8, "out_height": pl.Int64,
                                     "out_timestamp_ns": pl.Utf8, "out_kind": pl.Utf8, "out_method": pl.Utf8,
                                     "out_counterparty": pl.Utf8, "out_counterparty_class": pl.Utf8,
                                     "out_asset": pl.Utf8, "out_amount_raw": pl.Utf8,
                                     "account_txs_after_receipt": pl.Int64, "stop_reason": pl.Utf8})
    manifest.save_table("fastnear_tx", "trail_hops", hdf, urls=[f"{tr.base}/v0/account", f"{tr.base}/v0/transactions"],
                        params=TRAIL, sort_by=["depth", "account", "received_height", "out_height", "out_tx",
                                               "out_asset", "out_counterparty", "out_amount_raw"],
                        notes="Outflows of accounts that received >= min_near NEAR from treasury.near since trail_from, "
                              "followed hop by hop; stop_reason says where and why a trail ends.",
                        http_stats=client.stats_for(HOST))
