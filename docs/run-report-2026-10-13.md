# Run report — 2026-10-13 (first live end-to-end run)

Everything below is what the pipeline actually produced on 2026-10-13, not a plan.

## Commands

```bash
rm -f data/cgw.db*
python3 -m cgw.cli all                     # collect -> fuse -> forecast -> report
python3 -m cgw.cli keys --bootstrap        # provision demo API keys per tier
python3 -m unittest discover -s tests -t . # 36 tests
bash tools/api_smoketest.sh                # live API over real HTTP
```

Collection: **41 HTTP fetches in 30.8 s**.

| Table | Rows |
|---|---|
| raw_documents (audit) | 35 |
| memory_spot | 6 |
| memory_guide | 2 |
| segment_fin | 13 |
| sku | 18 |
| street_obs (per-merchant listings) | 1107 |
| signals | 263 |

Source errors recorded (not silently dropped): the AMD RX 7800 XT tracker slug is no
longer in the tracker index; one Reddit search feed returned HTTP 429 (expected
throttling — the model treats it as a gap, not as "no signals exist").

## What the fused data says on this date

* **Memory**: GDDR6 8Gb spot $12.450 (+1.32% session, TrendForce print 2026-10-13);
  conventional DRAM contract prices guided **+10–15% QoQ for 4Q26**
  ([TrendForce, 2026-09-30](https://www.trendforce.com/presscenter/news/20260930-13258.html)).
* **Allocation**: NVIDIA Q4 FY2026 Gaming $3.7B (**−13% QoQ**, +47% YoY) against Data
  Center $62.3B (+22% QoQ, +75% YoY); Data Center reached $89.0B in Q2 FY2027 (+117%
  YoY) — and from **Q1 FY2027 NVIDIA stopped disclosing a Gaming line at all**, which
  the pipeline detects and reports as a disclosure gap instead of carrying a stale
  number as current. AMD Q2 2026: Gaming $3.8B (+6% YoY) vs Data Center $6.7B (+107% YoY).
* **Street**: 13 of 18 tracked SKUs are above at least one MSRP trigger on the current
  in-stock listing basis (RTX 5090 $4,849 = 2.11× MSRP; RTX 5080 1.83×; RTX 5070 1.64×;
  RX 9060 XT 2.24×). Nine SKUs have zero in-stock merchants across the tracked
  retailers, which is one of the model's strongest EOL signals.
* **Signals**: `NVIDIA Reportedly Ending the RTX 5090, Reserves GB202 Silicon for
  Workstation GPUs` (TechPowerUp, 2026-10-10) and the same story on r/hardware — the
  exact thesis the product trades on, captured automatically and attached to the SKU.
* **Discontinuation board** (top of the list): RTX 4080 96%, RTX 5090 94%,
  RTX 4060 Ti 94%, RTX 4070 Ti 94%, RTX 4090 93%, RX 7900 XT 92%.
  Self-validation on this run: Spearman ρ = 0.653 between generation age and risk,
  monotonic across generations, 18 SKUs scored.

## Verification evidence

* `tests/`: **36 tests, OK.** Parser tests assert values taken from the recorded pages
  (GDDR6 8Gb at 12.45 / +1.32%; NVIDIA Q4 FY2025 Gaming $2.5B −22% QoQ −11% YoY and Data
  Center $35.6B +16%/+93%; ASUS RTX 5070 PRIME $869.99 on Amazon from the tracker;
  RTX 5070 launch MSRP $549 on March 4 2025). Model tests cover risk ordering, bounded
  projections, missing-price handling and API tier gating. The end-to-end test runs
  the whole pipeline offline on 13 recorded fixtures.
* `tools/api_smoketest.sh`: server starts, all endpoints exercised. Observed:
  `/v1/health` 200 without a key; `/v1/meta` reports 14 sources with freshness;
  protected endpoint without a key → **401**; free key on a pro endpoint → **403**
  (`included: health, meta, memory/latest, skus/summary`); pro key returns forecasts,
  triggers, allocation and signals; `X-RateLimit-Remaining: 198` on the free tier;
  server log clean of tracebacks.

## Bugs found and fixed during this run (kept here as a record)

1. NVIDIA's newsroom nav ("Gaming & Entertainment") was being paired with the
   total-revenue sentence → segment parsing rewritten to anchor on a tracked segment
   vocabulary and to cut each percentage's context at the next figure/segment.
2. Percentage order is not stable across releases (Q4 FY2026 leads with YoY) → QoQ/YoY
   are now classified by the words that follow each percentage, not by position.
3. Retailer timestamps were being ordered as strings, so "Sep 20 26" outranked
   "Oct 13 26" → a parsed `observed_ts` epoch is stored and used for "latest per
   merchant".
4. Placeholder "$99,999" retailer prices were polluting per-SKU medians → dropped at
   parse time (sentinel threshold).
5. `ThreadingHTTPServer` handed one SQLite connection to many threads → the API now
   opens a per-request connection.

## Known gaps (unchanged by this run)

Hand-set model priors with no outcome-fitted calibration yet; family-level (not
variant-level) price aggregation; no wafer-start / board-partner shipment data; GDDR7
has no free spot feed, so its $/GB is scaled from GDDR6 and flagged. See
`docs/model.md` §4 for the path to a calibrated model.
