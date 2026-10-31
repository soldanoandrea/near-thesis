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
    # phase 2a
    "fastnear_tx/block_sample_extra_blocks.csv": {"month", "draw", "sampled_height", "block_height", "num_transactions"},
    "fastnear_tx/block_sample_extra_txs.csv": {"month", "draw", "block_height", "real_signer_id", "real_receiver_id",
                                               "is_relayed", "transaction_hash"},
    "fastnear_tx/signer_month_activity.csv": {"signer_id", "month", "from_height", "to_height_inclusive", "txs_count",
                                              "rows_returned", "ts_first_s", "ts_gaps_s"},
    "fastnear_tx/signer_lifetime.csv": {"signer_id", "lifetime_txs_any_role", "first_height", "first_timestamp_s",
                                        "lifetime_txs_real_signer", "last_signed_height", "last_signed_timestamp_s"},
    "fastnear_tx/signer_tx_details.csv": {"signer_id", "month", "tx_hash", "outer_signer_id", "receiver_id",
                                          "real_receiver_id", "is_relayed", "methods", "action_kinds", "block_height"},
    "fastnear_tx/intents_days.csv": {"day", "from_height", "to_height_exclusive", "fee_pips_start", "fee_collector",
                                     "fee_paying_txs", "intents_receiver_txs"},
    "fastnear_tx/intents_swap_legs.csv": {"day", "tx_no", "event_index", "account_id", "token_id", "amount",
                                          "fee_collected", "referral"},
    "fastnear_tx/intents_swap_txs.csv": {"day", "window", "tx_no", "tx_hash", "block_height", "legs"},
    "fastnear_tx/intents_windows.csv": {"day", "window", "window_start", "window_blocks", "fee_paying_txs_listed",
                                        "txs_fetched"},
    "rpc_archival/intents_fee_collector_balances.csv": {"day", "token_id", "balance_start", "balance_end"},
    "oneclick/tokens.csv": {"assetId", "decimals", "symbol", "coingeckoId"},
    "defillama/coin_prices_intents_days.csv": {"day", "coin", "price_usd", "timestamp"},
    "fastnear_tx/wallet_flows.csv": {"wallet", "tx_hash", "receipt_id", "block_height", "block_timestamp_ns", "kind",
                                     "direction", "counterparty", "asset", "amount_raw", "method"},
    "fastnear_tx/trail_hops.csv": {"depth", "source", "account", "account_class", "received_tx", "received_height",
                                   "received_near_yocto", "out_tx", "out_counterparty", "out_asset", "out_amount_raw",
                                   "stop_reason"},
    "github/repos.csv": {"repo", "group", "created_at", "pushed_at", "stars", "archived"},
    "github/contributor_weeks.csv": {"repo", "author", "week_start", "commits"},
    "github/participation.csv": {"repo", "weeks_ago", "commits_all"},
    "github/releases.csv": {"repo", "tag", "published_at", "prerelease", "draft"},
    "opendevdata/eco_mads_monthly.csv": {"ecosystem", "ecosystem_id", "month", "day", "all_devs", "full_time_devs",
                                         "exclusive_devs"},
    "governance/hsp029_status.csv": {"topic_url", "title", "status", "spec_cap_formula", "activation"},
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


def test_yocto_and_raw_amounts_are_integers(raw):
    """Phase 2a raw amounts are exact integers in the token's smallest unit (no float rounding in data/raw)."""
    f = raw("fastnear_tx/wallet_flows.csv")
    assert f["amount_raw"].str.contains(r"^\d+$").all()
    legs = raw("fastnear_tx/intents_swap_legs.csv")
    assert legs["amount"].str.contains(r"^-?\d+$").all()
    b = raw("rpc_archival/intents_fee_collector_balances.csv")
    assert b["balance_start"].str.contains(r"^\d+$").all() and b["balance_end"].str.contains(r"^\d+$").all()


def test_metrics_table_schema(processed):
    fp = processed("metrics_first_pass.csv")
    assert {"question", "metric_id", "label", "value", "unit", "window", "source", "grade"} <= set(fp.columns)
    assert fp["metric_id"].is_duplicated().sum() == 0
    assert set(fp["grade"].unique()) <= {"A", "B", "A/B"}
