#!/usr/bin/env python3
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEEDBACK_DIR = ROOT / "feedback_ingest"
PROPOSAL_DIR = ROOT / "improvement_proposals"


def latest_feedback() -> Path:
    files = sorted(FEEDBACK_DIR.glob("normalized_*.json"))
    if not files:
        raise SystemExit("no normalized feedback files found")
    return files[-1]


def build_proposal(feedback: dict) -> dict:
    proposal_id = f"prop-{int(time.time())}"
    accepted = bool(feedback.get("safety", {}).get("accepted", False))
    return {
        "proposal_id": proposal_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_feedback": {
            "event_type": feedback.get("event_type", "unknown"),
            "url": feedback.get("url", ""),
            "author": feedback.get("author", "unknown"),
            "body": feedback.get("body", ""),
        },
        "category": feedback.get("category", "documentation"),
        "summary": "Automated proposal generated from feedback ingestion.",
        "planned_changes": [
            {
                "path": "docs/",
                "change_type": "update",
                "rationale": "Improve research documentation and governance traces."
            }
        ],
        "validation_plan": [
            "python -m compileall scripts",
            "schema checks"
        ],
        "simulation_plan": [
            "simulate candidate signals across regimes"
        ],
        "safety_review": {
            "contains_live_trading": bool(feedback.get("safety", {}).get("contains_live_trading_request", False)),
            "requires_human_review": True,
            "risk_notes": [
                "machine-generated proposal",
                "must remain draft until reviewer sign-off",
                "proposal accepted by safety classifier" if accepted else "proposal should be rejected"
            ]
        },
        "rollback_plan": "Revert proposal commit; archive rationale in change_summaries/."
    }


def main() -> None:
    feedback_path = latest_feedback()
    feedback = json.loads(feedback_path.read_text())
    proposal = build_proposal(feedback)
    PROPOSAL_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PROPOSAL_DIR / f"{proposal['proposal_id']}.json"
    out_path.write_text(json.dumps(proposal, indent=2) + "\n")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
