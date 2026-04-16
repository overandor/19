# Speculative Signal Discovery Lab (Governed, Research-Only)

This repository is an institutional research environment for discovering and evaluating **hypothetical, currently non-existent signal classes**.

It is designed as a governed software system with GitHub Actions-assisted self-improvement under strict human oversight.

## Non-Negotiable Safety Constraints

- No live trading instructions.
- No real-time trade calls or entries.
- No autonomous strategy deployment.
- No auto-merge of machine-generated changes.
- No safety gate weakening through automation.

## What This System Does

- explores candidate signal families from market structure and contextual data,
- records hypotheses and evidence with explicit uncertainty,
- runs simulation and falsification tests,
- rejects weak/noisy candidates aggressively,
- converts feedback into draft improvement PRs via controlled workflows.

## Key Design Surfaces

- Redesign blueprint: `docs/RESEARCH_LAB_REDESIGN.md`
- Schemas: `docs/schemas/`
- Automation workflows: `.github/workflows/`
- Safety policies: `safety_policies/`
- Improvement proposals: `improvement_proposals/`
- Candidate signal registry: `candidate_signal_registry/`

## Governance Model

All meaningful repository evolution follows:

1. feedback ingest,
2. proposal generation,
3. branch-based change,
4. test + simulation validation,
5. draft PR generation,
6. human review and approval,
7. merge with rollback traceability.

This repository should feel like a governed discovery engine, not a live trading bot.
