"""Print a status table of every keyless source (one light request each). Online; not part of `make reproduce`.

Usage: uv run python scripts/probe_sources.py
"""

from __future__ import annotations

import time

from nearthesis import config
from nearthesis.http import PoliteClient

ep = config.load()["endpoints"]
RPC = {"jsonrpc": "2.0", "id": "probe", "method": "status", "params": []}
PROBES = [
    ("NearBlocks charts (#7)", "GET", f"{ep['nearblocks']}/charts/latest", None),
    ("DefiLlama TVL (#12)", "GET", f"{ep['llama']}/v2/historicalChainTvl/Near", None),
    ("DefiLlama stablecoins (#12)", "GET", f"{ep['llama_stablecoins']}/stablecoincharts/Near", None),
    ("DefiLlama coins (#12)", "GET", f"{ep['llama_coins']}/prices/current/coingecko:near", None),
    ("CoinGecko keyless (#13)", "GET", f"{ep['coingecko']}/simple/price?ids=near&vs_currencies=usd", None),
    ("FastNear RPC (#1)", "POST", ep["rpc"], RPC),
    ("FastNear archival RPC (#2)", "POST", ep["archival_rpc"], RPC),
    ("near.org archival RPC (#2, fallback)", "POST", ep["archival_rpc_fallback"], RPC),
    ("FastNear API (#4)", "GET", f"{ep['fastnear_api']}/account/sputnik-dao.near/full", None),
    ("FastNear Transactions API (#5)", "POST", f"{ep['fastnear_tx']}/v0/blocks", {"desc": True, "limit": 1}),
    ("Aurora Blockscout (#19)", "GET", f"{ep['aurora_api']}/stats", None),
]

client = PoliteClient(verbose=False)
print("| Source | Endpoint | Status | Seconds |")
print("|---|---|---|---|")
for name, method, url, body in PROBES:
    t0 = time.time()
    try:
        if method == "GET":
            client.get_json(url)
        else:
            client.post_json(url, body)
        status = "OK"
    except Exception as exc:  # report, never raise
        status = f"FAIL {type(exc).__name__}: {str(exc)[:80]}"
    print(f"| {name} | `{url}` | {status} | {time.time() - t0:.1f} |")
client.close()
