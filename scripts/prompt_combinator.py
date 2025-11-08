# prompt_combinator.py
import json, os, random, subprocess, re
from pathlib import Path
from scripts.util_entropy import entropy_mix, latest_blockhash_solana, latest_block_evm

ROOT = Path(__file__).resolve().parents[1]
EVM_MAN = json.loads((ROOT/"manifests/evm_univ2.json").read_text()) if (ROOT/"manifests/evm_univ2.json").exists() else {"pairs":[]}
SOL_MAN = json.loads((ROOT/"manifests/solana_accounts.json").read_text()) if (ROOT/"manifests/solana_accounts.json").exists() else {}

OUT = ROOT/"cache/focus.json"

AXES = {
    "anomaly": ["stale_oracle","price_gap","triangular_hint","depth_kink"],
    "venue": sorted(list({p["venue"] for p in EVM_MAN.get("pairs",[])} | set([x.get("venue","RAYDIUM") for x in SOL_MAN.get("pools",[])]))),
    "symbol": sorted(list({p["symbol"] for p in EVM_MAN.get("pairs",[])} | set([x.get("symbol","SOL/USDC") for x in SOL_MAN.get("pools",[])])))
}

LLM_BIN = os.getenv("LLM_BIN","ollama")
LLM_MODEL = os.getenv("LLM_MODEL","codellama:13b")

def llm_rank(candidates, entropy):
    prompt = (
        "Rank these DeFi scan targets by likelihood of mispricing now. "
        "Return JSON array of top 8 strings only.\n"
        f"entropy={entropy}\n"
        + "\n".join(f"- {c}" for c in candidates)
    )
    try:
        out = subprocess.check_output([LLM_BIN,"run",LLM_MODEL], input=prompt.encode(), timeout=45)
        m = re.search(rb"\[(.*?)\]", out, re.S)
        arr = json.loads(m.group(0).decode()) if m else []
        return [x for x in arr if isinstance(x,str)][:8]
    except Exception:
        random.seed(entropy); random.shuffle(candidates); return candidates[:8]

def main():
    evm_rpc = EVM_MAN.get("rpc_url","")
    sol_rpc = SOL_MAN.get("rpc_url","")
    ent = entropy_mix(latest_block_evm(evm_rpc), latest_blockhash_solana(sol_rpc), ",".join(AXES["symbol"]))
    candidates = [f"{a}|{v}|{s}" for a in AXES["anomaly"] for v in AXES["venue"] for s in AXES["symbol"]]
    ranked = llm_rank(candidates, ent)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"entropy": ent, "targets": ranked}, separators=(",",":")))
    print(f"wrote {OUT} with {len(ranked)} targets")

if __name__ == "__main__":
    main()
