"""SQLite persistence: immutable raw audit trail + typed observation tables."""
from __future__ import annotations

import json
import os
import sqlite3
import time
import zlib
from typing import Any, Iterable, Optional

from . import config

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS raw_documents (
    id           INTEGER PRIMARY KEY,
    source_key   TEXT NOT NULL,
    url          TEXT NOT NULL,
    status       INTEGER,
    fetched_at   REAL NOT NULL,
    sha256       TEXT,
    n_bytes      INTEGER,
    content_z    BLOB,
    error        TEXT,
    UNIQUE(source_key, url, sha256)
);

CREATE TABLE IF NOT EXISTS memory_spot (
    id           INTEGER PRIMARY KEY,
    source_key   TEXT NOT NULL,
    grade        TEXT NOT NULL,
    unit         TEXT,
    ts           TEXT,
    weekly_high  REAL, weekly_low REAL,
    session_high REAL, session_low REAL,
    session_avg  REAL, avg_change_pct REAL,
    fetched_at   REAL NOT NULL,
    url          TEXT,
    UNIQUE(source_key, grade, ts)
);

CREATE TABLE IF NOT EXISTS memory_guide (
    id           INTEGER PRIMARY KEY,
    source_key   TEXT NOT NULL,
    url          TEXT,
    published    TEXT,
    title        TEXT,
    metric       TEXT,
    low_pct      REAL, high_pct REAL,
    quote        TEXT,
    fetched_at   REAL NOT NULL,
    UNIQUE(url, metric, low_pct, high_pct)
);

CREATE TABLE IF NOT EXISTS segment_fin (
    id           INTEGER PRIMARY KEY,
    vendor       TEXT NOT NULL,
    period_label TEXT NOT NULL,
    segment      TEXT NOT NULL,
    revenue_musd REAL,
    qoq_pct      REAL, yoy_pct REAL,
    published    TEXT,
    release_url  TEXT,
    quote        TEXT,
    fetched_at   REAL NOT NULL,
    UNIQUE(vendor, period_label, segment)
);

CREATE TABLE IF NOT EXISTS sku (
    model        TEXT PRIMARY KEY,
    vendor       TEXT,
    series       TEXT,
    launch_date  TEXT,
    msrp_usd     REAL,
    tdp_w        REAL,
    memory_gen   TEXT,
    memory_gb    REAL,
    bus_width    INTEGER,
    source_url   TEXT,
    updated_at   REAL
);

CREATE TABLE IF NOT EXISTS street_obs (
    id           INTEGER PRIMARY KEY,
    sku_model    TEXT NOT NULL,
    merchant     TEXT,
    product_name TEXT,
    price_usd    REAL,
    stock        TEXT,
    observed_at  TEXT,
    observed_ts  REAL,
    source_url   TEXT,
    UNIQUE(sku_model, merchant, observed_at, price_usd)
);

CREATE TABLE IF NOT EXISTS signals (
    id           INTEGER PRIMARY KEY,
    subreddit    TEXT,
    title        TEXT NOT NULL,
    link         TEXT,
    published    TEXT,
    kind         TEXT,
    matched      TEXT,
    sku_model    TEXT,
    source_url   TEXT,
    fetched_at   REAL NOT NULL,
    UNIQUE(link, title)
);

CREATE TABLE IF NOT EXISTS features (
    sku_model    TEXT NOT NULL,
    asof         TEXT NOT NULL,
    payload      TEXT NOT NULL,
    PRIMARY KEY (sku_model, asof)
);

CREATE TABLE IF NOT EXISTS forecasts (
    sku_model    TEXT NOT NULL,
    asof         TEXT NOT NULL,
    model_version TEXT NOT NULL,
    payload      TEXT NOT NULL,
    PRIMARY KEY (sku_model, asof, model_version)
);

CREATE TABLE IF NOT EXISTS runs (
    run_id       TEXT PRIMARY KEY,
    started_at   REAL, finished_at REAL,
    stage        TEXT, stats TEXT
);

CREATE TABLE IF NOT EXISTS api_keys (
    key          TEXT PRIMARY KEY,
    label        TEXT,
    tier         TEXT NOT NULL,
    created_at   REAL,
    active       INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS ix_street_sku ON street_obs(sku_model, observed_ts);
CREATE INDEX IF NOT EXISTS ix_signals_pub ON signals(published);
"""


def connect(path: Optional[str] = None) -> sqlite3.Connection:
    path = path or config.DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path, timeout=30)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def save_raw(con: sqlite3.Connection, source_key: str, res) -> int:
    """Persist a FetchResult with the body gzipped for later re-parsing."""
    blob = zlib.compress(res.text.encode("utf-8", "replace")) if res.text else None
    cur = con.execute(
        "INSERT OR IGNORE INTO raw_documents"
        "(source_key, url, status, fetched_at, sha256, n_bytes, content_z, error)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (source_key, res.url, res.status, res.fetched_at, res.sha256,
         len(res.text or ""), blob, res.error))
    con.commit()
    return cur.lastrowid


def load_raw(con: sqlite3.Connection, source_key: str, url: str) -> Optional[str]:
    row = con.execute(
        "SELECT content_z FROM raw_documents WHERE source_key=? AND url=?"
        " ORDER BY fetched_at DESC LIMIT 1", (source_key, url)).fetchone()
    if not row or row["content_z"] is None:
        return None
    return decompress(row["content_z"])


def decompress(blob: bytes) -> str:
    return zlib.decompress(blob).decode("utf-8", "replace")


def upsert_many(con: sqlite3.Connection, table: str, cols: list[str],
                rows: Iterable[dict[str, Any]], unique_cols: list[str] | None = None) -> int:
    """INSERT OR REPLACE keyed on `unique_cols` (or the table's own PK)."""
    rows = list(rows)
    if not rows:
        return 0
    if unique_cols:
        placeholders = ",".join("?" for _ in cols)
        names = ",".join(cols)
        sql = (f"INSERT OR REPLACE INTO {table} ({names}) VALUES ({placeholders})")
        con.executemany(sql, [[r.get(c) for c in cols] for r in rows])
    else:
        placeholders = ",".join("?" for _ in cols)
        sql = f"INSERT OR REPLACE INTO {table} ({','.join(cols)}) VALUES ({placeholders})"
        con.executemany(sql, [[r.get(c) for c in cols] for r in rows])
    con.commit()
    return len(rows)


def record_run(con: sqlite3.Connection, run_id: str, stage: str, stats: dict) -> None:
    con.execute("INSERT OR REPLACE INTO runs(run_id, started_at, finished_at, stage, stats)"
                " VALUES (?,?,?,?,?)",
                (run_id, stats.get("started_at", time.time()), time.time(), stage,
                 json.dumps(stats, default=str)))
    con.commit()
