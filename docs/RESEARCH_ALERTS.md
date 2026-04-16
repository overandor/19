# Perp Research Alerts (GitHub Issues)

This workflow provides a **research-only alert channel**.

- Workflow: `.github/workflows/perp-research-alerts.yml`
- Script: `scripts/perp_research_alerts.py`
- Trigger: every 15 minutes UTC (cron) and manual dispatch.
- Output: creates/updates GitHub Issues labeled `research-alert`.

## Behavior

1. Fetch public Binance perpetual futures data.
2. Evaluate non-executable watch conditions (24h move/range/funding context).
3. Upsert issue stream:
   - one issue per symbol (`Research alert: SYMBOL`)
   - new detections are appended as comments.

## Safety Constraints

- Research alerts only.
- No order placement.
- No entry/exit instructions.
- No exchange authentication.
- Human interpretation required.

## Operational Notes

- GitHub cron is UTC.
- GitHub scheduled workflows support minimum 5-minute cadence; this workflow uses 15 minutes.
- `issues: write` permission is explicitly scoped for issue creation and comments.
