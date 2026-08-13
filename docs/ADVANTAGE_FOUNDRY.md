# Advantage Foundry

A controlled market for organizational strategies.

Different credible strategies are assigned to comparable employees, executed
under controlled conditions, measured against fair baselines, causally
evaluated, and selectively redistributed to the contexts where they are most
likely to repeat.

Not a leaderboard. Not a coaching chatbot. Not a recommendation dashboard.

- Product definition and the loop: this document.
- The five screens: `docs/ADVANTAGE_FOUNDRY_UI_SPEC.md`.
- Reference implementation: `advantage_foundry/`.
- Behavioural guarantees, as tests: `tests/test_advantage_foundry.py`.

## The loop

```
diagnose → assign → execute → observe → attribute → test portability
        → evolve → redistribute
```

The central output is never "Employee 17 won". It is:

> Workflow-first outreach created a repeatable advantage for operationally
> blocked integrated accounts, with moderate-to-high confidence. Expand it to
> twelve matched territories and test whether the timing component improves.

## What the user understands

Five things, and nothing else:

```
Your position   Your constraint   Your strategy   Your result   What changes next
```

Everything below that line — allocation, genomes, cohort matching, diffusion
planning — is implementation and stays out of the interface.

## Modules

| Module | Responsibility | Refuses |
|---|---|---|
| `compliance.py` | What a strategy may vary | Any variation touching medical, promotional, or privacy truth; unreviewed dimensions |
| `genome.py` | Structured, comparable, recombinable strategies | Lifecycle skips; components inherited from unsupported parents |
| `cohort.py` | Who counts as a peer; territory adjustment | Placing anyone against a cohort too small to be fair |
| `portfolio.py` | Explore vs exploit; today's assignments | Assigning a challenger materially worse than the proven option |
| `experiments.py` | Contracts, allocation, stop conditions | A contract that cannot name its unknown |
| `attribution.py` | What probably caused the outcome | Fake precision; a fully-explained outcome |
| `diffusion.py` | Portability, repeatability, decay, expansion | Scaling a person-dependent or decaying effect |
| `governance.py` | The constraints that cannot be design decisions | Experimental work reaching pay, ranking, or a surveillance feed |
| `engine.py` | One call per screen | — |

## The primitive

The fundamental object is not a task and not a recommendation. It is a
**strategy assignment**: an operating method, the conditions it applies under,
and the test attached to it.

```python
from advantage_foundry import AdvantageFoundry

plan = foundry.today("jordan-lee", context)
plan["items"][0]
# {"strategy_name": "Workflow-first follow-up",
#  "klass": "proven",
#  "sequence": ["Contact office operations", "Confirm the blocking workflow", ...],
#  "why": "Comparable accounts blocked by workflow progressed more often ...",
#  "evidence": "experimentally_supported",
#  "expected_effect": (0.11, 0.16),
#  "not_for_evaluation": True,
#  "actions": ("complete", "schedule", "modify", "replace", "decline", "data_wrong")}
```

## Four levels of evidence

`EXPERIMENTALLY_SUPPORTED` is the ceiling. There is no label meaning "proven",
and observational data cannot reach the ceiling no matter how good it looks —
that class is granted only by `experiments.conclude()`, from an allocated
comparison group.

```
unresolved                 cannot be attributed yet
observed_association       appeared together — no causal claim
probable_contribution      likely helped, after adjustment
experimentally_supported   beat a real comparison group
```

## Fair comparison

An employee is compared only to peers on the same product, under the same market
restrictions, in the same tenure band, with territory conditions within a
tolerance that widens only as far as it must. Below twelve peers, the percentile
is suppressed rather than published.

Results are divided by the advantage the territory supplied:

```
advantage_multiplier = (opportunity × maturity × resources) / access_difficulty
adjusted_result      = observed_result / advantage_multiplier
```

Note the direction on `access_difficulty`. The original sketch divided the
observed result *by* access difficulty, which would have handed the best adjusted
scores to whoever had the easiest access — precisely backwards. Harder access
raises the adjusted result: the same work done through more resistance is worth
more, not less.

Raw and adjusted placements are always returned together. The gap between them is
the whole point.

## Bounded exploration

The daily mix defaults to 60 / 25 / 15 and moves with tenure, market stability,
evidence density, launch windows, compliance risk, reversibility, and the
employee's own participation setting. Experimental share is capped at 25% and
forced to zero for new hires, opted-out employees, high-risk activity, and
irreversible work.

Two guardrails matter more than the ratio:

1. **`MIN_EXPECTED_RATIO`** — a challenger's lower credible bound must reach 85%
   of the best proven option's expected effect. A challenger that might be much
   worse is not a bold experiment; it is a cost imposed on someone who did not
   choose it.
2. **Every mix explains itself.** A day that looks different from yesterday's
   arrives with the sentence that says why.

## Bounded evolution

Successful strategies decompose into components — stakeholder, timing, sequence,
content, escalation. `recombine()` builds a challenger from components of
supported parents. The child inherits the union of its parents' varied dimensions
(so the compliance gate still applies) and the *intersection* of their use
conditions (so it cannot wander into contexts none of its components were
measured in), and it enters at `PROPOSED` / `UNRESOLVED`.

Nothing is generated. Only recombined.

## Pharma boundary

Permitted variation: timing, channel, route, stakeholder selection,
approved-content sequencing, workflow organization, follow-up interval, account
prioritization, administrative execution.

Never varied: approved claims, safety information, scientific evidence, fair
balance, indication boundaries, privacy restrictions, promotional permissions,
patient-level targeting, permitted contact rules.

Unknown dimensions are treated as violations — an unreviewed dimension in a
regulated channel is exactly the failure this gate exists to prevent.

The system may experiment with how approved work is organized. It may not
experiment with medical truth.

## What this must never become

Enforced in code, not in design review:

- a raw sales leaderboard;
- a secret experimentation platform;
- a compensation algorithm;
- a CRM-activity maximizer;
- a manager surveillance feed;
- a system that knowingly assigns inferior strategies;
- a mechanism for testing unapproved claims;
- a fake causality dashboard.

Experiment participation may never determine compensation, promotion,
discipline, termination, or ranking. Assignments carry `not_for_evaluation` and
`governance.assert_not_evaluative()` raises if one reaches an evaluative surface.

Overrides are data. `governance.override_is_signal()` drops the employee id, so
nothing downstream can accumulate a disobedience score.

## The moat

Not the model. The accumulated context–strategy–execution–outcome graph:

> Which sequence works for which employee, in which territory, against which
> barrier, under which market conditions, and for how long.

A competitor can buy the same CRM and use the same language model. It cannot
reconstruct this causal history.
