"""`make reproduce` is deterministic: two offline builds are byte-identical and match the committed outputs
(data/processed, reports/ and the generated thesis/falsifiers.md), bootstrap and model seeds included."""

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
        committed = paths.ROOT / p.relative_to(tmp_path / "a")
        assert committed.exists(), f"{name} not committed; run `make reproduce`"
        assert io.sha256_file(p) == io.sha256_file(committed), f"{name}: committed output is stale"


def test_phase2_outputs_are_part_of_the_build(tmp_path):
    out = build(out_root=tmp_path / "c", quiet=True)
    for name in ("analysis_summary.md", "models_summary.md", "falsifiers.md", "metrics_phase2.csv",
                 "organic_monthly.csv", "intents_check_days.csv", "model_supply_scenarios.csv", "predictions.csv"):
        assert name in out, name
