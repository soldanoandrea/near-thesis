"""`make reproduce` is deterministic: two offline builds are byte-identical and match the committed outputs."""

import pytest

from nearthesis import io, paths
from nearthesis.pipeline import build


@pytest.mark.slow
def test_build_twice_identical_and_matches_committed(tmp_path):
    a = build(out_root=tmp_path / "a", quiet=True)
    b = build(out_root=tmp_path / "b", quiet=True)
    assert a.keys() == b.keys()
    for name in a:
        assert io.sha256_file(a[name]) == io.sha256_file(b[name]), f"{name} differs between two builds"
    for name, p in a.items():
        committed = (paths.REPORTS if name.endswith(".md") else paths.PROCESSED) / name
        assert committed.exists(), f"{name} not committed; run `make reproduce`"
        assert io.sha256_file(p) == io.sha256_file(committed), f"{name}: committed output is stale"
