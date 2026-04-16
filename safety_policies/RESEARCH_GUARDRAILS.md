# Research Guardrails Policy

## Non-negotiable constraints
1. No live-trading instructions, order execution, or entry/exit automation.
2. No workflow may auto-merge strategy-affecting code.
3. No workflow may weaken safety checks or branch protections.
4. All automated proposals must be draft PRs requiring human approval.
5. Every proposal must include rollback and risk notes.

## Allowed automation scope
- documentation and taxonomy updates
- evaluation and simulation configuration
- reporting and diagnostics
- hypothesis registry maintenance
- test/lint hardening

## Mandatory checks before draft PR creation
- schema validation
- unit/static checks
- simulation-validation job
- safety policy compliance check

## Rejection criteria for feedback ingestion
- requests for live trade instructions
- unsafe bypass of review requirements
- non-specific directives without testable intent
- proposals that imply irreversible changes
