"""Memory pricing collectors (TrendForce GDDR/DRAM spot + contract, press guidance)."""
from __future__ import annotations

import re
from typing import Any

from .. import config
from ..htmltab import parse_tables, strip_tags

UNIT_RE = re.compile(r"^(?P<grade>[A-Za-z0-9 ]+?)\s*(?P<unit>\d+\s*Gb)$")


def _num(txt: str) -> float | None:
    txt = (txt or "").strip().replace(",", "")
    m = re.search(r"-?\d+(?:\.\d+)?", txt)
    return float(m.group(0)) if m else None


def parse_spot_table(html: str) -> dict[str, Any]:
    """Parse a TrendForce price-trend page (GDDR / DRAM / module spot).

    Returns {'last_update': str|None, 'rows': [...]}.
    """
    out: dict[str, Any] = {"last_update": None, "rows": []}
    m = re.search(r"Last Update\s*([0-9]{4}-[0-9]{2}-[0-9]{2}[^<]*)", html)
    if m:
        out["last_update"] = m.group(1).strip()

    for t in parse_tables(html):
        hdr = t.headers()
        if not any("session average" in h for h in hdr) and not any("daily high" in h for h in hdr):
            continue
        idx_change = t.header_index("average change", "session change", "change")
        cols = ["weekly_high", "weekly_low", "session_high", "session_low", "session_avg"]
        for row in t.body_rows():
            cells = [c.text for c in row.cells]
            if len(cells) < 3:
                continue
            item = cells[0]
            um = UNIT_RE.match(item.replace("  ", " ").strip())
            if not um:
                continue
            vals = [_num(c) for c in cells[1:]]
            numeric = [v for v in vals if v is not None]
            rec = {
                "grade": um.group("grade").strip(),
                "unit": um.group("unit").replace(" ", ""),
                "weekly_high": vals[0] if len(vals) > 0 else None,
                "weekly_low": vals[1] if len(vals) > 1 else None,
                "session_high": vals[2] if len(vals) > 2 else None,
                "session_low": vals[3] if len(vals) > 3 else None,
                "session_avg": vals[4] if len(vals) > 4 else None,
            }
            chg = None
            if idx_change is not None and idx_change < len(cells):
                cm = re.search(r"(-?\d+(?:\.\d+)?)\s*%", cells[idx_change])
                if cm:
                    val = float(cm.group(1))
                    down = bool(re.search(r"&#9660;|▼|\bdown\b|-", cells[idx_change][:40])) \
                        and not re.search(r"&#9650;|▲", cells[idx_change])
                    chg = -val if down else val
            rec["avg_change_pct"] = chg if chg is not None else (
                numeric[-1] if numeric and abs(numeric[-1]) < 100 else None)
            if rec["session_avg"] is None and numeric:
                rec["session_avg"] = numeric[0]
            out["rows"].append(rec)
    return out


GUIDE_PATTERNS = [
    # "Conventional DRAM contract prices are projected to grow 10-15% QoQ in 4Q26"
    re.compile(r"(?P<metric>[A-Za-z0-9 /&,\-]{3,60}?)\s+(?:contract )?prices?\s+(?:are|is|were)?\s*"
               r"(?:projected|expected|forecast|set)\s+to\s+(?P<dir>grow|increase|rise|climb|decline|fall|drop|decrease|slip)"
               r"\s+(?P<low>\d{1,2}(?:\.\d+)?)\s*(?:[%–\-~to]{1,4})\s*(?P<high>\d{1,2}(?:\.\d+)?)\s*%", re.I),
    # "overall NAND Flash contract prices are projected to increase 15-20% QoQ"
    re.compile(r"(?P<metric>[A-Za-z0-9 /&,\-]{3,60}?)\s+prices?\s+(?:growth|increase|decline)"
               r"[^.]{0,40}?(?P<low>\d{1,2}(?:\.\d+)?)\s*[%–\-~to]{1,4}\s*(?P<high>\d{1,2}(?:\.\d+)?)\s*%", re.I),
]
DIR_SIGN = {"decline": -1, "fall": -1, "drop": -1, "decrease": -1, "slip": -1}


MEMORY_NOUNS = ("dram", "nand", "gddr", "lpddr", "ssd", "ufs", "emmc", "memory", "wafer")
NOUN_RE = re.compile(r"\b(dram|nand flash|nand|gddr\d?|lpddr\d?|enterprise ssd|ssd|ufs|emmc|"
                     r"pc dram|server dram|mobile dram|conventional dram|wafer)\b", re.I)


def _clean_metric(raw: str) -> str | None:
    """Trim a captured metric phrase back to the memory category it names."""
    s = " ".join(raw.split()).strip(" ,;:–-")
    s = re.sub(r"^(?:trendforce|[0-9]{1,2}\s+(?:january|february|march|april|may|june|july|august|"
               r"september|october|november|december)\s+\d{4}[^A-Za-z]*)", "", s, flags=re.I)
    m = NOUN_RE.search(s)
    if not m:
        return None
    return s[m.start():].strip(" ,;:–-").title().replace("Dram", "DRAM").replace("Nand", "NAND")


def parse_price_guidance(text: str, url: str, title: str = "", published: str = "") -> list[dict]:
    """Extract quantitative contract-price guidance from press-release prose."""
    out: list[dict] = []
    seen: set[tuple] = set()
    for pat in GUIDE_PATTERNS:
        for m in pat.finditer(text):
            metric = _clean_metric(m.group("metric") or "")
            if not metric:
                continue
            d = m.groupdict().get("dir", "") or ""
            sign = DIR_SIGN.get(d.lower(), 1)
            low, high = float(m.group("low")), float(m.group("high"))
            if low > high:
                low, high = high, low
            key = (metric.lower(), low, high)
            if key in seen:
                continue
            seen.add(key)
            sent_start = max(0, text.rfind(".", 0, m.start()) + 1)
            sent_end = text.find(".", m.end())
            quote = " ".join(text[sent_start: sent_end if sent_end > 0 else m.end() + 60].split())
            # The press-release body begins with its own headline and date; strip them
            # so the quoted claim reads as the claim, not as page furniture.
            if title and title in quote:
                quote = quote.split(title, 1)[1].strip(" ,;-")
            quote = re.sub(r"^\d{1,2} \w+ \d{4}\s*(?:Semiconductors|Memory|Press Center)?\s*", "",
                           quote)
            quote = re.sub(r"^TrendForce\s+", "", quote)
            if len(quote) > 240:                       # keep the quoted claim readable
                quote = quote[:240].rsplit(" ", 1)[0] + " …"
            out.append({
                "source_key": "trendforce_news", "url": url, "published": published,
                "title": title, "metric": metric, "low_pct": round(sign * low, 2),
                "high_pct": round(sign * high, 2), "quote": quote,
            })
    # collapse duplicates that share a % range and url (keep the short metric name)
    best: dict[tuple, dict] = {}
    for r in out:
        k = (r["url"], r["low_pct"], r["high_pct"])
        cur = best.get(k)
        if cur is None or len(r["metric"]) < len(cur["metric"]):
            best[k] = r
    return sorted(best.values(), key=lambda r: -abs(r["high_pct"]))


def _page_text(html: str) -> str:
    """Body text of a TrendForce page with nav chrome removed."""
    t = strip_tags(html)
    marker = "Home Press Center"
    i = t.find(marker)
    if i >= 0:
        t = t[i + len(marker):]
    for tail in ("Popular Keywords", "About Us", "Related Reports", "© 2026 TrendForce"):
        j = t.rfind(tail)
        if j > 200:
            t = t[:j]
    return t


def parse_news_list(html: str) -> list[dict]:
    """Article links (url, date, title) from the press-centre listing."""
    items = []
    for m in re.finditer(r'(?s)<a[^>]+href="(/presscenter/news/(\d{8})-\d+\.html)"[^>]*>(.*?)</a>', html):
        title = strip_tags(m.group(3)).strip()
        if not title:
            continue
        d = m.group(2)
        items.append({"url": "https://www.trendforce.com" + m.group(1),
                      "published": f"{d[:4]}-{d[4:6]}-{d[6:]}", "title": title})
    # de-dup, newest first
    out, seen = [], set()
    for it in items:
        if it["url"] in seen:
            continue
        seen.add(it["url"])
        out.append(it)
    return sorted(out, key=lambda x: x["published"], reverse=True)


def collect(fetcher, max_articles: int = 6, store_raw=None) -> dict[str, Any]:
    """Fetch GDDR/DRAM spot prints, contract page and recent price guidance."""
    res: dict[str, Any] = {"spot": [], "guides": [], "articles": [], "errors": []}

    for key in ("trendforce_gddr_spot", "trendforce_dram_spot", "trendforce_dram_contract"):
        spec = config.SOURCES[key]
        r = fetcher.get(spec.url)
        if store_raw:
            store_raw(key, r)
        if not r.ok:
            res["errors"].append({"source": key, "error": r.error or r.status})
            continue
        parsed = parse_spot_table(r.text)
        for row in parsed["rows"]:
            row.update({"source_key": key, "ts": parsed["last_update"], "url": r.url})
            res["spot"].append(row)

    spec = config.SOURCES["trendforce_news"]
    r = fetcher.get(spec.url)
    if store_raw:
        store_raw("trendforce_news", r)
    if not r.ok:
        res["errors"].append({"source": "trendforce_news", "error": r.error or r.status})
        return res

    arts = parse_news_list(r.text)
    res["articles"] = arts[:max_articles]
    for art in arts[:max_articles]:
        ar = fetcher.get(art["url"])
        if store_raw:
            store_raw("trendforce_news", ar)
        if not ar.ok:
            res["errors"].append({"source": art["url"], "error": ar.error or ar.status})
            continue
        text = _page_text(ar.text)
        guides = parse_price_guidance(text, art["url"], art["title"], art["published"])
        res["guides"].extend(guides)
    return res
