"""Deterministic table I/O. Same input -> byte-identical CSV, so sha256 comparisons are meaningful."""

from __future__ import annotations

import hashlib
from pathlib import Path

import polars as pl

FLOAT_DECIMALS = 8


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_csv(df: pl.DataFrame, path: Path, sort_by: list[str] | None = None) -> tuple[int, str]:
    """Write `df` as CSV with stable row order and fixed float formatting. Returns (rows, sha256)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if sort_by:
        df = df.sort(sort_by, maintain_order=True)
    float_cols = [c for c, t in df.schema.items() if t in (pl.Float32, pl.Float64)]
    if float_cols:
        df = df.with_columns([pl.col(c).round(FLOAT_DECIMALS) for c in float_cols])
    df.write_csv(path, float_precision=FLOAT_DECIMALS, line_terminator="\n", null_value="")
    return df.height, sha256_file(path)


def read_csv(path: Path, **kwargs) -> pl.DataFrame:
    return pl.read_csv(path, infer_schema_length=0, **kwargs)  # all Utf8; callers cast explicitly
