"""`make reproduce` core: data/raw -> data/processed/*.csv + reports/metrics_summary.md. Offline and deterministic."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import polars as pl

from . import config, io, manifest, metrics, paths, report
from .metrics import MetricTable, _d, at, full_wsum, growth, ratio, series, wmean
from .transform import activity, daily as daily_mod, supply

DAILY_SOURCES = ("nearblocks", "defillama", "coingecko", "aurora")


def compute_as_of(m: dict) -> str:
    """Last complete UTC day before the earliest fetch of the daily sources."""
    times = [v["fetched_at_utc"] for v in m["files"].values() if v["source"] in DAILY_SOURCES]
    first = min(dt.datetime.fromisoformat(t.replace("Z", "+00:00")) for t in times)
    return (first.date() - dt.timedelta(days=1)).isoformat()


def raw_inventory(m: dict, raw: Path) -> pl.DataFrame:
    """Rows and covered span of every committed raw file (from the files themselves, not typed)."""
    rows = []
    for rel, e in sorted(m["files"].items()):
        df = io.read_csv(raw / rel)
        first = last = ""
        for col in ("date", "month", "boundary_utc"):
            if col in df.columns:
                first, last = str(df[col].min())[:10], str(df[col].max())[:10]
                break
        else:
            if "start_timestamp_ns" in df.columns:
                ts = df["start_timestamp_ns"].cast(pl.Int64)
                first, last = (dt.datetime.fromtimestamp(x / 1e9, dt.UTC).strftime("%Y-%m-%d")
                               for x in (ts.min(), ts.max()))
        rows.append((rel, e["source"], df.height, first, last, e["fetched_at_utc"], e["sha256"][:12]))
    return pl.DataFrame(rows, schema={"file": pl.Utf8, "source": pl.Utf8, "rows": pl.Int64, "first": pl.Utf8,
                                      "last": pl.Utf8, "fetched_at_utc": pl.Utf8, "sha256_12": pl.Utf8}, orient="row")


def _kv(raw: Path, rel: str) -> dict[str, str]:
    t = io.read_csv(raw / rel)
    return dict(zip(t["key"].to_list(), t["value"].to_list()))


def first_pass(raw: Path, daily: pl.DataFrame, epochs: pl.DataFrame, act: dict, peers: pl.DataFrame,
               bvf: pl.DataFrame, events: pl.DataFrame, tre: pl.DataFrame, as_of: str) -> pl.DataFrame:
    T = MetricTable()
    end = _d(as_of)
    yago = end - dt.timedelta(days=365)
    nb = lambda m: series(daily, "near", m, "nearblocks")  # noqa: E731
    dl = lambda m: series(daily, "near", m, "defillama")  # noqa: E731

    # ---------------- Q1 activity -------------------------------------------------------------------------------
    for m, label in (("txns", "Transactions per day"), ("active_accounts", "Active accounts per day"),
                     ("new_accounts", "New accounts per day")):
        cur, prev = wmean(nb(m), end, 30), wmean(nb(m), yago, 30)
        T.add("Q1", f"q1.{m}_30d_avg", f"{label}, 30-day average", cur, "count", f"30d to {as_of}",
              "nearblocks /v1/charts", "B")
        T.add("Q1", f"q1.{m}_30d_avg_yoy", f"{label}, 30-day average vs one year earlier", growth(cur, prev),
              "ratio", f"30d to {as_of} vs 30d to {yago}", "nearblocks /v1/charts", "B")
    mon = act["monthly"].filter(~pl.col("is_partial_month")).sort("month")
    if mon.height:
        last = mon.row(-1, named=True)
        lm = last["month"]
        year_before = mon.filter(pl.col("month") == f"{int(lm[:4]) - 1}{lm[4:]}")
        T.add("Q1", "q1.hot_share_last_month", f"Share of transactions involving game.hot.tg (HOT), {lm}",
              last.get("share_game_hot_tg"), "ratio", lm, "fastnear tx census / nearblocks", "A")
        if year_before.height:
            T.add("Q1", "q1.hot_share_year_before", f"Share of transactions involving game.hot.tg (HOT), {year_before['month'][0]}",
                  year_before["share_game_hot_tg"][0], "ratio", year_before["month"][0],
                  "fastnear tx census / nearblocks", "A")
        inc = mon.drop_nulls("share_incentivized_total")
        T.add("Q1", "q1.incentivized_share_last_month",
              f"Share of transactions involving incentivized contracts (HOT, KaiChing, SWEAT, NEARCrowd, inscriptions), {lm}",
              last.get("share_incentivized_total"), "ratio", lm, "fastnear tx census / nearblocks", "A")
        if year_before.height:
            T.add("Q1", "q1.incentivized_share_year_before",
                  f"Share of transactions involving incentivized contracts, {year_before['month'][0]}",
                  year_before["share_incentivized_total"][0], "ratio", year_before["month"][0],
                  "fastnear tx census / nearblocks", "A")
        if inc.height:
            pk = inc.sort(["share_incentivized_total", "month"], descending=[True, False]).row(0, named=True)
            T.add("Q1", "q1.incentivized_share_peak", f"Peak monthly share of incentivized contracts ({pk['month']})",
                  pk["share_incentivized_total"], "ratio", pk["month"], "fastnear tx census / nearblocks", "A")
        T.add("Q1", "q1.infrastructure_share_last_month",
              f"Share of transactions involving infrastructure contracts (Aurora, Chain Signatures, Intents), {lm}",
              last.get("share_infrastructure_total"), "ratio", lm, "fastnear tx census / nearblocks", "A")
        for acc, mid in (("v1.signer", "chain_signatures"), ("intents.near", "intents"), ("aurora", "aurora_relay")):
            col = "census_" + acc.replace(".", "_")
            if col in last:
                T.add("Q3" if acc != "aurora" else "Q1", f"q.{mid}_txs_last_month",
                      f"Transactions in which {acc} receives a receipt, {lm}", last[col], "count", lm,
                      "fastnear tx census", "A")
        T.add("Q1", "q1.organic_proxy_txns_per_day_last_month",
              f"Organic proxy: direct, named-signer txs to untracked contracts per day, {lm}",
              (last["organic_proxy_txns"] / last["nb_days"]) if last["organic_proxy_txns"] is not None else None,
              "count", lm, "census + stratified block sample", "A",
              ci_low=(last["organic_proxy_txns_p05"] / last["nb_days"]) if last["organic_proxy_txns_p05"] is not None else None,
              ci_high=(last["organic_proxy_txns_p95"] / last["nb_days"]) if last["organic_proxy_txns_p95"] is not None else None,
              notes="Structural proxy, not a bot score (per-signer bot score is phase 2).")
        m24 = mon.filter(pl.col("month") == f"{int(lm[:4]) - 2}{lm[4:]}")
        if m24.height:
            a = m24.row(0, named=True)
            T.add("Q1", "q1.organic_proxy_change_24m",
                  f"Organic proxy per day, {lm} vs {a['month']}",
                  growth(last["organic_proxy_txns"] / last["nb_days"], a["organic_proxy_txns"] / a["nb_days"])
                  if a["organic_proxy_txns"] else None, "ratio", f"{a['month']} to {lm}",
                  "census + stratified block sample", "A", notes="Point estimates; month-level CIs are wide.")
            T.add("Q1", "q1.organic_proxy_per_day_24m_before", f"Organic proxy per day, {a['month']}",
                  (a["organic_proxy_txns"] / a["nb_days"]) if a["organic_proxy_txns"] is not None else None,
                  "count", a["month"], "census + stratified block sample", "A",
                  ci_low=(a["organic_proxy_txns_p05"] / a["nb_days"]) if a["organic_proxy_txns_p05"] is not None else None,
                  ci_high=(a["organic_proxy_txns_p95"] / a["nb_days"]) if a["organic_proxy_txns_p95"] is not None else None)
        valid = mon.filter(pl.col("share_game_hot_tg") > 0).drop_nulls("hot_census_in_sample_ci")
        T.add("Q1", "q1.sample_validation_hot", "Months where the census HOT share falls inside the sample's 90% CI",
              valid["hot_census_in_sample_ci"].mean() if valid.height else None, "ratio",
              f"{valid.height} months with HOT activity", "census vs block sample", "A",
              notes="Checks the block-sampling method against an exact count.")
        T.add("Q1", "q1.sample_vs_nearblocks_median", "Median of sample-implied / NearBlocks monthly transactions",
              mon["sample_vs_nearblocks_txns"].median(), "ratio", "all months", "block sample vs nearblocks", "B",
              notes="Coverage cross-check between FastNear and NearBlocks indexes (noisy per month).")
    q = act["quarterly"].sort("quarter")
    qfull = q.filter(pl.col("months") == 3)
    if qfull.height:
        lq = qfull.row(-1, named=True)
        for c, label in (("relayed", "relayed (meta-transaction) txs"), ("implicit_signer", "txs signed by implicit accounts"),
                         ("hot", "txs to HOT (sample estimate)")):
            T.add("Q1", f"q1.{c}_share_{lq['quarter']}", f"Share of {label}, {lq['quarter']}", lq[f"{c}_share"],
                  "ratio", lq["quarter"], "stratified block sample", "A", ci_low=lq[f"{c}_share_p05"],
                  ci_high=lq[f"{c}_share_p95"])

    # ---------------- Q4 supply ---------------------------------------------------------------------------------
    sup = nb("total_supply")
    s_now, s_1y, s_2y = at(sup, end), at(sup, yago), at(sup, yago - dt.timedelta(days=365))
    T.add("Q4", "q4.total_supply", "Total supply", s_now, "NEAR", as_of, "nearblocks /v1/charts", "B")
    T.add("Q4", "q4.supply_growth_365d", "Realized supply growth, last 365 days", growth(s_now, s_1y), "ratio",
          f"{yago} to {as_of}", "nearblocks /v1/charts", "B")
    T.add("Q4", "q4.supply_growth_prev_365d", "Realized supply growth, the 365 days before", growth(s_1y, s_2y),
          "ratio", f"{yago - dt.timedelta(days=365)} to {yago}", "nearblocks /v1/charts", "B")
    T.add("Q4", "q4.circulating_share", "Circulating / total supply",
          ratio(at(nb("circulating_supply"), end), s_now), "ratio", as_of, "nearblocks /v1/charts", "B")
    pc = _kv(raw, "rpc/protocol_config_latest.csv")
    a, b = pc.get("max_inflation_rate", "0/1").split("/")
    T.add("Q4", "q4.max_inflation_rate_now", "Protocol max_inflation_rate (current)", int(a) / int(b), "ratio/yr",
          "final block at refresh", "rpc EXPERIMENTAL_protocol_config", "A")
    if events.height:
        ev = events.row(-1, named=True)
        T.add("Q4", "q4.last_inflation_change", f"Last max_inflation_rate change: {ev['from_rate']} -> {ev['to_rate']}",
              ev["to_rate"], "ratio/yr", f"between {ev['last_sample_before_utc']} and {ev['first_sample_after_utc']}",
              "archival epoch samples", "A")
    rec = epochs.filter(pl.col("start_date") > str(yago))
    if rec.height:
        T.add("Q4", "q4.mint_rate_365d", "Realized issuance rate (annualized), sampled epochs, last 365 days",
              rec["mint_annualized_rate"].mean(), "ratio/yr", f"{rec.height} epochs since {yago}",
              "archival block headers", "A")
        T.add("Q4", "q4.burn_rate_365d", "Fee burn rate (annualized), sampled epochs, last 365 days",
              rec["burn_annualized_rate"].mean(), "ratio/yr", f"{rec.height} epochs since {yago}",
              "archival block headers", "A")
        T.add("Q4", "q4.burn_to_mint_365d", "Burn offset: burned / minted NEAR, sampled epochs, last 365 days",
              ratio(rec["burn_near"].sum(), rec["mint_next_near"].sum()), "ratio", f"{rec.height} epochs since {yago}",
              "archival block headers", "A")
        T.add("Q4", "q4.realized_to_cap_365d", "Realized issuance / protocol cap, mean of sampled epochs",
              rec["realized_to_cap"].mean(), "ratio", f"{rec.height} epochs since {yago}", "archival block headers", "A",
              notes="Below 1 when validators miss blocks/chunks (reward scaled by uptime).")
    ident = epochs.drop_nulls("block_identity_holds")
    T.add("Q4", "q4.block_identity_pass_rate", "Exact per-block identity supply(b) = supply(prev) - burnt(b)",
          ident["block_identity_holds"].mean() if ident.height else None, "ratio", f"{ident.height} block pairs",
          "archival block headers", "A", notes="Exact yoctoNEAR integer comparison.")
    st = epochs.drop_nulls("staking_ratio")
    if st.height:
        ls = st.row(-1, named=True)
        T.add("Q4", "q4.staking_ratio_last_sample", f"Staking ratio (validator stake / total supply), epoch starting {ls['start_date']}",
              ls["staking_ratio"], "ratio", ls["start_date"], "archival validators", "A")
        y = st.filter(pl.col("start_date") <= str(yago))
        if y.height:
            T.add("Q4", "q4.staking_ratio_year_before", f"Staking ratio, epoch starting {y['start_date'][-1]}",
                  y["staking_ratio"][-1], "ratio", y["start_date"][-1], "archival validators", "A")
    vc = io.read_csv(raw / "rpc" / "validators_current.csv").with_columns(pl.col("stake_yocto").cast(pl.Float64))
    fb = io.read_csv(raw / "rpc" / "final_block_header.csv")
    stake_now = vc["stake_yocto"].sum() / 1e24
    T.add("Q4", "q4.staked_now", "Stake of current validators", stake_now, "NEAR", "epoch at refresh", "rpc validators", "A")
    T.add("Q4", "q4.staking_ratio_now", "Staking ratio at refresh", stake_now / (float(fb["total_supply_yocto"][0]) / 1e24),
          "ratio", "final block at refresh", "rpc validators + block header", "A")
    T.add("Q4", "q4.validators_now", "Validators in the current epoch", vc.height, "count", "epoch at refresh",
          "rpc validators", "A")
    stakes = sorted(vc["stake_yocto"].to_list(), reverse=True)
    acc, nak = 0.0, 0
    for s in stakes:
        acc += s
        nak += 1
        if acc * 3 > sum(stakes):
            break
    T.add("Q4", "q4.nakamoto_now", "Nakamoto coefficient (validators controlling > 1/3 of stake)", nak, "count",
          "epoch at refresh", "rpc validators", "A")
    tr = epochs.drop_nulls("treasury_reward_share")
    if tr.height:
        T.add("Q4", "q4.treasury_reward_share_last_sample", "Share of epoch rewards paid to treasury.near (last sample)",
              tr["treasury_reward_share"][-1], "ratio", tr["start_date"][-1], "archival validators", "A")
    if tre.height:
        for acc, short in (("buybacks.multisignature.near", "buyback_wallet"), ("treasury.near", "treasury"),
                           ("fefundsadmin.sputnik-dao.near", "fefundsadmin")):
            a = tre.filter(pl.col("account_id") == acc).sort("date").with_columns(pl.col("liquid_near").fill_null(0.0))
            if a.height < 7:
                continue
            last_r, six = a.row(-1, named=True), a.row(-7, named=True)
            T.add("Q4", f"q4.{short}_net_change_6m", f"{acc} net liquid balance change, {six['date']} to {last_r['date']}",
                  last_r["liquid_near"] - six["liquid_near"], "NEAR", f"{six['date']} to {last_r['date']}",
                  "archival view_account (month starts)", "A",
                  notes="Net balance change, not a ledger of purchases or transfers (phase 2: wallet histories).")
            ch = a["liquid_near"].diff().tail(6)
            T.add("Q4", f"q4.{short}_median_monthly_change_6m", f"{acc} median monthly balance change, last 6 months",
                  ch.median(), "NEAR", f"6 months to {last_r['date']}", "archival view_account (month starts)", "A")
    tac = io.read_csv(raw / "rpc" / "treasury_accounts_current.csv")
    for r in tac.iter_rows(named=True):
        if r["amount_yocto"]:
            T.add("Q4", f"q4.balance_now.{r['account_id']}", f"{r['account_id']} liquid balance at refresh",
                  float(r["amount_yocto"]) / 1e24, "NEAR", "final block at refresh", "rpc view_account", "A")

    # ---------------- Q5 fees and value accrual -------------------------------------------------------------------
    fee_nb30, fee_nb365 = full_wsum(nb("tx_fees_usd"), end, 30), full_wsum(nb("tx_fees_usd"), end, 365)
    fee_dl30, fee_dl365 = full_wsum(dl("chain_fees_usd"), end, 30), full_wsum(dl("chain_fees_usd"), end, 365)
    T.add("Q5", "q5.tx_fees_usd_30d", "NEAR transaction fees, last 30 days (NearBlocks)", fee_nb30, "USD", f"30d to {as_of}",
          "nearblocks /v1/charts", "B")
    T.add("Q5", "q5.tx_fees_usd_365d", "NEAR transaction fees, last 365 days (NearBlocks)", fee_nb365, "USD",
          f"365d to {as_of}", "nearblocks /v1/charts", "B")
    T.add("Q5", "q5.chain_fees_usd_30d", "NEAR chain fees, last 30 days (DefiLlama)", fee_dl30, "USD", f"30d to {as_of}",
          "defillama summary/fees/near", "B")
    T.add("Q5", "q5.fee_sources_ratio_30d", "Fees cross-check: NearBlocks / DefiLlama, 30 days", ratio(fee_nb30, fee_dl30),
          "ratio", f"30d to {as_of}", "nearblocks vs defillama", "B")
    T.add("Q5", "q5.fee_sources_ratio_365d", "Fees cross-check: NearBlocks / DefiLlama, 365 days",
          ratio(fee_nb365, fee_dl365), "ratio", f"365d to {as_of}", "nearblocks vs defillama", "B")
    bv = bvf.filter(pl.col("start_date") > str(yago)).drop_nulls("burn_to_tx_fees")
    if bv.height:
        T.add("Q5", "q5.burn_share_of_fees_365d", "Burned NEAR / NEAR fees (NearBlocks txn_fee), sampled epochs, last 365 days",
              ratio(bv["burn_near"].sum(), bv["nb_tx_fees_near"].sum()), "ratio", f"{bv.height} epochs since {yago}",
              "archival headers vs nearblocks", "A/B")
    bg = bvf.filter(pl.col("start_date") > str(yago)).drop_nulls("burn_to_gas_fees")
    if bg.height:
        T.add("Q5", "q5.burn_share_of_gas_fees_365d", "Burned NEAR / NEAR gas fees (NearBlocks gas_fee), sampled epochs, last 365 days",
              ratio(bg["burn_near"].sum(), bg["nb_gas_fees_near"].sum()), "ratio", f"{bg.height} epochs since {yago}",
              "archival headers vs nearblocks", "A/B",
              notes="NearBlocks publishes two fee fields; the burn share depends on which one is the denominator.")
    bva = bvf.drop_nulls("burn_to_tx_fees")
    if bva.height:
        T.add("Q5", "q5.burn_share_of_fees_all", "Burned NEAR / NEAR fees, all sampled epochs",
              ratio(bva["burn_near"].sum(), bva["nb_tx_fees_near"].sum()), "ratio", f"{bva.height} epochs",
              "archival headers vs nearblocks", "A/B")
    for m, label in (("intents_volume_usd", "NEAR Intents volume"), ("intents_fees_usd", "NEAR Intents fees"),
                     ("intents_revenue_usd", "NEAR Intents revenue"),
                     ("intents_holders_revenue_usd", "NEAR Intents holders revenue")):
        ser = dl(m)
        if ser.is_empty():
            continue
        T.add("Q2", f"q2.{m}_30d", f"{label}, last 30 days", full_wsum(ser, end, 30), "USD", f"30d to {as_of}",
              "defillama near-intents", "B")
        T.add("Q2", f"q2.{m}_365d", f"{label}, last 365 days", full_wsum(ser, end, 365), "USD", f"365d to {as_of}",
              "defillama near-intents", "B")
    iv90, iv90p = full_wsum(dl("intents_volume_usd"), end, 90), full_wsum(dl("intents_volume_usd"), end - dt.timedelta(days=90), 90)
    T.add("Q2", "q2.intents_volume_90d_growth", "NEAR Intents volume, last 90 days vs previous 90 days", growth(iv90, iv90p),
          "ratio", f"90d to {as_of}", "defillama near-intents", "B")
    iv_all = dl("intents_volume_usd")
    T.add("Q2", "q2.intents_volume_alltime", "NEAR Intents volume, all time", iv_all["value"].sum() if iv_all.height else None,
          "USD", f"{iv_all['date'].min()} to {as_of}" if iv_all.height else "", "defillama near-intents", "B")
    iv30, if30, ir30 = (full_wsum(dl(m), end, 30) for m in ("intents_volume_usd", "intents_fees_usd", "intents_revenue_usd"))
    T.add("Q5", "q5.intents_fee_take_rate_30d", "NEAR Intents fees / volume, 30 days", ratio(if30, iv30), "ratio",
          f"30d to {as_of}", "defillama near-intents", "B")
    T.add("Q5", "q5.intents_revenue_take_rate_30d", "NEAR Intents revenue / volume, 30 days", ratio(ir30, iv30), "ratio",
          f"30d to {as_of}", "defillama near-intents", "B")
    price = at(series(daily, "near", "price_usd", "coingecko"), end)
    r90 = epochs.filter(pl.col("start_date") > str(end - dt.timedelta(days=90)))
    if r90.height and price:
        iss30 = r90["mint_per_day_near"].mean() * 30 * price
        T.add("Q5", "q5.issuance_usd_30d", "Issuance value, 30 days at as-of price (mint/day from sampled epochs, last 90 days)",
              iss30, "USD", f"{r90.height} epochs, price {as_of}", "archival headers + coingecko", "A/B")
        T.add("Q5", "q5.intents_revenue_to_issuance_30d", "NEAR Intents revenue / issuance value, 30 days",
              ratio(ir30, iss30), "ratio", f"30d to {as_of}", "defillama + archival headers", "B")
        burn30 = r90["burn_per_day_near"].mean() * 30 * price
        T.add("Q5", "q5.burn_usd_30d", "Burn value, 30 days at as-of price (burn/day from sampled epochs, last 90 days)",
              burn30, "USD", f"{r90.height} epochs, price {as_of}", "archival headers + coingecko", "A/B")
    nrow = peers.filter(pl.col("chain") == "near").row(0, named=True)
    T.add("Q5", "q5.fees_to_mcap", "NEAR chain fees (30d annualized) / market cap", nrow["fees_30d_annualized_to_mcap"],
          "ratio", nrow["as_of"], "defillama + coingecko", "B")
    if ir30 is not None and nrow["market_cap_usd"]:
        T.add("Q5", "q5.fees_plus_intents_rev_to_mcap", "(NEAR chain fees + Intents revenue) 30d annualized / market cap",
              ((nrow["chain_fees_30d_usd"] or 0) + ir30) * 365 / 30 / nrow["market_cap_usd"], "ratio", nrow["as_of"],
              "defillama + coingecko", "B")

    # ---------------- Q7 comparables (headline only; full table in peers.csv) ---------------------------------------
    for c in ("tvl_to_mcap", "dex_volume_30d_to_tvl", "stablecoins_to_mcap"):
        T.add("Q7", f"q7.near_{c}", f"NEAR {c.replace('_', ' ')}", nrow[c], "ratio", nrow["as_of"], "defillama + coingecko", "B")
    T.add("Q7", "q7.near_tvl", "NEAR TVL", nrow["tvl_usd"], "USD", nrow["as_of"], "defillama", "B")
    T.add("Q7", "q7.near_dex_volume_30d", "NEAR DEX volume, 30 days (DefiLlama, includes Intents)",
          nrow["dex_volume_30d_usd"], "USD", nrow["as_of"], "defillama", "B")
    T.add("Q7", "q7.near_dex_volume_30d_ex_intents", "NEAR DEX volume, 30 days, excluding NEAR Intents",
          nrow["dex_volume_30d_ex_intents_usd"], "USD", nrow["as_of"], "defillama", "B")
    T.add("Q7", "q7.near_dex_volume_30d_ex_intents_to_tvl", "NEAR DEX volume excluding Intents, 30 days / TVL",
          ratio(nrow["dex_volume_30d_ex_intents_usd"], nrow["tvl_usd"]), "ratio", nrow["as_of"], "defillama", "B")

    # ---------------- context: Aurora, governance ------------------------------------------------------------------
    au = lambda m: series(daily, "aurora", m, "aurora_blockscout")  # noqa: E731
    T.add("Q1", "q1.aurora_txns_30d_avg", "Aurora (EVM on NEAR) transactions per day, 30-day average",
          wmean(au("txns"), end, 30), "count", f"30d to {as_of}", "aurora blockscout stats", "B")
    T.add("Q1", "q1.aurora_active_accounts_30d_avg", "Aurora active accounts per day, 30-day average",
          wmean(au("active_accounts"), end, 30), "count", f"30d to {as_of}", "aurora blockscout stats", "B")
    daos = io.read_csv(raw / "rpc" / "sputnik_dao_list.csv")
    T.add("Q4", "q4.sputnik_daos", "DAOs created by the Sputnik DAO factory", daos.height, "count", "at refresh",
          "rpc sputnik-dao.near get_dao_list", "A")
    return T.frame()


def build(out_root: str | Path | None = None, quiet: bool = False) -> dict[str, Path]:
    out = Path(out_root) if out_root else paths.ROOT
    processed, reports = out / "data" / "processed", out / "reports"
    raw = paths.RAW
    m = manifest.load()
    as_of = compute_as_of(m)
    tracked = list(config.load()["activity"]["receivers"])

    daily = daily_mod.build_daily_long(raw, as_of)
    cov = daily_mod.coverage(daily)
    epochs = supply.build_epochs(raw)
    conc = supply.build_validator_concentration(raw)
    groups = {k: list(v) for k, v in config.load()["activity"].get("groups", {}).items()}
    act = activity.build_monthly(raw, daily, tracked, as_of, groups)
    as_of_peers = metrics.peers_as_of(daily, as_of)
    peers = metrics.build_peers(daily, as_of_peers)
    ratios = metrics.build_ratios_daily(daily)
    events = metrics.protocol_events(epochs)
    bvf = metrics.burn_vs_fees(epochs, daily)
    tre = metrics.treasury_monthly(raw)
    fp = first_pass(raw, daily, epochs, act, peers, bvf, events, tre, as_of)
    near_wide = (daily.filter(pl.col("chain") == "near")
                 .with_columns((pl.col("metric") + "__" + pl.col("source")).alias("col"))
                 .pivot(on="col", index="date", values="value", sort_columns=True).sort("date"))

    inv = raw_inventory(m, raw)
    written: dict[str, Path] = {}

    def w(name: str, df: pl.DataFrame, sort_by: list[str] | None) -> None:
        p = processed / name
        io.write_csv(df, p, sort_by=sort_by)
        written[name] = p

    w("daily_long.csv", daily, ["chain", "metric", "source", "date"])
    w("near_daily_wide.csv", near_wide, ["date"])
    w("series_coverage.csv", cov, ["chain", "metric", "source"])
    w("epochs.csv", epochs, ["start_height"])
    w("validator_concentration.csv", conc, ["start_height"])
    w("protocol_events.csv", events, ["height_before"])
    w("burn_vs_fees_epochs.csv", bvf, ["start_height"])
    w("activity_monthly.csv", act["monthly"], ["month"])
    w("activity_quarterly_sample.csv", act["quarterly"], ["quarter"])
    w("activity_signer_mix_sample.csv", act["signer_mix"], ["month", "signer_kind"])
    w("activity_top_receivers_sample.csv", act["top_receivers"], None)
    w("census_vs_sample.csv", act["census_vs_sample"], ["account_id"])
    w("peers_snapshot.csv", peers, ["chain"])
    w("ratios_daily.csv", ratios, ["chain", "mcap_source", "metric", "date"])
    if tre.height:
        w("treasury_monthly.csv", tre, ["account_id", "date"])
    w("metrics_first_pass.csv", fp, None)
    w("raw_inventory.csv", inv, ["file"])

    md = report.render(m=m, as_of=as_of, as_of_peers=as_of_peers, fp=fp, epochs=epochs, act=act, peers=peers,
                       cov=cov, events=events, bvf=bvf, conc=conc, inv=inv)
    reports.mkdir(parents=True, exist_ok=True)
    rp = reports / "metrics_summary.md"
    rp.write_text(md)
    written["metrics_summary.md"] = rp
    # phase 2a: analysis layer and models (reports/analysis_summary.md, reports/models_summary.md)
    from . import phase2
    written.update(phase2.build(raw, processed, reports, daily=daily, epochs=epochs, peers=peers, as_of=as_of, fp=fp))
    if not quiet:
        print(report.console_table(fp))
        p2 = written.get("metrics_phase2.csv")
        if p2 is not None:
            print("\n" + report.console_table(pl.read_csv(p2, infer_schema_length=None)).replace(
                "Key results (first pass)", "Key results (phase 2a: analysis layer and models)"))
        print(f"\n[build] as-of {as_of}; wrote {len(written)} files to {processed} and {reports}")
    return written
