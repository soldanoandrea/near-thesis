"""data/raw/MANIFEST.json: provenance (URL, params, fetch time UTC, rows, sha256) for every committed raw file."""

from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import json
from pathlib import Path
from typing import Any

import polars as pl

from . import io, paths


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load(path: Path = paths.MANIFEST) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text())
    return {"schema_version": 1, "description": "Provenance of every committed file under data/raw/. "
            "sha256 is of the committed CSV. Regenerate with `make refresh`.", "files": {}}


def save(m: dict[str, Any], path: Path = paths.MANIFEST) -> None:
    m["files"] = dict(sorted(m["files"].items()))
    path.write_text(json.dumps(m, indent=2, sort_keys=False) + "\n")


@contextlib.contextmanager
def _locked():
    """Serialize manifest updates across processes (long fetchers may run concurrently)."""
    paths.RAW.mkdir(parents=True, exist_ok=True)
    with open(paths.RAW / ".manifest.lock", "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def save_table(source: str, name: str, df: pl.DataFrame, *, urls: list[str], params: Any = None,
               sort_by: list[str] | None = None, notes: str = "", http_stats: dict | None = None,
               fetched_at: str | None = None) -> Path:
    """Write data/raw/<source>/<name>.csv and record it in the manifest."""
    rel = f"{source}/{name}.csv"
    path = paths.RAW / rel
    rows, sha = io.write_csv(df, path, sort_by=sort_by)
    with _locked():
        _record(rel, source, df, urls, params, fetched_at, rows, sha, path, http_stats, notes)
    print(f"  wrote {rel}: {rows} rows", flush=True)
    return path


def _record(rel, source, df, urls, params, fetched_at, rows, sha, path, http_stats, notes) -> None:
    m = load()
    m["files"][rel] = {
        "source": source,
        "urls": urls,
        "params": params,
        "fetched_at_utc": fetched_at or utc_now(),
        "rows": rows,
        "columns": df.columns,
        "sha256": sha,
        "bytes": path.stat().st_size,
        "http": http_stats or {},
        "notes": notes,
    }
    save(m)
