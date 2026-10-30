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
