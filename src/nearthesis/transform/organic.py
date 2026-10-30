"""Bot-vs-human decomposition (PIANO.md Q1, phase 2a): per-signer activity score, transaction and account classes,
monthly organic transaction / active-account series with 90% bootstrap intervals, and new-account cohort retention.

Design (see `nearthesis.sampling`): every draw is an equal-probability draw of the month's transactions, clustered by
sampled block. For draw i in month m with real signer s:
  c_i      = transactions s really signed in month m (exact FastNear count)
  c_day_i  = transactions s really signed on the UTC day of the draw (from the signer's timestamps)
Estimators (N_m = NearBlocks transactions of month m, D_m = days in month m, n = draws in month m):
  class share of transactions  p_k   = (1/n) sum_i 1{tx label_i = k}
  transactions per day         T_k   = N_m p_k / D_m
  monthly active signers       MAS_k = N_m (1/n) sum_i 1{account label_i = k} / c_i
  daily active signers (avg)   DAS_k = (N_m / D_m) (1/n) sum_i 1{account label_i = k} / c_day_i
because sum over a month's transactions of 1/c(signer) counts each signer once (and likewise per day). 90% intervals:
bootstrap that resamples sampled blocks within each month (draws travel with their block), fixed seed.

Bot score (thresholds in config [organic], fixed before looking at the per-signer data):
  I1 c >= 300 txs/month; I2 c >= 3000 (extra point); I3 >= 18 distinct UTC hours active (>= 50 timestamps);
  I4 median gap < 30 s (>= 20 timestamps); I5 gap CV < 0.5 (>= 20 timestamps);
  I6 >= 90% of >= 10 detailed txs are the same (receiver, method) and c >= 30.
  automated if score >= 2 (strict: >= 1, lenient: >= 3).
Account label (per signer-month), first match wins:
  incentivized   majority of its detailed txs (or of its drawn txs) go to an incentivized contract (HOT, KaiChing,
                 SWEAT, NEARCrowd, inscriptions);
  infrastructure automated and majority of its txs go to settlement / bridge / MPC / EVM-relay contracts;
  automated      score >= threshold;
  organic        everything else.
Transaction label: incentivized if the drawn tx goes to an incentivized contract; otherwise the account label.

Limits (also in the report): timing features use at most 200 timestamps per signer-month (the most recent); a
human using an automated wallet feature can look automated and a slow bot can look human; relayed transactions are
attributed to their real (inner) signer; account labels use account ids only, no off-chain identity.
"""

from __future__ import annotations

import datetime as dt
import math
from collections import Counter
from pathlib import Path

import numpy as np
import polars as pl

from .. import config, io, sampling

CLASSES = ["organic", "automated", "incentivized", "infrastructure"]


def _month_start_ts(month: str) -> int:
    y, m = map(int, month.split("-"))
    return int(dt.datetime(y, m, 1, tzinfo=dt.UTC).timestamp())


def _add_months(month: str, k: int) -> str:
    y, m = map(int, month.split("-"))
    m0 = y * 12 + (m - 1) + k
    return f"{m0 // 12:04d}-{m0 % 12 + 1:02d}"


def is_incentivized(acc: str, incentivized: list[str], ocfg: dict) -> bool:
    return acc in incentivized or any(acc.endswith(x) for x in ocfg.get("incentivized_suffixes", []))


def _is_infra(acc: str, ocfg: dict) -> bool:
    return acc in ocfg["infrastructure"] or any(acc.endswith(s) for s in ocfg["infrastructure_suffixes"])


def decode_ts(first, gaps: str | None) -> list[int]:
    """Delta-encoded timestamps (first unix second + space-separated gaps) -> ascending unix seconds."""
    if first in (None, ""):
        return []
    out = [int(first)]
    for g in (gaps or "").split():
        out.append(out[-1] + int(g))
    return out


def signer_features(sma: pl.DataFrame, life: pl.DataFrame, det: pl.DataFrame, bounds: dict[str, tuple[int, int]],
                    incentivized: list[str], ocfg: dict) -> pl.DataFrame:
    """One row per (signer, month): counts, timing features, detail-based diversity, age, bot score."""
    life_d = {r["signer_id"]: r for r in life.iter_rows(named=True)}
    det_g: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for r in det.iter_rows(named=True):
        det_g.setdefault((r["signer_id"], r["month"]), []).append((r["real_receiver_id"] or "", r["methods"] or ""))
    rows = []
    for r in sma.iter_rows(named=True):
        s, month = r["signer_id"], r["month"]
        c_raw = int(r["txs_count"])
        c = max(c_raw, 1)
        ts = decode_ts(r["ts_first_s"], r["ts_gaps_s"])
        n_ts = len(ts)
        gaps = np.diff(ts) if n_ts >= 2 else np.array([])
        med_gap = float(np.median(gaps)) if gaps.size else None
        cv_gap = float(np.std(gaps) / np.mean(gaps)) if gaps.size >= 2 and np.mean(gaps) > 0 else None
        hours = len({(t // 3600) % 24 for t in ts})
        d = det_g.get((s, month), [])
        n_det = len(d)
        top_share = Counter(d).most_common(1)[0][1] / n_det if n_det else None
        inc_share = (sum(1 for rc, _ in d if is_incentivized(rc, incentivized, ocfg)
                             or (rc == s and is_incentivized(s, incentivized, ocfg))) / n_det if n_det else None)
        infra_share = sum(1 for rc, _ in d if _is_infra(rc, ocfg)) / n_det if n_det else None
        lf = life_d.get(s, {})
        first_ts = lf.get("first_timestamp_s")
        h0, h1 = bounds[month]
        first_h = lf.get("first_height")
        ind = {
            "i1_high_volume": c >= ocfg["high_volume_txs"],
            "i2_very_high_volume": c >= ocfg["very_high_volume_txs"],
            "i3_round_the_clock": n_ts >= ocfg["round_the_clock_min_ts"] and hours >= ocfg["round_the_clock_hours"],
            "i4_fast": n_ts >= ocfg["min_ts_for_timing"] and med_gap is not None and med_gap < ocfg["fast_median_gap_s"],
            "i5_regular": n_ts >= ocfg["min_ts_for_timing"] and cv_gap is not None and cv_gap < ocfg["regular_gap_cv"],
            "i6_repetitive": (n_det >= ocfg["repetitive_min_details"] and top_share is not None
                              and top_share >= ocfg["repetitive_share"] and c >= ocfg["repetitive_min_txs"]),
        }
        rows.append({"signer_id": s, "month": month, "txs_count": c, "count_was_zero": c_raw == 0,
                     "timestamps": n_ts, "timestamps_complete": n_ts >= c, "median_gap_s": med_gap, "gap_cv": cv_gap,
                     "active_hours": hours, "details": n_det, "top_pair_share": top_share,
                     "incentivized_share_details": inc_share, "infrastructure_share_details": infra_share,
                     "first_timestamp_s": first_ts,
                     "age_days_at_month_start": (_month_start_ts(month) - first_ts) / 86400 if first_ts else None,
                     "is_new": first_h is not None and h0 <= int(first_h) < h1,
                     "last_signed_timestamp_s": lf.get("last_signed_timestamp_s"),
                     **ind, "bot_score": sum(int(v) for v in ind.values()), "ts_list": ts})
    return pl.DataFrame(rows, infer_schema_length=None)


def label_draws(draws: pl.DataFrame, feats: pl.DataFrame, incentivized: list[str], ocfg: dict,
                threshold: int) -> pl.DataFrame:
    """Attach features to draws; compute c_day, account label and tx label at a given score threshold."""
    inc = lambda r: is_incentivized(r["real_receiver_id"], incentivized, ocfg) or (  # noqa: E731
        r["real_receiver_id"] == r["real_signer_id"] and is_incentivized(r["real_signer_id"], incentivized, ocfg))
    draws = draws.with_columns(pl.struct("real_receiver_id", "real_signer_id").map_elements(
        inc, return_dtype=pl.Boolean).alias("drawn_incentivized"))
    f = feats.drop("ts_list")
    # draws whose signer-month was not fetched cannot be labelled (none in a complete fetch; kept explicit)
    d = draws.join(f, left_on=["real_signer_id", "month"], right_on=["signer_id", "month"], how="inner")
    ts_map = {(r["signer_id"], r["month"]): r["ts_list"] for r in feats.select("signer_id", "month", "ts_list").iter_rows(named=True)}
    # drawn-receiver majorities per signer-month (used when there are no details)
    dm = (draws.with_columns(pl.col("drawn_incentivized").alias("_inc"),
                             pl.col("real_receiver_id").map_elements(lambda a: _is_infra(a, ocfg),
                                                                     return_dtype=pl.Boolean).alias("_inf"))
          .group_by(["real_signer_id", "month"]).agg(pl.col("_inc").mean().alias("drawn_inc_share"),
                                                     pl.col("_inf").mean().alias("drawn_infra_share")))
    d = d.join(dm, on=["real_signer_id", "month"], how="left").sort(["month", "draw_rank"])  # joins may reorder
    out = []
    for r in d.iter_rows(named=True):
        c = r["txs_count"] or 1
        ts = ts_map.get((r["real_signer_id"], r["month"]), [])
        bt = int(r["block_timestamp_ns"]) // 1_000_000_000
        day0 = bt - bt % 86400
        day1 = day0 + 86400
        in_day = sum(1 for t in ts if day0 <= t < day1)
        covers_day = r["timestamps_complete"] or (ts and ts[0] < day0)
        if covers_day:
            c_day, c_day_exact = max(in_day, 1), True
        else:
            y, m = map(int, r["month"].split("-"))
            ndays = (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.date(y, m, 1)).days
            c_day, c_day_exact = max(c / ndays, 1.0), False
        inc_share = r["incentivized_share_details"] if r["incentivized_share_details"] is not None else r["drawn_inc_share"]
        inf_share = r["infrastructure_share_details"] if r["infrastructure_share_details"] is not None else r["drawn_infra_share"]
        automated = (r["bot_score"] or 0) >= threshold
        if inc_share is not None and inc_share >= 0.5:
            acct = "incentivized"
        elif automated and inf_share is not None and inf_share >= 0.5:
            acct = "infrastructure"
        elif automated:
            acct = "automated"
        else:
            acct = "organic"
        if r["drawn_incentivized"]:
            txl = "incentivized"
        elif acct == "incentivized":
            txl = "automated" if automated else "organic"
        else:
            txl = acct
        out.append({**{k: r[k] for k in ("month", "draw_rank", "block_key", "real_signer_id", "real_receiver_id",
                                          "is_relayed", "txs_count", "bot_score", "is_new",
                                          "last_signed_timestamp_s")},
                    "c_day": float(c_day), "c_day_exact": c_day_exact, "account_label": acct, "tx_label": txl})
    return pl.DataFrame(out, infer_schema_length=None)


def _monthly_arrays(lab: pl.DataFrame):
    """Per month: block keys and per-draw arrays used by the estimators."""
    res = {}
    for (month,), g in lab.group_by(["month"], maintain_order=True):
        res[month] = {
            "block": g["block_key"].to_numpy(),
            "inv_c": 1.0 / g["txs_count"].cast(pl.Float64).to_numpy(),
            "inv_cday": 1.0 / g["c_day"].to_numpy(),
            "acct": g["account_label"].to_numpy(), "tx": g["tx_label"].to_numpy(),
        }
    return res


def _estimates(a: dict, idx: np.ndarray, N: float, D: float) -> dict:
    out = {}
    n = len(idx)
    for k in CLASSES:
        tx = (a["tx"][idx] == k).astype(float)
        ac = (a["acct"][idx] == k).astype(float)
        out[f"tx_share_{k}"] = tx.mean()
        out[f"txs_per_day_{k}"] = N * tx.mean() / D
        out[f"mas_{k}"] = N * (ac * a["inv_c"][idx]).mean()
        out[f"das_{k}"] = N / D * (ac * a["inv_cday"][idx]).mean()
    out["mas_all"] = N * a["inv_c"][idx].mean()
    out["das_all"] = N / D * a["inv_cday"][idx].mean()
    out["draws"] = n
    return out


def monthly_series(lab: pl.DataFrame, nb_month: pl.DataFrame, boot: int, seed: int) -> tuple[pl.DataFrame, dict]:
    """Monthly point estimates + 90% bootstrap intervals; also returns the bootstrap replicates per month."""
    arr = _monthly_arrays(lab)
    nbm = {r["month"]: r for r in nb_month.iter_rows(named=True)}
    rows, reps = [], {}
    for month in sorted(arr):
        if month not in nbm:
            continue
        a, N, D = arr[month], float(nbm[month]["nb_txns"]), float(nbm[month]["nb_days"])
        point = _estimates(a, np.arange(len(a["block"])), N, D)
        rng = np.random.default_rng([seed, int(month.replace("-", ""))])
        blocks = np.unique(a["block"])
        members = {b: np.flatnonzero(a["block"] == b) for b in blocks}
        rep = []
        for _ in range(boot):
            pick = rng.choice(blocks, size=len(blocks), replace=True)
            idx = np.concatenate([members[b] for b in pick])
            if idx.size:
                rep.append(_estimates(a, idx, N, D))
        reps[month] = rep
        row = {"month": month, "nb_txns": N, "nb_days": D, "sample_blocks_with_draws": len(blocks), **point}
        for key in [k for k in point if k != "draws"]:
            vals = np.array([r[key] for r in rep])
            row[f"{key}_p05"], row[f"{key}_p95"] = float(np.quantile(vals, 0.05)), float(np.quantile(vals, 0.95))
        rows.append(row)
    return pl.DataFrame(rows, infer_schema_length=None), reps


def quarterly_series(monthly: pl.DataFrame, reps: dict, keys: list[str]) -> pl.DataFrame:
    """Quarter = mean of its months' estimates (per-day and per-month quantities); intervals from the month
    replicates combined index by index (months are sampled independently)."""
    q = {}
    for m in monthly["month"].to_list():
        qq = f"{m[:4]}-Q{(int(m[5:7]) - 1) // 3 + 1}"
        q.setdefault(qq, []).append(m)
    rows = []
    for qq, months in sorted(q.items()):
        row = {"quarter": qq, "months": len(months)}
        for k in keys:
            vals = [float(monthly.filter(pl.col("month") == m)[k][0]) for m in months]
            row[k] = float(np.mean(vals))
            nrep = min(len(reps[m]) for m in months)
            comb = np.mean([[reps[m][i][k] for i in range(nrep)] for m in months], axis=0)
            row[f"{k}_p05"], row[f"{k}_p95"] = float(np.quantile(comb, 0.05)), float(np.quantile(comb, 0.95))
        rows.append(row)
    return pl.DataFrame(rows, infer_schema_length=None)


def cohort_retention(lab: pl.DataFrame, last_month: str, horizons=(1, 3, 6), boot: int = 1000,
                     seed: int = 0, lifetime_draws: int = 60) -> pl.DataFrame:
    """Rolling retention of new signers by quarterly cohort: share (account-weighted, weight 1/c) of accounts first
    seen in the cohort month that really signed a transaction at or after the start of month m+k. Bootstrap over
    sampled blocks within months. Also split organic vs other account labels."""
    new = lab.filter(pl.col("is_new") & pl.col("last_signed_timestamp_s").is_not_null()
                     & (pl.col("draw_rank") < lifetime_draws)).with_columns(
        (pl.col("month").str.slice(0, 4) + "-Q" + ((pl.col("month").str.slice(5, 2).cast(pl.Int64) - 1) // 3 + 1)
         .cast(pl.Utf8)).alias("cohort"))
    rows = []
    for group, sub in (("all", new), ("organic", new.filter(pl.col("account_label") == "organic")),
                       ("non_organic", new.filter(pl.col("account_label") != "organic"))):
        for (cohort,), g in sub.group_by(["cohort"], maintain_order=True):
            for k in horizons:
                ok = g.filter(pl.col("month").map_elements(lambda m: _add_months(m, k) <= last_month,
                                                           return_dtype=pl.Boolean))
                if ok.height < 3:
                    continue
                target = ok["month"].map_elements(lambda m: _month_start_ts(_add_months(m, k)), return_dtype=pl.Int64)
                ret = (ok["last_signed_timestamp_s"].cast(pl.Int64) >= target).cast(pl.Float64).to_numpy()
                w = 1.0 / ok["txs_count"].cast(pl.Float64).to_numpy()
                keys = (ok["month"] + "/" + ok["block_key"].cast(pl.Utf8)).to_numpy()
                point = float((w * ret).sum() / w.sum())
                rng = np.random.default_rng([seed, k, int(cohort[:4]), int(cohort[-1]), len(group)])
                ub = np.unique(keys)
                mem = {b: np.flatnonzero(keys == b) for b in ub}
                bs = []
                for _ in range(boot):
                    idx = np.concatenate([mem[b] for b in rng.choice(ub, size=len(ub), replace=True)])
                    bs.append((w[idx] * ret[idx]).sum() / w[idx].sum())
                rows.append({"group": group, "cohort": cohort, "horizon_months": k, "new_signer_draws": ok.height,
                             "retention": point, "retention_p05": float(np.quantile(bs, 0.05)),
                             "retention_p95": float(np.quantile(bs, 0.95)),
                             "unweighted_retention": float(ret.mean())})
    schema = {"group": pl.Utf8, "cohort": pl.Utf8, "horizon_months": pl.Int64, "new_signer_draws": pl.Int64,
              "retention": pl.Float64, "retention_p05": pl.Float64, "retention_p95": pl.Float64,
              "unweighted_retention": pl.Float64}
    return pl.DataFrame(rows, schema=schema).sort(["group", "horizon_months", "cohort"])


def build(raw: Path, daily: pl.DataFrame, as_of: str) -> dict[str, pl.DataFrame]:
    cfg = config.load()
    ocfg, scfg = cfg["organic"], cfg["signers"]
    seed = int(cfg["activity"]["seed"])
    incentivized = list(cfg["activity"]["groups"]["incentivized"]) + list(ocfg.get("incentivized_extra", []))
    d = raw / "fastnear_tx"
    if not (d / "signer_month_activity.csv").exists():
        return {}
    blocks, txs = sampling.load_block_sample(raw)
    draws = sampling.draw_signers(blocks, txs, scfg, seed)
    sma = io.read_csv(d / "signer_month_activity.csv")
    life = io.read_csv(d / "signer_lifetime.csv").with_columns(
        [pl.col(c).cast(pl.Int64) for c in ("first_height", "first_timestamp_s", "last_signed_height",
                                             "last_signed_timestamp_s", "lifetime_txs_any_role",
                                             "lifetime_txs_real_signer")])
    det = io.read_csv(d / "signer_tx_details.csv")
    mb = io.read_csv(d / "month_boundaries.csv")
    hs = [(r[0][:7], int(r[1])) for r in mb.select("boundary_utc", "height").iter_rows()]
    bounds = {m0: (h0, h1) for (m0, h0), (_, h1) in zip(hs[:-1], hs[1:])}
    feats = signer_features(sma, life, det, bounds, incentivized, ocfg)

    nb = (daily.filter((pl.col("chain") == "near") & (pl.col("source") == "nearblocks") & (pl.col("metric") == "txns"))
          .with_columns(pl.col("date").str.slice(0, 7).alias("month"))
          .group_by("month").agg(pl.col("value").sum().alias("nb_txns"), pl.len().alias("nb_days")))
    nba = (daily.filter((pl.col("chain") == "near") & (pl.col("source") == "nearblocks")
                        & (pl.col("metric") == "active_accounts"))
           .with_columns(pl.col("date").str.slice(0, 7).alias("month"))
           .group_by("month").agg(pl.col("value").mean().alias("nb_active_accounts_avg")))
    boot = int(ocfg["bootstrap"])
    lab = label_draws(draws, feats, incentivized, ocfg, int(ocfg["score_threshold"]))
    monthly, reps = monthly_series(lab, nb, boot, seed)
    monthly = (monthly.join(nba, on="month", how="left")
               .with_columns((pl.col("month") == as_of[:7]).alias("is_partial_month"),
                             (pl.col("das_all") / pl.col("nb_active_accounts_avg")).alias("das_all_to_nearblocks")))
    qkeys = ["txs_per_day_organic", "tx_share_organic", "mas_organic", "das_organic", "mas_all", "das_all",
             "tx_share_automated", "tx_share_incentivized", "tx_share_infrastructure"]
    full = monthly.filter(~pl.col("is_partial_month"))
    quarterly = quarterly_series(full, reps, qkeys)
    # sensitivity to the score threshold (point estimates, pooled by quarter)
    sens = []
    for name, th in (("strict", int(ocfg["strict_threshold"])), ("base", int(ocfg["score_threshold"])),
                     ("lenient", int(ocfg["lenient_threshold"]))):
        lb = label_draws(draws, feats, incentivized, ocfg, th)
        ms = _points_only(lb, nb)
        ms = ms.filter(pl.col("month") < as_of[:7]).with_columns(
            (pl.col("month").str.slice(0, 4) + "-Q" + ((pl.col("month").str.slice(5, 2).cast(pl.Int64) - 1) // 3 + 1)
             .cast(pl.Utf8)).alias("quarter"))
        g = ms.group_by("quarter").agg(pl.col("tx_share_organic").mean(), pl.col("mas_organic").mean(),
                                       pl.col("das_organic").mean())
        sens.append(g.with_columns(pl.lit(name).alias("threshold_name"), pl.lit(th).alias("score_threshold")))
    sensitivity = pl.concat(sens).sort(["quarter", "score_threshold"])
    last_month = sorted(monthly["month"].to_list())[-1]
    cohorts = cohort_retention(lab, last_month, boot=boot, seed=seed, lifetime_draws=int(scfg["lifetime_draws"]))
    top = (lab.filter(pl.col("tx_label") == "organic").with_columns(
        (pl.col("month").str.slice(0, 4) + "-Q" + ((pl.col("month").str.slice(5, 2).cast(pl.Int64) - 1) // 3 + 1)
         .cast(pl.Utf8)).alias("quarter"))
        .group_by(["quarter", "real_receiver_id"]).len().rename({"len": "organic_draws"})
        .with_columns((pl.col("organic_draws") / pl.col("organic_draws").sum().over("quarter")).alias("share"))
        .sort(["quarter", "organic_draws", "real_receiver_id"], descending=[False, True, False])
        .group_by("quarter", maintain_order=True).head(5))
    feats_out = feats.drop("ts_list").sort(["month", "signer_id"])
    return {"features": feats_out, "draws": lab.sort(["month", "draw_rank"]), "monthly": monthly,
            "quarterly": quarterly, "sensitivity": sensitivity, "cohorts": cohorts, "top_organic_receivers": top}


def _points_only(lab: pl.DataFrame, nb: pl.DataFrame) -> pl.DataFrame:
    arr = _monthly_arrays(lab)
    nbm = {r["month"]: r for r in nb.iter_rows(named=True)}
    rows = []
    for month in sorted(arr):
        if month in nbm:
            a = arr[month]
            rows.append({"month": month, **_estimates(a, np.arange(len(a["block"])), float(nbm[month]["nb_txns"]),
                                                      float(nbm[month]["nb_days"]))})
    return pl.DataFrame(rows, infer_schema_length=None)
