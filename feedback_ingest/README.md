# Feedback Ingest

Purpose:
- parse issue comments, PR comments, and manual review notes,
- classify feedback into improvement themes,
- reject unsafe or vague suggestions.

Outputs:
- `feedback_ingest/classified_feedback.json`
- references used by `improvement_proposals/`.
