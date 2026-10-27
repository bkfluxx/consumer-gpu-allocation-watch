"""Model tests: risk ordering, trigger maths, trend-direction handling.

These run entirely on synthetic rows shaped exactly like the real ones, so they
test the model logic (not the parsers). The directional claims asserted here are
the same ones the newsletter's validation block reports on live data.
"""
from __future__ import annotations

import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cgw import config, forecast as fc, fuse, store

NOW = time.time()


def build_db(path: str):
    con = store.connect(path)
    skus = [
        # model, vendor, series, launch, msrp, tdp, memgen, memgb
        ("RTX 4060", "nvidia", "RTX 40", "June 29, 2023", 299, 115, "GDDR6", 8),
        ("RTX 5070", "nvidia", "RTX 50", "March 4, 2025", 549, 250, "GDDR7", 12),
        ("RTX 4080", "nvidia", "RTX 40", "November 16, 2022", 1199, 320, "GDDR6X", 16),
        ("RTX 5060", "nvidia", "RTX 50", "May 19, 2025", 299, 145, "GDDR7", 8),
    ]
    for model, vendor, series, launch, msrp, tdp, gen, gb in skus:
        con.execute("INSERT OR REPLACE INTO sku(model,vendor,series,launch_date,msrp_usd,tdp_w,"
                    "memory_gen,memory_gb,source_url,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (model, vendor, series, launch, msrp, tdp, gen, gb, "https://example.test/sku", NOW))
    # street: 4060 deeply discounted and fully in stock; 5070 at MSRP; 4080 at 2x
    street = [("RTX 4060", "Amazon", 200.0, "IN_STOCK"), ("RTX 4060", "Newegg", 190.0, "IN_STOCK"),
              ("RTX 5070", "Amazon", 549.0, "IN_STOCK"), ("RTX 5070", "Newegg", 555.0, "OUT_OF_STOCK"),
              ("RTX 4080", "Amazon", 2398.0, "IN_STOCK")]
    for model, merch, price, stock in street:
        con.execute("INSERT OR REPLACE INTO street_obs(sku_model,merchant,product_name,price_usd,"
                    "stock,observed_at,source_url) VALUES (?,?,?,?,?,?,?)",
                    (model, merch, f"{merch} card", price, stock,
                     time.strftime("%b %d %y - %I:%M %p", time.localtime()),
                     "https://example.test/street"))
    # allocation: gaming down 12% QoQ, data centre up 20%
    for seg, rev, qoq, yoy in (("Gaming", 3700, -13.0, -12.0), ("Data Center", 62300, 22.0, 75.0)):
        con.execute("INSERT OR REPLACE INTO segment_fin(vendor,period_label,segment,revenue_musd,"
                    "qoq_pct,yoy_pct,published,release_url,quote,fetched_at)"
                    " VALUES ('nvidia','Q4 FY2026',?,?,?,?,?,?,?,?)",
                    (seg, rev, qoq, yoy, "February 26, 2026", "https://example.test/pr",
                     f"{seg} revenue was ${rev/1000:.1f} billion, "
                     f"{'up' if qoq>0 else 'down'} {abs(qoq):.0f}% from the previous quarter", NOW))
    # memory: GDDR6 spot print + DRAM contract guidance
    con.execute("INSERT OR REPLACE INTO memory_spot(source_key,grade,unit,ts,weekly_high,weekly_low,"
                "session_high,session_low,session_avg,avg_change_pct,fetched_at,url)"
                " VALUES ('trendforce_gddr_spot','GDDR6','8Gb','2026-10-13 18:10 (GMT+8)',18.0,10.2,"
                "18.0,10.2,12.45,1.32,?,'https://example.test/gddr')", (NOW,))
    con.execute("INSERT OR REPLACE INTO memory_guide(source_key,url,published,title,metric,low_pct,"
                "high_pct,quote,fetched_at) VALUES ('trendforce_news','https://example.test/tf',"
                "'2026-09-30','TF 4Q26','DRAM',10.0,15.0,'Conventional DRAM contract prices are "
                "projected to grow 10-15% QoQ in 4Q26',?)", (NOW,))
    # signals: an EOL headline attached to the 4060
    con.execute("INSERT OR REPLACE INTO signals(subreddit,title,link,published,kind,matched,"
                "sku_model,source_url,fetched_at) VALUES ('r/hardware','RTX 4060 reaches end of life',"
                "'https://example.test/1','2026-10-12T00:00:00Z','eol','end of life','RTX 4060',"
                "'https://example.test/feed',?)", (NOW,))
    con.commit()
    return con


class ModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = os.path.join(config.ROOT, "data", "test_model.db")
        if os.path.exists(cls.tmp):
            os.remove(cls.tmp)
        cls.con = build_db(cls.tmp)
        cls.feats = fuse.build_features(cls.con)
        cls.by = {f["sku_model"]: f for f in cls.feats}

    @classmethod
    def tearDownClass(cls):
        cls.con.close()
        for suffix in ("", "-wal", "-shm"):
            p = cls.tmp + suffix
            if os.path.exists(p):
                os.remove(p)

    def test_features_cover_every_sku(self):
        self.assertEqual(len(self.feats), 4)
        self.assertTrue(all(f["discontinuation_risk"] is not None for f in self.feats))
        self.assertTrue(all(f["sku_source_url"] for f in self.feats))

    def test_risk_prefers_old_and_discounted(self):
        self.assertGreater(self.by["RTX 4060"]["discontinuation_risk"],
                           self.by["RTX 5070"]["discontinuation_risk"])
        self.assertGreater(self.by["RTX 4080"]["discontinuation_risk"],
                           self.by["RTX 5060"]["discontinuation_risk"])

    def test_age_feature_and_estimate_flag(self):
        self.assertFalse(self.by["RTX 5070"]["age_estimated"])
        self.assertGreater(self.by["RTX 5070"]["age_days"], 400)

    def test_street_aggregates(self):
        s = self.by["RTX 4060"]["street"]
        self.assertEqual(s["median"], 195.0)
        self.assertEqual(s["in_stock_share"], 1.0)
        self.assertEqual(s["price_basis"], "in_stock_and_fresh")
        self.assertAlmostEqual(self.by["RTX 4060"]["street_premium_pct"], 195 / 299 - 1, places=3)

    def test_allocation_and_memory_inputs(self):
        f = self.by["RTX 4060"]
        self.assertEqual(f["allocation"]["gaming_qoq_pct"], -13.0)
        self.assertEqual(f["allocation"]["allocation_shift"], 35.0)
        self.assertEqual(f["memory_cost"]["gddr6_usd_per_8gb"], 12.45)
        self.assertEqual(f["memory_cost"]["guidance_mid_pct"], 12.5)
        self.assertGreater(f["memory_cost"]["est_vram_cost_usd"], 50)

    def test_signal_pressure_applied(self):
        self.assertEqual(self.by["RTX 4060"]["signals"]["n_eol"], 1)
        self.assertGreater(self.by["RTX 4060"]["pressures"]["signals"], 0)
        self.assertEqual(self.by["RTX 5070"]["signals"]["n_eol"], 0)

    def test_discontinuation_forecast_shape(self):
        out = fc.discontinuation(self.feats)
        self.assertEqual(len(out), 4)
        top = out[0]
        self.assertIn(top["sku_model"], ("RTX 4060", "RTX 4080"))
        self.assertEqual(len(top["risk_band"]), 2)
        self.assertLess(top["risk_band"][0], top["risk_band"][1])
        self.assertEqual(len(top["eol_window_dates"]), 2)
        self.assertTrue(top["top_drivers"])
        self.assertEqual(top["model_version"], fc.MODEL_VERSION)

    def test_trigger_levels_and_already_above(self):
        trig = fc.price_triggers(self.by["RTX 4080"])
        levels = [t["trigger_level"] for t in trig]
        self.assertEqual(levels, list(config.TRIGGER_LEVELS))
        self.assertTrue(all(t["already_above"] for t in trig))       # 2x MSRP
        self.assertAlmostEqual(trig[-1]["trigger_usd"], 1199 * 1.5, delta=0.01)

    def test_projection_is_bounded_and_upward(self):
        trig = fc.price_triggers(self.by["RTX 4060"])
        t = trig[1]
        self.assertGreater(t["projected_median_usd_90d"], t["current_median_usd"])
        self.assertLessEqual(abs(t["projected_change_pct_90d"]), config.PRIORS.max_projected_change + 1e-9)
        self.assertFalse(t["already_above"])
        self.assertTrue(t["sources"])

    def test_missing_street_price_is_reported_not_invented(self):
        feat = dict(self.by["RTX 5070"])
        feat["street"] = {"n_priced": 0, "in_stock_share": 0.0, "median": None, "source_urls": []}
        trig = fc.price_triggers(feat)
        self.assertTrue(all(t["status"] == "no_street_price" for t in trig))
        self.assertTrue(all(t["current_median_usd"] is None for t in trig))

    def test_validation_reports_direction(self):
        v = fc.validation(self.feats)
        self.assertTrue(v["checks"]["risk_increases_with_generation_age"])
        self.assertGreater(v["checks"]["generation_vs_risk_spearman"], 0)

    def test_persist_and_reload_roundtrip(self):
        fuse.persist_features(self.con, self.feats)
        out = fc.run_all(self.feats)
        fc.persist(self.con, out)
        loaded = fc.load_latest(self.con)
        self.assertEqual(len(loaded["discontinuation"]), 4)
        self.assertTrue(loaded["price_triggers"])
        self.assertEqual(loaded["validation"]["checks"]["n_skus_scored"], 4)


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = os.path.join(config.ROOT, "data", "test_api.db")
        if os.path.exists(cls.tmp):
            os.remove(cls.tmp)
        cls.con = build_db(cls.tmp)
        feats = fuse.build_features(cls.con)
        fuse.persist_features(cls.con, feats)
        fc.persist(cls.con, fc.run_all(feats))
        cls.con.execute("INSERT OR REPLACE INTO api_keys(key,label,tier,created_at,active)"
                        " VALUES ('test-free','t','free',?,1),('test-pro','t','pro',?,1)",
                        (NOW, NOW))
        cls.con.commit()

    @classmethod
    def tearDownClass(cls):
        cls.con.close()
        for suffix in ("", "-wal", "-shm"):
            p = cls.tmp + suffix
            if os.path.exists(p):
                os.remove(p)

    def test_health_and_meta_are_open(self):
        from cgw import api
        code, payload = api.build_payload(self.con, "/v1/health", {}, None)
        self.assertEqual(code, 200)
        code, payload = api.build_payload(self.con, "/v1/meta", {}, None)
        self.assertEqual(code, 200)
        self.assertIn("sources", payload)
        self.assertTrue(all(s["documents"] >= 0 for s in payload["sources"]))

    def test_key_resolution_and_tier_gating(self):
        from cgw import api
        free = api.resolve_key(self.con, "test-free")
        pro = api.resolve_key(self.con, "test-pro")
        self.assertEqual(free["tier"], "free")
        self.assertTrue(any(e.startswith("memory") for e in free["endpoints"]))
        self.assertNotIn("*", free["endpoints"])
        self.assertNotIn("*", pro["endpoints"])          # only the desk tier is wildcard
        self.assertIn("forecasts/discontinuation", pro["endpoints"])
        self.assertTrue(pro["requests_per_day"] > free["requests_per_day"])
        self.assertIsNone(api.resolve_key(self.con, "nope"))

    def test_forecast_endpoint_filters(self):
        from cgw import api
        code, payload = api.build_payload(self.con, "/v1/forecasts/discontinuation",
                                          {"min_risk": ["0.5"], "limit": ["2"]}, None)
        self.assertEqual(code, 200)
        self.assertLessEqual(len(payload["rows"]), 2)
        self.assertTrue(all(r["discontinuation_risk"] >= 0.5 for r in payload["rows"]))
        code, payload = api.build_payload(self.con, "/v1/forecasts/price-triggers",
                                          {"already_above": ["true"]}, None)
        self.assertEqual(code, 200)
        self.assertTrue(all(r["already_above"] for r in payload["rows"]))

    def test_unknown_path_is_404(self):
        from cgw import api
        code, payload = api.build_payload(self.con, "/v1/nope", {}, None)
        self.assertEqual(code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
