"""Command line: `python -m nearthesis refresh|build|verify`.

refresh  re-downloads every keyless source into data/raw/ (+ MANIFEST.json). Network. ~1-1.5 h, rate limited.
build    rebuilds data/processed/ and reports/metrics_summary.md from data/raw/ only. Offline, seconds.
verify   checks data/raw/ against MANIFEST.json (sha256, row counts).
"""

from __future__ import annotations

import argparse
import sys
import time

STEPS = ["nearblocks", "defillama", "coingecko", "aurora", "onchain", "epochs", "activity", "treasury"]


def refresh(only: list[str] | None, skip: list[str] | None) -> None:
    from .fetch import aurora, coingecko, defillama, fastnear_activity, nearblocks, onchain_state, rpc_epochs
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
    args = ap.parse_args(argv)

    if args.cmd == "refresh":
        refresh(args.only, args.skip)
    elif args.cmd == "build":
        from .pipeline import build
        build(out_root=args.out, quiet=args.quiet)
    elif args.cmd == "verify":
        from .verify import verify_raw
        problems = verify_raw()
        for p in problems:
            print("  " + p)
        print("[verify] OK" if not problems else f"[verify] {len(problems)} problem(s)")
        sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
