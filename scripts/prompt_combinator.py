import json
import os
import random
import re
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from scripts.util_entropy import (
    entropy_mix,
    latest_block_evm,
    latest_blockhash_solana,
)

ROOT = Path(__file__).resolve().parents[1]
FOCUS_PATH = ROOT / "cache" / "focus.json"

LLM_BIN = os.getenv("LLM_BIN", "ollama")
LLM_MODEL = os.getenv("LLM_MODEL", "codellama:13b")
DEFAULT_LIMIT = 8


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default
    except json.JSONDecodeError:
        return default


def _build_axes(evm_manifest: Dict, sol_manifest: Dict) -> Dict[str, List[str]]:
    evm_pairs = evm_manifest.get("pairs", []) if isinstance(evm_manifest, dict) else []
    sol_pools = sol_manifest.get("pools", []) if isinstance(sol_manifest, dict) else []

    venues = {p.get("venue") for p in evm_pairs if p.get("venue")}
    venues |= {p.get("venue", "RAYDIUM") for p in sol_pools}

    symbols = {p.get("symbol") for p in evm_pairs if p.get("symbol")}
    symbols |= {p.get("symbol", "SOL/USDC") for p in sol_pools}

    return {
        "anomaly": ["stale_oracle", "price_gap", "triangular_hint", "depth_kink"],
        "venue": sorted(v for v in venues if v),
        "symbol": sorted(s for s in symbols if s),
    }


def _enumerate_candidates(axes: Dict[str, List[str]]) -> List[str]:
    anomalies = axes.get("anomaly", [])
    venues = axes.get("venue", [])
    symbols = axes.get("symbol", [])
    return [f"{a}|{v}|{s}" for a in anomalies for v in venues for s in symbols]


def _invoke_llm(prompt: str) -> Tuple[str, bool]:
    try:
        proc = subprocess.run(
            [LLM_BIN, "run", LLM_MODEL],
            input=prompt.encode(),
            capture_output=True,
            check=True,
            timeout=45,
        )
        return proc.stdout.decode(), True
    except Exception as exc:
        return str(exc), False


def _extract_ranked(output: str, limit: int) -> List[str]:
    match = re.search(r"\[(.*?)\]", output, re.S)
    if not match:
        return []
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed if isinstance(item, str)][:limit]


def llm_rank(candidates: Iterable[str], entropy: str, limit: int = DEFAULT_LIMIT) -> Tuple[List[str], str, str]:
    candidates = list(candidates)
    prompt = (
        "Rank these DeFi scan targets by likelihood of mispricing now. "
        "Return JSON array of top strings only.\n"
        f"entropy={entropy}\n"
        + "\n".join(f"- {c}" for c in candidates)
    )
    raw, ok = _invoke_llm(prompt)
    if ok:
        ranked = _extract_ranked(raw, limit)
        if ranked:
            return ranked, raw, "llm"
    random.seed(entropy)
    random.shuffle(candidates)
    return candidates[:limit], raw, "fallback"


def compute_focus(write: bool = True, root: Path = ROOT) -> Dict[str, object]:
    evm_manifest = _load_json(root / "manifests" / "evm_univ2.json", {"pairs": []})
    sol_manifest = _load_json(root / "manifests" / "solana_accounts.json", {})

    axes = _build_axes(evm_manifest, sol_manifest)
    entropy = entropy_mix(
        latest_block_evm(evm_manifest.get("rpc_url", "")),
        latest_blockhash_solana(sol_manifest.get("rpc_url", "")),
        ",".join(axes.get("symbol", [])),
    )

    candidates = _enumerate_candidates(axes)
    if candidates:
        targets, raw, source = llm_rank(candidates, entropy)
    else:
        targets, raw, source = [], "no candidates", "empty"

    payload = {
        "entropy": entropy,
        "targets": targets,
        "source": source,
        "raw": raw,
    }

    if write:
        path = FOCUS_PATH if root == ROOT else root / "cache" / "focus.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, separators=(",", ":")))

    return payload


def main() -> None:
    payload = compute_focus(write=True)
    print(f"wrote {FOCUS_PATH} with {len(payload['targets'])} targets")


if __name__ == "__main__":
    main()
