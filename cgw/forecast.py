"""Forecasts: per-SKU discontinuation risk and street-price trigger crossings.

Both models are *deterministic functions of measured inputs* - nothing here is
sampled or invented. The weights/elasticities are hand-set priors (documented in
cgw/config.py and docs/model.md) and the module reports its own directional
validation (does risk move with SKU generation age?) so a reader can see how
much to trust the ordering.
"""
from __future__ import annotations

import datetime as dt
import json
import math
from typing import Any

from . import config, fuse

MODEL_VERSION = "cgw-0v1"

DRIVER_LABEL = {
    "age": "time in market",
    "discount": "street clearing below MSRP",
    "scarcity": "retail stock breadth",
    "memory_cost": "memory cost inflation",
    "allocation": "vendor die allocation shift",
    "signals": "supply/EOL chatter",
    "generation": "generation position",
}
WEIGHT_OF = {
    "age": config.PRIORS.w_age, "discount": config.PRIORS.w_discount,
    "scarcity": config.PRIORS.w_supply_scarcity, "memory_cost": config.PRIORS.w_memory_cost,
    "allocation": config.PRIORS.w_allocation, "signals": config.PRIORS.w_signals,
    "generation": config.PRIORS.w_generation,
}


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-max(-30.0, min(30.0, x))))


def discontinuation(features: list[dict]) -> list[dict]:
    out = []
    today = dt.date.today()
    for f in features:
        p = f.get("discontinuation_risk")
        if p is None:
            continue
        contrib = sorted(((k, round(WEIGHT_OF[k] * v, 3)) for k, v in f["pressures"].items()),
                         key=lambda kv: -kv[1])
        drivers = [{"feature": k, "label": DRIVER_LABEL[k], "contribution": c,
                    "value": f["pressures"][k]} for k, c in contrib if c > 0.05]
        q = max(0.25, (1 - p) * 5.0)
        lo_q, hi_q = round(q * 0.6, 2), round(q * 1.5, 2)
        out.append({
            "sku_model": f["sku_model"], "vendor": f["vendor"], "series": f["series"],
            "asof": f["asof"], "model_version": MODEL_VERSION,
            "discontinuation_risk": p,
            "risk_band": [round(max(0.01, p - 0.09), 3), round(min(0.99, p + 0.09), 3)],
            "expected_quarters_to_eol": round(q, 2),
            "eol_window_quarters": [lo_q, hi_q],
            "eol_window_dates": [
                (today + dt.timedelta(days=int(lo_q * 91))).isoformat(),
                (today + dt.timedelta(days=int(hi_q * 91))).isoformat(),
            ],
            "top_drivers": drivers[:4],
            "evidence": {
                "age_days": f["age_days"], "launch_date": f["launch_date"],
                "street_premium_pct": f["street_premium_pct"],
                "in_stock_share": (f["street"] or {}).get("in_stock_share"),
                "gaming_qoq_pct": (f["allocation"] or {}).get("gaming_qoq_pct"),
                "dc_qoq_pct": (f["allocation"] or {}).get("dc_qoq_pct"),
                "guidance_mid_pct": f["memory_cost"]["guidance_mid_pct"],
                "n_eol_signals": f["signals"]["n_eol"],
            },
            "sources": [u for u in [
                f["sku_source_url"], f["memory_cost"]["guidance_url"],
                (f["allocation"] or {}).get("release_url"),
                *(f["street"].get("source_urls", []) if f["street"] else []),
            ] if u],
        })
    return sorted(out, key=lambda x: -x["discontinuation_risk"])


def price_triggers(f: dict) -> list[dict]:
    """Projected street price path and trigger-crossing probabilities."""
    st = f.get("street") or {}
    msrp = f.get("msrp_usd")
    p0 = st.get("median")
    pri = config.PRIORS
    if not msrp or not p0:
        return [{"sku_model": f["sku_model"], "msrp_usd": msrp, "trigger_level": lvl,
                 "trigger_usd": round(msrp * lvl, 2) if msrp else None,
                 "status": "no_street_price",
                 "note": "no current retail price observed for this SKU",
                 "current_median_usd": None, "already_above": False,
                 "cross_prob_90d": None, "eta_days": None,
                 "sources": (st.get("source_urls") or []),
                 "model_version": MODEL_VERSION}
                for lvl in config.TRIGGER_LEVELS]

    horizon_q = pri.horizon_days / 91.0
    share = f["memory_cost"]["vram_cost_share_of_msrp"]
    if share is None:
        share = 0.16  # reference share when VRAM is unknown; flagged below
        share_known = False
    else:
        share = min(pri.memory_share_ceiling, max(pri.memory_share_floor, share))
        share_known = True
    guidance = (f["memory_cost"]["guidance_mid_pct"] or 0.0) / 100.0
    cost_delta = guidance * share * horizon_q            # fraction of MSRP added
    scarcity = 1 - (st.get("in_stock_share") or 0.0)
    uplift = pri.scarcity_uplift * scarcity * (1 - (f["discontinuation_risk"] or 0) * 0.4)
    change = pri.pass_through * cost_delta + uplift
    change = max(-pri.max_projected_change, min(pri.max_projected_change, change))
    projected = p0 * (1 + change)

    out = []
    for lvl in config.TRIGGER_LEVELS:
        trigger = msrp * lvl
        gap_pct = trigger / p0 - 1
        already = p0 >= trigger
        # soft crossing score: distance between projected and trigger, normalised
        score = _sigmoid((projected - trigger) / (0.04 * trigger))
        eta = None
        if projected > p0 and projected >= trigger:
            frac = (trigger - p0) / (projected - p0)
            eta = max(1, int(round(frac * pri.horizon_days)))
        out.append({
            "sku_model": f["sku_model"], "msrp_usd": msrp, "trigger_level": lvl,
            "trigger_usd": round(trigger, 2),
            "current_median_usd": round(p0, 2),
            "current_premium_pct": round(p0 / msrp - 1, 4),
            "already_above": bool(already),
            "gap_to_trigger_pct": round(gap_pct, 4),
            "projected_median_usd_90d": round(projected, 2),
            "projected_change_pct_90d": round(projected / p0 - 1, 4),
            "cross_prob_90d": round(score, 3),
            "eta_days": eta,
            "drivers": {
                "memory_cost_delta_pct_of_msrp": round(cost_delta * 100, 2),
                "memory_share_of_msrp": round(share, 3),
                "memory_share_measured": share_known,
                "scarcity_uplift_pct": round(uplift * 100, 2),
                "pass_through_assumed": pri.pass_through,
                "projected_change_capped": abs(pri.pass_through * cost_delta + uplift)
                                           > pri.max_projected_change,
                "n_merchants_priced": st.get("n_priced"),
                "price_basis": st.get("price_basis"),
                "basis_age_days": st.get("basis_age_days"),
            },
            "sources": [u for u in [
                *(st.get("source_urls") or []), f["memory_cost"]["guidance_url"]] if u],
            "model_version": MODEL_VERSION,
        })
    return out


def validation(features: list[dict]) -> dict:
    """Directional self-checks that can be computed from live data."""
    pairs = [(f["pressures"]["generation"], f["discontinuation_risk"]) for f in features
             if f.get("discontinuation_risk") is not None]
    rho = _spearman(pairs) if len(pairs) >= 4 else None
    gen_mean: dict[float, list[float]] = {}
    for f in features:
        g = f["pressures"]["generation"]
        gen_mean.setdefault(g, []).append(f["discontinuation_risk"] or 0)
    monotone = all(
        sum(gen_mean[a]) / len(gen_mean[a]) <= sum(gen_mean[b]) / len(gen_mean[b]) + 1e-9
        for a, b in zip(range(0, 2), range(1, 3)) if a in gen_mean and b in gen_mean)
    risky = [f for f in features if (f["street"] or {}).get("in_stock_share") == 0
             and (f["street"] or {}).get("n_merchants", 0) > 0]
    return {
        "checks": {
            "generation_vs_risk_spearman": round(rho, 3) if rho is not None else None,
            "risk_increases_with_generation_age": monotone,
            "skus_with_zero_stock": [f["sku_model"] for f in risky],
            "n_skus_scored": len(features),
        },
        "caveat": ("Priors are hand-set for v0; these checks only confirm the model orders "
                   "SKUs in the direction domain knowledge expects. No outcome-fitted "
                   "calibration exists yet - see docs/model.md for the roadmap."),
    }


def _spearman(pairs: list[tuple[float, float]]) -> float:
    def rank(vals: list[float]) -> list[float]:
        order = sorted(range(len(vals)), key=lambda i: vals[i])
        ranks = [0.0] * len(vals)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                ranks[order[k]] = avg
            i = j + 1
        return ranks
    xs = rank([p[0] for p in pairs])
    ys = rank([p[1] for p in pairs])
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
    return num / den if den else 0.0


def run_all(features: list[dict]) -> dict[str, Any]:
    disc = discontinuation(features)
    trig = []
    for f in features:
        trig.extend(price_triggers(f))
    return {"discontinuation": disc, "price_triggers": trig,
            "validation": validation(features),
            "asof": features[0]["asof"] if features else None,
            "model_version": MODEL_VERSION}


def persist(con, forecasts: dict) -> int:
    asof = forecasts.get("asof") or dt.date.today().isoformat()
    by_sku: dict[str, dict] = {}
    for row in forecasts["discontinuation"]:
        by_sku.setdefault(row["sku_model"], {"discontinuation": None, "price_triggers": []})
        by_sku[row["sku_model"]]["discontinuation"] = row
    for row in forecasts["price_triggers"]:
        by_sku.setdefault(row["sku_model"], {"discontinuation": None, "price_triggers": []})
        by_sku[row["sku_model"]]["price_triggers"].append(row)
    rows = [{"sku_model": k, "asof": asof, "model_version": MODEL_VERSION,
             "payload": json.dumps(v, default=str)} for k, v in by_sku.items()]
    con.executemany(
        "INSERT OR REPLACE INTO forecasts(sku_model, asof, model_version, payload) VALUES (?,?,?,?)",
        [(r["sku_model"], r["asof"], r["model_version"], r["payload"]) for r in rows])
    con.commit()
    return len(rows)


def load_latest(con) -> dict[str, Any]:
    row = con.execute("SELECT MAX(asof) AS a FROM forecasts").fetchone()
    asof = row["a"] if row else None
    if not asof:
        return {"discontinuation": [], "price_triggers": [], "validation": {}, "asof": None,
                "model_version": MODEL_VERSION}
    payloads = [json.loads(r["payload"]) for r in con.execute(
        "SELECT payload FROM forecasts WHERE asof=?", (asof,)).fetchall()]
    disc = sorted((p["discontinuation"] for p in payloads if p.get("discontinuation")),
                  key=lambda x: -x["discontinuation_risk"])
    trig = [t for p in payloads for t in p.get("price_triggers", [])]
    feats = fuse.load_latest_features(con, asof)
    return {"discontinuation": disc, "price_triggers": trig,
            "validation": validation(feats) if feats else {}, "asof": asof,
            "model_version": MODEL_VERSION}
