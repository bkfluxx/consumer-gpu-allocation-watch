"""Die-allocation collectors: vendor segment revenue (Gaming vs Data Center).

The allocation signal is the quarter-over-quarter direction of each vendor's
Gaming revenue set against its Data Center revenue. When gaming revenue falls
while data-centre revenue rises, the wafers and packaging capacity are moving
away from consumer parts - which is what drives consumer SKU EOL and scarcity.
"""
from __future__ import annotations

import html as html_mod
import re
from typing import Any

from .. import config
from ..htmltab import strip_tags

SEGMENTS = ["Data Center", "Gaming", "Professional Visualization", "Automotive",
            "Client", "Embedded", "Radeon", "Edge Computing"]

# Vendor wording varies; map what we see onto the buckets we track.
SEGMENT_ALIASES = {
    "data center": "Data Center", "gaming": "Gaming", "gaming and ai pc": "Gaming",
    "professional visualization": "Professional Visualization", "automotive": "Automotive",
    "client": "Client", "embedded": "Embedded", "radeon": "Radeon",
    "edge computing": "Edge Computing",
}
IGNORE_SEGMENTS = {"record", "record quarterly", "quarterly", "total", "full-year",
                   "full year", "fourth-quarter", "first-quarter", "second-quarter",
                   "third-quarter", "our", "the", "revenue", "annual", "fiscal"}

# Anchored so a nav label ("Gaming & Entertainment") can never be paired with the
# total-revenue sentence, which is how a naive sentence scan misreads these pages.
# Matches start exactly at a segment name from the tracked vocabulary, so a nav
# label or a "record quarterly revenue" sentence can never be paired with a
# segment's figures. The percentage context is taken separately (see below) and
# cut at the next figure or segment name, which is what kept one match from
# swallowing the next segment's sentence.
SEG_ALT = "|".join(sorted((re.escape(k) for k in SEGMENT_ALIASES), key=len, reverse=True))
SEG_PAT = re.compile(
    rf"(?P<seg>{SEG_ALT})\s+revenue\s+(?:of|was|grew\s+to|rose\s+to)\s+"
    rf"\$(?P<amt>[\d.,]+)\s+(?P<unit>billion|million)", re.I)
CONTEXT_STOP = re.compile(rf"\$|\b(?:{SEG_ALT})\b", re.I)

QOQ_HINTS = re.compile(r"previous quarter|sequentially|quarter-over-quarter|from Q[1-4]\b", re.I)
YOY_HINTS = re.compile(r"year ago|year-over-year|from a year|yoy", re.I)


def _classify_pcts(tail: str) -> dict[str, float | None]:
    """Sort '(up|down) N%' mentions in a segment sentence into QoQ vs YoY.

    Vendors do not keep a fixed order - NVIDIA's Q4 FY2026 release leads with the
    year-over-year move - so each percentage is classified by the words that
    follow it rather than by position.
    """
    out: dict[str, float | None] = {"qoq_pct": None, "yoy_pct": None}
    # Find every percentage first, then give each one its own context, cut at the
    # start of the next percentage. A single regex cannot do both: a greedy context
    # swallows the following percentage, and a lazily truncated one may never find a
    # terminator (NVIDIA's Q4 FY2026 gaming sentence runs past 70 chars without a comma).
    hits = list(re.finditer(r"\b(up|down)\s+([\d.]+)\s*%", tail, re.I))
    for i, m in enumerate(hits):
        sign = 1 if m.group(1).lower() == "up" else -1
        val = sign * float(m.group(2))
        end = hits[i + 1].start() if i + 1 < len(hits) else min(len(tail), m.end() + 80)
        ctx = tail[m.end():end][:80]
        if QOQ_HINTS.search(ctx) and out["qoq_pct"] is None:
            out["qoq_pct"] = val
        elif YOY_HINTS.search(ctx) and out["yoy_pct"] is None:
            out["yoy_pct"] = val
        elif out["qoq_pct"] is None:
            out["qoq_pct"] = val
        elif out["yoy_pct"] is None:
            out["yoy_pct"] = val
    return out


ORD = {"first": 1, "second": 2, "third": 3, "fourth": 4}


def period_from_slug(slug: str) -> str | None:
    """'...-fourth-quarter-and-fiscal-2025' -> 'Q4 FY2025' (fiscal year)."""
    m = re.search(r"(first|second|third|fourth)-quarter", slug)
    if not m:
        return None
    q = ORD[m.group(1)]
    fy = re.search(r"fiscal-(\d{4})", slug)
    if fy:
        return f"Q{q} FY{fy.group(1)}"
    cal = re.search(r"-(\d{4})(?:-|$)", slug)
    if cal:
        return f"Q{q} {cal.group(1)}"
    return f"Q{q}"


def parse_nvidia_results(html: str, url: str) -> dict[str, Any]:
    """Pull per-segment revenue + QoQ/YoY out of an NVIDIA earnings release.

    Segment names are read from the release rather than assumed: NVIDIA stopped
    breaking out Gaming from fiscal 2027, so a fixed segment list would silently
    report a stale gaming number as if it were current.
    """
    text = " ".join(strip_tags(html).split())
    published = ""
    pm = re.search(r"([A-Z][a-z]+ \d{1,2}, \d{4})", text[:4000])
    if pm:
        published = pm.group(1)
    period = period_from_slug(url)
    out: dict[str, Any] = {"vendor": "nvidia", "period_label": period, "published": published,
                           "release_url": url, "segments": [], "warnings": []}
    if not period:
        out["warnings"].append("could not derive period label from url")

    found: dict[str, dict] = {}
    for m in SEG_PAT.finditer(text):
        raw_seg = " ".join(m.group("seg").split())
        key = SEGMENT_ALIASES.get(raw_seg.lower())
        if not key or key in found:
            continue                        # unknown buckets are never invented
        amount = float(m.group("amt").replace(",", ""))
        musd = amount * 1000 if m.group("unit").lower() == "billion" else amount
        tail = text[m.end("unit"): m.end("unit") + 200]
        stop = CONTEXT_STOP.search(tail)
        if stop:
            tail = tail[:stop.start()]
        pcts = _classify_pcts(tail)
        found[key] = {
            "vendor": "nvidia", "period_label": period, "segment": key,
            "revenue_musd": musd, "qoq_pct": pcts["qoq_pct"], "yoy_pct": pcts["yoy_pct"],
            "published": published, "release_url": url,
            "quote": " ".join((m.group(0) + tail)[:400].split()),
        }
    out["segments"] = list(found.values())
    if "Gaming" not in found:
        out["warnings"].append("no Gaming segment disclosed in this release")
    if not found:
        out["warnings"].append("no segment revenue parsed")
    return out


def parse_amd_results(html: str, url: str, title: str = "") -> dict[str, Any]:
    """AMD earnings releases: '<Segment> segment revenue was $X million, down Y% ...'."""
    text = " ".join(strip_tags(html).split())
    period = None
    pm = re.search(r"(first|second|third|fourth)\s+quarter\s+(?:of\s+)?(?:fiscal\s+)?(\d{4})", title, re.I)
    if pm:
        period = f"Q{ORD[pm.group(1).lower()]} {pm.group(2)}"
    out: dict[str, Any] = {"vendor": "amd", "period_label": period, "published": "",
                           "release_url": url, "segments": [], "warnings": []}
    if not period:
        out["warnings"].append("period label not derivable; skipped")
        return out
    dm = re.search(r"([A-Z][a-z]+ \d{1,2}, \d{4})", text[:4000])
    if dm:
        out["published"] = dm.group(1)

    for seg in SEGMENTS:
        m = re.search(
            rf"{re.escape(seg)}\s+segment\s+revenue\s+(?:was|of)\s+\$([\d.,]+)\s*(billion|million)"
            rf"([^.]{{0,220}})", text, re.I)
        if not m:
            continue
        amount = float(m.group(1).replace(",", ""))
        musd = amount * 1000 if m.group(2).lower() == "billion" else amount
        pcts = _classify_pcts(m.group(3))
        out["segments"].append({
            "vendor": "amd", "period_label": period, "segment": seg, "revenue_musd": musd,
            "qoq_pct": pcts["qoq_pct"], "yoy_pct": pcts["yoy_pct"],
            "published": out["published"], "release_url": url,
            "quote": " ".join((m.group(0))[:400].split()),
        })
    if not out["segments"]:
        out["warnings"].append("no segment revenue parsed")
    return out


def parse_nvidia_links(html: str) -> list[str]:
    links = set()
    for m in re.finditer(r'href="(/news/nvidia-announces-financial-results-for-[^"]+)"', html):
        links.add("https://nvidianews.nvidia.com" + m.group(1))
    return sorted(links)


def parse_rss_items(xml: str) -> list[dict]:
    """RSS 2.0 (<item>) and Atom (<entry>) items, whichever the feed uses.

    Reddit serves Atom (`/new/.rss`), TrendForce-style feeds serve RSS; both show
    up in this pipeline so the parser has to handle the link representation of
    each (Atom puts the URL in an attribute, RSS in element text).
    """
    xml = xml or ""
    blocks = re.findall(r"(?s)<item>(.*?)</item>", xml)
    atom = False
    if not blocks:
        blocks = re.findall(r"(?s)<entry[^>]*>(.*?)</entry>", xml)
        atom = True

    def text_of(blk: str, tag: str) -> str:
        m = re.search(rf"(?s)<{re.escape(tag)}[^>]*>(.*?)</{re.escape(tag)}>", blk)
        if not m:
            return ""
        v = m.group(1).strip()
        v = re.sub(r"(?s)^<!\[CDATA\[(.*?)\]\]>$", r"\1", v)
        return strip_tags(v).strip()

    def link_of(blk: str) -> str:
        m = re.search(r'<link[^>]*rel="alternate"[^>]*href="([^"]+)"', blk)
        if not m:
            m = re.search(r'<link[^>]*href="([^"]+)"', blk)
        if m:
            return html_mod.unescape(m.group(1))
        return text_of(blk, "link")

    items = []
    for blk in blocks:
        items.append({
            "title": text_of(blk, "title"),
            "link": link_of(blk),
            "published": text_of(blk, "pubDate") or text_of(blk, "updated")
                         or text_of(blk, "published") or text_of(blk, "dc:date"),
        })
    return items


def collect(fetcher, max_nvidia: int = 6, store_raw=None) -> dict[str, Any]:
    res: dict[str, Any] = {"segments": [], "warnings": [], "errors": []}

    # --- NVIDIA: newsroom search page -> quarterly results releases
    spec = config.SOURCES["nvidia_newsroom"]
    r = fetcher.get(spec.url)
    if store_raw:
        store_raw("nvidia_newsroom", r)
    if not r.ok:
        res["errors"].append({"source": "nvidia_newsroom", "error": r.error or r.status})
    else:
        links = parse_nvidia_links(r.text)
        # newest fiscal year first is not guaranteed; parse all we found
        for link in links[:max_nvidia]:
            pr = fetcher.get(link)
            if store_raw:
                store_raw("nvidia_newsroom", pr)
            if not pr.ok:
                res["errors"].append({"source": link, "error": pr.error or pr.status})
                continue
            parsed = parse_nvidia_results(pr.text, link)
            res["segments"].extend(parsed["segments"])
            res["warnings"].extend({"source": link, "warning": w} for w in parsed["warnings"])

    # --- AMD: IR RSS -> earnings release
    spec = config.SOURCES["amd_ir_rss"]
    ar = fetcher.get(spec.url)
    if store_raw:
        store_raw("amd_ir_rss", ar)
    if not ar.ok:
        res["errors"].append({"source": "amd_ir_rss", "error": ar.error or ar.status})
    else:
        items = parse_rss_items(ar.text)
        earn = [i for i in items if re.search(r"Reports.*(Financial Results|Quarter)", i["title"], re.I)]
        if not earn:
            res["warnings"].append({"source": "amd_ir_rss",
                                    "warning": "no earnings release in current RSS window"})
        for it in earn[:2]:
            pr = fetcher.get(it["link"])
            if store_raw:
                store_raw("amd_ir_rss", pr)
            if not pr.ok:
                res["errors"].append({"source": it["link"], "error": pr.error or pr.status})
                continue
            parsed = parse_amd_results(pr.text, it["link"], it["title"])
            res["segments"].extend(parsed["segments"])
            res["warnings"].extend({"source": it["link"], "warning": w} for w in parsed["warnings"])
    return res
