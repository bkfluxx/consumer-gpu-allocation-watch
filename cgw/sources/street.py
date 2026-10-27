"""Street-price / availability collectors (NowInStock retailer tracker).

Each row in the tracker is a real retailer listing: product name, merchant,
stock status, last price and its timestamp. Those per-listing observations are
what the price-trigger forecasts are computed from.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Optional

from .. import config
from ..htmltab import parse_tables

PRICE_RE = re.compile(r"\$([\d,]+(?:\.\d{2})?)")
MERCHANT_RE = re.compile(r"\s*:\s*([^:()]{2,40})$")
VRAM_RE = re.compile(r"(?<![A-Za-z])(\d{1,2})\s*GB?\b")
STOCK_WORDS = ("in stock", "out of stock", "pre-order", "backorder", "coming soon",
               "see site", "discontinued", "unknown")
DATE_RE = re.compile(r"([A-Z][a-z]{2} \d{1,2} \d{2} - \d{1,2}:\d{2}\s*[AP]M)")
# Retailer trackers use a placeholder for "price on request"; treating it as a
# price would poison the per-SKU median.
SENTINEL_PRICE = 20000.0


def parse_observed_at(txt: str) -> Optional[float]:
    """'Oct 13 26 - 6:50 PM' -> epoch seconds (None if it is not a timestamp).

    The tracker's two-digit year is the only date information available; if that
    lands in the future by more than a month it belongs to the previous year
    (a December row read in January). The epoch value is what the fusion layer
    sorts on - sorting the display strings themselves puts "Sep 20" after
    "Oct 13".
    """
    if not txt:
        return None
    for fmt in ("%b %d %y - %I:%M %p", "%b %d %Y - %I:%M %p", "%b %d %y", "%b %d %Y"):
        try:
            stamp = dt.datetime.strptime(txt.strip(), fmt)
        except ValueError:
            continue
        if stamp > dt.datetime.now() + dt.timedelta(days=31):
            stamp = stamp.replace(year=stamp.year - 1)
        return stamp.timestamp()
    return None


def parse_index(html: str) -> list[tuple[str, str]]:
    """SKU tracker pages: [(vendor, slug), ...]."""
    out, seen = [], set()
    for m in re.finditer(r'href="/computers/videocards/(nvidia|amd)/([a-z0-9]+)/"', html):
        key = (m.group(1), m.group(2))
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def _clean_name(n: str) -> tuple[str, str]:
    """'(ASUS ... GAMING) : Amazon' -> ('ASUS ...', 'Amazon')."""
    n = " ".join(n.split())
    merchant = ""
    mm = MERCHANT_RE.search(n)
    if mm:
        merchant = mm.group(1).strip()
        n = n[:mm.start()].strip()
    return n, merchant


def parse_sku_page(html: str, url: str, sku_model: str, vendor: str) -> list[dict]:
    """Rows from a per-SKU tracker page."""
    obs: list[dict] = []
    for t in parse_tables(html):
        hdr = t.headers()
        if not any(h.startswith("name") for h in hdr) or not any("status" in h for h in hdr):
            continue
        for row in t.body_rows():
            cells = [c.text for c in row.cells]
            if len(cells) < 3:
                continue
            name, merchant = _clean_name(cells[0])
            if not name or not merchant:
                continue
            status = cells[1].strip()
            pm = PRICE_RE.search(cells[2])
            price = float(pm.group(1).replace(",", "")) if pm else None
            if price is not None and price >= SENTINEL_PRICE:
                price = None          # placeholder ("ask us") prices, not street prices
            observed = ""
            for c in cells[3:]:
                dm = DATE_RE.search(c)
                if dm:
                    observed = dm.group(1)
                    break
            vm = VRAM_RE.search(name)
            obs.append({
                "sku_model": sku_model, "merchant": merchant, "product_name": name,
                "price_usd": price, "stock": status.upper().replace(" ", "_") or "UNKNOWN",
                "observed_at": observed, "observed_ts": parse_observed_at(observed),
                "source_url": url,
                "listing_vram_gb": float(vm.group(1)) if vm else None,
            })
    return obs


def collect(fetcher, slugs=None, store_raw=None, vendor_filter=None,
            max_skus: int | None = None) -> dict[str, Any]:
    """Discover tracker pages from the index, then pull each SKU page."""
    res: dict[str, Any] = {"observations": [], "pages": [], "errors": [], "sku_vram": {}}
    slugs = slugs or config.NOWINSTOCK_SLUGS

    # confirm the index still lists these pages (real discovery, not a hardcode check)
    known: set[tuple[str, str]] = set()
    for key in ("nowinstock_nvidia", "nowinstock_amd"):
        spec = config.SOURCES[key]
        r = fetcher.get(spec.url)
        if store_raw:
            store_raw(key, r)
        if r.ok:
            known.update(parse_index(r.text))
        else:
            res["errors"].append({"source": key, "error": r.error or r.status})

    picked = 0
    for vendor, model, slug in slugs:
        if vendor_filter and vendor != vendor_filter:
            continue
        if max_skus is not None and picked >= max_skus:
            break
        if known and (vendor, slug) not in known:
            res["errors"].append({"source": f"{vendor}/{slug}", "error": "not in tracker index"})
            continue
        url = f"https://www.nowinstock.net/computers/videocards/{vendor}/{slug}/"
        r = fetcher.get(url)
        if store_raw:
            store_raw(f"nowinstock_{vendor}", r)
        if not r.ok:
            res["errors"].append({"source": url, "error": r.error or r.status})
            continue
        rows = parse_sku_page(r.text, r.url, model, vendor)
        res["observations"].extend(rows)
        vrams = [o["listing_vram_gb"] for o in rows if o.get("listing_vram_gb")]
        if vrams:
            res["sku_vram"][model] = max(set(vrams), key=vrams.count)
        res["pages"].append({"sku_model": model, "url": url, "rows": len(rows)})
        picked += 1
    return res
