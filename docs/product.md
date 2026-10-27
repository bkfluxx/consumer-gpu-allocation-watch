# Product notes: newsletter + API

## Who buys this

1. **Board partners and system integrators** — need to know which SKUs are safe to
   build a production run around and which are about to be cut, before the vendor
   tells them. Budget line: procurement risk.
2. **Retail buyers and distributors** — want to buy ahead of a price trigger, not
   after. Budget line: margin on inventory.
3. **Traders, refurbishers and repair shops** — the used/refurb market reprices off
   new-card street prices with a lag.
4. **Analysts and journalists** — need a sourced, dated series rather than a
   screenshot; the provenance trail is the sellable part.
5. **Data-driven consumers** (the free tier) — "should I buy now or wait".

## Packaging

| Tier | Price | What you get | Why it prices here |
|---|---|---|---|
| Newsletter / free API | $0 | weekly newsletter, freshness metadata, memory prints, top-line board | acquisition and credibility; the provenance footer is the marketing |
| Pro API | $199/mo | full per-SKU forecasts, trigger projections with drivers, allocation series, signal stream, 20k req/day | one avoided bad buy-order pays for years of it |
| Desk | $499/mo | Pro + alert webhooks on trigger crossings/EOL signals + quarterly review call + 100k req/day | workflow embedding: alerts go into the buyer's procurement system |

Design rules that come from the buyer list:

* **Never publish an unsourced number.** Every figure carries source URL + date, and
  the API exposes the raw audit reference.
* **Flag what is stale or missing** rather than interpolating it (the `†` basis mark,
  the Gaming disclosure-gap note, `no_street_price` status).
* **Explain each forecast**: `top_drivers` plus the input values are in the payload,
  so a desk analyst can disagree with a specific assumption instead of the whole thing.
* **Alert on transitions, not levels**: trigger crossings, new EOL chatter, and
  disclosure changes (e.g. a vendor dropping the Gaming line) are the events worth a push.

## Costs and unit economics (prototype numbers)

* Collection run: ~43 HTTP fetches, ~46 s wall clock, all keyless public sources. The
  heavy pages (two Wikipedia GPU lists, ~3.6 MB each) are fetched weekly, not hourly.
* Storage: raw bodies are gzipped in SQLite; a month of hourly tracker runs lands in
  the low hundreds of MB. A single small VPS covers v0; no per-fetch vendor fees.
* Marginal cost of a newsletter subscriber or API call is effectively zero, so the
  business is limited by data quality and distribution, not by infrastructure.

## Rollout

1. **Weeks 1–2** — run `cgw all` on an hourly cron, publish the newsletter weekly,
   accumulate daily forecast snapshots (already written to the `forecasts` table).
2. **Weeks 3–6** — ship the alert webhooks and a minimal subscriber signup; publish
   a public "last week vs this week" diff so the newsletter shows its own accuracy.
3. **Month 2+** — score the accumulated snapshots against realised EOL dates, refit
   the weights on that history (see `docs/model.md` §4), and use the calibration
   result as the sales argument for the paid tiers.
4. **Later** — add the paid inputs (wafer starts, board-partner shipments, paid
   memory contract prints) as a "provenance upgrade" tier once revenue justifies them.

## What would falsify this business

* Vendors restoring full, timely SKU-level allocation disclosure (kills the
  information asymmetry the product exists to exploit).
* Retail availability data becoming uniformly free and structured (kills the
  tracker-scraping moat; the forecast layer would still stand).
* A forecasting competitor with paid supply-chain data publishing the same calls
  free — the defensible answer is the audit trail and per-SKU evidence, not the score.
