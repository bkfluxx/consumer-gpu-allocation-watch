"""Supply / EOL signal collectors (public RSS from Reddit)."""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from .. import config
from .allocation import parse_rss_items

FAMILY_RE_CACHE: dict[str, re.Pattern] = {}


def _family_re(name: str) -> re.Pattern:
    if name not in FAMILY_RE_CACHE:
        FAMILY_RE_CACHE[name] = re.compile(r"\b" + re.escape(name).replace(r"\ ", r"\s*") + r"\b", re.I)
    return FAMILY_RE_CACHE[name]


def match_sku(title: str) -> str | None:
    """Longest tracked family name mentioned in the headline."""
    hits = [name for _, name in config.TRACKED_FAMILIES if _family_re(name).search(title)]
    if not hits:
        return None
    return max(hits, key=len)


def classify(title: str) -> tuple[str, list[str]]:
    low = title.lower()
    best, terms = "other", []
    for kind, keys in config.SIGNAL_KINDS.items():
        hit = [k for k in keys if k in low]
        if hit:
            terms.extend(hit)
            if best == "other" or kind == "eol":
                best = kind
    return best, sorted(set(terms))


def parse_feed(xml: str, url: str) -> list[dict]:
    out = []
    sm = re.search(r"/r/([A-Za-z0-9_]+)/", url)
    host = re.sub(r"^www\.", "", urlparse(url).netloc or "")
    subreddit = f"r/{sm.group(1)}" if sm else host
    for it in parse_rss_items(xml):
        if not it["title"]:
            continue
        kind, terms = classify(it["title"])
        out.append({"subreddit": subreddit, "title": it["title"][:300], "link": it["link"],
                    "published": it["published"], "kind": kind,
                    "matched": ",".join(terms), "sku_model": match_sku(it["title"]),
                    "source_url": url})
    return out


def collect(fetcher, store_raw=None, feeds=None) -> dict[str, Any]:
    """Pull Reddit + trade-press feeds and classify each headline."""
    res: dict[str, Any] = {"signals": [], "errors": [], "feeds_ok": 0, "feeds_failed": 0}
    sources = list(feeds) if feeds else (
        [(u, "reddit_signals") for u in config.REDDIT_FEEDS] +
        [(u, key) for u, key in zip(config.NEWS_FEEDS,
                                    ("techpowerup_rss", "tomshardware_rss", "wccftech_rss"))])
    for url, key in sources:
        r = fetcher.get(url)
        if store_raw:
            store_raw(key, r)
        if not r.ok:
            res["feeds_failed"] += 1
            res["errors"].append({"source": url, "error": r.error or r.status})
            continue
        res["feeds_ok"] += 1
        res["signals"].extend(parse_feed(r.text, r.url))
    # de-dup on link
    seen, uniq = set(), []
    for s in res["signals"]:
        key = s["link"] or s["title"]
        if key in seen:
            continue
        seen.add(key)
        uniq.append(s)
    res["signals"] = uniq
    return res
