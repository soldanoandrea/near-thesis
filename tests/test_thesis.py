"""thesis/THESIS.md is rendered from thesis/THESIS.in.md with every number taken from data/processed, has the parts the
track asks for, and quotes the sha256 of the frozen predictions; the frozen file matches the pipeline's predictions
for the committed snapshot and, where the tag exists locally, the tag message."""

import re
import subprocess

import polars as pl
import pytest

from nearthesis import io, manifest, paths
from nearthesis.pipeline import compute_as_of
from nearthesis.web import numbers

THESIS = paths.ROOT / "thesis"
REGISTERED_AS_OF = "2026-10-29"   # snapshot the predictions were frozen from
TAG = "predictions-2026-10-31"


def _body(text: str) -> str:
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    return "\n".join(line for line in text.split("\n") if not line.startswith("|"))


def test_thesis_is_fully_rendered_from_the_registry():
    tpl = (THESIS / "THESIS.in.md").read_text()
    out = (THESIS / "THESIS.md").read_text()
    assert numbers.TOKEN.findall(tpl), "the template should take its numbers from the registry"
    assert "{{" not in out and "}}" not in out
    assert " n/a" not in out
    R = numbers.build(paths.PROCESSED, THESIS, manifest.load())
    rendered, _ = R.render(tpl)
    assert rendered in out


def test_thesis_has_the_required_parts_and_length():
    out = (THESIS / "THESIS.md").read_text()
    heads = [h.lower() for h in re.findall(r"^##+ (.+)$", out, flags=re.M)]
    for part in ("verdict", "method", "the evidence", "the bull case", "the bear case", "valuation",
                 "what would change our mind", "limitations", "reproduce"):
        assert any(part in h for h in heads), part
    words = len(re.findall(r"\S+", _body(out)))
    assert 2500 <= words <= 4500, words
    assert "make reproduce" in out and "git clone" in out


def test_predictions_are_frozen_and_quoted():
    p = THESIS / "predictions.csv"
    pred = pl.read_csv(p, infer_schema_length=None)
    assert {"id", "metric", "comparator", "threshold", "check_date", "source"} <= set(pred.columns)
    assert pred.height >= 7 and pred["threshold"].null_count() == 0
    sha = io.sha256_file(p)
    assert sha in (THESIS / "THESIS.md").read_text()
    assert TAG in (THESIS / "THESIS.md").read_text()
    if compute_as_of(manifest.load()) == REGISTERED_AS_OF:
        assert io.sha256_file(paths.PROCESSED / "predictions.csv") == sha, \
            "the frozen predictions differ from the pipeline's for the snapshot they were registered from"


def test_tag_message_carries_the_hash_if_the_tag_exists():
    try:
        msg = subprocess.run(["git", "-C", str(paths.ROOT), "tag", "-l", "--format=%(contents)", TAG],
                             capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git not available")
    if not msg.strip():
        pytest.skip(f"tag {TAG} not present in this clone (tags are not pushed by default)")
    assert io.sha256_file(THESIS / "predictions.csv") in msg
