# Speculative Signal Discovery Framework

## Candidate Signal Registry Format

Registry file: `candidate_signal_registry/registry.jsonl`

Each row references `docs/schemas/candidate_signal.schema.json` and must include explicit uncertainty, missing evidence, and failure modes.

## Example Candidate Signals (Research-Only)

1. **Regime Transition Tension Index**
   - Hypothesis: abrupt shifts in order-book asymmetry persistence + funding divergence may precede short-lived regime transition.
2. **Compression-Disagreement Release**
   - Hypothesis: volatility compression with rising model disagreement may indicate pending non-linear move risk (direction uncertain).
3. **Narrative-Liquidity Mismatch State**
   - Hypothesis: strong narrative embedding polarity with weakening depth resilience may signal unstable conditions.

None of these are deployment signals; they are exploratory candidates only.

## Testing Framework

### Required test battery

- walk-forward historical simulation,
- regime-holdout evaluation,
- shuffled-label placebo control,
- feature-permutation sensitivity,
- naive baseline comparison,
- calibration and drift checks.

### Evidence scorecards

Persist to `evidence_scorecards/` using `docs/schemas/evidence_scorecard.schema.json`.

## Scoring Rubric

- Evidence strength (0-5)
- Regime robustness (0-5)
- Calibration quality (0-5)
- Mechanism plausibility (0-5)
- Noise risk (0-5, lower is better)

Suggested promotion bar:
- evidence >= 3.5
- regime robustness >= 3
- calibration >= 3
- noise risk <= 2

## Rejection Criteria

Reject when any of the following persist across windows:

- out-of-sample degradation > threshold,
- instability concentrated in one regime,
- calibration collapse,
- weak mechanism and high perturbation sensitivity,
- placebo/shuffle performance near observed signal performance.

## "Probably Noise" Example Language

- "This candidate is probably noise: its advantage disappears under label shuffling and does not survive regime holdout."
- "This pattern is likely spurious: confidence is uncalibrated and the effect is confined to a narrow hindsight interval."
- "Evidence is insufficient: mechanism is vague, baseline delta is small, and stability is poor."
