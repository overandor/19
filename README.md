# Supervised AI Market Research Lab

This repository is redesigned as a **governed market intelligence and experimentation system**.

It continuously studies market and feature data, generates structured hypotheses, tracks realized outcomes, and proposes process improvements under strict human supervision.

## Safety & Governance Guardrails

This system is intentionally **not** an autonomous trading agent.

- No live order placement.
- No auto-execution of strategies.
- No self-deployment of strategy/prompt/model changes.
- No activation of new logic without explicit human approval.

## Core Workflow

1. Observe market + feature data (`ingestion/`, `feature_engine/`).
2. Generate hypotheses (`hypothesis_engine/`).
3. Persist hypotheses + metadata (`signal_history/`, `memory_store/`).
4. Evaluate outcomes and calibration (`evaluation_engine/`, `evaluations/`).
5. Detect repeated failure modes (`failure_mode_reports/`).
6. Propose controlled improvements (`experiments/`, `approvals/`).
7. Require human sign-off before activation (`approval_gate` process in `docs/REDESIGN_PLAN.md`).

## Repository as Memory

The repository is a first-class memory surface with immutable-style append logs and versioned artifacts:

- `signal_history/`
- `evaluations/`
- `experiments/`
- `prompts/`
- `model_versions/`
- `weekly_reviews/`
- `failure_mode_reports/`
- `dashboards/`

## Where to Start

- Read the complete redesign blueprint: `docs/REDESIGN_PLAN.md`
- Review canonical schemas + logging envelopes: `docs/DATA_SCHEMAS.md`
- Use `approvals/approval_queue.jsonl` for pending changes and `approvals/approval_decisions.jsonl` for outcomes.

