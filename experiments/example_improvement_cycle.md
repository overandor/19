# Example Controlled Improvement Cycle

## Step 1: Observe failure mode
- Source: `failure_mode_reports/recurring_patterns.jsonl`
- Pattern: high-confidence false positives in `high_vol_mean_revert` regime.

## Step 2: Generate proposal
- Proposal ID: `prop_2026_04_16_007`
- Changes:
  - Prompt update: stronger uncertainty and abstain instruction.
  - Feature update: `spread_x_volatility_interaction`.

## Step 3: Simulate
- Protocol: rolling walk-forward across multiple historical windows.
- Outcome:
  - Brier score improves.
  - False positives decrease.
  - Recall impact is small and accepted.

## Step 4: Human review
- Submit proposal + simulation to approval queue.
- Reviewers assess regressions, overfitting risk, and rollback path.

## Step 5: Activate only after explicit approval
- If approved, update `registries/active_config.json`.
- Append activation event to `registries/changelog.jsonl`.
- Archive in weekly review.

## Step 6: Continue loop
- Monitor post-activation metrics.
- If degradation appears, execute rollback using last approved versions.
