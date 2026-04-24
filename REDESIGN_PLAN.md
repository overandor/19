# Supervised AI Market Research Service Redesign Plan

## Mission
Build a repository-backed system that continuously studies market data, records hypotheses, evaluates outcomes, and proposes improvements to its own research process over time. The system acts as a governed AI research lab, an institutional experiment engine, and an auditable market intelligence repository. It strictly avoids unsupervised autonomous trading.

## Strict Operational Rules
- **NO** placing real trades.
- **NO** auto-executing strategies.
- **NO** self-deploying strategy changes without human review.
- **NO** operating as an unsupervised autonomous trading agent.

## Directory Structure

```
.
├── core/
│   ├── ingestion.py          # Market data and feature ingestion
│   ├── feature_engine.py     # Feature calculation and formatting
│   ├── hypothesis_engine.py  # AI prompt execution and signal generation
│   ├── evaluation_engine.py  # Outcome resolution, scoring, and failure detection
│   └── approval_gate.py      # Review mechanism for new strategies and prompts
├── signal_history/           # Persistent JSON/CSV records of every hypothesis
├── evaluations/              # Results of hypothesis scoring and calibration
├── experiments/              # Test runs, simulations, and experimental logic
├── prompts/                  # Version-controlled prompt templates for hypothesis generation
├── model_versions/           # Records of model configs and versions used
├── weekly_reviews/           # Aggregated reports of system performance
├── failure_mode_reports/     # Clustered error and miscalibration analysis
├── dashboards/               # Artifacts for visualization and neomorphic UI
└── REDESIGN_PLAN.md          # This architectural blueprint
```

## Data Schemas

### Hypothesis Record (`signal_history/`)
```json
{
  "hypothesis_id": "uuid",
  "timestamp": "ISO8601",
  "exchange": "string",
  "symbol": "string",
  "regime": "string (e.g., high_volatility, trending)",
  "hypothesis_direction": "int (-1, 0, 1)",
  "confidence": "float (0.0 - 1.0)",
  "uncertainty": "float (0.0 - 1.0)",
  "feature_snapshot": {
    "volatility": "float",
    "volume_trend": "float",
    "momentum": "float"
  },
  "rationale_summary": "string",
  "model_version": "string",
  "prompt_version": "string",
  "status": "pending | evaluated"
}
```

### Evaluation Record (`evaluations/`)
```json
{
  "evaluation_id": "uuid",
  "hypothesis_id": "uuid",
  "evaluation_timestamp": "ISO8601",
  "realized_outcome_direction": "int (-1, 0, 1)",
  "realized_magnitude_bps": "float",
  "predicted_confidence": "float",
  "calibration_error": "float",
  "label": "true_positive | false_positive | true_negative | false_negative",
  "failure_cluster": "string | null"
}
```

## Logging Format
The system uses structured JSON logging for all operational events to facilitate search and aggregation.
```json
{
  "timestamp": "2023-10-27T10:00:00Z",
  "level": "INFO",
  "component": "hypothesis_engine",
  "event": "generated_hypothesis",
  "symbol": "WETH/USDC",
  "hypothesis_id": "uuid",
  "message": "Successfully generated bullish hypothesis for WETH/USDC under low volatility regime."
}
```

## Evaluation Framework
1. **Outcome Simulation**: Continuously pull realized market data following a hypothesis timestamp. Calculate max favorable excursion and max adverse excursion over predefined time horizons (e.g., 5m, 1h, 24h).
2. **Calibration Scoring**: Compare the predicted `confidence` against the binary correctness of the `hypothesis_direction`. Use Brier scores or similar metrics to assess calibration.
3. **Failure Detection**: Categorize incorrect predictions (False Positives/Negatives).
4. **Clustering**: Group failures by `regime`, `feature_snapshot` characteristics, or `model_version` to identify systemic blind spots (e.g., "Model consistently overestimates momentum during high-volatility regimes").

## Approval Workflow
Modifications to the system's core logic (prompts, features, regime logic) require strict governance.

1. **Proposal**: System (or human) creates a Pull Request proposing a change. The PR includes a simulated backtest using `evaluations/` data to demonstrate expected improvement.
2. **Logging**: The proposal is documented in `experiments/`.
3. **Diffing**: The change is diffed against the current active version (e.g., in `prompts/`).
4. **Human Review**: A human reviewer examines the rationale, backtest results, and diff.
5. **Approval & Merge**: The human explicitly approves the PR. Only upon merge to `main` does the new logic become active for future hypothesis generation.

## Example Improvement Cycle
1. **Observe**: The `evaluation_engine` identifies a high rate of False Positives for mean-reversion trades during trending regimes.
2. **Hypothesize (System)**: The system automatically generates a report in `failure_mode_reports/` suggesting that the "mean_reversion_prompt_v2" is miscalibrated for "trending" regimes.
3. **Propose**: A script generates a proposed prompt change: `mean_reversion_prompt_v3` with added explicit constraints against trading against strong momentum features.
4. **Simulate**: The system runs `mean_reversion_prompt_v3` over historical feature snapshots where v2 failed, verifying a reduction in False Positives.
5. **Score**: The simulated score shows a 15% improvement in calibration.
6. **Review**: The system creates a branch, commits `mean_reversion_prompt_v3`, appends the simulation results, and opens a Pull Request.
7. **Human Approval**: The researcher reviews the PR, ensures the new prompt logic is sound, and approves/merges.
8. **Version & Archive**: `prompt_version` increments. Future hypothesis records tag the new version. The cycle repeats.
