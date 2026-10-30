"""Current on-chain state via public RPC and FastNear (sources #1, #4, #5, #20-#22). Keyless, one snapshot per refresh.

* EXPERIMENTAL_genesis_config, EXPERIMENTAL_protocol_config, validators (current epoch), final block header.
* Sputnik DAO factory `get_dao_list` (DAO count).
* view_account + FastNear /v1/account/<id>/full for treasury / revenue / buyback wallets.
* FastNear Transactions API all-time txs_count for the tracked receivers (role filter: is_real_receiver).
"""

from __future__ import annotations

import base64
import json

import polars as pl

from .. import config, manifest
from ..http import PoliteClient, RpcError

RPC_HOSTS = ("free.rpc.fastnear.com", "rpc.mainnet.near.org")


def _rpc(client: PoliteClient, method: str, params) -> dict:
    ep = config.load()["endpoints"]
    try:
        return client.rpc(ep["rpc"], method, params)
    except RpcError:
        raise
    except Exception as exc:  # fall back to near.org RPC on transport failure
        print(f"  {method} failed on primary RPC ({exc}); using fallback")
        return client.rpc(ep["rpc_fallback"], method, params)


def _flatten_scalars(d: dict, prefix: str = "") -> list[tuple[str, str]]:
    out = []
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out += _flatten_scalars(v, key + ".")
        elif isinstance(v, list) and len(v) == 2 and all(isinstance(x, int) for x in v):
            out.append((key, f"{v[0]}/{v[1]}"))  # rationals such as max_inflation_rate
        elif isinstance(v, (str, int, float, bool)) or v is None:
            out.append((key, "" if v is None else str(v)))
    return out


def fetch(client: PoliteClient) -> None:
    cfg = config.load()
    ep = cfg["endpoints"]

    # genesis + protocol config ---------------------------------------------------------------------------
    gen = _rpc(client, "EXPERIMENTAL_genesis_config", {})
    df = pl.DataFrame(_flatten_scalars(gen), schema={"key": pl.Utf8, "value": pl.Utf8}, orient="row")
    manifest.save_table("rpc", "genesis_config", df, urls=[f"{ep['rpc']} EXPERIMENTAL_genesis_config"],
                        sort_by=["key"], notes="Scalar fields of the mainnet genesis config.",
                        http_stats=client.stats_for(*RPC_HOSTS))

    final = _rpc(client, "block", {"finality": "final"})
    h = final["header"]
    pc = _rpc(client, "EXPERIMENTAL_protocol_config", {"block_id": h["height"]})
    df = pl.DataFrame(_flatten_scalars(pc), schema={"key": pl.Utf8, "value": pl.Utf8}, orient="row")
    manifest.save_table("rpc", "protocol_config_latest", df,
                        urls=[f"{ep['rpc']} EXPERIMENTAL_protocol_config"], params={"block_id": h["height"]},
                        sort_by=["key"], notes="Scalar fields of the protocol config at the final block of the refresh.",
                        http_stats=client.stats_for(*RPC_HOSTS))

    burnt = sum(int(c["balance_burnt"]) for c in final["chunks"] if c["height_included"] == h["height"])
    df = pl.DataFrame([{"height": str(h["height"]), "hash": h["hash"], "timestamp_ns": str(h["timestamp_nanosec"]),
                        "epoch_id": h["epoch_id"], "total_supply_yocto": h["total_supply"],
                        "gas_price_yocto": h["gas_price"], "balance_burnt_yocto": str(burnt),
                        "latest_protocol_version": str(h["latest_protocol_version"])}])
    manifest.save_table("rpc", "final_block_header", df, urls=[f"{ep['rpc']} block finality=final"],
                        notes="Header of the final block at refresh time.", http_stats=client.stats_for(*RPC_HOSTS))

    # current validators ------------------------------------------------------------------------------------
    v = _rpc(client, "validators", [None])
    rows = [(x["account_id"], x["stake"], str(x.get("num_produced_blocks", "")), str(x.get("num_expected_blocks", "")),
             str(x.get("num_produced_chunks", "")), str(x.get("num_expected_chunks", "")))
            for x in v["current_validators"]]
    df = pl.DataFrame(rows, schema={"account_id": pl.Utf8, "stake_yocto": pl.Utf8, "produced_blocks": pl.Utf8,
                                    "expected_blocks": pl.Utf8, "produced_chunks": pl.Utf8, "expected_chunks": pl.Utf8},
                      orient="row").with_columns(pl.lit(str(v["epoch_start_height"])).alias("epoch_start_height"),
                                                 pl.lit(str(v["epoch_height"])).alias("epoch_height"))
    manifest.save_table("rpc", "validators_current", df, urls=[f"{ep['rpc']} validators [null]"],
                        sort_by=["account_id"], notes="current_validators of the epoch in progress at refresh time.",
                        http_stats=client.stats_for(*RPC_HOSTS))

    # Sputnik DAO factory ----------------------------------------------------------------------------------
    res = _rpc(client, "query", {"request_type": "call_function", "finality": "final", "account_id": "sputnik-dao.near",
                                 "method_name": "get_dao_list", "args_base64": base64.b64encode(b"{}").decode()})
    daos = json.loads(bytes(res["result"]))
    df = pl.DataFrame({"dao_id": daos}).with_columns(pl.lit(str(res["block_height"])).alias("block_height"))
    manifest.save_table("rpc", "sputnik_dao_list", df, urls=[f"{ep['rpc']} call_function sputnik-dao.near get_dao_list"],
                        sort_by=["dao_id"], notes="All DAOs created by the Sputnik DAO v2 factory.",
                        http_stats=client.stats_for(*RPC_HOSTS))

    # treasury / revenue wallets: view_account + FastNear holdings ------------------------------------------
    acc_rows, hold_rows = [], []
    for acc in cfg["treasury"]["accounts"]:
        try:
            va = _rpc(client, "query", {"request_type": "view_account", "finality": "final", "account_id": acc})
            acc_rows.append((acc, va["amount"], va["locked"], str(va["block_height"]), True))
        except RpcError as exc:
            acc_rows.append((acc, None, None, str(h["height"]), False))
            print(f"  view_account {acc}: {exc.cause}")
        full = client.get_json(f"{ep['fastnear_api']}/account/{acc}/full")
        for t in full.get("tokens") or []:
            hold_rows.append((acc, "ft", t.get("contract_id"), t.get("balance"), str(t.get("last_update_block_height"))))
        for p in full.get("pools") or []:
            hold_rows.append((acc, "staking_pool", p.get("pool_id"), None, str(p.get("last_update_block_height"))))
        for n in full.get("nfts") or []:
            hold_rows.append((acc, "nft", n.get("contract_id"), None, str(n.get("last_update_block_height"))))
    df = pl.DataFrame(acc_rows, schema={"account_id": pl.Utf8, "amount_yocto": pl.Utf8, "locked_yocto": pl.Utf8,
                                        "block_height": pl.Utf8, "exists": pl.Boolean}, orient="row")
    manifest.save_table("rpc", "treasury_accounts_current", df, urls=[f"{ep['rpc']} view_account"],
                        sort_by=["account_id"], notes="Liquid (amount) and staked-locked balances of tracked wallets.",
                        http_stats=client.stats_for(*RPC_HOSTS))
    df = pl.DataFrame(hold_rows, schema={"account_id": pl.Utf8, "kind": pl.Utf8, "contract_id": pl.Utf8,
                                         "balance_raw": pl.Utf8, "last_update_block_height": pl.Utf8}, orient="row")
    manifest.save_table("fastnear_api", "treasury_holdings_current", df,
                        urls=[f"{ep['fastnear_api']}/account/<id>/full"], sort_by=["account_id", "kind", "contract_id"],
                        notes="FastNear indexed FT / NFT / staking-pool holdings of tracked wallets. balance_raw is in "
                              "the token's smallest unit (decimals not resolved).",
                        http_stats=client.stats_for("api.fastnear.com"))

    # all-time tx counts per tracked receiver -----------------------------------------------------------------
    rows = []
    for acc in cfg["activity"]["receivers"]:
        d = client.post_json(f"{ep['fastnear_tx']}/v0/account",
                             {"account_id": acc, "is_real_receiver": True, "limit": 1})
        rows.append((acc, str(d["txs_count"])))
    df = pl.DataFrame(rows, schema={"account_id": pl.Utf8, "txs_count": pl.Utf8}, orient="row")
    manifest.save_table("fastnear_tx", "receiver_txs_alltime", df, urls=[f"{ep['fastnear_tx']}/v0/account"],
                        params={"is_real_receiver": True, "limit": 1}, sort_by=["account_id"],
                        notes="All-time count of transactions whose real receiver is the account (relayers excluded).",
                        http_stats=client.stats_for("tx.main.fastnear.com"))
