"""Money trails (Q4): ledgers of the NEAR revenue / buyback wallets and treasury.near, the DefiLlama revenue
reconciliation, the treasury balance reconciliation, and where large treasury outflows went.

Inputs: fastnear_tx/wallet_flows.csv (one row per value movement touching a wallet), fastnear_tx/trail_hops.csv,
rpc_archival/treasury_monthly.csv, the 1Click token list (decimals, symbols) and daily NEAR prices.
Flow types:
  swap_leg  DIP-4 token_diff legs inside NEAR Intents (the wallet itself trading)
  custody   moving the wallet's own funds between forms: NEAR <-> wNEAR (wrap.near), deposits into / withdrawals from
            its NEAR Intents balance (mt_mint / mt_burn), storage deposits
  transfer  value received from / sent to another account (NEAR, NEP-141 or NEP-245 inside Intents)
Revenue reconciliation follows the DefiLlama adapter's definition (dimension-adapters/fees/near-intents):
NEAR Transfer actions and positive wrap.near transfers into the three revenue wallets from accounts outside that set,
priced at the day's NEAR price.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import polars as pl

from .. import accounts, io
from ..transform.daily import series

STABLES = {"USDC", "USDT", "DAI", "USDC.e", "USDT.e", "USD₮", "USDt", "FRAX", "USDe"}
NEAR_SYMBOLS = {"NEAR", "wNEAR"}


def _tokens(raw: Path) -> dict[str, tuple[str, int]]:
    p = raw / "oneclick" / "tokens.csv"
    out = {"NEAR": ("NEAR", 24), "nep141:wrap.near": ("wNEAR", 24)}
    if p.exists():
        for r in io.read_csv(p).iter_rows(named=True):
            out.setdefault(r["assetId"], (r["symbol"], int(r["decimals"])))
    return out


def normalize(flows: pl.DataFrame, tokens: dict[str, tuple[str, int]]) -> pl.DataFrame:
    rows = []
    for r in flows.iter_rows(named=True):
        a = r["asset"]
        tok = "NEAR" if a == "NEAR" else (a[len("intents.near:"):] if a.startswith("intents.near:") else f"nep141:{a}")
        sym, dec = tokens.get(tok, ("", None))
        amt = int(r["amount_raw"]) / 10 ** dec if dec is not None else None
        group = "NEAR" if sym in NEAR_SYMBOLS else ("stable" if sym in STABLES else "other")
        cp = r["counterparty"] or ""
        kind, meth = r["kind"], r["method"] or ""
        if kind == "token_diff":
            ftype = "swap_leg"
        elif (cp == accounts.WRAP and (meth in ("near_deposit", "near_withdraw", "storage_deposit") or kind in
                                        ("ft_mint", "ft_burn", "near_transfer"))) or kind in ("mt_mint", "mt_burn") \
                or meth == "storage_deposit" or (cp == accounts.INTENTS and kind == "ft_transfer"):
            ftype = "custody"
        else:
            ftype = "transfer"
        ts = int(r["block_timestamp_ns"]) // 1_000_000_000
        rows.append({**{k: r[k] for k in ("wallet", "tx_hash", "receipt_id", "block_height", "kind", "direction",
                                          "counterparty", "method")},
                     "date": dt.datetime.fromtimestamp(ts, dt.UTC).strftime("%Y-%m-%d"),
                     "token": tok, "symbol": sym, "asset_group": group, "amount": amt, "flow_type": ftype,
                     "counterparty_class": accounts.classify(cp)})
    return pl.DataFrame(rows, infer_schema_length=None).with_columns(pl.col("date").str.slice(0, 7).alias("month"))


def build(raw: Path, daily: pl.DataFrame, epochs: pl.DataFrame) -> dict[str, pl.DataFrame]:
    p = raw / "fastnear_tx" / "wallet_flows.csv"
    if not p.exists():
        return {}
    flows = normalize(io.read_csv(p).with_columns(pl.col("block_height").cast(pl.Int64)), _tokens(raw))
    px = {str(d): v for d, v in series(daily, "near", "price_usd", "defillama").iter_rows()}
    flows = flows.with_columns(pl.col("date").replace_strict(px, default=None, return_dtype=pl.Float64).alias("near_price"))
    flows = flows.with_columns(
        pl.when(pl.col("asset_group") == "NEAR").then(pl.col("amount") * pl.col("near_price"))
        .when(pl.col("asset_group") == "stable").then(pl.col("amount")).otherwise(None).alias("usd"))

    monthly = (flows.group_by(["wallet", "month", "flow_type", "direction", "counterparty_class", "asset_group"])
               .agg(pl.len().alias("flows"), pl.col("amount").sum().alias("amount"), pl.col("usd").sum().alias("usd"))
               .sort(["wallet", "month", "flow_type", "direction", "counterparty_class", "asset_group"]))

    # DefiLlama revenue definition, reproduced from on-chain flows
    rw = set(accounts.REVENUE_WALLETS)
    rev = flows.filter(pl.col("wallet").is_in(list(rw)) & (pl.col("direction") == "in")
                       & ~pl.col("counterparty").is_in(list(rw))
                       & (((pl.col("kind") == "near_transfer") & (pl.col("token") == "NEAR"))
                          | ((pl.col("kind") == "ft_transfer") & (pl.col("token") == "nep141:wrap.near"))))
    rev_d = rev.group_by("date").agg(pl.col("amount").sum().alias("near"), pl.col("usd").sum().alias("usd_onchain"))
    dl = series(daily, "near", "intents_revenue_usd", "defillama").with_columns(pl.col("date").cast(pl.Utf8))
    recon = (dl.rename({"value": "usd_defillama"}).join(rev_d, on="date", how="full", coalesce=True)
             .with_columns(pl.col("date").str.slice(0, 7).alias("month"))
             .group_by("month").agg(pl.col("usd_defillama").sum(), pl.col("usd_onchain").sum(),
                                    pl.col("near").sum().alias("near_onchain"))
             .with_columns((pl.col("usd_onchain") / pl.col("usd_defillama")).alias("onchain_to_defillama"))
             .sort("month"))

    # buyback summary: NEAR captured into the revenue wallets (DefiLlama definition), last 180 days, annualized
    last_day = flows["date"].max()
    since = str(dt.date.fromisoformat(last_day) - dt.timedelta(days=180))
    since_bb = "2026-02-23"
    r180 = rev.filter(pl.col("date") > since)
    bb_out = flows.filter((pl.col("wallet") == "buybacks.multisignature.near") & (pl.col("direction") == "out")
                          & (pl.col("flow_type") == "transfer") & (pl.col("asset_group") == "NEAR")
                          & (pl.col("date") >= since_bb))
    buyback_summary = pl.DataFrame([{
        "window": f"{since} to {last_day}", "near_captured": float(r180["amount"].sum()),
        "near_acquired_annualized": float(r180["amount"].sum()) * 365 / 180,
        "usd_captured": float(r180["usd"].sum()),
        "near_captured_since_buyback_start": float(rev.filter(pl.col("date") >= since_bb)["amount"].sum()),
        "buyback_wallet_near_transfers_out_since_start": float(bb_out["amount"].sum()),
        "buyback_wallet_out_counterparties": ", ".join(sorted(set(bb_out["counterparty"].to_list())))[:500]}])

    # treasury reconciliation: archival month-start balances vs NEAR flows -> implied protocol rewards
    tm = io.read_csv(raw / "rpc_archival" / "treasury_monthly.csv").filter(pl.col("account_id") == "treasury.near")
    bal = [(r["boundary_utc"][:7], int(r["amount_yocto"]) / 1e24, r["boundary_utc"][:10])
           for r in tm.iter_rows(named=True) if r["amount_yocto"]]
    tf = flows.filter((pl.col("wallet") == "treasury.near") & (pl.col("token") == "NEAR"))
    net = {m: v for m, v in tf.with_columns(pl.when(pl.col("direction") == "in").then(pl.col("amount"))
                                            .otherwise(-pl.col("amount")).alias("s"))
           .group_by("month").agg(pl.col("s").sum()).iter_rows()}
    ep = epochs.with_columns(pl.col("start_date").str.slice(0, 7).alias("month"))
    rows = []
    for (m0, b0, d0), (m1, b1, d1) in zip(bal[:-1], bal[1:]):
        e = ep.filter(pl.col("month") == m0)
        days = (dt.date.fromisoformat(d1) - dt.date.fromisoformat(d0)).days  # the last interval ends at the fetch day
        exp = (float(e["mint_per_day_near"].mean()) * days * float(e["treasury_reward_share"].drop_nulls().mean())
               if e.height and e["treasury_reward_share"].drop_nulls().len() else None)
        rows.append({"month": m0, "days": days, "balance_start": b0, "balance_end": b1, "net_flows_near": net.get(m0, 0.0),
                     "implied_non_transaction_inflow": b1 - b0 - net.get(m0, 0.0),
                     "expected_treasury_rewards": exp,
                     "implied_to_expected": (b1 - b0 - net.get(m0, 0.0)) / exp if exp else None})
    treasury_recon = pl.DataFrame(rows, infer_schema_length=None)

    # treasury outflows and trails
    t_out = (flows.filter((pl.col("wallet") == "treasury.near") & (pl.col("direction") == "out")
                          & (pl.col("token") == "NEAR"))
             .select("date", "tx_hash", "counterparty", "counterparty_class", "amount", "kind", "method").sort("date"))
    hp = raw / "fastnear_tx" / "trail_hops.csv"
    trails = pl.DataFrame()
    if hp.exists():
        h = io.read_csv(hp)
        # the same later outflow is seen once per incoming transfer that was followed: keep it once (lowest hop)
        h = (h.with_columns(pl.col("depth").cast(pl.Int64), pl.col("out_height").cast(pl.Int64, strict=False))
             .sort(["depth", "account", "out_height", "out_tx", "out_counterparty", "out_asset", "out_amount_raw",
                    "stop_reason"])
             .unique(subset=["account", "out_tx", "out_counterparty", "out_asset", "out_amount_raw", "stop_reason"],
                     keep="first", maintain_order=True)
             .filter(~(pl.col("stop_reason") == "already_traced")))
        trails = h.with_columns(
            (pl.col("received_near_yocto").cast(pl.Float64) / 1e24).alias("received_near"),
            pl.when(pl.col("out_asset") == "NEAR").then(pl.col("out_amount_raw").cast(pl.Float64) / 1e24)
            .otherwise(None).alias("out_near"))
    out = {"_flows": flows.drop("near_price").sort(["wallet", "block_height", "tx_hash", "receipt_id", "token",
                                                   "direction", "counterparty", "kind"]),
           "monthly": monthly, "revenue_reconciliation": recon, "buyback_summary": buyback_summary,
           "treasury_reconciliation": treasury_recon, "treasury_outflows": t_out}
    if trails.height:
        out["trails"] = trails
    return out
