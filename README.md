# ConsumerGPU Allocation Watch (CGW)

Tracks where graphics silicon and memory capacity are actually going — gaming
cards vs professional/data-centre parts, memory contract prices, retailer stock
and street prices — and turns that into per-SKU forecasts: **which consumer GPUs
are next to be discontinued, and when a card's street price crosses a trigger
level.**

Product shape: a newsletter (free/paid tier) plus a JSON API. Both are generated
from the same fusion pipeline; nothing is written by hand.

*Status: working prototype, v0. Runs end to end against live public sources.*

---

## Why this exists (the signal being sold)

In the current cycle the consumer GPU market is being squeezed from two sides at
once, and both sides are publicly observable if you watch the right feeds:

1. **Allocation.** Capacity moves to data-centre and professional parts. NVIDIA's
   own releases show Gaming at **$3.7B in Q4 FY2026 (−13% QoQ)** while Data Center
   grew to **$62.3B (+22% QoQ)**, and from fiscal 2027 NVIDIA stopped breaking the
   Gaming line out at all — the disclosure itself went away.
2. **Memory cost.** TrendForce's public prints show GDDR6 8Gb spot at **$12.45
   (+1.32%)** with conventional DRAM contract prices guided **+10–15% QoQ for
   4Q26**, i.e. board BOMs inflate while retail demand stays soft.

Add retailer stock/street data and the trade-press signal stream and you can
forecast, per SKU, which cards are heading for EOL and when a street price will
break a threshold. That is the product.

## Data sources (all live, all cited, all re-checkable)

| Source | Kind | What it yields | Refresh |
|---|---|---|---|
| TrendForce GDDR spot price | memory | GDDR5/GDDR6 8Gb weekly high/low/session average + change | daily |
| TrendForce DRAM spot & contract pages | memory | DRAM/module spot and contract prints | daily/monthly |
| TrendForce press releases | memory | quantified contract-price guidance (e.g. "+10–15% QoQ") | daily |
| NVIDIA Newsroom financial results | allocation | per-quarter segment revenue (Gaming vs Data Center vs Edge Computing) | quarterly |
| AMD IR press-release RSS | allocation | per-quarter segment revenue (Gaming, Data Center, Client, Embedded) | quarterly |
| NowInStock.net trackers (NVIDIA/AMD) | street | per-merchant price, stock status, timestamp, per SKU | hourly |
| Reddit public RSS (`r/hardware`) | signal | supply/EOL/restock chatter | hourly |
| TechPowerUp / Tom's Hardware / Wccftech RSS | signal | GPU supply, launch and EOL reporting | hourly |
| Wikipedia GPU lists (CC BY-SA) | SKU reference | launch date, launch MSRP, TDP, memory generation | weekly |

Retailer trackers are used instead of scraping retailers directly: Newegg,
Micro Center, Best Buy and B&H all block plain HTTP clients, and a paid product
should not be built on a scraper that breaks weekly. Every fetch is stored
byte-for-byte in `raw_documents` with a SHA-256, so any number in the newsletter
can be traced back to the exact page it came from.

## Pipeline

```
collect  -> raw_documents (audit, gzipped) + typed tables
fuse     -> per-SKU feature vector with provenance per feature
forecast -> discontinuation risk + EOL window; street-price trigger crossings
report   -> newsletter (md + html), CSVs, JSON; API serves the same data
```

Per-SKU features: SKU age, street premium vs launch MSRP, retail stock breadth,
merchant spread, measured VRAM cost share of the board, memory contract-price
pressure, vendor allocation shift (Gaming trend vs Data Center trend), EOL /
shortage signal counts, and generation position. The risk model is a logistic
combination of those features with hand-set weights (see
[`docs/model.md`](docs/model.md)); the price path is a pass-through model over the
measured memory-cost delta plus a scarcity term, capped at ±30% per horizon.

## Run it

```bash
python3 -m pip install -r requirements.txt      # only `requests`
python3 -m cgw.cli all                          # collect -> fuse -> forecast -> report
python3 -m cgw.cli keys --bootstrap             # provision demo API keys
python3 -m cgw.cli serve --port 8787            # JSON API
```

Outputs land in `out/` (`newsletter_<date>.md/.html`, `discontinuation_<date>.csv`,
`price_triggers_<date>.csv`, `forecasts_<date>.json`); the database is `data/cgw.db`.

Useful flags: `--max-skus N` (smoke runs), `CGW_DATA_DIR` / `CGW_OUT_DIR` /
`CGW_DB` overrides.

### Tests

```bash
python3 -m unittest discover -s tests -t . -v
```

Three layers:

* `tests/test_parsers.py` — parser tests pinned to **real upstream markup**
  exported from the pipeline's own raw audit trail (`tools/export_fixtures.py`).
  They assert the actual values those pages served (GDDR6 8Gb at 12.45 / +1.32%,
  NVIDIA Q4 FY2025 Gaming $2.5B −22% QoQ −11% YoY and Data Center $35.6B +16%/+93%,
  ASUS RTX 5070 PRIME at $869.99 on Amazon from the tracker, RTX 5070 launch MSRP
  $549 on March 4 2025). If a source changes its markup, these fail loudly.
* `tests/test_model.py` — model behaviour on synthetic rows: risk ordering, trigger
  maths, bounded projections, missing-data handling, API tier gating.
* `tests/test_e2e.py` — recorded-fixture run of the whole pipeline with no network;
  asserts every table fills, real values survive, and the report artefacts are
  written (a fixture-missing SKU must come out with no price, never a guessed one).

## What is measured vs what is assumed

Measured (from sources): every price, stock status, segment revenue, memory print,
contract-price guidance, launch date, MSRP, headline.

Assumed (priors, all in `cgw/config.py`): risk weights, the clearance/age
thresholds, the BOM pass-through (0.55), the scarcity uplift (0.20), the ±30% cap,
and the GDDR7 $/GB multiplier (no free public GDDR7 spot feed exists). The
newsletter states the pass-through assumption inline, and the API exposes each
contribution so a subscriber can re-weight it.

Known limitations, stated rather than hidden:

* No outcome-fitted calibration yet — the model orders SKUs and explains why, it
  is not (yet) a probability calibrated against realised EOL events. The pipeline
  records one forecast snapshot per day so calibration becomes possible as
  history accumulates.
* Gaming revenue disclosure gaps are surfaced, not interpolated: NVIDIA's fiscal
  2027 releases have no Gaming line, so the model carries the last datapoint and
  labels it stale.
* AMD's SKU pages carry fewer priced listings than NVIDIA's; SKUs with no
  in-stock listing are flagged (`†`) rather than being given a synthetic price.
* Prices are aggregated at **family** level, so a "RTX 5060 Ti" median blends its
  8 GB and 16 GB variants; per-variant bucketing is the next slice of work.
* Die-size/wafer-start counts, board-partner shipment volumes and paid memory
  contract prints are the obvious v1 paid inputs.

## Monetisation

See [`docs/product.md`](docs/product.md): free tier (freshness + memory prints +
top-line board), Pro API at $199/mo (full forecasts, allocation series, signal
stream) and a Desk tier at $499/mo (alert webhooks + quarterly review call).
API keys, tiers and rate limits are implemented in `cgw/api.py`.

## Layout

```
cgw/
  config.py        sources, tracked SKUs, model priors, API tiers
  http.py          polite fetcher (per-host throttle, 429 backoff, hashing)
  htmltab.py       nesting-aware HTML table extractor (stdlib only)
  store.py         SQLite schema, raw audit trail, upserts
  pipeline.py      collect -> DB, source health
  fuse.py          per-SKU feature fusion
  forecast.py      discontinuation risk + price-trigger model + self-validation
  report.py        newsletter (md/html), CSV/JSON exports
  api.py           JSON API with key auth, tiers, rate limits
  cli.py           collect | fuse | forecast | report | all | keys | serve
  sources/         one module per source family (pure parsers + collectors)
tools/export_fixtures.py   export real pages from the audit trail for tests
docs/                      model.md, api.md, product.md
out/                       generated newsletter and data exports
```
