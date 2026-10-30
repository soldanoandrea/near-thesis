"""NEAR Intents settlement cross-check (Q2): rebuild sampled days' swap volume from on-chain `token_diff` events and
compare with the DefiLlama series (NEAR-uploaded Dune dataset `dataset_near_intents_metrics`).

Per sampled transaction (all its DIP-4 token_diff events, all accounts):
  net(a, t)   = sum of account a's diffs in token t inside the transaction (removes routing hops)
  v_account   = max(USD sold, USD bought) over a's priced net legs
  v_tx        = 1/2 sum_a v_account          (each swap has a buyer and a seller side; counted once)
  gross_tx    = USD of all negative legs before netting (both sides and routing hops)
  fee_tx      = USD of protocol fees collected / fee rate (fee-implied gross)
Day-level estimate of one-sided swap volume:
  V = census count of fee-paying transactions x mean(v_tx); 90% CI from a bootstrap over sampled windows. The
  "two-sided equivalent" 2V is what a definition counting both legs of every swap would report.
Frame check: a control sample of *all* transactions touching intents.near (any method) tests that every transaction
with a token_diff pays the protocol fee, i.e. that the fee-paying frame contains all swaps.
The fee collector's balance change is NOT a census of fees: its balances fall during the day for many tokens (it
moves or converts what it collects), so it is reported as a diagnostic only.
Tokens are priced with DefiLlama prices at 12:00 UTC of the day via the CoinGecko ids of the 1Click token list;
legs in tokens without a price are reported (count and share), never guessed.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import polars as pl

from .. import io

BOOT = 2000
SEED = 20261101


def _token_table(raw: Path) -> dict[str, dict]:
    t = io.read_csv(raw / "oneclick" / "tokens.csv")
    return {r["assetId"]: {"decimals": int(r["decimals"]), "symbol": r["symbol"],
                           "cg": r["coingeckoId"] if r["coingeckoId"] not in ("", "None") else None}
            for r in t.iter_rows(named=True)}


def _prices(raw: Path) -> dict[tuple[str, str], float]:
    p = io.read_csv(raw / "defillama" / "coin_prices_intents_days.csv")
    return {(r["day"], r["coin"].removeprefix("coingecko:")): float(r["price_usd"]) for r in p.iter_rows(named=True)}


def tx_values(txs: pl.DataFrame, legs: pl.DataFrame, tokens: dict, prices: dict,
              fee_pips: dict[str, int]) -> pl.DataFrame:
    """One row per sampled transaction: v_tx, gross, fee-implied gross, referral-side volume, unpriced counts.
    Transactions without a successful token_diff leg keep zeros (they are part of the counted population)."""
    by_tx = {k: g for k, g in legs.group_by(["day", "tx_no"], maintain_order=True)}
    rows = []
    for t in txs.iter_rows(named=True):
        day = t["day"]
        g = by_tx.get((day, t["tx_no"]))
        pips = fee_pips.get(day) or 1

        def usd(tok: str, amount: int) -> float | None:
            meta = tokens.get(tok)
            if not meta or not meta["cg"]:
                return None
            p = prices.get((day, meta["cg"]))
            return None if p is None else amount / 10 ** meta["decimals"] * p

        gross = fee_gross = ref_vol = 0.0
        unpriced = 0
        net: dict[tuple[str, str], int] = {}
        if g is not None:
            for (_, _, ref), eg in g.group_by(["event_index", "account_id", "referral"], maintain_order=True):
                sold = bought = 0.0
                for r in eg.iter_rows(named=True):
                    a = int(r["amount"])
                    net[(r["account_id"], r["token_id"])] = net.get((r["account_id"], r["token_id"]), 0) + a
                    u = usd(r["token_id"], abs(a))
                    if u is None:
                        unpriced += 1
                        continue
                    if a < 0:
                        gross += u
                        sold += u
                    else:
                        bought += u
                    if r["fee_collected"]:
                        fee_gross += (usd(r["token_id"], int(r["fee_collected"])) or 0.0) * 1_000_000 / pips
                if ref:
                    ref_vol += max(sold, bought)
        per_acc: dict[str, list[float]] = {}
        for (acc, tok), a in net.items():
            u = usd(tok, abs(a)) if a else None
            if u is None:
                continue
            per_acc.setdefault(acc, [0.0, 0.0])[0 if a < 0 else 1] += u
        rows.append({"day": day, "window": int(t["window"]), "tx_no": int(t["tx_no"]), "tx_hash": t["tx_hash"],
                     "v_tx_usd": 0.5 * sum(max(a, b) for a, b in per_acc.values()), "gross_sold_usd": gross,
                     "fee_implied_gross_usd": fee_gross, "referral_side_usd": ref_vol,
                     "legs": 0 if g is None else g.height, "unpriced_legs": unpriced})
    return pl.DataFrame(rows, infer_schema_length=None)


def _sample_stats(t: pl.DataFrame) -> dict | None:
    if not t.height:
        return None
    v, g, f = t["v_tx_usd"].sum(), t["gross_sold_usd"].sum(), t["fee_implied_gross_usd"].sum()
    return {"mean_v": v / t.height, "mean_gross": g / t.height, "mean_ref": t["referral_side_usd"].sum() / t.height,
            "cal": (g / f) if f > 0 else None, "net": (v / g) if g > 0 else None}


def build(raw: Path, daily: pl.DataFrame) -> dict[str, pl.DataFrame]:
    d = raw / "fastnear_tx"
    if not (d / "intents_swap_txs.csv").exists():
        return {}
    days = io.read_csv(d / "intents_days.csv")
    txs = io.read_csv(d / "intents_swap_txs.csv").with_columns(pl.col("window").cast(pl.Int64),
                                                               pl.col("tx_no").cast(pl.Int64))
    legs = io.read_csv(d / "intents_swap_legs.csv").with_columns(pl.col("tx_no").cast(pl.Int64),
                                                                 pl.col("event_index").cast(pl.Int64))
    wins = io.read_csv(d / "intents_windows.csv").with_columns(pl.col("window").cast(pl.Int64))
    bal = io.read_csv(raw / "rpc_archival" / "intents_fee_collector_balances.csv")
    ctl = io.read_csv(d / "intents_control_txs.csv")
    tokens, prices = _token_table(raw), _prices(raw)
    fee_pips = {r["day"]: int(r["fee_pips_start"]) for r in days.iter_rows(named=True) if r["fee_pips_start"]}
    tv = tx_values(txs, legs, tokens, prices, fee_pips)
    dl = (daily.filter((pl.col("chain") == "near") & (pl.col("source") == "defillama")
                       & pl.col("metric").is_in(["intents_volume_usd", "intents_fees_usd", "intents_revenue_usd"]))
          .pivot(on="metric", index="date", values="value"))
    dl_map = {r["date"]: r for r in dl.iter_rows(named=True)}
    rows = []
    for r in days.sort("day").iter_rows(named=True):
        day = r["day"]
        pips = int(r["fee_pips_start"] or 1)
        n_fee = int(r["fee_paying_txs"])
        t = tv.filter(pl.col("day") == day)
        windows = wins.filter(pl.col("day") == day)["window"].sort().to_numpy()
        # diagnostic only: the fee collector's balance change (not a fee census, see the module docstring)
        b = bal.filter(pl.col("day") == day)
        deltas = [int(x["balance_end"]) - int(x["balance_start"]) for x in b.iter_rows(named=True)]
        rising, falling = sum(1 for x in deltas if x > 0), sum(1 for x in deltas if x < 0)
        # sample estimates; 90% CI by a bootstrap over sampled windows (clusters)
        per_win = {w: t.filter(pl.col("window") == w) for w in windows}
        point = _sample_stats(t)
        rng = np.random.default_rng([SEED, int(day.replace("-", ""))])
        vb_s = []
        for _ in range(BOOT):
            pick = rng.choice(windows, size=len(windows), replace=True)
            st = _sample_stats(pl.concat([per_win[w] for w in pick]))
            if st is not None:
                vb_s.append(n_fee * st["mean_v"])
        vb = n_fee * point["mean_v"]
        vb05, vb95 = (float(x) for x in np.quantile(vb_s, [0.05, 0.95]))
        cd = ctl.filter(pl.col("day") == day)
        td = cd.filter(pl.col("token_diff_legs").cast(pl.Int64) > 0)
        dlr = dl_map.get(day, {})
        dlv = dlr.get("intents_volume_usd")
        rows.append({"day": day, "fee_pips": pips, "fee_paying_txs": n_fee,
                     "intents_receiver_txs": int(r["intents_receiver_txs"]), "windows": len(windows),
                     "sampled_txs": t.height, "sampled_legs": int(t["legs"].sum()),
                     "unpriced_leg_share": float(t["unpriced_legs"].sum() / max(t["legs"].sum(), 1)),
                     "volume_sample_usd": vb, "volume_sample_p05": vb05, "volume_sample_p95": vb95,
                     "gross_sold_sample_scaled_usd": n_fee * point["mean_gross"],
                     "referral_side_sample_scaled_usd": n_fee * point["mean_ref"],
                     "netting_ratio": point["net"], "fee_rounding_calibration": point["cal"],
                     "control_txs": cd.height, "control_txs_with_token_diff": td.height,
                     "control_token_diff_without_fee": td.filter(~(pl.col("fee_collector_in_logs") == "true")).height,
                     "fee_collector_tokens_rising": rising, "fee_collector_tokens_falling": falling,
                     "defillama_volume_usd": dlv, "defillama_fees_usd": dlr.get("intents_fees_usd"),
                     "ratio_sample_to_defillama": vb / dlv if dlv else None,
                     "ratio_sample_to_defillama_p05": vb05 / dlv if dlv else None,
                     "ratio_sample_to_defillama_p95": vb95 / dlv if dlv else None,
                     "ratio_two_sided_to_defillama": 2 * vb / dlv if dlv else None,
                     "ratio_two_sided_to_defillama_p05": 2 * vb05 / dlv if dlv else None,
                     "ratio_two_sided_to_defillama_p95": 2 * vb95 / dlv if dlv else None,
                     "ratio_gross_sold_to_defillama": n_fee * point["mean_gross"] / dlv if dlv else None})
    days_df = pl.DataFrame(rows, infer_schema_length=None)
    # asset concentration from the sample: USD of sold legs by token symbol (USDC on every chain counts as USDC)
    lg = legs.join(txs.select("day", "tx_no"), on=["day", "tx_no"]).filter(pl.col("amount").str.starts_with("-"))
    rows_c = []
    for r in lg.iter_rows(named=True):
        meta = tokens.get(r["token_id"])
        p = prices.get((r["day"], meta["cg"])) if meta and meta["cg"] else None
        if p is not None:
            rows_c.append({"day": r["day"], "symbol": meta["symbol"],
                           "usd": -int(r["amount"]) / 10 ** meta["decimals"] * p})
    conc = (pl.DataFrame(rows_c).group_by(["day", "symbol"]).agg(pl.col("usd").sum().alias("gross_sold_usd_sample"))
            .with_columns((pl.col("gross_sold_usd_sample") / pl.col("gross_sold_usd_sample").sum().over("day")).alias("share"))
            .sort(["day", "share", "symbol"], descending=[False, True, False]))
    hhi = conc.group_by("day", maintain_order=True).agg((pl.col("share") ** 2).sum().alias("hhi"),
                                                        pl.col("share").max().alias("top_share"),
                                                        pl.col("symbol").first().alias("top_symbol")).sort("day")
    return {"days": days_df, "tx_values": tv.sort(["day", "tx_no"]), "concentration": conc, "hhi": hhi}
