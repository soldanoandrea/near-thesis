"""Model unit tests on synthetic inputs (no data files needed): known answers, invariants, determinism."""

import math

import numpy as np
import polars as pl
import pytest

from nearthesis.models import adoption, multiples, supply, yields


# ------------------------------------------------------------------------------------------------ (a) supply
def test_cap_paths():
    assert supply.cap_path(0, "status_quo", 3) == 0.025
    assert supply.cap_path(3, "hsp029", 3) == 0.025          # activation month: ramp starts
    assert supply.cap_path(15, "hsp029", 3) == pytest.approx(0.0205)  # halfway
    assert supply.cap_path(27, "hsp029", 3) == pytest.approx(0.016)
    assert supply.cap_path(100, "hsp029", 3) == pytest.approx(0.016)
    with pytest.raises(ValueError):
        supply.cap_path(0, "nope", 3)


def test_project_compounds_and_buybacks_only_touch_float():
    p = supply.project(1000.0, 12, policy="status_quo")
    assert p["total_supply"][-1] == pytest.approx(1000 * (1 + 0.025 / 12) ** 12)
    assert (p["float_supply"] == p["total_supply"]).all()
    q = supply.project(1000.0, 12, policy="status_quo", buyback_yield=0.01)
    assert q["total_supply"][-1] == pytest.approx(p["total_supply"][-1])
    assert q["float_supply"][-1] < q["total_supply"][-1]
    r = supply.project(1000.0, 12, policy="status_quo", burn_rate=0.025)
    assert r["total_supply"][-1] == pytest.approx(1000.0)  # burn exactly offsets issuance


def test_hsp029_issues_less_than_status_quo():
    sc = [{"scenario": "a", "policy": "status_quo"}, {"scenario": "b", "policy": "hsp029", "activation_month": 3}]
    t = supply.scenario_table(1000.0, sc, [1, 5])
    s5 = t.filter(pl.col("horizon_years") == 5).sort("scenario")
    assert s5["total_supply"][1] < s5["total_supply"][0]
    assert s5.filter(pl.col("policy") == "hsp029")["year_issuance_rate"][0] == pytest.approx(0.016, rel=0.02)
    assert not t["offsets_cover_issuance"].any()


def test_net_zero_threshold_arithmetic():
    r = supply.net_zero_threshold(supply=1000, price=2.0, issuance_rate=0.025, burn_rate=0.005, take_rate=0.001,
                                  buyback_share=1.0, revenue_now_usd=10.0)
    assert r["required_revenue_usd"] == pytest.approx(40.0)
    assert r["required_volume_usd"] == pytest.approx(40_000.0)
    assert r["multiple_of_current_revenue"] == pytest.approx(4.0)


# ------------------------------------------------------------------------------------------------ (b) multiples
def _peer_inputs():
    base = {"revenue_30d": None, "revenue_365d": None, "intents_fees_30d": None, "intents_fees_365d": None,
            "intents_revenue_30d": None, "intents_revenue_365d": None}
    return pl.DataFrame([
        {**base, "chain": "near", "market_cap_usd": 1000.0, "fees_30d": 3.0, "fees_365d": 40.0, "revenue_30d": 2.0,
         "revenue_365d": 20.0, "intents_fees_30d": 6.0, "intents_fees_365d": 60.0, "intents_revenue_30d": 3.0,
         "intents_revenue_365d": 30.0},
        {**base, "chain": "p1", "market_cap_usd": 500.0, "fees_30d": 3.0, "fees_365d": 50.0, "revenue_30d": 1.0,
         "revenue_365d": 10.0},
        {**base, "chain": "p2", "market_cap_usd": 2000.0, "fees_30d": 6.0, "fees_365d": 100.0, "revenue_30d": 4.0,
         "revenue_365d": 40.0},
    ])


def test_multiples_values():
    m = multiples.multiples(_peer_inputs())
    near = m.filter((pl.col("chain") == "near") & (pl.col("variant") == "fees_plus_intents_fees")
                    & (pl.col("basis") == "365d"))
    assert near["multiple"][0] == pytest.approx(1000 / 100)
    p1 = m.filter((pl.col("chain") == "p1") & (pl.col("variant") == "chain_fees") & (pl.col("basis") == "30d_annualized"))
    assert p1["multiple"][0] == pytest.approx(500 / (3 * 365 / 30))
    assert m.filter(pl.col("chain") == "p1")["variant"].unique().sort().to_list() == ["chain_fees", "chain_revenue"]


def test_near_vs_peers_implied_mcap():
    v = multiples.near_vs_peers(multiples.multiples(_peer_inputs()))
    r = v.filter((pl.col("variant") == "chain_fees") & (pl.col("basis") == "365d")).row(0, named=True)
    assert r["peer_median"] == pytest.approx((10 + 20) / 2)
    assert r["implied_mcap_at_peer_median"] == pytest.approx(40 * 15)
    assert r["near_richer_than_peers"] == pytest.approx(1.0)  # 25x vs 10x and 20x


# ------------------------------------------------------------------------------------------------ (c) adoption
def test_loglinear_recovers_growth():
    t = np.arange(36)
    y = 100 * np.exp(0.05 * t)
    p = adoption.fit("loglinear", t, y)
    assert p["b"] == pytest.approx(0.05, abs=1e-9)


def test_logistic_recovers_s_curve():
    t = np.arange(48)
    y = 1000 / (1 + np.exp(-0.3 * (t - 20)))
    p = adoption.fit("logistic", t, y)
    assert p["K"] == pytest.approx(1000, rel=0.02)
    assert p["r"] == pytest.approx(0.3, rel=0.05)


def test_backtest_prefers_true_model_and_is_out_of_sample():
    rng = np.random.default_rng(1)
    t = np.arange(40)
    y = 50 * np.exp(0.04 * t + rng.normal(0, 0.02, len(t)))
    bt = adoption.backtest(t, y, horizons=(3,), min_train=12)
    s = adoption.backtest_summary(bt)
    best = s.filter(pl.col("horizon") == 3).sort("mean_abs_log_error")["model"][0]
    assert best in ("loglinear", "logistic")
    # out of sample: the first origin uses 12 points and predicts point 14
    assert bt["origin_t"].min() == 11


def test_forecast_ranges_deterministic_and_ordered():
    t = np.arange(30)
    y = 200 * np.exp(-0.03 * t) * np.exp(np.sin(t) * 0.05)
    a = adoption.forecast_ranges(t, y, "loglinear", horizons=(12,), n_boot=200, seed=7)
    b = adoption.forecast_ranges(t, y, "loglinear", horizons=(12,), n_boot=200, seed=7)
    assert a.equals(b)
    r = a.row(0, named=True)
    assert r["p05"] < r["p50"] < r["p95"]
    assert r["p50"] < r["last_value"]  # a declining series is forecast to keep declining


# ------------------------------------------------------------------------------------------------ (d) yields
def test_real_yields_identities():
    r = yields.real_yields(issuance=0.025, burn=0.0005, buyback=0.002, staking_ratio=0.45, treasury_share=0.1,
                           commission=0.05)
    assert r["gross_staker_yield"] == pytest.approx(0.025 * 0.9 / 0.45)
    assert r["net_staker_yield"] == pytest.approx(0.05 * 0.95)
    assert r["float_dilution"] == pytest.approx(0.0225)
    assert r["real_staker_yield"] == pytest.approx(1.0475 / 1.0225 - 1)
    assert r["real_non_staker_yield"] == pytest.approx(1 / 1.0225 - 1)


def test_scenario_grid_shape():
    g = yields.scenario_grid({"status_quo": 0.025, "hsp029_target": 0.016}, 0.996, 0.0004, [0.0, 0.002],
                             [0.4, 0.5], 0.1, [0.0, 0.05])
    assert g.height == 2 * 2 * 2 * 2
    sq = g.filter(pl.col("policy") == "status_quo")["gross_staker_yield"].max()
    hs = g.filter(pl.col("policy") == "hsp029_target")["gross_staker_yield"].max()
    assert hs < sq and math.isclose(hs / sq, 0.016 / 0.025)
