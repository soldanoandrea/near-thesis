"""Manifest integrity: every committed raw file is recorded, unchanged (sha256), with provenance."""

import json
import re

from nearthesis import config, manifest, paths
from nearthesis.verify import verify_raw


def test_raw_files_match_manifest():
    assert verify_raw() == []


def test_manifest_entries_have_provenance():
    m = manifest.load()
    assert m["files"], "manifest is empty"
    for rel, e in m["files"].items():
        assert e["urls"] and all(u.startswith("https://") for u in e["urls"]), rel
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", e["fetched_at_utc"]), rel
        assert re.fullmatch(r"[0-9a-f]{64}", e["sha256"]), rel
        assert e["rows"] >= 1, rel
        assert e["source"] == rel.split("/")[0], rel


def test_committed_snapshot_size_under_50mb():
    total = sum(p.stat().st_size for p in paths.RAW.rglob("*") if p.is_file())
    assert total < 50 * 1024 * 1024, f"data/raw is {total / 1e6:.1f} MB"


def test_no_keys_or_secrets_anywhere():
    """Keyless by design: no auth headers, no key/token query params, no .env files."""
    from nearthesis.http import PoliteClient

    c = PoliteClient(verbose=False)
    sent = {k.lower() for k in c._client.headers}
    assert not sent & {"authorization", "x-api-key", "x-cg-pro-api-key", "x-cg-demo-api-key", "cookie"}
    c.close()
    blob = json.dumps(manifest.load()).lower() + json.dumps(config.load()).lower()
    for needle in ("api_key=", "apikey=", "token=", "bearer ", "x-api-key"):
        assert needle not in blob
    assert not list(paths.ROOT.glob(".env")) and not list(paths.ROOT.glob(".env.*[!l]"))


PHASE2_SNAPSHOTS = [
    "fastnear_tx/block_sample_extra_blocks.csv", "fastnear_tx/block_sample_extra_txs.csv",
    "fastnear_tx/signer_month_activity.csv", "fastnear_tx/signer_lifetime.csv", "fastnear_tx/signer_tx_details.csv",
    "fastnear_tx/intents_days.csv", "fastnear_tx/intents_swap_legs.csv", "fastnear_tx/intents_swap_txs.csv",
    "fastnear_tx/intents_windows.csv",
    "rpc_archival/intents_fee_collector_balances.csv", "oneclick/tokens.csv", "defillama/coin_prices_intents_days.csv",
    "fastnear_tx/wallet_flows.csv", "fastnear_tx/trail_hops.csv", "github/repos.csv", "github/contributor_weeks.csv",
    "github/participation.csv", "github/releases.csv", "github/fetch_log.csv", "opendevdata/eco_mads_monthly.csv",
    "governance/hsp029_status.csv",
]


def test_phase2_snapshots_documented():
    """Every phase 2a snapshot is in the manifest with notes (what it is) and stays small."""
    files = manifest.load()["files"]
    for rel in PHASE2_SNAPSHOTS:
        assert rel in files, f"{rel} missing from MANIFEST.json"
        e = files[rel]
        assert len(e["notes"]) > 20, rel
        assert e["bytes"] < 8 * 1024 * 1024, f"{rel} is {e['bytes'] / 1e6:.1f} MB"


def test_committed_raw_and_processed_under_50mb():
    total = sum(p.stat().st_size for d in (paths.RAW, paths.PROCESSED) for p in d.rglob("*") if p.is_file())
    assert total < 50 * 1024 * 1024, f"data/raw + data/processed is {total / 1e6:.1f} MB"
