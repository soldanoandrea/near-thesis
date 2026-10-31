"""NEAR Intents settlement cross-check (PIANO.md Q2 / section 3.2, phase 2a). Keyless: FastNear Transactions API,
FastNear archival RPC view calls, the public 1Click token list and DefiLlama coin prices.

Contracts (docs.near-intents.org, read 2026-10-30 UTC): the Verifier `intents.near` settles every intent and emits
DIP-4 `token_diff` events for swaps; it charges a protocol fee of `fee()` pips (1 pip = 0.0001%) on the sold leg of
each token_diff and moves it to `fee_collector()` (an implicit account) inside its own NEP-245 ledger.

For each of `days` sampled UTC days (one uniform day per 2-month stratum, seeded):
1. `intents_days.csv`: the day's block-height range (first block at or after 00:00 UTC, FastNear /v0/blocks search),
   the census count of transactions in which the fee collector appears in an event log (= transactions that paid a
   protocol fee, i.e. swaps), the count of transactions touching intents.near, and `fee()` at both ends.
2. `intents_fee_collector_balances.csv`: the fee collector's balance of every token it holds, at the first block of
   the day and of the next day (archival `mt_batch_balance_of`). The difference is the protocol fee collected that
   day; divided by the fee rate it is a census of gross sold volume per token (both sides of every swap).
3. `intents_swap_legs.csv`: a cluster sample of fee-paying transactions: `windows_per_day` windows of consecutive
   blocks (uniform seeded starts, length chosen to hold ~`target_txs_per_window` fee-paying transactions), every such
   transaction expanded with /v0/transactions into one row per token_diff leg (account, token, signed amount, fee
   collected on that token, referral tag).
Prices (`defillama/coin_prices_intents_days.csv`) are DefiLlama historical prices at 12:00 UTC of each day for the
CoinGecko ids that the 1Click token list (`oneclick/tokens.csv`) assigns to each asset id.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import sys

import numpy as np
import polars as pl

from .. import config, io, manifest, paths
from ..http import PoliteClient
from .fastnear_activity import TxApi
from .rpc_epochs import Archival

ONECLICK_TOKENS = "https://1click.chaindefuser.com/v0/tokens"


def sample_days(cfg: dict, seed: int) -> list[str]:
    first, last = dt.date.fromisoformat(cfg["first_day"]), dt.date.fromisoformat(cfg["last_day"])
    n = int(cfg["days"])
    span = (last - first).days + 1
    edges = [first + dt.timedelta(days=round(i * span / n)) for i in range(n + 1)]
    rng = np.random.default_rng([seed, 4])
    return [str(a + dt.timedelta(days=int(rng.integers(0, (b - a).days)))) for a, b in zip(edges[:-1], edges[1:])]


def _view(arc: Archival, account: str, method: str, args: dict, block: int):
    res = arc.call("query", {"request_type": "call_function", "block_id": block, "account_id": account,
                             "method_name": method,
                             "args_base64": base64.b64encode(json.dumps(args).encode()).decode()})
    return json.loads(bytes(res["result"]))


def _safe_view(arc: Archival, account: str, method: str, args: dict, block: int):
    """View call that returns None when the method did not exist at that height (older contract versions)."""
    from ..http import RpcError
    try:
        return _view(arc, account, method, args, block)
    except RpcError as exc:
        print(f"  {method} at {block}: {exc.cause}", file=sys.stderr)
        return None


def _ns(d: dt.date) -> int:
    return int(dt.datetime.combine(d, dt.time(), dt.UTC).timestamp()) * 1_000_000_000


def fetch(client: PoliteClient) -> None:
    cfg, seed = config.load()["intents_check"], int(config.load()["activity"]["seed"])
    verifier = cfg["verifier"]
    api, arc = TxApi(client), Archival(client)
    base = api.base
    mb = io.read_csv(paths.RAW / "fastnear_tx" / "month_boundaries.csv")
    anchors = [(r[0], int(r[1]), int(r[2])) for r in mb.select("boundary_utc", "height", "block_timestamp_ns").iter_rows()]
    days = sample_days(cfg, seed)
    print(f"  sampled days: {days}", file=sys.stderr)

    day_rows, bal_rows, leg_rows, tx_rows, win_rows, ctl_rows = [], [], [], [], [], []
    for day in days:
        d0 = dt.date.fromisoformat(day)
        bounds = []
        for t in (_ns(d0), _ns(d0 + dt.timedelta(days=1))):
            lo = max((a for a in anchors if a[2] < t), key=lambda a: a[1])
            hi = min((a for a in anchors if a[2] >= t), key=lambda a: a[1])
            bounds.append(api.height_at(t, (lo[1], lo[2]), (hi[1], hi[2])))
        (h0, t0), (h1, t1) = bounds
        fee0, fee1 = (_safe_view(arc, verifier, "fee", {}, h) for h in (h0, h1))
        fc, fc1 = (_safe_view(arc, verifier, "fee_collector", {}, h) for h in (h0, h1))
        fc = fc or fc1
        n_fee = int(client.post_json(f"{base}/v0/account", {"account_id": fc, "is_event_log": True,
                                                            "from_tx_block_height": h0, "to_tx_block_height": h1 - 1,
                                                            "limit": 1}, immutable=True)["txs_count"])
        n_int = int(client.post_json(f"{base}/v0/account", {"account_id": verifier, "is_real_receiver": True,
                                                            "from_tx_block_height": h0, "to_tx_block_height": h1 - 1,
                                                            "limit": 1}, immutable=True)["txs_count"])
        day_rows.append({"day": day, "from_height": h0, "to_height_exclusive": h1, "from_timestamp_ns": str(t0),
                         "to_timestamp_ns": str(t1), "fee_pips_start": fee0, "fee_pips_end": fee1,
                         "fee_collector": fc, "fee_collector_end": fc1, "fee_paying_txs": n_fee,
                         "intents_receiver_txs": n_int})
        # fee collector balances ------------------------------------------------------------------------------
        toks, start = [], 0
        while True:
            page = _view(arc, verifier, "mt_tokens_for_owner", {"account_id": fc, "from_index": str(start),
                                                               "limit": 500}, h1)
            toks += [p["token_id"] for p in page]
            if len(page) < 500:
                break
            start += 500
        toks = sorted(set(toks))
        b0 = _view(arc, verifier, "mt_batch_balance_of", {"account_id": fc, "token_ids": toks}, h0)
        b1 = _view(arc, verifier, "mt_batch_balance_of", {"account_id": fc, "token_ids": toks}, h1)
        for tok, x0, x1 in zip(toks, b0, b1):
            bal_rows.append({"day": day, "token_id": tok, "balance_start": str(x0), "balance_end": str(x1)})
        # cluster sample of fee-paying transactions --------------------------------------------------------------
        w = max(1, round(int(cfg["target_txs_per_window"]) * (h1 - h0) / max(n_fee, 1)))
        rng = np.random.default_rng([seed, int(day.replace("-", "")), 5])
        starts = sorted(int(x) for x in rng.integers(h0, max(h0 + 1, h1 - w), size=int(cfg["windows_per_day"])))
        tx_no = 0
        for k, s in enumerate(starts):
            hashes, token = [], None
            while True:
                body = {"account_id": fc, "is_event_log": True, "from_tx_block_height": s,
                        "to_tx_block_height": s + w - 1, "limit": 200, "desc": False}
                if token:
                    body["resume_token"] = token
                d = client.post_json(f"{base}/v0/account", body, immutable=True)
                rows = d.get("account_txs") or []
                hashes += [r["transaction_hash"] for r in rows]
                token = d.get("resume_token")
                if len(rows) < 200 or not token:
                    break
            hashes = list(dict.fromkeys(hashes))
            n_in = 0
            for i in range(0, len(hashes), 20):
                txs = client.post_json(f"{base}/v0/transactions", {"tx_hashes": hashes[i:i + 20]},
                                       immutable=True).get("transactions") or []
                for t in txs:
                    legs = legs_of_tx(t, day, k, verifier)
                    tx_rows.append({"day": day, "window": k, "tx_no": tx_no, "tx_hash": t["transaction"]["hash"],
                                    "block_height": int(t["execution_outcome"]["block_height"]), "legs": len(legs)})
                    for lg in legs:
                        leg_rows.append({"day": day, "tx_no": tx_no, **{c: lg[c] for c in (
                            "event_index", "account_id", "token_id", "amount", "fee_collected", "referral")}})
                    tx_no += 1
                    n_in += 1
            win_rows.append({"day": day, "window": k, "window_start": s, "window_blocks": w,
                             "fee_paying_txs_listed": len(hashes), "txs_fetched": n_in})
        # control sample: every transaction touching intents.near in a few short windows (any method, any signer)
        wc = max(1, round(int(cfg["control_txs_per_window"]) * (h1 - h0) / max(n_int, 1)))
        rngc = np.random.default_rng([seed, int(day.replace("-", "")), 6])
        for k, s in enumerate(sorted(int(x) for x in rngc.integers(h0, max(h0 + 1, h1 - wc),
                                                                    size=int(cfg["control_windows_per_day"])))):
            d = client.post_json(f"{base}/v0/account", {"account_id": verifier, "is_real_receiver": True,
                                                        "from_tx_block_height": s, "to_tx_block_height": s + wc - 1,
                                                        "limit": 200, "desc": False}, immutable=True)
            hashes = list(dict.fromkeys(r["transaction_hash"] for r in d.get("account_txs") or []))
            for i in range(0, len(hashes), 20):
                for t in client.post_json(f"{base}/v0/transactions", {"tx_hashes": hashes[i:i + 20]},
                                          immutable=True).get("transactions") or []:
                    logs = [lg for rc in t.get("receipts") or [] for lg in rc["execution_outcome"]["outcome"]["logs"]]
                    legs = legs_of_tx(t, day, k, verifier)
                    ctl_rows.append({"day": day, "window": k, "window_start": s, "window_blocks": wc,
                                     "tx_hash": t["transaction"]["hash"],
                                     "methods": "|".join(a["FunctionCall"]["method_name"] for a in t["transaction"]["actions"]
                                                         if isinstance(a, dict) and "FunctionCall" in a),
                                     "token_diff_legs": len(legs),
                                     "legs_with_fee": sum(1 for x in legs if x["fee_collected"] not in ("", "0")),
                                     "fee_collector_in_logs": any(fc in lg for lg in logs)})
        print(f"  intents {day}: heights {h0}-{h1}, {n_fee} fee-paying txs, {len(toks)} fee tokens, "
              f"{sum(1 for r in tx_rows if r['day'] == day)} sampled txs, {sum(1 for r in leg_rows if r['day'] == day)} legs", file=sys.stderr, flush=True)

    stats = client.stats_for("tx.main.fastnear.com", "archival-rpc.mainnet.fastnear.com")
    design = {"days": days, "seed": seed, **{k: cfg[k] for k in cfg}}
    manifest.save_table("fastnear_tx", "intents_days", pl.DataFrame(day_rows, infer_schema_length=None),
                        urls=[f"{base}/v0/blocks", f"{base}/v0/account", f"{arc.url} call_function {verifier}"],
                        params=design, sort_by=["day"],
                        notes="Sampled UTC days: height range, census counts (fee-paying txs = txs whose event logs name "
                              "the fee collector), protocol fee in pips at both ends.", http_stats=stats)
    manifest.save_table("rpc_archival", "intents_fee_collector_balances", pl.DataFrame(bal_rows, infer_schema_length=None),
                        urls=[f"{arc.url} call_function {verifier} mt_batch_balance_of"], params=design,
                        sort_by=["day", "token_id"],
                        notes="Fee collector NEP-245 balances inside intents.near at the first block of the day and of "
                              "the next day (raw token units).", http_stats=stats)
    manifest.save_table("fastnear_tx", "intents_windows", pl.DataFrame(win_rows, infer_schema_length=None),
                        urls=[f"{base}/v0/account"], params=design, sort_by=["day", "window"],
                        notes="Sampled windows of consecutive blocks per day: start height, length, number of "
                              "fee-paying transactions listed and fetched.", http_stats=stats)
    manifest.save_table("fastnear_tx", "intents_swap_txs", pl.DataFrame(tx_rows, infer_schema_length=None),
                        urls=[f"{base}/v0/transactions"], params=design, sort_by=["day", "tx_no"],
                        notes="Every sampled fee-paying transaction: window, hash, block height, number of token_diff "
                              "legs (0 = it paid a fee without a successful token_diff of intents.near).",
                        http_stats=stats)
    manifest.save_table("fastnear_tx", "intents_control_txs", pl.DataFrame(ctl_rows, infer_schema_length=None),
                        urls=[f"{base}/v0/account", f"{base}/v0/transactions"], params=design,
                        sort_by=["day", "window", "tx_hash"],
                        notes="Control sample: every transaction in which intents.near receives a receipt, in a few "
                              "short windows per day; whether it has token_diff legs and whether the fee collector "
                              "appears in its logs (tests that the fee-paying frame contains all swaps).",
                        http_stats=stats)
    lschema = {"day": pl.Utf8, "tx_no": pl.Int64, "event_index": pl.Int64, "account_id": pl.Utf8, "token_id": pl.Utf8,
               "amount": pl.Utf8, "fee_collected": pl.Utf8, "referral": pl.Utf8}
    manifest.save_table("fastnear_tx", "intents_swap_legs", pl.DataFrame(leg_rows, schema=lschema),
                        urls=[f"{base}/v0/transactions"], params=design,
                        sort_by=["day", "tx_no", "event_index", "account_id", "token_id"],
                        notes="One row per token leg of every DIP-4 token_diff event of the sampled transactions "
                              "(tx_no -> intents_swap_txs.csv; amount signed, raw units; fee_collected = protocol fee "
                              "charged on that token in that event).", http_stats=stats)

    # token list and prices -----------------------------------------------------------------------------------
    tl = client.get_json(ONECLICK_TOKENS)
    tdf = pl.DataFrame([{k: str(t.get(k, "")) for k in ("assetId", "decimals", "blockchain", "symbol", "coingeckoId",
                                                         "contractAddress")} for t in tl])
    manifest.save_table("oneclick", "tokens", tdf, urls=[ONECLICK_TOKENS], sort_by=["assetId"],
                        notes="Public 1Click token list (no JWT needed for this endpoint): asset id, decimals, symbol, "
                              "CoinGecko id. Current prices in the response are not kept.",
                        http_stats=client.stats_for("1click.chaindefuser.com"))
    ids = sorted({t for t in tdf["coingeckoId"].to_list() if t and t != "None"})
    prows = []
    llama = config.load()["endpoints"]["llama_coins"]
    for day in days:
        ts = int(dt.datetime.combine(dt.date.fromisoformat(day), dt.time(12), dt.UTC).timestamp())
        for i in range(0, len(ids), 40):
            coins = ",".join(f"coingecko:{x}" for x in ids[i:i + 40])
            d = client.get_json(f"{llama}/prices/historical/{ts}/{coins}", immutable=True)
            for k, v in (d.get("coins") or {}).items():
                prows.append({"day": day, "coin": k, "price_usd": float(v["price"]), "timestamp": int(v["timestamp"]),
                              "confidence": float(v.get("confidence") or 0)})
    manifest.save_table("defillama", "coin_prices_intents_days", pl.DataFrame(prows, infer_schema_length=None),
                        urls=[f"{llama}/prices/historical/<ts>/<coins>"], params={"days": days, "at": "12:00 UTC"},
                        sort_by=["day", "coin"], notes="DefiLlama historical prices for the CoinGecko ids of the 1Click "
                                                       "token list, at noon UTC of each sampled day.",
                        http_stats=client.stats_for("coins.llama.fi"))


def legs_of_tx(t: dict, day: str, window: int, verifier: str) -> list[dict]:
    out, idx = [], 0
    for rc in t.get("receipts") or []:
        oc = rc["execution_outcome"]["outcome"]
        if oc.get("executor_id") != verifier:
            continue
        st = oc.get("status") or {}
        if not ("SuccessValue" in st or "SuccessReceiptId" in st):
            continue
        for lg in oc.get("logs") or []:
            if not lg.startswith("EVENT_JSON:"):
                continue
            try:
                e = json.loads(lg[len("EVENT_JSON:"):])
            except ValueError:
                continue
            if e.get("standard") != "dip4" or e.get("event") != "token_diff":
                continue
            for d in e.get("data") or []:
                fees = d.get("fees_collected") or {}
                for tok, amt in (d.get("diff") or {}).items():
                    out.append({"day": day, "window": window, "tx_hash": t["transaction"]["hash"],
                                "block_height": int(rc["execution_outcome"]["block_height"]), "event_index": idx,
                                "account_id": d.get("account_id", ""), "token_id": tok, "amount": str(amt),
                                "fee_collected": str(fees.get(tok, "")), "referral": d.get("referral") or ""})
                idx += 1
    return out
