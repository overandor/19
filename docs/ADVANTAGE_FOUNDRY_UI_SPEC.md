# Advantage Foundry — Five-Screen UI Specification

Status: design spec. Implemented against `advantage_foundry/` (see `docs/ADVANTAGE_FOUNDRY.md`).

The employee-facing product is five screens. Not eight tabs, not a dashboard grid.
Each screen answers exactly one question and is allowed to say exactly one thing at a time.

| Screen | The one question | Read time |
|---|---|---|
| My Edge | Where do I actually stand, and what is holding me back? | 15 s |
| Today | What do I do in the next eight hours? | 10 s |
| Experiment | What am I testing, and what is unknown about it? | 30 s |
| Why It Worked | What actually caused the thing that happened? | 45 s |
| Strategy Portfolio | Which methods are winning, and where do they travel? (manager) | 2 min |

## 0. Rules that apply to every screen

**R1 — Five nouns only.** The user must never need a vocabulary beyond:
position, constraint, strategy, result, what changes next. Internal names
(allocator, genome, diffusion cohort, propensity model) never reach the UI.

**R2 — Evidence class is always visible on any claim.** Every statement of effect
carries one of four labels, rendered as a chip, never as prose:

```
OBSERVED ASSOCIATION      grey    "appeared together — no causal claim"
PROBABLE CONTRIBUTION     blue    "likely helped, after adjustment"
EXPERIMENTALLY SUPPORTED  green   "beat a real comparison group"
UNRESOLVED                amber   "cannot be attributed yet"
```

There is no fifth chip. There is no "Proven by AI". `EXPERIMENTALLY_SUPPORTED` is
the ceiling the product can ever claim.

**R3 — No fake precision.** Contribution is rendered in bands
(`material / moderate / limited / possible / none detected`), never as `27.43%`.
Point estimates and intervals exist in the audit drawer, one tap away, labeled
as model output. Ranges beat points: "58th → 68th–74th percentile", never "→ 71st".

**R4 — Experimental is labeled at every touchpoint.** An experimental strategy
is marked on the card, in the day plan, in the result, and in the history. If a
label would be cropped by a layout, the layout is wrong.

**R5 — Every recommendation carries its exit.** Accept / Modify / Replace /
Decline / "This data is wrong" are present on every assignment card. Decline is
never buried behind a menu, never requires a reason, and never renders a warning
dialog. An override writes a learning signal, not a compliance flag.

**R6 — Uncertainty is stated, not implied.** When confidence is low the screen
says so in words ("we do not know yet whether this transfers to your territory"),
not by shrinking a progress bar.

**R7 — No ranking of people.** No screen shows a named list of employees ordered
by output. Percentiles are always cohort-relative and always opportunity-adjusted;
the raw number may be shown only alongside its adjusted counterpart.

**R8 — Degraded honestly.** When inputs are stale or a cohort is too small, the
screen shows what it cannot compute and why, and keeps the rest working. It never
substitutes a confident-looking default for a missing estimate.

---

## 1. My Edge

**Job:** orient in 15 seconds. Strength, constraint, and the three moves in play.

**Data contract** — `engine.my_edge(employee_id)`:

```
position.percentile_adjusted        int
position.percentile_raw             int | null
position.cohort_size                int
position.cohort_basis               list[str]     # what made these people comparable
position.projection                 (int, int) | null   # 30-day band
strength                            str           # one line
constraint.label                    str           # one line, the largest correctable one
constraint.correctable              bool
moves.proven                        AssignmentSummary
moves.personalized                  AssignmentSummary
moves.experimental                  AssignmentSummary | null
```

**Layout**

```
┌──────────────────────────────────────────────────────┐
│ YOUR CURRENT EDGE                                    │
│                                                      │
│ 58th percentile        among 46 comparable peers  ⓘ  │
│ opportunity-adjusted   raw position: 22 of 84        │
│                                                      │
│ Expected in 30 days    68th – 74th                   │
│ ──────────────────────────────────────────────────── │
│ STRENGTH                                             │
│ Complex institutional accounts                       │
│                                                      │
│ LARGEST CORRECTABLE CONSTRAINT                       │
│ Follow-up reliability — 63% of commitments closed    │
│ within 48h, cohort top quartile is 86%               │
│ ──────────────────────────────────────────────────── │
│ IN PLAY NOW                                          │
│ ● Proven        Resolve open commitments first    →  │
│ ● Personalized  Expand institutional coverage     →  │
│ ◆ Experiment    Nurse-coordinator-first sequence  →  │
└──────────────────────────────────────────────────────┘
```

The ⓘ on cohort opens **Why these peers**: the matching basis in plain language
("similar territory maturity, same product, comparable account opportunity,
comparable access conditions, 2–5 years tenure"). This is the fairness receipt
and it must never be more than one tap away.

**States**

- *Cohort too small* (< 12 peers): percentile is suppressed entirely. Copy:
  "Not enough comparable peers to place you fairly yet. Showing your own trend
  instead." Constraint and moves still render — constraint diagnosis does not
  depend on the cohort.
- *New hire* (< 90 days): no experimental slot; the third row reads
  "Experiments start after onboarding." No projection band.
- *Constraint not correctable by the employee* (access restriction, formulary
  block): the constraint is shown but tagged `not yours to fix` and routed to the
  manager view instead of generating actions. This is the anti-blame guarantee.

**Forbidden here:** trend sparklines of peers, any named colleague, any total
that mixes raw and adjusted numbers, "you are #17".

---

## 2. Today

**Job:** the day, as a list you can finish. Maximum five items.

**Data contract** — `engine.today(employee_id)`:

```
items[].id
items[].text                str           # imperative, ≤ 90 chars
items[].klass               proven | personalized | experimental
items[].account_ref         str | null
items[].effort_minutes      int
items[].why                 str           # one sentence, cohort-grounded
items[].evidence            EvidenceClass
items[].actions             [complete, schedule, modify, replace, decline, data_wrong]
portfolio_mix               {proven: float, personalized: float, experimental: float}
mix_reason                  str           # why *this* mix, for *this* person, today
```

**Layout**

```
┌──────────────────────────────────────────────────────┐
│ TODAY                          60 / 25 / 15  mix  ⓘ  │
│                                                      │
│ ● 1  Resolve two open commitments          20 min ✓  │
│ ● 2  Contact operations at Account 241     35 min ✓  │
│ ● 3  Drop the low-value afternoon visit     0 min ✓  │
│ ● 4  Prepare access material, Account 318   15 min ✓ │
│ ◆ 5  Test coordinator-first at Account 512  30 min ✓ │
│      EXPERIMENTAL · 14 days · reversible             │
└──────────────────────────────────────────────────────┘
```

Tapping a row expands it in place into the assignment card — it does not navigate
away. The card shows: the action sequence, why-this-cohort, expected effort,
expected effect as a band, evidence chip, and the five exits from R5.

The mix chip `60 / 25 / 15` is tappable and explains itself in one sentence:
"More proven work than usual today: you are in your first quarter on this
territory." The user is never left to guess why their day looks different from
last week's.

**States**

- *Nothing assignable*: "No high-confidence work for today. Here are two things
  worth clearing." — falls back to open commitments, never to invented busywork.
- *An item's data is stale*: the row keeps rendering with a `data from 3 days ago`
  tag rather than disappearing.
- *Declined item*: strikes through, stays visible until end of day, and the
  replacement (if any) appears directly beneath it so the swap is legible.

**Forbidden here:** more than five items, activity counts as goals
("make 12 calls"), any item whose only justification is CRM completeness.

---

## 3. Experiment

**Job:** make the test legible. What is being tried, what is genuinely unknown,
and how to stop.

**Data contract** — `engine.experiment(assignment_id)`:

```
hypothesis              str
what_is_known           str
what_is_unknown         str          # required, non-empty, never hedged away
selection_reason        str          # why *you* were eligible
sequence[]              str          # the literal steps
duration_days           int
day_index               int
primary_outcome         str
guardrails[]            str
stop_conditions[]       str
risk                    low | moderate
protections[]           str
can_stop                bool         # always true for the employee
peer_variants_visible   false        # hard-coded; see below
```

**Layout**

```
┌──────────────────────────────────────────────────────┐
│ ◆ EXPERIMENT                          day 6 of 14    │
│                                                      │
│ Contact the operational stakeholder before repeating │
│ physician outreach.                                  │
│                                                      │
│ WHAT WE KNOW                                         │
│ Promising in 34 comparable workflow-blocked accounts │
│                                    PROBABLE CONTRIB. │
│                                                      │
│ WHAT WE DO NOT KNOW                                  │
│ Whether the effect transfers to a territory with     │
│ your access profile. That is what you are testing.   │
│                                                      │
│ WHY YOU                                              │
│ You have 14 qualifying accounts and no active        │
│ medical escalation.                                  │
│                                                      │
│ THE SEQUENCE                                         │
│ 1  Contact office operations                         │
│ 2  Confirm the blocking workflow                     │
│ 3  Send the approved operational resource            │
│ 4  Resume physician outreach after classification    │
│                                                      │
│ PROTECTIONS                                          │
│ · Approved materials only                            │
│ · No contact frequency above policy                  │
│ · Not used in compensation, ranking, or review       │
│ · You can stop this at any time                      │
│                                                      │
│ [ Stop this experiment ]   [ Ask for standard work ] │
└──────────────────────────────────────────────────────┘
```

**"What we do not know" is a required field.** If the system cannot articulate the
unknown, the strategy is not an experiment — it is a guess, and it does not ship.
Rendering fails loudly (empty state: "This experiment is missing its hypothesis
and has been withdrawn") rather than quietly dropping the section.

**Peer variants are hidden during the run.** The screen never shows what other
people in the cohort were assigned. Not as a courtesy — as an integrity control:
visible variants contaminate the comparison. After the experiment closes, results
are released in aggregate on *Why It Worked* and in the manager portfolio.

**The compensation disclaimer is not fine print.** It sits in the protections list
at full weight, because experiment participation that could plausibly affect pay
is coercion, not research.

**States**

- *Stopped by employee*: acknowledges without friction — "Stopped. You are back on
  standard work." No confirmation modal, no reason field, no follow-up prompt.
- *Stopped by the system* (guardrail or negative-outcome threshold): says which
  stop condition fired, in the employee's language, same day.
- *Concluded*: converts to a result card and links to *Why It Worked*.

---

## 4. Why It Worked

**Job:** the honest post-mortem of one outcome. This is the screen the whole
product exists to earn the right to show.

**Data contract** — `engine.why_it_worked(outcome_id)`:

```
outcome.summary              str
outcome.from_state           str
outcome.to_state             str
counterfactual.observed      float
counterfactual.baseline      float        # matched comparison, not last quarter
counterfactual.lift_pp       float
counterfactual.confidence    low | moderate | high
counterfactual.confounder    str | null   # the biggest one, named
contributors[]               {actor, band, note}
unexplained                  present | minimal
what_mattered                str
what_did_not_matter          str | null
evidence                     EvidenceClass
next_move                    str | null
audit_available              bool
```

**Layout**

```
┌──────────────────────────────────────────────────────┐
│ ACCOUNT MOVEMENT              Account 241             │
│ engaged  →  access-enabled                            │
│                                                      │
│ MOST LIKELY CONTRIBUTORS          PROBABLE CONTRIB.  │
│ You (execution)                          material    │
│ Market-access team                       material    │
│ The assigned strategy                    moderate    │
│ Territory conditions                   supportive    │
│ Unexplained remainder                     present    │
│                                                      │
│ WITHOUT THIS APPROACH                                │
│ Comparable accounts progressed 29% of the time.      │
│ Yours progressed. Estimated lift +32 points,         │
│ moderate confidence.                                 │
│                                                      │
│ ⚠ A formulary improvement landed in your territory   │
│   in the same window. Some of this is not yours.     │
│                                                      │
│ WHAT MATTERED                                        │
│ Reaching the nurse manager before repeating          │
│ physician outreach.                                  │
│                                                      │
│ WHAT DID NOT APPEAR TO MATTER                        │
│ The additional clinical material.                    │
│                                                      │
│ NEXT                                                 │
│ Three of your accounts match this pattern.  [ See ]  │
│                                                      │
│ View the model output →                              │
└──────────────────────────────────────────────────────┘
```

**The confounder callout is mandatory when one exists.** A product that credits the
representative for a formulary win is lying to them, and they will find out. Naming
the confounder is what makes the *unconfounded* credit believable later.

**"Unexplained remainder: present"** appears whenever residual variance exceeds the
attribution threshold. It is a feature. The alternative — distributing 100% of
every outcome across known actors — is the fake-causality dashboard this product
is defined against.

**"What did not appear to matter"** is as valuable as what did, and is the only
place the product tells someone to stop doing work. It renders only when a
component was actually varied and measured; otherwise it is omitted, not filled
with a plausible guess.

The audit link exposes point estimates, intervals, the matched comparison set,
adjustment covariates, and model version. Labeled as model output, not as truth.

**States**

- *Unattributable* (`UNRESOLVED`): the screen says "We cannot separate your
  contribution from what else moved in your territory this month" and shows the
  candidate contributors without bands. It does not guess.
- *Negative outcome*: identical structure, no blame framing. The subject is the
  strategy, never the person: "The sequence did not move this account. It has been
  flagged for review, not counted against you."

---

## 5. Strategy Portfolio (manager)

**Job:** manage methods, not people. The only screen where cross-employee data
aggregates — and it aggregates by *strategy*, never by name.

**Data contract** — `engine.strategy_portfolio(team_id)`:

```
strategies[].name
strategies[].evidence          EvidenceClass
strategies[].adjusted_lift     (float, float)    # band, not a point
strategies[].best_fit[]        str
strategies[].known_failure     str | null
strategies[].portability       global | selective | local | non_transferable
strategies[].decay             stable | decaying | expired
strategies[].active_users      int               # count only
strategies[].decision          scale | continue | hold | retire
open_questions[]               str
```

**Layout**

```
┌──────────────────────────────────────────────────────┐
│ STRATEGY PORTFOLIO                    12 territories │
│                                                      │
│ Workflow-first 2.3            EXPERIMENTALLY SUPP.   │
│ +11 to +16%   selective   stable        24 users     │
│ Best fit: operationally blocked integrated systems   │
│ Fails when: scientific questions are still open      │
│ → Scale to 12 matched territories                    │
│ ──────────────────────────────────────────────────── │
│ Early-morning access               PROBABLE CONTRIB. │
│ +4 to +12%    local       stable         9 users     │
│ → Keep testing — effect not separated from territory │
│ ──────────────────────────────────────────────────── │
│ High-frequency revisits            EXPERIMENTALLY S. │
│ −8 to −2%     —           —             31 users     │
│ → Retire. Costs field time, no progression gain.     │
│ ──────────────────────────────────────────────────── │
│ Long evidence packets                     UNRESOLVED │
│ no effect detected                       17 users    │
│ → Remove as default; keep on request                 │
└──────────────────────────────────────────────────────┘
```

Negative results get equal billing. A portfolio that only surfaces winners is a
marketing surface; retiring "high-frequency revisits" is the highest-value row on
this screen because it gives 31 people their afternoons back.

**Coaching view** (per employee, reachable from here) shows: primary strength,
primary constraint, current intervention, observed effect. It shows *no* email
content, *no* activity feed, *no* location trail, and *no* experiment acceptance
rate. If a manager wants to know why someone declined a strategy, the product's
answer is "ask them".

**Attribution separation panel.** The manager must be able to distinguish employee
skill / strategy quality / execution quality / territory conditions /
cross-functional support / external market movement / unexplained variation. Each
outcome rolls up with those seven components intact. This is what stops a manager
from promoting the person with the easiest ZIP code.

**Forbidden here:** any employee-vs-employee ordering, any per-person experiment
compliance metric, any export that joins strategy outcomes to compensation data.

---

## 6. What the UI must never render

Hard constraints, enforced in `advantage_foundry/compliance.py` and
`advantage_foundry/governance.py`, not merely in design review:

1. A leaderboard of named employees by raw output.
2. An experiment the participant cannot see or stop.
3. A causal claim above `EXPERIMENTALLY_SUPPORTED`.
4. A contribution percentage in the default view.
5. An experimental assignment surfaced in any compensation, promotion,
   discipline, or ranking context.
6. Manager-visible private email content that policy has not already authorized.
7. Any experiment varying approved claims, safety information, fair balance,
   indication boundaries, patient targeting, or contact permissions —
   these dimensions are rejected before assignment, never at render time.
8. An override count presented as a behavior score.

## 7. Screen-to-engine map

| Screen | Engine call | Primary modules |
|---|---|---|
| My Edge | `engine.my_edge()` | `cohort`, `portfolio` |
| Today | `engine.today()` | `portfolio`, `genome`, `compliance` |
| Experiment | `engine.experiment()` | `experiments`, `compliance` |
| Why It Worked | `engine.why_it_worked()` | `attribution` |
| Strategy Portfolio | `engine.strategy_portfolio()` | `attribution`, `diffusion` |

Navigation is flat. There are no sub-tabs. If a sixth screen is proposed, the
proposal must first name which of the five it replaces.
