# API reference

`python3 -m cgw.cli serve --host 127.0.0.1 --port 8787`

Auth: `X-API-Key` header (or `?key=`). Keys live in the `api_keys` table; tiers and
daily limits are declared in `cgw/config.py`. `/v1/health` and `/v1/meta` are open so
status monitors work without a key. 401/403/429 responses are JSON with an `error`
field; every response carries `asof` and `generated_at`.

| Endpoint | Tier | Notes |
|---|---|---|
| `GET /v1/health` | open | service status, DB path, model version |
| `GET /v1/meta` | open | per-source freshness, document counts, licences, attribution requirement |
| `GET /v1/memory/latest` | free | current GDDR/DRAM spot prints + contract-price guidance + working assumption |
| `GET /v1/memory/history?limit=` | pro | spot prints over time (accumulates from the first run) |
| `GET /v1/skus/summary` | free | top-line board: SKU, MSRP, street median, premium, risk, stock share |
| `GET /v1/skus` | pro | full per-SKU feature vectors incl. provenance URLs |
| `GET /v1/forecasts/discontinuation?min_risk=&vendor=&limit=` | pro | risk, band, EOL window, top drivers, evidence |
| `GET /v1/forecasts/price-triggers?vendor=&already_above=&limit=` | pro | per-SKU per-trigger projections, crossing scores, ETA, drivers |
| `GET /v1/allocation` | pro | per-vendor segment revenue, trends, allocation shift, disclosure gaps |
| `GET /v1/signals?kind=eol\|shortage\|restock\|launch&limit=` | pro | classified headlines with links |

Example:

```bash
curl -s -H "X-API-Key: demo-free-key" \
  'http://127.0.0.1:8787/v1/forecasts/discontinuation?min_risk=0.8&limit=3' | python3 -m json.tool
```

Response shape (truncated):

```json
{
  "asof": "2026-10-13",
  "model_version": "cgw-0v1",
  "rows": [
    {
      "sku_model": "RX 7900 XT",
      "discontinuation_risk": 0.96,
      "risk_band": [0.87, 0.99],
      "expected_quarters_to_eol": 0.2,
      "eol_window_dates": ["2026-10-26", "2026-11-16"],
      "top_drivers": [
        {"feature": "discount", "label": "street clearing below MSRP", "contribution": 1.07},
        {"feature": "age", "label": "time in market", "contribution": 0.87}
      ],
      "evidence": {"age_days": 1400, "street_premium_pct": -0.238, "in_stock_share": 0.0},
      "sources": ["https://en.wikipedia.org/wiki/List_of_AMD_graphics_processing_units", "..."]
    }
  ],
  "validation": {"checks": {"generation_vs_risk_spearman": 0.76}}
}
```

Tiers (`cgw keys --bootstrap` provisions one demo key per tier):

| Tier | Price | Limit | Endpoints |
|---|---|---|---|
| `free` | $0 | 200 req/day | health, meta, memory/latest, skus/summary |
| `pro` | $199/mo | 20,000 req/day | all of the above + skus, forecasts, allocation, signals, memory/history |
| `desk` | $499/mo | 100,000 req/day | everything, plus alert webhooks and a quarterly review call (webhooks: next) |

Attribution is required for `free`; the newsletter already cites every figure with
its source URL and publication date.
