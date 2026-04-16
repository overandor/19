# Testing Framework, Scoring Rubric, and Rejection Criteria

## Evaluation Stages

1. **Specification completeness check**
   - Reject hypotheses without mechanism, context, and failure modes.
2. **Data sufficiency check**
   - Reject if required features are missing or low quality.
3. **Baseline-relative simulation**
   - Compare to naive baselines and randomization controls.
4. **Regime robustness testing**
   - Evaluate behavior across volatility and liquidity regimes.
5. **Calibration and drift checks**
   - Reliability and temporal stability required.
6. **Adversarial stress tests**
   - Perturb labels, windows, and feature subsets.

## Evidence Scorecard Dimensions

- statistical persistence
- regime consistency
- baseline outperformance margin
- calibration quality
- drift resistance
- implementation fragility
- interpretability quality
- reproducibility confidence

Each dimension is scored `0-5` and weighted conservatively.

## Promotion Rules

- `imagined -> weakly_supported`: minimum reproducibility evidence in at least one regime.
- `weakly_supported -> under_test`: multi-window consistency and baseline superiority.
- `under_test -> promising`: robust across regimes with acceptable drift.
- Any stage -> `rejected`: strong evidence of noise, leakage, or instability.

## Rejection Criteria (Aggressive)

A candidate is rejected if any condition is met:

- effect vanishes under slight resampling
- behavior concentrated in one narrow period
- outperformance explained by leakage or feature contamination
- calibration collapses out-of-sample
- mechanism unsupported and inconsistent with observed microstructure

## Standard Noise Verdict Language

Use explicit wording such as:

- "Observed pattern is likely noise; predictive effect is not stable across regimes."
- "Signal behavior appears sample-specific and fails out-of-window validation."
- "Candidate mechanism is under-specified and currently unsupported by evidence."

## Confidence Tiers

- `low`: exploratory, weak evidence
- `moderate`: repeated but fragile evidence
- `high_research`: robust evidence for research continuation only

No confidence tier implies production readiness.
