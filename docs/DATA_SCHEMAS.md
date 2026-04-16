# Canonical Data Schemas & Logging Contracts

This file defines minimum fields for durable records.

## 1) Hypothesis Record (`signal_history/hypotheses.jsonl`)

```json
{
  "hypothesis_id": "hyp_2026_04_16_0001",
  "timestamp_utc": "2026-04-16T12:00:00Z",
  "exchange": "BINANCE",
  "symbol": "BTCUSDT",
  "timeframe": "15m",
  "horizon_minutes": 60,
  "regime": "high_vol_mean_revert",
  "direction": "up|down|neutral",
  "confidence": 0.67,
  "uncertainty": 0.22,
  "feature_snapshot": {
    "rv_1h": 0.045,
    "orderbook_imbalance": -0.12,
    "spread_bps": 1.8
  },
  "rationale_summary": "Short pressure exhausted while spread stabilizes.",
  "model_version": "model_v2.3.1",
  "prompt_version": "prompt_hypothesis_v1.4.0",
  "feature_version": "features_v1.2.0",
  "status": "pending_outcome",
  "trace_id": "trace_abc123"
}
```

## 2) Outcome Record (`evaluations/hypothesis_outcomes.jsonl`)

```json
{
  "hypothesis_id": "hyp_2026_04_16_0001",
  "realized_timestamp_utc": "2026-04-16T13:00:00Z",
  "entry_price": 64200.1,
  "exit_price": 64510.3,
  "realized_return": 0.00483,
  "realized_direction": "up",
  "is_correct_direction": true,
  "label": "TP",
  "confidence_error": -0.12,
  "brier_component": 0.102,
  "calibration_bucket": "0.6_0.7",
  "evaluation_version": "eval_v1.0.0",
  "trace_id": "trace_abc123"
}
```

## 3) Calibration Report (`evaluations/calibration_reports.jsonl`)

```json
{
  "report_id": "cal_2026_w16",
  "window_start_utc": "2026-04-09T00:00:00Z",
  "window_end_utc": "2026-04-16T00:00:00Z",
  "sample_size": 782,
  "ece": 0.041,
  "brier_score": 0.186,
  "log_loss": 0.544,
  "by_regime": {
    "trend": {"ece": 0.028, "brier": 0.172},
    "high_vol_mean_revert": {"ece": 0.072, "brier": 0.219}
  },
  "active_model_version": "model_v2.3.1",
  "active_prompt_version": "prompt_hypothesis_v1.4.0"
}
```

## 4) Failure Cluster (`failure_mode_reports/recurring_patterns.jsonl`)

```json
{
  "cluster_id": "failcluster_2026_04_16_01",
  "created_utc": "2026-04-16T14:10:00Z",
  "trigger": "high_confidence_false_positive_rate_exceeded",
  "signature": {
    "regime": "high_vol_mean_revert",
    "confidence_band": "0.7_0.9",
    "spread_bps_range": [1.2, 2.4]
  },
  "occurrences": 64,
  "estimated_impact_bps": -143,
  "suspected_causes": [
    "uncertainty underestimation",
    "prompt over-weights momentum wording"
  ],
  "recommended_actions": [
    "tighten confidence gating",
    "add spread-volatility interaction feature"
  ]
}
```

## 5) Improvement Proposal (`experiments/proposals.jsonl`)

```json
{
  "proposal_id": "prop_2026_04_16_007",
  "created_utc": "2026-04-16T14:30:00Z",
  "proposal_type": "prompt+feature",
  "based_on_failure_clusters": ["failcluster_2026_04_16_01"],
  "changes": {
    "prompt_diff_ref": "prompts/diffs/prompt_hypothesis_v1.4.0_to_v1.5.0.diff",
    "feature_change": "add spread_x_volatility_interaction"
  },
  "expected_benefit": "reduce high-confidence false positives in high-vol regimes",
  "simulation_plan": "rolling_6m_walkforward_v2",
  "status": "proposed"
}
```

## 6) Simulation Result (`experiments/simulations.jsonl`)

```json
{
  "simulation_id": "sim_2026_04_16_011",
  "proposal_id": "prop_2026_04_16_007",
  "completed_utc": "2026-04-16T16:00:00Z",
  "datasets": ["market_2025Q4", "market_2026Q1"],
  "metrics_delta": {
    "brier_score": -0.017,
    "false_positive_rate": -0.18,
    "recall": -0.03
  },
  "regression_checks": {
    "trend_regime_pass": true,
    "crash_regime_pass": true
  },
  "status": "ready_for_review"
}
```

## 7) Approval Queue (`approvals/approval_queue.jsonl`)

```json
{
  "review_id": "rev_2026_04_16_002",
  "proposal_id": "prop_2026_04_16_007",
  "submitted_utc": "2026-04-16T16:10:00Z",
  "required_reviewers": ["research_lead", "risk_officer"],
  "state": "review_pending",
  "artifacts": {
    "proposal": "experiments/proposals.jsonl#prop_2026_04_16_007",
    "simulation": "experiments/simulations.jsonl#sim_2026_04_16_011"
  }
}
```

## 8) Approval Decision (`approvals/approval_decisions.jsonl`)

```json
{
  "review_id": "rev_2026_04_16_002",
  "decision_utc": "2026-04-16T18:00:00Z",
  "decision": "approved",
  "reviewers": ["research_lead", "risk_officer"],
  "comments": "Approved for shadow deployment only.",
  "activation_scope": "hypothesis_engine_v_next",
  "rollback_target": "prompt_hypothesis_v1.4.0 + features_v1.2.0"
}
```

## 9) Active Registry Pointer (`registries/active_config.json`)

```json
{
  "active_model_version": "model_v2.3.1",
  "active_prompt_version": "prompt_hypothesis_v1.4.0",
  "active_feature_version": "features_v1.2.0",
  "last_approved_review_id": "rev_2026_04_10_005",
  "updated_utc": "2026-04-10T09:30:00Z"
}
```

