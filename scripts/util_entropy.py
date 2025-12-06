# util_entropy.py
import hashlib, time, requests

DEFAULT_TIMEOUT = 10

def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()

def latest_blockhash_solana(rpc_url: str) -> str:
    try:
        r = requests.post(
            rpc_url,
            json={"jsonrpc":"2.0","id":1,"method":"getLatestBlockhash"},
            timeout=DEFAULT_TIMEOUT,
        )
        return (r.json().get("result") or {}).get("value", {}).get("blockhash", "")
    except Exception:
        return ""

def latest_block_evm(rpc_url: str) -> str:
    try:
        r = requests.post(
            rpc_url,
            json={"jsonrpc":"2.0","id":1,"method":"eth_blockNumber","params":[]},
            timeout=DEFAULT_TIMEOUT,
        )
        return r.json().get("result","")
    except Exception:
        return ""

def entropy_mix(*parts: str) -> str:
    now = str(time.time())
    return sha256_hex("|".join([now, *[p or "" for p in parts]]))
