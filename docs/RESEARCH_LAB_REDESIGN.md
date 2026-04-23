# Governed Repository Redesign: Speculative Signal Discovery Lab

## Purpose

This repository is a **research-only system** for exploring whether currently non-existent or underdefined signal classes might exist.

It is not a trading engine. It does not publish live entries, orders, or executable instructions.

## Hard Constraints

1. No live trade generation.
2. No auto-deployment of strategy logic.
3. No auto-merge of machine-generated changes.
4. No unreviewed activation of prompts/models/evaluation logic.
5. All automated changes must be branch-based, test-backed, reversible.

---

## Research Questions

1. What predictive structures might exist beyond current indicator stacks?
2. Can new signal families emerge from higher-order interactions (microstructure × regime × narrative context)?
3. Can LLMs help organize and stress-test hypotheses without overstating certainty?
4. What evidence threshold distinguishes weak pattern from robust signal candidate?

---

## System Architecture (Governance First)

### A) Discovery Stack

1. **Feature Ingest Layer** (`feedback_ingest/`, `evaluation_reports/`, external market datasets)
   - Ingests price/volume, funding, OI, liquidation, orderbook state, regime labels, optional narrative embeddings.

2. **Latent Interaction Engine**
   - Searches for non-obvious feature interactions.
   - Produces candidate relationships and anomaly regimes.

3. **Signal Hypothesis Engine**
   - Converts discovered interactions into structured hypotheses (with uncertainty, missing evidence, failure modes).

4. **Noise Challenge Engine**
   - Tries to falsify hypotheses via placebo tests, shuffled labels, and naive baselines.

5. **Registry + Evidence Store**
   - Maintains lifecycle status for candidate signal families.
   - Records both supporting and contradictory evidence.

### B) Repository Self-Improvement Stack (GitHub Actions)

1. **Feedback Parser**
   - Parses issue/PR comments and evaluation artifacts.
2. **Improvement Classifier**
   - Maps feedback into improvement themes (docs, evaluation, taxonomy, simulation, prompts).
3. **Proposal Generator**
   - Produces structured improvement proposal JSON.
4. **Branch Updater**
   - Applies changes in controlled file scopes.
5. **Validation Runner**
   - Executes tests/lint/schema checks/simulation harness.
6. **Draft PR Generator**
   - Opens draft PR containing rationale, diff summary, evidence, risks, rollback notes.
7. **Human Approval Gate**
   - Required before merge or activation.

---

## Comment-to-PR Data Flow

1. Trigger event from issue comment / PR comment / manual dispatch / schedule.
2. Extract feedback payload and metadata.
3. Classify intent and safety level.
4. Reject unsafe/vague requests with explicit reason.
5. Create `improvement_proposals/<proposal_id>.json`.
6. Generate branch `auto/proposal-<proposal_id>`.
7. Apply scoped modifications.
8. Run checks + simulation.
9. Store outputs in `change_summaries/`, `simulation_runs/`, `evaluation_reports/`.
10. Open/refresh draft PR.
11. Await human review.
12. On approval, merge through normal branch protection.

---

## Branch Strategy

- `main`: protected, human-reviewed merges only.
- `auto/proposal-*`: machine-generated working branches.
- `research/*`: human-authored experimental branches.
- `rollback/*`: emergency restoration branches from known-good states.

Rules:
- Bot cannot push directly to `main`.
- Bot-created PRs are always `draft`.
- Required checks must pass before draft can be marked ready.

---

## Candidate Signal Discovery Design

### Candidate Families to Explore

- Regime transition precursors.
- Order-book asymmetry persistence.
- Failed breakout signatures.
- Volatility compression-release precursors.
- Correlated liquidation pressure clusters.
- Funding/open-interest divergence states.
- Narrative-structure regime effects.
- Model disagreement as uncertainty signal.

### Hypothesis Record Requirements

Each candidate must include:
- signal family name,
- mechanism narrative,
- required features,
- expected context,
- expected failure modes,
- confidence in existence,
- supporting evidence,
- missing evidence,
- uncertainty statement.

### Candidate Status Lifecycle

`imagined -> weakly_supported -> under_test -> promising|unstable|rejected`

`research_candidate_only` is a global tag for all items in this system.

---

## Evaluation and Rejection Framework

### Core Tests

1. Historical simulation with walk-forward splits.
2. Regime stability checks.
3. Baseline comparison (naive directional and random controls).
4. Calibration and drift diagnostics.
5. Noise challenge tests (label shuffling, feature permutation).

### Scoring Rubric (Illustrative)

- Evidence Strength (0-5)
- Regime Robustness (0-5)
- Calibration Quality (0-5)
- Interpretability/Mechanism Plausibility (0-5)
- Noise Susceptibility (inverse)

Promotion requires minimum thresholds and no critical safety failures.

### Aggressive Rejection Criteria

Reject/demote when:
- gains disappear under walk-forward,
- effect only appears in narrow hindsight windows,
- unstable calibration,
- high sensitivity to tiny data perturbations,
- no plausible mechanism and repeated out-of-sample failure.

Example language:
> "This pattern is probably noise: performance collapses after label shuffling and fails regime holdout tests."

---

## Required Per-Cycle Artifacts

Every automation cycle must persist:

- source feedback reference,
- interpretation,
- affected files,
- diff summary,
- test results,
- simulation results,
- confidence estimate,
- risk notes,
- rollback notes.

---

## Governance Controls

- Immutable-style append logs for evidence.
- Registry pointer updates only via approved PRs.
- Safety policies as code (`safety_policies/` + workflow checks).
- Weekly evolution reports documenting approved/rejected changes.

---

## Rollback Plan

1. Identify last approved commit + registry pointers.
2. Open `rollback/<date>-<reason>` branch.
3. Revert affected commits/config pointers.
4. Re-run validations and simulation checks.
5. Open rollback PR with incident summary.
6. Require human approval and merge.

---

## Operational Tone

Institutional, skeptical, anti-hype:
- treat all discovered patterns as provisional,
- favor falsification over confirmation,
- document uncertainty and failure quickly.

