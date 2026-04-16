# Repository Redesign Plan: Governed Non-Existent Signal Discovery

## 1) Mission
Reframe the codebase as a research operating system for discovering, testing, and rejecting speculative signal classes that are not yet formalized in the current strategy stack.

## 2) Governance-first principles
1. **Human approval is mandatory** for strategy-relevant merges.
2. **No live execution path** is allowed in automation.
3. **Every machine-authored change is reversible** with explicit rollback notes.
4. **Evidence over novelty**: unproven signal ideas are treated as hypotheses until replicated.
5. **Rejection is a first-class output**.

## 3) Event triggers and workflow architecture
### Trigger sources
- `issues`
- `issue_comment`
- `pull_request_review_comment`
- `pull_request`
- `workflow_dispatch`
- scheduled weekly reviews (`cron`)

### Workflow set
- `feedback-ingest.yml`: normalize comments/feedback into structured proposals.
- `repo-self-review.yml`: inspect repo quality gaps and produce upgrade briefs.
- `simulation-validation.yml`: run hypothesis backtest/simulation checks.
- `draft-pr-generator.yml`: create branch + draft PR with rationale and risk controls.
- `weekly-evolution-report.yml`: publish aggregate outcomes and failure analysis.

## 4) Comment-to-improvement data flow
1. Capture source feedback payload from GitHub event.
2. Classify into themes: architecture, docs, evaluation, feature extraction, reporting, taxonomy.
3. Reject unsafe/vague inputs with explicit reason.
4. Convert accepted input to `improvement_proposals/*.json`.
5. Generate candidate patch in controlled directories.
6. Run tests, lint, and research simulations.
7. Write machine rationale + diff summary + risk note + rollback plan.
8. Open **draft** PR only.
9. Block merge pending human approval.

## 5) Branch strategy
- Branch naming: `auto/proposal-<proposal_id>-<short-theme>`.
- Protected default branch with required checks.
- Draft PRs only from automation.
- No direct pushes to protected branch.

## 6) Required outputs per improvement cycle
Each cycle must emit:
- source feedback reference
- interpretation of requested improvement
- affected files
- diff summary
- test results
- simulation results
- confidence level
- risk notes
- rollback notes

## 7) Rollback plan
- Every PR includes a deterministic rollback commit recipe.
- Automated report tracks post-merge regressions.
- Regression trigger opens a rollback proposal PR instead of direct revert.

## 8) Why this is research-only
This system evaluates hypotheses and uncertainty. It does not provide executable trade calls or deployment-ready trading logic.
