# Perp Research Alerts (GitHub Issues)

This workflow provides a **research-only alert channel** powered by public endpoints.

- Workflow: `.github/workflows/perp-research-alerts.yml`
- Script: `scripts/perp_research_alerts.py`
- Trigger: every 15 minutes UTC (cron) and manual dispatch.
- Output: creates/updates GitHub Issues labeled `research-alert`.

## Data Sources (No Exchange API Keys)

### Binance USDⓈ-M (public)
- Base: `https://fapi.binance.com`
- Used routes:
  - `/fapi/v1/ticker/24hr`
  - `/fapi/v1/premiumIndex`
  - `/fapi/v1/openInterest`
  - `/fapi/v1/depth`

### Gate.io futures (public)
- Base: `https://api.gateio.ws/api/v4`
- Used routes:
  - `/futures/usdt/tickers`
  - `/futures/usdt/contracts/{contract}`
  - `/futures/usdt/order_book`

### XT.com
XT is intentionally not wired yet in this watcher until an official, stable endpoint reference is verified and reviewed.

## Behavior

1. Poll Binance and Gate perpetual market snapshots.
2. Evaluate non-executable watch conditions:
   - 24h move magnitude,
   - 24h range expansion,
   - funding-rate extremes,
   - spread widening from top-of-book.
3. Upsert issue stream:
   - one open issue per exchange-symbol pair,
   - new detections appended as issue comments.
4. Persist run snapshots to `alerts/history/*.json` for audit trail artifacts.

## Safety Constraints

- Research alerts only.
- No order placement.
- No entry/exit instructions.
- No exchange authentication.
- Human interpretation required.

## Operational Notes

- GitHub cron is UTC.
- GitHub scheduled workflows support minimum 5-minute cadence; this workflow uses 15 minutes.
- `issues: write` is explicitly scoped for issue creation and comments.
