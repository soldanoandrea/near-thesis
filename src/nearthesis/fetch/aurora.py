"""Aurora (source #19): Blockscout stats-service daily lines (full history) and the /api/v2/stats snapshot. Keyless."""

from __future__ import annotations

import datetime as dt

import polars as pl

from .. import config, manifest
from ..http import PoliteClient

HOST = "explorer.mainnet.aurora.dev"
LINES = ("newTxns", "activeAccounts", "newAccounts", "txnsFee")


def fetch(client: PoliteClient) -> None:
    ep = config.load()["endpoints"]
    today = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    rows, urls = [], []
    for line in LINES:
        url = f"{ep['aurora_stats']}/lines/{line}"
        params = {"resolution": "DAY", "from": "2020-01-01", "to": today}
        urls.append(f"{url}?resolution=DAY&from=2020-01-01&to=<fetch date>")
        d = client.get_json(url, params=params)
        for p in d.get("chart", []):
            rows.append((p["date"], line, p["value"], bool(p.get("is_approximate", False))))
    df = pl.DataFrame(rows, schema={"date": pl.Utf8, "metric": pl.Utf8, "value": pl.Utf8, "is_approximate": pl.Boolean},
                      orient="row")
    manifest.save_table("aurora", "stats_lines_daily", df, urls=urls, sort_by=["metric", "date"],
                        notes="Blockscout stats-service lines (resolution=DAY). txnsFee is in ETH (Aurora's gas "
                              "token). Rows flagged is_approximate (the current day) are dropped in processing.",
                        http_stats=client.stats_for(HOST))
    url = f"{ep['aurora_api']}/stats"
    d = client.get_json(url)
    keys = ["total_addresses", "total_blocks", "total_transactions", "transactions_today", "average_block_time"]
    df = pl.DataFrame({k: [str(d.get(k))] for k in keys})
    manifest.save_table("aurora", "stats_snapshot", df, urls=[url], notes="Current Blockscout counters.",
                        http_stats=client.stats_for(HOST))
