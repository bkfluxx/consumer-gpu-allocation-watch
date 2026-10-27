"""Configuration: sources, tracked SKUs, model weights, triggers, API tiers.

Everything the model uses is declared here so a reviewer can see the priors and
change them without touching code. Weights are hand-set expert priors for v0
(see docs/model.md); the *inputs* they act on are measured, sourced values.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("CGW_DATA_DIR", os.path.join(ROOT, "data"))
OUT_DIR = os.environ.get("CGW_OUT_DIR", os.path.join(ROOT, "out"))
FIXTURE_DIR = os.path.join(ROOT, "tests", "fixtures")
DB_PATH = os.path.join(DATA_DIR, "cgw.db")

# --------------------------------------------------------------------------
# Sources. `tier` is the licence posture we assume for republishing derived
# numbers; `refresh` is the intended polling cadence in production.
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class SourceSpec:
    key: str
    name: str
    url: str
    kind: str          # memory | street | allocation | signal | sku
    refresh: str
    license_note: str


SOURCES: dict[str, SourceSpec] = {s.key: s for s in [
    SourceSpec("trendforce_gddr_spot", "TrendForce GDDR Spot Price",
               "https://www.trendforce.com/price/dram/gddr_spot", "memory", "daily",
               "Public price page; figures republished as cited derived metrics."),
    SourceSpec("trendforce_dram_contract", "TrendForce DRAM Contract Price",
               "https://www.trendforce.com/price/dram/dram_contract", "memory", "monthly",
               "Public price page."),
    SourceSpec("trendforce_dram_spot", "TrendForce DRAM Spot Price",
               "https://www.trendforce.com/price/dram/dram_spot", "memory", "daily",
               "Public price page."),
    SourceSpec("trendforce_news", "TrendForce Press Center (Semiconductors)",
               "https://www.trendforce.com/presscenter/news/Semiconductors", "memory", "daily",
               "Press releases; quoted with attribution."),
    SourceSpec("nvidia_newsroom", "NVIDIA Newsroom financial results",
               "https://nvidianews.nvidia.com/news?q=financial+results", "allocation", "quarterly",
               "Vendor press releases; quoted with attribution."),
    SourceSpec("amd_ir_rss", "AMD Investor Relations press releases (RSS)",
               "https://ir.amd.com/news-events/press-releases/rss", "allocation", "weekly",
               "Vendor press releases; quoted with attribution."),
    SourceSpec("nowinstock_nvidia", "NowInStock.net NVIDIA tracker",
               "https://www.nowinstock.net/computers/videocards/nvidia/", "street", "hourly",
               "Public retailer tracker; per-merchant prices republished as aggregates."),
    SourceSpec("nowinstock_amd", "NowInStock.net AMD tracker",
               "https://www.nowinstock.net/computers/videocards/amd/", "street", "hourly",
               "Public retailer tracker; per-merchant prices republished as aggregates."),
    SourceSpec("reddit_signals", "Reddit public RSS (hardware/supply chatter)",
               "https://www.reddit.com/r/hardware/new/.rss", "signal", "hourly",
               "Public RSS; headlines quoted with link. Reddit throttles bursts - "
               "treat gaps as expected, not as a data outage."),
    SourceSpec("techpowerup_rss", "TechPowerUp news RSS",
               "https://www.techpowerup.com/rss/news", "signal", "hourly",
               "Public RSS; headlines quoted with link."),
    SourceSpec("tomshardware_rss", "Tom's Hardware RSS",
               "https://www.tomshardware.com/feeds/all", "signal", "hourly",
               "Public RSS; headlines quoted with link."),
    SourceSpec("wccftech_rss", "Wccftech RSS",
               "https://wccftech.com/feed/", "signal", "hourly",
               "Public RSS; headlines quoted with link."),
    SourceSpec("wikipedia_nvidia_skus", "Wikipedia: List of Nvidia GPUs",
               "https://en.wikipedia.org/wiki/List_of_Nvidia_graphics_processing_units", "sku", "weekly",
               "CC BY-SA 4.0; attributes used, text not republished."),
    SourceSpec("wikipedia_amd_skus", "Wikipedia: List of AMD GPUs",
               "https://en.wikipedia.org/wiki/List_of_AMD_graphics_processing_units", "sku", "weekly",
               "CC BY-SA 4.0; attributes used, text not republished."),
]}

# Subreddits / search feeds polled for supply + EOL chatter. Kept short on
# purpose: Reddit rate-limits bursts (HTTP 429), so the collector spaces these
# out and treats throttling as an expected gap rather than a failure.
REDDIT_FEEDS = [
    "https://www.reddit.com/r/hardware/new/.rss",
    "https://www.reddit.com/r/hardware/search.rss?q=restock+OR+supply+OR+%22end+of+life%22"
    "&sort=new&restrict_sr=1",
]

# Trade-press feeds. These carry the vendor/board-partner supply statements the
# product actually trades on, and unlike Reddit they do not throttle.
NEWS_FEEDS = [
    "https://www.techpowerup.com/rss/news",
    "https://www.tomshardware.com/feeds/all",
    "https://wccftech.com/feed/",
]

SIGNAL_KINDS = {
    "eol": ["end of life", "eol", "discontinu", "last batch", "final shipment",
            "phased out", "no longer produced", "production ends", "ending the",
            "wind down", "halt production", "sunset", "replaces the", "successor"],
    "shortage": ["shortage", "out of stock", "scalping", "price hike", "price increase",
                 "sold out", "allocation", "tariff", "memory prices", "undersupply",
                 "supply squeeze", "price surge"],
    "restock": ["restock", "back in stock", "in stock at", "available at"],
    "launch": ["launch", "announced", "unveil", "new card", "super series"],
}

# Memory generation multipliers for $/GB when the grade is not published in a
# free feed. GDDR7 has no free public spot feed, so we scale from the GDDR6
# 8Gb spot print. Documented as an estimate, not a measurement.
MEMORY_GEN_MULT = {"GDDR5": 0.55, "GDDR6": 1.0, "GDDR6X": 1.15, "GDDR7": 1.35, "HBM": 6.0}
DEFAULT_GEN = "GDDR6"

# --------------------------------------------------------------------------
# Model priors (v0 heuristics - hand-set, NOT fitted on outcomes).
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class ModelPriors:
    # logistic risk weights
    bias: float = -1.15
    w_age: float = 1.10
    w_discount: float = 1.45       # deep street discount == clearance == EOL signal
    w_supply_scarcity: float = 0.85
    w_memory_cost: float = 0.90
    w_allocation: float = 1.25     # die shifted to data centre
    w_signals: float = 1.00
    w_generation: float = 0.80
    # thresholds used to turn features into 0..1 signals
    clearance_discount: float = -0.08   # street <= MSRP*0.92
    shortage_premium: float = 0.12
    age_mid_days: float = 620.0
    age_scale_days: float = 190.0
    # --- price-path priors: temper the scarcity term and cap the extrapolation
    pass_through: float = 0.55
    scarcity_uplift: float = 0.20  # max uplift attributed to scarcity at 1 - stock_breadth
    horizon_days: int = 90
    max_projected_change: float = 0.30   # never project more than +/-30% in one horizon
    memory_share_floor: float = 0.05
    memory_share_ceiling: float = 0.60


PRIORS = ModelPriors()

# Trigger levels as multiples of launch MSRP.
TRIGGER_LEVELS = (1.05, 1.15, 1.30, 1.50)

# --------------------------------------------------------------------------
# API monetisation tiers (see docs/product.md).
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Tier:
    key: str
    name: str
    price_usd_month: int
    requests_per_day: int
    endpoints: tuple
    notes: str


TIERS: dict[str, Tier] = {t.key: t for t in [
    Tier("free", "Free", 0, 200,
         ("health", "meta", "memory/latest", "skus/summary"),
         "Freshness metadata + memory prints + top-line SKU board. Attribution required."),
    Tier("pro", "Pro API", 199, 20000,
         ("health", "meta", "memory/latest", "memory/history", "skus/summary", "skus",
          "forecasts/discontinuation", "forecasts/price-triggers", "allocation", "signals"),
         "Full per-SKU forecasts, allocation series and signal stream."),
    Tier("desk", "Desk (newsletter + API + alert webhooks)", 499, 100000,
         ("*",),
         "Everything in Pro plus trigger alerts, webhook push and quarterly review call."),
]}

SERIES_PATTERNS = [
    ("nvidia", "RTX 50", r"RTX\s*50\d0"),
    ("nvidia", "RTX 40", r"RTX\s*40\d0"),
    ("nvidia", "RTX 30", r"RTX\s*30\d0"),
    ("amd", "RX 9000", r"RX\s*90\d0"),
    ("amd", "RX 7000", r"RX\s*7\d00"),
    ("amd", "RX 6000", r"RX\s*6\d00"),
]

# Tracked SKU families: the consumer parts large enough to have retail feeds.
TRACKED_FAMILIES = [
    ("nvidia", "RTX 5090"), ("nvidia", "RTX 5080"), ("nvidia", "RTX 5070 Ti"),
    ("nvidia", "RTX 5070"), ("nvidia", "RTX 5060 Ti"), ("nvidia", "RTX 5060"),
    ("nvidia", "RTX 4090"), ("nvidia", "RTX 4080"), ("nvidia", "RTX 4070 Ti"),
    ("nvidia", "RTX 4070"), ("nvidia", "RTX 4060 Ti"), ("nvidia", "RTX 4060"),
    ("amd", "RX 9070 XT"), ("amd", "RX 9070"), ("amd", "RX 9060 XT"),
    ("amd", "RX 7900 XT"), ("amd", "RX 7800 XT"), ("amd", "RX 7600"),
]

# nowinstock slugs (verified against the tracker index pages).
NOWINSTOCK_SLUGS = [
    ("nvidia", "RTX 5090", "rtx5090"), ("nvidia", "RTX 5080", "rtx5080"),
    ("nvidia", "RTX 5070 Ti", "rtx5070ti"), ("nvidia", "RTX 5070", "rtx5070"),
    ("nvidia", "RTX 5060 Ti", "rtx5060ti"), ("nvidia", "RTX 5060", "rtx5060"),
    ("nvidia", "RTX 4090", "rtx4090"), ("nvidia", "RTX 4080", "rtx4080"),
    ("nvidia", "RTX 4070 Ti", "rtx4070ti"), ("nvidia", "RTX 4070", "rtx4070"),
    ("nvidia", "RTX 4060 Ti", "rtx4060ti"), ("nvidia", "RTX 4060", "rtx4060"),
    ("amd", "RX 9070 XT", "rx9070xt"), ("amd", "RX 9060 XT", "rx9060xt"),
    ("amd", "RX 7900 XT", "rx7900xt"), ("amd", "RX 7800 XT", "rx7800xt"),
    ("amd", "RX 7600", "rx7600"),
]

USER_AGENT_OWNER = os.environ.get("CGW_CONTACT", "cgw-watch@example.com")
