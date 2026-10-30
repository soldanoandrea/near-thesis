"""Tidy daily table: one row per (date, chain, metric, source). Units are explicit; nothing is filled or smoothed.

Daily values dated D cover the UTC day D (flows) or the state at 00:00 UTC of D (prices, TVL, supply snapshots,
following each provider's convention). Rows after the as-of date (the last complete UTC day before the earliest
fetch) are dropped so that partial days never enter a sum.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from .. import io

YOCTO = 1e24

NEARBLOCKS_FIELDS = {
    # raw column: (metric, unit, scale, zero_is_missing)
    "txns": ("txns", "count", 1.0, False),
    "active_accounts": ("active_accounts", "count", 1.0, False),
    "new_accounts": ("new_accounts", "count", 1.0, False),
    "deleted_accounts": ("deleted_accounts", "count", 1.0, False),
    "active_contracts": ("active_contracts", "count", 1.0, False),
    "new_contracts": ("new_contracts", "count", 1.0, False),
    "blocks": ("blocks", "count", 1.0, False),
    "total_supply": ("total_supply", "NEAR", 1 / YOCTO, False),
    "circulating_supply": ("circulating_supply", "NEAR", 1 / YOCTO, False),
    "txn_fee": ("tx_fees", "NEAR", 1 / YOCTO, False),
    "gas_fee": ("gas_fees", "NEAR", 1 / YOCTO, False),
    "txn_fee_usd": ("tx_fees_usd", "USD", 1.0, True),
    "near_price": ("price_usd", "USD", 1.0, True),
    "market_cap": ("market_cap_usd", "USD", 1.0, True),
}

AURORA_FIELDS = {"newTxns": ("txns", "count"), "activeAccounts": ("active_accounts", "count"),
                 "newAccounts": ("new_accounts", "count"), "txnsFee": ("tx_fees_eth", "ETH")}

SCHEMA = {"date": pl.Utf8, "chain": pl.Utf8, "metric": pl.Utf8, "source": pl.Utf8, "value": pl.Float64,
          "unit": pl.Utf8}


def _frame(df: pl.DataFrame, chain: str | pl.Expr, metric: str, source: str, value: pl.Expr, unit: str) -> pl.DataFrame:
    chain_expr = chain if isinstance(chain, pl.Expr) else pl.lit(chain)
    return df.select(pl.col("date"), chain_expr.alias("chain"), pl.lit(metric).alias("metric"),
                     pl.lit(source).alias("source"), value.cast(pl.Float64).alias("value"), pl.lit(unit).alias("unit"))


def nearblocks(raw: Path) -> list[pl.DataFrame]:
    nb = io.read_csv(raw / "nearblocks" / "charts_daily.csv")
    out = []
    for col, (metric, unit, scale, zero_missing) in NEARBLOCKS_FIELDS.items():
        v = pl.col(col).cast(pl.Float64) * scale
        if zero_missing:
            v = pl.when(pl.col(col).cast(pl.Float64) > 0).then(v).otherwise(None)
        out.append(_frame(nb, "near", metric, "nearblocks", v, unit))
    return out


def defillama(raw: Path) -> list[pl.DataFrame]:
    d = raw / "defillama"
    out = []
    tvl = io.read_csv(d / "chain_tvl_daily.csv")
    out.append(_frame(tvl, pl.col("chain"), "tvl_usd", "defillama", pl.col("tvl_usd"), "USD"))

    fees = io.read_csv(d / "chain_fees_daily.csv")
    for data_type, metric in (("dailyFees", "chain_fees_usd"), ("dailyRevenue", "chain_revenue_usd")):
        f = fees.filter(pl.col("data_type") == data_type)
        out.append(_frame(f, pl.col("chain"), metric, "defillama", pl.col("value_usd"), "USD"))

    dex = io.read_csv(d / "dex_volume_daily.csv")
    out.append(_frame(dex, pl.col("chain"), "dex_volume_usd", "defillama", pl.col("volume_usd"), "USD"))
    bd = io.read_csv(d / "dex_volume_near_by_protocol_daily.csv").with_columns(pl.col("volume_usd").cast(pl.Float64))
    ex = (bd.group_by("date").agg(pl.col("volume_usd").filter(pl.col("protocol") != "NEAR Intents").sum()
                                  .alias("v")))
    out.append(_frame(ex, "near", "dex_volume_ex_intents_usd", "defillama", pl.col("v"), "USD"))

    st = io.read_csv(d / "stablecoins_daily.csv")
    out.append(_frame(st, pl.col("chain"), "stablecoins_usd", "defillama", pl.col("circulating_usd"), "USD"))

    it = io.read_csv(d / "near_intents_daily.csv")
    for data_type, metric in (("dailyVolume", "intents_volume_usd"), ("dailyFees", "intents_fees_usd"),
                              ("dailyRevenue", "intents_revenue_usd"),
                              ("dailyHoldersRevenue", "intents_holders_revenue_usd")):
        f = it.filter(pl.col("data_type") == data_type)
        if f.height:
            out.append(_frame(f, "near", metric, "defillama", pl.col("value_usd"), "USD"))

    # coins.llama.fi: keep the earliest sample of each UTC day (closest to 00:00, like the other providers)
    px = (io.read_csv(d / "coin_prices_daily.csv").with_columns(pl.col("timestamp").cast(pl.Int64))
          .sort(["chain", "timestamp"]).group_by(["chain", "date"], maintain_order=True).first())
    out.append(_frame(px, pl.col("chain"), "price_usd", "defillama", pl.col("price_usd"), "USD"))
    return out


def coingecko(raw: Path) -> list[pl.DataFrame]:
    cg = (io.read_csv(raw / "coingecko" / "market_chart_365d.csv")
          .with_columns(pl.col("timestamp_ms").cast(pl.Int64))
          .filter(pl.col("timestamp_ms") % 86_400_000 == 0))  # drop the intraday "live" point
    return [_frame(cg, pl.col("chain"), m, "coingecko", pl.col(c), "USD")
            for m, c in (("price_usd", "price_usd"), ("market_cap_usd", "market_cap_usd"),
                         ("volume_usd", "volume_usd"))]


def aurora(raw: Path) -> list[pl.DataFrame]:
    a = io.read_csv(raw / "aurora" / "stats_lines_daily.csv").filter(pl.col("is_approximate") != "true")
    out = []
    for line, (metric, unit) in AURORA_FIELDS.items():
        f = a.filter(pl.col("metric") == line)
        out.append(_frame(f, "aurora", metric, "aurora_blockscout", pl.col("value"), unit))
    return out


def build_daily_long(raw: Path, as_of: str) -> pl.DataFrame:
    frames = nearblocks(raw) + defillama(raw) + coingecko(raw) + aurora(raw)
    df = pl.concat([f.cast(SCHEMA) for f in frames], how="vertical")
    df = df.filter(pl.col("date") <= as_of)
    # Aurora's stats service starts its lines on 2020-01-01 with zeros before launch: trim leading zeros per series
    df = df.sort(["chain", "metric", "source", "date"])
    started = (pl.col("value").fill_null(0) != 0).cum_max().over(["chain", "metric", "source"])
    df = df.filter(started | (pl.col("source") != "aurora_blockscout"))
    dups = df.group_by(["date", "chain", "metric", "source"]).len().filter(pl.col("len") > 1)
    if dups.height:
        raise ValueError(f"duplicate (date, chain, metric, source) rows:\n{dups.head()}")
    return df


def coverage(daily: pl.DataFrame) -> pl.DataFrame:
    """Per series: span, rows, missing calendar days inside the span, nulls, longest gap."""
    rows = []
    for (chain, metric, source), g in daily.group_by(["chain", "metric", "source"], maintain_order=True):
        dates = g["date"].str.to_date().sort()
        span = (dates[-1] - dates[0]).days + 1
        gaps = dates.diff().dt.total_days().drop_nulls()
        rows.append((chain, metric, source, str(dates[0]), str(dates[-1]), g.height, span - g.height,
                     int(g["value"].null_count()), int(gaps.max() - 1) if len(gaps) else 0))
    return pl.DataFrame(rows, schema={"chain": pl.Utf8, "metric": pl.Utf8, "source": pl.Utf8, "first_date": pl.Utf8,
                                      "last_date": pl.Utf8, "rows": pl.Int64, "missing_days": pl.Int64,
                                      "null_values": pl.Int64, "longest_gap_days": pl.Int64}, orient="row")


def series(daily: pl.DataFrame, chain: str, metric: str, source: str) -> pl.DataFrame:
    """(date: Date, value) for one series, sorted."""
    return (daily.filter((pl.col("chain") == chain) & (pl.col("metric") == metric) & (pl.col("source") == source))
            .select(pl.col("date").str.to_date(), "value").sort("date"))
