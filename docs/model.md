# Model notes (v0)

Two models run per SKU. Both are deterministic functions of measured inputs; the
coefficients are hand-set priors, declared in `cgw/config.py::ModelPriors` so a
subscriber or reviewer can re-weight them.

## 1. Discontinuation risk

Each feature is first mapped into a 0..1 "pressure" score:

| Feature | Pressure formula | Reads |
|---|---|---|
| `age` | `sigmoid((age_days − 620) / 190)` | SKU age from the Wikipedia launch date (series median if the date cell is missing; flagged `age_estimated`) |
| `discount` | `clip((−premium − 0.08) / 0.20)` | street median vs launch MSRP: a >8% discount is treated as clearance |
| `scarcity` | `1 − in_stock_share` | share of tracked merchants currently in stock |
| `memory_cost` | `clip(guidance_mid% × (vram_share/0.16) / 15)` | TrendForce contract-price guidance scaled by the SKU's measured VRAM cost share |
| `allocation` | `clip(−gaming_trend% / 25)` | vendor Gaming revenue trend (QoQ preferred, YoY fallback, basis recorded) |
| `signals` | `clip((1.0·eol + 0.4·shortage + 0.5·eol_series + 0.2·shortage_series) / 2)` | classified headlines in the window |
| `generation` | `clip(generation_index / 2)` | 0 = current series, 1 = previous, 2 = two back |

```
z = −1.15
  + 1.10·age + 1.45·discount + 0.85·scarcity + 0.90·memory_cost
  + 1.25·allocation + 1.00·signals + 0.80·generation
risk = 1 / (1 + exp(−z))
```

Reported risk band is `risk ± 0.09` (a display convention, not a confidence
interval). Expected time to EOL is `(1 − risk) × 5` quarters, window `[0.6q, 1.5q]`
converted to dates.

Directional self-validation is computed from live data on every run and shipped
in the newsletter and API: Spearman ρ between generation position and risk, plus a
monotonicity check across generations. On the 2026-10-13 run: **ρ = 0.76, monotone =
true, 18 SKUs scored**. This confirms ordering, not calibration.

## 2. Street-price trigger crossings

Trigger levels are multiples of launch MSRP: 1.05×, 1.15×, 1.30×, 1.50×.

```
share       = VRAM cost / MSRP          (clamped to [0.05, 0.60]; 0.16 reference when VRAM unknown, flagged)
cost_delta  = guidance_mid × share × horizon_quarters
uplift      = 0.20 × (1 − in_stock_share) × (1 − 0.4·risk)      # scarcity term
change      = clip(0.55·cost_delta + uplift, −0.30, +0.30)
projected   = median_now × (1 + change)
```

* `0.55` = share of component inflation assumed to reach street prices.
* `0.20` = maximum uplift attributed to scarcity (the largest single uncertainty in
  the model; halving it halves the projected move — `projected_change_capped`
  flags where the ±30% cap binds).
* Crossing score is `sigmoid((projected − trigger) / (0.04·trigger))`, and ETA is a
  linear interpolation between today's median and the 90-day projection.

Every trigger row carries its inputs (`memory_cost_delta_pct_of_msrp`,
`memory_share_of_msrp`, `scarcity_uplift_pct`, `pass_through_assumed`,
`n_merchants_priced`) and the source URLs, so the forecast can be argued with.

## 3. Price basis rules

The SKU median is not "the cheapest listing". It is the median over the latest
observation per merchant, restricted to:

1. in-stock listings observed within 14 days → `price_basis = in_stock_and_fresh`
2. otherwise all priced listings → `price_basis = stale_or_out_of_stock_listings_only`,
   surfaced with a `†` in the newsletter and the flag in the API

Placeholder prices (≥ $20,000 "ask us" entries) are dropped at parse time.

## 4. Roadmap to a calibrated model

1. Accumulate daily forecast snapshots (the `forecasts` table is already keyed by
   `asof`) and score them against realised EOL dates and street prices.
2. Add the paid inputs where the money is: quarterly wafer-start and die-allocation
   estimates, board-partner shipment volumes, paid memory contract prints.
3. Fit the weights (logistic regression or gradient boosting) on that history and
   replace the hand priors, keeping the feature contributions as the explanation.
