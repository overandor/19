# Signal Discovery Architecture (Speculative, Research-Only)

## Research questions
1. What predictive structures might exist that are not captured by conventional indicators?
2. Can novel signal families emerge from unusual feature interactions?
3. Can an LLM improve hypothesis naming and taxonomy while preserving uncertainty?
4. What evidence threshold separates weak artifacts from robust signals?

## Module architecture
- `feedback_ingest/`: parses and classifies feedback and evaluation commentary.
- `improvement_proposals/`: structured machine-readable proposal objects.
- `candidate_signal_registry/`: status-tracked speculative signal hypotheses.
- `simulation_runs/`: run metadata and metrics by candidate signal.
- `evaluation_reports/`: test outcomes, uncertainty analysis, and failure cases.
- `change_summaries/`: rationale + diffs + risks for every automated change.
- `safety_policies/`: hard governance constraints.

## Discovery layer: candidate families
- regime transition precursors
- order-book asymmetry persistence
- failed breakout signatures
- volatility compression-release precursors
- correlated liquidation pressure clusters
- funding/open-interest divergence states
- narrative embedding regime effects
- model disagreement as uncertainty signal

## Hypothesis lifecycle statuses
- `imagined`
- `weakly_supported`
- `under_test`
- `rejected`
- `promising`
- `unstable`
- `research_candidate_only`

## Evaluation framework
For each candidate hypothesis:
1. historical simulation across multiple regimes
2. baseline comparison against naive controls
3. calibration and drift checks
4. failure pattern mining
5. anti-overfitting stress checks
6. demotion or rejection when instability dominates

## Scoring rubric (0-5 each)
- explanatory plausibility
- signal stability across regimes
- baseline lift persistence
- calibration quality
- adverse condition robustness
- reproducibility across windows

### Promotion gates
- Promote to `promising` only when:
  - median regime stability >= 3.5
  - baseline lift positive in majority of windows
  - no critical failure mode unresolved
- Otherwise remain `under_test` or move to `rejected`.

## Noise-first language examples
- "Observed effect did not survive out-of-regime validation; likely noise."
- "Signal-family hypothesis is underidentified; evidence insufficient."
- "Performance concentrated in one regime; not generalizable."

## LLM role
Permitted:
- hypothesis synthesis
- taxonomy/naming support
- uncertainty summarization
- flaw identification

Prohibited:
- certainty claims without evidence
- live entry/exit instruction generation
- bypassing governance gates
