"""First-pass metrics for the PIANO.md section 2 questions that keyless sources can answer (phase 1).

Every number here is computed from data/raw via the transforms; nothing is typed by hand. Each metric carries its
source and an evidence grade: A = on-chain / re-runnable from chain data, B = aggregator (DefiLlama, NearBlocks,
CoinGecko, Blockscout).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl

from . import io
from .transform.daily import series

YOCTO = 1e24


def _d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def wsum(ser: pl.DataFrame, end: dt.date, days: int) -> tuple[float | None, int]:
    start = end - dt.timedelta(days=days - 1)
    w = ser.filter((pl.col("date") >= start) & (pl.col("date") <= end)).drop_nulls("value")
    return (float(w["value"].sum()) if w.height else None), w.height


def wmean(ser: pl.DataFrame, end: dt.date, days: int) -> float | None:
    s, n = wsum(ser, end, days)
    return s / n if n else None


def at(ser: pl.DataFrame, day: dt.date) -> float | None:
    w = ser.filter(pl.col("date") == day).drop_nulls("value")
    return float(w["value"][0]) if w.height else None


def full_wsum(ser: pl.DataFrame, end: dt.date, days: int, min_cov: float = 0.97) -> float | None:
    s, n = wsum(ser, end, days)
    return s if n >= min_cov * days else None


def ratio(a: float | None, b: float | None) -> float | None:
    return a / b if a is not None and b not in (None, 0) else None


def growth(a: float | None, b: float | None) -> float | None:
    r = ratio(a, b)
    return r - 1 if r is not None else None


@dataclass
class MetricTable:
    rows: list[dict] = field(default_factory=list)

    def add(self, question: str, metric_id: str, label: str, value, unit: str, window: str, source: str,
            grade: str, ci_low=None, ci_high=None, notes: str = "") -> None:
        self.rows.append({"question": question, "metric_id": metric_id, "label": label,
                          "value": None if value is None else float(value), "ci90_low": ci_low, "ci90_high": ci_high,
                          "unit": unit, "window": window, "source": source, "grade": grade, "notes": notes})

    def frame(self) -> pl.DataFrame:
        return pl.DataFrame(self.rows, schema={"question": pl.Utf8, "metric_id": pl.Utf8, "label": pl.Utf8,
                                               "value": pl.Float64, "ci90_low": pl.Float64, "ci90_high": pl.Float64,
                                               "unit": pl.Utf8, "window": pl.Utf8, "source": pl.Utf8,
                                               "grade": pl.Utf8, "notes": pl.Utf8})


# ------------------------------------------------------------------------------------------------ peers / ratios
PEER_CHAINS = ["near", "solana", "sui", "aptos", "base", "ethereum", "tron"]


def peers_as_of(daily: pl.DataFrame, as_of: str) -> str:
    """Last date present in every peer chain's TVL, chain-fee and DEX series (comparability across chains)."""
    last = (daily.filter(pl.col("chain").is_in(PEER_CHAINS) & (pl.col("source") == "defillama")
                         & pl.col("metric").is_in(["tvl_usd", "chain_fees_usd", "dex_volume_usd"]))
            .group_by(["chain", "metric"]).agg(pl.col("date").max()))
    return min(as_of, str(last["date"].min()))


def build_peers(daily: pl.DataFrame, as_of_peers: str) -> pl.DataFrame:
    end = _d(as_of_peers)
    yago = end - dt.timedelta(days=365)
    rows = []
    for c in PEER_CHAINS:
        tvl = series(daily, c, "tvl_usd", "defillama")
        fees = series(daily, c, "chain_fees_usd", "defillama")
        rev = series(daily, c, "chain_revenue_usd", "defillama")
        dex = series(daily, c, "dex_volume_usd", "defillama")
        st = series(daily, c, "stablecoins_usd", "defillama")
        mc = series(daily, c, "market_cap_usd", "coingecko")
        px = series(daily, c, "price_usd", "coingecko")
        f30, f365 = full_wsum(fees, end, 30), full_wsum(fees, end, 365)
        d30 = full_wsum(dex, end, 30)
        mcap = at(mc, end)
        row = {
            "chain": c,
            "as_of": as_of_peers,
            "price_usd": at(px, end),
            "market_cap_usd": mcap,
            "tvl_usd": at(tvl, end),
            "stablecoins_usd": at(st, end),
            "chain_fees_30d_usd": f30,
            "chain_fees_365d_usd": f365,
            "chain_revenue_365d_usd": full_wsum(rev, end, 365),
            "dex_volume_30d_usd": d30,
            "dex_volume_30d_ex_intents_usd": (full_wsum(series(daily, "near", "dex_volume_ex_intents_usd",
                                                               "defillama"), end, 30) if c == "near" else None),
            "fees_30d_annualized_to_mcap": ratio(f30 * 365 / 30 if f30 is not None else None, mcap),
            "fees_365d_to_mcap": ratio(f365, mcap),
            "tvl_to_mcap": ratio(at(tvl, end), mcap),
            "stablecoins_to_mcap": ratio(at(st, end), mcap),
            "dex_volume_30d_to_tvl": ratio(d30, at(tvl, end)),
            "tvl_yoy": growth(at(tvl, end), at(tvl, yago)),
            "chain_fees_30d_yoy": growth(f30, full_wsum(fees, yago, 30)),
            "dex_volume_30d_yoy": growth(d30, full_wsum(dex, yago, 30)),
            "stablecoins_yoy": growth(at(st, end), at(st, yago)),
        }
        rows.append(row)
    return pl.DataFrame(rows, infer_schema_length=None)


def build_ratios_daily(daily: pl.DataFrame) -> pl.DataFrame:
    """Daily price-normalized ratios: trailing-30d fees annualized / market cap, TVL / market cap, etc.

    Peers use CoinGecko market caps (365-day keyless window); NEAR also gets a full-history variant with the
    NearBlocks market cap.
    """
    out = []
    specs = [(c, "coingecko") for c in PEER_CHAINS if c != "base"] + [("near", "nearblocks")]
    for chain, mc_source in specs:
        mc = series(daily, chain, "market_cap_usd", mc_source).rename({"value": "mcap"})
        if mc.is_empty():
            continue
        f = series(daily, chain, "chain_fees_usd", "defillama").rename({"value": "fees"})
        tvl = series(daily, chain, "tvl_usd", "defillama").rename({"value": "tvl"})
        dex = series(daily, chain, "dex_volume_usd", "defillama").rename({"value": "dex"})
        st = series(daily, chain, "stablecoins_usd", "defillama").rename({"value": "stable"})
        cal = pl.DataFrame({"date": pl.date_range(f["date"].min() if f.height else mc["date"].min(),
                                                  mc["date"].max(), "1d", eager=True)})
        j = (cal.join(f, on="date", how="left").join(dex, on="date", how="left")
             .with_columns(pl.col("fees").rolling_sum(30, min_samples=30).alias("fees30"),
                           pl.col("dex").rolling_sum(30, min_samples=30).alias("dex30"))
             .join(mc, on="date", how="inner").join(tvl, on="date", how="left").join(st, on="date", how="left"))
        j = j.with_columns((pl.col("fees30") * 365 / 30 / pl.col("mcap")).alias("fees_30d_annualized_to_mcap"),
                           (pl.col("tvl") / pl.col("mcap")).alias("tvl_to_mcap"),
                           (pl.col("stable") / pl.col("mcap")).alias("stablecoins_to_mcap"),
                           (pl.col("dex30") / pl.col("tvl")).alias("dex_volume_30d_to_tvl"))
        long = j.select("date", "fees_30d_annualized_to_mcap", "tvl_to_mcap", "stablecoins_to_mcap",
                        "dex_volume_30d_to_tvl").unpivot(index="date", variable_name="metric", value_name="value")
        out.append(long.drop_nulls("value").with_columns(pl.lit(chain).alias("chain"),
                                                         pl.lit(mc_source).alias("mcap_source")))
    df = pl.concat(out).with_columns(pl.col("date").cast(pl.Utf8))
    return df.select("date", "chain", "metric", "mcap_source", "value")


# ------------------------------------------------------------------------------------------------ supply helpers
def protocol_events(epochs: pl.DataFrame) -> pl.DataFrame:
    """Changes of max_inflation_rate between consecutive sampled epochs (bracketed by sample dates)."""
    e = epochs.select("start_utc", "start_height", "max_inflation_rate").drop_nulls("max_inflation_rate")
    rows = []
    prev = None
    for r in e.iter_rows(named=True):
        if prev is not None and r["max_inflation_rate"] != prev["max_inflation_rate"]:
            rows.append({"from_rate": prev["max_inflation_rate"], "to_rate": r["max_inflation_rate"],
                         "last_sample_before_utc": prev["start_utc"], "first_sample_after_utc": r["start_utc"],
                         "height_before": prev["start_height"], "height_after": r["start_height"]})
        prev = r
    return pl.DataFrame(rows, schema={"from_rate": pl.Float64, "to_rate": pl.Float64,
                                      "last_sample_before_utc": pl.Utf8, "first_sample_after_utc": pl.Utf8,
                                      "height_before": pl.Int64, "height_after": pl.Int64})


def burn_vs_fees(epochs: pl.DataFrame, daily: pl.DataFrame) -> pl.DataFrame:
    """Per sampled epoch: exact burn (headers) vs NearBlocks fees prorated to the epoch's time window."""
    tx = {r[0]: r[1] for r in series(daily, "near", "tx_fees", "nearblocks").iter_rows()}
    gas = {r[0]: r[1] for r in series(daily, "near", "gas_fees", "nearblocks").iter_rows()}
    rows = []
    for r in epochs.iter_rows(named=True):
        t0 = dt.datetime.fromisoformat(r["start_utc"].replace("Z", "+00:00"))
        t1 = t0 + dt.timedelta(hours=r["duration_hours"])
        f_tx = f_gas = 0.0
        covered = True
        day = t0.date()
        while day <= t1.date():
            d0 = dt.datetime.combine(day, dt.time(), dt.UTC)
            ov = (min(t1, d0 + dt.timedelta(days=1)) - max(t0, d0)).total_seconds()
            if ov > 0:
                if day not in tx or day not in gas:
                    covered = False
                    break
                f_tx += tx[day] * ov / 86400
                f_gas += gas[day] * ov / 86400
            day += dt.timedelta(days=1)
        rows.append({"start_height": r["start_height"], "start_date": r["start_date"], "burn_near": r["burn_near"],
                     "nb_tx_fees_near": f_tx if covered else None, "nb_gas_fees_near": f_gas if covered else None,
                     "burn_to_tx_fees": (r["burn_near"] / f_tx) if covered and f_tx > 0 else None,
                     "burn_to_gas_fees": (r["burn_near"] / f_gas) if covered and f_gas > 0 else None})
    return pl.DataFrame(rows, infer_schema_length=None)


def treasury_monthly(raw: Path) -> pl.DataFrame:
    p = raw / "rpc_archival" / "treasury_monthly.csv"
    if not p.exists():
        return pl.DataFrame()
    t = io.read_csv(p)
    return t.with_columns(
        pl.col("boundary_utc").str.slice(0, 10).alias("date"),
        (pl.col("amount_yocto").cast(pl.Float64) / YOCTO).alias("liquid_near"),
        (pl.col("locked_yocto").cast(pl.Float64) / YOCTO).alias("locked_near"),
    ).select("date", "account_id", "exists", "liquid_near", "locked_near").sort(["account_id", "date"])
