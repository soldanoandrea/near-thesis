import polars as pl
import pytest

from nearthesis import io, paths


@pytest.fixture(scope="session")
def processed():
    def load(name: str) -> pl.DataFrame:
        return pl.read_csv(paths.PROCESSED / name, infer_schema_length=None)
    return load


@pytest.fixture(scope="session")
def raw():
    def load(rel: str) -> pl.DataFrame:
        return io.read_csv(paths.RAW / rel)
    return load
