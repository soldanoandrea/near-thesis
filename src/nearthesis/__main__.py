"""Command line: `python -m nearthesis refresh|build|verify`.

refresh  re-downloads every keyless source into data/raw/ (+ MANIFEST.json). Network. About 2 h, rate limited.
build    rebuilds data/processed/ and reports/metrics_summary.md from data/raw/ only. Offline, seconds.
site     renders thesis/THESIS.md and the static dashboard in site/ from data/processed/. Offline, seconds.
verify   checks data/raw/ against MANIFEST.json (sha256, row counts).
"""

from __future__ import annotations

import argparse
import sys
import time

STEPS = ["nearblocks", "defillama", "coingecko", "aurora", "onchain", "epochs", "activity", "treasury",
         # phase 2a (analysis layer)
         "signer_blocks", "signers", "trails", "github", "opendevdata", "intents_check", "governance"]


def refresh(only: list[str] | None, skip: list[str] | None) -> None:
    from .fetch import aurora, coingecko, defillama, fastnear_activity, nearblocks, onchain_state, rpc_epochs, signers
    from .fetch import devdata, governance, intents_check, money_trails
    from .http import PoliteClient

    fns = {
        "nearblocks": nearblocks.fetch,
        "defillama": defillama.fetch,
        "coingecko": coingecko.fetch,
        "aurora": aurora.fetch,
        "onchain": onchain_state.fetch,
        "epochs": rpc_epochs.fetch,
        "activity": fastnear_activity.fetch,
        "treasury": fastnear_activity.fetch_treasury,
        "signer_blocks": signers.fetch_extra_blocks,
        "signers": signers.fetch,
        "trails": money_trails.fetch,
        "github": devdata.fetch_github,
        "opendevdata": devdata.fetch_opendevdata,
        "intents_check": intents_check.fetch,
        "governance": governance.fetch,
    }
    steps = [s for s in STEPS if (not only or s in only) and (not skip or s not in skip)]
    client = PoliteClient()
    failed = []
    for s in steps:
        t0 = time.time()
        print(f"[refresh] {s} ...", flush=True)
        try:
            fns[s](client)
            print(f"[refresh] {s} done in {time.time() - t0:.0f}s", flush=True)
        except Exception as exc:  # keep going: one failing source must not block the others
            failed.append(s)
            print(f"[refresh] {s} FAILED: {type(exc).__name__}: {exc}", flush=True)
    print("[refresh] http stats per host:")
    for host, st in sorted(client.stats.items()):
        print(f"  {host}: {vars(st)}")
    client.close()
    if failed:
        print(f"[refresh] failed steps: {failed} (previous snapshots for them are kept)")
        sys.exit(1)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="nearthesis")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("refresh", help="re-download raw snapshots (network)")
    r.add_argument("--only", nargs="*", choices=STEPS)
    r.add_argument("--skip", nargs="*", choices=STEPS)
    b = sub.add_parser("build", help="offline: raw -> processed tables + reports/metrics_summary.md")
    b.add_argument("--out", default=None, help="output root (default: repo root); used by the determinism test")
    b.add_argument("--quiet", action="store_true")
    sub.add_parser("verify", help="check data/raw against MANIFEST.json")
    sub.add_parser("freeze-predictions", help="copy data/processed/predictions.csv to thesis/predictions.csv once")
    st = sub.add_parser("site", help="offline: data/processed -> thesis/THESIS.md + site/ (static dashboard)")
    st.add_argument("--out", default=None, help="output root (default: repo root); used by the site test")
    st.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    if args.cmd == "refresh":
        refresh(args.only, args.skip)
    elif args.cmd == "build":
        from .pipeline import build
        build(out_root=args.out, quiet=args.quiet)
    elif args.cmd == "site":
        from .web.build import build_site
        build_site(out_root=args.out, quiet=args.quiet)
    elif args.cmd == "freeze-predictions":
        from . import paths
        from .predictions import freeze
        p, sha, created = freeze(paths.PROCESSED, paths.ROOT / "thesis")
        print(f"[predictions] {'froze' if created else 'already frozen, left unchanged:'} {p} sha256 {sha}")
    elif args.cmd == "verify":
        from .verify import verify_raw
        problems = verify_raw()
        for p in problems:
            print("  " + p)
        print("[verify] OK" if not problems else f"[verify] {len(problems)} problem(s)")
        sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
