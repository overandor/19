# util_entropy.py
import hashlib, time, requests

def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()

def latest_blockhash_solana(rpc_url: str) -> str:
    if not rpc_url:
        return ""
    try:
        r = requests.post(
            rpc_url,
            json={"jsonrpc":"2.0","id":1,"method":"getLatestBlockhash"},
            timeout=8,
        )
        return (r.json().get("result") or {}).get("value", {}).get("blockhash", "")
    except Exception:
        return ""

def latest_block_evm(rpc_url: str) -> str:
    if not rpc_url:
        return ""
    try:
        r = requests.post(
            rpc_url,
            json={"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]},
            timeout=8,
        )
        return r.json().get("result","")
    except Exception:
        return ""

def entropy_mix(*parts: str) -> str:
    now = str(time.time())
    return sha256_hex("|".join([now, *[p or "" for p in parts]]))
