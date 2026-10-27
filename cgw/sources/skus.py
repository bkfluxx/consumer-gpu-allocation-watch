"""SKU-universe collector: launch date, MSRP, TDP and memory generation.

Source: Wikipedia GPU lists (CC BY-SA). The launch MSRP is what the street-price
triggers are measured against, and the launch date drives the age feature.
"""
from __future__ import annotations

import re
from typing import Any

from .. import config
from ..htmltab import parse_tables, strip_tags

MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")
MONTH_ALT = "|".join(list(MONTHS) + [m[:3] for m in MONTHS])
# "March 4, 2025" / "Mar 6, 2025" / "May, 2025" / "June 2025"
DATE_RE = re.compile(r"\b(" + MONTH_ALT + r")\s+(?:\d{1,2},\s*)?\d{4}\b")
MSRP_RE = re.compile(r"\$\s?([\d,]+)(?:\s*\(USD\s*\$?([\d,]+)\))?")
MSRP_COL_NAMES = ("msrp (usd)", "release price (usd)", "launch price (usd)", "price (usd)",
                  "release date & price", "release date and price")
VENDOR_PREFIX = {"nvidia": r"GeForce\s+", "amd": r"Radeon\s+"}


def canonical_model(raw: str, vendor: str) -> str | None:
    """'GeForce RTX 5070 Ti[498]' / 'Radeon RX 9070 XT (Navi 48' -> 'RTX 5070 Ti' / 'RX 9070 XT'."""
    name = re.sub(r"\[[^\]]*\]", "", strip_tags(raw)).strip()
    name = re.sub(VENDOR_PREFIX.get(vendor, ""), "", name, flags=re.I)
    name = re.sub(r"\(.*$", "", name)          # drop codename parenthesis, often truncated
    name = re.sub(r"\s+", " ", name).strip(" -–")
    hits = [f for v, f in config.TRACKED_FAMILIES
            if v == vendor and re.match(re.escape(f) + r"\b", name, re.I)]
    if not hits:
        return None
    return max(hits, key=len)


def parse_sku_tables(html: str, vendor: str, source_url: str) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for t in parse_tables(html):
        hdr = t.headers()
        if not any(c in hdr for c in MSRP_COL_NAMES):
            continue
        table_rows: list[dict] = []
        for row in t.body_rows():
            cells = [c.text for c in row.cells]
            if not cells:
                continue
            model = canonical_model(cells[0], vendor)
            if not model or model in seen:
                continue
            launch = ""
            for c in cells[1:4]:
                dm = DATE_RE.search(c)
                if dm:
                    launch = dm.group(0)
                    break
            msrp = tdp = mem_gb = None
            money_cells = [(i, m) for i, c in enumerate(cells) for m in [MSRP_RE.search(c)] if m]
            if money_cells:
                i, m = money_cells[-1]
                msrp = float(m.group(1).replace(",", ""))
                # TDP: "250", "263 W", "150 W 160 W" - nearest such cell before the price
                for j in range(i - 1, max(0, i - 5), -1):
                    c = cells[j].strip()
                    tm = re.fullmatch(r"(\d{2,3})(?:\s*W)(?:\s+\d{2,3}\s*W)?", c) or \
                         re.fullmatch(r"(\d{2,3})", c)
                    if tm and 20 <= int(tm.group(1)) <= 700:
                        tdp = float(tm.group(1))
                        break
            # VRAM when the table states it in a cell of its own ("8 GB", "16 GB")
            for c in cells:
                gbm = re.fullmatch(r"\s*(\d{1,2})\s*GB(?:\s+\d{1,2}\s*GB)?\s*", c)
                if gbm:
                    mem_gb = float(gbm.group(1))
                    break
            mem_gen = ""
            for c in cells:
                gm = re.search(r"\b(GDDR\dX?|GDDR7|GDDR6X|GDDR6|GDDR5)\b", c, re.I)
                if gm:
                    mem_gen = gm.group(1).upper()
                    break
            seen.add(model)
            table_rows.append({"model": model, "vendor": vendor, "series": _series_of(model),
                               "launch_date": launch, "msrp_usd": msrp, "tdp_w": tdp,
                               "memory_gen": mem_gen, "memory_gb": mem_gb, "bus_width": None,
                               "source_url": source_url})
        # Rowspan layout in these tables drops cells for some rows, so a row can
        # lose its memory-generation cell. The generation is a property of the
        # series, so borrow the value that other rows in the same table carry.
        gens = [r["memory_gen"] for r in table_rows if r["memory_gen"]]
        if gens:
            table_gen = max(set(gens), key=gens.count)
            for r in table_rows:
                if not r["memory_gen"]:
                    r["memory_gen"] = table_gen
        out.extend(table_rows)
    return out


def _series_of(model: str) -> str:
    for vendor, series, pat in config.SERIES_PATTERNS:
        if re.search(pat, model, re.I):
            return series
    return ""


def collect(fetcher, store_raw=None) -> dict[str, Any]:
    res: dict[str, Any] = {"skus": [], "errors": []}
    for key, vendor in (("wikipedia_nvidia_skus", "nvidia"), ("wikipedia_amd_skus", "amd")):
        spec = config.SOURCES[key]
        r = fetcher.get(spec.url)
        if store_raw:
            store_raw(key, r)
        if not r.ok:
            res["errors"].append({"source": key, "error": r.error or r.status})
            continue
        res["skus"].extend(parse_sku_tables(r.text, vendor, r.url))
    return res
