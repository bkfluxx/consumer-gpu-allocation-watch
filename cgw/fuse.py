"""Feature fusion: one row per SKU combining every source's latest reading.

Every feature carries the source URL(s) it was derived from, so the API and the
newsletter can show provenance next to the number.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import re
import statistics
import time
from typing import Any, Optional

from . import config

GEN_INDEX = {"RTX 50": 0, "RTX 40": 1, "RTX 30": 2, "RX 9000": 0, "RX 7000": 1, "RX 6000": 2}


def _parse_date(txt: str) -> Optional[dt.date]:
    if not txt:
        return None
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d", "%B %Y", "%b %Y",
                "%b %d %y - %I:%M %p", "%b %d %y"):
        try:
            return dt.datetime.strptime(txt.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-max(-30.0, min(30.0, x))))


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


# ---------------------------------------------------------------------------
# source readers
# ---------------------------------------------------------------------------
def _street_time(txt: str) -> Optional[dt.datetime]:
    """Tracker timestamps look like 'Oct 13 26 - 6:50 PM' (display fallback)."""
    if not txt:
        return None
    for fmt in ("%b %d %y - %I:%M %p", "%b %d %Y - %I:%M %p", "%b %d %y"):
        try:
            return dt.datetime.strptime(txt.strip(), fmt)
        except ValueError:
            continue
    return None


def _obs_dt(obs: dict) -> Optional[dt.datetime]:
    """Observation time from the stored epoch, falling back to the display string."""
    ts = obs.get("observed_ts")
    if ts:
        return dt.datetime.fromtimestamp(ts)
    return _street_time(obs.get("observed_at") or "")


def _obs_key(obs: dict) -> tuple[float, str]:
    dtv = _obs_dt(obs)
    return (dtv.timestamp() if dtv else float("-inf"), obs.get("observed_at") or "")


def latest_street(con, fresh_days: int = 14) -> dict[str, dict]:
    """Latest price per (sku, merchant), then per-SKU aggregates.

    "Latest" is picked on the parsed `observed_ts`, not the display string: sorting
    the strings puts "Sep 20 26" after "Oct 13 26". The median is then taken over
    *current* listings - in-stock observations first, and anything older than
    `fresh_days` is kept only as a fallback basis (flagged), because a stale
    out-of-stock price is not a street price.
    """
    rows = con.execute("SELECT * FROM street_obs").fetchall()
    latest: dict[tuple[str, str], dict] = {}
    for r in rows:
        d = dict(r)
        key = (d["sku_model"], d["merchant"])
        cur = latest.get(key)
        if cur is None or _obs_key(d) >= _obs_key(cur):
            latest[key] = d
    per_sku: dict[str, list[dict]] = {}
    for (model, _merchant), d in latest.items():
        per_sku.setdefault(model, []).append(d)

    cutoff = dt.datetime.now() - dt.timedelta(days=fresh_days)
    out: dict[str, dict] = {}
    for model, obs in per_sku.items():
        priced = [o for o in obs if o["price_usd"] and o["price_usd"] > 20]
        in_stock = [o for o in obs if (o["stock"] or "").startswith("IN_STOCK")]
        fresh_live = [o for o in priced
                      if (o["stock"] or "").startswith("IN_STOCK")
                      and ((_obs_dt(o) or dt.datetime.min) >= cutoff)]
        if fresh_live:
            basis, basis_note = fresh_live, "in_stock_and_fresh"
        elif priced:
            basis, basis_note = priced, "stale_or_out_of_stock_listings_only"
        else:
            # stable schema for API consumers: the keys exist and are null
            out[model] = {"n_merchants": len(obs), "n_priced": 0, "n_basis": 0,
                          "in_stock_share": 0.0, "median": None, "min": None, "max": None,
                          "spread_pct": None, "merchants": [], "merchants_in_stock": [],
                          "observed_at": max((o["observed_at"] or "" for o in obs)) or None,
                          "source_urls": sorted({o["source_url"] for o in obs if o["source_url"]}),
                          "price_basis": "none"}
            continue
        prices = [o["price_usd"] for o in basis]
        med = statistics.median(prices)
        newest = max((o["observed_at"] or "" for o in obs))
        newest_ts = _street_time(newest)
        out[model] = {
            "n_merchants": len(obs),
            "n_priced": len(priced),
            "n_basis": len(basis),
            "price_basis": basis_note,
            "basis_age_days": round((dt.datetime.now() - newest_ts).days, 1) if newest_ts else None,
            "in_stock_share": round(len(in_stock) / max(1, len(obs)), 3),
            "median": round(med, 2),
            "min": round(min(prices), 2),
            "max": round(max(prices), 2),
            "spread_pct": round((max(prices) - min(prices)) / med, 3) if med else None,
            "merchants": sorted({o["merchant"] for o in obs}),
            "merchants_in_stock": sorted({o["merchant"] for o in in_stock}),
            "observed_at": newest,
            "source_urls": sorted({o["source_url"] for o in obs if o["source_url"]}),
            "_obs": [{"merchant": o["merchant"], "price": o["price_usd"], "stock": o["stock"],
                      "product": o["product_name"], "observed_at": o["observed_at"]}
                     for o in sorted(obs, key=lambda x: (x["price_usd"] or 1e9))],
        }
    return out


def latest_memory(con) -> dict[str, Any]:
    spot = {}
    for r in con.execute("""
        SELECT * FROM memory_spot m WHERE fetched_at > ?
        ORDER BY fetched_at DESC""", (time.time() - 30 * 86400,)).fetchall():
        key = f"{r['grade']} {r['unit']}"
        spot.setdefault(key, dict(r))
    guides = [dict(r) for r in con.execute("""
        SELECT * FROM memory_guide WHERE fetched_at > ?
        ORDER BY published DESC""", (time.time() - 45 * 86400,)).fetchall()]
    # guidance midpoint for conventional DRAM contract prices (the closest free
    # proxy for what a board partner pays for GDDR next quarter)
    dram = [g for g in guides if "dram" in g["metric"].lower() and "mobile" not in g["metric"].lower()]
    chosen = dram[0] if dram else (guides[0] if guides else None)
    mid = None
    if chosen:
        mid = round((chosen["low_pct"] + chosen["high_pct"]) / 2, 2)
    gddr6 = None
    for k, v in spot.items():
        if k.upper().startswith("GDDR6"):
            gddr6 = v
            break
    return {"spot": spot, "guides": guides, "guidance": chosen,
            "guidance_mid_pct": mid,
            "gddr6_session_avg": gddr6["session_avg"] if gddr6 else None,
            "gddr6_change_pct": gddr6["avg_change_pct"] if gddr6 else None,
            "gddr6_ts": gddr6["ts"] if gddr6 else None,
            "gddr6_url": gddr6["url"] if gddr6 else None}


def latest_allocation(con) -> dict[str, dict]:
    """Latest segment read per vendor, with a disclosure-gap check.

    Vendors sometimes stop breaking out the Gaming line (NVIDIA from fiscal 2027),
    so the latest Gaming datapoint is taken from the most recent period that still
    has one and the gap is surfaced instead of being papered over.
    """
    import re
    out: dict[str, dict] = {}
    rows = con.execute("SELECT * FROM segment_fin").fetchall()
    by_vendor: dict[str, dict[str, list[dict]]] = {}
    for r in rows:
        by_vendor.setdefault(r["vendor"], {}).setdefault(r["period_label"] or "?", []).append(dict(r))

    def period_key(label: str) -> tuple[int, int]:
        m = re.match(r"Q(\d)\s+(?:FY)?(\d{4})", label or "")
        return (int(m.group(2)), int(m.group(1))) if m else (0, 0)

    for vendor, periods in by_vendor.items():
        ordered = sorted(periods.items(), key=lambda kv: period_key(kv[0]), reverse=True)
        latest_label, segs = ordered[0]

        def seg_of(name: str, items: list[dict]) -> dict | None:
            return next((s for s in items if s["segment"].lower() == name.lower()), None)

        gaming = seg_of("Gaming", segs)
        gaming_period = latest_label if gaming else None
        gap_periods: list[str] = []
        if not gaming:
            for label, items in ordered[1:]:
                g = seg_of("Gaming", items)
                if g:
                    gaming, gaming_period = g, label
                    break
                gap_periods.append(label)
        dc = seg_of("Data Center", segs) or next(
            (seg_of("Data Center", items) for _, items in ordered[1:] if seg_of("Data Center", items)),
            None)
        edge = seg_of("Edge Computing", segs)

        # Trend basis: prefer QoQ; fall back to YoY and say so, because the
        # direction of the allocation shift is what the model consumes.
        def trend(seg: dict | None) -> tuple[float | None, str]:
            if not seg:
                return None, "none"
            if seg.get("qoq_pct") is not None:
                return seg["qoq_pct"], "qoq"
            if seg.get("yoy_pct") is not None:
                return seg["yoy_pct"], "yoy"
            return None, "none"

        g_trend, g_basis = trend(gaming)
        dc_trend, dc_basis = trend(dc)
        out[vendor] = {
            "period": latest_label,
            "periods_available": [k for k, _ in ordered],
            "gaming_musd": gaming["revenue_musd"] if gaming else None,
            "gaming_period": gaming_period,
            "gaming_qoq_pct": gaming["qoq_pct"] if gaming else None,
            "gaming_yoy_pct": gaming["yoy_pct"] if gaming else None,
            "gaming_trend_pct": g_trend,
            "gaming_trend_basis": g_basis,
            "gaming_disclosure_gap_periods": gap_periods,
            "dc_musd": dc["revenue_musd"] if dc else None,
            "dc_period": next((lbl for lbl, items in ordered if seg_of("Data Center", items)), None),
            "dc_qoq_pct": dc["qoq_pct"] if dc else None,
            "dc_yoy_pct": dc["yoy_pct"] if dc else None,
            "dc_trend_pct": dc_trend,
            "edge_computing_musd": edge["revenue_musd"] if edge else None,
            "allocation_shift": (round(dc_trend - g_trend, 2)
                                 if dc_trend is not None and g_trend is not None else None),
            "allocation_shift_basis": f"dc_{dc_basis}_minus_gaming_{g_basis}",
            "release_url": (gaming or dc or {}).get("release_url") if (gaming or dc) else None,
            "quote": (gaming or {}).get("quote") if gaming else None,
        }
    return out


def latest_signals(con, window_days: int = 30) -> dict[str, Any]:
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - window_days * 86400))
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM signals ORDER BY published DESC").fetchall()]
    per_sku: dict[str, list[dict]] = {}
    per_series: dict[str, list[dict]] = {}
    for r in rows:
        if r["sku_model"]:
            per_sku.setdefault(r["sku_model"], []).append(r)
        for _vendor, series, pat in config.SERIES_PATTERNS:
            if re.search(pat, r["title"] or "", re.I):
                per_series.setdefault(series, []).append(r)
                break
    return {"all": rows, "per_sku": per_sku, "per_series": per_series,
            "window_days": window_days, "cutoff": cutoff,
            "n_eol": sum(1 for r in rows if r["kind"] == "eol"),
            "n_shortage": sum(1 for r in rows if r["kind"] == "shortage")}


# ---------------------------------------------------------------------------
# fusion
# ---------------------------------------------------------------------------
def build_features(con) -> list[dict]:
    sku_rows = [dict(r) for r in con.execute("SELECT * FROM sku").fetchall()]
    street = latest_street(con)
    mem = latest_memory(con)
    alloc = latest_allocation(con)
    sig = latest_signals(con)
    today = dt.date.today()
    priors = config.PRIORS

    gddr6_avg = mem["gddr6_session_avg"]
    gddr6_per_gb = (gddr6_avg * 8 / 8) if gddr6_avg else None  # 8Gb part -> $/GB

    out: list[dict] = []

    # Launch dates are missing for a few rows (the wiki tables use rowspans, so a
    # row can lose its date cell). Fall back to the median launch date of the
    # series and mark the age as estimated.
    series_launch: dict[str, list[dt.date]] = {}
    for s in sku_rows:
        d = _parse_date(s["launch_date"] or "")
        if d:
            series_launch.setdefault(s["series"] or "?", []).append(d)
    series_median_launch = {k: sorted(v)[len(v) // 2] for k, v in series_launch.items() if v}

    for s in sku_rows:
        model = s["model"]
        launch = _parse_date(s["launch_date"] or "")
        age_estimated = False
        if launch is None:
            launch = series_median_launch.get(s["series"] or "?")
            age_estimated = launch is not None
        age_days = (today - launch).days if launch else None
        st = street.get(model)
        msrp = s["msrp_usd"]
        vendor = s["vendor"]
        gen = GEN_INDEX.get(s["series"] or "", 2)

        premium = spread = None
        if st and st.get("median") and msrp:
            premium = round(st["median"] / msrp - 1, 4)
            spread = st.get("spread_pct")

        # --- memory cost pass-through share of the board BOM
        gen_mult = config.MEMORY_GEN_MULT.get((s["memory_gen"] or config.DEFAULT_GEN).upper(), 1.0)
        est_per_gb = gddr6_per_gb * gen_mult if gddr6_per_gb else None
        vram_gb = s["memory_gb"]
        vram_cost = round(est_per_gb * vram_gb, 2) if (est_per_gb and vram_gb) else None
        vram_share = round(vram_cost / msrp, 4) if (vram_cost and msrp) else None

        # --- pressures (0..1)
        f_age = _sigmoid(((age_days or 0) - priors.age_mid_days) / priors.age_scale_days) if age_days else 0.0
        f_discount = _clip((-premium - abs(priors.clearance_discount)) / 0.20) if premium is not None else 0.0
        f_scarcity = _clip(1 - (st["in_stock_share"] if st else 0.0))
        mem_share_ref = 0.16
        f_memory = _clip(((mem["guidance_mid_pct"] or 0) * ((vram_share or mem_share_ref) / mem_share_ref)) / 15.0)
        a = alloc.get(vendor) or {}
        gaming_trend = a.get("gaming_trend_pct")
        f_alloc = _clip(-(gaming_trend or 0) / 25.0)
        sk_sigs = sig["per_sku"].get(model, [])
        ser_sigs = sig["per_series"].get(s["series"] or "", [])
        n_eol = sum(1 for x in sk_sigs if x["kind"] == "eol")
        n_short = sum(1 for x in sk_sigs if x["kind"] == "shortage")
        n_eol_series = sum(1 for x in ser_sigs if x["kind"] == "eol")
        n_short_series = sum(1 for x in ser_sigs if x["kind"] == "shortage")
        f_sig = _clip((1.0 * n_eol + 0.4 * n_short + 0.5 * n_eol_series + 0.2 * n_short_series) / 2.0)
        f_gen = _clip(gen / 2.0)

        z = (priors.bias
             + priors.w_age * f_age
             + priors.w_discount * f_discount
             + priors.w_supply_scarcity * f_scarcity
             + priors.w_memory_cost * f_memory
             + priors.w_allocation * f_alloc
             + priors.w_signals * f_sig
             + priors.w_generation * f_gen)
        risk = _sigmoid(z)

        out.append({
            "sku_model": model, "vendor": vendor, "series": s["series"],
            "launch_date": s["launch_date"] or (launch.isoformat() if launch else None),
            "age_days": age_days, "age_estimated": age_estimated,
            "msrp_usd": msrp, "tdp_w": s["tdp_w"],
            "memory_gen": s["memory_gen"] or None, "memory_gb": vram_gb,
            "sku_source_url": s["source_url"],
            "street": st or {"n_priced": 0},
            "street_premium_pct": premium,
            "memory_cost": {
                "gddr6_usd_per_8gb": gddr6_avg,
                "gddr6_weekly_change_pct": mem["gddr6_change_pct"],
                "gddr6_ts": mem["gddr6_ts"],
                "guidance_mid_pct": mem["guidance_mid_pct"],
                "guidance_quote": (mem["guidance"] or {}).get("quote"),
                "guidance_url": (mem["guidance"] or {}).get("url"),
                "gen_multiplier": gen_mult,
                "est_usd_per_gb": round(est_per_gb, 2) if est_per_gb else None,
                "est_vram_cost_usd": vram_cost,
                "vram_cost_share_of_msrp": vram_share,
            },
            "allocation": a,
            "signals": {"n_signals": len(sk_sigs), "n_eol": n_eol, "n_shortage": n_short,
                        "n_series_signals": len(ser_sigs), "n_eol_series": n_eol_series,
                        "n_restock": sum(1 for x in sk_sigs if x["kind"] == "restock"),
                        "latest": (sk_sigs or ser_sigs)[0]["title"] if (sk_sigs or ser_sigs) else None,
                        "latest_link": (sk_sigs or ser_sigs)[0]["link"] if (sk_sigs or ser_sigs) else None},
            "pressures": {"age": round(f_age, 3), "discount": round(f_discount, 3),
                          "scarcity": round(f_scarcity, 3), "memory_cost": round(f_memory, 3),
                          "allocation": round(f_alloc, 3), "signals": round(f_sig, 3),
                          "generation": round(f_gen, 3)},
            "risk_raw_logit": round(z, 3),
            "discontinuation_risk": round(risk, 4),
            "asof": dt.date.today().isoformat(),
            "generated_at": time.time(),
        })
    return out


def persist_features(con, features: list[dict]) -> int:
    rows = [{"sku_model": f["sku_model"], "asof": f["asof"],
             "payload": json.dumps(f, default=str)} for f in features]
    return _upsert_payloads(con, "features", rows)


def _upsert_payloads(con, table: str, rows: list[dict]) -> int:
    con.executemany(f"INSERT OR REPLACE INTO {table}(sku_model, asof, payload) VALUES (?,?,?)",
                    [(r["sku_model"], r["asof"], r["payload"]) for r in rows])
    con.commit()
    return len(rows)


def load_latest_features(con, asof: str | None = None) -> list[dict]:
    if asof is None:
        row = con.execute("SELECT MAX(asof) AS a FROM features").fetchone()
        asof = row["a"] if row else None
    if not asof:
        return []
    return [json.loads(r["payload"]) for r in con.execute(
        "SELECT payload FROM features WHERE asof=? ORDER BY sku_model", (asof,)).fetchall()]
