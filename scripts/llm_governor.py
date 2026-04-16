#!/usr/bin/env python3
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "cache"
SIGNALS_PATH = ROOT / "signals.json"
FOCUS_PATH = CACHE_DIR / "focus.json"
STATUS_PATH = CACHE_DIR / "beast_status.json"
STATE_PATH = CACHE_DIR / "governance_state.json"

LLM_BIN = os.getenv("LLM_BIN", "ollama")
LLM_MODEL = os.getenv("LLM_MODEL", "llama3.1")


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _invoke_llm(prompt: str) -> Tuple[str, bool]:
    try:
        proc = subprocess.run(
            [LLM_BIN, "run", LLM_MODEL],
            input=prompt.encode(),
            capture_output=True,
            check=True,
            timeout=45,
        )
        return proc.stdout.decode().strip(), True
    except Exception as exc:
        return f"llm_unavailable: {exc}", False


def _decision_from_metrics(metrics: Dict[str, float]) -> str:
    top_edge = metrics.get("top_edge_bps", 0.0)
    signal_count = metrics.get("signal_count", 0)
    if signal_count == 0:
        return "expand_manifests"
    if top_edge < 0:
        return "tighten_filters"
    if top_edge < 10:
        return "increase_scan_diversity"
    return "hold_course"


def build_governance_state() -> Dict[str, object]:
    signals = _load_json(SIGNALS_PATH, {"generated_at": 0, "signals": []})
    focus = _load_json(FOCUS_PATH, {"targets": [], "source": "missing"})
    status = _load_json(STATUS_PATH, {})

    rows: List[Dict] = signals.get("signals", []) if isinstance(signals, dict) else []
    top_edge = max((float(r.get("edge_bps", 0)) for r in rows), default=0.0)

    metrics = {
        "signal_count": len(rows),
        "top_edge_bps": round(top_edge, 2),
        "focus_target_count": len(focus.get("targets", [])),
        "focus_source": str(focus.get("source", "missing")),
        "beast_status": str(status.get("mode", "unknown")),
    }

    system_prompt = (
        "You are the governance model for a fully autonomous arbitrage repository. "
        "Given metrics, output a single short policy objective."
    )
    candidate_objective = _decision_from_metrics(metrics)
    llm_prompt = (
        f"{system_prompt}\n"
        f"metrics={json.dumps(metrics, separators=(",", ":"))}\n"
        f"candidate={candidate_objective}\n"
        "Return one line objective."
    )

    objective, used_llm = _invoke_llm(llm_prompt)
    if not used_llm:
        objective = candidate_objective

    return {
        "generated_at": int(time.time()),
        "mode": "self-governing",
        "controller": "llm-governor",
        "llm_used": used_llm,
        "objective": objective[:240],
        "metrics": metrics,
        "allowed_actions": [
            "update_signals",
            "refresh_focus",
            "update_readme",
            "publish_pages",
            "open_issue_on_failure",
        ],
    }


def write_state(payload: Dict[str, object]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(payload, indent=2) + "\n")


def main() -> None:
    payload = build_governance_state()
    write_state(payload)
    print(f"wrote {STATE_PATH} objective={payload['objective']}")


if __name__ == "__main__":
    main()
