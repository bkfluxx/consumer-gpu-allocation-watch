"""End-to-end test on recorded fixtures - no network.

Feeds the pipeline the exact bytes the live sources served (tests/fixtures) and
runs collect -> fuse -> forecast -> report, then asserts the artefacts exist and
contain the expected derived rows.
"""
from __future__ import annotations

import gzip
import glob
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cgw import config, forecast as fc, fuse, pipeline, report, store
from cgw.http import FetchResult

FIX = config.FIXTURE_DIR

# url substring -> fixture file. The NVIDIA quarterly releases are all served from
# the same recorded release in the offline test (the live collector fetches each
# quarter's own page); the period label still comes from the URL, so the parser path
# is exercised exactly as in production.
ROUTES = [
    ("/price/dram/gddr_spot", "gddr_spot.html"),
    ("/price/dram/dram_spot", "gddr_spot.html"),
    ("/price/dram/dram_contract", "gddr_spot.html"),
    ("/presscenter/news/Semiconductors", "trendforce_news_list.html"),
    ("/presscenter/news/2026", "trendforce_news_4q26.html"),
    ("nvidianews.nvidia.com/news?q=financial+results", "nvidia_newsroom_index.html"),
    ("nvidia-announces-financial-results-for", "nvidia_q4fy2025.html"),
    ("ir.amd.com/news-events/press-releases/rss", "amd_ir_rss.xml"),
    ("ir.amd.com/news-events/press-releases/detail/", "amd_earnings.html"),
    ("videocards/nvidia/rtx5070", "nowinstock_rtx5070.html"),
    ("videocards/nvidia/", "nowinstock_index.html"),
    ("reddit.com/r/hardware", "reddit_hardware_atom.xml"),
    ("techpowerup.com/rss/news", "techpowerup_news.xml"),
    ("Nvidia_graphics_processing_units", "wiki_nvidia_gpus.html.gz"),
    ("AMD_graphics_processing_units", "wiki_amd_gpus.html.gz"),
]


class FakeFetcher:
    """Serves recorded fixtures; anything unrouted is a recorded 404, never a guess."""

    def __init__(self, routes):
        self.routes = routes
        self.calls: list[dict] = []
        self.misses: list[str] = []

    def get(self, url, headers=None, params=None):
        for frag, name in self.routes:
            if frag in url:
                path = os.path.join(FIX, name)
                if name.endswith(".gz"):
                    with gzip.open(path, "rt", encoding="utf-8") as fh:
                        body = fh.read()
                else:
                    with open(path, encoding="utf-8", errors="replace") as fh:
                        body = fh.read()
                self.calls.append({"url": url, "status": 200, "bytes": len(body),
                                   "fetched_at": time.time()})
                import hashlib
                return FetchResult(url=url, status=200, text=body, fetched_at=time.time(),
                                   sha256=hashlib.sha256(body.encode()).hexdigest())
        self.misses.append(url)
        self.calls.append({"url": url, "status": 404, "bytes": 0, "fetched_at": time.time()})
        return FetchResult(url=url, status=404, text="", fetched_at=time.time(),
                            sha256="", error="404 fixture not routed")


@unittest.skipUnless(os.path.exists(os.path.join(FIX, "gddr_spot.html")), "fixtures missing")
class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="cgw-e2e-")
        cls.db = os.path.join(cls.tmpdir, "e2e.db")
        cls.con = store.connect(cls.db)
        cls.old = (config.NOWINSTOCK_SLUGS, config.OUT_DIR)
        config.NOWINSTOCK_SLUGS = [("nvidia", "RTX 5070", "rtx5070")]
        config.OUT_DIR = os.path.join(cls.tmpdir, "out")
        fetcher = FakeFetcher(ROUTES)
        cls.stats = pipeline.collect_all(cls.con, fetcher=fetcher, verbose=False)
        cls.features = fuse.build_features(cls.con)
        fuse.persist_features(cls.con, cls.features)
        cls.forecasts = fc.run_all(cls.features)
        fc.persist(cls.con, cls.forecasts)
        cls.ctx = report.build_context(cls.con)
        cls.paths = report.write_outputs(cls.con, cls.ctx)

    @classmethod
    def tearDownClass(cls):
        config.NOWINSTOCK_SLUGS, config.OUT_DIR = cls.old
        cls.con.close()
        import shutil
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def test_collect_populated_every_table(self):
        counts = {t: self.con.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
                  for t in ("raw_documents", "memory_spot", "memory_guide", "segment_fin",
                            "sku", "street_obs", "signals")}
        for table, n in counts.items():
            self.assertGreater(n, 0, f"{table} empty: {counts}")
        self.assertGreater(counts["sku"], 10)
        self.assertGreater(counts["street_obs"], 10)

    def test_real_values_survive_the_pipeline(self):
        gddr = self.con.execute(
            "SELECT * FROM memory_spot WHERE source_key='trendforce_gddr_spot' AND grade='GDDR6'"
        ).fetchone()
        self.assertAlmostEqual(gddr["session_avg"], 12.45, places=2)

        nv = self.con.execute("SELECT * FROM segment_fin WHERE vendor='nvidia' AND segment='Gaming'"
                             " ORDER BY period_label DESC LIMIT 1").fetchone()
        self.assertIsNotNone(nv, "no NVIDIA Gaming segment row ingested")
        self.assertAlmostEqual(nv["revenue_musd"], 2500, delta=1)
        self.assertAlmostEqual(nv["qoq_pct"], -22, delta=1)
        self.assertAlmostEqual(nv["yoy_pct"], -11, delta=1)

        rtx5070 = self.con.execute("SELECT * FROM sku WHERE model='RTX 5070'").fetchone()
        self.assertAlmostEqual(rtx5070["msrp_usd"], 549, delta=1)

        street_row = self.con.execute(
            "SELECT MIN(price_usd) p FROM street_obs WHERE sku_model='RTX 5070'").fetchone()
        self.assertGreater(street_row["p"], 100)          # a real street price, not a placeholder
        listing = self.con.execute(
            "SELECT * FROM street_obs WHERE sku_model='RTX 5070' AND merchant='Amazon'"
            " AND price_usd=869.99").fetchone()
        self.assertIsNotNone(listing, "the recorded ASUS RTX 5070 PRIME listing is missing")
        self.assertEqual(listing["stock"], "IN_STOCK")
        self.assertIsNotNone(listing["observed_ts"], "tracker timestamp not parsed to epoch")

    def test_features_and_forecasts_for_the_priced_sku(self):
        by = {f["sku_model"]: f for f in self.features}
        f = by["RTX 5070"]
        self.assertAlmostEqual(f["msrp_usd"], 549, delta=1)
        self.assertIsNotNone(f["street"]["median"])
        self.assertEqual(f["street"]["price_basis"], "in_stock_and_fresh")
        self.assertGreater(f["street"]["n_priced"], 3)
        # SKUs with no tracker page in this fixture set must not be given fake prices
        self.assertIsNone(by["RTX 5090"]["street"].get("median"))

        disc = {d["sku_model"]: d for d in self.forecasts["discontinuation"]}
        self.assertIn("RTX 5070", disc)
        self.assertTrue(0 < disc["RTX 5070"]["discontinuation_risk"] < 1)
        self.assertGreaterEqual(len(self.forecasts["price_triggers"]),
                                len(self.features) * len(config.TRIGGER_LEVELS))

    def test_report_artifacts_written(self):
        for key in ("newsletter_md", "newsletter_html", "discontinuation_csv",
                    "price_triggers_csv", "forecasts_json"):
            self.assertTrue(os.path.exists(self.paths[key]), key)
            self.assertGreater(os.path.getsize(self.paths[key]), 500, key)

        with open(self.paths["newsletter_md"], encoding="utf-8") as fh:
            md = fh.read()
        self.assertIn("# Consumer GPU Allocation Watch", md)
        self.assertIn("## Discontinuation watchlist", md)
        self.assertIn("## Street-price triggers", md)
        self.assertIn("## Provenance", md)
        self.assertIn("12.450", md)                     # real GDDR6 print
        self.assertIn(f"{len(self.features)} SKUs scored", md)
        self.assertNotIn("Traceback", md)

        # the priced SKU must appear in the trigger export even when it is not in the
        # top of the watchlist (it is a current-series card, so its risk is low)
        import csv
        with open(self.paths["price_triggers_csv"], encoding="utf-8") as fh:
            trig_rows = list(csv.DictReader(fh))
        self.assertTrue(any(r["sku_model"] == "RTX 5070" for r in trig_rows))
        self.assertTrue(any(r["already_above"] == "True" for r in trig_rows))
        with open(self.paths["newsletter_html"], encoding="utf-8") as fh:
            html = fh.read()
        self.assertIn("<table>", html)
        self.assertIn("</table>", html)

        with open(self.paths["discontinuation_csv"], encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(len(rows), len(self.features))

    def test_api_payload_from_pipeline_data(self):
        from cgw import api
        code, payload = api.build_payload(self.con, "/v1/skus/summary", {"limit": ["5"]}, None)
        self.assertEqual(code, 200)
        self.assertTrue(payload["skus"])
        self.assertEqual(payload["asof"], self.features[0]["asof"])
        code, payload = api.build_payload(self.con, "/v1/memory/latest", {}, None)
        self.assertEqual(code, 200)
        self.assertIsNotNone(payload["guidance_mid_pct"])
        code, payload = api.build_payload(self.con, "/v1/signals", {"kind": ["shortage"]}, None)
        self.assertEqual(code, 200)
        self.assertTrue(all(s["kind"] == "shortage" for s in payload["signals"]))

    def test_source_health_reports_expected_gaps(self):
        health = {h["source_key"]: h for h in pipeline.source_health(self.con)}
        self.assertIn("trendforce_gddr_spot", health)
        self.assertGreater(health["trendforce_gddr_spot"]["ok_documents"], 0)
        # nothing may be silently missing: unrouted fetches are counted as failures
        self.assertTrue(any(h["failed_documents"] > 0 for h in health.values()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
