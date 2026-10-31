"""`make site` is deterministic and offline: the committed thesis/THESIS.md, thesis/NUMBERS.md and site/ are exactly
what the code produces from data/processed; the pages load nothing but the pinned Plotly.js; every chart states what
it shows and what it does not, and names the processed tables it is drawn from."""

import re

from nearthesis import io, manifest, paths
from nearthesis.web import build, charts, numbers


def test_site_build_is_deterministic_and_committed(tmp_path):
    a = build.build_site(out_root=tmp_path / "a", quiet=True)
    b = build.build_site(out_root=tmp_path / "b", quiet=True)
    assert a.keys() == b.keys()
    for rel in a:
        assert io.sha256_file(a[rel]) == io.sha256_file(b[rel]), f"{rel} differs between two builds"
        committed = paths.ROOT / rel
        assert committed.exists(), f"{rel} is not committed; run `make site`"
        assert io.sha256_file(a[rel]) == io.sha256_file(committed), f"{rel} is stale; run `make site`"


def test_pages_load_only_the_pinned_plotly():
    for page in (paths.ROOT / "site").glob("*.html"):
        text = page.read_text()
        ext = re.findall(r'<(?:script|link|img|iframe)[^>]+(?:src|href)="((?:https?:)?//[^"]+)"', text)
        assert set(ext) <= {build.PLOTLY_URL}, f"{page.name} loads {ext}"
        for tag in re.findall(r"<script[^>]+cdnjs[^>]*>", text):
            assert f'integrity="{build.PLOTLY_SRI}"' in tag and 'crossorigin="anonymous"' in tag


def test_every_chart_says_what_it_shows_and_names_its_tables():
    R = numbers.build(paths.PROCESSED, paths.ROOT / "thesis", manifest.load())
    specs = charts.all_charts(paths.PROCESSED, R)
    assert {c["id"] for c in specs} >= {"classes", "signers", "intents", "revenue", "treasury", "supply", "multiples",
                                        "developers"}
    for c in specs:
        cap = c["caption"]
        assert cap.startswith("Shows ") and "it does not" in cap, c["id"]
        assert cap.count(". ") == 0, f"{c['id']}: the caption should be one sentence"
        assert "{{" not in cap and "n/a" not in cap
        assert c["sources"] and all((paths.ROOT / s).exists() for s in c["sources"]), c["id"]
        assert c["table"]["rows"], c["id"]


def test_dashboard_lists_every_raw_file_with_its_sha256():
    page = (paths.ROOT / "site" / "dashboard.html").read_text()
    for rel, e in manifest.load()["files"].items():
        assert e["sha256"] in page and f"data/raw/{rel}" in page, rel


def test_registry_sources_point_at_committed_files():
    R = numbers.build(paths.PROCESSED, paths.ROOT / "thesis", manifest.load())
    for key, n in R.items.items():
        f = n.source.split(":")[0].split(" ")[0]
        if f.startswith(("data/", "thesis/")):
            assert (paths.ROOT / f).exists(), f"{key}: {f}"


def _code_blocks(text: str) -> list[str]:
    return re.findall(r"```(?:json)?\n(.*?)\n```", text, flags=re.S)


def test_x_post_draft_fits_and_says_what_the_rules_ask():
    post = (paths.ROOT / "docs" / "DEMO_POST.md").read_text()
    blocks = _code_blocks(post)
    main = blocks[0]
    for b in blocks:  # X counts every URL as 23 characters
        assert len(re.sub(r"https?://\S+", "x" * 23, b)) <= 280, b[:60]
    assert "@NEARProtocol" in main and "#NEARHackathon" in main and "NEAR HACKATHON" in main
    assert "https://github.com/soldanoandrea/near-thesis" in main
    assert "archival RPC" in main or "intents.near" in main  # NEAR's concrete role


def test_submission_json_is_valid_and_within_limits():
    import json
    doc = (paths.ROOT / "docs" / "SUBMISSION.md").read_text()
    payload = json.loads(_code_blocks(doc)[0])
    assert payload["tracks"] == ["thesis"]
    assert "website" not in payload
    assert 20 <= len(payload["idea"]) <= 2000
    assert len(json.dumps(payload).encode()) <= 12_000
    assert payload["projectUrl"] == "https://github.com/soldanoandrea/near-thesis"
    for k in ("requestId", "leadName", "email", "size", "nearAddress", "demoUrl", "consent"):
        assert payload[k].startswith("<HUMAN"), k
