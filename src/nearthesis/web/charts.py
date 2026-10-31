"""Chart specifications for site/dashboard.html, built from data/processed only.

Each chart is a plain dict (Plotly traces + layout + a data table + a one-sentence caption); colors are role tokens
("@s1".."@s8" categorical slots, "@ink", "@muted", "@grid", "@axis", "@surface", with an optional "/alpha") that
site/assets/app.js resolves from CSS variables, so one spec renders in light and dark themes. Numbers in captions
come from the number registry (numbers.py), never typed.
"""

from __future__ import annotations

import math
from pathlib import Path

import polars as pl

from ..report import fmt
from .numbers import Registry

QUARTERS_FROM = "2025-Q1"  # first quarter with the full 200-draw design in every month (analysis_summary.md, Q1)
CLASSES = [("organic", "Organic (human-like)", "@s1"), ("automated", "Automated (bots)", "@s2"),
           ("incentivized", "Incentivized programs", "@s3"), ("infrastructure", "Infrastructure relays", "@s4"),
           ("account_setup", "Account setup", "@s5")]


def _csv(processed: Path, name: str) -> pl.DataFrame:
    return pl.read_csv(processed / name, infer_schema_length=None)


def r6(x):
    """Round floats to 6 significant digits so the JSON is compact and byte-stable."""
    if x is None:
        return None
    if isinstance(x, float):
        if x != x:
            return None
        return float(f"{x:.6g}")
    return x


def _axis(title: str = "", **kw) -> dict:
    a = {"title": {"text": title, "font": {"size": 12}}, "gridcolor": "@grid", "linecolor": "@axis", "zeroline": False,
         "tickfont": {"size": 11}, "automargin": True}
    a.update(kw)
    return a


def _band(x, lo, hi, color: str, xa="x", ya="y", name="90% interval") -> list[dict]:
    return [
        {"type": "scatter", "x": x, "y": [r6(v) for v in hi], "mode": "lines", "line": {"width": 0}, "xaxis": xa,
         "yaxis": ya, "hoverinfo": "skip", "showlegend": False, "name": name},
        {"type": "scatter", "x": x, "y": [r6(v) for v in lo], "mode": "lines", "line": {"width": 0}, "fill": "tonexty",
         "fillcolor": f"{color}/0.18", "xaxis": xa, "yaxis": ya, "hoverinfo": "skip", "showlegend": False, "name": name},
    ]


def _cols(n: int, gap: float = 0.06) -> list[list[float]]:
    w = (1 - gap * (n - 1)) / n
    return [[round(i * (w + gap), 4), round(i * (w + gap) + w, 4)] for i in range(n)]


def _rows(n: int, gap: float = 0.08) -> list[list[float]]:
    h = (1 - gap * (n - 1)) / n
    return [[round(1 - (i * (h + gap) + h), 4), round(1 - i * (h + gap), 4)] for i in reversed(range(n))][::-1]


def _panel_title(text: str, i: int) -> dict:
    s = "" if i == 1 else str(i)
    return {"text": f"<b>{text}</b>", "xref": f"x{s} domain", "yref": f"y{s} domain", "x": 0, "y": 1.02,
            "xanchor": "left", "yanchor": "bottom", "showarrow": False, "font": {"size": 12, "color": "@ink"}}


def _panels(n: int, wide: str, narrow: str) -> tuple[dict, dict]:
    """Axis domains for n panels: `wide` / `narrow` are 'cols' or 'rows'."""
    def lay(kind):
        doms = _cols(n) if kind == "cols" else _rows(n)
        out = {}
        for i, d in enumerate(doms, 1):
            s = "" if i == 1 else str(i)
            if kind == "cols":
                out[f"xaxis{s}"] = {"domain": d, "anchor": f"y{s}"}
                out[f"yaxis{s}"] = {"domain": [0, 0.9], "anchor": f"x{s}"}
            else:
                out[f"xaxis{s}"] = {"domain": [0, 1], "anchor": f"y{s}"}
                out[f"yaxis{s}"] = {"domain": [d[0], d[1] - 0.03], "anchor": f"x{s}"}
        return out
    return lay(wide), lay(narrow)


def _merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for k, v in extra.items():
        out[k] = {**out.get(k, {}), **v} if isinstance(v, dict) else v
    return out


# ------------------------------------------------------------------------------------------------- Q1 class shares
def classes(processed: Path, R: Registry) -> dict:
    q = _csv(processed, "organic_quarterly.csv").filter((pl.col("months") == 3) & (pl.col("quarter") >= QUARTERS_FROM)).sort("quarter")
    x = q["quarter"].to_list()
    traces, ann = [], []
    base_axes = {}
    for i, (c, label, color) in enumerate(CLASSES, 1):
        s = "" if i == 1 else str(i)
        xa, ya = f"x{s}", f"y{s}"
        traces += _band(x, q[f"tx_share_{c}_p05"].to_list(), q[f"tx_share_{c}_p95"].to_list(), color, xa, ya)
        traces.append({"type": "scatter", "x": x, "y": [r6(v) for v in q[f"tx_share_{c}"].to_list()], "mode": "lines+markers",
                       "name": label, "line": {"color": color, "width": 2}, "marker": {"size": 7, "color": color},
                       "xaxis": xa, "yaxis": ya, "showlegend": False,
                       "customdata": [[fmt(a, "ratio"), fmt(b, "ratio")] for a, b in
                                      zip(q[f"tx_share_{c}_p05"].to_list(), q[f"tx_share_{c}_p95"].to_list())],
                       "hovertemplate": f"{label}<br>%{{x}}: %{{y:.2%}}<br>90% CI %{{customdata[0]}} to %{{customdata[1]}}<extra></extra>"})
        base_axes[f"xaxis{s}"] = _axis("", tickangle=-45, tickfont={"size": 10})
        base_axes[f"yaxis{s}"] = _axis("", tickformat=".1~%", rangemode="tozero")
        ann.append(_panel_title(label, i))
    wide, narrow = _panels(5, "cols", "rows")
    layout = {**base_axes, "annotations": ann, "margin": {"l": 50, "r": 10, "t": 30, "b": 60}, "showlegend": False}
    rows = []
    for r in q.iter_rows(named=True):
        rows.append([r["quarter"]] + [f"{fmt(r[f'tx_share_{c}'], 'ratio')} ({fmt(r[f'tx_share_{c}_p05'], 'ratio')} to "
                                     f"{fmt(r[f'tx_share_{c}_p95'], 'ratio')})" for c, _, _ in CLASSES])
    return {
        "id": "classes", "q": "Q1", "title": "Who sends NEAR's transactions: five classes of signer, share of all transactions",
        "caption": (f"Shows the share of all transactions sent by each class of real signer per quarter, with 90% bootstrap "
                    f"intervals (organic {R.fmt('q1b.organic_tx_share')} in 2026-Q3, {R.fmt('q1b.organic_tx_share', 'ci')}); "
                    "it does not show who the people behind organic accounts are, and the classes come from a rule-based "
                    "bot score, not labelled data."),
        "sources": ["data/processed/organic_quarterly.csv"],
        "traces": traces, "layout": _merge(layout, wide), "layout_narrow": narrow, "height": 340, "height_narrow": 1000,
        "table": {"headers": ["Quarter"] + [lab for _, lab, _ in CLASSES], "rows": rows},
    }


# ------------------------------------------------------------------------------------------------- Q1 signers
def signers(processed: Path, R: Registry) -> dict:
    q = _csv(processed, "organic_quarterly.csv").filter((pl.col("months") == 3) & (pl.col("quarter") >= QUARTERS_FROM)).sort("quarter")
    am = (_csv(processed, "activity_monthly.csv")
          .with_columns((pl.col("month").str.slice(0, 4) + "-Q" + ((pl.col("month").str.slice(5, 2).cast(pl.Int64) - 1) // 3 + 1)
                         .cast(pl.Utf8)).alias("quarter"))
          .group_by("quarter").agg(((pl.col("nb_active_accounts_avg") * pl.col("nb_days")).sum() / pl.col("nb_days").sum())
                                   .alias("nb_active"), pl.len().alias("months")))
    q = q.join(am, on="quarter", how="left").sort("quarter")
    x = q["quarter"].to_list()
    floor = 300.0
    traces = []
    series = [("das_all", "All real signers (incl. inner signers of relayed txs)", "@s1"),
              ("das_organic", "Organic signers", "@s2")]
    for col, label, color in series:
        lo = [max(v, floor) for v in q[f"{col}_p05"].to_list()]
        traces += _band(x, lo, [max(v, floor) for v in q[f"{col}_p95"].to_list()], color)
        traces.append({"type": "scatter", "x": x, "y": [r6(v) if v > 0 else None for v in q[col].to_list()],
                       "mode": "lines+markers", "name": label, "connectgaps": False,
                       "line": {"color": color, "width": 2}, "marker": {"size": 8, "color": color},
                       "customdata": [[f"{a:,.0f}", f"{b:,.0f}"] for a, b in zip(q[f"{col}_p05"].to_list(), q[f"{col}_p95"].to_list())],
                       "hovertemplate": f"{label}<br>%{{x}}: %{{y:,.0f}} a day<br>90% CI %{{customdata[0]}} to %{{customdata[1]}}<extra></extra>"})
    traces.append({"type": "scatter", "x": x, "y": [r6(v) for v in q["nb_active"].to_list()], "mode": "lines+markers",
                   "name": "NearBlocks 'active accounts'", "line": {"color": "@s3", "width": 2}, "marker": {"size": 8, "color": "@s3", "symbol": "square"},
                   "hovertemplate": "NearBlocks active accounts<br>%{x}: %{y:,.0f} a day<extra></extra>"})
    ticks = [1e3, 3e3, 1e4, 3e4, 1e5, 3e5, 1e6, 3e6]
    layout = {"xaxis": _axis(""), "yaxis": _axis("Distinct accounts per day (log scale)", type="log", tickvals=ticks,
                                                 ticktext=[f"{t / 1e6:g}M" if t >= 1e6 else f"{t / 1e3:g}k" for t in ticks],
                                                 range=[math.log10(floor), math.log10(6e6)]),
              "legend": {"orientation": "h", "y": 1.12, "x": 0, "traceorder": "normal"},
              "margin": {"l": 70, "r": 10, "t": 40, "b": 40}, "hovermode": "closest"}
    zero_q = [r["quarter"] for r in q.iter_rows(named=True) if r["das_organic"] <= 0]
    rows = [[r["quarter"], f"{r['das_all']:,.0f} ({r['das_all_p05']:,.0f} to {r['das_all_p95']:,.0f})",
             f"{r['das_organic']:,.0f} ({r['das_organic_p05']:,.0f} to {r['das_organic_p95']:,.0f})",
             f"{r['nb_active']:,.0f}"] for r in q.iter_rows(named=True)]
    return {
        "id": "signers", "q": "Q1", "title": "Daily active signers: all, organic, and what NearBlocks reports",
        "caption": (f"Shows organic daily active signers falling from {R.fmt('q1b.organic_das_first_full_quarter')} (2025-Q1) to "
                    f"{R.fmt('q1b.organic_das')} (2026-Q3, 90% CI {R.fmt('q1b.organic_das', 'ci')}) while all real signers "
                    f"are {R.fmt('q1b.das_to_nearblocks', 'x')} what NearBlocks calls active accounts (median, last 12 months); it does not "
                    f"resolve the size of the organic decline, because the 2025-Q1 interval reaches 0 (lower bounds are "
                    f"drawn at {floor:,.0f} on the log axis, and a quarter with no organic draw ({', '.join(zero_q) or 'none'}) estimates 0 and "
                    "is left as a gap; the table has the exact intervals)."),
        "sources": ["data/processed/organic_quarterly.csv", "data/processed/activity_monthly.csv"],
        "traces": traces, "layout": layout, "height": 420,
        "table": {"headers": ["Quarter", "All real signers / day (90% CI)", "Organic signers / day (90% CI)",
                              "NearBlocks active accounts / day"], "rows": rows},
    }


# ------------------------------------------------------------------------------------------------- Q2 Intents check
def intents(processed: Path, R: Registry) -> dict:
    d = _csv(processed, "intents_check_days.csv").sort("day")
    x = d["day"].to_list()
    one, lo, hi = d["volume_sample_usd"].to_list(), d["volume_sample_p05"].to_list(), d["volume_sample_p95"].to_list()
    dl = d["defillama_volume_usd"].to_list()
    hov = lambda lab: f"{lab}<br>%{{x}}: $%{{y:,.3s}}<br>%{{customdata}}<extra></extra>"  # noqa: E731
    traces = [
        {"type": "bar", "x": x, "y": [r6(v) for v in dl], "name": "DefiLlama reported volume", "marker": {"color": "@s1"},
         "customdata": ["NEAR-uploaded Dune dataset" for _ in x], "hovertemplate": hov("DefiLlama")},
        {"type": "bar", "x": x, "y": [r6(v) for v in one], "name": "On-chain, each swap counted once (90% CI)", "marker": {"color": "@s2"},
         "error_y": {"type": "data", "symmetric": False, "array": [r6(h - v) for h, v in zip(hi, one)],
                     "arrayminus": [r6(v - lw) for v, lw in zip(one, lo)], "color": "@ink", "thickness": 1.2, "width": 4},
         "customdata": [f"{fmt(r, 'ratio')} of DefiLlama" for r in d["ratio_sample_to_defillama"].to_list()],
         "hovertemplate": hov("On-chain one-sided")},
        {"type": "bar", "x": x, "y": [r6(2 * v) for v in one], "name": "Two-sided equivalent (2x one-sided)", "marker": {"color": "@s3"},
         "error_y": {"type": "data", "symmetric": False, "array": [r6(2 * (h - v)) for h, v in zip(hi, one)],
                     "arrayminus": [r6(2 * (v - lw)) for v, lw in zip(one, lo)], "color": "@ink", "thickness": 1.2, "width": 4},
         "customdata": [f"{fmt(r, 'ratio')} of DefiLlama" for r in d["ratio_two_sided_to_defillama"].to_list()],
         "hovertemplate": hov("Two-sided equivalent")},
    ]
    layout = {"barmode": "group", "bargap": 0.25, "bargroupgap": 0.08, "xaxis": _axis("Sampled day (UTC)", type="category"),
              "yaxis": _axis("Swap volume that day (USD)", tickprefix="$", tickformat="~s"),
              "legend": {"orientation": "h", "y": 1.14, "x": 0}, "margin": {"l": 70, "r": 10, "t": 50, "b": 50}}
    rows = [[r["day"], fmt(r["defillama_volume_usd"], "USD"),
             f"{fmt(r['volume_sample_usd'], 'USD')} ({fmt(r['volume_sample_p05'], 'USD')} to {fmt(r['volume_sample_p95'], 'USD')})",
             fmt(r["ratio_sample_to_defillama"], "ratio"), fmt(r["ratio_two_sided_to_defillama"], "ratio"),
             f"{int(r['fee_paying_txs']):,}", f"{int(r['sampled_txs']):,}"] for r in d.iter_rows(named=True)]
    return {
        "id": "intents", "q": "Q2", "title": "NEAR Intents: swap volume rebuilt from on-chain events vs DefiLlama, by sampled day",
        "caption": (f"Shows that public on-chain swaps, each counted once, add up to {R.fmt('q2b.ratio_sample_median')} of DefiLlama's "
                    f"daily volume at the median of {R.fmt('ic.days', 'int')} sampled days and to {R.fmt('q2b.ratio_two_sided_median')} when "
                    "both legs are counted; it does not show whether the gap is a two-sided definition or confidential "
                    "volume that public events cannot see."),
        "sources": ["data/processed/intents_check_days.csv"],
        "traces": traces, "layout": layout, "height": 420,
        "table": {"headers": ["Day", "DefiLlama", "On-chain one-sided (90% CI)", "One-sided / DefiLlama",
                              "Two-sided / DefiLlama", "Fee-paying txs (census)", "Sampled txs"], "rows": rows},
    }


# ------------------------------------------------------------------------------------------------- Q4 revenue
def revenue(processed: Path, R: Registry) -> dict:
    rr = _csv(processed, "ledger_revenue_reconciliation.csv").filter(pl.col("usd_defillama") > 1000).sort("month")
    as_of = str(R.get("in.as_of").value)
    x = [m + (" (partial)" if m >= as_of[:7] else "") for m in rr["month"].to_list()]
    ratios = [fmt(v, "ratio") for v in rr["onchain_to_defillama"].to_list()]
    traces = [
        {"type": "bar", "x": x, "y": [r6(v) for v in rr["usd_defillama"].to_list()], "name": "DefiLlama captured revenue",
         "marker": {"color": "@s1"}, "hovertemplate": "DefiLlama<br>%{x}: $%{y:,.3s}<extra></extra>"},
        {"type": "bar", "x": x, "y": [r6(v) for v in rr["usd_onchain"].to_list()], "name": "Rebuilt from on-chain flows into the revenue wallets",
         "marker": {"color": "@s2"}, "customdata": ratios,
         "hovertemplate": "On-chain<br>%{x}: $%{y:,.3s}<br>%{customdata} of DefiLlama<extra></extra>"},
    ]
    layout = {"barmode": "group", "bargap": 0.25, "bargroupgap": 0.08, "xaxis": _axis("Month", type="category"),
              "yaxis": _axis("USD per month", tickprefix="$", tickformat="~s"),
              "legend": {"orientation": "h", "y": 1.14, "x": 0}, "margin": {"l": 70, "r": 10, "t": 50, "b": 50}}
    rows = [[m, fmt(r["usd_defillama"], "USD"), fmt(r["usd_onchain"], "USD"), fmt(r["near_onchain"], "NEAR"),
             fmt(r["onchain_to_defillama"], "ratio")] for m, r in zip(x, rr.iter_rows(named=True))]
    return {
        "id": "revenue", "q": "Q4", "title": "NEAR Intents captured revenue: DefiLlama vs rebuilt from on-chain flows",
        "caption": (f"Shows that the NEAR and wNEAR received by the three revenue wallets match DefiLlama's captured revenue "
                    f"month by month ({R.fmt('rev.ratio_min')} to {R.fmt('rev.ratio_max')}; {R.fmt('q4b.revenue_onchain_to_defillama')} "
                    f"over the last six months, the last one partial); it does not verify DefiLlama's gross fees or volume, "
                    "which come from a NEAR-uploaded dataset."),
        "sources": ["data/processed/ledger_revenue_reconciliation.csv"],
        "traces": traces, "layout": layout, "height": 400,
        "table": {"headers": ["Month", "DefiLlama", "On-chain (USD at daily price)", "On-chain (NEAR)", "On-chain / DefiLlama"],
                  "rows": rows},
    }


# ------------------------------------------------------------------------------------------------- Q4 treasury Sankey
def _short(acc: str) -> str:
    return f"{acc[:8]}… (implicit)" if len(acc) == 64 and all(c in "0123456789abcdef" for c in acc) else acc


CLASS_COLOR = {"treasury": "@s1", "named_other": "@s7", "multisig": "@s4", "implicit_near": "@muted",
               "staking_pool": "@s3", "other": "@axis"}


def treasury(processed: Path, R: Registry, min_edge: float = 250_000) -> dict:
    out = _csv(processed, "ledger_treasury_outflows.csv").filter((pl.col("date") >= "2026-04-01") & (pl.col("amount") >= 100_000))
    tl = _csv(processed, "ledger_trails.csv").filter(pl.col("out_asset") == "NEAR")
    ends = _csv(processed, "ledger_trail_endpoints.csv")
    edges: dict[tuple[str, str], float] = {}
    cls: dict[str, str] = {"treasury.near": "treasury"}
    for r in out.iter_rows(named=True):
        edges[("treasury.near", r["counterparty"])] = edges.get(("treasury.near", r["counterparty"]), 0.0) + r["amount"]
        cls[r["counterparty"]] = r["counterparty_class"]
    agg = (tl.group_by(["depth", "account", "account_class", "out_counterparty", "out_counterparty_class"])
           .agg(pl.col("out_near").sum().alias("near"), pl.len().alias("n"))
           .sort(["depth", "account", "out_counterparty"]))
    small: dict[str, float] = {}
    for r in agg.iter_rows(named=True):
        cls.setdefault(r["account"], r["account_class"])
        if r["near"] >= min_edge:
            cls.setdefault(r["out_counterparty"], r["out_counterparty_class"])
            k = (r["account"], r["out_counterparty"])
            edges[k] = edges.get(k, 0.0) + r["near"]
        elif r["near"] > 0:
            small[r["account"]] = small.get(r["account"], 0.0) + r["near"]
    # keep the graph acyclic: drop an edge whose target already reaches its source (NEAR sent back up the trail)
    adj: dict[str, set[str]] = {}
    kept, dropped = [], []

    def reaches(a: str, b: str) -> bool:
        stack, seen = [a], set()
        while stack:
            u = stack.pop()
            if u == b:
                return True
            if u in seen:
                continue
            seen.add(u)
            stack.extend(adj.get(u, ()))
        return False
    for (u, v), w in edges.items():
        if reaches(v, u):
            dropped.append((u, v, w))
            continue
        adj.setdefault(u, set()).add(v)
        kept.append((u, v, w))
    other = f"transfers under {min_edge / 1e3:,.0f}k NEAR (not drawn one by one)"
    for u, w in sorted(small.items()):
        if any(u == a for a, _, _ in kept) or u in adj or any(u == b for _, b, _ in kept):
            kept.append((u, other, w))
    cls[other] = "other"
    nodes: list[str] = []
    for u, v, _ in kept:
        for a in (u, v):
            if a not in nodes:
                nodes.append(a)
    stop = {r["endpoint"]: r["how"] for r in ends.iter_rows(named=True)}
    idx = {a: i for i, a in enumerate(nodes)}
    labels = [("treasury.near" if a == "treasury.near" else _short(a)) for a in nodes]
    node_hover = [f"{a}<br>class: {cls.get(a, 'other')}" + (f"<br>trail: {stop[a]}" if a in stop else "") for a in nodes]
    trace = {"type": "sankey", "arrangement": "snap", "valueformat": ",.0f", "valuesuffix": " NEAR",
             "node": {"label": labels, "pad": 14, "thickness": 14, "color": [CLASS_COLOR.get(cls.get(a, "other"), "@muted") for a in nodes],
                      "line": {"width": 0}, "customdata": node_hover, "hovertemplate": "%{customdata}<extra></extra>"},
             "link": {"source": [idx[u] for u, _, _ in kept], "target": [idx[v] for _, v, _ in kept],
                      "value": [r6(w) for _, _, w in kept],
                      "color": [f"{CLASS_COLOR.get(cls.get(v, 'other'), '@muted')}/0.35" for _, v, _ in kept],
                      "hovertemplate": "%{source.label} → %{target.label}<br>%{value} moved after receipt<extra></extra>"},
             "textfont": {"size": 11, "color": "@ink"}}
    layout = {"margin": {"l": 10, "r": 10, "t": 10, "b": 10}}
    rows = [[_short(u), _short(v), fmt(w, "NEAR")] for u, v, w in kept]
    rows += [[_short(u), _short(v), fmt(w, "NEAR") + " (loop back up the trail, not drawn)"] for u, v, w in dropped]
    return {
        "id": "treasury", "q": "Q4", "title": "Where treasury.near's April-May 2026 outflows went (five hops, transfers of 250k NEAR or more)",
        "caption": (f"Shows the accounts that moved NEAR after receiving the {R.fmt('q4b.treasury_outflows_since_apr')} sent by "
                    f"treasury.near ({R.fmt('tr.apr_tranche')} in April, {R.fmt('tr.may_tranche')} in May), reaching staking pools "
                    f"p2p-org ({R.fmt('tr.pool_p2p')}) and figment ({R.fmt('tr.pool_figment')}); it does not prove that the same "
                    "coins moved (NEAR is fungible, so link widths are amounts moved after each receipt and can exceed what an "
                    "account received) or who controls the unlabelled implicit accounts."),
        "sources": ["data/processed/ledger_treasury_outflows.csv", "data/processed/ledger_trails.csv",
                    "data/processed/ledger_trail_endpoints.csv"],
        "traces": [trace], "layout": layout, "height": 620, "min_width": 900,
        "table": {"headers": ["From", "To", "NEAR moved"], "rows": rows},
        "legend_html": [("treasury.near", "@s1"), ("named account", "@s7"), ("multisig", "@s4"),
                        ("implicit (unlabelled) account", "@muted"), ("staking pool", "@s3"), ("smaller transfers", "@axis")],
    }


# ------------------------------------------------------------------------------------------------- Q4 supply fans
POLICIES = [("status_quo", "Status quo: 2.5% cap", "@s1"), ("hsp029_act3m", "HSP-029, active after 3 months", "@s2"),
            ("hsp029_act9m", "HSP-029, active after 9 months", "@s3")]


def supply(processed: Path, R: Registry) -> dict:
    p = _csv(processed, "model_supply_paths.csv")
    s0 = float(R.get("in.supply0").value)
    traces = []
    for pol, label, color in POLICIES:
        def ser(level, col):
            t = p.filter(pl.col("scenario") == f"{pol}/{level}").sort("month")
            return [0] + t["month"].to_list(), t[col].to_list()
        m, cap = ser("base", "cap")
        traces.append({"type": "scatter", "x": m, "y": [r6(cap[0])] + [r6(v) for v in cap], "mode": "lines", "name": label,
                       "line": {"color": color, "width": 2, "shape": "hv"}, "xaxis": "x", "yaxis": "y", "showlegend": False,
                       "hovertemplate": f"{label}<br>month %{{x}}: cap %{{y:.2%}}<extra></extra>"})
        lo = [0.0] + [v / s0 - 1 for v in ser("high", "float_supply")[1]]   # high offsets -> lowest float growth
        hi = [0.0] + [v / s0 - 1 for v in ser("low", "float_supply")[1]]
        traces += _band(m, lo, hi, color, "x2", "y2")
        base = [0.0] + [v / s0 - 1 for v in ser("base", "float_supply")[1]]
        traces.append({"type": "scatter", "x": m, "y": [r6(v) for v in base], "mode": "lines", "name": label,
                       "line": {"color": color, "width": 2, "dash": "solid" if pol == "status_quo" else "dot" if pol.endswith("9m") else "dash"},
                       "xaxis": "x2", "yaxis": "y2",
                       "hovertemplate": f"{label}<br>month %{{x}}: float +%{{y:.2%}} vs today (base offsets)<extra></extra>"})
    layout = {"xaxis": {**_axis(""), "domain": [0, 1], "anchor": "y", "matches": "x2", "showticklabels": False},
              "yaxis": {**_axis("Issuance cap"), "domain": [0.72, 0.95], "tickformat": ".1%", "rangemode": "tozero"},
              "xaxis2": {**_axis("Months from the snapshot"), "domain": [0, 1], "anchor": "y2", "dtick": 12},
              "yaxis2": {**_axis("Float growth vs today"), "domain": [0, 0.6], "tickformat": ".0%"},
              "annotations": [_panel_title("Issuance cap per policy", 1), _panel_title(
                  "Float (supply minus NEAR bought back and held), growth since the snapshot; band = low to high offsets", 2)],
              "legend": {"orientation": "h", "y": -0.18, "x": 0, "traceorder": "normal"},
              "margin": {"l": 70, "r": 10, "t": 30, "b": 70}}
    sc = _csv(processed, "model_supply_scenarios.csv").filter(pl.col("horizon_years").is_in([1, 3, 5])).sort(["scenario", "horizon_years"])
    rows = [[r["scenario"], str(r["horizon_years"]), fmt(r["total_supply"], "NEAR"), fmt(r["float_supply"], "NEAR"),
             fmt(r["float_growth_cagr"], "ratio"), "yes" if str(r["offsets_cover_issuance"]).lower() == "true" else "no"]
            for r in sc.iter_rows(named=True)]
    return {
        "id": "supply", "q": "Q4", "title": "Supply and dilution: 2.5% issuance vs HSP-029 (1.6%), five-year scenario fans",
        "caption": (f"Shows float growth of {R.fmt('sc.status_quo/base.1y.float_cagr')} in year one at the 2.5% cap with today's burn "
                    f"and buybacks, and {R.fmt('ma.float_cagr_5y.hsp029_act3m/base')} a year over five years if HSP-029 activates after "
                    f"three months (snapshot status: {R.fmt('in.hsp029_status')}); it does not forecast price, and the bands only vary "
                    "fee and Intents revenue growth (the model's low / base / high inputs), not the vote outcome."),
        "sources": ["data/processed/model_supply_paths.csv", "data/processed/model_supply_scenarios.csv",
                    "data/processed/model_inputs.csv"],
        "traces": traces, "layout": layout, "height": 520,
        "table": {"headers": ["Scenario", "Years", "Total supply", "Float", "Float growth / yr", "Burn + buybacks cover issuance"],
                  "rows": rows},
    }


# ------------------------------------------------------------------------------------------------- Q7 multiples
def multiples(processed: Path, R: Registry) -> dict:
    mm = _csv(processed, "model_multiples.csv").filter(pl.col("basis") == "30d_annualized")
    panels = [("chain_fees", "fees_plus_intents_fees", "Market cap / annualized fees (30 days)"),
              ("chain_revenue", "revenue_plus_intents_revenue", "Market cap / annualized revenue (30 days)")]
    traces, ann, shapes, rows = [], [], [], []
    for i, (peer_var, near_var, title) in enumerate(panels, 1):
        s = "" if i == 1 else str(i)
        pe = mm.filter((pl.col("variant") == peer_var) & (pl.col("chain") != "near") & pl.col("multiple").is_not_null()).sort("multiple")
        n1 = mm.filter((pl.col("variant") == peer_var) & (pl.col("chain") == "near")).row(0, named=True)
        n2 = mm.filter((pl.col("variant") == near_var) & (pl.col("chain") == "near")).row(0, named=True)
        cats = [c.capitalize() for c in pe["chain"].to_list()] + ["NEAR, chain only", "NEAR incl. Intents"]
        vals = pe["multiple"].to_list() + [n1["multiple"], n2["multiple"]]
        colors = ["@muted"] * pe.height + ["@s2", "@s1"]
        traces.append({"type": "bar", "orientation": "h", "y": cats, "x": [r6(v) for v in vals], "marker": {"color": colors},
                       "xaxis": f"x{s}", "yaxis": f"y{s}", "showlegend": False,
                       "text": [f"{v:,.0f}x" for v in vals], "textposition": "outside", "cliponaxis": False,
                       "textfont": {"size": 11, "color": "@ink"},
                       "hovertemplate": "%{y}: %{x:,.0f}x<extra></extra>"})
        med = float(R.get(f"mv.{peer_var}.30d_annualized.peer_median").value)
        shapes.append({"type": "line", "xref": f"x{s}", "yref": f"y{s} domain", "x0": med, "x1": med, "y0": 0, "y1": 1,
                       "line": {"color": "@ink", "width": 1.5, "dash": "dot"}})
        ann.append(_panel_title(title, i))
        ann.append({"text": f"peer median {med:,.0f}x", "xref": f"x{s}", "yref": f"y{s} domain", "x": math.log10(med),
                    "y": 1.0, "xanchor": "left", "yanchor": "top", "xshift": 4, "showarrow": False, "font": {"size": 11, "color": "@ink2"}})
        rows += [[title.split(" / ")[1].split(" (")[0], c, f"{v:,.0f}x"] for c, v in zip(cats, vals)]
    ticks = [30, 100, 300, 1000, 3000, 10000, 30000]
    lx = dict(type="log", tickvals=ticks, ticktext=[f"{t:,}x" for t in ticks], range=[math.log10(50), math.log10(30000)])
    base = {"xaxis": _axis("", **lx), "yaxis": _axis(""), "xaxis2": _axis("", **lx), "yaxis2": _axis(""), "bargap": 0.35,
            "annotations": ann, "shapes": shapes, "margin": {"l": 130, "r": 40, "t": 40, "b": 40}, "showlegend": False}
    wide, narrow = _panels(2, "cols", "rows")
    for lay in (wide, narrow):
        for k in ("yaxis", "yaxis2"):
            lay[k]["automargin"] = True
    if wide["xaxis2"]["domain"][0] < 0.6:
        wide["xaxis2"]["domain"] = [0.62, 1.0]
        wide["xaxis"]["domain"] = [0.0, 0.40]
    return {
        "id": "multiples", "q": "Q7", "title": "Valuation multiples vs peers, with and without NEAR Intents (log scale; lower = cheaper)",
        "caption": (f"Shows NEAR's market cap at {R.fmt('mb.chain_fees', 'x')} its annualized chain fees (peer median "
                    f"{R.fmt('mv.chain_fees.30d_annualized.peer_median')}) but {R.fmt('mb.fees_plus_intents_fees', 'x')} once NEAR Intents fees are "
                    f"counted, and {R.fmt('mb.revenue_plus_intents_revenue', 'x')} on captured revenue; it does not say which basis the market "
                    "should use, and most Intents fees never reach NEAR's revenue wallets."),
        "sources": ["data/processed/model_multiples.csv", "data/processed/model_multiples_near_vs_peers.csv"],
        "traces": traces, "layout": _merge(base, wide), "layout_narrow": narrow, "height": 380, "height_narrow": 700,
        "table": {"headers": ["Basis", "Chain", "Multiple"], "rows": rows},
    }


# ------------------------------------------------------------------------------------------------- Q6 developers
def developers(processed: Path, R: Registry) -> dict:
    ds = _csv(processed, "dev_ecosystem_share_quarterly.csv").filter((pl.col("ecosystem") == "near") & (pl.col("quarter") >= "2022-Q1")).sort("quarter")
    x = ds["quarter"].to_list()
    traces = [
        {"type": "bar", "x": x, "y": ds["all_devs"].to_list(), "name": "NEAR monthly active developers", "marker": {"color": "@s1"},
         "xaxis": "x", "yaxis": "y", "showlegend": False, "hovertemplate": "%{x}: %{y:,} developers<extra></extra>"},
        {"type": "scatter", "x": x, "y": [r6(v) for v in ds["share_of_web3_devs"].to_list()], "mode": "lines+markers",
         "name": "Share of all web3 developers", "line": {"color": "@s2", "width": 2}, "marker": {"size": 7, "color": "@s2"},
         "xaxis": "x2", "yaxis": "y2", "hovertemplate": "%{x}: %{y:.2%} of web3 developers<extra></extra>"},
        {"type": "scatter", "x": x, "y": [r6(v) for v in ds["near_to_peer_set"].to_list()], "mode": "lines+markers",
         "name": "NEAR / developers of the six peer chains", "line": {"color": "@s3", "width": 2},
         "marker": {"size": 7, "color": "@s3", "symbol": "square"}, "xaxis": "x2", "yaxis": "y2",
         "hovertemplate": "%{x}: %{y:.2%} of the peer set<extra></extra>"},
    ]
    layout = {"xaxis": {**_axis(""), "domain": [0, 1], "anchor": "y", "matches": "x2", "showticklabels": False, "type": "category"},
              "yaxis": {**_axis("Developers"), "domain": [0.55, 0.93]},
              "xaxis2": {**_axis("", tickangle=-45), "domain": [0, 1], "anchor": "y2", "type": "category"},
              "yaxis2": {**_axis("Share"), "domain": [0, 0.42], "tickformat": ".1%", "rangemode": "tozero"},
              "annotations": [_panel_title("NEAR monthly active developers (Electric Capital, quarter end)", 1),
                              _panel_title("NEAR's share", 2)],
              "legend": {"orientation": "h", "y": -0.3, "x": 0, "traceorder": "normal"},
              "margin": {"l": 70, "r": 10, "t": 30, "b": 60}}
    rows = [[r["quarter"], f"{int(r['all_devs']):,}", fmt(r["share_of_web3_devs"], "ratio"), fmt(r["near_to_peer_set"], "ratio")]
            for r in ds.iter_rows(named=True)]
    return {
        "id": "developers", "q": "Q6", "title": "Developers: NEAR's monthly active developers and its share",
        "caption": (f"Shows NEAR's monthly active developers down {R.fmt('q6.near_mad_yoy', 'abs')} in a year to {R.fmt('q6.near_mad')} "
                    f"while its count relative to the six peer chains rose from {R.fmt('dev.2025q3.to_peers')} to "
                    f"{R.fmt('dev.2026q3.to_peers')}; it does not measure developer quality or output, and Electric Capital's "
                    "repository-to-ecosystem mapping is taken as published."),
        "sources": ["data/processed/dev_ecosystem_share_quarterly.csv"],
        "traces": traces, "layout": layout, "height": 520,
        "table": {"headers": ["Quarter", "NEAR developers", "Share of web3", "NEAR / peer chains"], "rows": rows},
    }


def all_charts(processed: Path, R: Registry) -> list[dict]:
    return [classes(processed, R), signers(processed, R), intents(processed, R), revenue(processed, R),
            treasury(processed, R), supply(processed, R), multiples(processed, R), developers(processed, R)]
