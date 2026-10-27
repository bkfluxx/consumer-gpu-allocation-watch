"""Outputs: newsletter (Markdown + HTML), CSV/JSON exports for the API tier."""
from __future__ import annotations

import csv
import html
import io
import json
import os
import re
import time
from typing import Any

from . import config, forecast as fc, fuse, pipeline


def _pct(x: float | None, digits: int = 1) -> str:
    if x is None:
        return "n/a"
    return f"{x * 100:+.{digits}f}%"


def _num_pct(x: float | None, digits: int = 1) -> str:
    """Percentage points already expressed as a number (+47 -> '+47.0%')."""
    if x is None:
        return "n/a"
    return f"{x:+.{digits}f}%"


def _money(x: float | None) -> str:
    return "n/a" if x is None else f"${x:,.0f}"


def _basis_mark(street: dict) -> str:
    """Flag prices that are not from currently in-stock listings."""
    if not street:
        return ""
    basis = street.get("price_basis")
    if basis == "in_stock_and_fresh":
        return ""
    if basis == "stale_or_out_of_stock_listings_only":
        return " †"
    return ""


def build_context(con) -> dict[str, Any]:
    feats = fuse.load_latest_features(con)
    return {
        "asof": feats[0]["asof"] if feats else None,
        "features": feats,
        "forecasts": fc.load_latest(con),
        "memory": fuse.latest_memory(con),
        "allocation": fuse.latest_allocation(con),
        "signals": fuse.latest_signals(con),
        "health": pipeline.source_health(con),
    }


def newsletter_markdown(ctx: dict[str, Any], top_n: int = 10) -> str:
    f = ctx["forecasts"]
    disc = f.get("discontinuation", [])[:top_n]
    trig = f.get("price_triggers", [])
    mem = ctx["memory"]
    alloc = ctx["allocation"]
    feats = {x["sku_model"]: x for x in ctx["features"]}
    L: list[str] = []
    L.append(f"# Consumer GPU Allocation Watch — {ctx['asof']}")
    L.append("")
    L.append("*Die allocation, memory contract prices, street prices and supply signals fused "
             "into per-SKU discontinuation and price-trigger forecasts. Every number below is "
             "derived from a dated public source; see the provenance footer.*")
    L.append("")

    # --- memory read
    g = mem.get("guidance")
    L.append("## Memory cost read")
    L.append("")
    if mem.get("gddr6_session_avg") is not None:
        L.append(f"- **GDDR6 8Gb spot**: ${mem['gddr6_session_avg']:.3f} per 8Gb device "
                 f"({mem.get('gddr6_change_pct'):+.2f}% on the session, TrendForce print dated "
                 f"{mem.get('gddr6_ts')}).")
    if g:
        L.append(f"- **{g['metric']} contract prices**: {g['low_pct']:+.0f}% to {g['high_pct']:+.0f}% "
                 f"({g['quote']}) — [{g['title']}]({g['url']}), {g['published']}.")
    if mem.get("guidance_mid_pct") is not None and g:
        L.append(f"- Working assumption baked into the price path: **{mem['guidance_mid_pct']:+.1f}%** "
                 f"component-cost pressure over the next quarter, passed through at "
                 f"{config.PRIORS.pass_through:.0%}.")
    L.append("")

    # --- allocation read
    L.append("## Die allocation read")
    L.append("")
    for vendor, a in sorted(alloc.items()):
        if a.get("gaming_musd") is None and a.get("dc_musd") is None:
            continue
        gp = a.get("gaming_period") or "n/a"
        L.append(f"- **{vendor.upper()} — latest quarter {a['period']}**")
        if a.get("gaming_musd") is not None:
            L.append(f"  - Gaming {_money(a['gaming_musd'])}M in {gp} "
                     f"(QoQ {_num_pct(a.get('gaming_qoq_pct'))}, YoY {_num_pct(a.get('gaming_yoy_pct'))}).")
        if a.get("dc_musd") is not None:
            L.append(f"  - Data Center {_money(a['dc_musd'])}M in {a.get('dc_period') or a['period']} "
                     f"(QoQ {_num_pct(a.get('dc_qoq_pct'))}, YoY {_num_pct(a.get('dc_yoy_pct'))}).")
        if a.get("edge_computing_musd") is not None:
            L.append(f"  - Edge Computing {_money(a['edge_computing_musd'])}M "
                     f"(new disclosure bucket in {a['period']}).")
        if a.get("allocation_shift") is not None:
            L.append(f"  - Allocation shift: {a['allocation_shift']:+.1f} pts "
                     f"({a.get('allocation_shift_basis')}) — positive means data-centre "
                     f"growth is outpacing consumer graphics.")
        if a.get("gaming_musd") is not None and a.get("gaming_period") != a.get("period"):
            gap = ", ".join(a.get("gaming_disclosure_gap_periods") or [])
            L.append(f"  - **Gaming is no longer broken out from {gap or a['period']}**; the "
                     f"latest Gaming datapoint is {gp}. The model keeps using it and flags it "
                     f"as a disclosure gap, not as current-quarter performance.")
        L.append(f"  - [Source]({a.get('release_url')})")
    L.append("")

    # --- discontinuation board
    L.append("## Discontinuation watchlist")
    L.append("")
    L.append("| SKU | Age (d) | Street vs MSRP | Stock breadth | Risk | EOL window | Top driver |")
    L.append("|---|---|---|---|---|---|---|")
    for d in disc:
        feat = feats.get(d["sku_model"], {})
        st = feat.get("street") or {}
        L.append("| {sku} | {age} | {prem} | {stock} | {risk:.0%} | {win} | {drv} |".format(
            sku=d["sku_model"],
            age=d["evidence"]["age_days"] or "n/a",
            prem=_pct(d["evidence"]["street_premium_pct"]) + _basis_mark(st),
            stock=(f"{st.get('in_stock_share', 0):.0%} of {st.get('n_merchants', 0)}"
                   if st.get("n_merchants") else "no listings"),
            risk=d["discontinuation_risk"],
            win=f"{d['eol_window_dates'][0]} → {d['eol_window_dates'][1]}",
            drv=(d["top_drivers"][0]["label"] if d["top_drivers"] else "—")))
    L.append("")

    # --- trigger alerts: one line per SKU, highest level crossed
    above = [t for t in trig if t.get("already_above")]
    crossings: dict[str, dict] = {}
    for t in above:
        cur = crossings.get(t["sku_model"])
        if cur is None or t["trigger_level"] > cur["trigger_level"]:
            crossings[t["sku_model"]] = t
    upcoming = sorted([t for t in trig if not t.get("already_above") and t.get("eta_days")],
                      key=lambda t: t["eta_days"])[:8]
    L.append("## Street-price triggers")
    L.append("")
    if crossings:
        L.append(f"**Above a trigger right now ({len(crossings)} SKUs)** — highest level crossed "
                 f"per SKU, median of currently in-stock retailer listings:")
        L.append("")
        for t in sorted(crossings.values(), key=lambda t: -t["current_premium_pct"]):
            feat = feats.get(t["sku_model"], {})
            mark = _basis_mark(feat.get("street") or {})
            L.append(f"- **{t['sku_model']}** {_money(t['current_median_usd'])}{mark} vs "
                     f"{_money(t['msrp_usd'])} MSRP ({_pct(t['current_premium_pct'])}), through the "
                     f"{t['trigger_level']:.2f}× trigger at {_money(t['trigger_usd'])}.")
        L.append("")
        L.append("† price is the latest listing basis but no currently in-stock listing was "
                 "observed, so treat it as a stale reference rather than a live street price.")
    else:
        L.append("*No SKU is currently above a trigger level.*")
    L.append("")
    if upcoming:
        L.append("**Nearest projected crossings (90-day horizon):**")
        L.append("")
        L.append("| SKU | Trigger | Now | Projected (90d) | Cross prob. | ETA (days) |")
        L.append("|---|---|---|---|---|---|")
        for t in upcoming:
            L.append(f"| {t['sku_model']} | {t['trigger_level']:.2f}× = {_money(t['trigger_usd'])} | "
                     f"{_money(t['current_median_usd'])} | {_money(t['projected_median_usd_90d'])} "
                     f"({_pct(t['projected_change_pct_90d'])}) | {t['cross_prob_90d']:.0%} | "
                     f"{t['eta_days']} |")
    L.append("")

    # --- signal digest
    sigs = [s for s in ctx["signals"]["all"] if s["kind"] in ("eol", "shortage")][:6]
    if sigs:
        L.append("## Supply signals")
        L.append("")
        for s in sigs:
            tag = s["kind"].upper()
            sku = f" — `{s['sku_model']}`" if s["sku_model"] else ""
            L.append(f"- **{tag}**{sku}: [{s['title']}]({s['link']}) ({s['subreddit']}, "
                     f"{s['published'] or 'undated'})")
        L.append("")

    # --- method + provenance
    v = f.get("validation", {})
    L.append("## Method and limits")
    L.append("")
    L.append(f"- Model `{f.get('model_version')}`, {len(feats)} SKUs scored, "
             f"{len(trig)} trigger rows. Priors are hand-set; inputs are measured.")
    if v.get("checks"):
        c = v["checks"]
        L.append(f"- Directional check: Spearman rho between generation age and risk = "
                 f"{c.get('generation_vs_risk_spearman')}; risk rises with generation age = "
                 f"{c.get('risk_increases_with_generation_age')}.")
        if c.get("skus_with_zero_stock"):
            L.append(f"- SKUs with listings but zero in-stock merchants: "
                     f"{', '.join(c['skus_with_zero_stock'])}.")
    L.append("- Not yet included: die-size/wafer-start counts, board-partner shipment data and "
             "paid memory contract prints. These are the highest-value paid inputs for v1.")
    L.append("- SKU prices are aggregated at *family* level (e.g. \"RTX 5060 Ti\" covers its 8 GB and "
             "16 GB variants), so a mixed-variant retail shelf widens the median; per-variant "
             "bucketing is next on the list.")
    L.append(f"- Projections use a hand-set pass-through of {config.PRIORS.pass_through:.0%} and a "
             f"scarcity uplift capped at {config.PRIORS.scarcity_uplift:.0%}; halving the uplift "
             f"halves the projected move. Rows where the ±{config.PRIORS.max_projected_change:.0%} "
             f"cap binds are flagged in the API payload (`projected_change_capped`).")
    L.append("")
    L.append("## Provenance")
    L.append("")
    L.append("| Source | Kind | Docs | Last fetch |")
    L.append("|---|---|---|---|")
    for h in ctx["health"]:
        L.append(f"| [{h['name']}]({h['url']}) | {h['kind']} | {h['ok_documents']}/{h['documents']} "
                 f"| {h['last_fetch']} |")
    L.append("")
    L.append(f"*Generated {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())} by "
             f"ConsumerGPU Allocation Watch. Quotes reproduced for attribution; "
             f"see each source's terms.*")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# markdown -> html (small, no dependency)
# ---------------------------------------------------------------------------
def markdown_to_html(md: str) -> str:
    lines = md.split("\n")
    out, in_table, in_list = [], False, False

    def inline(s: str) -> str:
        s = html.escape(s, quote=False)
        s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        s = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", s)
        return s

    def close_table():
        nonlocal in_table
        if in_table:
            out.append("</tbody></table>")
            in_table = False

    for ln in lines:
        if ln.startswith("|"):
            cells = [c.strip() for c in ln.strip("|").split("|")]
            if all(set(c) <= set("-: ") and c for c in cells):
                continue
            if not in_table:
                out.append('<table><thead><tr>' +
                           "".join(f"<th>{inline(c)}</th>" for c in cells) +
                           "</tr></thead><tbody>")
                in_table = True
            else:
                out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in cells) + "</tr>")
            continue
        close_table()
        if ln.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(ln[2:])}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        if ln.startswith("### "):
            out.append(f"<h3>{inline(ln[4:])}</h3>")
        elif ln.startswith("## "):
            out.append(f"<h2>{inline(ln[3:])}</h2>")
        elif ln.startswith("# "):
            out.append(f"<h1>{inline(ln[2:])}</h1>")
        elif ln.strip() == "":
            out.append("")
        else:
            out.append(f"<p>{inline(ln)}</p>")
    close_table()
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


HTML_SHELL = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
 body {{ margin:0 auto; max-width:820px; padding:32px 20px 64px;
        font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
        color:#14161a; background:#fbfbfc; }}
 h1 {{ font-size:28px; line-height:1.2; margin:0 0 8px; }}
 h2 {{ font-size:19px; margin:32px 0 8px; padding-bottom:6px; border-bottom:1px solid #e6e7eb; }}
 table {{ border-collapse:collapse; width:100%; margin:12px 0; font-size:14px; }}
 th, td {{ text-align:left; padding:7px 9px; border-bottom:1px solid #e6e7eb; }}
 th {{ background:#f2f3f6; font-weight:600; }}
 code {{ background:#f2f3f6; padding:1px 5px; border-radius:4px; font-size:13px; }}
 a {{ color:#0b5cd5; }}
 ul {{ padding-left:20px; }}
 em {{ color:#5c6270; }}
</style></head><body>
{body}
</body></html>
"""


def write_outputs(con, ctx: dict[str, Any]) -> dict[str, str]:
    os.makedirs(config.OUT_DIR, exist_ok=True)
    md = newsletter_markdown(ctx)
    paths = {"newsletter_md": os.path.join(config.OUT_DIR, f"newsletter_{ctx['asof']}.md"),
             "newsletter_html": os.path.join(config.OUT_DIR, f"newsletter_{ctx['asof']}.html")}
    with open(paths["newsletter_md"], "w", encoding="utf-8") as fh:
        fh.write(md)
    with open(paths["newsletter_html"], "w", encoding="utf-8") as fh:
        fh.write(HTML_SHELL.format(title=f"Consumer GPU Allocation Watch {ctx['asof']}",
                                   body=markdown_to_html(md)))

    # CSV: discontinuation board
    csv_path = os.path.join(config.OUT_DIR, f"discontinuation_{ctx['asof']}.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["sku_model", "vendor", "series", "age_days", "msrp_usd", "street_median_usd",
                    "street_premium_pct", "in_stock_share", "discontinuation_risk",
                    "risk_low", "risk_high", "eol_window_start", "eol_window_end",
                    "top_driver", "top_driver_value"])
        for d in ctx["forecasts"].get("discontinuation", []):
            feat = next((x for x in ctx["features"] if x["sku_model"] == d["sku_model"]), {})
            st = feat.get("street") or {}
            w.writerow([d["sku_model"], d["vendor"], d["series"], d["evidence"]["age_days"],
                        feat.get("msrp_usd"), st.get("median"), d["evidence"]["street_premium_pct"],
                        st.get("in_stock_share"), d["discontinuation_risk"], d["risk_band"][0],
                        d["risk_band"][1], d["eol_window_dates"][0], d["eol_window_dates"][1],
                        d["top_drivers"][0]["label"] if d["top_drivers"] else "",
                        d["top_drivers"][0]["value"] if d["top_drivers"] else ""])
    paths["discontinuation_csv"] = csv_path

    trig_path = os.path.join(config.OUT_DIR, f"price_triggers_{ctx['asof']}.csv")
    with open(trig_path, "w", newline="", encoding="utf-8") as fh:
        rows = ctx["forecasts"].get("price_triggers", [])
        if rows:
            keys: list[str] = []
            for r in rows:                      # rows differ: priced vs no-price SKUs
                for k in r:
                    if k not in keys:
                        keys.append(k)
            w = csv.DictWriter(fh, fieldnames=keys)
            w.writeheader()
            for r in rows:
                w.writerow({k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
                            for k, v in r.items()})
    paths["price_triggers_csv"] = trig_path

    json_path = os.path.join(config.OUT_DIR, f"forecasts_{ctx['asof']}.json")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump({"asof": ctx["asof"], "model_version": ctx["forecasts"].get("model_version"),
                   "discontinuation": ctx["forecasts"].get("discontinuation"),
                   "price_triggers": ctx["forecasts"].get("price_triggers"),
                   "validation": ctx["forecasts"].get("validation")}, fh, indent=2, default=str)
    paths["forecasts_json"] = json_path
    return paths
