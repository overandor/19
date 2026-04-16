#!/usr/bin/env python3
import json
import os
import re
from pathlib import Path
from typing import Dict

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "feedback_ingest"


def classify(text: str) -> str:
    text_l = text.lower()
    rules = [
        (r"\b(doc|readme|explain|template)\b", "documentation"),
        (r"\b(test|validation|simulate|backtest|regime)\b", "evaluation"),
        (r"\b(feature|embedding|taxonomy|signal class)\b", "feature_extraction"),
        (r"\b(report|dashboard|summary|scorecard)\b", "reporting"),
        (r"\b(arch|workflow|pipeline|governance)\b", "architecture"),
    ]
    for pattern, label in rules:
        if re.search(pattern, text_l):
            return label
    return "documentation"


def safety_flags(text: str) -> Dict[str, bool]:
    text_l = text.lower()
    live_terms = ["buy now", "short now", "market order", "live trade", "entry price"]
    contains_live = any(term in text_l for term in live_terms)
    is_vague = len(text_l.strip()) < 20
    return {
        "contains_live_trading_request": contains_live,
        "is_too_vague": is_vague,
        "accepted": (not contains_live) and (not is_vague),
    }


def normalize_event(payload: Dict) -> Dict:
    body = str(payload.get("body", ""))
    output = {
        "event_type": payload.get("event_type", "manual"),
        "comment_id": str(payload.get("comment_id", "manual-0")),
        "author": payload.get("author", "unknown"),
        "body": body,
        "created_at": payload.get("created_at", ""),
        "url": payload.get("url", ""),
    }
    output["category"] = classify(body)
    output["safety"] = safety_flags(body)
    return output


def main() -> None:
    event_path = os.getenv("FEEDBACK_EVENT_PATH", "")
    if event_path and Path(event_path).exists():
        payload = json.loads(Path(event_path).read_text())
    else:
        payload = {
            "event_type": "manual",
            "comment_id": "manual-0",
            "author": "local",
            "body": "Manual architecture review request",
            "created_at": "",
            "url": "",
        }

    normalized = normalize_event(payload)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"normalized_{normalized['comment_id']}.json"
    out_path.write_text(json.dumps(normalized, indent=2) + "\n")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
