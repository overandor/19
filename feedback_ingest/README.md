# Feedback ingest

This folder stores normalized feedback events used to generate governed improvement proposals.

- input sources: issue comments, PR comments, issue bodies, manual feedback artifacts
- output: proposal-ready JSON records with category labels and safety flags
- unsafe or vague requests are rejected with explicit reasons
