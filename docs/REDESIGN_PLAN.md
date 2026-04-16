# Repository Redesign Plan: Supervised Self-Optimizing Market Research Service

## 1) Mission Profile

Build a repository-backed, continuously running research service that:

- studies market behavior from ingested data,
- emits structured hypotheses,
- stores every hypothesis and realized outcome,
- evaluates accuracy and calibration over time,
- proposes improvements to research logic,
- requires explicit human approval before any change can become active.

### Non-Goals (hard constraints)

- No trade execution.
- No brokerage exchange order APIs.
- No autonomous strategy deployment.
- No unsupervised self-modification.

---

## 2) Target Architecture

```text
┌────────────────┐     ┌────────────────┐     ┌────────────────────┐
│ Ingestion Layer│ ──▶ │ Feature Engine │ ──▶ │ Hypothesis Engine  │
└────────────────┘     └────────────────┘     └────────────────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌────────────────┐     ┌────────────────┐     ┌────────────────────┐
│ Memory Store   │ ◀── │ Evaluation Eng.│ ◀── │ Realized Outcomes  │
└────────────────┘     └────────────────┘     └────────────────────┘
         │
         ▼
┌────────────────┐     ┌────────────────┐     ┌────────────────────┐
│ Experiment Trk.│ ──▶ │ Approval Gate  │ ──▶ │ Registry Activation │
└────────────────┘     └────────────────┘     └────────────────────┘
                                   ▲
                                   │
                            Human Reviewer
```

### Components

1. **Ingestion Layer**
   - Pulls market prices, volumes, volatility, microstructure features, and optional alt-data.
   - Writes normalized snapshots to append-only tables/files.

2. **Feature Engine**
   - Computes deterministic feature vectors with versioned feature definitions.
   - Stores both derived values and feature provenance.

3. **Hypothesis Engine**
   - Generates directional hypotheses (e.g., up/down/neutral over horizon).
   - Outputs confidence, uncertainty, rationale summary, and regime tag.

4. **Evaluation Engine**
   - Joins hypotheses with realized outcomes once horizon elapses.
   - Computes calibration, Brier/log loss, hit rate, regime-specific metrics.

5. **Memory Store**
   - Durable, queryable storage for hypothesis history, outcomes, and metadata.
   - Backed by database + repo artifacts for governance/audit.

6. **Model Registry**
   - Tracks active/candidate model versions, checksums, changelogs, tests.

7. **Prompt Registry**
   - Version-controls prompts and rationale templates used by hypothesis engine.

8. **Experiment Tracker**
   - Captures proposal intent, diffs, simulation protocol, and results.

9. **Dashboard**
   - Displays performance, drift, failure clusters, and proposal queue.

10. **Approval Gate**
   - Enforces review states: `proposed -> simulated -> review_pending -> approved/rejected`.

---

## 3) Repository Structure (Governed Memory Surface)

```text
.
├── approvals/
│   ├── approval_queue.jsonl
│   └── approval_decisions.jsonl
├── dashboards/
│   ├── metrics_snapshot.json
│   └── README.md
├── docs/
│   ├── DATA_SCHEMAS.md
│   └── REDESIGN_PLAN.md
├── evaluations/
│   ├── hypothesis_outcomes.jsonl
│   ├── calibration_reports.jsonl
│   └── confusion_reports.jsonl
├── experiments/
│   ├── proposals.jsonl
│   ├── simulations.jsonl
│   └── example_improvement_cycle.md
├── failure_mode_reports/
│   └── recurring_patterns.jsonl
├── feature_engine/
│   └── README.md
├── hypothesis_engine/
│   └── README.md
├── ingestion/
│   └── README.md
├── memory_store/
│   └── README.md
├── model_versions/
│   ├── model_registry.json
│   └── model_cards/
├── prompts/
│   ├── prompt_registry.json
│   └── hypothesis_prompt_v1.md
├── registries/
│   ├── active_config.json
│   └── changelog.jsonl
├── signal_history/
│   └── hypotheses.jsonl
└── weekly_reviews/
    └── YYYY-WW-template.md
```

**Design rule:** historical records are append-only; updates are represented by new events referencing prior IDs.

---

## 4) Data Lifecycle & Control Points

1. `observe`: ingest raw market data snapshot.
2. `featurize`: compute deterministic feature set with `feature_version`.
3. `hypothesize`: emit structured hypothesis with `hypothesis_id`.
4. `persist`: append event to `signal_history/hypotheses.jsonl`.
5. `realize`: once horizon matures, append outcome event.
6. `evaluate`: compute metric events and error labels.
7. `compare`: benchmark current config vs historical baseline.
8. `propose`: generate improvement proposal + diff.
9. `simulate`: backtest/offline replay evaluation.
10. `review`: human approves/rejects via approval queue.
11. `activate`: if approved, update registries with new active versions.
12. `archive`: write weekly summary + changelog entries.

---

## 5) Evaluation Framework

### Per-Hypothesis Evaluation

For each matured hypothesis:

- Compute realized return over target horizon.
- Determine expected sign agreement.
- Score confidence accuracy (Brier/log loss).
- Quantify uncertainty adequacy.
- Assign:
  - true positive / true negative
  - false positive / false negative
  - abstain quality (if neutral)

### Aggregate Evaluation

- Rolling metrics: 1D, 7D, 30D, regime buckets.
- Calibration curves by confidence decile.
- Drift checks for feature distributions.
- Regime-conditioned confusion matrices.
- Failure-mode clustering:
  - by regime,
  - by volatility state,
  - by spread/liquidity state,
  - by prompt/model version.

### Failure Pattern Detection

Cluster repeated misses where:

- same regime + similar feature neighborhood,
- repeated high-confidence wrong direction,
- uncertainty underestimated.

Each cluster becomes a `failure_mode_reports` artifact with suggested remediations.

---

## 6) Controlled Self-Improvement Workflow

### What can be proposed

- Prompt wording/template changes.
- Feature weighting or transformations.
- Regime classifier thresholds.
- Evaluation criteria and reporting schema.

### Mandatory gates before activation

1. Proposal logged with rationale and expected impact.
2. Diff generated against current active config.
3. Simulation run on holdout/historical windows.
4. Risk report generated (including failure regressions).
5. Human reviewer decision recorded.
6. Activation only after explicit `approved` state.

### Reviewer Checklist

- Improvement significant and statistically plausible.
- No degraded behavior in critical regimes.
- No overfitting signatures in backtests.
- Prompt/model/version provenance complete.
- Rollback path validated.

---

## 7) Versioning & Rollback Strategy

- **Prompts**: semantic versions (`prompt_hypothesis_v1.2.0`).
- **Models**: immutable artifact IDs with checksum.
- **Features**: `feature_schema_version` + migration note.
- **Active config pointer**: `registries/active_config.json`.

Rollback = move active pointers to prior approved versions, append rollback event to `registries/changelog.jsonl`.

---

## 8) Logging Format (JSONL Event Envelope)

Every persisted event uses a common envelope:

```json
{
  "event_id": "uuid",
  "event_type": "hypothesis_created",
  "event_time_utc": "2026-04-16T00:00:00Z",
  "service": "hypothesis_engine",
  "version": "1.0.0",
  "trace_id": "uuid",
  "actor": "system|human",
  "payload": {"...": "..."}
}
```

Principles:

- Append-only JSONL for auditable history.
- `trace_id` links ingestion -> hypothesis -> evaluation -> proposal.
- `actor` differentiates generated events vs reviewer actions.

---

## 9) Dashboard Requirements

Dashboard surfaces:

- Active model/prompt versions + approval status.
- Signal counts by exchange/symbol/regime.
- Calibration and confusion trends.
- Top failure clusters and unresolved issues.
- Proposal queue with simulation deltas.
- Weekly governance digest links.

---

## 10) Example Improvement Cycle (Condensed)

1. Evaluation finds repeated false positives in high-volatility mean-reversion regime.
2. System proposes prompt update requiring stricter uncertainty language and adds volatility interaction feature.
3. Proposal logged with diff + hypothesis.
4. Simulation shows:
   - false positives reduced 18%,
   - minor recall drop 3%,
   - net Brier improvement 9%.
5. Human reviewer approves with comment and scope note.
6. `active_config` updated to new prompt/model feature version.
7. Weekly review logs decision + rollback candidate.

See `experiments/example_improvement_cycle.md` for a concrete artifact walkthrough.

---

## 11) Implementation Phases

### Phase 1: Governance Foundation
- Create directory structure + schemas + append-only logs.
- Add registries and approval queue.

### Phase 2: Core Pipeline
- Implement ingestion, feature, hypothesis, evaluation services.
- Store hypotheses/outcomes end-to-end.

### Phase 3: Improvement Engine
- Add proposal generation + simulation harness.
- Add failure clustering and recommendation templates.

### Phase 4: Dashboard & Ops
- Build reviewer dashboard.
- Add weekly review automation and integrity checks.

### Phase 5: Hardening
- Add reproducibility checks, signature verification, backup policies.
- Validate rollback drills and governance audits.

