"""Per-epoch supply accounting from archival block headers (data/raw/rpc_archival/epochs_sampled.csv).

Exact integer arithmetic in yoctoNEAR; floats only for the published NEAR / ratio columns.
  burn(E)       = balance_burnt(first block of E) + supply(first of E) - supply(last of E)
  mint(E+1)     = supply(first of E+1) - supply(last of E) + balance_burnt(first of E+1)
  identity      = supply(check) == supply(first of E) - balance_burnt(check) for the block right after the first
Annualization uses nearcore's 365-day year (num_seconds_per_year = 31,536,000).
"""

from __future__ import annotations

import datetime as dt
from fractions import Fraction
from pathlib import Path

import polars as pl

from .. import io

YOCTO = 10**24
YEAR_S = 31_536_000


def _int(x: str | None) -> int | None:
    return None if x in (None, "") else int(x)


def _rate(x: str | None) -> float | None:
    if not x:
        return None
    a, b = x.split("/")
    return float(Fraction(int(a), int(b))) if int(b) else None


def build_epochs(raw: Path) -> pl.DataFrame:
    src = io.read_csv(raw / "rpc_archival" / "epochs_sampled.csv")
    rows = []
    for r in src.iter_rows(named=True):
        s0, s_last, s_next = int(r["supply_start_yocto"]), int(r["supply_last_yocto"]), int(r["supply_next_start_yocto"])
        b0, b_next = int(r["burnt_start_block_yocto"]), int(r["burnt_next_start_block_yocto"])
        burn = b0 + s0 - s_last
        mint = s_next - s_last + b_next
        t0, t1 = int(r["start_timestamp_ns"]), int(r["next_start_timestamp_ns"])
        dur_s = (t1 - t0) / 1e9
        identity = None
        if r.get("check_prev_hash_is_start") == "true":
            identity = int(r["check_supply_yocto"]) == s0 - int(r["check_burnt_yocto"])
        stake = _int(r.get("total_stake_yocto"))
        rew_total, rew_tre = _int(r.get("reward_paid_total_yocto")), _int(r.get("reward_paid_treasury_yocto"))
        mir = _rate(r.get("max_inflation_rate"))
        mint_rate = mint / s_last * YEAR_S / dur_s
        rows.append({
            "epoch_id": r["epoch_id"],
            "epoch_height": _int(r.get("epoch_height")),
            "start_height": int(r["start_height"]),
            "start_utc": dt.datetime.fromtimestamp(t0 / 1e9, dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "start_date": dt.datetime.fromtimestamp(t0 / 1e9, dt.UTC).strftime("%Y-%m-%d"),
            "duration_hours": dur_s / 3600,
            "blocks_in_epoch": int(r["next_start_height"]) - int(r["start_height"]),
            "protocol_version": _int(r.get("protocol_version")),
            "max_inflation_rate": mir,
            "supply_start_near": s0 / YOCTO,
            "burn_near": burn / YOCTO,
            "mint_next_near": mint / YOCTO,
            "net_issuance_near": (mint - burn) / YOCTO,
            "burn_per_day_near": burn / YOCTO / (dur_s / 86400),
            "mint_per_day_near": mint / YOCTO / (dur_s / 86400),
            "mint_annualized_rate": mint_rate,
            "burn_annualized_rate": burn / s0 * YEAR_S / dur_s,
            "net_annualized_rate": (mint - burn) / s0 * YEAR_S / dur_s,
            "realized_to_cap": (mint_rate / mir) if mir else None,
            "burn_to_mint": burn / mint if mint else None,
            "block_identity_holds": identity,
            "validators_available": r.get("validators_available") == "true",
            "num_validators": _int(r.get("num_validators")),
            "staked_near": stake / YOCTO if stake is not None else None,
            "staking_ratio": stake / s0 if stake is not None else None,
            "nakamoto_coefficient": _int(r.get("nakamoto_coefficient")),
            "treasury_reward_share": (rew_tre / rew_total) if rew_total else None,
            "gas_price_yocto_per_gas": int(r["gas_price_start_yocto"]),
        })
    return pl.DataFrame(rows).sort("start_height")


def build_validator_concentration(raw: Path) -> pl.DataFrame:
    """Top-1 / top-10 stake shares and Nakamoto coefficient per sampled epoch."""
    v = io.read_csv(raw / "rpc_archival" / "epoch_validator_stakes.csv").with_columns(
        pl.col("stake_yocto").cast(pl.Float64) / YOCTO, pl.col("start_height").cast(pl.Int64))
    v = v.sort(["start_height", "stake_yocto"], descending=[False, True])
    g = v.group_by("start_height", maintain_order=True).agg(
        pl.col("stake_yocto").sum().alias("total_stake_near"),
        pl.col("stake_yocto").first().alias("top1"),
        pl.col("stake_yocto").head(10).sum().alias("top10"),
        pl.len().alias("validators"))
    return g.with_columns((pl.col("top1") / pl.col("total_stake_near")).alias("top1_share"),
                          (pl.col("top10") / pl.col("total_stake_near")).alias("top10_share")).drop("top1", "top10")
