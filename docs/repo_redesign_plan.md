# Full Repository Redesign Plan

## 1) Strategic Reframe

The repository is redesigned from a signal-emitting stack into a governed lab that explores whether new predictive signal classes might exist. The lab is explicitly anti-deployment: it supports discovery, rejection, and controlled promotion to further research only.

## 2) Comment-to-Improvement Lifecycle

1. **Feedback ingestion**
   - Source events: issue, issue_comment, pull_request_review_comment, discussion artifacts, and scheduled review reports.
   - Raw feedback is normalized into `feedback_ingest/YYYY/MM/*.json`.
2. **Classification and safety triage**
   - Classify into themes: architecture, docs, evaluation, reporting, feature extraction, taxonomy, test coverage, prompts, simulation config.
   - Reject if unsafe, vague, or requests live trade behavior.
3. **Improvement proposal generation**
   - Emit proposal documents in `improvement_proposals/` using schema.
   - Include requested change interpretation, confidence, and risk tags.
4. **Branch proposal creation**
   - Dedicated branch naming: `proposal/<date>/<proposal_id>`.
   - Changes constrained to approved paths and policy checks.
5. **Validation stage**
   - Lint, tests, schema checks, and simulation validation.
6. **Draft PR generation**
   - Open draft PR with rationale, diff summary, evidence, and rollback plan.
7. **Human review gate**
   - Mandatory reviewer approval before merge.
8. **Post-merge evidence logging**
   - Record outcomes and unresolved failure patterns.

## 3) Event Triggers

- `issues`, `issue_comment`, `pull_request_review_comment` for feedback collection.
- `workflow_dispatch` for manual controlled runs.
- `schedule` for periodic self-review and weekly evolution reports.

## 4) Branching and Change Control

- Never commit research-improvement changes directly to default branch.
- Automated proposals always target draft PRs.
- Required status checks:
  - schema validation
  - unit tests
  - simulation validation
  - safety policy validation

## 5) Improvement Cycle Required Outputs

Each cycle must produce:

- source feedback comment metadata
- machine interpretation of requested improvement
- affected files list
- generated diff summary
- test and simulation results
- confidence estimate
- risk notes
- rollback notes

## 6) Rollback Plan

- Every proposal includes a deterministic rollback section:
  - commit SHA to revert
  - files touched
  - known side effects
  - post-rollback verification checks
- Emergency rollback is a standard Git revert PR, never force-push.

## 7) Governance Principles

- No live execution features.
- No weakening of safety guards via automation.
- No auto-merge from comments.
- No claims of confirmed alpha without reproducible evidence.
