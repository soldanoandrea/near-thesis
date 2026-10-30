"""DefiLlama (source #12): chain TVL, chain fees/revenue, DEX volume, stablecoins, NEAR Intents, daily prices.

All endpoints are keyless. We keep only the time series (`totalDataChart`), not the protocol metadata.
"""

from __future__ import annotations

import datetime as dt

import polars as pl

from .. import config, manifest
from ..http import PoliteClient

HOSTS = ("api.llama.fi", "stablecoins.llama.fi", "coins.llama.fi")


def _day(ts: int | str) -> str:
    return dt.datetime.fromtimestamp(int(float(ts)), dt.UTC).strftime("%Y-%m-%d")


def _tdc(payload: dict) -> list[tuple[str, float]]:
    return [(_day(t), float(v)) for t, v in (payload.get("totalDataChart") or [])]


def fetch(client: PoliteClient) -> None:
    cfg = config.load()
    ep = cfg["endpoints"]
    chains = cfg["chains"]

    # --- TVL -------------------------------------------------------------------------------------------
    rows, urls = [], []
    for c in chains:
        if not c["llama_tvl"]:
            continue
        url = f"{ep['llama']}/v2/historicalChainTvl/{c['llama_tvl']}"
        urls.append(url)
        for r in client.get_json(url):
            rows.append((c["chain"], _day(r["date"]), r["date"], float(r["tvl"])))
    df = pl.DataFrame(rows, schema={"chain": pl.Utf8, "date": pl.Utf8, "timestamp": pl.Int64, "tvl_usd": pl.Float64},
                      orient="row")
    manifest.save_table("defillama", "chain_tvl_daily", df, urls=urls, sort_by=["chain", "date"],
                        notes="historicalChainTvl per chain; DefiLlama default TVL (excludes liquid staking, "
                              "double counts and borrowed by default).", http_stats=client.stats_for(*HOSTS))

    # --- Chain fees & revenue (the L1/L2 itself, category "Chain") --------------------------------------
    rows, urls = [], []
    for c in chains:
        if not c["llama_chain_fees"]:
            continue
        for data_type in ("dailyFees", "dailyRevenue"):
            url = f"{ep['llama']}/summary/fees/{c['llama_chain_fees']}"
            params = {"dataType": data_type}
            urls.append(f"{url}?dataType={data_type}")
            payload = client.get_json(url, params=params)
            rows += [(c["chain"], d, data_type, v) for d, v in _tdc(payload)]
    df = pl.DataFrame(rows, schema={"chain": pl.Utf8, "date": pl.Utf8, "data_type": pl.Utf8, "value_usd": pl.Float64},
                      orient="row")
    manifest.save_table("defillama", "chain_fees_daily", df, urls=urls, sort_by=["chain", "data_type", "date"],
                        notes="summary/fees/<chain> for the chain protocol itself (gas/transaction fees paid to "
                              "the chain). dailyRevenue = DefiLlama's revenue definition for that chain "
                              "(e.g. burned fees). NEAR series sourced by DefiLlama from Allium.",
                        http_stats=client.stats_for(*HOSTS))

    # --- DEX volume per chain ---------------------------------------------------------------------------
    rows, urls, near_bd = [], [], []
    for c in chains:
        if not c["llama_dex"]:
            continue
        url = f"{ep['llama']}/overview/dexs/{c['llama_dex']}"
        with_bd = c["chain"] == "near"
        params = {"excludeTotalDataChart": "false",
                  "excludeTotalDataChartBreakdown": "false" if with_bd else "true"}
        urls.append(f"{url}?excludeTotalDataChart=false&excludeTotalDataChartBreakdown={params['excludeTotalDataChartBreakdown']}")
        payload = client.get_json(url, params=params)
        rows += [(c["chain"], d, v) for d, v in _tdc(payload)]
        if with_bd:
            for t, parts in payload.get("totalDataChartBreakdown") or []:
                for proto, v in parts.items():
                    near_bd.append((_day(t), proto, float(v)))
    df = pl.DataFrame(rows, schema={"chain": pl.Utf8, "date": pl.Utf8, "volume_usd": pl.Float64}, orient="row")
    manifest.save_table("defillama", "dex_volume_daily", df, urls=urls, sort_by=["chain", "date"],
                        notes="overview/dexs/<chain> totalDataChart. For NEAR this INCLUDES NEAR Intents "
                              "(see dex_volume_near_by_protocol_daily).", http_stats=client.stats_for(*HOSTS))
    df = pl.DataFrame(near_bd, schema={"date": pl.Utf8, "protocol": pl.Utf8, "volume_usd": pl.Float64}, orient="row")
    manifest.save_table("defillama", "dex_volume_near_by_protocol_daily", df, urls=[urls[0]],
                        sort_by=["date", "protocol"],
                        notes="totalDataChartBreakdown of overview/dexs/near: daily volume per protocol on NEAR.",
                        http_stats=client.stats_for(*HOSTS))

    # --- Stablecoins ------------------------------------------------------------------------------------
    rows, urls = [], []
    for c in chains:
        if not c["llama_stable"]:
            continue
        url = f"{ep['llama_stablecoins']}/stablecoincharts/{c['llama_stable']}"
        urls.append(url)
        for r in client.get_json(url):
            circ = r.get("totalCirculatingUSD") or {}
            bridged = r.get("totalBridgedToUSD") or {}
            rows.append((c["chain"], _day(r["date"]), float(sum(circ.values())), float(sum(bridged.values()))))
    df = pl.DataFrame(rows, schema={"chain": pl.Utf8, "date": pl.Utf8, "circulating_usd": pl.Float64,
                                    "bridged_to_usd": pl.Float64}, orient="row")
    manifest.save_table("defillama", "stablecoins_daily", df, urls=urls, sort_by=["chain", "date"],
                        notes="stablecoincharts/<chain>: sum over peg types of totalCirculatingUSD.",
                        http_stats=client.stats_for(*HOSTS))

    # --- NEAR Intents (protocol) ------------------------------------------------------------------------
    slug = cfg["intents"]["llama_slug"]
    rows, urls = [], []
    for kind, data_type in (("dexs", "dailyVolume"), ("fees", "dailyFees"), ("fees", "dailyRevenue"),
                            ("fees", "dailyHoldersRevenue")):
        url = f"{ep['llama']}/summary/{kind}/{slug}"
        urls.append(f"{url}?dataType={data_type}")
        try:
            payload = client.get_json(url, params={"dataType": data_type})
        except Exception as exc:  # holders revenue may not be tracked; record and continue
            print(f"  skip {url}?dataType={data_type}: {exc}")
            continue
        rows += [(d, data_type, v) for d, v in _tdc(payload)]
    df = pl.DataFrame(rows, schema={"date": pl.Utf8, "data_type": pl.Utf8, "value_usd": pl.Float64}, orient="row")
    manifest.save_table("defillama", "near_intents_daily", df, urls=urls, sort_by=["data_type", "date"],
                        notes="NEAR Intents via DefiLlama. Upstream is a NEAR-uploaded Dune dataset "
                              "(dimension-adapters dexs/near-intents): single-sourced, grade B.",
                        http_stats=client.stats_for(*HOSTS))

    # --- Daily prices, full history (CoinGecko keyless is limited to 365 days) -------------------------
    rows, urls = [], []
    start0 = int(dt.datetime(2020, 7, 1, tzinfo=dt.UTC).timestamp())
    end = int(dt.datetime.now(dt.UTC).timestamp())
    span = 400
    for c in chains:
        if not c["llama_coin"]:
            continue
        start = start0
        while start < end:
            url = f"{ep['llama_coins']}/chart/{c['llama_coin']}"
            params = {"start": start, "span": span, "period": "1d"}
            urls.append(f"{url}?start={start}&span={span}&period=1d")
            payload = client.get_json(url, params=params)
            pts = (payload.get("coins", {}).get(c["llama_coin"]) or {}).get("prices") or []
            for p in pts:
                rows.append((c["chain"], c["llama_coin"], int(p["timestamp"]), _day(p["timestamp"]), float(p["price"])))
            start += span * 86400
    df = (pl.DataFrame(rows, schema={"chain": pl.Utf8, "coin": pl.Utf8, "timestamp": pl.Int64, "date": pl.Utf8,
                                     "price_usd": pl.Float64}, orient="row")
          .unique(subset=["coin", "timestamp"], keep="first"))
    manifest.save_table("defillama", "coin_prices_daily", df, urls=urls, sort_by=["chain", "timestamp"],
                        notes="coins.llama.fi/chart, period=1d, paged in 400-day spans. Timestamps are the "
                              "provider's sample times (not always 00:00 UTC); one or more rows per UTC date.",
                        http_stats=client.stats_for(*HOSTS))

    # --- Chain snapshot (current TVL, token, gecko id) -------------------------------------------------
    url = f"{ep['llama']}/v2/chains"
    payload = client.get_json(url)
    df = pl.DataFrame([(str(r.get("name")), r.get("gecko_id"), r.get("tokenSymbol"), float(r.get("tvl") or 0.0))
                       for r in payload],
                      schema={"name": pl.Utf8, "gecko_id": pl.Utf8, "token_symbol": pl.Utf8, "tvl_usd": pl.Float64},
                      orient="row")
    manifest.save_table("defillama", "chains_snapshot", df, urls=[url], sort_by=["name"],
                        notes="Current TVL of every chain tracked by DefiLlama (for rank context).",
                        http_stats=client.stats_for(*HOSTS))

