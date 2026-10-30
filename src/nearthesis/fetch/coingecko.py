"""CoinGecko public API without key (source #13): market chart for the last 365 days (price, market cap, volume).

Keyless access refuses ranges older than 365 days (error 10012), so full price history comes from DefiLlama coins
and NearBlocks. Market caps for peers are only available for this 365-day window.
"""

from __future__ import annotations

import datetime as dt

import polars as pl

from .. import config, manifest
from ..http import PoliteClient

HOST = "api.coingecko.com"


def fetch(client: PoliteClient) -> None:
    cfg = config.load()
    base = cfg["endpoints"]["coingecko"]
    rows, urls = [], []
    for c in cfg["chains"]:
        cid = c["coingecko"]
        if not cid:
            continue
        url = f"{base}/coins/{cid}/market_chart"
        params = {"vs_currency": "usd", "days": "365", "interval": "daily"}
        urls.append(f"{url}?vs_currency=usd&days=365&interval=daily")
        d = client.get_json(url, params=params)
        caps = {int(t): v for t, v in d.get("market_caps", [])}
        vols = {int(t): v for t, v in d.get("total_volumes", [])}
        for t, p in d.get("prices", []):
            t = int(t)
            rows.append((c["chain"], cid, t, dt.datetime.fromtimestamp(t / 1000, dt.UTC).strftime("%Y-%m-%d"),
                         float(p), caps.get(t), vols.get(t)))
    df = pl.DataFrame(rows, schema={"chain": pl.Utf8, "coin_id": pl.Utf8, "timestamp_ms": pl.Int64, "date": pl.Utf8,
                                    "price_usd": pl.Float64, "market_cap_usd": pl.Float64, "volume_usd": pl.Float64},
                      orient="row")
    manifest.save_table("coingecko", "market_chart_365d", df, urls=urls, sort_by=["chain", "timestamp_ms"],
                        notes="Keyless /coins/<id>/market_chart?days=365&interval=daily. Points are 00:00 UTC except "
                              "the last one, which is the live price at fetch time (dropped in processing).",
                        http_stats=client.stats_for(HOST))
