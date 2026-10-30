"""Filesystem layout. Everything is relative to the repository root."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(os.environ.get("NEARTHESIS_ROOT", Path(__file__).resolve().parents[2]))
CONFIG = ROOT / "config" / "sources.toml"
RAW = ROOT / "data" / "raw"
MANIFEST = RAW / "MANIFEST.json"
CACHE = ROOT / "data" / "cache"
PROCESSED = ROOT / "data" / "processed"
REPORTS = ROOT / "reports"
