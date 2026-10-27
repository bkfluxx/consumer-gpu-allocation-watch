"""JSON API (stdlib http.server - no framework dependency).

Auth: `X-API-Key` header, or `?key=`. Keys live in the `api_keys` table and are
mapped to a tier in cgw/config.py. Rate limits are enforced per key per day.
Endpoints mirror the newsletter sections so the same fusion feeds both products.
"""
from __future__ import annotations

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from . import config, forecast as fc, fuse, pipeline, store

DEFAULT_KEY = "demo-free-key"


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], int] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int) -> tuple[bool, int]:
        day = time.strftime("%Y-%m-%d")
        with self._lock:
            used = self._hits.get((key, day), 0)
            if used >= limit:
                return False, 0
            self._hits[(key, day)] = used + 1
            return True, limit - used - 1


LIMITER = RateLimiter()


def resolve_key(con, key: str | None) -> dict | None:
    if not key:
        return None
    row = con.execute("SELECT * FROM api_keys WHERE key=? AND active=1", (key,)).fetchone()
    if not row:
        return None
    tier = config.TIERS.get(row["tier"])
    if not tier:
        return None
    return {"key": row["key"], "label": row["label"], "tier": tier.key,
            "tier_name": tier.name, "endpoints": tier.endpoints,
            "requests_per_day": tier.requests_per_day}


def _filtered(rows: list[dict], q: dict) -> list[dict]:
    vendor = (q.get("vendor") or [None])[0]
    min_risk = float((q.get("min_risk") or [0])[0] or 0)
    limit = int((q.get("limit") or [50])[0] or 50)
    out = rows
    if vendor:
        out = [r for r in out if (r.get("vendor") or "").lower() == vendor.lower()]
    if min_risk:
        out = [r for r in out if (r.get("discontinuation_risk") or 0) >= min_risk]
    return out[:max(1, min(limit, 500))]


def build_payload(con, path: str, q: dict, caller: dict | None) -> tuple[int, dict]:
    ctx_asof_row = con.execute("SELECT MAX(asof) AS a FROM features").fetchone()
    asof = ctx_asof_row["a"] if ctx_asof_row else None
    base = {"asof": asof, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    if path in ("/v1/health", "/v1/health/"):
        return 200, {**base, "status": "ok", "db": config.DB_PATH,
                     "model_version": fc.MODEL_VERSION}

    if path in ("/v1/meta", "/v1/meta/"):
        return 200, {**base, "sources": pipeline.source_health(con),
                     "attribution_required": True,
                     "licenses": "See each source's terms; derived metrics only."}

    if path.startswith("/v1/memory/latest"):
        mem = fuse.latest_memory(con)
        return 200, {**base, "spot": [{"grade": f"{k}", **v} for k, v in mem["spot"].items()],
                     "guidance": mem["guides"][:5], "guidance_mid_pct": mem["guidance_mid_pct"],
                     "asof_print": mem.get("gddr6_ts")}

    if path.startswith("/v1/memory/history"):
        rows = [dict(r) for r in con.execute(
            "SELECT source_key, grade, unit, ts, session_avg, avg_change_pct, url"
            " FROM memory_spot ORDER BY ts DESC LIMIT 200").fetchall()]
        return 200, {**base, "history": rows, "n": len(rows)}

    if path.startswith("/v1/skus/summary"):
        feats = fuse.load_latest_features(con)
        out = [{"sku_model": f["sku_model"], "vendor": f["vendor"], "series": f["series"],
                "msrp_usd": f["msrp_usd"], "street_median_usd": (f["street"] or {}).get("median"),
                "street_premium_pct": f["street_premium_pct"],
                "discontinuation_risk": f["discontinuation_risk"],
                "in_stock_share": (f["street"] or {}).get("in_stock_share")} for f in feats]
        return 200, {**base, "skus": _filtered(out, q), "n": len(out)}

    if path.startswith("/v1/skus"):
        feats = fuse.load_latest_features(con)
        return 200, {**base, "skus": _filtered(feats, q), "n": len(feats)}

    if path.startswith("/v1/forecasts/discontinuation"):
        f = fc.load_latest(con)
        rows = _filtered(f["discontinuation"], q)
        return 200, {**base, "model_version": f["model_version"], "rows": rows,
                     "validation": f.get("validation"), "n": len(rows)}

    if path.startswith("/v1/forecasts/price-triggers"):
        f = fc.load_latest(con)
        rows = f["price_triggers"]
        vendor = (q.get("vendor") or [None])[0]
        only_crossed = (q.get("already_above") or ["false"])[0].lower() in ("1", "true", "yes")
        if vendor:
            rows = [r for r in rows if vendor.lower() in r["sku_model"].lower()
                    or vendor.lower() in ("nvidia", "amd")]
        if only_crossed:
            rows = [r for r in rows if r.get("already_above")]
        limit = int((q.get("limit") or [100])[0])
        return 200, {**base, "model_version": f["model_version"], "rows": rows[:limit],
                     "n": len(rows)}

    if path.startswith("/v1/allocation"):
        alloc = fuse.latest_allocation(con)
        return 200, {**base, "vendors": alloc}

    if path.startswith("/v1/signals"):
        s = fuse.latest_signals(con)
        kind = (q.get("kind") or [None])[0]
        limit = int((q.get("limit") or [50])[0])
        rows = s["all"]
        if kind:
            rows = [r for r in rows if r["kind"] == kind]
        return 200, {**base, "signals": rows[:limit], "n": len(rows)}

    return 404, {"error": "not_found", "path": path,
                 "hint": "see docs/api.md for the endpoint list"}


class Handler(BaseHTTPRequestHandler):
    con = None          # injected (kept for compatibility with direct handler use)
    server_version = "CGW/0.1"

    def _connection(self):
        """One SQLite connection per request thread.

        ThreadingHTTPServer dispatches each request on its own thread and a SQLite
        connection may not cross threads, so the server stashes the database *path*
        and each request opens (and closes) its own handle.
        """
        db_path = getattr(self.server, "db_path", None)
        return store.connect(db_path) if db_path else self.con

    def _send(self, code: int, payload: dict, extra: dict | None = None) -> None:
        body = json.dumps(payload, indent=2, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        q = parse_qs(u.query)
        con = self._connection()
        try:
            key = self.headers.get("X-API-Key") or (q.get("key") or [None])[0]
            caller = resolve_key(con, key)
            # /v1/meta and /v1/health stay open so monitors can reach them.
            if u.path.startswith("/v1/meta") or u.path.startswith("/v1/health"):
                code, payload = build_payload(con, u.path, q, caller)
                return self._send(code, payload)
            if not caller:
                return self._send(401, {"error": "unauthorized",
                                        "hint": "pass X-API-Key (see docs/api.md; "
                                                "'demo-free-key' is provisioned by "
                                                "`cgw keys --bootstrap`)"})
            ok, remaining = LIMITER.allow(caller["key"], caller["requests_per_day"])
            if not ok:
                return self._send(429, {"error": "rate_limited",
                                        "requests_per_day": caller["requests_per_day"]})
            endpoint = u.path.strip("/").replace("v1/", "", 1)
            allowed = caller["endpoints"]
            if "*" not in allowed and not any(endpoint.startswith(a) for a in allowed):
                return self._send(403, {"error": "tier_does_not_include_endpoint",
                                        "tier": caller["tier"], "endpoint": endpoint,
                                        "included": list(allowed)})
            code, payload = build_payload(con, u.path, q, caller)
            payload.setdefault("caller", {"tier": caller["tier"], "label": caller["label"]})
            self._send(code, payload, {"X-RateLimit-Remaining": str(remaining)})
        finally:
            if getattr(self.server, "db_path", None) and con is not self.con:
                con.close()

    def log_message(self, fmt, *args):  # keep the console quiet-ish
        if self.server.verbose:  # type: ignore[attr-defined]
            super().log_message(fmt, *args)


def serve(con, host: str = "127.0.0.1", port: int = 8787,
          verbose: bool = True) -> ThreadingHTTPServer:
    Handler.con = con
    httpd = ThreadingHTTPServer((host, port), Handler)
    row = con.execute("PRAGMA database_list").fetchone()
    httpd.db_path = row[2] if row and row[2] else None   # type: ignore[attr-defined]
    httpd.verbose = verbose  # type: ignore[attr-defined]
    return httpd
