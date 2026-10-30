"""Integrity checks of data/raw against MANIFEST.json (used by `nearthesis verify` and the tests)."""

from __future__ import annotations

from . import io, manifest, paths


def verify_raw() -> list[str]:
    problems = []
    m = manifest.load()
    files = m.get("files", {})
    for rel, meta in files.items():
        p = paths.RAW / rel
        if not p.exists():
            problems.append(f"missing file {rel}")
            continue
        sha = io.sha256_file(p)
        if sha != meta["sha256"]:
            problems.append(f"sha256 mismatch {rel}: manifest {meta['sha256'][:12]} vs file {sha[:12]}")
        rows = io.read_csv(p).height
        if rows != meta["rows"]:
            problems.append(f"row count mismatch {rel}: manifest {meta['rows']} vs file {rows}")
    on_disk = {str(p.relative_to(paths.RAW)) for p in paths.RAW.rglob("*.csv")}
    for rel in sorted(on_disk - set(files)):
        problems.append(f"file not in manifest {rel}")
    return problems
