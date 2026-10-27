"""Command line entry point: python -m cgw.cli <command>."""
from __future__ import annotations

import argparse
import secrets
import sys
import time

from . import api, config, forecast as fc, fuse, pipeline, report, store


def cmd_collect(args) -> int:
    con = store.connect(args.db)
    stats = pipeline.collect_all(con, max_skus=args.max_skus, verbose=True)
    print(f"\ncollect done in {stats['duration_s']}s, {stats['fetches']} fetches")
    for k, v in stats["rows"].items():
        print(f"  rows {k}: {v}")
    if stats["errors"]:
        print(f"  {len(stats['errors'])} source errors:")
        for e in stats["errors"][:12]:
            print(f"    - {e['source']}: {e['error']}")
    return 0


def cmd_fuse(args) -> int:
    con = store.connect(args.db)
    feats = fuse.build_features(con)
    n = fuse.persist_features(con, feats)
    print(f"fused {n} SKUs (asof {feats[0]['asof'] if feats else 'n/a'})")
    for f in sorted(feats, key=lambda x: -(x["discontinuation_risk"] or 0))[:8]:
        st = f["street"] or {}
        print(f"  {f['sku_model']:<14} risk={f['discontinuation_risk']:.0%} "
              f"street={st.get('median')} stock={st.get('in_stock_share')}")
    return 0


def cmd_forecast(args) -> int:
    con = store.connect(args.db)
    feats = fuse.load_latest_features(con)
    if not feats:
        print("no features - run `fuse` first", file=sys.stderr)
        return 1
    out = fc.run_all(feats)
    n = fc.persist(con, out)
    print(f"forecasts for {n} SKUs; {len(out['price_triggers'])} trigger rows")
    print(f"  validation: {out['validation'].get('checks')}")
    return 0


def cmd_report(args) -> int:
    con = store.connect(args.db)
    ctx = report.build_context(con)
    paths = report.write_outputs(con, ctx)
    for k, v in paths.items():
        print(f"{k}: {v}")
    return 0


def cmd_all(args) -> int:
    rc = cmd_collect(args)
    if rc:
        return rc
    cmd_fuse(args)
    cmd_forecast(args)
    cmd_report(args)
    return 0


def cmd_keys(args) -> int:
    con = store.connect(args.db)
    if args.bootstrap:
        for tier in config.TIERS.values():
            key = api.DEFAULT_KEY if tier.key == "free" else f"{tier.key}-{secrets.token_hex(8)}"
            con.execute("INSERT OR REPLACE INTO api_keys(key,label,tier,created_at,active)"
                        " VALUES (?,?,?,?,1)", (key, tier.name + " demo", tier.key, time.time()))
        con.commit()
    rows = con.execute("SELECT key,label,tier,active FROM api_keys").fetchall()
    if not rows:
        print("no keys yet - run `cgw keys --bootstrap`")
    for r in rows:
        t = config.TIERS.get(r["tier"])
        print(f"  {r['key']:<28} {r['tier']:<5} {r['label']:<16} "
              f"{t.requests_per_day if t else '?'} req/day")
    return 0


def cmd_serve(args) -> int:
    con = store.connect(args.db)
    httpd = api.serve(con, args.host, args.port)
    print(f"serving on http://{args.host}:{args.port}  (Ctrl-C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cgw", description=__doc__)
    p.add_argument("--db", default=None, help=f"sqlite path (default {config.DB_PATH})")
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser("collect", help="fetch all sources into the database")
    c.add_argument("--max-skus", type=int, default=None, help="limit SKU pages (smoke runs)")
    c.set_defaults(func=cmd_collect)

    sub.add_parser("fuse", help="build per-SKU features").set_defaults(func=cmd_fuse)
    sub.add_parser("forecast", help="run the forecast models").set_defaults(func=cmd_forecast)
    sub.add_parser("report", help="write newsletter + CSV/JSON exports").set_defaults(func=cmd_report)
    a = sub.add_parser("all", help="collect -> fuse -> forecast -> report")
    a.add_argument("--max-skus", type=int, default=None)
    a.set_defaults(func=cmd_all)

    k = sub.add_parser("keys", help="list/provision API keys")
    k.add_argument("--bootstrap", action="store_true", help="create demo keys per tier")
    k.set_defaults(func=cmd_keys)

    s = sub.add_parser("serve", help="run the JSON API")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8787)
    s.set_defaults(func=cmd_serve)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
