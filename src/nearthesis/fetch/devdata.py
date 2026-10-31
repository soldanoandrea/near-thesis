"""Developer activity (PIANO.md Q6, phase 2a). Two keyless sources:

1. GitHub REST API without a token (60 requests/hour per IP). A small, cached pull: repository metadata,
   `stats/contributors` (weekly commits of the top 100 contributors over the whole history), `stats/participation`
   (weekly commits of everyone, last 52 weeks) and releases, for NEAR's core repositories, the NEAR Intents verifier
   and the most-starred active repositories of the `nearai` organization. The fetcher reads X-RateLimit-Remaining and
   sleeps until the reset time instead of running into 403s; `stats/*` answers 202 while GitHub computes and is
   retried after a pause. What could not be fetched is recorded with its HTTP status in `github/fetch_log.csv`.
2. Electric Capital Open Dev Data (CC BY 4.0, https://data.opendevdata.org/manifest.json): the per-ecosystem daily
   Monthly Active Developer table `eco_mads.parquet` is read with HTTP range requests (only the row groups of the
   selected ecosystems), and only month-end rows are kept.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
import time

import httpx
import polars as pl

from .. import config, manifest, paths

GH = "https://api.github.com"
CORE_REPOS = ["near/nearcore", "near/near-sdk-rs", "near/near-sdk-js", "near/near-api-js", "near/near-cli-rs"]
# NEAR Intents: the Verifier contract and the two repositories linked from docs.near-intents.org (SDK, example solver)
INTENTS_REPOS = ["near/intents", "defuse-protocol/sdk-monorepo", "defuse-protocol/near-intents-amm-solver"]
NEARAI_ORG = "nearai"
NEARAI_TOP = 4
ODD_MANIFEST = "https://data.opendevdata.org/manifest.json"
ODD_ECOSYSTEMS = {2817: "near", 391: "solana", 9547: "sui", 9601: "aptos", 13317: "base", 2: "ethereum", 10: "tron",
                  7164: "all_web3"}


class GitHub:
    """Keyless, cached, rate-limit-aware GET client for api.github.com."""

    def __init__(self):
        cfg = config.load()["http"]
        self.client = httpx.Client(timeout=60, headers={"User-Agent": cfg["user_agent"],
                                                        "Accept": "application/vnd.github+json"})
        self.cache = paths.CACHE / "api.github.com"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.min_interval = float(cfg["min_interval_s"].get("api.github.com", 5.0))
        self.last = 0.0
        self.log: list[dict] = []
        self.requests = 0

    def get(self, path: str, max_age_s: float = 3 * 86400, accept_202: int = 3):
        url = path if path.startswith("http") else GH + path
        cpath = self.cache / (hashlib.sha256(url.encode()).hexdigest() + ".json")
        if cpath.exists():
            c = json.loads(cpath.read_text())
            if time.time() - c["fetched_at_unix"] <= max_age_s:
                self.log.append({"url": url, "status": c["status"], "from_cache": True})
                return c["status"], c["body"], c.get("link", "")
        for attempt in range(accept_202 + 1):
            wait = self.min_interval - (time.monotonic() - self.last)
            if wait > 0:
                time.sleep(wait)
            r = self.client.get(url)
            self.last = time.monotonic()
            self.requests += 1
            rem = int(r.headers.get("x-ratelimit-remaining", "60"))
            reset = int(r.headers.get("x-ratelimit-reset", "0"))
            print(f"  GET {url} -> {r.status_code} (remaining {rem})", file=sys.stderr, flush=True)
            if r.status_code == 202 and attempt < accept_202:
                time.sleep(30)
                continue
            if r.status_code in (403, 429) and rem == 0:
                pause = max(0, reset - time.time()) + 5
                print(f"  rate limit reached; sleeping {pause:.0f}s until reset", file=sys.stderr, flush=True)
                time.sleep(min(pause, 3700))
                continue
            break
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") and r.content else None
        if r.status_code == 200:
            cpath.write_text(json.dumps({"url": url, "status": r.status_code, "fetched_at_unix": int(time.time()),
                                         "body": body, "link": r.headers.get("link", "")}))
        self.log.append({"url": url, "status": r.status_code, "from_cache": False})
        if rem <= 2:
            pause = max(0, reset - time.time()) + 5
            print(f"  {rem} requests left; sleeping {pause:.0f}s until reset", file=sys.stderr, flush=True)
            time.sleep(min(pause, 3700))
        return r.status_code, body, r.headers.get("link", "")


def fetch_github(client=None) -> None:
    gh = GitHub()
    fetched_at = manifest.utc_now()
    st, org, _ = gh.get(f"/orgs/{NEARAI_ORG}/repos?per_page=100&type=public&sort=pushed")
    nearai = []
    if st == 200 and org:
        cutoff = (dt.datetime.now(dt.UTC) - dt.timedelta(days=365)).isoformat()
        cand = [r for r in org if not r.get("fork") and not r.get("archived") and (r.get("pushed_at") or "") >= cutoff]
        nearai = [r["full_name"] for r in sorted(cand, key=lambda r: (-r["stargazers_count"], r["full_name"]))][:NEARAI_TOP]
    repos = CORE_REPOS + INTENTS_REPOS + nearai
    meta_rows, week_rows, part_rows, rel_rows = [], [], [], []
    for repo in repos:
        st, m, _ = gh.get(f"/repos/{repo}")
        if st != 200 or not m:
            continue
        group = "nearai" if repo in nearai else ("intents" if repo in INTENTS_REPOS else "core")
        meta_rows.append({"repo": repo, "resolved_full_name": m["full_name"], "group": group,
                          "created_at": m["created_at"], "pushed_at": m["pushed_at"], "stars": m["stargazers_count"],
                          "forks": m["forks_count"], "open_issues": m["open_issues_count"], "archived": m["archived"],
                          "default_branch": m["default_branch"], "language": m.get("language") or ""})
        st, contrib, _ = gh.get(f"/repos/{repo}/stats/contributors")
        if st == 200 and isinstance(contrib, list):
            for c in contrib:
                login = (c.get("author") or {}).get("login") or f"anon-{hashlib.sha256(json.dumps(c.get('author')).encode()).hexdigest()[:8]}"
                for w in c.get("weeks") or []:
                    if w.get("c"):
                        week_rows.append({"repo": repo, "author": login,
                                          "week_start": dt.datetime.fromtimestamp(w["w"], dt.UTC).strftime("%Y-%m-%d"),
                                          "commits": int(w["c"])})
        st, part, _ = gh.get(f"/repos/{repo}/stats/participation")
        if st == 200 and isinstance(part, dict) and part.get("all"):
            # 52 weekly buckets, oldest first, the last one ending at the time of the request
            now = dt.datetime.now(dt.UTC).date()
            for i, n in enumerate(part["all"]):
                part_rows.append({"repo": repo, "weeks_ago": 51 - i, "approx_week_start":
                                  str(now - dt.timedelta(days=7 * (52 - i))), "commits_all": int(n),
                                  "commits_owner": int((part.get("owner") or [0] * 52)[i])})
        page, url = 0, f"/repos/{repo}/releases?per_page=100"
        while url and page < 2:
            st, rel, link = gh.get(url)
            page += 1
            if st != 200 or not isinstance(rel, list):
                break
            for r in rel:
                rel_rows.append({"repo": repo, "tag": r.get("tag_name") or "", "published_at": r.get("published_at") or "",
                                 "prerelease": bool(r.get("prerelease")), "draft": bool(r.get("draft"))})
            url = None
            for part_link in (link or "").split(","):
                if 'rel="next"' in part_link:
                    url = part_link[part_link.find("<") + 1:part_link.find(">")]
    stats = {"requests": gh.requests}
    common = dict(params={"repos": repos, "nearai_top": NEARAI_TOP}, http_stats=stats, fetched_at=fetched_at)
    manifest.save_table("github", "repos", pl.DataFrame(meta_rows, infer_schema_length=None),
                        urls=[f"{GH}/repos/<owner>/<repo>", f"{GH}/orgs/{NEARAI_ORG}/repos"], sort_by=["repo"],
                        notes="Repository metadata at fetch time. nearai repos = most-starred non-fork, non-archived "
                              "repos pushed in the last 365 days.", **common)
    manifest.save_table("github", "contributor_weeks",
                        pl.DataFrame(week_rows, schema={"repo": pl.Utf8, "author": pl.Utf8, "week_start": pl.Utf8,
                                                        "commits": pl.Int64}),
                        urls=[f"{GH}/repos/<owner>/<repo>/stats/contributors"],
                        sort_by=["repo", "week_start", "author"],
                        notes="Weekly commits (default branch) of the top 100 contributors per repo, weeks with >0 "
                              "commits only. Public GitHub logins.", **common)
    manifest.save_table("github", "participation",
                        pl.DataFrame(part_rows, schema={"repo": pl.Utf8, "weeks_ago": pl.Int64,
                                                        "approx_week_start": pl.Utf8, "commits_all": pl.Int64,
                                                        "commits_owner": pl.Int64}),
                        urls=[f"{GH}/repos/<owner>/<repo>/stats/participation"], sort_by=["repo", "weeks_ago"],
                        notes="Weekly commit counts of all contributors, last 52 weeks (bucket 0 = most recent).",
                        **common)
    manifest.save_table("github", "releases",
                        pl.DataFrame(rel_rows, schema={"repo": pl.Utf8, "tag": pl.Utf8, "published_at": pl.Utf8,
                                                       "prerelease": pl.Boolean, "draft": pl.Boolean}),
                        urls=[f"{GH}/repos/<owner>/<repo>/releases"], sort_by=["repo", "published_at", "tag"],
                        notes="Up to 200 most recent releases per repo.", **common)
    log = pl.DataFrame(gh.log, schema={"url": pl.Utf8, "status": pl.Int64, "from_cache": pl.Boolean})
    manifest.save_table("github", "fetch_log", log.unique(subset=["url"], keep="last", maintain_order=True),
                        urls=[GH], sort_by=["url"],
                        notes="Every GitHub URL requested and its final HTTP status (202 = statistics still being "
                              "computed by GitHub; such tables are missing for that repo).", **common)


def fetch_opendevdata(client=None) -> None:
    fetched_at = manifest.utc_now()
    man = httpx.get(ODD_MANIFEST, timeout=60).json()["dataset"]
    version = man["version"]
    res = {r["path"].rsplit("/", 1)[-1]: r for r in man["resources"]}
    url = "https://data.opendevdata.org" + res["eco_mads.parquet"]["path"]
    df = (pl.scan_parquet(url).filter(pl.col("ecosystem_id").is_in(list(ODD_ECOSYSTEMS))).collect()
          .with_columns(pl.col("day").dt.strftime("%Y-%m").alias("month")))
    monthly_commits = df.group_by(["ecosystem_id", "month"]).agg(pl.col("num_commits").sum().alias("num_commits_month_sum"),
                                                                  pl.len().alias("days_in_data"))
    last = df.sort("day").group_by(["ecosystem_id", "month"], maintain_order=True).last()
    out = (last.join(monthly_commits, on=["ecosystem_id", "month"])
           .with_columns(pl.col("ecosystem_id").replace_strict(ODD_ECOSYSTEMS, return_dtype=pl.Utf8).alias("ecosystem"),
                         pl.col("day").dt.strftime("%Y-%m-%d").alias("day"))
           .select("ecosystem", "ecosystem_id", "month", "day", "all_devs", "exclusive_devs", "multichain_devs",
                   "full_time_devs", "part_time_devs", "one_time_devs", "devs_0_1y", "devs_1_2y", "devs_2y_plus",
                   "num_commits", "num_commits_month_sum", "days_in_data"))
    manifest.save_table("opendevdata", "eco_mads_monthly", out, urls=[url, ODD_MANIFEST],
                        params={"version": version, "ecosystem_ids": ODD_ECOSYSTEMS, "license": "CC BY 4.0"},
                        sort_by=["ecosystem", "month"], fetched_at=fetched_at,
                        notes="Electric Capital Open Dev Data eco_mads: last available day of each month per ecosystem "
                              "(all_devs etc. are 28-day rolling Monthly Active Developer counts), plus the sum of the "
                              "daily num_commits column over the month. Read with HTTP range requests (no full download).",
                        http_stats={"rows_read": df.height})
