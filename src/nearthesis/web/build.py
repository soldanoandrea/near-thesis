"""`make site`: render thesis/THESIS.md from its template and build the static site in site/. Offline, deterministic.

Inputs: data/processed/*.csv, data/raw/MANIFEST.json, thesis/THESIS.in.md, thesis/findings.in.md,
thesis/predictions.csv, thesis/valuation_priors.toml, docs/*.in.md. Outputs: thesis/THESIS.md, thesis/NUMBERS.md,
docs/*.md rendered from their templates (demo script, post draft, submission draft), site/index.html
(the thesis), site/dashboard.html (charts, scorecard, provenance), site/assets/{style.css, app.js, data.js}, and the
findings block of README.md (between its two markers; the rest of the README is hand-written).
Plotly.js is loaded from a pinned cdnjs URL with a subresource-integrity hash; nothing else is fetched.
"""

from __future__ import annotations

import html
import shutil
from pathlib import Path

import polars as pl

from .. import io, manifest as manifest_mod, paths
from ..report import fmt
from . import charts as charts_mod, md, numbers

REPO_URL = "https://github.com/soldanoandrea/near-thesis"
PAGES_URL = "https://soldanoandrea.github.io/near-thesis/"
PLOTLY_VERSION = "2.35.3"
PLOTLY_URL = f"https://cdnjs.cloudflare.com/ajax/libs/plotly.js/{PLOTLY_VERSION}/plotly.min.js"
PLOTLY_SRI = "sha512-7H/XbvOmUsf6mawBvmmx9BsPt9ew2NTwQ3QDSzNe6iyacDbCJU+7pBbZY1NdmTpuj7snxSsXasMYMiR2tv906g=="
PREDICTIONS_TAG = "predictions-2026-10-31"
STATIC = Path(__file__).parent / "static"
E = lambda s: html.escape(str(s), quote=True)  # noqa: E731


def blob(path: str) -> str:
    return f"{REPO_URL}/blob/main/{path}"


def head(title: str, description: str, plotly: bool) -> str:
    scripts = ""
    if plotly:
        scripts = (f'<script src="{PLOTLY_URL}" integrity="{PLOTLY_SRI}" crossorigin="anonymous" '
                   'referrerpolicy="no-referrer"></script>\n<script src="assets/data.js"></script>\n')
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{E(title)}</title>
<meta name="description" content="{E(description)}">
<link rel="stylesheet" href="assets/style.css">
<script>try{{var t=localStorage.getItem("nt-theme");if(t)document.documentElement.setAttribute("data-theme",t)}}catch(e){{}}</script>
{scripts}<script src="assets/app.js"></script>
</head>
"""


def header(active: str) -> str:
    def a(href, text, key):
        cur = ' aria-current="page"' if key == active else ""
        return f'<a href="{href}"{cur}>{text}</a>'
    return (f'<header class="site-header"><div class="inner"><a class="brand" href="index.html">near-thesis</a><nav>'
            f'{a("index.html", "Thesis", "thesis")}{a("dashboard.html", "Dashboard", "dashboard")}'
            f'{a("dashboard.html#scorecard", "Scorecard", "")}{a("dashboard.html#provenance", "Data", "")}'
            f'<a href="{REPO_URL}">Repository</a></nav>'
            '<button class="theme-toggle" id="theme-toggle" type="button">Theme: auto</button></div></header>\n')


def footer(R: numbers.Registry) -> str:
    return (f'<footer>Snapshot as-of {E(R.fmt("in.as_of"))} (UTC); raw data fetched {E(R.fmt("snap.first_fetch"))} to '
            f'{E(R.fmt("snap.last_fetch"))}. Every number on this site is computed by <code>make reproduce</code> from the '
            f'committed snapshots; nothing is typed by hand. Built for NEAR HACKATHON 2026, track <code>thesis</code>. '
            f'Written by an AI agent team; no NEAR position. Not financial advice. MIT license. '
            f'<a href="{REPO_URL}">Source</a>.</footer>\n')


def table_html(headers: list[str], rows: list[list[str]], num_cols: set[int] | None = None,
               raw_cols: set[int] | None = None, cls: dict[int, str] | None = None) -> str:
    num_cols, raw_cols, cls = num_cols or set(), raw_cols or set(), cls or {}
    out = ['<div class="table-wrap"><table><thead><tr>']
    for i, h in enumerate(headers):
        klass = " ".join(x for x in ("num" if i in num_cols else "", cls.get(i, "")) if x)
        out.append(f'<th{f" class=\"{klass}\"" if klass else ""}>{E(h)}</th>')
    out.append("</tr></thead><tbody>")
    for r in rows:
        tds = []
        for i, c in enumerate(r):
            klass = " ".join(x for x in ("num" if i in num_cols else "", cls.get(i, "")) if x)
            tds.append(f'<td{f" class=\"{klass}\"" if klass else ""}>{c if i in raw_cols else E(c)}</td>')
        out.append("<tr>" + "".join(tds) + "</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


def card(c: dict) -> str:
    legend = ""
    if c.get("legend_html"):
        legend = '<div class="legend-row">' + "".join(
            f'<span style="--sw: var({charts_mod_var(tok)})">{E(lab)}</span>' for lab, tok in c["legend_html"]) + "</div>"
    src = " · ".join(f'<a href="{blob(s)}">{E(s)}</a>' for s in c["sources"])
    tbl = table_html(c["table"]["headers"], c["table"]["rows"])
    plot = f'<div class="plot" id="plot-{c["id"]}" role="img" aria-label="{E(c["title"])}"></div>'
    if c.get("min_width"):  # wide diagrams scroll sideways on phones instead of shrinking into illegibility
        plot = (f'<div class="plot-scroll"><div class="plot" id="plot-{c["id"]}" role="img" aria-label="{E(c["title"])}" '
                f'style="min-width:{c["min_width"]}px"></div></div>')
    return (f'<section class="card" id="card-{c["id"]}">\n<h3><span class="qtag">{E(c["q"])}</span>{E(c["title"])}</h3>\n'
            f'{legend}{plot}\n'
            f'<div class="noplot">The interactive chart needs Plotly.js {PLOTLY_VERSION} from cdnjs (pinned, with an integrity '
            f'hash). The data table below holds the same numbers.</div>\n'
            f'<p class="caption"><b>What this shows, and what it does not:</b> {E(c["caption"])}</p>\n'
            f'<p class="sources">Data: {src} · chart code: <a href="{blob("src/nearthesis/web/charts.py")}">'
            f'src/nearthesis/web/charts.py</a></p>\n'
            f'<details><summary>Data table</summary>{tbl}</details>\n</section>\n')


def charts_mod_var(tok: str) -> str:
    return {"@s1": "--series-1", "@s2": "--series-2", "@s3": "--series-3", "@s4": "--series-4", "@s5": "--series-5",
            "@s7": "--series-7", "@muted": "--text-muted", "@axis": "--axis"}[tok]


def tiles(R: numbers.Registry) -> str:
    T = [
        ("Q1", "Organic share of transactions, 2026-Q3", R.fmt("q1b.organic_tx_share"), f"90% CI {R.fmt('q1b.organic_tx_share', 'ci')}"),
        ("Q1", "Organic daily active signers, 2026-Q3", R.fmt("q1b.organic_das"),
         f"CI {R.fmt('q1b.organic_das', 'ci')}; {R.fmt('oq.from2025q3.das_organic_min')} to "
         f"{R.fmt('oq.from2025q3.das_organic_max')} per quarter since 2025-Q3"),
        ("Q1", "Real signers / NearBlocks active accounts", R.fmt("om.das_to_nearblocks.last6", "x"),
         f"last six months ({R.fmt('q1b.das_to_nearblocks', 'x')} 12-month median); relayers hide the real signer"),
        ("Q2", "Intents on-chain volume / DefiLlama", R.fmt("q2b.ratio_sample_median", "p0"),
         f"each swap once; both legs: {R.fmt('q2b.ratio_two_sided_median', 'p0')}"),
        ("Q4", "Intents revenue rebuilt on-chain / DefiLlama", R.fmt("q4b.revenue_onchain_to_defillama", "p1"), "last six months"),
        ("Q4", "Float dilution after buybacks", R.fmt("sc.status_quo/base.1y.float_cagr") + " / yr",
         f"offset needs {R.fmt('ma.net_zero_multiple.0.0249', 'x')} today's Intents revenue"),
        ("Q7", "Market cap / chain fees", R.fmt("mb.chain_fees", "x"),
         f"{R.fmt('mb.fees_plus_intents_fees', 'x')} incl. Intents fees; peer median {R.fmt('mv.chain_fees.30d_annualized.peer_median')}"),
        ("Q6", "Monthly active developers", R.fmt("q6.near_mad"), f"{R.fmt('q6.near_mad_yoy')} y/y; share vs peers rising"),
    ]
    return '<div class="tiles">' + "".join(
        f'<div class="tile"><span class="q">{E(q)}</span><div class="label">{E(lab)}</div><div class="value">{E(v)}</div>'
        f'<div class="sub">{E(sub)}</div></div>' for q, lab, v, sub in T) + "</div>"


def _status(s: str) -> tuple[str, str]:
    if s.startswith("met"):
        return "met", f"{s}: counts against the bull case"
    if s.startswith("half"):
        return "half", s
    if s.startswith("not met"):
        return "notmet", s
    return "na", s


def scorecard(processed: Path, thesis_dir: Path, R: numbers.Registry) -> str:
    fs = pl.read_csv(processed / "falsifier_status.csv", infer_schema_length=None)
    rows = []
    for r in fs.iter_rows(named=True):
        k, label = _status(r["status"])
        rows.append([r["question"], E(r["falsifier"]), E(r["reading"]), f'<span class="status {k}">{E(label)}</span>'])
    out = ['<section id="scorecard" class="card">',
           '<h3><span class="qtag">Q1-Q7</span>What would change our mind: pre-registered falsifiers, status at the snapshot</h3>',
           f'<p class="caption"><b>What this shows, and what it does not:</b> each falsifier was written in PIANO.md before the '
           f'phase-2 data were fetched; "met" means the evidence now counts against the bullish case on that question '
           f'({R.fmt("fs.met", "int")} met, {R.fmt("fs.half", "int")} half met, {R.fmt("fs.not_met", "int")} not met, '
           f'{R.fmt("fs.not_assessed", "int")} not assessed, of {R.fmt("fs.rows", "int")}); it does not weigh the questions against '
           'each other.</p>',
           table_html(["Q", "Falsifier (PIANO.md)", "Current reading", "Status"], rows, raw_cols={1, 2, 3}),
           f'<p class="sources">Data: <a href="{blob("data/processed/falsifier_status.csv")}">data/processed/falsifier_status.csv</a> '
           f'(generated by <a href="{blob("src/nearthesis/report2.py")}">src/nearthesis/report2.py</a>)</p>']
    pp = thesis_dir / "predictions.csv"
    if pp.exists():
        pr = pl.read_csv(pp, infer_schema_length=None)
        prow = []
        for r in pr.iter_rows(named=True):
            def val(v, unit=r["unit"]):
                return numbers.show(numbers.Num("", float(v), unit, ""))
            prow.append([r["id"], r["bullish_claim"], r["metric"], f'{r["comparator"]} {val(r["threshold"])}',
                         r["check_date"], f'{val(r["current_value"])} ({r["current_window"]})', r["source"],
                         f'<span class="status pending">open until {E(r["check_date"])}</span>'])
        out += ["</section>\n", '<section id="predictions" class="card">',
                '<h3><span class="qtag">P1-P7</span>Dated predictions, frozen before their outcomes exist</h3>',
                f'<p class="caption"><b>What this shows, and what it does not:</b> the claims the bullish case needs, each with '
                'a threshold the pipeline computed from the snapshot and a date, frozen in <code>thesis/predictions.csv</code> '
                f'(sha256 <code class="hash">{E(R.fmt("pred.sha256"))}</code>, annotated git tag <code>{PREDICTIONS_TAG}</code>); '
                'it does not say they will hold: a prediction that fails counts against the thesis and is reported, not '
                'removed.</p>',
                table_html(["ID", "Bullish claim", "Metric", "Test", "Check on", "At registration", "Source", "Status"],
                           [[E(c) if i != 7 else c for i, c in enumerate(r)] for r in prow], raw_cols=set(range(8)),
                           cls={2: "col-wide", 3: "nowrap", 4: "nowrap", 6: "col-wide"}),
                f'<p class="sources">Data: <a href="{blob("thesis/predictions.csv")}">thesis/predictions.csv</a> '
                f'(frozen copy of <a href="{blob("data/processed/predictions.csv")}">data/processed/predictions.csv</a>, '
                f'generated by <a href="{blob("src/nearthesis/predictions.py")}">src/nearthesis/predictions.py</a>)</p>']
    out.append("</section>\n")
    return "\n".join(out)


def provenance(m: dict) -> str:
    rows = []
    for rel, e in sorted(m["files"].items()):
        urls = e.get("urls") or []
        u = E(urls[0]) + (f' <span class="muted">(+{len(urls) - 1} more)</span>' if len(urls) > 1 else "") if urls else ""
        rows.append([f"<code>data/raw/{E(rel)}</code>", E(e["source"]), E(e["fetched_at_utc"]), f'{e["rows"]:,}',
                     E(e["sha256"]), u])
    return ('<section id="provenance" class="card"><h3><span class="qtag">Data</span>Data provenance: every committed raw '
            'file, where it came from, when, and its sha256</h3>'
            '<p class="caption"><b>What this shows, and what it does not:</b> the source, fetch time (UTC), row count and '
            'sha256 of each snapshot in <code>data/raw/MANIFEST.json</code> that every chart is rebuilt from '
            '(<code>make verify</code> re-checks the hashes); it does not show that the upstream APIs would return the '
            'same data today (<code>make refresh</code> re-downloads them).</p>'
            + table_html(["File", "Source", "Fetched (UTC)", "Rows", "sha256", "Endpoint"], rows, num_cols={3},
                         raw_cols={0, 1, 2, 4, 5}, cls={4: "hash"})
            + f'<p class="sources">Data: <a href="{blob("data/raw/MANIFEST.json")}">data/raw/MANIFEST.json</a> · source notes: '
              f'<a href="{blob("docs/DATA_NOTES.md")}">docs/DATA_NOTES.md</a></p></section>\n')


def outro(R: numbers.Registry) -> str:
    """Closing frame of the demo video (dashboard.html#capture=outro); hidden on the normal page."""
    return ('<section id="outro" class="card outro" aria-hidden="true"><h2>NEAR on the evidence</h2>'
            "<p><b>NEAR's role:</b> every number is rebuilt from NEAR itself: archival RPC block headers for supply, burn "
            "and staking; the FastNear indexer for per-signer histories, wallet flows and the treasury trail; DIP-4 "
            "settlement events on <code>intents.near</code> for NEAR Intents volume and fees.</p>"
            f'<p><b>Reproduce:</b> <code>git clone {REPO_URL} &amp;&amp; cd near-thesis &amp;&amp; make reproduce</code></p>'
            f'<p><b>Predictions frozen:</b> sha256 <code>{E(R.fmt("pred.sha256")[:16])}…</code>, git tag '
            f'<code>{PREDICTIONS_TAG}</code>; first checks on {E(R.fmt("pred.P2.date"))}.</p>'
            "<p>Built at NEAR HACKATHON 2026, track <code>thesis</code>. Keyless public data, no NEAR position. "
            "Not financial advice.</p></section>\n")


def dashboard_html(R: numbers.Registry, charts: list[dict], processed: Path, thesis_dir: Path, m: dict) -> str:
    by = {c["id"]: c for c in charts}
    sections = [
        ("Q1. Is the activity real?", "q1", ["classes", "signers"]),
        ("Q2. Is NEAR Intents volume what it is reported to be?", "q2", ["intents"]),
        ("Q4. Does value reach holders, and where did the treasury go?", "q4", ["revenue", "treasury", "supply"]),
        ("Q7. What is NEAR worth relative to peers?", "q7", ["multiples"]),
        ("Q6. Are developers staying?", "q6", ["developers"]),
    ]
    body = [head("NEAR thesis dashboard", "Charts, falsifier scorecard and data provenance for a re-runnable, data-backed "
                 "long-term case on NEAR.", plotly=True), "<body>\n", header("dashboard"), "<main>\n"]
    body.append(
        '<section id="hero">'
        "<h1>NEAR on the evidence: the dashboard</h1>"
        f'<p class="lede">Snapshot as-of {E(R.fmt("in.as_of"))}. Organic use is a small share of NEAR\'s transactions and has '
        "not grown since mid-2025; NEAR Intents is real and its captured revenue reconciles with on-chain flows within a few "
        "percent, but only about half of its reported volume is visible as public swaps; issuance still outruns burn plus "
        "buybacks. Every chart says what it "
        "shows and what it does not, "
        f'with the table behind it. The argument is in the <a href="index.html">thesis</a>.</p>'
        f"{tiles(R)}</section>\n")
    for title, sid, ids in sections:
        body.append(f'<h2 id="{sid}">{E(title)}</h2>\n')
        body += [card(by[i]) for i in ids]
    body.append('<h2 id="change-our-mind">What would change our mind</h2>\n')
    body.append(scorecard(processed, thesis_dir, R))
    body.append('<h2 id="data">Data</h2>\n')
    body.append(provenance(m))
    body.append(outro(R))
    body.append("</main>\n")
    body.append(footer(R))
    body.append("</body>\n</html>\n")
    return "".join(body)


def link_map(href: str) -> str:
    if href.startswith("../site/"):
        return href[len("../site/"):]
    if href.startswith("../"):
        return blob(href[3:])
    if href.startswith(("http://", "https://", "#", "mailto:")):
        return href
    return blob("thesis/" + href)


def thesis_html(R: numbers.Registry, thesis_md: str, used) -> str:
    article, heads = md.render(thesis_md, link_map)
    toc = "".join(f'<a class="l{lv}" href="#{hid}">{md.inline(t)}</a>' for lv, hid, t in heads if lv in (2, 3))
    prov = numbers.provenance_rows(R, used)
    appendix = ('<details id="numbers"><summary>Where every number in this essay comes from '
                f'({len(prov)} values, filled in by <code>make site</code>)</summary>'
                + table_html(["Key", "Value", "Source"], [[f"<code>{E(k)}</code>", E(v), E(s)] for k, v, s in prov],
                             raw_cols={0, 1, 2}) + "</details>")
    return "".join([
        head("NEAR on the evidence", "A data-backed, re-runnable long-term thesis on NEAR: what on-chain data says, "
             "with intervals, priors and dated falsifiers.", plotly=False),
        "<body>\n", header("thesis"), "<main>\n",
        f'<div class="doc"><article>{article}\n{appendix}</article><nav class="toc" aria-label="Contents">'
        f'<a href="dashboard.html"><b>Open the dashboard</b></a>{toc}</nav></div>\n',
        "</main>\n", footer(R), "</body>\n</html>\n"])


def placeholder_html(R: numbers.Registry) -> str:
    return "".join([head("NEAR on the evidence", "Data-backed NEAR thesis.", plotly=False), "<body>\n", header("thesis"),
                    '<main><h1>NEAR on the evidence</h1><p>The essay is not rendered yet. '
                    '<a href="dashboard.html">Open the dashboard</a>.</p></main>\n', footer(R), "</body>\n</html>\n"])


def render_thesis(R: numbers.Registry, template: str) -> tuple[str, str, list]:
    text, used = R.render(template)
    header_note = ("<!-- Generated by `make site` from thesis/THESIS.in.md: every number is filled in from data/processed "
                   "(sources in thesis/NUMBERS.md). Edit the template, not this file. -->\n")
    rows = numbers.provenance_rows(R, used)
    nmd = ["# Where every number in THESIS.md comes from", "",
           "Generated by `make site` from the number registry (`src/nearthesis/web/numbers.py`). Each key below appears in "
           "`thesis/THESIS.in.md` as `{{key}}`; its value is read from the processed table named in the last column.", "",
           "| Key | Value | Source |", "|---|---|---|"]
    nmd += [f"| `{k}` | {v} | {s.replace('|', '/')} |" for k, v, s in rows]
    return header_note + text, "\n".join(nmd) + "\n", used


FINDINGS_START = "<!-- findings:start (generated by `make site` from thesis/findings.in.md; do not edit) -->"
FINDINGS_END = "<!-- findings:end -->"


def splice_findings(readme: str, block: str) -> str:
    """Replace the README's findings block (between the two markers) with the rendered template."""
    if FINDINGS_START not in readme or FINDINGS_END not in readme:
        return readme
    head, rest = readme.split(FINDINGS_START, 1)
    _, tail = rest.split(FINDINGS_END, 1)
    return f"{head}{FINDINGS_START}\n{block.rstrip()}\n{FINDINGS_END}{tail}"


def build_site(out_root: str | Path | None = None, quiet: bool = False) -> dict[str, Path]:
    out = Path(out_root) if out_root else paths.ROOT
    processed = paths.PROCESSED
    thesis_dir = paths.ROOT / "thesis"
    m = manifest_mod.load()
    R = numbers.build(processed, thesis_dir, m)
    charts = charts_mod.all_charts(processed, R)
    site, assets, tout = out / "site", out / "site" / "assets", out / "thesis"
    assets.mkdir(parents=True, exist_ok=True)
    tout.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}

    def w(rel: str, text: str) -> None:
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        written[rel] = p

    tpl = thesis_dir / "THESIS.in.md"
    if tpl.exists():
        thesis_md, numbers_md, used = render_thesis(R, tpl.read_text())
        w("thesis/THESIS.md", thesis_md)
        w("thesis/NUMBERS.md", numbers_md)
        w("site/index.html", thesis_html(R, thesis_md, used))
    else:
        w("site/index.html", placeholder_html(R))
    w("site/dashboard.html", dashboard_html(R, charts, processed, thesis_dir, m))
    for tpl_doc in sorted((paths.ROOT / "docs").glob("*.in.md")):  # docs whose numbers come from the registry
        name = tpl_doc.name.replace(".in.md", ".md")
        w(f"docs/{name}", f"<!-- Generated by `make site` from docs/{tpl_doc.name}; edit the template, not this file. -->\n"
          + R.render(tpl_doc.read_text())[0])
    readme, ftpl = paths.ROOT / "README.md", thesis_dir / "findings.in.md"
    if readme.exists() and ftpl.exists():
        w("README.md", splice_findings(readme.read_text(), R.render(ftpl.read_text())[0]))
    keep = ("id", "traces", "layout", "layout_narrow", "height", "height_narrow")
    data = {"as_of": R.fmt("in.as_of"), "charts": [{k: c[k] for k in keep if k in c} for c in charts]}
    w("site/assets/data.js", "/* Generated by `make site` from data/processed; do not edit. */\nwindow.NT_DATA = "
      + numbers.dumps(data) + ";\n")
    for name in ("style.css", "app.js"):
        p = assets / name
        shutil.copyfile(STATIC / name, p)
        written[f"site/assets/{name}"] = p
    w("site/.nojekyll", "")
    if not quiet:
        size = sum(p.stat().st_size for k, p in written.items() if k.startswith("site/"))
        print(f"[site] wrote {len(written)} files ({size / 1e3:,.0f} kB in site/); open site/index.html")
    return written
