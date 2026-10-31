"""Phase 2a: sampling design, analysis tables and cross-checks. Tolerances are stated, not tuned to pass silently."""

import polars as pl
import pytest

from nearthesis import config, paths, sampling


def _metric(fp: pl.DataFrame, mid: str):
    r = fp.filter(pl.col("metric_id") == mid)
    assert r.height == 1, mid
    return r.row(0, named=True)


# ------------------------------------------------------------------------------------------------ sampling design
def test_signer_draws_are_deterministic_and_inside_the_block_sample():
    blocks, txs = sampling.load_block_sample(paths.RAW)
    cfg, seed = config.load()["signers"], int(config.load()["activity"]["seed"])
    a = sampling.draw_signers(blocks, txs, cfg, seed)
    b = sampling.draw_signers(blocks, txs, cfg, seed)
    assert a.equals(b)
    assert a.join(txs, on=["month", "block_key", "transaction_hash"], how="anti").height == 0
    per = a.group_by("month").len()
    assert per.filter(pl.col("month") >= cfg["recent_first_month"])["len"].min() == cfg["draws_recent"]
    assert not a.select("month", "transaction_hash").is_duplicated().any(), "draws are without replacement"


def test_extra_block_sample_widens_recent_months():
    blocks, _ = sampling.load_block_sample(paths.RAW)
    cfg = config.load()["signers"]
    recent = blocks.filter(pl.col("month") >= cfg["extra_first_month"]).group_by("month").len()
    assert recent["len"].min() >= 30 + cfg["extra_blocks_per_month"] - 3  # a few base months have 28-29 blocks


# ------------------------------------------------------------------------------------------------ Q1 organic
def test_organic_shares_and_intervals(processed):
    m = processed("organic_monthly.csv")
    classes = ("organic", "automated", "incentivized", "infrastructure", "account_setup")
    for k in classes:
        assert m[f"tx_share_{k}"].is_between(0, 1).all()
        assert (m[f"tx_share_{k}_p05"] <= m[f"tx_share_{k}"] + 1e-9).all()
        assert (m[f"tx_share_{k}"] <= m[f"tx_share_{k}_p95"] + 1e-9).all()
    total = sum(m[f"tx_share_{k}"] for k in classes)
    assert ((total - 1).abs() < 1e-6).all(), "tx classes must partition the draws (CSV floats have 8 decimals)"
    assert (m["mas_organic"] <= m["mas_all"] + 1e-6).all()
    assert (m["das_organic"] <= m["das_all"] + 1e-6).all()


def test_daily_signers_bounded_by_transactions(processed):
    """Identity: every daily active signer signs at least one transaction that day, so the estimate of distinct real
    signers per day cannot exceed transactions per day (also in each bootstrap bound)."""
    m = processed("organic_monthly.csv")
    tpd = m["nb_txns"] / m["nb_days"]
    assert (m["das_all"] <= tpd + 1e-6).all()
    assert (m["das_all_p95"] <= tpd + 1e-6).all()
    assert (m["mas_all"] <= m["nb_txns"] + 1e-6).all()


def test_cohort_retention_bounds(processed):
    c = processed("organic_cohorts.csv")
    assert c["retention"].is_between(0, 1).all()
    assert (c["retention_p05"] <= c["retention"] + 1e-9).all() and (c["retention"] <= c["retention_p95"] + 1e-9).all()
    # rolling retention can only fall with the horizon, cohort by cohort
    w = c.filter(pl.col("group") == "all").pivot(on="horizon_months", index="cohort", values="retention").drop_nulls()
    if w.height and {"1", "3"} <= set(w.columns):
        assert (w["1"] + 1e-9 >= w["3"]).all()


# ------------------------------------------------------------------------------------------------ Q2 intents
def test_intents_check_days(processed):
    d = processed("intents_check_days.csv")
    assert d.height == config.load()["intents_check"]["days"]
    assert (d["fee_paying_txs"] > 0).all() and (d["sampled_txs"] > 100).all()
    assert (d["volume_sample_p05"] <= d["volume_sample_usd"]).all()
    assert (d["volume_sample_usd"] <= d["volume_sample_p95"]).all()
    assert d["netting_ratio"].is_between(0.05, 1.0).all(), "one-sided volume must be a fraction of gross sold legs"
    assert (d["unpriced_leg_share"] < 0.2).all()


# ------------------------------------------------------------------------------------------------ Q4 money trails
def test_revenue_rebuilt_onchain_matches_defillama(processed):
    """DefiLlama's revenue is NEAR swept into three wallets: our on-chain rebuild must match within 10% over 6 months."""
    fp = processed("metrics_phase2.csv")
    v = _metric(fp, "q4b.revenue_onchain_to_defillama")["value"]
    assert abs(v - 1) < 0.10, v


def test_treasury_balance_reconciles_with_rewards(processed):
    """Archival balance changes of treasury.near minus transaction flows = 10% reward share (within 5%, median)."""
    t = processed("ledger_treasury_reconciliation.csv").drop_nulls("implied_to_expected")
    assert t.height >= 12
    assert abs(t["implied_to_expected"].median() - 1) < 0.05


def test_ledger_flows_are_positive_and_classified(processed):
    f = processed("ledger_monthly.csv")
    assert (f.drop_nulls("amount")["amount"] >= 0).all()
    assert set(f["flow_type"].unique()) <= {"swap_leg", "custody", "transfer"}
    assert set(f["direction"].unique()) <= {"in", "out"}


# ------------------------------------------------------------------------------------------------ Q6 developers
def test_developer_shares(processed):
    e = processed("dev_ecosystem_monthly.csv")
    assert e["share_of_web3_devs"].drop_nulls().is_between(0, 1).all()
    near = e.filter(pl.col("ecosystem") == "near")
    assert near.height >= 60 and (near["all_devs"] > 0).all()
    g = processed("dev_github_summary.csv")
    assert {"near/nearcore", "near/intents"} <= set(g["repo"])


# ------------------------------------------------------------------------------------------------ models outputs
def test_model_tables_present_and_consistent(processed):
    s = processed("model_supply_scenarios.csv")
    assert set(s["horizon_years"]) == set(config.load()["models"]["horizons_years"])
    sq = s.filter(pl.col("scenario") == "status_quo/base").sort("horizon_years")
    hs = s.filter(pl.col("scenario") == "hsp029_act3m/base").sort("horizon_years")
    assert (hs["total_supply"] <= sq["total_supply"] + 1e-6).all()
    assert (s["float_supply"] <= s["total_supply"] + 1e-6).all()
    y = processed("model_yields_history.csv")
    assert y["gross_staker_yield"].drop_nulls().is_between(0, 0.2).all()
    m = processed("model_multiples.csv")
    assert (m["multiple"].drop_nulls() > 0).all()


def test_phase2_metrics_schema(processed):
    fp = processed("metrics_phase2.csv")
    assert fp["metric_id"].is_duplicated().sum() == 0
    assert set(fp["grade"].unique()) <= {"A", "B", "A/B", "model"}
    ci = fp.with_columns(pl.col("ci90_low").cast(pl.Float64), pl.col("ci90_high").cast(pl.Float64)).drop_nulls(
        ["ci90_low", "ci90_high"])
    assert (ci["ci90_low"] <= ci["ci90_high"] + 1e-9).all()
