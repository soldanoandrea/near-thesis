"""(a) Supply and value-accrual scenarios: 2.5% issuance cap (status quo) vs HSP-029 (ramp to 1.6%), with fee burn
and NEAR Intents buybacks as offsets, 1-5 year horizons.

Monthly recursion (t = months from the start, dt = 1/12 year):
  cap(t)       = 2.5% status quo, or HSP-029: 2.5% - 0.9% x min(max(t - activation, 0), 24) / 24
  issued(t)    = S(t) x cap(t) x realized_to_cap x dt                       (minted to validators + treasury)
  burned(t)    = S(t) x burn_rate x fee_growth^(t/12) x dt                   (70%+ of gas fees, removed from supply)
  bought(t)    = S(t) x buyback_yield x revenue_growth^(t/12) / price_growth^(t/12) x dt
                 (NEAR bought back with Intents revenue; held, not burned: it leaves the float, not total supply)
  S(t+1)       = S(t) + issued(t) - burned(t)
  float(t+1)   = float(t) + issued(t) - burned(t) - bought(t)
`buyback_yield` is annualized buyback USD / market cap at the start; dividing by the price path converts USD revenue
into NEAR. Every parameter is an input; `phase2` derives the base values from the data and sets the ranges.
"""

from __future__ import annotations

import polars as pl

STATUS_QUO_CAP = 0.025
HSP029_TARGET = 0.016
HSP029_RAMP_MONTHS = 24


def cap_path(month: int, policy: str, activation_month: int) -> float:
    """Issuance cap (annual rate) in force during month `month` (0-based) under a policy."""
    if policy == "status_quo":
        return STATUS_QUO_CAP
    if policy == "hsp029":
        k = min(max(month - activation_month, 0), HSP029_RAMP_MONTHS)
        return STATUS_QUO_CAP - (STATUS_QUO_CAP - HSP029_TARGET) * k / HSP029_RAMP_MONTHS
    raise ValueError(policy)


def project(supply0: float, months: int, *, policy: str, activation_month: int = 3, realized_to_cap: float = 1.0,
            burn_rate: float = 0.0, fee_growth: float = 1.0, buyback_yield: float = 0.0, revenue_growth: float = 1.0,
            price_growth: float = 1.0) -> pl.DataFrame:
    """Month-by-month supply path. Rates are annual fractions; growth factors are per year (1.0 = flat)."""
    s, flt = float(supply0), float(supply0)
    rows = []
    cum_i = cum_b = cum_bb = 0.0
    for t in range(months):
        yrs = t / 12
        cap = cap_path(t, policy, activation_month)
        iss = s * cap * realized_to_cap / 12
        brn = s * burn_rate * fee_growth ** yrs / 12
        bb = s * buyback_yield * (revenue_growth / price_growth) ** yrs / 12
        s, flt = s + iss - brn, flt + iss - brn - bb
        cum_i, cum_b, cum_bb = cum_i + iss, cum_b + brn, cum_bb + bb
        rows.append({"month": t + 1, "cap": cap, "issued": iss, "burned": brn, "bought_back": bb, "total_supply": s,
                     "float_supply": flt, "cum_issued": cum_i, "cum_burned": cum_b, "cum_bought_back": cum_bb})
    return pl.DataFrame(rows)


def scenario_table(supply0: float, scenarios: list[dict], horizons_years: list[int]) -> pl.DataFrame:
    """One row per scenario x horizon: supply, float, cumulative flows and annualized net dilution rates."""
    out = []
    months = 12 * max(horizons_years)
    for sc in scenarios:
        params = {k: v for k, v in sc.items() if k not in ("scenario", "policy")}
        path = project(supply0, months, policy=sc["policy"], **params)
        for h in horizons_years:
            r = path.filter(pl.col("month") == 12 * h).row(0, named=True)
            last12 = path.filter(pl.col("month").is_between(12 * h - 11, 12 * h))
            s_prev = path.filter(pl.col("month") == 12 * h - 12)["total_supply"]
            f_prev = path.filter(pl.col("month") == 12 * h - 12)["float_supply"]
            s0 = float(s_prev[0]) if s_prev.len() else supply0
            f0 = float(f_prev[0]) if f_prev.len() else supply0
            out.append({"scenario": sc["scenario"], "policy": sc["policy"], "horizon_years": h,
                        "total_supply": r["total_supply"], "float_supply": r["float_supply"],
                        "cum_issued": r["cum_issued"], "cum_burned": r["cum_burned"],
                        "cum_bought_back": r["cum_bought_back"],
                        "supply_growth_cagr": (r["total_supply"] / supply0) ** (1 / h) - 1,
                        "float_growth_cagr": (r["float_supply"] / supply0) ** (1 / h) - 1,
                        "year_issuance_rate": float(last12["issued"].sum()) / s0,
                        "year_offset_rate": float(last12["burned"].sum() + last12["bought_back"].sum()) / s0,
                        "year_net_float_dilution": r["float_supply"] / f0 - 1,
                        "offsets_cover_issuance": bool(last12["burned"].sum() + last12["bought_back"].sum()
                                                       >= last12["issued"].sum())})
    return pl.DataFrame(out)


def net_zero_threshold(*, supply: float, price: float, issuance_rate: float, burn_rate: float, take_rate: float,
                       buyback_share: float, revenue_now_usd: float) -> dict:
    """Annual Intents revenue (USD) and volume at which burn + buybacks offset issuance, at a given price.

    take_rate = captured revenue / volume; buyback_share = share of captured revenue used to buy NEAR.
    """
    gap_near = max(issuance_rate - burn_rate, 0.0) * supply
    rev = gap_near * price / buyback_share if buyback_share > 0 else float("inf")
    vol = rev / take_rate if take_rate > 0 else float("inf")
    return {"required_revenue_usd": rev, "required_volume_usd": vol,
            "multiple_of_current_revenue": rev / revenue_now_usd if revenue_now_usd > 0 else float("inf")}


def threshold_grid(*, supply: float, prices: list[float], issuance_rates: list[float], burn_rate: float,
                   take_rates: list[float], buyback_share: float, revenue_now_usd: float,
                   volume_now_usd: float) -> pl.DataFrame:
    rows = []
    for p in prices:
        for i in issuance_rates:
            for tr in take_rates:
                r = net_zero_threshold(supply=supply, price=p, issuance_rate=i, burn_rate=burn_rate, take_rate=tr,
                                       buyback_share=buyback_share, revenue_now_usd=revenue_now_usd)
                rows.append({"price_usd": p, "issuance_rate": i, "take_rate": tr, **r,
                             "multiple_of_current_volume": r["required_volume_usd"] / volume_now_usd
                             if volume_now_usd > 0 else float("inf")})
    return pl.DataFrame(rows)
