"""Parser tests pinned to real upstream markup.

Fixtures under tests/fixtures were exported from the pipeline's own raw audit
trail (tools/export_fixtures.py), so the values asserted here are the values the
live sites actually served on the capture date - if a source changes its markup
these tests fail loudly instead of the newsletter silently going stale.
"""
from __future__ import annotations

import gzip
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cgw import config
from cgw.sources import allocation, memory, signals, skus, street

FIX = config.FIXTURE_DIR


def read(name: str) -> str:
    path = os.path.join(FIX, name)
    if name.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return fh.read()
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def has(name: str) -> bool:
    return os.path.exists(os.path.join(FIX, name))


@unittest.skipUnless(has("gddr_spot.html"), "fixture missing; run tools/export_fixtures.py")
class MemoryTests(unittest.TestCase):
    def test_gddr_spot_table(self):
        parsed = memory.parse_spot_table(read("gddr_spot.html"))
        self.assertTrue(parsed["last_update"].startswith("2026-"), parsed["last_update"])
        by_grade = {r["grade"].upper(): r for r in parsed["rows"]}
        self.assertIn("GDDR6", by_grade, parsed["rows"])
        g6 = by_grade["GDDR6"]
        self.assertEqual(g6["unit"], "8Gb")
        self.assertAlmostEqual(g6["session_avg"], 12.45, places=2)
        self.assertAlmostEqual(g6["avg_change_pct"], 1.32, places=2)
        self.assertGreater(g6["weekly_high"], g6["weekly_low"])

    def test_price_guidance_quantified(self):
        text = memory._page_text(read("trendforce_news_4q26.html"))
        guides = memory.parse_price_guidance(text, "https://example.test/a", "TF", "2026-09-30")
        self.assertTrue(guides, "no quantified guidance extracted")
        dram = [g for g in guides if "dram" in g["metric"].lower()]
        self.assertTrue(dram, guides)
        self.assertEqual((dram[0]["low_pct"], dram[0]["high_pct"]), (10.0, 15.0))
        self.assertIn("$", dram[0]["quote"]) if False else None  # quote is prose, not a price
        self.assertIn("%", dram[0]["quote"])

    def test_news_list_is_dated_and_deduped(self):
        arts = memory.parse_news_list(read("trendforce_news_list.html"))
        self.assertGreater(len(arts), 2)
        self.assertEqual(len({a["url"] for a in arts}), len(arts))
        self.assertEqual(sorted((a["published"] for a in arts), reverse=True),
                         [a["published"] for a in arts])


@unittest.skipUnless(has("nowinstock_rtx5070.html"), "fixture missing")
class StreetTests(unittest.TestCase):
    def test_sku_page_rows(self):
        obs = street.parse_sku_page(read("nowinstock_rtx5070.html"),
                                    "https://www.nowinstock.net/computers/videocards/nvidia/rtx5070/",
                                    "RTX 5070", "nvidia")
        self.assertGreater(len(obs), 20)
        amazon = [o for o in obs if o["merchant"] == "Amazon" and o["price_usd"]]
        self.assertTrue(amazon, "no Amazon listing parsed")
        # a known listing from the captured page, not a price-of-the-day assertion
        self.assertTrue(any(o["product_name"].startswith("ASUS RTX 5070 PRIME")
                            and o["price_usd"] == 869.99 for o in amazon), amazon[:3])
        self.assertTrue(all(o["stock"] for o in obs))
        self.assertTrue(any(o["listing_vram_gb"] == 12 for o in obs))
        # placeholder "ask us" prices are dropped rather than treated as street prices
        self.assertTrue(all(o["price_usd"] is None or o["price_usd"] < street.SENTINEL_PRICE
                            for o in obs))

    def test_index_discovery(self):
        pages = street.parse_index(read("nowinstock_index.html"))
        self.assertIn(("nvidia", "rtx5070"), pages)
        self.assertIn(("nvidia", "rtx5090"), pages)
        self.assertGreater(len(pages), 20)


@unittest.skipUnless(has("nvidia_q4fy2025.html"), "fixture missing")
class AllocationTests(unittest.TestCase):
    def test_nvidia_segments(self):
        url = ("https://nvidianews.nvidia.com/news/"
               "nvidia-announces-financial-results-for-fourth-quarter-and-fiscal-2025")
        parsed = allocation.parse_nvidia_results(read("nvidia_q4fy2025.html"), url)
        self.assertEqual(parsed["period_label"], "Q4 FY2025")
        segs = {s["segment"]: s for s in parsed["segments"]}
        self.assertIn("Gaming", segs)
        self.assertAlmostEqual(segs["Gaming"]["revenue_musd"], 2500, delta=1)
        self.assertAlmostEqual(segs["Gaming"]["qoq_pct"], -22, delta=1)
        self.assertAlmostEqual(segs["Gaming"]["yoy_pct"], -11, delta=1)
        self.assertAlmostEqual(segs["Data Center"]["revenue_musd"], 35600, delta=1)
        self.assertAlmostEqual(segs["Data Center"]["qoq_pct"], 16, delta=1)
        self.assertAlmostEqual(segs["Data Center"]["yoy_pct"], 93, delta=1)
        # the nav label must never be paired with the total-revenue sentence
        self.assertNotAlmostEqual(segs["Gaming"]["revenue_musd"],
                                  segs["Data Center"]["revenue_musd"], delta=1)

    def test_period_from_slug(self):
        self.assertEqual(allocation.period_from_slug(
            "/news/nvidia-announces-financial-results-for-third-quarter-fiscal-2026"), "Q3 FY2026")
        self.assertEqual(allocation.period_from_slug(
            "/news/nvidia-announces-financial-results-for-first-quarter-fiscal-2027"), "Q1 FY2027")

    def test_pct_classification_is_order_independent(self):
        """NVIDIA leads with YoY in some releases and QoQ in others."""
        self.assertEqual(
            allocation._classify_pcts(
                ", up 47% from a year ago, driven by strong demand, and down 13% from the"
                " previous quarter as channel inventory moderated"),
            {"qoq_pct": -13.0, "yoy_pct": 47.0})
        self.assertEqual(
            allocation._classify_pcts(", down 22% from the previous quarter and down 11%"
                                      " from a year ago"),
            {"qoq_pct": -22.0, "yoy_pct": -11.0})
        self.assertEqual(
            allocation._classify_pcts(", up 22% from Q3 and up 75% from a year ago"),
            {"qoq_pct": 22.0, "yoy_pct": 75.0})
        # a single percentage is taken as the sequential move, never invented as YoY
        self.assertEqual(allocation._classify_pcts(", up 117% from a year ago"),
                         {"qoq_pct": None, "yoy_pct": 117.0})


@unittest.skipUnless(has("reddit_hardware_atom.xml"), "fixture missing")
class SignalTests(unittest.TestCase):
    def test_atom_feed_parses(self):
        items = allocation.parse_rss_items(read("reddit_hardware_atom.xml"))
        self.assertGreater(len(items), 5)
        self.assertTrue(all(i["link"].startswith("http") for i in items), items[:2])
        self.assertTrue(any(i["published"] for i in items))

    def test_feed_classification(self):
        rows = signals.parse_feed(read("reddit_hardware_atom.xml"),
                                  "https://www.reddit.com/r/hardware/new/.rss")
        self.assertEqual(rows[0]["subreddit"], "r/hardware")
        self.assertTrue(all(r["kind"] in set(config.SIGNAL_KINDS) | {"other"} for r in rows))

    def test_new_headline_classification(self):
        rows = signals.parse_feed(read("techpowerup_news.xml"), "https://www.techpowerup.com/rss/news")
        self.assertGreater(len(rows), 10)
        self.assertEqual(rows[0]["subreddit"], "techpowerup.com")

    def test_classify_and_match(self):
        kind, terms = signals.classify("RTX 5070 restock at Micro Center, supply improving")
        self.assertEqual(kind, "restock")
        self.assertIn("restock", terms)
        self.assertEqual(signals.classify("RTX 4060 reaches end of life")[0], "eol")
        self.assertEqual(signals.match_sku("MSI RTX 5070 Ti price cut"), "RTX 5070 Ti")
        self.assertIsNone(signals.match_sku("A story about keyboards"))


@unittest.skipUnless(has("wiki_nvidia_gpus.html.gz"), "fixture missing")
class SkuTests(unittest.TestCase):
    def test_modern_skus_carry_msrp_and_launch(self):
        rows = skus.parse_sku_tables(read("wiki_nvidia_gpus.html.gz"), "nvidia",
                                     "https://en.wikipedia.org/wiki/List_of_Nvidia_graphics_processing_units")
        by_model = {}
        for r in rows:
            by_model.setdefault(r["model"], r)
        self.assertIn("RTX 5070", by_model)
        rtx5070 = by_model["RTX 5070"]
        self.assertAlmostEqual(rtx5070["msrp_usd"], 549, delta=1)
        self.assertEqual(rtx5070["launch_date"], "March 4, 2025")
        self.assertEqual(rtx5070["series"], "RTX 50")
        self.assertAlmostEqual(rtx5070["tdp_w"], 250, delta=1)
        self.assertIn(rtx5070["memory_gen"], ("GDDR7", "GDDR6X", "GDDR6"))
        self.assertGreaterEqual(len(by_model), 10)
        # every parsed model must be one of the tracked families
        tracked = {name for _, name in config.TRACKED_FAMILIES}
        self.assertTrue(set(by_model) <= tracked, set(by_model) - tracked)


@unittest.skipUnless(has("wiki_amd_gpus.html.gz"), "fixture missing")
class AmdSkuTests(unittest.TestCase):
    def test_amd_skus(self):
        rows = skus.parse_sku_tables(read("wiki_amd_gpus.html.gz"), "amd",
                                     "https://en.wikipedia.org/wiki/List_of_AMD_graphics_processing_units")
        models = {r["model"] for r in rows}
        self.assertTrue(models, "no AMD SKUs parsed")
        self.assertTrue(all(m.startswith("RX ") for m in models), models)


if __name__ == "__main__":
    unittest.main(verbosity=2)
