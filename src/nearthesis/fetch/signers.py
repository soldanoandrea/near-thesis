"""Per-signer histories for the bot-vs-human decomposition (PIANO.md Q1, phase 2a). FastNear Transactions API, keyless.

1. Widen the block sample of recent months (`block_sample_extra_*.csv`): `extra_blocks_per_month` more uniform heights
   per month from `extra_first_month`, seed stream [seed, yyyymm, 2], same schema as the phase-1 sample.
2. Draw transactions from the pooled block sample (`nearthesis.sampling.draw_signers`, seeded, offline-reproducible).
3. For each drawn transaction's real signer:
   a. `signer_month_activity.csv`: /v0/account {is_real_signer, month height range, limit 200, desc} -> exact count
      of transactions the account really signed that month (`txs_count`) and the timestamps of up to 200 of them
      (the most recent), delta-encoded (first unix second + gaps) to keep the snapshot small;
   b. `signer_lifetime.csv`, for the first `lifetime_draws` draws of a month: first appearance in any role
      (/v0/account desc=false, limit 1: account creation or first funding) and, for signers whose first appearance
      falls in the drawn month (new accounts), the last transaction they really signed up to the fetch
      (/v0/account is_real_signer desc, limit 1) for cohort retention;
   c. `signer_tx_details.csv`: for the first `detail_draws` draws of a month, if the signer signed at least
      `detail_min_txs` transactions, receiver / method / action kinds of its `detail_txs` most recent transactions of
      the month (/v0/transactions, 20 hashes per call).
Public on-chain account ids only. Quirks (docs/DATA_NOTES.md): /v0/account returns newest first unless desc=false is
sent (the OpenAPI spec says the opposite), and `to_tx_block_height` is inclusive.
"""

from __future__ import annotations

import sys
import time

import numpy as np
import polars as pl

from .. import config, io, manifest, paths, sampling
from ..http import PoliteClient
from .fastnear_activity import TxApi

HOST = "tx.main.fastnear.com"
FRESH_S = 7 * 86400  # mutable lifetime queries are reused from the cache for a week (resumable runs)


def _boundaries() -> list[tuple[str, int, int]]:
    b = io.read_csv(paths.RAW / "fastnear_tx" / "month_boundaries.csv")
    rows = [(r[0][:7], int(r[1])) for r in b.select("boundary_utc", "height").iter_rows()]
    return [(m0, h0, h1) for (m0, h0), (_, h1) in zip(rows[:-1], rows[1:])]


def fetch_extra_blocks(client: PoliteClient) -> None:
    cfg, act = config.load()["signers"], config.load()["activity"]
    api = TxApi(client)
    n, seed = int(cfg["extra_blocks_per_month"]), int(act["seed"])
    brows, trows = [], []
    for month, h0, h1 in _boundaries():
        if month < cfg["extra_first_month"]:
            continue
        rng = np.random.default_rng([seed, int(month.replace("-", "")), 2])
        for k, h in enumerate(sorted(int(x) for x in rng.integers(h0, h1, size=n))):
            d = api.block_with_txs(h)
            b = d["block"]
            brows.append((month, k, h, int(b["block_height"]), str(b["block_timestamp"]), int(b["num_transactions"]),
                          int(b["num_receipts"]), str(b["gas_burnt"]), str(b["tokens_burnt"]), str(b["total_supply"]),
                          int(b["protocol_version"]), int(b["chunks_included"])))
            for t in d.get("block_txs") or []:
                trows.append((month, k, int(b["block_height"]), int(t["tx_index"]), int(t["shard_id"]),
                              t["signer_id"], t["receiver_id"], t["real_signer_id"], t["real_receiver_id"],
                              bool(t["is_relayed"]), bool(t["is_success"]), str(t["gas_burnt"]),
                              str(t["tokens_burnt"]), t["transaction_hash"]))
        print(f"  extra block sample {month}: {len(trows)} txs so far", file=sys.stderr, flush=True)
    design = {"blocks_per_month": n, "seed": seed, "first_month": cfg["extra_first_month"],
              "rng": "numpy.random.default_rng([seed, yyyymm, 2]).integers(h0, h1)",
              "skipped_height_rule": "next existing height"}
    bdf = pl.DataFrame(brows, schema={"month": pl.Utf8, "draw": pl.Int64, "sampled_height": pl.Int64,
                                      "block_height": pl.Int64, "block_timestamp_ns": pl.Utf8,
                                      "num_transactions": pl.Int64, "num_receipts": pl.Int64, "gas_burnt": pl.Utf8,
                                      "tokens_burnt_yocto": pl.Utf8, "total_supply_yocto": pl.Utf8,
                                      "protocol_version": pl.Int64, "chunks_included": pl.Int64}, orient="row")
    manifest.save_table("fastnear_tx", "block_sample_extra_blocks", bdf, urls=[f"{api.base}/v0/block"], params=design,
                        sort_by=["month", "draw"],
                        notes="Phase 2a widening of the stratified block sample for recent months (independent seed "
                              "stream; pooled with block_sample_blocks.csv in the analysis).",
                        http_stats=client.stats_for(HOST))
    tdf = pl.DataFrame(trows, schema={"month": pl.Utf8, "draw": pl.Int64, "block_height": pl.Int64,
                                      "tx_index": pl.Int64, "shard_id": pl.Int64, "signer_id": pl.Utf8,
                                      "receiver_id": pl.Utf8, "real_signer_id": pl.Utf8, "real_receiver_id": pl.Utf8,
                                      "is_relayed": pl.Boolean, "is_success": pl.Boolean, "gas_burnt": pl.Utf8,
                                      "tokens_burnt_yocto": pl.Utf8, "transaction_hash": pl.Utf8}, orient="row")
    manifest.save_table("fastnear_tx", "block_sample_extra_txs", tdf, urls=[f"{api.base}/v0/block"], params=design,
                        sort_by=["month", "draw", "tx_index"],
                        notes="Every transaction of every extra sampled block. Public on-chain account IDs.",
                        http_stats=client.stats_for(HOST))


def parse_tx(t: dict) -> dict:
    """Receiver, real receiver (inside a delegate action), method names and action kinds of one transaction."""
    tr = t["transaction"]
    kinds, methods, real_recv, relayed = [], [], tr["receiver_id"], False
    for a in tr["actions"]:
        if isinstance(a, str):
            kinds.append(a)
            continue
        (k, v), = a.items()
        if k == "Delegate":
            relayed = True
            da = v.get("delegate_action", v)
            real_recv = da.get("receiver_id", real_recv)
            for ia in da.get("actions", []):
                ia = ia.get("action", ia) if isinstance(ia, dict) else ia
                if isinstance(ia, str):
                    kinds.append(ia)
                    continue
                (ik, iv), = ia.items()
                kinds.append(ik)
                if ik == "FunctionCall":
                    methods.append(iv.get("method_name", ""))
            continue
        kinds.append(k)
        if k == "FunctionCall":
            methods.append(v.get("method_name", ""))
    return {"tx_hash": tr["hash"], "outer_signer_id": tr["signer_id"], "receiver_id": tr["receiver_id"],
            "real_receiver_id": real_recv, "is_relayed": relayed, "methods": "|".join(methods),
            "action_kinds": "|".join(kinds), "block_height": int(t["execution_outcome"]["block_height"])}


def fetch(client: PoliteClient) -> None:
    cfg, seed = config.load()["signers"], int(config.load()["activity"]["seed"])
    api = TxApi(client)
    base = api.base
    bounds = {m: (h0, h1) for m, h0, h1 in _boundaries()}
    blocks, txs = sampling.load_block_sample(paths.RAW)
    draws = sampling.draw_signers(blocks, txs, cfg, seed)
    print(f"  {draws.height} draws, {draws['real_signer_id'].n_unique()} distinct signers", file=sys.stderr)

    month_rows: dict[tuple[str, str], dict] = {}
    first_rows: dict[str, dict] = {}
    last_rows: dict[str, dict] = {}
    detail_rows: dict[tuple[str, str, str], dict] = {}
    t0 = time.time()
    months = sorted(draws["month"].unique().to_list(), reverse=True)  # most recent first
    for month in months:
        h0, h1 = bounds[month]
        m0_s = None
        for r in draws.filter(pl.col("month") == month).sort("draw_rank").iter_rows(named=True):
            s = r["real_signer_id"]
            key = (s, month)
            if key not in month_rows:
                d = client.post_json(f"{base}/v0/account",
                                     {"account_id": s, "is_real_signer": True, "from_tx_block_height": h0,
                                      "to_tx_block_height": h1 - 1, "limit": 200, "desc": True}, immutable=True)
                rows = d.get("account_txs") or []
                ts = sorted(int(x["tx_block_timestamp"]) // 1_000_000_000 for x in rows)
                month_rows[key] = {
                    "signer_id": s, "month": month, "from_height": h0, "to_height_inclusive": h1 - 1,
                    "txs_count": int(d["txs_count"]), "rows_returned": len(rows),
                    "ts_first_s": ts[0] if ts else None,
                    "ts_gaps_s": " ".join(str(b - a) for a, b in zip(ts[:-1], ts[1:])),
                    "recent_hashes": [x["transaction_hash"] for x in rows[: int(cfg["detail_txs"])]],
                }
            if s not in first_rows and r["draw_rank"] < int(cfg["lifetime_draws"]):
                d = client.post_json(f"{base}/v0/account", {"account_id": s, "limit": 1, "desc": False},
                                     immutable=True)
                rows = d.get("account_txs") or []
                first_rows[s] = {"signer_id": s, "lifetime_txs_any_role": int(d["txs_count"]),
                                 "first_height": int(rows[0]["tx_block_height"]) if rows else None,
                                 "first_timestamp_s": int(rows[0]["tx_block_timestamp"]) // 1_000_000_000 if rows else None}
            fr = first_rows.get(s, {"first_height": None})
            is_new = fr["first_height"] is not None and h0 <= fr["first_height"] < h1
            if is_new and s not in last_rows and r["draw_rank"] < int(cfg["lifetime_draws"]):
                d = client.post_json(f"{base}/v0/account", {"account_id": s, "is_real_signer": True, "limit": 1,
                                                            "desc": True}, max_age_s=FRESH_S)
                rows = d.get("account_txs") or []
                last_rows[s] = {"signer_id": s, "lifetime_txs_real_signer": int(d["txs_count"]),
                                "last_signed_height": int(rows[0]["tx_block_height"]) if rows else None,
                                "last_signed_timestamp_s": int(rows[0]["tx_block_timestamp"]) // 1_000_000_000 if rows else None}
            mr = month_rows[key]
            if r["draw_rank"] < int(cfg["detail_draws"]) and mr["txs_count"] >= int(cfg["detail_min_txs"]):
                need = [h for h in mr["recent_hashes"] if (s, month, h) not in detail_rows]
                for i in range(0, len(need), 20):
                    d = client.post_json(f"{base}/v0/transactions", {"tx_hashes": need[i:i + 20]}, immutable=True)
                    for t in d.get("transactions") or []:
                        p = parse_tx(t)
                        detail_rows[(s, month, p["tx_hash"])] = {"signer_id": s, "month": month, **p}
        done = months.index(month) + 1
        print(f"  signers {month}: {len(month_rows)} signer-months, {len(first_rows)} signers, {len(last_rows)} new, "
              f"{len(detail_rows)} detail txs ({done}/{len(months)} months, {time.time() - t0:.0f}s)",
              file=sys.stderr, flush=True)

    stats = client.stats_for(HOST)
    design = {"draws_recent": cfg["draws_recent"], "draws_early": cfg["draws_early"],
              "lifetime_draws": cfg["lifetime_draws"], "detail_draws": cfg["detail_draws"],
              "recent_first_month": cfg["recent_first_month"], "seed": seed,
              "rng": "numpy.random.default_rng([seed, yyyymm, 3]).permutation(pooled block-sample txs)"}
    mdf = pl.DataFrame([{k: v for k, v in r.items() if k != "recent_hashes"} for r in month_rows.values()],
                       schema={"signer_id": pl.Utf8, "month": pl.Utf8, "from_height": pl.Int64,
                               "to_height_inclusive": pl.Int64, "txs_count": pl.Int64, "rows_returned": pl.Int64,
                               "ts_first_s": pl.Int64, "ts_gaps_s": pl.Utf8})
    manifest.save_table("fastnear_tx", "signer_month_activity", mdf, urls=[f"{base}/v0/account"], params=design,
                        sort_by=["month", "signer_id"],
                        notes="Per drawn (signer, month): exact count of transactions really signed in the month "
                              "(is_real_signer, relayers unwrapped) and the unix-second timestamps of up to 200 of them "
                              "(the most recent), delta-encoded: ts_first_s = earliest returned, ts_gaps_s = "
                              "space-separated gaps in seconds, ascending.", http_stats=stats)
    fdf = pl.DataFrame(list(first_rows.values()), schema={"signer_id": pl.Utf8, "lifetime_txs_any_role": pl.Int64,
                                                          "first_height": pl.Int64, "first_timestamp_s": pl.Int64})
    ldf = pl.DataFrame(list(last_rows.values()), schema={"signer_id": pl.Utf8, "lifetime_txs_real_signer": pl.Int64,
                                                         "last_signed_height": pl.Int64,
                                                         "last_signed_timestamp_s": pl.Int64})
    life = fdf.join(ldf, on="signer_id", how="left")
    manifest.save_table("fastnear_tx", "signer_lifetime", life, urls=[f"{base}/v0/account"], params=design,
                        sort_by=["signer_id"],
                        notes="First appearance in any role (creation / first funding) for every drawn signer; last "
                              "really-signed transaction and lifetime signed count only for signers new in their drawn "
                              "month (cohort retention). Lifetime counts are as of the fetch.", http_stats=stats)
    ddf = pl.DataFrame(list(detail_rows.values()),
                       schema={"signer_id": pl.Utf8, "month": pl.Utf8, "tx_hash": pl.Utf8, "outer_signer_id": pl.Utf8,
                               "receiver_id": pl.Utf8, "real_receiver_id": pl.Utf8, "is_relayed": pl.Boolean,
                               "methods": pl.Utf8, "action_kinds": pl.Utf8, "block_height": pl.Int64})
    manifest.save_table("fastnear_tx", "signer_tx_details", ddf, urls=[f"{base}/v0/transactions"], params=design,
                        sort_by=["month", "signer_id", "block_height", "tx_hash"],
                        notes="Receiver, real receiver (inside Delegate actions), FunctionCall method names and action "
                              "kinds of up to 20 recent txs per detailed (signer, month).", http_stats=stats)
