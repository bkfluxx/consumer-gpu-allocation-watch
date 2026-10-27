"""Export fixture payloads out of the pipeline's raw audit trail.

Run after a real `cgw collect`; the fixtures are byte-identical to what the live
sources served, so the parser tests assert against real upstream markup.
    python3 tools/export_fixtures.py
"""
from __future__ import annotations

import gzip
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cgw import config, store  # noqa: E402

# name -> (source_key, url LIKE pattern)
FIXTURES = {
    "gddr_spot.html": ("trendforce_gddr_spot", "%/price/dram/gddr_spot%"),
    "trendforce_news_list.html": ("trendforce_news", "%/presscenter/news/Semiconductors%"),
    "trendforce_news_4q26.html": ("trendforce_news", "%/presscenter/news/20260930-13258.html%"),
    "nowinstock_rtx5070.html": ("nowinstock_nvidia", "%/videocards/nvidia/rtx5070/"),
    "reddit_hardware_atom.xml": ("reddit_signals", "%reddit.com/r/hardware/new%"),
    "techpowerup_news.xml": ("techpowerup_rss", "%techpowerup.com/rss/news%"),
    "nvidia_newsroom_index.html": ("nvidia_newsroom", "%financial+results%"),
    "amd_ir_rss.xml": ("amd_ir_rss", "%press-releases/rss%"),
}
# Fixtures that need an exact URL: the tracker *index* is a different page from the
# per-SKU pages and a LIKE pattern cannot tell them apart.
EXACT_FIXTURES = {
    "nowinstock_index.html": ("nowinstock_nvidia",
                              "https://www.nowinstock.net/computers/videocards/nvidia/"),
}
GZ_FIXTURES = {
    "wiki_nvidia_gpus.html.gz": ("wikipedia_nvidia_skus", "%Nvidia_graphics_processing_units%"),
    "wiki_amd_gpus.html.gz": ("wikipedia_amd_skus", "%AMD_graphics_processing_units%"),
}
# name -> (source_key, url LIKE pattern) resolved after the plain ones
DERIVED = {
    "nvidia_q4fy2025.html": ("nvidia_newsroom", "%fourth-quarter-and-fiscal-2025%"),
    "amd_earnings.html": ("amd_ir_rss", "%press-releases/detail/%"),
}

# Releases that have aged out of a vendor's newsroom search window can be pulled
# directly by URL (documented, deterministic), then stored into the audit trail
# like any other fetch so the fixture is reproducible.
DIRECT_FETCH = {
    "nvidia_q4fy2025.html": (
        "nvidia_newsroom",
        "https://nvidianews.nvidia.com/news/"
        "nvidia-announces-financial-results-for-fourth-quarter-and-fiscal-2025"),
}


def newest_doc(con, key: str, pattern: str):
    return con.execute(
        "SELECT url, content_z FROM raw_documents WHERE source_key=? AND url LIKE ?"
        " AND content_z IS NOT NULL ORDER BY fetched_at DESC LIMIT 1", (key, pattern)).fetchone()


def _direct_fetch(con, name: str, missing: list[str]):
    """Fetch a named release by URL and record it in the audit trail."""
    from cgw.http import Fetcher
    key, url = DIRECT_FETCH[name]
    print(f"  {name}: not in audit trail, fetching {url}")
    res = Fetcher(min_interval=1.0).get(url)
    if not res.ok:
        return None
    store.save_raw(con, key, res)
    return con.execute(
        "SELECT url, content_z FROM raw_documents WHERE source_key=? AND url=?"
        " ORDER BY fetched_at DESC LIMIT 1", (key, res.url)).fetchone()


def main() -> int:
    os.makedirs(config.FIXTURE_DIR, exist_ok=True)
    con = store.connect()
    made, missing = 0, []
    for name, (key, pat) in (FIXTURES | EXACT_FIXTURES).items():
        pattern = pat if pat.startswith("%") else pat
        row = (newest_doc(con, key, pat) if pat.startswith("%")
               else con.execute("SELECT url, content_z FROM raw_documents WHERE source_key=?"
                                " AND url=? AND content_z IS NOT NULL ORDER BY fetched_at DESC"
                                " LIMIT 1", (key, pat)).fetchone())
        if not row:
            missing.append(f"{key} {pat}")
            continue
        body = store.decompress(row["content_z"])
        with open(os.path.join(config.FIXTURE_DIR, name), "w", encoding="utf-8") as fh:
            fh.write(body)
        made += 1
        print(f"  wrote {name} ({len(body)} bytes)  <- {row['url'][:90]}")
    for name, (key, pat) in GZ_FIXTURES.items():
        row = newest_doc(con, key, pat)
        if not row:
            missing.append(f"{key} {pat}")
            continue
        body = store.decompress(row["content_z"])
        with gzip.open(os.path.join(config.FIXTURE_DIR, name), "wt", encoding="utf-8") as fh:
            fh.write(body)
        made += 1
        print(f"  wrote {name} ({len(body)} bytes, gzipped)")
    for name, (key, pat) in DERIVED.items():
        row = newest_doc(con, key, pat)
        if not row and name in DIRECT_FETCH:
            row = _direct_fetch(con, name, missing)
        if not row:
            missing.append(f"{key} {pat}")
            continue
        body = store.decompress(row["content_z"])
        with open(os.path.join(config.FIXTURE_DIR, name), "w", encoding="utf-8") as fh:
            fh.write(body)
        made += 1
        print(f"  wrote {name} ({len(body)} bytes)  <- {row['url'][:90]}")

    for m in missing:
        print(f"  MISSING {m}")
    print(f"exported {made} fixtures to {config.FIXTURE_DIR}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
