#!/usr/bin/env python3
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "cache"
STATE_PATH = CACHE_DIR / "governance_state.json"
PROPOSAL_DIR = ROOT / "improvement_proposals"
SIM_RUN_DIR = ROOT / "simulation_runs"
EVAL_DIR = ROOT / "evaluation_reports"

LLM_BIN = os.getenv("LLM_BIN", "ollama")
LLM_MODEL = os.getenv("LLM_MODEL", "llama3.1")


def _invoke_llm(prompt: str) -> Tuple[str, bool]:
    try:
        proc = subprocess.run(
            [LLM_BIN, "run", LLM_MODEL],
            input=prompt.encode(),
            capture_output=True,
            check=True,
            timeout=35,
        )
        return proc.stdout.decode().strip(), True
    except Exception:
        return "prioritize evidence quality and rejection discipline", False


def _count(path: Path, pattern: str) -> int:
    return len(list(path.glob(pattern))) if path.exists() else 0


def _fallback_objective(metrics: Dict[str, int]) -> str:
    if metrics["pending_proposals"] == 0:
        return "increase feedback ingestion coverage"
    if metrics["simulation_reports"] < metrics["pending_proposals"]:
        return "close simulation evidence gaps before proposing promotions"
    if metrics["evaluation_reports"] == 0:
        return "generate baseline evaluation scorecards"
    return "tighten rejection criteria for unstable hypotheses"


def build_state() -> Dict[str, object]:
    metrics = {
        "pending_proposals": _count(PROPOSAL_DIR, "*.json"),
        "simulation_reports": _count(SIM_RUN_DIR, "*.json"),
        "evaluation_reports": _count(EVAL_DIR, "*.md"),
    }

    fallback = _fallback_objective(metrics)
    prompt = (
        "You are a cautious research governance assistant. "
        "Return one short objective prioritizing safety, evidence quality, and hypothesis rejection discipline.\n"
        f"metrics={json.dumps(metrics, separators=(',', ':'))}\n"
        f"fallback={fallback}"
    )
    objective, llm_used = _invoke_llm(prompt)

    return {
        "generated_at": int(time.time()),
        "mode": "research-governed",
        "controller": "llm-governor",
        "llm_used": llm_used,
        "objective": objective[:220],
        "safety_assertions": {
            "live_trading_disabled": True,
            "human_approval_required": True,
            "auto_merge_disabled": True,
        },
        "metrics": metrics,
        "required_cycle_outputs": [
            "source_feedback",
            "interpretation",
            "affected_files",
            "diff_summary",
            "test_results",
            "simulation_results",
            "confidence",
            "risk_notes",
            "rollback_notes",
        ],
    }


def write_state(payload: Dict[str, object]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(payload, indent=2) + "\n")


def main() -> None:
    payload = build_state()
    write_state(payload)
    print(f"wrote {STATE_PATH} objective={payload['objective']}")


if __name__ == "__main__":
    main()
