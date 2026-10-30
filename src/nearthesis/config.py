"""Load config/sources.toml (stdlib tomllib, no extra dependency)."""

from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import paths


@lru_cache(maxsize=1)
def load(path: Path | None = None) -> dict[str, Any]:
    with open(path or paths.CONFIG, "rb") as fh:
        return tomllib.load(fh)


def chains() -> list[dict[str, str]]:
    return list(load()["chains"])
