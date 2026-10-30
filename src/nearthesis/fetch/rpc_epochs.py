"""Archival epoch sampler (sources #2, #20, #21): supply, mint, burn, stake and protocol config per sampled epoch.

For a target height h every `step_epochs` epochs from genesis, with E = epoch of h:
  validators(E)            -> start height of E, stake set of E
  block(start(E))          -> first block of E: total_supply, timestamp, chunk balance_burnt
  block(prev_hash)         -> last block of E-1
  validators(E-1)          -> start height of E-1, stake set, rewards map
  block(start(E-1))        -> first block of E-1
  block(start(E-1) + 1)    -> exact per-block identity check: supply(b) = supply(prev) - balance_burnt(b)
  EXPERIMENTAL_protocol_config at start(E-1) -> max_inflation_rate, protocol version, epoch length
Epoch E-1 is then fully characterized:
  burn(E-1)  = balance_burnt(first(E-1)) + supply(first(E-1)) - supply(last(E-1))        (no mint inside an epoch)
  mint(E)    = supply(first(E)) - supply(last(E-1)) + balance_burnt(first(E))          (mint lands on first block)
All amounts are kept as exact yoctoNEAR integers (strings). All requests are for finalized history => cached.
"""

from __future__ import annotations

import sys

import polars as pl

from .. import config, manifest
from ..http import PoliteClient, RpcError

HOSTS = ("archival-rpc.mainnet.fastnear.com", "archival-rpc.mainnet.near.org")
EPOCH_LEN = 43_200


class Archival:
    def __init__(self, client: PoliteClient):
        ep = config.load()["endpoints"]
        self.c = client
        self.url = ep["archival_rpc"]
        self.fallback = ep["archival_rpc_fallback"]

    def call(self, method: str, params, immutable: bool = True):
        try:
            return self.c.rpc(self.url, method, params, immutable=immutable)
        except RpcError:
            raise
        except Exception as exc:
            print(f"  {method} failed on FastNear archival ({exc}); trying near.org archival", file=sys.stderr)
            return self.c.rpc(self.fallback, method, params, immutable=immutable)

    def block(self, block_id):
        return self.call("block", {"block_id": block_id})

    def block_at_or_after(self, height: int, max_skip: int = 50):
        for h in range(height, height + max_skip):
            try:
                return self.block(h)
            except RpcError as exc:
                if exc.cause in ("UNKNOWN_BLOCK", "GARBAGE_COLLECTED_BLOCK"):
                    continue
                raise
        raise RuntimeError(f"no block found in [{height}, {height + max_skip})")

    def validators(self, epoch_id: str):
        """validators by epoch id, or None when the archival node no longer serves that epoch (UNKNOWN_EPOCH).

        Verified 2026-10-30: both FastNear and near.org archival answer UNKNOWN_EPOCH before epoch 545 (~2021-03).
        """
        try:
            return self.call("validators", {"epoch_id": epoch_id})
        except RpcError as exc:
            if exc.cause == "UNKNOWN_EPOCH":
                return None
            raise

    def epoch_start(self, epoch_id: str, height_in_epoch: int, genesis_h: int, hint: int | None = None) -> int:
        """First height of `epoch_id`, by bisection on block headers (used when `validators` is unavailable).

        Predicate P(h) = epoch_id(first existing block >= h) == epoch_id is monotone in h. A `hint` (expected start,
        epochs being ~43,200 heights long) gives a +-300 bracket that is verified before use; otherwise the full
        one-epoch bracket is searched.
        """
        def p(h: int) -> bool:
            return self.block_at_or_after(h)["header"]["epoch_id"] == epoch_id

        lo = hi = None
        if hint is not None and genesis_h < hint - 300 and hint + 300 <= height_in_epoch:
            if not p(hint - 300) and p(hint + 300):
                lo, hi = hint - 300, hint + 300
        if lo is None:
            lo = max(genesis_h, height_in_epoch - 45_000)
            while lo > genesis_h and p(lo):
                lo = max(genesis_h, lo - 45_000)
            if lo == genesis_h and p(lo):
                return genesis_h
            hi = height_in_epoch
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if p(mid):
                hi = mid
            else:
                lo = mid
        return int(self.block_at_or_after(hi)["header"]["height"])


def burnt_in_block(block: dict) -> int:
    h = block["header"]["height"]
    return sum(int(c["balance_burnt"]) for c in block["chunks"] if c["height_included"] == h)


def nakamoto(stakes: list[int]) -> int:
    total = sum(stakes)
    acc, n = 0, 0
    for s in sorted(stakes, reverse=True):
        acc += s
        n += 1
        if acc * 3 > total:
            return n
    return n


def fetch(client: PoliteClient) -> None:
    cfg = config.load()
    step = int(cfg["archival_epochs"]["step_epochs"])
    genesis_h = int(cfg["archival_epochs"]["genesis_height"])
    arc = Archival(client)

    latest = arc.call("block", {"finality": "final"}, immutable=False)["header"]["height"]
    # stop two epochs before the head so that both E-1 and E are finished epochs (immutable answers)
    targets = list(range(genesis_h + 2 * EPOCH_LEN + EPOCH_LEN // 2, latest - 2 * EPOCH_LEN, step * EPOCH_LEN))
    print(f"  epoch sampler: {len(targets)} targets, step {step} epochs, head {latest}", file=sys.stderr)

    epoch_rows, val_rows = [], []
    seen: set[str] = set()
    prev_start_e: int | None = None
    for i, target in enumerate(targets):
        b = arc.block_at_or_after(target)
        e_id = b["header"]["epoch_id"]
        v_e = arc.validators(e_id)
        start_e = (int(v_e["epoch_start_height"]) if v_e else
                   arc.epoch_start(e_id, b["header"]["height"], genesis_h,
                                   hint=(prev_start_e + step * EPOCH_LEN) if prev_start_e else None))
        prev_start_e = start_e
        first_e = arc.block(start_e)
        last_p = arc.block(first_e["header"]["prev_hash"])
        p_id = last_p["header"]["epoch_id"]
        if p_id in seen:
            continue
        seen.add(p_id)
        v_p = arc.validators(p_id)
        start_p = (int(v_p["epoch_start_height"]) if v_p
                   else arc.epoch_start(p_id, last_p["header"]["height"], genesis_h, hint=start_e - EPOCH_LEN))
        first_p = arc.block(start_p)
        check = arc.block_at_or_after(start_p + 1)  # non-boundary block: supply(check) = supply(prev) - burnt(check)
        try:
            pc = arc.call("EXPERIMENTAL_protocol_config", {"block_id": first_p["header"]["height"]})
        except RpcError as exc:
            print(f"  protocol_config unavailable at {start_p}: {exc.cause}", file=sys.stderr)
            pc = {}

        stakes_p = [int(x["stake"]) for x in v_p["current_validators"]] if v_p else []
        stakes_e = [int(x["stake"]) for x in v_e["current_validators"]] if v_e else []
        rewards = {k: int(x) for k, x in ((v_p or {}).get("validator_reward_paid_prev_epoch") or {}).items()}
        treasury = pc.get("protocol_treasury_account", "treasury.near")
        mir = pc.get("max_inflation_rate")
        prr = pc.get("protocol_reward_rate")
        fh, lh, nh = first_p["header"], last_p["header"], first_e["header"]

        def opt(x):
            return None if x is None else str(x)

        epoch_rows.append({
            "epoch_height": opt(v_p["epoch_height"]) if v_p else None,
            "epoch_id": p_id,
            "validators_available": "true" if v_p else "false",
            "start_height": str(fh["height"]),
            "start_timestamp_ns": str(fh["timestamp_nanosec"]),
            "last_height": str(lh["height"]),
            "last_timestamp_ns": str(lh["timestamp_nanosec"]),
            "next_start_height": str(nh["height"]),
            "next_start_timestamp_ns": str(nh["timestamp_nanosec"]),
            "supply_start_yocto": fh["total_supply"],
            "supply_last_yocto": lh["total_supply"],
            "supply_next_start_yocto": nh["total_supply"],
            "burnt_start_block_yocto": str(burnt_in_block(first_p)),
            "burnt_next_start_block_yocto": str(burnt_in_block(first_e)),
            "gas_price_start_yocto": fh["gas_price"],
            "check_height": str(check["header"]["height"]),
            "check_prev_hash_is_start": "true" if check["header"]["prev_hash"] == fh["hash"] else "false",
            "check_supply_yocto": check["header"]["total_supply"],
            "check_burnt_yocto": str(burnt_in_block(check)),
            "protocol_version": opt(pc.get("protocol_version")),
            "epoch_length": opt(pc.get("epoch_length")),
            "max_inflation_rate": f"{mir[0]}/{mir[1]}" if mir else None,
            "protocol_reward_rate": f"{prr[0]}/{prr[1]}" if prr else None,
            "num_validators": opt(len(stakes_p)) if v_p else None,
            "total_stake_yocto": opt(sum(stakes_p)) if v_p else None,
            "nakamoto_coefficient": opt(nakamoto(stakes_p)) if v_p else None,
            "next_num_validators": opt(len(stakes_e)) if v_e else None,
            "next_total_stake_yocto": opt(sum(stakes_e)) if v_e else None,
            "reward_recipients": opt(len(rewards)) if v_p else None,
            "reward_paid_total_yocto": opt(sum(rewards.values())) if v_p else None,
            "reward_paid_treasury_yocto": opt(rewards.get(treasury, 0)) if v_p else None,
        })
        if v_p:
            for x in v_p["current_validators"]:
                val_rows.append((str(v_p["epoch_height"]), str(fh["height"]), x["account_id"], x["stake"]))
        if (i + 1) % 10 == 0:
            print(f"  epochs {i + 1}/{len(targets)} (start height {fh['height']})", file=sys.stderr, flush=True)

    df = pl.DataFrame(epoch_rows, schema={k: pl.Utf8 for k in epoch_rows[0]})
    df = df.with_columns(pl.col("start_height").cast(pl.Int64)).sort("start_height").with_columns(
        pl.col("start_height").cast(pl.Utf8))
    params = {"step_epochs": step, "genesis_height": genesis_h, "head_height_at_fetch": latest,
              "targets": len(targets)}
    manifest.save_table("rpc_archival", "epochs_sampled", df,
                        urls=[f"{arc.url} block / validators / EXPERIMENTAL_protocol_config"], params=params,
                        notes="One fully characterized epoch per sample (see module docstring for the identities). "
                              "yoctoNEAR integers stored as strings. validators_available=false: archival nodes "
                              "answer UNKNOWN_EPOCH before epoch 545 (~2021-03), so epoch boundaries were found by "
                              "bisection on block-header epoch_id and stake fields are empty. Fallback host: "
                              "archival-rpc.mainnet.near.org.",
                        http_stats=client.stats_for(*HOSTS))
    vdf = pl.DataFrame(val_rows, schema={"epoch_height": pl.Utf8, "start_height": pl.Utf8, "account_id": pl.Utf8,
                                         "stake_yocto": pl.Utf8}, orient="row")
    vdf = vdf.with_columns(pl.col("start_height").cast(pl.Int64)).sort(["start_height", "account_id"]).with_columns(
        pl.col("start_height").cast(pl.Utf8))
    manifest.save_table("rpc_archival", "epoch_validator_stakes", vdf,
                        urls=[f"{arc.url} validators {{epoch_id}}"], params=params,
                        notes="current_validators stake of every sampled epoch (raw validators responses are "
                              "~0.4 MB each and are not committed; this table keeps account_id and stake only).",
                        http_stats=client.stats_for(*HOSTS))
