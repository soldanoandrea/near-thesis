"""No-gap checks on daily series. Gaps are never filled; these series must be complete over their span."""

import datetime as dt

import polars as pl
import pytest

CORE = [
    ("near", "txns", "nearblocks"), ("near", "active_accounts", "nearblocks"), ("near", "total_supply", "nearblocks"),
    ("near", "circulating_supply", "nearblocks"), ("near", "tx_fees", "nearblocks"),
    ("near", "tvl_usd", "defillama"), ("near", "chain_fees_usd", "defillama"), ("near", "dex_volume_usd", "defillama"),
    ("near", "stablecoins_usd", "defillama"), ("near", "intents_volume_usd", "defillama"),
    ("near", "price_usd", "coingecko"), ("near", "market_cap_usd", "coingecko"),
]


@pytest.mark.parametrize("chain,metric,source", CORE)
def test_core_series_have_no_gaps(processed, chain, metric, source):
    cov = processed("series_coverage.csv")
    r = cov.filter((pl.col("chain") == chain) & (pl.col("metric") == metric) & (pl.col("source") == source))
    assert r.height == 1, "series missing"
    assert r["missing_days"][0] == 0, f"{r.to_dicts()[0]}"


def test_nearblocks_starts_at_genesis_and_is_fresh(processed):
    cov = processed("series_coverage.csv")
    r = cov.filter((pl.col("source") == "nearblocks") & (pl.col("metric") == "txns")).row(0, named=True)
    assert r["first_date"] == "2020-07-21"
    fp = processed("metrics_first_pass.csv")
    assert r["last_date"] >= str(dt.date.fromisoformat(r["first_date"]) + dt.timedelta(days=2000))


def test_every_month_has_census_and_sample(processed):
    m = processed("activity_monthly.csv")
    months = m["month"].to_list()
    assert months == sorted(months)
    y, mo = map(int, months[0].split("-"))
    for got in months:
        assert got == f"{y:04d}-{mo:02d}", f"month gap before {got}"
        y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
    assert (m["sample_blocks"] >= 25).all()


def test_epoch_samples_are_regular(processed):
    e = processed("epochs.csv").sort("start_height")
    gaps = e["start_height"].diff().drop_nulls()
    assert gaps.min() > 0
    assert gaps.max() < 40 * 43_200, "a sampling gap larger than 40 epochs"
