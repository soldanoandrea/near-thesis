"""(d) Staking yield and real yield: nominal reward rate vs issuance vs burn vs buybacks.

Definitions (annual rates, fractions of total supply unless stated):
  issuance           = realized mint rate (archival supply deltas)
  gross staker yield = issuance x (1 - treasury share of rewards) / staking ratio      (before validator commission)
  net staker yield   = gross x (1 - commission)
  net dilution       = issuance - burn                (total supply growth)
  float dilution     = issuance - burn - buybacks     (buybacks are held, not burned: they leave the float only)
  real staker yield  = (1 + net staker yield) / (1 + float dilution) - 1   (change in a staker's share of the float)
  non-staker real    = 1 / (1 + float dilution) - 1
"""

from __future__ import annotations

import polars as pl


def real_yields(issuance: float, burn: float, buyback: float, staking_ratio: float, treasury_share: float,
                commission: float) -> dict:
    gross = issuance * (1 - treasury_share) / staking_ratio if staking_ratio > 0 else None
    net = gross * (1 - commission) if gross is not None else None
    float_dil = issuance - burn - buyback
    return {"issuance_rate": issuance, "burn_rate": burn, "buyback_rate": buyback,
            "net_supply_growth": issuance - burn, "float_dilution": float_dil, "staking_ratio": staking_ratio,
            "treasury_share": treasury_share, "commission": commission, "gross_staker_yield": gross,
            "net_staker_yield": net,
            "real_staker_yield": (1 + net) / (1 + float_dil) - 1 if net is not None else None,
            "real_non_staker_yield": 1 / (1 + float_dil) - 1}


def historical_table(periods: pl.DataFrame, commission: float) -> pl.DataFrame:
    """periods columns: period, issuance_rate, burn_rate, buyback_rate, staking_ratio, treasury_share."""
    rows = []
    for r in periods.iter_rows(named=True):
        if r["staking_ratio"] is None or r["issuance_rate"] is None:
            continue
        rows.append({"period": r["period"], **real_yields(r["issuance_rate"], r["burn_rate"] or 0.0,
                                                          r["buyback_rate"] or 0.0, r["staking_ratio"],
                                                          r["treasury_share"] if r["treasury_share"] is not None
                                                          else 0.1, commission)})
    return pl.DataFrame(rows, infer_schema_length=None)


def scenario_grid(caps: dict[str, float], realized_to_cap: float, burn: float, buybacks: list[float],
                  staking_ratios: list[float], treasury_share: float, commissions: list[float]) -> pl.DataFrame:
    rows = []
    for name, cap in caps.items():
        for bb in buybacks:
            for sr in staking_ratios:
                for c in commissions:
                    rows.append({"policy": name, **real_yields(cap * realized_to_cap, burn, bb, sr, treasury_share, c)})
    return pl.DataFrame(rows, infer_schema_length=None)
