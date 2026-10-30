"""(b) Fee and revenue multiples vs peers (Solana, Sui, Aptos, Ethereum, Tron; Base is a usage benchmark without a
token), for NEAR with and without NEAR Intents.

Input: one row per chain with market cap and fee / revenue sums over 30 and 365 days (USD, DefiLlama) plus, for NEAR,
Intents fees and captured revenue. Output: long table chain x variant x basis with
  multiple = market cap / annualized flow   (30d flows x 365/30; 365d flows as is)
and NEAR's implied market cap at the peer median / min / max multiple ("what the peers' pricing would imply").
"""

from __future__ import annotations

import statistics

import polars as pl

VARIANTS = {
    # variant: (fee column(s) summed, label)
    "chain_fees": (["fees"], "chain fees (gas)"),
    "chain_revenue": (["revenue"], "chain revenue (DefiLlama: burned / protocol share of gas)"),
    "fees_plus_intents_fees": (["fees", "intents_fees"], "chain fees + Intents gross fees"),
    "revenue_plus_intents_revenue": (["revenue", "intents_revenue"], "chain revenue + Intents captured revenue"),
}


def multiples(inputs: pl.DataFrame) -> pl.DataFrame:
    """inputs columns: chain, market_cap_usd, fees_30d, fees_365d, revenue_30d, revenue_365d,
    intents_fees_30d, intents_fees_365d, intents_revenue_30d, intents_revenue_365d (nulls allowed)."""
    rows = []
    for r in inputs.iter_rows(named=True):
        for variant, (cols, label) in VARIANTS.items():
            if variant.endswith("intents_fees") or variant.endswith("intents_revenue"):
                if r["chain"] != "near":
                    continue
            for basis, ann in (("30d_annualized", 365 / 30), ("365d", 1.0)):
                suffix = "30d" if basis.startswith("30d") else "365d"
                vals = [r.get(f"{c}_{suffix}") for c in cols]
                flow = None if any(v is None for v in vals) else sum(vals) * ann
                mc = r["market_cap_usd"]
                rows.append({"chain": r["chain"], "variant": variant, "variant_label": label, "basis": basis,
                             "annual_flow_usd": flow, "market_cap_usd": mc,
                             "multiple": (mc / flow) if (mc and flow) else None})
    return pl.DataFrame(rows, schema={"chain": pl.Utf8, "variant": pl.Utf8, "variant_label": pl.Utf8,
                                      "basis": pl.Utf8, "annual_flow_usd": pl.Float64, "market_cap_usd": pl.Float64,
                                      "multiple": pl.Float64})


def near_vs_peers(mult: pl.DataFrame) -> pl.DataFrame:
    """For each NEAR variant and basis: peer median / min / max of the comparable peer multiple (chain fees or chain
    revenue), NEAR's rank, and NEAR's market cap implied at those peer multiples."""
    rows = []
    peers = mult.filter((pl.col("chain") != "near") & pl.col("multiple").is_not_null())
    for r in mult.filter((pl.col("chain") == "near")).iter_rows(named=True):
        peer_variant = "chain_fees" if "fees" in r["variant"] else "chain_revenue"
        pm = peers.filter((pl.col("variant") == peer_variant) & (pl.col("basis") == r["basis"]))["multiple"].to_list()
        if not pm or r["annual_flow_usd"] is None:
            continue
        med = statistics.median(pm)
        rows.append({"variant": r["variant"], "basis": r["basis"], "near_multiple": r["multiple"],
                     "peer_variant": peer_variant, "peers": len(pm), "peer_median": med, "peer_min": min(pm),
                     "peer_max": max(pm),
                     "near_richer_than_peers": sum(1 for x in pm if r["multiple"] > x) / len(pm),
                     "implied_mcap_at_peer_median": r["annual_flow_usd"] * med,
                     "implied_mcap_at_peer_min": r["annual_flow_usd"] * min(pm),
                     "implied_mcap_at_peer_max": r["annual_flow_usd"] * max(pm),
                     "near_market_cap": r["market_cap_usd"]})
    return pl.DataFrame(rows, infer_schema_length=None)
