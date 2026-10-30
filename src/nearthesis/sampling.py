"""Signer draw design shared by the fetcher (which signers to look up) and the offline analysis (how to weight them).

Population: the transactions of one calendar month (UTC). Stage 1 (phase 1 + phase 2a): blocks drawn uniformly by
height inside the month (`block_sample_blocks.csv`, plus `block_sample_extra_blocks.csv` for recent months); every
transaction of a sampled block is kept, so every transaction of the month has the same inclusion probability.
Stage 2 (here): `n` transactions drawn without replacement, uniformly, from the pooled stage-1 transactions of the
month. Each draw is therefore an equal-probability draw from the month's transactions, clustered by block; the
analysis bootstraps over blocks. The draw order is a seeded permutation, so the first k draws are themselves a uniform
subsample (used to decide which draws also get method-level details).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl

from . import io

EXTRA_DRAW_OFFSET = 1000  # block keys of the extra sample are draw + 1000, so (month, block_key) is unique


def load_block_sample(raw: Path) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Base + extra block samples as (blocks, txs) with a unique `block_key` per sampled block within a month."""
    d = raw / "fastnear_tx"
    parts_b, parts_t = [], []
    for name, off in (("block_sample", 0), ("block_sample_extra", EXTRA_DRAW_OFFSET)):
        bp, tp = d / f"{name}_blocks.csv", d / f"{name}_txs.csv"
        if not bp.exists():
            continue
        b = io.read_csv(bp).with_columns((pl.col("draw").cast(pl.Int64) + off).alias("block_key"),
                                         pl.lit(name).alias("sample"))
        t = io.read_csv(tp).with_columns((pl.col("draw").cast(pl.Int64) + off).alias("block_key"),
                                         pl.lit(name).alias("sample"))
        parts_b.append(b.select("month", "block_key", "sample", pl.col("block_height").cast(pl.Int64),
                                pl.col("block_timestamp_ns").cast(pl.Int64), pl.col("num_transactions").cast(pl.Int64)))
        parts_t.append(t.select("month", "block_key", "sample", pl.col("block_height").cast(pl.Int64),
                                pl.col("tx_index").cast(pl.Int64), "signer_id", "receiver_id", "real_signer_id",
                                "real_receiver_id", (pl.col("is_relayed") == "true").alias("is_relayed"),
                                "transaction_hash"))
    return pl.concat(parts_b), pl.concat(parts_t)


def draws_per_month(month: str, cfg: dict) -> int:
    return int(cfg["draws_recent"] if month >= cfg["recent_first_month"] else cfg["draws_early"])


def draw_signers(blocks: pl.DataFrame, txs: pl.DataFrame, cfg: dict, seed: int) -> pl.DataFrame:
    """Seeded stage-2 draws: one row per drawn transaction, with its block timestamp and draw rank."""
    ts = blocks.select("month", "block_key", "block_timestamp_ns")
    out = []
    for month in sorted(txs["month"].unique().to_list()):
        pool = txs.filter(pl.col("month") == month).sort(["block_key", "tx_index"])
        n = min(draws_per_month(month, cfg), pool.height)
        rng = np.random.default_rng([seed, int(month.replace("-", "")), 3])
        order = rng.permutation(pool.height)[:n]
        picked = pool[order.tolist()].with_columns(pl.Series("draw_rank", np.arange(n), dtype=pl.Int64))
        out.append(picked)
    d = pl.concat(out).join(ts, on=["month", "block_key"], how="left")
    return d.select("month", "draw_rank", "block_key", "sample", "block_height", "block_timestamp_ns", "tx_index",
                    "transaction_hash", "real_signer_id", "real_receiver_id", "is_relayed").sort(["month", "draw_rank"])
