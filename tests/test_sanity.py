"""Sanity ranges and cross-source agreement. Tolerances are stated, not tuned to pass silently."""

import polars as pl


def _metric(fp: pl.DataFrame, mid: str):
    r = fp.filter(pl.col("metric_id") == mid)
    assert r.height == 1, mid
    return r["value"][0]


def test_supply_identity_holds_exactly(processed):
    e = processed("epochs.csv").drop_nulls("block_identity_holds")
    assert e.height >= 100
    assert e["block_identity_holds"].all(), "supply(b) != supply(prev) - balance_burnt(b) for some sampled block"


def test_supply_ranges(processed):
    e = processed("epochs.csv")
    assert e["supply_start_near"].is_between(999_000_000, 1_500_000_000).all()
    assert (e["burn_near"] >= 0).all() and (e["mint_next_near"] >= 0).all()
    minting = e.filter(pl.col("reward_formula") != "none")
    assert minting["realized_to_cap"].is_between(0.80, 1.01).all(), minting.filter(
        ~pl.col("realized_to_cap").is_between(0.80, 1.01)).select("start_date", "reward_formula", "realized_to_cap")
    # no minting only at the very start (before inflation was switched on in late 2020)
    first_mint = minting["start_height"].min()
    assert (e.filter(pl.col("start_height") > first_mint)["reward_formula"] != "none").all()
    s = e.drop_nulls("staking_ratio")
    assert s["staking_ratio"].is_between(0.2, 0.8).all()
    assert s["num_validators"].is_between(20, 1000).all()


def test_archival_supply_matches_nearblocks(processed):
    """Header total_supply at epoch start vs NearBlocks daily total_supply on that date: within 0.1%."""
    e = processed("epochs.csv").select(pl.col("start_date").cast(pl.Utf8).alias("date"), "supply_start_near")
    d = (processed("daily_long.csv").filter((pl.col("metric") == "total_supply") & (pl.col("source") == "nearblocks"))
         .select(pl.col("date").cast(pl.Utf8), "value"))
    j = e.join(d, on="date")
    assert j.height >= 100
    rel = (j["value"] / j["supply_start_near"] - 1).abs()
    assert rel.max() < 1e-3, j.with_columns(rel.alias("rel")).sort("rel").tail(3)


def test_fee_sources_agree_within_5pct(processed):
    fp = processed("metrics_first_pass.csv")
    for mid in ("q5.fee_sources_ratio_30d", "q5.fee_sources_ratio_365d"):
        v = _metric(fp, mid)
        assert abs(v - 1) < 0.05, f"{mid} = {v}"


def test_price_sources_agree(processed):
    d = processed("daily_long.csv").filter((pl.col("chain") == "near") & (pl.col("metric") == "price_usd"))
    w = d.pivot(on="source", index="date", values="value").drop_nulls()
    rel = (w["nearblocks"] / w["coingecko"] - 1).abs()
    assert rel.median() < 0.01
    rel2 = (w["defillama"] / w["coingecko"] - 1).abs()
    assert rel2.median() < 0.01


def test_burn_share_plausible(processed):
    fp = processed("metrics_first_pass.csv")
    v = _metric(fp, "q5.burn_share_of_fees_365d")
    assert 0.3 < v <= 1.0, v


def test_shares_and_intervals(processed):
    q = processed("activity_quarterly_sample.csv")
    for c in ("hot", "relayed", "implicit_signer", "other_direct_named"):
        sub = q.drop_nulls(f"{c}_share")
        assert sub[f"{c}_share"].is_between(0, 1).all()
        assert (sub[f"{c}_share_p05"] <= sub[f"{c}_share"] + 1e-12).all()
        assert (sub[f"{c}_share"] <= sub[f"{c}_share_p95"] + 1e-12).all()
    m = processed("activity_monthly.csv").drop_nulls("share_tracked_total")
    assert m["share_tracked_total"].is_between(0, 1.0).all()


def test_census_validates_sampling(processed):
    """Exact HOT counts should fall inside the sample's 90% CI in most months (nominal 90%)."""
    fp = processed("metrics_first_pass.csv")
    assert _metric(fp, "q1.sample_validation_hot") >= 0.75


def test_peer_table_complete(processed):
    p = processed("peers_snapshot.csv")
    assert set(p["chain"]) >= {"near", "solana", "sui", "aptos", "base"}
    tok = p.filter(pl.col("chain") != "base")
    assert tok["market_cap_usd"].drop_nulls().len() == tok.height
    assert (p["tvl_usd"] > 0).all() and (p["chain_fees_30d_usd"] > 0).all()
