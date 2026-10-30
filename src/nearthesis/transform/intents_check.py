"""NEAR Intents settlement cross-check (Q2): rebuild sampled days' swap volume from on-chain `token_diff` events and
compare with the DefiLlama series (NEAR-uploaded Dune dataset `dataset_near_intents_metrics`).

Per sampled transaction (all its DIP-4 token_diff events, all accounts):
  net(a, t)   = sum of account a's diffs in token t inside the transaction (removes routing hops)
  v_account   = max(USD sold, USD bought) over a's priced net legs
  v_tx        = 1/2 sum_a v_account          (each swap has a buyer and a seller side; counted once)
  gross_tx    = USD of all negative legs before netting (both sides and routing hops)
  fee_tx      = USD of protocol fees collected / fee rate (fee-implied gross)
Two day-level estimates of one-sided swap volume:
  B (sample)  = census count of fee-paying transactions x mean(v_tx); 90% CI from a bootstrap over sampled windows
  A (census)  = fee collector balance change, divided by the fee rate and priced = gross sold volume of the whole
                day (exact count of fees, no sampling), x (sample gross / sample fee-implied gross: the fee is rounded
                up per leg) x (sample v_tx / sample gross: netting to one side)
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


def tx_values(legs: pl.DataFrame, tokens: dict, prices: dict, fee_pips: dict[str, int]) -> pl.DataFrame:
    """One row per sampled transaction: v_tx, gross, fee-implied gross, referral-side volume, unpriced counts."""
    rows = []
    legs = legs.filter(pl.col("tx_hash") != "")
    for (day, window, txh), g in legs.group_by(["day", "window", "tx_hash"], maintain_order=True):
        pips = fee_pips.get(day) or 1

        def usd(tok: str, amount: int) -> float | None:
            meta = tokens.get(tok)
            if not meta or not meta["cg"]:
                return None
            p = prices.get((day, meta["cg"]))
            return None if p is None else amount / 10 ** meta["decimals"] * p

        gross = fee_gross = 0.0
        unpriced = 0
        net: dict[tuple[str, str], int] = {}
        ref_vol = 0.0
        for (ev, acc, ref), eg in g.group_by(["event_index", "account_id", "referral"], maintain_order=True):
            sold = bought = 0.0
            for r in eg.iter_rows(named=True):
                a = int(r["amount"])
                net[(acc, r["token_id"])] = net.get((acc, r["token_id"]), 0) + a
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
                    fu = usd(r["token_id"], int(r["fee_collected"]))
                    fee_gross += (fu or 0.0) * 1_000_000 / pips
            if ref:
                ref_vol += max(sold, bought)
        per_acc: dict[str, list[float]] = {}
        for (acc, tok), a in net.items():
            if a == 0:
                continue
            u = usd(tok, abs(a))
            if u is None:
                continue
            s = per_acc.setdefault(acc, [0.0, 0.0])
            s[0 if a < 0 else 1] += u
        v = 0.5 * sum(max(s, b) for s, b in per_acc.values())
        rows.append({"day": day, "window": int(window), "tx_hash": txh, "v_tx_usd": v, "gross_sold_usd": gross,
                     "fee_implied_gross_usd": fee_gross, "referral_side_usd": ref_vol, "legs": g.height,
                     "unpriced_legs": unpriced})
    return pl.DataFrame(rows, infer_schema_length=None)


def build(raw: Path, daily: pl.DataFrame) -> dict[str, pl.DataFrame]:
    d = raw / "fastnear_tx"
    if not (d / "intents_swap_legs.csv").exists():
        return {}
    days = io.read_csv(d / "intents_days.csv")
    legs = io.read_csv(d / "intents_swap_legs.csv")
    bal = io.read_csv(raw / "rpc_archival" / "intents_fee_collector_balances.csv")
    tokens, prices = _token_table(raw), _prices(raw)
    fee_pips = {r["day"]: int(r["fee_pips_start"]) for r in days.iter_rows(named=True) if r["fee_pips_start"]}
    tv = tx_values(legs, tokens, prices, fee_pips)
    dl = (daily.filter((pl.col("chain") == "near") & (pl.col("source") == "defillama")
                       & pl.col("metric").is_in(["intents_volume_usd", "intents_fees_usd", "intents_revenue_usd"]))
          .pivot(on="metric", index="date", values="value"))
    dl_map = {r["date"]: r for r in dl.iter_rows(named=True)}
    rows, tok_rows = [], []
    for r in days.sort("day").iter_rows(named=True):
        day = r["day"]
        pips = int(r["fee_pips_start"] or 1)
        n_fee = int(r["fee_paying_txs"])
        t = tv.filter(pl.col("day") == day)
        lg = legs.filter((pl.col("day") == day))
        windows = lg["window"].cast(pl.Int64).unique().sort().to_numpy()
        # census: fee collector balance change per token
        b = bal.filter(pl.col("day") == day)
        census_gross = census_fees_usd = 0.0
        unpriced_fee_tokens = 0
        neg_delta = 0
        for x in b.iter_rows(named=True):
            delta = int(x["balance_end"]) - int(x["balance_start"])
            if delta < 0:
                neg_delta += 1
            if delta <= 0:
                continue
            meta = tokens.get(x["token_id"])
            p = prices.get((day, meta["cg"])) if meta and meta["cg"] else None
            if p is None:
                unpriced_fee_tokens += 1
                tok_rows.append({"day": day, "token_id": x["token_id"], "symbol": meta["symbol"] if meta else "",
                                 "fee_delta_raw": str(delta), "gross_sold_usd": None})
                continue
            fee_usd = delta / 10 ** meta["decimals"] * p
            census_fees_usd += fee_usd
            census_gross += fee_usd * 1_000_000 / pips
            tok_rows.append({"day": day, "token_id": x["token_id"], "symbol": meta["symbol"],
                             "fee_delta_raw": str(delta), "gross_sold_usd": fee_usd * 1_000_000 / pips})
        # sample estimates with a cluster bootstrap over windows
        arr = {w: t.filter(pl.col("window") == w) for w in windows}
        def stats(ws):
            sub = [arr[w] for w in ws if arr[w].height]
            if not sub:
                return None
            s = pl.concat(sub)
            v, g, f = s["v_tx_usd"].sum(), s["gross_sold_usd"].sum(), s["fee_implied_gross_usd"].sum()
            return {"mean_v": v / s.height, "mean_gross": g / s.height, "mean_ref": s["referral_side_usd"].sum() / s.height,
                    "cal": (g / f) if f > 0 else None, "net": (v / g) if g > 0 else None}
        point = stats(windows)
        rng = np.random.default_rng([SEED, int(day.replace("-", ""))])
        bs = [stats(rng.choice(windows, size=len(windows), replace=True)) for _ in range(BOOT)]
        bs = [x for x in bs if x]
        def q(key, scale=1.0, census=False):
            vals = np.array([(x[key] if not census else (census_gross * (x["cal"] or 1.0) * (x["net"] or 0.0)))
                             * scale for x in bs if x.get(key) is not None or census])
            return float(np.quantile(vals, 0.05)), float(np.quantile(vals, 0.95))
        vb = n_fee * point["mean_v"]
        vb05, vb95 = q("mean_v", n_fee)
        va = census_gross * (point["cal"] or 1.0) * (point["net"] or 0.0)
        va05, va95 = q("", census=True)
        dlr = dl_map.get(day, {})
        dlv = dlr.get("intents_volume_usd")
        rows.append({"day": day, "fee_pips": pips, "fee_paying_txs": n_fee,
                     "intents_receiver_txs": int(r["intents_receiver_txs"]), "windows": len(windows),
                     "sampled_txs": t.height, "sampled_legs": int(t["legs"].sum()),
                     "unpriced_leg_share": float(t["unpriced_legs"].sum() / max(t["legs"].sum(), 1)),
                     "volume_sample_usd": vb, "volume_sample_p05": vb05, "volume_sample_p95": vb95,
                     "gross_sold_sample_scaled_usd": n_fee * point["mean_gross"],
                     "referral_side_sample_scaled_usd": n_fee * point["mean_ref"],
                     "census_fee_implied_gross_usd": census_gross, "fee_rounding_calibration": point["cal"],
                     "netting_ratio": point["net"], "volume_census_usd": va, "volume_census_p05": va05,
                     "volume_census_p95": va95, "census_protocol_fees_usd": census_fees_usd,
                     "fee_tokens_unpriced": unpriced_fee_tokens, "fee_tokens_with_negative_delta": neg_delta,
                     "defillama_volume_usd": dlv, "defillama_fees_usd": dlr.get("intents_fees_usd"),
                     "ratio_sample_to_defillama": vb / dlv if dlv else None,
                     "ratio_sample_to_defillama_p05": vb05 / dlv if dlv else None,
                     "ratio_sample_to_defillama_p95": vb95 / dlv if dlv else None,
                     "ratio_census_to_defillama": va / dlv if dlv else None,
                     "ratio_census_to_defillama_p05": va05 / dlv if dlv else None,
                     "ratio_census_to_defillama_p95": va95 / dlv if dlv else None})
    days_df = pl.DataFrame(rows, infer_schema_length=None)
    tok = pl.DataFrame(tok_rows, infer_schema_length=None)
    conc = (tok.drop_nulls("gross_sold_usd").group_by(["day", "symbol"]).agg(pl.col("gross_sold_usd").sum())
            .with_columns((pl.col("gross_sold_usd") / pl.col("gross_sold_usd").sum().over("day")).alias("share"))
            .sort(["day", "share"], descending=[False, True]))
    hhi = conc.group_by("day").agg((pl.col("share") ** 2).sum().alias("hhi"), pl.col("share").max().alias("top_share"),
                                   pl.col("symbol").first().alias("top_symbol")).sort("day")
    return {"days": days_df, "tx_values": tv.sort(["day", "window", "tx_hash"]), "tokens": tok.sort(["day", "token_id"]),
            "concentration": conc, "hhi": hhi}
