# Speculative Signal Research Lab

This repository is a **governed research system** for exploring whether currently non-existent (or underdefined) predictive signal classes could exist.

## Scope and safety boundary
- Research only: discovery, simulation, and evidence scoring.
- No live trading orchestration, no order routing, no executable entries.
- All automated changes are reviewable, testable, reversible, and blocked on human approval.

## What this lab does
- Generates structured hypotheses for speculative signal families.
- Evaluates candidates against historical data and regime segmentation.
- Rejects weak or unstable hypotheses aggressively.
- Produces auditable improvement proposals from repository feedback.

## Operating model
GitHub Actions drives a governed improvement loop:
1. ingest feedback (issues, PR comments, evaluation artifacts)
2. classify and normalize into improvement proposals
3. create branch-based candidate changes in controlled paths
4. run tests and simulation validation
5. open draft PRs with rationale, risk notes, and rollback instructions
6. require explicit human review before merge

## Core repository outputs
- `candidate_signal_registry/`
- `signal_discovery_reports/`
- `rejected_signal_archive/`
- `regime_test_results/`
- `feature_interaction_maps/`
- `weekly_research_reviews/`
- `speculative_signal_taxonomy/`
- `evidence_scorecards/`

## Design documents
- `docs/REPO_REDESIGN_PLAN.md`
- `docs/SIGNAL_DISCOVERY_ARCHITECTURE.md`
- `safety_policies/RESEARCH_GUARDRAILS.md`
