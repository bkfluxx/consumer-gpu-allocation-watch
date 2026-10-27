"""Pretty-print the interesting parts of a CGW API response (used by the smoke test).

Usage: python3 tools/print_api.py <kind> < json-file
"""
from __future__ import annotations

import json
import sys


def main() -> int:
    kind = sys.argv[1] if len(sys.argv) > 1 else "summary"
    d = json.load(sys.stdin)
    if kind == "health":
        print(json.dumps({k: d[k] for k in ("status", "asof", "model_version")}, indent=2))
    elif kind == "meta":
        print(f"sources: {len(d['sources'])}")
        for s in d["sources"][:3]:
            print(f"  {s['name']:<45} {s['kind']:<10} docs={s['ok_documents']}/{s['documents']}"
                  f" last={s['last_fetch']}")
    elif kind == "error":
        print(json.dumps(d, indent=2)[:400])
    elif kind == "discontinuation":
        print(f"asof={d['asof']} model={d['model_version']}")
        for r in d["rows"]:
            drivers = [x["label"] for x in r["top_drivers"][:2]]
            print(f"  {r['sku_model']:<12} risk={r['discontinuation_risk']:.0%} "
                  f"band={r['risk_band']} eol={r['eol_window_dates']} drivers={drivers}")
    elif kind == "triggers":
        for r in d["rows"]:
            print(f"  {r['sku_model']:<12} {r['trigger_level']}x={r['trigger_usd']:<9} "
                  f"now={r['current_median_usd']:<9} proj90={r['projected_median_usd_90d']:<9} "
                  f"cross_prob={r['cross_prob_90d']}")
    elif kind == "allocation":
        for vendor, a in d["vendors"].items():
            print(f"  {vendor}: period={a['period']} gaming={a['gaming_musd']} "
                  f"(from {a['gaming_period']}) dc={a['dc_musd']} "
                  f"shift={a['allocation_shift']} ({a['allocation_shift_basis']}) "
                  f"gap={a['gaming_disclosure_gap_periods']}")
    elif kind == "signals":
        for s in d["signals"]:
            print(f"  - [{s['kind']}] {s['title'][:100]}")
            print(f"      {s['link'][:95]}")
    elif kind == "memory":
        print(f"guidance_mid_pct={d['guidance_mid_pct']} spot_grades="
              f"{[s['grade'] + ' ' + str(s.get('unit')) for s in d['spot']]}")
        for g in d["guidance"][:2]:
            print(f"  {g['metric']}: {g['low_pct']:+.0f}%..{g['high_pct']:+.0f}% ({g['published']})")
    else:
        print(json.dumps(d, indent=2)[:600])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
