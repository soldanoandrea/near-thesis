"""Phase 2a build: analysis layer (bot-vs-human decomposition, Intents cross-check, money trails, developer activity)
and models (supply scenarios, multiples, adoption, yields). Offline, deterministic, called by `pipeline.build`.

Writes data/processed/<table>.csv, reports/analysis_summary.md and reports/models_summary.md. Every number in the
reports comes from these tables; every model input is either computed here from data/processed or read from
config/sources.toml ([models] ranges), and both are printed in the report.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import polars as pl

from . import config, io, predictions as preds, report2
from .metrics import MetricTable, _d, at, full_wsum, ratio
from .models import adoption, multiples, supply as msupply, yields as myields
from .transform import devactivity, intents_check, ledgers, organic
from .transform.daily import series


def _years_between(a: str, b: str) -> float:
    return (_d(b) - _d(a)).days / 365.0


def intents_quarterly(daily: pl.DataFrame, as_of: str) -> pl.DataFrame:
    """Quarterly NEAR Intents volume, fees, captured revenue and take rates (DefiLlama), complete quarters only."""
    rows = []
    d = (daily.filter((pl.col("chain") == "near") & (pl.col("source") == "defillama")
                      & pl.col("metric").is_in(["intents_volume_usd", "intents_fees_usd", "intents_revenue_usd"]))
         .pivot(on="metric", index="date", values="value").sort("date")
         .with_columns((pl.col("date").str.slice(0, 4) + "-Q" + ((pl.col("date").str.slice(5, 2).cast(pl.Int64) - 1)
                                                                 // 3 + 1).cast(pl.Utf8)).alias("quarter")))
    q = d.group_by("quarter").agg(pl.len().alias("days"), pl.col("intents_volume_usd").sum().alias("volume"),
                                  pl.col("intents_fees_usd").sum().alias("fees"),
                                  pl.col("intents_revenue_usd").sum().alias("revenue")).sort("quarter")
    q = q.filter(pl.col("days") >= 88).with_columns(
        (pl.col("fees") / pl.col("volume")).alias("fee_take_rate"),
        (pl.col("revenue") / pl.col("volume")).alias("revenue_take_rate"),
        (pl.col("volume") / pl.col("volume").shift(1) - 1).alias("volume_qoq"),
        (pl.col("revenue") / pl.col("revenue").shift(1) - 1).alias("revenue_qoq"))
    return q


def model_inputs(raw: Path, daily: pl.DataFrame, epochs: pl.DataFrame, as_of: str, led: dict, ic: dict) -> dict:
    end = _d(as_of)
    fb = io.read_csv(raw / "rpc" / "final_block_header.csv")
    supply0 = int(fb["total_supply_yocto"][0]) / 1e24
    price = at(series(daily, "near", "price_usd", "coingecko"), end)
    mcap = at(series(daily, "near", "market_cap_usd", "coingecko"), end)
    yago = str(end - dt.timedelta(days=365))
    rec = epochs.filter(pl.col("start_date") > yago)
    dl = lambda m: series(daily, "near", m, "defillama")  # noqa: E731
    vol90, rev90, hrev90, fee90 = (full_wsum(dl(m), end, 90) for m in ("intents_volume_usd", "intents_revenue_usd",
                                                                       "intents_holders_revenue_usd", "intents_fees_usd"))
    ann = 365 / 90
    inp = {
        "as_of": as_of, "supply0": supply0, "price": price, "market_cap": mcap,
        "realized_to_cap": float(rec["realized_to_cap"].mean()),
        "issuance_rate_365d": float(rec["mint_annualized_rate"].mean()),
        "burn_rate": float(rec["burn_annualized_rate"].mean()),
        "treasury_share": float(epochs.drop_nulls("treasury_reward_share")["treasury_reward_share"][-1]),
        "staking_ratio": float(epochs.drop_nulls("staking_ratio")["staking_ratio"][-1]),
        "intents_volume_annualized_90d": vol90 * ann if vol90 else None,
        "intents_revenue_annualized_90d": rev90 * ann if rev90 else None,
        "intents_holders_revenue_annualized_90d": hrev90 * ann if hrev90 else None,
        "intents_fees_annualized_90d": fee90 * ann if fee90 else None,
    }
    inp["take_rate_90d"] = ratio(rev90, vol90)
    inp["buyback_yield_defillama"] = ratio(inp["intents_holders_revenue_annualized_90d"], mcap)
    bb = led.get("buyback_summary")
    if bb is not None and bb.height:
        r = bb.row(0, named=True)
        inp["buyback_near_per_year_onchain"] = r["near_acquired_annualized"]
        inp["buyback_yield_onchain"] = r["near_acquired_annualized"] / supply0 if r["near_acquired_annualized"] else None
    else:
        inp["buyback_near_per_year_onchain"] = inp["buyback_yield_onchain"] = None
    inp["buyback_yield"] = inp["buyback_yield_onchain"] or inp["buyback_yield_defillama"] or 0.0
    gp = raw / "governance" / "hsp029_status.csv"
    if gp.exists():
        g = io.read_csv(gp).row(0, named=True)
        from . import manifest as _m
        inp["hsp029_status"] = g["status"]
        inp["hsp029_snapshot_utc"] = _m.load()["files"]["governance/hsp029_status.csv"]["fetched_at_utc"]
        inp["hsp029_url"] = g["topic_url"]
    d = ic.get("days") if ic else None
    inp["intents_onchain_one_sided_to_defillama"] = (float(d["ratio_sample_to_defillama"].median())
                                                     if d is not None and d.height else None)
    inp["buyback_yield_source"] = "on-chain buyback ledger" if inp["buyback_yield_onchain"] else "DefiLlama holders revenue"
    return inp


def run_supply_models(inp: dict, mcfg: dict) -> dict[str, pl.DataFrame]:
    scen = []
    pol = [("status_quo", "status_quo", 3)] + [(f"hsp029_act{a}m", "hsp029", a) for a in mcfg["hsp029_activation_months"]]
    for name, policy, act in pol:
        for lvl in ("low", "base", "high"):
            scen.append({"scenario": f"{name}/{lvl}", "policy": policy, "activation_month": act,
                         "realized_to_cap": inp["realized_to_cap"], "burn_rate": inp["burn_rate"],
                         "fee_growth": mcfg["fee_growth"][lvl], "buyback_yield": inp["buyback_yield"],
                         "revenue_growth": mcfg["revenue_growth"][lvl], "price_growth": 1.0})
    table = msupply.scenario_table(inp["supply0"], scen, mcfg["horizons_years"])
    paths = []
    for sc in scen:
        p = msupply.project(inp["supply0"], 12 * max(mcfg["horizons_years"]), policy=sc["policy"],
                            **{k: v for k, v in sc.items() if k not in ("scenario", "policy")})
        paths.append(p.with_columns(pl.lit(sc["scenario"]).alias("scenario")))
    grid = msupply.threshold_grid(
        supply=inp["supply0"], prices=[inp["price"] * m for m in mcfg["price_multipliers"]],
        issuance_rates=[0.025 * inp["realized_to_cap"], 0.016 * inp["realized_to_cap"]], burn_rate=inp["burn_rate"],
        take_rates=[(inp["take_rate_90d"] or 0) * m for m in mcfg["take_rate_multipliers"]],
        buyback_share=mcfg["buyback_share_of_revenue"], revenue_now_usd=inp["intents_revenue_annualized_90d"] or 0.0,
        volume_now_usd=inp["intents_volume_annualized_90d"] or 0.0)
    params = pl.DataFrame([{"scenario": s["scenario"], **{k: v for k, v in s.items() if k != "scenario"}} for s in scen])
    return {"model_supply_scenarios": table, "model_supply_paths": pl.concat(paths).select("scenario", pl.exclude("scenario")),
            "model_net_zero_grid": grid, "model_supply_parameters": params}


def run_multiples(daily: pl.DataFrame, peers: pl.DataFrame) -> dict[str, pl.DataFrame]:
    as_of = peers["as_of"][0]
    end = _d(as_of)
    rows = []
    for r in peers.iter_rows(named=True):
        c = r["chain"]
        if c == "base":
            continue
        f, rv = series(daily, c, "chain_fees_usd", "defillama"), series(daily, c, "chain_revenue_usd", "defillama")
        row = {"chain": c, "market_cap_usd": r["market_cap_usd"], "fees_30d": full_wsum(f, end, 30),
               "fees_365d": full_wsum(f, end, 365), "revenue_30d": full_wsum(rv, end, 30),
               "revenue_365d": full_wsum(rv, end, 365), "intents_fees_30d": None, "intents_fees_365d": None,
               "intents_revenue_30d": None, "intents_revenue_365d": None}
        if c == "near":
            for m, k in (("intents_fees_usd", "intents_fees"), ("intents_revenue_usd", "intents_revenue")):
                s = series(daily, "near", m, "defillama")
                row[f"{k}_30d"], row[f"{k}_365d"] = full_wsum(s, end, 30), full_wsum(s, end, 365)
        rows.append(row)
    inputs = pl.DataFrame(rows, infer_schema_length=None)
    mult = multiples.multiples(inputs).with_columns(pl.lit(as_of).alias("as_of"))
    return {"model_multiples": mult, "model_multiples_near_vs_peers": multiples.near_vs_peers(mult).with_columns(
        pl.lit(as_of).alias("as_of")), "model_multiples_inputs": inputs.with_columns(pl.lit(as_of).alias("as_of"))}


def run_adoption(org: dict, daily: pl.DataFrame, as_of: str, mcfg: dict) -> dict[str, pl.DataFrame]:
    out_fit, out_bt, out_fc, out_series = [], [], [], []
    series_list = []
    if org:
        first = config.load()["signers"]["recent_first_month"]  # months with the full 200-draw design
        mon = (org["monthly"].filter(~pl.col("is_partial_month") & (pl.col("month") >= first)).sort("month")
               .tail(int(mcfg["adoption_fit_months"])))
        # monthly estimates can be 0 (no organic draw among 200), which a log model cannot use: the organic series
        # are trailing 3-month means (past data only, so the backtest stays out of sample)
        def trailing(col: str):
            v = mon[col].to_list()
            return mon["month"].to_list()[2:], [sum(v[i - 2:i + 1]) / 3 for i in range(2, len(v))]
        for name, col in (("organic_daily_active_signers_3m", "das_organic"),
                          ("organic_monthly_active_signers_3m", "mas_organic"),
                          ("organic_txs_per_day_3m", "txs_per_day_organic")):
            months_, vals_ = trailing(col)
            series_list.append((name, months_, vals_))
    iv = (series(daily, "near", "intents_volume_usd", "defillama")
          .with_columns(pl.col("date").dt.strftime("%Y-%m").alias("month"))
          .group_by("month").agg(pl.col("value").sum(), pl.len().alias("days")).sort("month")
          .filter((pl.col("days") >= 28) & (pl.col("month") < as_of[:7])))
    series_list.append(("intents_monthly_volume_usd", iv["month"].to_list(), iv["value"].to_list()))
    for name, months, vals in series_list:
        y = np.array(vals, float)
        keep = np.isfinite(y) & (y > 0)
        months = [m for m, k in zip(months, keep) if k]
        y = y[keep]
        if len(y) < mcfg["adoption_min_train"] + 3:
            continue
        # time in calendar months since the first kept month: dropping a month (a value of 0) must not shift later ones
        t = np.array([(int(m[:4]) - int(months[0][:4])) * 12 + int(m[5:7]) - int(months[0][5:7]) for m in months], float)
        out_series.append(pl.DataFrame({"series": name, "month": months, "t": t.astype(int), "value": y}))
        for m in adoption.MODELS:
            p = adoption.fit(m, t, y)
            out_fit.append({"series": name, "model": m, "first_month": months[0], "last_month": months[-1],
                            "points": len(y), "growth_per_month": p.get("b"), "K": p.get("K"), "r": p.get("r"),
                            "t0": p.get("t0"), "sigma_log": p.get("sigma"),
                            "K_at_grid_edge": p.get("K_at_grid_edge")})
        bt = adoption.backtest(t, y, horizons=tuple(mcfg["adoption_backtest_horizons"]),
                               min_train=int(mcfg["adoption_min_train"]))
        out_bt.append(adoption.backtest_summary(bt).with_columns(pl.lit(name).alias("series")))
        for m in adoption.MODELS:
            fc = adoption.forecast_ranges(t, y, m, horizons=tuple(mcfg["adoption_forecast_horizons"]),
                                          n_boot=int(mcfg["adoption_bootstrap"]), seed=20261101)
            out_fc.append(fc.with_columns(pl.lit(name).alias("series"), pl.lit(months[-1]).alias("last_month")))
    res = {}
    if out_fit:
        res["model_adoption_fits"] = pl.DataFrame(out_fit, infer_schema_length=None)
        res["model_adoption_backtest"] = pl.concat(out_bt).select("series", pl.exclude("series"))
        res["model_adoption_forecasts"] = pl.concat(out_fc).select("series", pl.exclude("series"))
        res["model_adoption_series"] = pl.concat(out_series)
    return res


def run_yields(epochs: pl.DataFrame, inp: dict, mcfg: dict, as_of: str, led: dict) -> dict[str, pl.DataFrame]:
    e = epochs.with_columns(pl.col("start_date").str.slice(0, 4).alias("year"))
    per = (e.group_by("year").agg(pl.col("mint_annualized_rate").mean().alias("issuance_rate"),
                                  pl.col("burn_annualized_rate").mean().alias("burn_rate"),
                                  pl.col("staking_ratio").drop_nulls().mean().alias("staking_ratio"),
                                  pl.col("treasury_reward_share").drop_nulls().mean().alias("treasury_share"))
           .rename({"year": "period"}).with_columns(pl.lit(0.0).alias("buyback_rate")).sort("period"))
    # buybacks started 2026-02-23: the 2026 row uses NEAR captured on-chain in the complete months since then
    if led and "revenue_reconciliation" in led:
        rr = led["revenue_reconciliation"].filter((pl.col("month") >= "2026-03") & (pl.col("month") < as_of[:7]))
        if rr.height:
            rate = float(rr["near_onchain"].sum()) * 12 / rr.height / inp["supply0"]
            per = per.with_columns(pl.when(pl.col("period") == "2026").then(rate).otherwise(pl.col("buyback_rate"))
                                   .alias("buyback_rate"))
    end = _d(as_of)
    last = []
    for days in (365, 90):
        r = epochs.filter(pl.col("start_date") > str(end - dt.timedelta(days=days)))
        last.append({"period": f"last {days} days", "issuance_rate": r["mint_annualized_rate"].mean(),
                     "burn_rate": r["burn_annualized_rate"].mean(),
                     "staking_ratio": r.drop_nulls("staking_ratio")["staking_ratio"].mean(),
                     "treasury_share": r.drop_nulls("treasury_reward_share")["treasury_reward_share"].mean(),
                     "buyback_rate": inp["buyback_yield"]})
    periods = pl.concat([per.filter(pl.col("period") >= "2021"), pl.DataFrame(last)], how="diagonal_relaxed")
    hist = pl.concat([myields.historical_table(periods, c).with_columns(pl.lit(c).alias("commission_assumed"))
                      for c in mcfg["commissions"]])
    grid = myields.scenario_grid({"status_quo_2.5%": 0.025, "hsp029_target_1.6%": 0.016}, inp["realized_to_cap"],
                                 inp["burn_rate"], [0.0, inp["buyback_yield"]], mcfg["staking_ratios"],
                                 inp["treasury_share"], mcfg["commissions"])
    return {"model_yields_history": hist, "model_yields_scenarios": grid}


def build(raw: Path, processed: Path, reports: Path, *, daily: pl.DataFrame, epochs: pl.DataFrame,
          peers: pl.DataFrame, as_of: str, fp: pl.DataFrame) -> dict[str, Path]:
    mcfg = config.load()["models"]
    written: dict[str, Path] = {}

    def w(name: str, df: pl.DataFrame | None, sort_by: list[str] | None = None) -> None:
        if df is None or not isinstance(df, pl.DataFrame):
            return
        p = processed / f"{name}.csv"
        io.write_csv(df, p, sort_by=sort_by)
        written[f"{name}.csv"] = p

    org = organic.build(raw, daily, as_of)
    ic = intents_check.build(raw, daily)
    led = ledgers.build(raw, daily, epochs)
    dev = {}
    if (raw / "github" / "contributor_weeks.csv").exists():
        dev["dev_github_monthly"] = devactivity.github_monthly(raw)
        dev["dev_github_summary"] = devactivity.github_summary(raw, as_of)
    if (raw / "opendevdata" / "eco_mads_monthly.csv").exists():
        eco = devactivity.ecosystem_monthly(raw)
        dev["dev_ecosystem_monthly"] = eco
        dev["dev_ecosystem_share_quarterly"] = devactivity.share_trend(eco)

    iq = intents_quarterly(daily, as_of)
    inp = model_inputs(raw, daily, epochs, as_of, led, ic)
    sm = run_supply_models(inp, mcfg)
    mm = run_multiples(daily, peers)
    am = run_adoption(org, daily, as_of, mcfg)
    ym = run_yields(epochs, inp, mcfg, as_of, led)
    inputs_df = pl.DataFrame([{"parameter": k, "value": (None if v is None or isinstance(v, str) else float(v)),
                               "text": v if isinstance(v, str) else ""} for k, v in inp.items()])

    for k, v in org.items():
        w(f"organic_{k}", v)
    for k, v in ic.items():
        w(f"intents_check_{k}", v)
    for k, v in led.items():
        if not k.startswith("_"):  # "_flows" duplicates data/raw/fastnear_tx/wallet_flows.csv row by row: not written
            w(f"ledger_{k}", v)
    for k, v in dev.items():
        w(k, v)
    for group in (sm, mm, am, ym):
        for k, v in group.items():
            w(k, v)
    w("model_inputs", inputs_df)
    w("intents_quarterly", iq)

    T = report2.headline_metrics(org=org, ic=ic, led=led, dev=dev, inp=inp, sm=sm, mm=mm, am=am, ym=ym, fp=fp,
                                 as_of=as_of)
    w("metrics_phase2", T)
    reports.mkdir(parents=True, exist_ok=True)
    pa = reports / "analysis_summary.md"
    fs = report2.falsifier_status(org=org, ic=ic, led=led, dev=dev, sm=sm, mm=mm, ym=ym, iq=iq, inp=inp,
                                  census=io.read_csv(raw / "fastnear_tx" / "monthly_receiver_counts.csv"), daily=daily)
    w("falsifier_status", fs)
    pa.write_text(report2.render_analysis(org=org, ic=ic, led=led, dev=dev, T=T, as_of=as_of, fs=fs))
    written["analysis_summary.md"] = pa
    pred = preds.build(raw=raw, daily=daily, org=org, led=led, dev=dev, mm=mm, am=am, as_of=as_of)
    w("predictions", pred)
    thesis = reports.parent / "thesis"
    thesis.mkdir(parents=True, exist_ok=True)
    pf = thesis / "falsifiers.md"
    pf.write_text(report2.render_falsifiers(pred, io.sha256_file(written["predictions.csv"]), as_of))
    written["falsifiers.md"] = pf
    pm = reports / "models_summary.md"
    pm.write_text(report2.render_models(inp=inp, sm=sm, mm=mm, am=am, ym=ym, T=T, mcfg=mcfg, as_of=as_of))
    written["models_summary.md"] = pm
    return written
