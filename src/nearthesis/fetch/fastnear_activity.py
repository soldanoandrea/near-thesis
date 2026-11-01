"""Activity composition inputs from the FastNear Transactions API (source #5) and archival RPC (source #2).

1. month_boundaries: first block with timestamp >= 00:00 UTC of each month (interpolation search on /v0/blocks).
2. monthly_receiver_counts: exact monthly counts of transactions whose *real* receiver is a tracked contract
   (txs_count of /v0/account with is_real_receiver=true over the month's height range).
3. block_sample_*: stratified random block sample, `blocks_per_month` uniform heights per month (seeded),
   every transaction of each sampled block (/v0/block with_transactions=true). Input for the HOT / relayer /
   implicit-vs-named decomposition with bootstrap confidence intervals (PIANO.md Q1, section 3.1).
4. treasury_monthly: archival view_account of tracked treasury / buyback wallets at each month boundary.

API quirks handled here (see docs/DATA_NOTES.md): `to_*_height` bounds are inclusive although the OpenAPI says
exclusive; /v0/blocks needs desc=false for ascending order; a skipped height returns {"block": null}.
"""

from __future__ import annotations

import datetime as dt
import sys

import numpy as np
import polars as pl

from .. import config, manifest
from ..http import PoliteClient, RpcError
from .rpc_epochs import Archival

HOST = "tx.main.fastnear.com"


class TxApi:
    def __init__(self, client: PoliteClient):
        self.c = client
        self.base = config.load()["endpoints"]["fastnear_tx"]

    def blocks(self, frm: int, to: int, limit: int) -> list[dict]:
        d = self.c.post_json(f"{self.base}/v0/blocks",
                             {"from_block_height": frm, "to_block_height": to, "limit": limit, "desc": False},
                             immutable=True)
        return d.get("blocks") or []

    def first_at_or_after(self, h: int, window: int = 5000) -> tuple[int, int] | None:
        b = self.blocks(h, h + window, 1)
        return (int(b[0]["block_height"]), int(b[0]["block_timestamp"])) if b else None

    def latest(self) -> tuple[int, int]:
        d = self.c.post_json(f"{self.base}/v0/blocks", {"desc": True, "limit": 1})
        b = d["blocks"][0]
        return int(b["block_height"]), int(b["block_timestamp"])

    def height_at(self, t_ns: int, lo: tuple[int, int], hi: tuple[int, int]) -> tuple[int, int]:
        """First block (height, ts) with ts >= t_ns. Invariant: lo.ts < t_ns <= hi.ts, both existing blocks.

        hi_h is a height bound: no block exists in [hi_h, hi.height), so the answer is hi or lies in (lo, hi_h).
        """
        hi_h = hi[0]
        it = 0
        while hi_h - lo[0] > 100:
            it += 1
            if it % 3 == 0:  # bisection step guards against poor interpolation
                g = (lo[0] + hi_h) // 2
            else:
                g = lo[0] + int((t_ns - lo[1]) / max(1, hi[1] - lo[1]) * (hi_h - lo[0]))
            g = min(max(g, lo[0] + 1), hi_h - 1)
            r = self.first_at_or_after(g, window=hi_h - g)
            if r is None or r[0] >= hi_h:
                hi_h = g
            elif r[1] >= t_ns:
                hi, hi_h = r, r[0]
            else:
                lo = r
        h = lo[0] + 1
        while h < hi_h:
            rows = self.blocks(h, hi_h - 1, 100)
            for b in rows:
                if int(b["block_timestamp"]) >= t_ns:
                    return int(b["block_height"]), int(b["block_timestamp"])
            if not rows:
                break
            h = int(rows[-1]["block_height"]) + 1
        return hi

    def block_with_txs(self, h: int, max_skip: int = 50) -> dict:
        for x in range(h, h + max_skip):
            d = self.c.post_json(f"{self.base}/v0/block", {"block_id": x, "with_transactions": True}, immutable=True)
            if d.get("block"):
                return d
        raise RuntimeError(f"no block in [{h}, {h + max_skip})")

    def receiver_count(self, account: str, frm: int, to_incl: int) -> int:
        d = self.c.post_json(f"{self.base}/v0/account",
                             {"account_id": account, "is_real_receiver": True, "from_tx_block_height": frm,
                              "to_tx_block_height": to_incl, "limit": 1}, immutable=True)
        return int(d["txs_count"])


def month_starts(first: str, now: dt.datetime) -> list[dt.datetime]:
    y, m = map(int, first.split("-"))
    out = []
    while True:
        d = dt.datetime(y, m, 1, tzinfo=dt.UTC)
        if d >= now:
            break
        out.append(d)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _ns(d: dt.datetime) -> int:
    return int(d.timestamp()) * 1_000_000_000


def fetch(client: PoliteClient) -> None:
    cfg = config.load()
    act = cfg["activity"]
    api = TxApi(client)
    now = dt.datetime.now(dt.UTC)
    end_of_window = dt.datetime(now.year, now.month, now.day, tzinfo=dt.UTC)  # today 00:00 UTC (exclusive end)
    starts = month_starts(act["first_month"], end_of_window)
    bounds_t = starts + [end_of_window]

    # 1. month boundaries ---------------------------------------------------------------------------------
    # Boundaries are immutable facts: when the committed file already has exactly the wanted boundaries, reuse it.
    from .. import io, paths

    wanted = [d.strftime("%Y-%m-%dT%H:%M:%SZ") for d in bounds_t]
    prev = paths.RAW / "fastnear_tx" / "month_boundaries.csv"
    if prev.exists() and io.read_csv(prev)["boundary_utc"].to_list() == wanted:
        old = io.read_csv(prev)
        boundaries = [(b, int(h), int(t)) for b, h, t in old.iter_rows()]
        print("  reusing committed month_boundaries.csv (same boundaries)", file=sys.stderr)
        fresh = False
    else:
        # Reuse the committed month starts (immutable); search only the ones that are new, such as the boundary of a
        # month that has ended since the last refresh and the new fetch day. The old last row (a fetch day, not a
        # month start) is not reused.
        known = {}
        if prev.exists():
            old_rows = list(io.read_csv(prev).iter_rows())[:-1]
            known = {b: (int(h), int(t)) for b, h, t in old_rows}
        genesis_h = int(cfg["archival_epochs"]["genesis_height"])
        lo = api.first_at_or_after(genesis_h)
        hi = api.latest()
        boundaries = []
        for d in bounds_t:
            key = d.strftime("%Y-%m-%dT%H:%M:%SZ")
            if key in known:
                h, t = known[key]
                boundaries.append((key, h, t))
                lo = (h, t)
                continue
            h, t = api.height_at(_ns(d), lo, hi)
            boundaries.append((d.strftime("%Y-%m-%dT%H:%M:%SZ"), h, t))
            lo = (h, t)  # t < next boundary, so it is a valid lower anchor for the next search
            print(f"  boundary {d:%Y-%m-%d} -> height {h}", file=sys.stderr, flush=True)
        fresh = True
    bdf = pl.DataFrame([(b, h, str(t)) for b, h, t in boundaries],
                       schema={"boundary_utc": pl.Utf8, "height": pl.Int64, "block_timestamp_ns": pl.Utf8}, orient="row")
    if fresh:
        manifest.save_table("fastnear_tx", "month_boundaries", bdf, urls=[f"{api.base}/v0/blocks"],
                            sort_by=["boundary_utc"],
                            notes="First block whose timestamp is >= the boundary (00:00 UTC on the 1st of each month; "
                                  "the last row is 00:00 UTC of the fetch day and closes the final, partial month).",
                            http_stats=client.stats_for(HOST))

    strata = [(b0[:7], h0, h1) for (b0, h0, _), (_, h1, _) in zip(boundaries[:-1], boundaries[1:])]

    # 2. exact monthly receiver counts ----------------------------------------------------------------------
    rows = []
    for month, h0, h1 in strata:
        for acc in act["receivers"]:
            rows.append((month, acc, h0, h1 - 1, api.receiver_count(acc, h0, h1 - 1)))
        print(f"  receiver counts {month}", file=sys.stderr, flush=True)
    df = pl.DataFrame(rows, schema={"month": pl.Utf8, "account_id": pl.Utf8, "from_height": pl.Int64,
                                    "to_height_inclusive": pl.Int64, "txs_count": pl.Int64}, orient="row")
    manifest.save_table("fastnear_tx", "monthly_receiver_counts", df, urls=[f"{api.base}/v0/account"],
                        params={"is_real_receiver": True, "limit": 1, "accounts": act["receivers"]},
                        sort_by=["month", "account_id"],
                        notes="txs_count = number of transactions in the month whose real receiver (relayer "
                              "unwrapped) is the account. Exact count from the FastNear ClickHouse index.",
                        http_stats=client.stats_for(HOST))

    # 3. stratified block sample ----------------------------------------------------------------------------
    n = int(act["blocks_per_month"])
    seed = int(act["seed"])
    brows, trows = [], []
    for month, h0, h1 in strata:
        rng = np.random.default_rng([seed, int(month.replace("-", ""))])
        draws = sorted(int(x) for x in rng.integers(h0, h1, size=n))
        for k, h in enumerate(draws):
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
        print(f"  block sample {month}: {len(trows)} txs so far", file=sys.stderr, flush=True)
    design = {"blocks_per_month": n, "seed": seed, "rng": "numpy.random.default_rng([seed, yyyymm]).integers(h0, h1)",
              "skipped_height_rule": "next existing height"}
    bdf = pl.DataFrame(brows, schema={"month": pl.Utf8, "draw": pl.Int64, "sampled_height": pl.Int64,
                                      "block_height": pl.Int64, "block_timestamp_ns": pl.Utf8,
                                      "num_transactions": pl.Int64, "num_receipts": pl.Int64, "gas_burnt": pl.Utf8,
                                      "tokens_burnt_yocto": pl.Utf8, "total_supply_yocto": pl.Utf8,
                                      "protocol_version": pl.Int64, "chunks_included": pl.Int64}, orient="row")
    manifest.save_table("fastnear_tx", "block_sample_blocks", bdf, urls=[f"{api.base}/v0/block"], params=design,
                        sort_by=["month", "draw"], notes="One row per sampled block (including empty blocks).",
                        http_stats=client.stats_for(HOST))
    tdf = pl.DataFrame(trows, schema={"month": pl.Utf8, "draw": pl.Int64, "block_height": pl.Int64,
                                      "tx_index": pl.Int64, "shard_id": pl.Int64, "signer_id": pl.Utf8,
                                      "receiver_id": pl.Utf8, "real_signer_id": pl.Utf8, "real_receiver_id": pl.Utf8,
                                      "is_relayed": pl.Boolean, "is_success": pl.Boolean, "gas_burnt": pl.Utf8,
                                      "tokens_burnt_yocto": pl.Utf8, "transaction_hash": pl.Utf8}, orient="row")
    manifest.save_table("fastnear_tx", "block_sample_txs", tdf, urls=[f"{api.base}/v0/block"], params=design,
                        sort_by=["month", "draw", "tx_index"],
                        notes="Every transaction of every sampled block. Public on-chain account IDs.",
                        http_stats=client.stats_for(HOST))


def fetch_treasury(client: PoliteClient) -> None:
    """Archival view_account of tracked wallets at month boundaries (needs month_boundaries.csv from `fetch`)."""
    from .. import io, paths

    cfg = config.load()
    tre = cfg["treasury"]
    arc = Archival(client)
    bdf = io.read_csv(paths.RAW / "fastnear_tx" / "month_boundaries.csv")
    rows = []
    for boundary, height in zip(bdf["boundary_utc"], bdf["height"].cast(pl.Int64)):
        if boundary[:7] < tre["first_month"]:
            continue
        for acc in tre["accounts"]:
            try:
                va = arc.call("query", {"request_type": "view_account", "block_id": int(height), "account_id": acc})
                rows.append((boundary, int(height), acc, va["amount"], va["locked"], True))
            except RpcError as exc:
                if exc.cause != "UNKNOWN_ACCOUNT":
                    raise
                rows.append((boundary, int(height), acc, None, None, False))
    df = pl.DataFrame(rows, schema={"boundary_utc": pl.Utf8, "block_height": pl.Int64, "account_id": pl.Utf8,
                                    "amount_yocto": pl.Utf8, "locked_yocto": pl.Utf8, "exists": pl.Boolean},
                      orient="row")
    manifest.save_table("rpc_archival", "treasury_monthly", df, urls=[f"{arc.url} query view_account"],
                        params={"accounts": tre["accounts"], "first_month": tre["first_month"]},
                        sort_by=["boundary_utc", "account_id"],
                        notes="Balances at the first block of each month (from fastnear_tx/month_boundaries.csv). "
                              "exists=false: account not yet created at that height.",
                        http_stats=client.stats_for("archival-rpc.mainnet.fastnear.com"))
