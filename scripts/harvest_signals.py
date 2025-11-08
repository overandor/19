#!/usr/bin/env python3
import json
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from scripts.edge_math import edge_bps
from scripts.evm_univ2 import fetch_prices_univ2
from scripts import solana_stub as sol

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "signals.json"
EVM_MANIFEST_PATH = ROOT / "manifests" / "evm_univ2.json"
SOL_MANIFEST_PATH = ROOT / "manifests" / "solana_accounts.json"
FOCUS_PATH = ROOT / "cache" / "focus.json"

SLIP_BPS = 3
BUFFER_BPS = 2
TTL_SECONDS = 30


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default
    except json.JSONDecodeError:
        return default


def _load_focus(path: Path) -> List[str]:
    data = _load_json(path, {})
    targets = data.get("targets", []) if isinstance(data, dict) else []
    return [str(t) for t in targets]


def _focus_filter(symbol: str, venue: str, targets: Iterable[str]) -> bool:
    targets = set(targets)
    if not targets:
        return True
    key_price = f"price_gap|{venue}|{symbol}"
    key_tri = f"triangular_hint|{venue}|{symbol}"
    return key_price in targets or key_tri in targets


def _best_edges(prices: Iterable[Dict], targets: Iterable[str]) -> List[Dict[str, object]]:
    grouped: Dict[str, List[Dict]] = {}
    for item in prices:
        if not isinstance(item, dict) or "error" in item:
            continue
        symbol = item.get("symbol")
        if not symbol:
            continue
        grouped.setdefault(symbol, []).append(item)

    now = int(time.time())
    signals: List[Dict[str, object]] = []
    for symbol, rows in grouped.items():
        if len(rows) < 2:
            continue
        best_ask = min(rows, key=lambda r: r["mid"])
        best_bid = max(rows, key=lambda r: r["mid"])
        if not _focus_filter(symbol, best_ask.get("venue", ""), targets) and not _focus_filter(
            symbol, best_bid.get("venue", ""), targets
        ):
            continue
        fees = max(best_ask.get("fees_bps_roundtrip", 0), best_bid.get("fees_bps_roundtrip", 0))
        gross_edge = edge_bps(best_bid["mid"], best_ask["mid"], fees_bps=0, slip_bps=0, buffer_bps=0)
        edge = edge_bps(best_bid["mid"], best_ask["mid"], fees_bps=fees, slip_bps=SLIP_BPS, buffer_bps=BUFFER_BPS)
        signals.append(
            {
                "chain": "EVM",
                "symbol": symbol,
                "best_bid": best_bid["mid"],
                "best_ask": best_ask["mid"],
                "sell_venue": best_bid.get("venue"),
                "buy_venue": best_ask.get("venue"),
                "edge_bps_gross": gross_edge,
                "edge_bps": edge,
                "ttl_seconds": TTL_SECONDS,
                "ts": now,
                "assumptions": {
                    "fees_bps": fees,
                    "slip_bps": SLIP_BPS,
                    "buffer_bps": BUFFER_BPS,
                },
            }
        )
    return signals


def generate_signals(
    evm_manifest: Optional[Dict] = None,
    sol_manifest: Optional[Dict] = None,
    focus_targets: Optional[Iterable[str]] = None,
) -> Dict[str, object]:
    evm_manifest = evm_manifest if isinstance(evm_manifest, dict) else _load_json(EVM_MANIFEST_PATH, {"pairs": []})
    sol_manifest = sol_manifest if isinstance(sol_manifest, dict) else _load_json(SOL_MANIFEST_PATH, {})
    focus_targets = list(focus_targets) if focus_targets is not None else _load_focus(FOCUS_PATH)

    signals: List[Dict[str, object]] = []

    if evm_manifest.get("pairs"):
        prices = fetch_prices_univ2(evm_manifest)
        signals.extend(_best_edges(prices, focus_targets))

    if sol_manifest:
        try:
            sol.fetch_pyth_prices(sol_manifest)
        except Exception:
            pass

    payload = {
        "generated_at": int(time.time()),
        "signals": sorted(signals, key=lambda x: -x["edge_bps"]),
    }
    return payload


def write_signals(payload: Dict[str, object], out_path: Path = OUT_PATH) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, separators=(",", ":")))
    return out_path


def main() -> None:
    payload = generate_signals()
    write_signals(payload, OUT_PATH)
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
