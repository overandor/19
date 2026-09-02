# Speculative Signal Research Lab (Governed, Research-Only)
https://overaj.vercel.app/
This repository is re-framed as a **research operating system** for discovering and evaluating **hypothetical, currently non-existent signal classes**.

## Non-Negotiable Constraints

- Research-only: no live trading execution, no order routing, no trade deployment.
- Governance-first: all machine-generated changes are branch-based, testable, reversible, and human-reviewed.
- Skeptical by design: candidate patterns are assumed to be noise until evidence survives adversarial testing.

## Mission

Build and continuously improve a governed pipeline that:

1. Ingests comments, issue feedback, and evaluation artifacts.
2. Converts valid feedback into structured improvement proposals.
3. Proposes repository changes in draft PRs.
4. Runs tests and simulation validation before review.
5. Records rationale, confidence, risk, and rollback notes.

## Repository Areas

- `.github/workflows/` — governed automation workflows.
- `feedback_ingest/` — parsed and classified feedback artifacts.
- `improvement_proposals/` — proposal JSON files and schemas.
- `evaluation_reports/` — evaluation outputs and scorecards.
- `simulation_runs/` — non-execution simulation artifacts.
- `prompt_versions/` — prompt and hypothesis-template versions.
- `change_summaries/` — machine-generated change narratives.
- `safety_policies/` — hard safety requirements.
- `candidate_signal_registry/` — speculative signal registry and status transitions.
- `signal_discovery_reports/` — periodic discovery reports.
- `rejected_signal_archive/` — rejected hypotheses and failure evidence.
- `regime_test_results/` — regime-segmented evaluation results.
- `feature_interaction_maps/` — interactions and latent factor diagnostics.
- `weekly_research_reviews/` — weekly governed status reviews.
- `speculative_signal_taxonomy/` — evolving taxonomy of candidate signal families.
- `evidence_scorecards/` — standardized confidence and rejection scorecards.
- `memory_credit_daemon/` — v0 metering daemon for compute-reuse receipts and an SPL credits token. Devnet/localnet by default; mainnet requires an explicit opt-in *and* a `proof_of_avoided_work` authorization covering only audited credits.
- `proof_of_avoided_work/` — makes a compute-reuse claim falsifiable: work commitments, an oracle that owns the baseline, sampled re-execution audits, and settlement that pays only what survived.
- `memory_shell/` — a sandboxed shell that cuts an LLM server's resident memory: shared `MAP_SHARED` weights, content-addressed KV reuse under a byte budget, and tenant isolation so cache sharing is not an oracle about other people's prompts. Feeds measured costs to `proof_of_avoided_work`.
- `packaging/` — macOS `.dmg` build script, installer, and launchd agent for `memory_shell`.

## Key Design Documents

- `docs/repo_redesign_plan.md`
- `docs/module_architecture.md`
- `docs/testing_and_scoring_framework.md`
- `docs/DISTRIBUTED_LLM_INFERENCE.md`
- `docs/MEMORY_CREDIT_DAEMON.md`
- `docs/PROOF_OF_AVOIDED_WORK.md`
- `docs/MEMORY_SHELL.md`
- `safety_policies/research_only_policy.md`
- `.github/pull_request_template.md`
- `improvement_proposals/schema/improvement_proposal.schema.json`
- `candidate_signal_registry/schema/candidate_signal.schema.json`

## Workflow Set

The repository includes workflow skeletons for governed self-improvement:

- `feedback-ingest.yml`
- `repo-self-review.yml`
- `simulation-validation.yml`
- `draft-pr-generator.yml`
- `weekly-evolution-report.yml`

All workflow outputs are review artifacts; none can merge strategy logic without explicit human approval.
