"""Collection pipeline: fetch every source, persist raw bytes + typed rows."""
from __future__ import annotations

import time
import uuid
from typing import Any

from . import config, store
from .http import Fetcher
from .sources import allocation, memory, signals, skus, street


def collect_all(con, fetcher: Fetcher | None = None, verbose: bool = True,
                max_skus: int | None = None) -> dict[str, Any]:
    fetcher = fetcher or Fetcher(min_interval=0.8)
    run_id = uuid.uuid4().hex[:12]
    started = time.time()

    def store_raw(key: str, res) -> None:
        store.save_raw(con, key, res)

    stats: dict[str, Any] = {"run_id": run_id, "started_at": started,
                             "fetches": 0, "rows": {}, "errors": []}
    log = (lambda *a: print(*a)) if verbose else (lambda *a: None)

    log("[collect] memory pricing ...")
    mem = memory.collect(fetcher, store_raw=store_raw)
    n = store.upsert_many(
        con, "memory_spot",
        ["source_key", "grade", "unit", "ts", "weekly_high", "weekly_low",
         "session_high", "session_low", "session_avg", "avg_change_pct", "fetched_at", "url"],
        [{**r, "fetched_at": time.time()} for r in mem["spot"]],
        unique_cols=["source_key", "grade", "ts"])
    stats["rows"]["memory_spot"] = n
    g = store.upsert_many(
        con, "memory_guide",
        ["source_key", "url", "published", "title", "metric", "low_pct", "high_pct",
         "quote", "fetched_at"],
        [{**r, "fetched_at": time.time()} for r in mem["guides"]])
    stats["rows"]["memory_guide"] = g
    stats["errors"] += mem["errors"]
    log(f"  spot rows={n} guidance rows={g} articles={len(mem['articles'])}")

    log("[collect] vendor allocation (NVIDIA / AMD) ...")
    alloc = allocation.collect(fetcher, store_raw=store_raw)
    a = store.upsert_many(
        con, "segment_fin",
        ["vendor", "period_label", "segment", "revenue_musd", "qoq_pct", "yoy_pct",
         "published", "release_url", "quote", "fetched_at"],
        [{**r, "fetched_at": time.time()} for r in alloc["segments"]])
    stats["rows"]["segment_fin"] = a
    stats["errors"] += alloc["errors"]
    stats["warnings"] = alloc.get("warnings", [])
    log(f"  segment rows={a}")

    log("[collect] SKU universe ...")
    sk = skus.collect(fetcher, store_raw=store_raw)
    s = store.upsert_many(
        con, "sku",
        ["model", "vendor", "series", "launch_date", "msrp_usd", "tdp_w", "memory_gen",
         "memory_gb", "bus_width", "source_url", "updated_at"],
        [{**r, "updated_at": time.time()} for r in sk["skus"]], unique_cols=["model"])
    stats["rows"]["sku"] = s
    stats["errors"] += sk["errors"]
    log(f"  sku rows={s}")

    log("[collect] street prices ...")
    st = street.collect(fetcher, store_raw=store_raw, max_skus=max_skus)
    n = store.upsert_many(
        con, "street_obs",
        ["sku_model", "merchant", "product_name", "price_usd", "stock", "observed_at",
         "observed_ts", "source_url"],
        [{k: v for k, v in r.items() if k != "listing_vram_gb"} for r in st["observations"]],
        unique_cols=["sku_model", "merchant", "observed_at", "price_usd"])
    stats["rows"]["street_obs"] = n
    stats["errors"] += st["errors"]
    log(f"  street rows={n} pages={len(st['pages'])}")
    # fill VRAM from listing titles when Wikipedia did not carry it
    for model, gb in st.get("sku_vram", {}).items():
        con.execute("UPDATE sku SET memory_gb=COALESCE(memory_gb, ?) WHERE model=?", (gb, model))
    con.commit()

    log("[collect] supply signals ...")
    sg = signals.collect(fetcher, store_raw=store_raw)
    n = store.upsert_many(
        con, "signals",
        ["subreddit", "title", "link", "published", "kind", "matched", "sku_model",
         "source_url", "fetched_at"],
        [{**r, "fetched_at": time.time()} for r in sg["signals"]])
    stats["rows"]["signals"] = n
    stats["errors"] += sg["errors"]
    log(f"  signal rows={n}")

    stats["fetches"] = len(fetcher.calls)
    stats["finished_at"] = time.time()
    stats["duration_s"] = round(stats["finished_at"] - started, 1)
    store.record_run(con, run_id, "collect", stats)
    return stats


def source_health(con) -> list[dict]:
    """Per-source freshness from the raw audit trail (feeds /v1/meta)."""
    rows = con.execute("""
        SELECT source_key, COUNT(*) AS docs, MAX(fetched_at) AS last_fetch,
               SUM(CASE WHEN status BETWEEN 200 AND 299 THEN 1 ELSE 0 END) AS ok_docs,
               SUM(CASE WHEN status IS NULL OR status NOT BETWEEN 200 AND 299 THEN 1 ELSE 0 END)
                   AS failed
        FROM raw_documents GROUP BY source_key ORDER BY source_key
    """).fetchall()
    out = []
    for r in rows:
        spec = config.SOURCES.get(r["source_key"])
        out.append({
            "source_key": r["source_key"],
            "name": spec.name if spec else r["source_key"],
            "kind": spec.kind if spec else "",
            "documents": r["docs"],
            "ok_documents": r["ok_docs"],
            "failed_documents": r["failed"],
            "last_fetch": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(r["last_fetch"]))
            if r["last_fetch"] else None,
            "age_hours": round((time.time() - r["last_fetch"]) / 3600, 1) if r["last_fetch"] else None,
            "refresh_target": spec.refresh if spec else "",
            "license_note": spec.license_note if spec else "",
            "url": spec.url if spec else "",
        })
    return out
