# Module Architecture: Non-Existent Signal Discovery Lab

## Architecture Layers

1. **Feedback Ingest Layer**
   - Parses repository comments/issues/reports.
   - Normalizes to structured feedback events.

2. **Hypothesis Engine**
   - Synthesizes candidate signal families from available feature spaces.
   - Produces structured hypotheses with mechanism and failure-mode fields.

3. **Candidate Signal Registry**
   - Tracks candidate lifecycle:
     - `imagined`
     - `weakly_supported`
     - `under_test`
     - `rejected`
     - `promising`
     - `unstable`
     - `research_candidate_only`

4. **Evaluation Framework**
   - Historical simulation by regime segments.
   - Drift, calibration, and baseline comparisons.
   - Aggressive rejection logic for weak patterns.

5. **Failure Pattern Miner**
   - Mines repeated failure modes and confounders.
   - Creates entries in rejected archive and failure scorecards.

6. **Proposal & Governance Layer**
   - Converts validated improvements into branch-based draft PRs.
   - Attaches rationale, evidence, confidence, and risk.

## Data Flow (Comment -> Draft PR)

1. Event arrives in `feedback-ingest.yml`.
2. Event parsed to `feedback_ingest/*.json`.
3. Theme classification + safety filters.
4. Improvement proposal generated in `improvement_proposals/`.
5. Controlled changes applied in designated directories.
6. `simulation-validation.yml` produces evidence artifacts.
7. `draft-pr-generator.yml` opens draft PR with attached summaries.
8. Human reviewers approve/reject.

## Candidate Signal Families (Examples)

- Regime transition precursors
- Order-book asymmetry persistence
- Failed breakout signatures
- Volatility compression-release precursors
- Correlated liquidation pressure clusters
- Funding/open-interest divergence states
- Narrative-structure regime effects
- Model disagreement as uncertainty signal

## LLM Responsibilities (Bounded)

- Name and organize candidate signal classes.
- Generate hypothesis descriptions and known unknowns.
- Identify flaws and confounders.
- Summarize uncertainty explicitly.
- Never claim speculative signals are confirmed or deployable.
