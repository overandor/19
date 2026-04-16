# Safety Policy: Research-Only Operation

## Hard Constraints

1. The repository must not emit live executable trade entries, order instructions, or broker-executable commands.
2. Automated workflows must not auto-merge strategy, risk, or execution logic.
3. Any automated change must be reviewable, testable, and reversible.
4. Suggestions derived from comments must pass safety and scope validation before proposal generation.
5. Safety gates may not be weakened by self-improvement workflows.

## Forbidden Automation Outcomes

- Enabling live trading execution paths.
- Generating direct trade calls, entries, or allocations.
- Circumventing branch protections or mandatory approvals.
- Claiming certainty for speculative signal hypotheses.

## Required Controls

- branch-only proposal generation
- draft PR requirement
- CI test + simulation checks
- mandatory human approval before merge
- rollback notes in every proposal

## Incident Response

If a workflow proposes unsafe logic:

1. mark proposal as blocked
2. open safety incident record in `evaluation_reports/`
3. require human security review
4. archive proposal under rejected change artifacts
