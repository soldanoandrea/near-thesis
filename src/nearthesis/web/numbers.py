"""Every number the thesis and the dashboard print, with the processed table it comes from.

The registry is filled from data/processed only (plus the frozen thesis/predictions.csv and the subjective weights in
thesis/valuation_priors.toml, both committed files): every metric of metrics_first_pass.csv and metrics_phase2.csv
under its metric_id, plus named values read from other processed tables. thesis/THESIS.in.md refers to them as
`{{key}}` (value), `{{key:ci}}` (90% interval), `{{key:abs}}` (absolute value), `{{key:p1}}` / `{{key:p0}}` (percent
with 1 / 0 decimals), `{{key:sp0}}` (signed percent) or `{{key:x}}` (multiple); `make site` substitutes them, so no number in THESIS.md is typed.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

import polars as pl

from .. import accounts, io
from ..report import fmt

TOKEN = re.compile(r"\{\{([A-Za-z0-9_./%+-]+)(?::([a-z0-9]+))?\}\}")


@dataclass
class Num:
    key: str
    value: float | str | None
    unit: str
    source: str
    ci_low: float | None = None
    ci_high: float | None = None


def show(n: Num, mod: str | None = None) -> str:
    """Format a registry value for prose. Uses the reports' formatter so the essay and the reports print alike."""
    v, unit = n.value, n.unit
    if unit == "text":
        return str(v)
    if v is None:
        return "n/a"
    if mod == "ci":
        if n.ci_low is None or n.ci_high is None:
            raise KeyError(f"{n.key} has no interval")
        return f"{show(Num(n.key, n.ci_low, unit, n.source))} to {show(Num(n.key, n.ci_high, unit, n.source))}"
    if mod == "abs":
        return show(Num(n.key, abs(float(v)), unit, n.source))
    if mod in ("p1", "p0"):
        return f"{float(v) * 100:.{1 if mod == 'p1' else 0}f}%"
    if mod == "sp0":
        return f"{float(v) * 100:+.0f}%"
    if mod == "x" or unit == "multiple":
        x = float(v)
        return f"{x:,.0f}x" if abs(x) >= 100 else f"{x:.1f}x"
    if mod == "int":
        return f"{float(v):,.0f}"
    if unit == "prob":
        return f"{float(v):.2f}"
    if unit == "pp":
        return f"{float(v) * 100:+.2f} pp"
    if unit == "years":
        return f"{float(v):g}"
    if unit == "count" and isinstance(v, float) and abs(v) >= 100:
        return f"{v:,.0f}"
    return fmt(v, unit)


class Registry:
    def __init__(self) -> None:
        self.items: dict[str, Num] = {}

    def add(self, key: str, value, unit: str, source: str, ci_low=None, ci_high=None) -> None:
        if key in self.items:
            raise ValueError(f"duplicate number key {key}")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value = float(value)
        self.items[key] = Num(key, value, unit, source, ci_low, ci_high)

    def get(self, key: str) -> Num:
        if key not in self.items:
            raise KeyError(f"unknown number '{key}' (not in the registry built from data/processed)")
        return self.items[key]

    def fmt(self, key: str, mod: str | None = None) -> str:
        return show(self.get(key), mod)

    def render(self, text: str) -> tuple[str, list[tuple[str, str | None]]]:
        """Replace every {{key[:mod]}} token. Returns the text and the tokens used, in order of first use."""
        used: list[tuple[str, str | None]] = []

        def sub(m: re.Match) -> str:
            k = (m.group(1), m.group(2))
            if k not in used:
                used.append(k)
            return self.fmt(*k)
        return TOKEN.sub(sub, text), used


def _f(x) -> float | None:
    if x is None or x == "":
        return None
    v = float(x)
    return None if v != v else v  # NaN -> None


def _csv(processed: Path, name: str) -> pl.DataFrame:
    return pl.read_csv(processed / name, infer_schema_length=None)


def build(processed: Path, thesis_dir: Path, manifest: dict) -> Registry:
    R = Registry()
    P = lambda name, what: f"data/processed/{name}: {what}"  # noqa: E731

    # --- every generated headline metric, under its own id ------------------------------------------------------
    for name in ("metrics_first_pass.csv", "metrics_phase2.csv"):
        for r in _csv(processed, name).iter_rows(named=True):
            R.add(r["metric_id"], _f(r["value"]), r["unit"], P(name, f"metric_id = {r['metric_id']}"),
                  _f(r["ci90_low"]), _f(r["ci90_high"]))

    inp = {r["parameter"]: (r["text"] or _f(r["value"])) for r in _csv(processed, "model_inputs.csv").iter_rows(named=True)}
    for k, unit in (("market_cap", "USD"), ("price", "USD"), ("intents_revenue_annualized_90d", "USD"),
                    ("intents_volume_annualized_90d", "USD"), ("intents_fees_annualized_90d", "USD"),
                    ("take_rate_90d", "bp"), ("buyback_yield_onchain", "ratio"),
                    ("buyback_near_per_year_onchain", "NEAR"), ("supply0", "NEAR"), ("staking_ratio", "ratio"),
                    ("hsp029_status", "text"), ("hsp029_snapshot_utc", "text"), ("as_of", "text")):
        R.add(f"in.{k}", inp[k], unit, P("model_inputs.csv", f"parameter = {k}"))

    R.add("in.capture_share", float(inp["intents_revenue_annualized_90d"]) / float(inp["intents_fees_annualized_90d"]), "ratio",
          P("model_inputs.csv", "intents_revenue_annualized_90d / intents_fees_annualized_90d"))
    trl = _csv(processed, "ledger_trails.csv")
    R.add("tr.exchange_like_stops", trl.filter(pl.col("stop_reason").str.starts_with("busy_account")
                                               | (pl.col("out_counterparty_class") == "intents")).height, "count",
          P("ledger_trails.csv", "rows whose trail stops at an exchange-like account (busy_account) or goes into NEAR Intents"))

    # --- Q1: class shares and signers ----------------------------------------------------------------------------
    oq = _csv(processed, "organic_quarterly.csv").filter(pl.col("months") == 3)
    for q in ("2025-Q1", "2026-Q3"):
        r = oq.filter(pl.col("quarter") == q).row(0, named=True)
        tag = q.replace("-", "").lower()
        for c in ("organic", "automated", "incentivized", "infrastructure", "account_setup"):
            R.add(f"oq.{tag}.share_{c}", r[f"tx_share_{c}"], "ratio",
                  P("organic_quarterly.csv", f"quarter = {q}, tx_share_{c}"), r[f"tx_share_{c}_p05"],
                  r[f"tx_share_{c}_p95"])
        R.add(f"oq.{tag}.das_all", r["das_all"], "count", P("organic_quarterly.csv", f"quarter = {q}, das_all"),
              r["das_all_p05"], r["das_all_p95"])
    for r in oq.iter_rows(named=True):
        tag = r["quarter"].replace("-", "").lower()
        R.add(f"oq.{tag}.das_organic", r["das_organic"], "count", P("organic_quarterly.csv", f"quarter = {r['quarter']}, das_organic"),
              r["das_organic_p05"], r["das_organic_p95"])
    since = oq.filter(pl.col("quarter") >= "2025-Q3")
    R.add("oq.from2025q3.das_organic_min", since["das_organic"].min(), "count",
          P("organic_quarterly.csv", "min das_organic over the full quarters from 2025-Q3"))
    R.add("oq.from2025q3.das_organic_max", since["das_organic"].max(), "count",
          P("organic_quarterly.csv", "max das_organic over the full quarters from 2025-Q3"))
    dr = _csv(processed, "organic_draws.csv")
    for q, months in (("2025-Q1", ["2025-01", "2025-02", "2025-03"]), ("2026-Q3", ["2026-07", "2026-08", "2026-09"])):
        x = dr.filter(pl.col("month").is_in(months))
        tag = q.replace("-", "").lower()
        R.add(f"draws.{tag}.all", x.height, "count", P("organic_draws.csv", f"rows, {months[0]} to {months[-1]}"))
        R.add(f"draws.{tag}.organic", x.filter(pl.col("account_label") == "organic").height, "count",
              P("organic_draws.csv", f"account_label = organic, {months[0]} to {months[-1]}"))
    om = _csv(processed, "organic_monthly.csv").filter(pl.col("is_partial_month").cast(pl.Utf8).str.to_lowercase() == "false"
                                                       ).sort("month").tail(6)
    R.add("om.das_to_nearblocks.last6", om["das_all_to_nearblocks"].median(), "multiple",
          P("organic_monthly.csv", "median das_all_to_nearblocks, last six complete months"))
    R.add("om.last6.first_month", om["month"][0], "text", P("organic_monthly.csv", "first of the last six complete months"))
    R.add("om.last6.last_month", om["month"][-1], "text", P("organic_monthly.csv", "last complete month"))
    am = _csv(processed, "activity_monthly.csv")
    q3 = am.filter(pl.col("month").is_in(["2026-07", "2026-08", "2026-09"]))
    R.add("act.2026q3.chain_signatures_share", q3["census_v1_signer"].sum() / q3["nb_txns"].sum(), "ratio",
          P("activity_monthly.csv", "sum(census_v1_signer) / sum(nb_txns), 2026-07 to 2026-09"))
    R.add("act.2026q3.nb_txns_per_day", q3["nb_txns"].sum() / q3["nb_days"].sum(), "count",
          P("activity_monthly.csv", "sum(nb_txns) / sum(nb_days), 2026-07 to 2026-09"))
    q1_25 = am.filter(pl.col("month").is_in(["2025-01", "2025-02", "2025-03"]))
    R.add("act.2025q1.nb_txns_per_day", q1_25["nb_txns"].sum() / q1_25["nb_days"].sum(), "count",
          P("activity_monthly.csv", "sum(nb_txns) / sum(nb_days), 2025-01 to 2025-03"))
    sens = _csv(processed, "organic_cohorts.csv")
    R.add("coh.informative_cohorts", sens.filter((pl.col("group") == "all") & (pl.col("horizon_months") == 3)
                                                 & (pl.col("new_signer_draws") >= 20)).height, "count",
          P("organic_cohorts.csv", "cohorts with >= 20 new-signer draws (group all, horizon 3)"))

    # --- Q2: Intents ---------------------------------------------------------------------------------------------
    d = _csv(processed, "intents_check_days.csv")
    R.add("ic.days", d.height, "count", P("intents_check_days.csv", "rows (sampled days)"))
    R.add("ic.ratio_min", d["ratio_sample_to_defillama"].min(), "ratio", P("intents_check_days.csv", "min ratio_sample_to_defillama"))
    R.add("ic.ratio_max", d["ratio_sample_to_defillama"].max(), "ratio", P("intents_check_days.csv", "max ratio_sample_to_defillama"))
    R.add("ic.days_one_sided_ci_has_100", d.filter((pl.col("ratio_sample_to_defillama_p05") <= 1)
                                                   & (pl.col("ratio_sample_to_defillama_p95") >= 1)).height, "count",
          P("intents_check_days.csv", "days whose one-sided 90% CI contains 100%"))
    R.add("ic.days_two_sided_ci_has_100", d.filter((pl.col("ratio_two_sided_to_defillama_p05") <= 1)
                                                   & (pl.col("ratio_two_sided_to_defillama_p95") >= 1)).height, "count",
          P("intents_check_days.csv", "days whose two-sided 90% CI contains 100%"))
    R.add("ic.days_two_sided_below_100", d.filter(pl.col("ratio_two_sided_to_defillama_p95") < 1).height, "count",
          P("intents_check_days.csv", "days whose two-sided 90% CI lies wholly below 100%"))
    R.add("ic.sampled_txs", d["sampled_txs"].sum(), "count", P("intents_check_days.csv", "sum(sampled_txs)"))
    R.add("ic.netting_median", d["netting_ratio"].median(), "ratio", P("intents_check_days.csv", "median netting_ratio"))
    iq = _csv(processed, "intents_quarterly.csv")
    for q in ("2026-Q2", "2026-Q3"):
        r = iq.filter(pl.col("quarter") == q).row(0, named=True)
        tag = q.replace("-", "").lower()
        R.add(f"iq.{tag}.volume", r["volume"], "USD", P("intents_quarterly.csv", f"quarter = {q}, volume"))
        R.add(f"iq.{tag}.volume_qoq", r["volume_qoq"], "ratio", P("intents_quarterly.csv", f"quarter = {q}, volume_qoq"))
        R.add(f"iq.{tag}.revenue_qoq", r["revenue_qoq"], "ratio", P("intents_quarterly.csv", f"quarter = {q}, revenue_qoq"))
        R.add(f"iq.{tag}.revenue_take_rate", r["revenue_take_rate"], "bp",
              P("intents_quarterly.csv", f"quarter = {q}, revenue_take_rate"))
        R.add(f"iq.{tag}.fee_take_rate", r["fee_take_rate"], "bp", P("intents_quarterly.csv", f"quarter = {q}, fee_take_rate"))

    # --- Q4: revenue, buybacks, treasury ---------------------------------------------------------------------------
    rr = _csv(processed, "ledger_revenue_reconciliation.csv").filter(pl.col("usd_defillama") > 1000)
    R.add("rev.months", rr.height, "count", P("ledger_revenue_reconciliation.csv", "months with DefiLlama revenue > $1k"))
    R.add("rev.ratio_min", rr["onchain_to_defillama"].min(), "ratio", P("ledger_revenue_reconciliation.csv", "min onchain_to_defillama"))
    R.add("rev.ratio_max", rr["onchain_to_defillama"].max(), "ratio", P("ledger_revenue_reconciliation.csv", "max onchain_to_defillama"))
    R.add("rev.first_month", rr["month"][0], "text", P("ledger_revenue_reconciliation.csv", "first month with revenue"))
    R.add("rev.last_month", rr["month"][-1], "text", P("ledger_revenue_reconciliation.csv", "last month (partial: to the fetch day)"))
    R.add("rev.usd_onchain_total", rr["usd_onchain"].sum(), "USD", P("ledger_revenue_reconciliation.csv", "sum usd_onchain"))
    R.add("rev.usd_defillama_total", rr["usd_defillama"].sum(), "USD", P("ledger_revenue_reconciliation.csv", "sum usd_defillama"))
    lm = (_csv(processed, "ledger_monthly.csv")
          .filter(pl.col("wallet").is_in(accounts.REVENUE_WALLETS) & (pl.col("direction") == "in")
                  & (pl.col("flow_type") == "transfer") & (pl.col("asset_group") == "NEAR")
                  & (pl.col("counterparty_class") != "revenue_wallet"))
          .with_columns((pl.col("counterparty_class") == "intents").alias("from_intents")))
    src = "ledger_monthly.csv"
    for tag, a, b in (("early", rr["month"][0], "2026-03"), ("recent", "2026-04", rr["month"][-1])):
        w = lm.filter((pl.col("month") >= a) & (pl.col("month") <= b))
        R.add(f"rev.src_intents_share.{tag}", w.filter(pl.col("from_intents"))["usd"].sum() / w["usd"].sum(), "ratio",
              P(src, f"USD share of revenue-rule NEAR inflows from intents.near, {a} to {b}"))
        R.add(f"rev.src.{tag}.first_month", a, "text", P(src, f"first month of the {tag} window"))
        R.add(f"rev.src.{tag}.last_month", b, "text", P(src, f"last month of the {tag} window"))
    per = (lm.filter(pl.col("month").is_in(rr["month"].to_list())).group_by("month")
           .agg((pl.col("usd") * pl.col("from_intents")).sum().alias("i"), pl.col("usd").sum().alias("t")))
    R.add("rev.months_mostly_other", per.filter(pl.col("i") < 0.5 * pl.col("t")).height, "count",
          P(src, "months with DefiLlama revenue > $1k in which under half of the captured NEAR came from intents.near"))
    bb = _csv(processed, "ledger_buyback_summary.csv").row(0, named=True)
    R.add("bb.sent_out", bb["buyback_wallet_near_transfers_out_since_start"], "NEAR",
          P("ledger_buyback_summary.csv", "buyback_wallet_near_transfers_out_since_start"))
    to = _csv(processed, "ledger_treasury_outflows.csv").filter(pl.col("date") >= "2026-04-01")
    for m, label in (("2026-04", "apr"), ("2026-05", "may")):
        t = to.filter(pl.col("date").str.starts_with(m))
        R.add(f"tr.{label}_tranche", t["amount"].sum(), "NEAR", P("ledger_treasury_outflows.csv", f"sum amount, {m}"))
    te = _csv(processed, "ledger_trail_endpoints.csv")
    for acc, label in (("p2p-org.poolv1.near", "p2p"), ("figment.poolv1.near", "figment")):
        R.add(f"tr.pool_{label}", te.filter(pl.col("endpoint") == acc)["near"].sum(), "NEAR",
              P("ledger_trail_endpoints.csv", f"endpoint = {acc}"))
    unf = te.filter(pl.col("how").str.starts_with("not followed")).sort("near", descending=True)
    R.add("tr.largest_unfollowed", unf["near"][0], "NEAR", P("ledger_trail_endpoints.csv", "largest 'not followed' endpoint"))
    R.add("tr.no_outflow_seen", te.filter(pl.col("how") == "no_outflow_seen")["near"].sum(), "NEAR",
          P("ledger_trail_endpoints.csv", "sum near where how = no_outflow_seen"))
    tl = _csv(processed, "ledger_trails.csv")
    nf = tl.filter(pl.col("account") == "nfendowment03.near")
    R.add("tr.nfendowment03_received", nf["received_near"].max(), "NEAR",
          P("ledger_trails.csv", "account = nfendowment03.near, received_near"))
    R.add("tr.nfendowment03_sent", nf.filter(pl.col("out_asset") == "NEAR")["out_near"].sum(), "NEAR",
          P("ledger_trails.csv", "account = nfendowment03.near, sum out_near"))
    R.add("tr.accounts_followed", tl["account"].n_unique(), "count", P("ledger_trails.csv", "distinct accounts followed"))
    R.add("tr.nfendowment03_recipients", nf.filter(pl.col("out_asset") == "NEAR")["out_counterparty"].n_unique(), "count",
          P("ledger_trails.csv", "account = nfendowment03.near, distinct NEAR counterparties"))

    # --- models -----------------------------------------------------------------------------------------------------
    sc = _csv(processed, "model_supply_scenarios.csv")
    for s in sc.iter_rows(named=True):
        base = f"sc.{s['scenario']}.{int(s['horizon_years'])}y"
        R.add(f"{base}.float_cagr", s["float_growth_cagr"], "ratio", P("model_supply_scenarios.csv",
              f"scenario = {s['scenario']}, horizon_years = {s['horizon_years']}, float_growth_cagr"))
        R.add(f"{base}.supply_cagr", s["supply_growth_cagr"], "ratio", P("model_supply_scenarios.csv",
              f"scenario = {s['scenario']}, horizon_years = {s['horizon_years']}, supply_growth_cagr"))
    spar = _csv(processed, "model_supply_parameters.csv")
    for lvl in ("low", "base", "high"):
        r = spar.filter(pl.col("scenario") == f"status_quo/{lvl}").row(0, named=True)
        R.add(f"par.revenue_change.{lvl}", r["revenue_growth"] - 1, "ratio",
              P("model_supply_parameters.csv", f"scenario = status_quo/{lvl}, revenue_growth - 1 (per year)"))
    grid = _csv(processed, "model_net_zero_grid.csv")
    price = float(inp["price"])
    g = grid.filter(((pl.col("price_usd") - price).abs() < 1e-6) & ((pl.col("take_rate") - float(inp["take_rate_90d"])).abs() < 1e-9))
    for r in g.iter_rows(named=True):
        tag = "sq" if r["issuance_rate"] > 0.02 else "hsp"
        R.add(f"nz.{tag}.required_revenue", r["required_revenue_usd"], "USD",
              P("model_net_zero_grid.csv", f"current price and take rate, issuance_rate = {r['issuance_rate']:.4f}"))
        R.add(f"nz.{tag}.issuance_rate", r["issuance_rate"], "ratio",
              P("model_net_zero_grid.csv", f"issuance_rate (realized share of the {'2.5%' if tag == 'sq' else '1.6%'} cap)"))
    nv = _csv(processed, "model_multiples_near_vs_peers.csv")
    for r in nv.iter_rows(named=True):
        base = f"mv.{r['variant']}.{r['basis']}"
        R.add(f"{base}.peer_median", r["peer_median"], "multiple", P("model_multiples_near_vs_peers.csv", f"{base[3:]}, peer_median"))
        R.add(f"{base}.peer_min", r["peer_min"], "multiple", P("model_multiples_near_vs_peers.csv", f"{base[3:]}, peer_min"))
        R.add(f"{base}.peer_max", r["peer_max"], "multiple", P("model_multiples_near_vs_peers.csv", f"{base[3:]}, peer_max"))
        R.add(f"{base}.near", r["near_multiple"], "multiple", P("model_multiples_near_vs_peers.csv", f"{base[3:]}, near_multiple"))
        R.add(f"{base}.mcap_at_median", r["implied_mcap_at_peer_median"], "USD",
              P("model_multiples_near_vs_peers.csv", f"{base[3:]}, implied_mcap_at_peer_median"))
    bt = _csv(processed, "model_adoption_backtest.csv").filter(pl.col("series") == "organic_daily_active_signers_3m")
    for r in bt.iter_rows(named=True):
        R.add(f"bt.das.{r['model']}.{r['horizon']}m", r["mean_abs_log_error"], "count",
              P("model_adoption_backtest.csv", f"organic_daily_active_signers_3m, {r['model']}, horizon {r['horizon']}"))
        R.add(f"bt.das.{r['model']}.{r['horizon']}m.n", r["forecasts"], "count",
              P("model_adoption_backtest.csv", f"organic_daily_active_signers_3m, {r['model']}, horizon {r['horizon']}, forecasts"))
    bti = _csv(processed, "model_adoption_backtest.csv").filter(pl.col("series") == "intents_monthly_volume_usd")
    for r in bti.iter_rows(named=True):
        R.add(f"bt.iv.{r['model']}.{r['horizon']}m", r["mean_abs_log_error"], "count",
              P("model_adoption_backtest.csv", f"intents_monthly_volume_usd, {r['model']}, horizon {r['horizon']}"))
    fc = _csv(processed, "model_adoption_forecasts.csv").filter(
        (pl.col("series") == "organic_daily_active_signers_3m") & (pl.col("model") == "loglinear"))
    for r in fc.iter_rows(named=True):
        h = int(r["horizon_months"])
        R.add(f"fc.das.{h}m", r["p50"], "count", P("model_adoption_forecasts.csv",
              f"organic_daily_active_signers_3m, loglinear, {h} months, p50 (p05-p95 as interval)"), r["p05"], r["p95"])
    ys = _csv(processed, "model_yields_scenarios.csv")
    for pol, tag in (("hsp029_target_1.6%", "hsp"), ("status_quo_2.5%", "sq")):
        r = ys.filter((pl.col("policy") == pol) & (pl.col("buyback_rate") > 0) & ((pl.col("staking_ratio") - 0.45).abs() < 1e-9)
                      & ((pl.col("commission") - 0.05).abs() < 1e-9)).row(0, named=True)
        R.add(f"ys.{tag}.real_staker", r["real_staker_yield"], "ratio", P("model_yields_scenarios.csv",
              f"{pol}, current buybacks, staking 45%, commission 5%, real_staker_yield"))
        R.add(f"ys.{tag}.non_staker", r["real_non_staker_yield"], "ratio", P("model_yields_scenarios.csv",
              f"{pol}, current buybacks, staking 45%, commission 5%, real_non_staker_yield"))

    # --- Q6 developers -----------------------------------------------------------------------------------------
    ds = _csv(processed, "dev_ecosystem_share_quarterly.csv").filter(pl.col("ecosystem") == "near")
    for q in ("2025-Q3", "2026-Q3"):
        r = ds.filter(pl.col("quarter") == q).row(0, named=True)
        R.add(f"dev.{q.replace('-', '').lower()}.to_peers", r["near_to_peer_set"], "ratio",
              P("dev_ecosystem_share_quarterly.csv", f"near, {q}, near_to_peer_set"))

    # --- falsifiers and predictions -------------------------------------------------------------------------------
    fs = _csv(processed, "falsifier_status.csv")
    st = fs["status"].to_list()
    R.add("fs.rows", len(st), "count", P("falsifier_status.csv", "rows"))
    R.add("fs.met", sum(s.startswith("met") for s in st), "count", P("falsifier_status.csv", "status starts with 'met'"))
    R.add("fs.half", sum(s.startswith("half") for s in st), "count", P("falsifier_status.csv", "status starts with 'half'"))
    R.add("fs.not_met", sum(s.startswith("not met") for s in st), "count", P("falsifier_status.csv", "status starts with 'not met'"))
    R.add("fs.not_assessed", sum(s.startswith("not assessed") for s in st), "count", P("falsifier_status.csv", "status 'not assessed'"))
    pp = thesis_dir / "predictions.csv"
    if pp.exists():
        pr = pl.read_csv(pp, infer_schema_length=None)
        R.add("pred.count", pr.height, "count", "thesis/predictions.csv: rows")
        R.add("pred.sha256", io.sha256_file(pp), "text", "sha256 of thesis/predictions.csv")
        for r in pr.iter_rows(named=True):
            unit = {"count": "count", "USD": "USD", "bp": "bp", "ratio": "ratio", "multiple": "multiple"}[r["unit"]]
            R.add(f"pred.{r['id']}.threshold", r["threshold"], unit, f"thesis/predictions.csv: {r['id']}, threshold")
            R.add(f"pred.{r['id']}.current", r["current_value"], unit, f"thesis/predictions.csv: {r['id']}, current_value")
            R.add(f"pred.{r['id']}.date", r["check_date"], "text", f"thesis/predictions.csv: {r['id']}, check_date")

    # --- subjective weights over model scenarios (thesis/valuation_priors.toml) ---------------------------------------
    vp_path = thesis_dir / "valuation_priors.toml"
    if vp_path.exists():
        vp = tomllib.loads(vp_path.read_text())
        pol, rev = vp["policy"], vp["revenue_path"]
        src = "thesis/valuation_priors.toml"
        for k, v in pol.items():
            R.add(f"vp.policy.{k}", v, "prob", f"{src}: [policy] {k}")
        for k, v in rev.items():
            R.add(f"vp.revenue.{k}", v, "prob", f"{src}: [revenue_path] {k}")
        h = int(vp["horizon_years"])
        R.add("vp.horizon", h, "years", f"{src}: horizon_years")
        exp, cover, lo, hi = 0.0, 0.0, None, None
        for p, wp in pol.items():
            for lvl, wr in rev.items():
                r = sc.filter((pl.col("scenario") == f"{p}/{lvl}") & (pl.col("horizon_years") == h)).row(0, named=True)
                exp += wp * wr * r["float_growth_cagr"]
                cover += wp * wr * (str(r["offsets_cover_issuance"]).lower() == "true")
                lo = r["float_growth_cagr"] if lo is None else min(lo, r["float_growth_cagr"])
                hi = r["float_growth_cagr"] if hi is None else max(hi, r["float_growth_cagr"])
        both = f"{src} weights x data/processed/model_supply_scenarios.csv (horizon {h})"
        R.add("vp.float_cagr_expected", exp, "ratio", f"{both}: probability-weighted float_growth_cagr", lo, hi)
        R.add("vp.p_offsets_cover", cover, "prob", f"{both}: weight of branches with offsets_cover_issuance in year {h}")
        R.add("vp.p_hsp", sum(v for k, v in pol.items() if k.startswith("hsp029")), "prob", f"{src}: sum of hsp029 weights")

    # --- snapshot --------------------------------------------------------------------------------------------------
    files = manifest["files"]
    fetched = sorted(v["fetched_at_utc"] for v in files.values())
    R.add("snap.files", len(files), "count", "data/raw/MANIFEST.json: files")
    R.add("snap.rows", sum(v["rows"] for v in files.values()), "count", "data/raw/MANIFEST.json: sum of rows")
    R.add("snap.first_fetch", fetched[0], "text", "data/raw/MANIFEST.json: earliest fetched_at_utc")
    R.add("snap.last_fetch", fetched[-1], "text", "data/raw/MANIFEST.json: latest fetched_at_utc")
    return R


def provenance_rows(R: Registry, used: list[tuple[str, str | None]]) -> list[list[str]]:
    seen, rows = set(), []
    for key, _mod in used:
        if key in seen:
            continue
        seen.add(key)
        n = R.get(key)
        val = show(n)
        if n.ci_low is not None and n.ci_high is not None and n.unit != "text":
            val += f" ({show(n, 'ci')})"
        rows.append([key, val, n.source])
    return rows


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
