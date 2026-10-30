"""Schema checks for raw snapshots and processed tables."""

import polars as pl
import pytest

RAW_COLUMNS = {
    "nearblocks/charts_daily.csv": {"date", "near_price", "market_cap", "total_supply", "circulating_supply", "blocks",
                                    "gas_fee", "txns", "txn_fee", "txn_fee_usd", "new_accounts", "active_accounts"},
    "defillama/chain_tvl_daily.csv": {"chain", "date", "timestamp", "tvl_usd"},
    "defillama/chain_fees_daily.csv": {"chain", "date", "data_type", "value_usd"},
    "defillama/dex_volume_daily.csv": {"chain", "date", "volume_usd"},
    "defillama/dex_volume_near_by_protocol_daily.csv": {"date", "protocol", "volume_usd"},
    "defillama/stablecoins_daily.csv": {"chain", "date", "circulating_usd", "bridged_to_usd"},
    "defillama/near_intents_daily.csv": {"date", "data_type", "value_usd"},
    "defillama/coin_prices_daily.csv": {"chain", "coin", "timestamp", "date", "price_usd"},
    "coingecko/market_chart_365d.csv": {"chain", "coin_id", "timestamp_ms", "date", "price_usd", "market_cap_usd",
                                        "volume_usd"},
    "aurora/stats_lines_daily.csv": {"date", "metric", "value", "is_approximate"},
    "rpc/validators_current.csv": {"account_id", "stake_yocto", "epoch_start_height", "epoch_height"},
    "rpc_archival/epochs_sampled.csv": {"epoch_id", "start_height", "start_timestamp_ns", "supply_start_yocto",
                                        "supply_last_yocto", "supply_next_start_yocto", "burnt_start_block_yocto",
                                        "burnt_next_start_block_yocto", "check_supply_yocto", "check_burnt_yocto",
                                        "max_inflation_rate", "total_stake_yocto", "validators_available"},
    "fastnear_tx/month_boundaries.csv": {"boundary_utc", "height", "block_timestamp_ns"},
    "fastnear_tx/monthly_receiver_counts.csv": {"month", "account_id", "from_height", "to_height_inclusive",
                                                "txs_count"},
    "fastnear_tx/block_sample_blocks.csv": {"month", "draw", "sampled_height", "block_height", "num_transactions"},
    "fastnear_tx/block_sample_txs.csv": {"month", "draw", "block_height", "real_signer_id", "real_receiver_id",
                                         "is_relayed"},
}


@pytest.mark.parametrize("rel,cols", sorted(RAW_COLUMNS.items()))
def test_raw_columns(raw, rel, cols):
    df = raw(rel)
    missing = cols - set(df.columns)
    assert not missing, f"{rel} missing {missing}"
    if "date" in df.columns:
        assert df["date"].str.to_date("%Y-%m-%d", strict=True).null_count() == 0


def test_yocto_fields_are_integers(raw):
    e = raw("rpc_archival/epochs_sampled.csv")
    for c in ("supply_start_yocto", "supply_last_yocto", "supply_next_start_yocto", "check_supply_yocto"):
        assert e[c].str.contains(r"^\d+$").all(), c


def test_daily_long_schema(processed):
    d = processed("daily_long.csv")
    assert d.columns == ["date", "chain", "metric", "source", "value", "unit"]
    assert d["date"].cast(pl.Utf8).str.to_date().null_count() == 0
    assert d.select(["date", "chain", "metric", "source"]).is_duplicated().sum() == 0
    units = d.group_by(["metric", "source"]).agg(pl.col("unit").n_unique())
    assert (units["unit"] == 1).all(), "a metric changes unit inside one source"


def test_metrics_table_schema(processed):
    fp = processed("metrics_first_pass.csv")
    assert {"question", "metric_id", "label", "value", "unit", "window", "source", "grade"} <= set(fp.columns)
    assert fp["metric_id"].is_duplicated().sum() == 0
    assert set(fp["grade"].unique()) <= {"A", "B", "A/B"}
