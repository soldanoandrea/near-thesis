"""Developer activity (Q6): GitHub repositories (keyless REST, cached) and Electric Capital Open Dev Data MADs.

* GitHub commits per month = sum of weekly commits of the top 100 contributors (stats/contributors), weeks assigned to
  the month of their start date; active authors = distinct logins with >= 1 commit in such weeks. `participation`
  (all contributors, last 52 weeks) measures how much of the commit flow the top-100 table covers.
* Open Dev Data: `all_devs` is a 28-day rolling Monthly Active Developer count (Electric Capital methodology); the
  month-end value is used. NEAR's share = NEAR all_devs / "All Web3 Ecosystems" all_devs. Developers active in several
  ecosystems count in each, so shares of different chains do not add to 100%.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from .. import io


def github_monthly(raw: Path) -> pl.DataFrame:
    w = io.read_csv(raw / "github" / "contributor_weeks.csv").with_columns(pl.col("commits").cast(pl.Int64))
    repos = io.read_csv(raw / "github" / "repos.csv").select("repo", "group")
    m = (w.with_columns(pl.col("week_start").str.slice(0, 7).alias("month"))
         .group_by(["repo", "month"]).agg(pl.col("commits").sum(), pl.col("author").n_unique().alias("active_authors"))
         .join(repos, on="repo", how="left"))
    grp = (w.join(repos, on="repo").with_columns(pl.col("week_start").str.slice(0, 7).alias("month"))
           .group_by(["group", "month"]).agg(pl.col("commits").sum(), pl.col("author").n_unique().alias("active_authors"))
           .with_columns(pl.lit("ALL:" ).add(pl.col("group")).alias("repo")))
    return pl.concat([m.select("repo", "group", "month", "commits", "active_authors"),
                      grp.select("repo", "group", "month", "commits", "active_authors")]).sort(["repo", "month"])


def github_summary(raw: Path, as_of: str) -> pl.DataFrame:
    """Per repo: last 12 complete months vs the 12 before (commits, authors), releases, top-100 coverage."""
    mon = github_monthly(raw).filter(~pl.col("repo").str.starts_with("ALL:"))
    end = as_of[:7]  # current (partial) month excluded
    months = sorted({m for m in mon["month"].to_list() if m < end})
    last12, prev12 = months[-12:], months[-24:-12]
    w = io.read_csv(raw / "github" / "contributor_weeks.csv").with_columns(pl.col("commits").cast(pl.Int64))
    rel = io.read_csv(raw / "github" / "releases.csv").filter(pl.col("draft") != "true")
    part = io.read_csv(raw / "github" / "participation.csv").with_columns(pl.col("commits_all").cast(pl.Int64))
    repos = io.read_csv(raw / "github" / "repos.csv")
    rows = []
    for r in repos.iter_rows(named=True):
        repo = r["repo"]
        mr = mon.filter(pl.col("repo") == repo)
        wr = w.filter(pl.col("repo") == repo).with_columns(pl.col("week_start").str.slice(0, 7).alias("month"))
        c12 = int(mr.filter(pl.col("month").is_in(last12))["commits"].sum())
        c24 = int(mr.filter(pl.col("month").is_in(prev12))["commits"].sum())
        a12 = wr.filter(pl.col("month").is_in(last12))["author"].n_unique()
        a24 = wr.filter(pl.col("month").is_in(prev12))["author"].n_unique()
        rr = rel.filter(pl.col("repo") == repo)
        rl12 = rr.filter(pl.col("published_at").str.slice(0, 7).is_in(last12))
        pa = part.filter(pl.col("repo") == repo)
        # top-100 coverage over the participation window (52 weeks ending at the fetch)
        if pa.height:
            first_week = pa["approx_week_start"].min()
            top = int(w.filter((pl.col("repo") == repo) & (pl.col("week_start") >= first_week))["commits"].sum())
            allc = int(pa["commits_all"].sum())
        else:
            top, allc = None, None
        rows.append({"repo": repo, "group": r["group"], "archived": r["archived"] == "true", "stars": int(r["stars"]),
                     "window_last12": f"{last12[0]} to {last12[-1]}" if last12 else "",
                     "commits_last12": c12, "commits_prev12": c24,
                     "commits_change": (c12 / c24 - 1) if c24 else None,
                     "authors_last12": a12, "authors_prev12": a24,
                     "authors_change": (a12 / a24 - 1) if a24 else None,
                     "releases_last12": rl12.height,
                     "stable_releases_last12": rl12.filter(pl.col("prerelease") != "true").height,
                     "last_release": rr["published_at"].max() if rr.height else "",
                     "participation_52w_commits": allc, "top100_52w_commits": top,
                     "top100_coverage_52w": (top / allc) if allc else None})
    return pl.DataFrame(rows, infer_schema_length=None).sort("repo")


def ecosystem_monthly(raw: Path) -> pl.DataFrame:
    e = io.read_csv(raw / "opendevdata" / "eco_mads_monthly.csv").with_columns(
        [pl.col(c).cast(pl.Int64) for c in ("all_devs", "exclusive_devs", "multichain_devs", "full_time_devs",
                                            "part_time_devs", "one_time_devs", "num_commits")])
    tot = e.filter(pl.col("ecosystem") == "all_web3").select("month", pl.col("all_devs").alias("web3_devs"),
                                                             pl.col("full_time_devs").alias("web3_full_time"))
    out = (e.filter(pl.col("ecosystem") != "all_web3").join(tot, on="month", how="left")
           .with_columns((pl.col("all_devs") / pl.col("web3_devs")).alias("share_of_web3_devs"),
                         (pl.col("full_time_devs") / pl.col("web3_full_time")).alias("share_of_web3_full_time"),
                         (pl.col("exclusive_devs") / pl.col("all_devs")).alias("exclusive_share"),
                         (pl.col("day").str.slice(8, 2).cast(pl.Int64) < 28).alias("partial_month")))
    return out.select("ecosystem", "month", "day", "partial_month", "all_devs", "full_time_devs", "exclusive_devs",
                      "web3_devs", "share_of_web3_devs", "share_of_web3_full_time", "exclusive_share",
                      pl.col("num_commits").alias("commits_28d")).sort(["ecosystem", "month"])


def share_trend(eco: pl.DataFrame) -> pl.DataFrame:
    """Quarter-end share of web3 developers per ecosystem and its quarter-on-quarter change."""
    q = (eco.filter(~pl.col("partial_month") & pl.col("month").str.slice(5, 2).is_in(["03", "06", "09", "12"]))
         .with_columns((pl.col("month").str.slice(0, 4) + "-Q" + (pl.col("month").str.slice(5, 2).cast(pl.Int64) // 3)
                        .cast(pl.Utf8)).alias("quarter"))
         .sort(["ecosystem", "quarter"])
         .with_columns(pl.col("share_of_web3_devs").diff().over("ecosystem").alias("share_change_qoq"),
                       (pl.col("all_devs") / pl.col("all_devs").shift(4).over("ecosystem") - 1).alias("devs_yoy")))
    peers = (q.filter(pl.col("ecosystem") != "near").group_by("quarter").agg(pl.col("all_devs").sum().alias("peer_devs")))
    q = q.join(peers, on="quarter", how="left").with_columns((pl.col("all_devs") / pl.col("peer_devs")).alias("near_to_peer_set"))
    q = q.with_columns(pl.when(pl.col("ecosystem") == "near").then(pl.col("near_to_peer_set")).otherwise(None)
                       .alias("near_to_peer_set"))
    return q.select("ecosystem", "quarter", "all_devs", "full_time_devs", "share_of_web3_devs", "share_change_qoq",
                    "devs_yoy", "near_to_peer_set").sort(["ecosystem", "quarter"])
