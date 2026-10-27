# Consumer GPU Allocation Watch — 2026-10-13

*Die allocation, memory contract prices, street prices and supply signals fused into per-SKU discontinuation and price-trigger forecasts. Every number below is derived from a dated public source; see the provenance footer.*

## Memory cost read

- **GDDR6 8Gb spot**: $12.450 per 8Gb device (+1.32% on the session, TrendForce print dated 2026-10-13 18:10 (GMT+8)).
- **Conventional DRAM contract prices**: +10% to +15% (Conventional DRAM contract prices are projected to grow 10–15% QoQ in 4Q26, while NAND Flash contract prices are expected to increase 15–20% Enterprise SSDs are the only category expected to see price growth accelerate due to strong demand …) — [AI Server Demand Sustains Memory Contract Price Increases in 4Q26, While Consumer-Side Pressure Persists, Says TrendForce](https://www.trendforce.com/presscenter/news/20260930-13258.html), 2026-09-30.
- Working assumption baked into the price path: **+12.5%** component-cost pressure over the next quarter, passed through at 55%.

## Die allocation read

- **AMD — latest quarter Q2 2026**
  - Gaming $3,800M in Q2 2026 (QoQ n/a, YoY +6.0%).
  - Data Center $6,700M in Q2 2026 (QoQ n/a, YoY +107.0%).
  - Allocation shift: +101.0 pts (dc_yoy_minus_gaming_yoy) — positive means data-centre growth is outpacing consumer graphics.
  - [Source](https://ir.amd.com/news-events/press-releases/detail/1295/amd-reports-second-quarter-2026-financial-results)
- **NVIDIA — latest quarter Q2 FY2027**
  - Gaming $3,700M in Q4 FY2026 (QoQ -13.0%, YoY +47.0%).
  - Data Center $89,000M in Q2 FY2027 (QoQ n/a, YoY +117.0%).
  - Edge Computing $7,200M (new disclosure bucket in Q2 FY2027).
  - Allocation shift: +130.0 pts (dc_yoy_minus_gaming_qoq) — positive means data-centre growth is outpacing consumer graphics.
  - **Gaming is no longer broken out from Q1 FY2027**; the latest Gaming datapoint is Q4 FY2026. The model keeps using it and flags it as a disclosure gap, not as current-quarter performance.
  - [Source](https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-fourth-quarter-and-fiscal-2026)

## Discontinuation watchlist

| SKU | Age (d) | Street vs MSRP | Stock breadth | Risk | EOL window | Top driver |
|---|---|---|---|---|---|---|
| RTX 4080 | 1427 | -16.6% † | 0% of 3 | 96% | 2026-10-26 → 2026-11-16 | time in market |
| RTX 5090 | 588 | +110.9% † | 0% of 9 | 94% | 2026-10-29 → 2026-11-22 | supply/EOL chatter |
| RTX 4060 Ti | 1238 | +30.3% † | 0% of 4 | 94% | 2026-10-30 → 2026-11-24 | time in market |
| RTX 4070 Ti | 1377 | +7.0% † | 0% of 3 | 94% | 2026-10-30 → 2026-11-24 | time in market |
| RTX 4060 | 1202 | +15.7% † | 0% of 3 | 94% | 2026-10-30 → 2026-11-24 | time in market |
| RTX 4090 | 1020 | +34.5% † | 0% of 4 | 93% | 2026-11-01 → 2026-11-29 | time in market |
| RX 7900 XT | 1400 | -13.8% † | 0% of 5 | 92% | 2026-11-02 → 2026-12-03 | time in market |
| RTX 4070 | 784 | -3.2% † | 0% of 4 | 92% | 2026-11-03 → 2026-12-07 | memory cost inflation |
| RX 7800 XT | 1133 | n/a | no listings | 88% | 2026-11-13 → 2026-12-31 | time in market |
| RTX 5070 | 588 | +63.9% | 38% of 8 | 87% | 2026-11-16 → 2027-01-07 | memory cost inflation |

## Street-price triggers

**Above a trigger right now (13 SKUs)** — highest level crossed per SKU, median of currently in-stock retailer listings:

- **RX 9060 XT** $670 vs $299 MSRP (+123.9%), through the 1.50× trigger at $448.
- **RTX 5090** $4,849 † vs $2,299 MSRP (+110.9%), through the 1.50× trigger at $3,448.
- **RTX 5080** $1,831 vs $999 MSRP (+83.3%), through the 1.50× trigger at $1,498.
- **RTX 5070 Ti** $1,250 vs $749 MSRP (+66.9%), through the 1.50× trigger at $1,124.
- **RTX 5060** $495 vs $299 MSRP (+65.5%), through the 1.50× trigger at $448.
- **RTX 5070** $900 vs $549 MSRP (+63.9%), through the 1.50× trigger at $824.
- **RTX 5060 Ti** $610 vs $379 MSRP (+60.9%), through the 1.50× trigger at $568.
- **RX 9070 XT** $866 vs $599 MSRP (+44.6%), through the 1.30× trigger at $779.
- **RTX 4090** $2,150 † vs $1,599 MSRP (+34.5%), through the 1.30× trigger at $2,079.
- **RTX 4060 Ti** $520 † vs $399 MSRP (+30.3%), through the 1.30× trigger at $519.
- **RX 7600** $340 vs $269 MSRP (+26.4%), through the 1.15× trigger at $309.
- **RTX 4060** $346 † vs $299 MSRP (+15.7%), through the 1.15× trigger at $344.
- **RTX 4070 Ti** $855 † vs $799 MSRP (+7.0%), through the 1.05× trigger at $839.

† price is the latest listing basis but no currently in-stock listing was observed, so treat it as a stale reference rather than a live street price.

**Nearest projected crossings (90-day horizon):**

| SKU | Trigger | Now | Projected (90d) | Cross prob. | ETA (days) |
|---|---|---|---|---|---|
| RX 7600 | 1.30× = $350 | $340 | $378 (+11.3%) | 89% | 23 |
| RX 9070 XT | 1.50× = $898 | $866 | $937 (+8.2%) | 74% | 41 |
| RTX 4070 Ti | 1.15× = $919 | $855 | $973 (+13.8%) | 81% | 49 |
| RTX 4070 | 1.05× = $629 | $580 | $663 (+14.3%) | 80% | 53 |
| RTX 4060 | 1.30× = $389 | $346 | $397 (+14.8%) | 63% | 75 |
| RTX 4090 | 1.50× = $2,398 | $2,150 | $2,447 (+13.8%) | 62% | 75 |

## Supply signals

- **SHORTAGE**: [Lenovo Legion Go 2 Price Hike Puts Ryzen Z2 Extreme Handheld Price Over $3,000](https://www.techpowerup.com/353682/lenovo-legion-go-2-price-hike-puts-ryzen-z2-extreme-handheld-price-over-usd-3-000) (techpowerup.com, Tue, 13 Oct 2026 18:09:54 +0000)
- **SHORTAGE**: [Intel’s Ex-CEO Pat Gelsinger Says HBM Is A “Hideous Memory,” Replete With Terrible Bit Density, And Thermal And Shoreline Bandwidth Issues, Even As Nanya Reiterates DRAM Shortages Till 2028](https://wccftech.com/intels-ex-ceo-pat-gelsinger-says-hbm-is-a-hideous-memory-replete-with-terrible-bit-density-and-thermal-and-shoreline-bandwidth-issues-even-as-nanya-reiterates-dram-shortages-till-2028/) (wccftech.com, Tue, 13 Oct 2026 15:48:02 +0000)
- **SHORTAGE**: [Framework Laptop 12 (Wildcat Lake) review: Growing up amid an unprecedented shortage](https://www.tomshardware.com/laptops/framework-laptop-12-review-wildcat-lake) (tomshardware.com, Tue, 13 Oct 2026 15:00:00 +0000)
- **SHORTAGE**: [AMD GPUs Get Price Hike in China with International Increases To Follow](https://www.techpowerup.com/353520/amd-gpus-get-price-hike-in-china-with-international-increases-to-follow) (techpowerup.com, Thu, 08 Oct 2026 18:48:33 +0000)
- **SHORTAGE**: [(PR) Rising Costs Threaten Notebook Demand in 2027, Raising Risks of Shipment Declines and Price Increase](https://www.techpowerup.com/353502/rising-costs-threaten-notebook-demand-in-2027-raising-risks-of-shipment-declines-and-price-increase) (techpowerup.com, Thu, 08 Oct 2026 11:50:06 +0000)
- **EOL** — `RTX 5090`: [NVIDIA Reportedly Ending the RTX 5090, Reserves GB202 Silicon for Workstation GPUs](https://www.techpowerup.com/353578/nvidia-reportedly-ending-the-rtx-5090-reserves-gb202-silicon-for-workstation-gpus) (techpowerup.com, Sat, 10 Oct 2026 11:36:04 +0000)

## Method and limits

- Model `cgw-0v1`, 18 SKUs scored, 72 trigger rows. Priors are hand-set; inputs are measured.
- Directional check: Spearman rho between generation age and risk = 0.653; risk rises with generation age = True.
- SKUs with listings but zero in-stock merchants: RTX 4060, RTX 4060 Ti, RTX 4070, RTX 4070 Ti, RTX 4080, RTX 4090, RTX 5090, RX 7900 XT.
- Not yet included: die-size/wafer-start counts, board-partner shipment data and paid memory contract prints. These are the highest-value paid inputs for v1.
- SKU prices are aggregated at *family* level (e.g. "RTX 5060 Ti" covers its 8 GB and 16 GB variants), so a mixed-variant retail shelf widens the median; per-variant bucketing is next on the list.
- Projections use a hand-set pass-through of 55% and a scarcity uplift capped at 20%; halving the uplift halves the projected move. Rows where the ±30% cap binds are flagged in the API payload (`projected_change_capped`).

## Provenance

| Source | Kind | Docs | Last fetch |
|---|---|---|---|
| [AMD Investor Relations press releases (RSS)](https://ir.amd.com/news-events/press-releases/rss) | allocation | 2/2 | 2026-10-13T23:36:41Z |
| [NowInStock.net AMD tracker](https://www.nowinstock.net/computers/videocards/amd/) | street | 5/5 | 2026-10-13T23:36:56Z |
| [NowInStock.net NVIDIA tracker](https://www.nowinstock.net/computers/videocards/nvidia/) | street | 13/13 | 2026-10-13T23:36:53Z |
| [NVIDIA Newsroom financial results](https://nvidianews.nvidia.com/news?q=financial+results) | allocation | 5/5 | 2026-10-13T23:36:40Z |
| [Reddit public RSS (hardware/supply chatter)](https://www.reddit.com/r/hardware/new/.rss) | signal | 2/2 | 2026-10-13T23:37:00Z |
| [TechPowerUp news RSS](https://www.techpowerup.com/rss/news) | signal | 1/1 | 2026-10-13T23:37:01Z |
| [Tom's Hardware RSS](https://www.tomshardware.com/feeds/all) | signal | 1/1 | 2026-10-13T23:37:01Z |
| [TrendForce DRAM Contract Price](https://www.trendforce.com/price/dram/dram_contract) | memory | 1/1 | 2026-10-13T23:36:32Z |
| [TrendForce DRAM Spot Price](https://www.trendforce.com/price/dram/dram_spot) | memory | 1/1 | 2026-10-13T23:36:32Z |
| [TrendForce GDDR Spot Price](https://www.trendforce.com/price/dram/gddr_spot) | memory | 1/1 | 2026-10-13T23:36:31Z |
| [TrendForce Press Center (Semiconductors)](https://www.trendforce.com/presscenter/news/Semiconductors) | memory | 6/6 | 2026-10-13T23:36:37Z |
| [Wccftech RSS](https://wccftech.com/feed/) | signal | 1/1 | 2026-10-13T23:37:01Z |
| [Wikipedia: List of AMD GPUs](https://en.wikipedia.org/wiki/List_of_AMD_graphics_processing_units) | sku | 1/1 | 2026-10-13T23:36:42Z |
| [Wikipedia: List of Nvidia GPUs](https://en.wikipedia.org/wiki/List_of_Nvidia_graphics_processing_units) | sku | 1/1 | 2026-10-13T23:36:42Z |

*Generated 2026-10-13 23:37 UTC by ConsumerGPU Allocation Watch. Quotes reproduced for attribution; see each source's terms.*