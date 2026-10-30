"""NearBlocks (source #7): /v1/charts (full daily history since 2020-07-21) and /v1/stats (current snapshot).

Free plan without key: 6 req/min, 333/day. We make 2 requests per refresh, 11 s apart. Attribution: data by NearBlocks.
"""

from __future__ import annotations

import polars as pl

from .. import config, manifest
from ..http import PoliteClient

HOST = "api.nearblocks.io"


def _as_str_frame(rows: list[dict]) -> pl.DataFrame:
    cols = list(rows[0].keys())
    return pl.DataFrame({c: [None if r.get(c) is None else str(r[c]) for r in rows] for c in cols},
                        schema={c: pl.Utf8 for c in cols})


def fetch(client: PoliteClient) -> None:
    base = config.load()["endpoints"]["nearblocks"]
    url = f"{base}/charts"
    rows = client.get_json(url)["charts"]
    df = _as_str_frame(rows).with_columns(pl.col("date").str.slice(0, 10))
    manifest.save_table(
        "nearblocks", "charts_daily", df, urls=[url], sort_by=["date"],
        notes="Verbatim /v1/charts rows (all values kept as strings; supply and fee fields are yoctoNEAR). "
              "date truncated to YYYY-MM-DD (UTC day). Data by NearBlocks (attribution required by their free plan).",
        http_stats=client.stats_for(HOST))

    url = f"{base}/stats"
    rows = client.get_json(url)["stats"]
    manifest.save_table(
        "nearblocks", "stats_snapshot", _as_str_frame(rows), urls=[url],
        notes="Current network snapshot (/v1/stats). Not a time series; changes every refresh.",
        http_stats=client.stats_for(HOST))
