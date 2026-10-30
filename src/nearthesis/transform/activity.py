"""Q1 first pass: what share of NEAR transactions is HOT / other tracked contracts / relayed / implicit / named.

Two independent inputs:
* census: exact monthly counts of transactions in which a tracked contract is a real receiver of some receipt
  (FastNear txs_count with is_real_receiver: involvement, not only top-level receiver), divided by NearBlocks monthly
  transactions. Counts of different contracts can overlap inside one transaction, so group totals add only
  "primary" contracts (config `activity.groups`); `census_vs_sample.csv` compares each count with the top-level
  share seen in the block sample;
* sample: every transaction of `blocks_per_month` uniformly drawn blocks per month (stratified by month),
  giving shares for things no census exists for (relayed meta-transactions, implicit vs named signers).
Sample shares are ratio estimators over blocks (cluster sample); 90% intervals come from a bootstrap that resamples
blocks within each month (fixed seed, so results are deterministic). Quarterly figures pool months with weights
proportional to each month's block-height range (stratified estimator).

This is a structural decomposition, not a bot score: the per-signer rule-based bot score of PIANO.md Q1 needs
per-signer histories and is phase 2.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import polars as pl

from .. import io

BOOT = 1000
SEED = 20261101
IMPLICIT_NEAR = re.compile(r"^[0-9a-f]{64}$")
IMPLICIT_ETH = re.compile(r"^0x[0-9a-f]{40}$")


def signer_kind(acc: str) -> str:
    if IMPLICIT_NEAR.match(acc):
        return "implicit_near"
    if IMPLICIT_ETH.match(acc):
        return "implicit_eth"
    if acc.endswith(".tg"):
        return "named_tg"
    if acc.endswith(".near"):
        return "named_near"
    return "named_other"


def load_sample(raw: Path, tracked: list[str]) -> tuple[pl.DataFrame, pl.DataFrame]:
    blocks = io.read_csv(raw / "fastnear_tx" / "block_sample_blocks.csv").with_columns(
        pl.col("draw").cast(pl.Int64), pl.col("num_transactions").cast(pl.Int64), pl.col("block_height").cast(pl.Int64))
    txs = io.read_csv(raw / "fastnear_tx" / "block_sample_txs.csv").with_columns(pl.col("draw").cast(pl.Int64))
    txs = txs.with_columns(
        pl.col("real_signer_id").map_elements(signer_kind, return_dtype=pl.Utf8).alias("signer_kind"),
        (pl.col("is_relayed") == "true").alias("relayed"),
        pl.when(pl.col("real_receiver_id").is_in(tracked)).then(pl.col("real_receiver_id"))
        .otherwise(pl.lit("other")).alias("receiver_group"),
    )
    return blocks, txs


# indicator columns evaluated per transaction; shares are sum(indicator) / sum(txs) over sampled blocks
GROUPS: dict[str, list[str]] = {}


def _indicators(txs: pl.DataFrame) -> pl.DataFrame:
    other = pl.col("receiver_group") == "other"
    named = pl.col("signer_kind").str.starts_with("named")
    return txs.with_columns(
        (pl.col("receiver_group") == "game.hot.tg").alias("hot"),
        pl.col("receiver_group").is_in(GROUPS.get("incentivized", [])).alias("incentivized"),
        (pl.col("receiver_group") != "other").alias("tracked"),
        pl.col("relayed").alias("relayed"),
        pl.col("signer_kind").str.starts_with("implicit").alias("implicit_signer"),
        (other & ~pl.col("relayed") & named).alias("other_direct_named"),
        other.alias("other"),
        (other & pl.col("relayed")).alias("other_relayed"),
        (other & pl.col("signer_kind").str.starts_with("implicit")).alias("other_implicit"),
    )


SHARES = ["hot", "incentivized", "tracked", "relayed", "implicit_signer", "other", "other_relayed", "other_implicit",
          "other_direct_named"]
# ratios with a denominator other than all transactions: name -> (numerator, denominator)
CONDITIONAL = {"organic_given_other": ("other_direct_named", "other")}


def _block_matrix(blocks: pl.DataFrame, txs: pl.DataFrame) -> pl.DataFrame:
    """One row per sampled block: total txs and indicator counts (empty blocks kept with zeros)."""
    ind = _indicators(txs)
    agg = ind.group_by(["month", "draw"]).agg([pl.col(c).cast(pl.Int64).sum().alias(c) for c in SHARES])
    m = blocks.select("month", "draw", "num_transactions").join(agg, on=["month", "draw"], how="left")
    return m.with_columns([pl.col(c).fill_null(0) for c in SHARES]).sort(["month", "draw"])


def monthly_sample_shares(blocks: pl.DataFrame, txs: pl.DataFrame) -> pl.DataFrame:
    mat = _block_matrix(blocks, txs)
    rng = np.random.default_rng(SEED)
    rows = []
    for (month,), g in mat.group_by(["month"], maintain_order=True):
        n = g.height
        tot = g["num_transactions"].to_numpy().astype(float)
        idx = rng.integers(0, n, size=(BOOT, n))
        row = {"month": month, "sample_blocks": n, "sample_txs": int(tot.sum()), "sample_tx_per_block": tot.mean()}
        boot_tot = tot[idx].sum(axis=1)
        for c in SHARES:
            x = g[c].to_numpy().astype(float)
            point = x.sum() / tot.sum() if tot.sum() > 0 else None
            with np.errstate(invalid="ignore", divide="ignore"):
                b = x[idx].sum(axis=1) / boot_tot
            b = b[np.isfinite(b)]
            row[f"{c}_share"] = point
            row[f"{c}_share_p05"] = float(np.quantile(b, 0.05)) if point is not None and b.size else None
            row[f"{c}_share_p95"] = float(np.quantile(b, 0.95)) if point is not None and b.size else None
        for name, (num_c, den_c) in CONDITIONAL.items():
            x, y = g[num_c].to_numpy().astype(float), g[den_c].to_numpy().astype(float)
            point = x.sum() / y.sum() if y.sum() > 0 else None
            with np.errstate(invalid="ignore", divide="ignore"):
                b = x[idx].sum(axis=1) / y[idx].sum(axis=1)
            b = b[np.isfinite(b)]
            row[name] = point
            row[f"{name}_p05"] = float(np.quantile(b, 0.05)) if point is not None and b.size else None
            row[f"{name}_p95"] = float(np.quantile(b, 0.95)) if point is not None and b.size else None
        rows.append(row)
    return pl.DataFrame(rows, infer_schema_length=None).sort("month")


def quarterly_sample_shares(blocks: pl.DataFrame, txs: pl.DataFrame, weights: dict[str, float]) -> pl.DataFrame:
    """Stratified (by month) ratio estimator pooled by quarter, weights = block-height range of each month."""
    mat = _block_matrix(blocks, txs).with_columns(
        (pl.col("month").str.slice(0, 4) + "-Q" + ((pl.col("month").str.slice(5, 2).cast(pl.Int64) - 1) // 3 + 1)
         .cast(pl.Utf8)).alias("quarter"))
    rng = np.random.default_rng(SEED + 1)
    rows = []
    for (quarter,), q in mat.group_by(["quarter"], maintain_order=True):
        months = q["month"].unique(maintain_order=True).to_list()
        strata = []
        for mth in months:
            g = q.filter(pl.col("month") == mth)
            strata.append((weights.get(mth, 0.0), g["num_transactions"].to_numpy().astype(float),
                           {c: g[c].to_numpy().astype(float) for c in SHARES}))
        row = {"quarter": quarter, "months": len(months), "sample_blocks": q.height,
               "sample_txs": int(q["num_transactions"].sum())}
        # point estimate: sum_m W_m * mean_m(x) / sum_m W_m * mean_m(tot)
        den = sum(w * t.mean() for w, t, _ in strata)
        boots = []
        for w, t, xs in strata:
            idx = rng.integers(0, len(t), size=(BOOT, len(t)))
            boots.append((w, t[idx].mean(axis=1), {c: xs[c][idx].mean(axis=1) for c in SHARES}))
        bden = sum(w * bt for w, bt, _ in boots)
        for c in SHARES:
            num = sum(w * xs[c].mean() for w, _, xs in strata)
            row[f"{c}_share"] = num / den if den > 0 else None
            with np.errstate(invalid="ignore", divide="ignore"):
                b = sum(w * bx[c] for w, _, bx in boots) / bden
            b = b[np.isfinite(b)]
            row[f"{c}_share_p05"] = float(np.quantile(b, 0.05)) if den > 0 and b.size else None
            row[f"{c}_share_p95"] = float(np.quantile(b, 0.95)) if den > 0 and b.size else None
        for name, (num_c, den_c) in CONDITIONAL.items():
            num = sum(w * xs[num_c].mean() for w, _, xs in strata)
            dd = sum(w * xs[den_c].mean() for w, _, xs in strata)
            row[name] = num / dd if dd > 0 else None
            with np.errstate(invalid="ignore", divide="ignore"):
                b = sum(w * bx[num_c] for w, _, bx in boots) / sum(w * bx[den_c] for w, _, bx in boots)
            b = b[np.isfinite(b)]
            row[f"{name}_p05"] = float(np.quantile(b, 0.05)) if dd > 0 and b.size else None
            row[f"{name}_p95"] = float(np.quantile(b, 0.95)) if dd > 0 and b.size else None
        rows.append(row)
    return pl.DataFrame(rows, infer_schema_length=None).sort("quarter")


def build_monthly(raw: Path, daily: pl.DataFrame, tracked: list[str], as_of: str,
                  groups: dict[str, list[str]] | None = None) -> dict[str, pl.DataFrame]:
    GROUPS.clear()
    GROUPS.update(groups or {})
    # primary accounts: those summed in group totals and excluded from the sample's "other" bucket
    primary = sorted({a for accs in (groups or {}).values() for a in accs}) or list(tracked)
    # NearBlocks monthly totals (calendar months, UTC)
    nb = (daily.filter((pl.col("chain") == "near") & (pl.col("source") == "nearblocks")
                       & pl.col("metric").is_in(["txns", "active_accounts", "new_accounts", "blocks"]))
          .with_columns(pl.col("date").str.slice(0, 7).alias("month")))
    nbm = nb.pivot(on="metric", index=["date", "month"], values="value").group_by("month").agg(
        pl.col("txns").sum().alias("nb_txns"), pl.col("active_accounts").mean().alias("nb_active_accounts_avg"),
        pl.col("new_accounts").sum().alias("nb_new_accounts"), pl.col("blocks").sum().alias("nb_blocks"),
        pl.len().alias("nb_days"))

    counts = io.read_csv(raw / "fastnear_tx" / "monthly_receiver_counts.csv").with_columns(
        pl.col("txs_count").cast(pl.Int64), pl.col("from_height").cast(pl.Int64),
        pl.col("to_height_inclusive").cast(pl.Int64))
    wide = counts.pivot(on="account_id", index="month", values="txs_count")
    rename = {a: "census_" + a.replace(".", "_") for a in tracked}
    wide = wide.rename({k: v for k, v in rename.items() if k in wide.columns})
    heights = counts.group_by("month").agg(pl.col("from_height").first(),
                                           (pl.col("to_height_inclusive").first() + 1).alias("to_height"))
    weights = {m: float(t - f) for m, f, t in heights.select("month", "from_height", "to_height").iter_rows()}

    blocks, txs = load_sample(raw, primary)
    ms = monthly_sample_shares(blocks, txs)
    qs = quarterly_sample_shares(blocks, txs, weights)

    m = (nbm.join(wide, on="month", how="inner").join(heights, on="month", how="left")
         .join(ms, on="month", how="left").sort("month"))
    census_cols = [v for v in rename.values() if v in m.columns]
    primary_cols = [rename[a] for a in primary if rename.get(a) in m.columns]
    m = m.with_columns(pl.sum_horizontal(primary_cols).alias("census_tracked_total"))
    for gname, accs in (groups or {}).items():
        cols = [rename[a] for a in accs if rename.get(a) in m.columns]
        m = m.with_columns(pl.sum_horizontal(cols).alias(f"census_{gname}_total"),
                           (pl.sum_horizontal(cols) / pl.col("nb_txns")).alias(f"share_{gname}_total"))
    m = m.with_columns(
        *[(pl.col(c) / pl.col("nb_txns")).alias(c.replace("census_", "share_")) for c in census_cols],
        (pl.col("census_tracked_total") / pl.col("nb_txns")).alias("share_tracked_total"),
        (pl.col("nb_txns") - pl.col("census_tracked_total")).alias("other_txns"),
        # coverage check: sample mean tx/block * height range vs NearBlocks monthly txns
        (pl.col("sample_tx_per_block") * (pl.col("to_height") - pl.col("from_height")) / pl.col("nb_txns"))
        .alias("sample_vs_nearblocks_txns"),
    )
    # organic proxy: census "other" transactions (not to a tracked contract) x the sampled share of them that are
    # direct (not relayed) and signed by a named account; the 90% CI is the bootstrap CI of that conditional share
    m = m.with_columns((pl.col("other_txns") * pl.col("organic_given_other")).alias("organic_proxy_txns"),
                       (pl.col("other_txns") * pl.col("organic_given_other_p05")).alias("organic_proxy_txns_p05"),
                       (pl.col("other_txns") * pl.col("organic_given_other_p95")).alias("organic_proxy_txns_p95"),
                       (pl.col("month") == as_of[:7]).alias("is_partial_month"))
    # sample vs census validation for HOT
    m = m.with_columns(((pl.col("share_game_hot_tg") >= pl.col("hot_share_p05"))
                        & (pl.col("share_game_hot_tg") <= pl.col("hot_share_p95"))).alias("hot_census_in_sample_ci"))
    # census (involvement) vs sample (top-level receiver) per tracked contract, pooled over months with activity:
    # sample-implied txs = sum over months of NearBlocks txs x sampled top-level share of the contract
    top = (txs.group_by(["month", "real_receiver_id"]).len().rename({"len": "n"})
           .join(txs.group_by("month").len().rename({"len": "tot"}), on="month"))
    cvs = []
    for a in tracked:
        col = rename.get(a)
        if col not in m.columns:
            continue
        sh = top.filter(pl.col("real_receiver_id") == a).select("month", (pl.col("n") / pl.col("tot")).alias("s"))
        j = m.select("month", "nb_txns", pl.col(col).alias("census")).join(sh, on="month", how="left").with_columns(
            pl.col("s").fill_null(0.0)).filter((pl.col("census") > 0) & ~pl.col("month").eq(as_of[:7]))
        implied = float((j["nb_txns"] * j["s"]).sum()) if j.height else 0.0
        cvs.append((a, "primary" if a in primary else "secondary", j.height, float(j["census"].sum()) if j.height else 0.0,
                    implied, (float(j["census"].sum()) / implied) if implied > 0 else None))
    census_vs_sample = pl.DataFrame(cvs, schema={"account_id": pl.Utf8, "role": pl.Utf8, "months": pl.Int64,
                                                 "census_txs": pl.Float64, "sample_implied_top_level_txs": pl.Float64,
                                                 "census_to_sample": pl.Float64}, orient="row")
    signer_mix = (txs.group_by(["month", "signer_kind"]).len()
                  .with_columns((pl.col("len") / pl.col("len").sum().over("month")).alias("share"))
                  .rename({"len": "sample_txs"}).sort(["month", "signer_kind"]))
    top_receivers = (txs.group_by(["month", "real_receiver_id"]).len()
                     .with_columns((pl.col("len") / pl.col("len").sum().over("month")).alias("share"))
                     .sort(["month", "len", "real_receiver_id"], descending=[False, True, False])
                     .group_by("month", maintain_order=True).head(3).rename({"len": "sample_txs"}))
    return {"monthly": m, "quarterly": qs, "signer_mix": signer_mix, "top_receivers": top_receivers,
            "census_vs_sample": census_vs_sample}
