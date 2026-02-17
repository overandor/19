#!/usr/bin/env python3
import json
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from scripts.edge_math import edge_bps
from scripts.evm_univ2 import fetch_prices_univ2
from scripts import solana_stub as sol
from scripts.perps_hedge import compute_perps_hedge

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "signals.json"
EVM_MANIFEST_PATH = ROOT / "manifests" / "evm_univ2.json"
SOL_MANIFEST_PATH = ROOT / "manifests" / "solana_accounts.json"
FOCUS_PATH = ROOT / "cache" / "focus.json"
PERPS_HEDGE_PATH = ROOT / "manifests" / "perps_hedge.json"
PERPS_VENUES_PATH = ROOT / "manifests" / "perps_venues.json"

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




def _eligible_perp_venues(venues_manifest: Dict[str, object], max_fee_usd: Optional[float] = None) -> List[Dict[str, object]]:
    default_limit = venues_manifest.get("max_network_fee_usd", 0.10) if isinstance(venues_manifest, dict) else 0.10
    fee_limit = float(max_fee_usd) if max_fee_usd is not None else float(default_limit)
    venues = venues_manifest.get("venues", []) if isinstance(venues_manifest, dict) else []

    eligible: List[Dict[str, object]] = []
    for row in venues:
        if not isinstance(row, dict):
            continue
        fee = row.get("estimated_network_fee_usd")
        if fee is None:
            continue
        if float(fee) <= fee_limit:
            eligible.append(
                {
                    "venue": row.get("venue"),
                    "network": row.get("network"),
                    "instrument_type": row.get("instrument_type", "perps"),
                    "estimated_network_fee_usd": float(fee),
                }
            )
    return eligible

def _best_edges(prices: Iterable[Dict], targets: Iterable[str], hedge_manifest: Dict[str, object], venues_manifest: Dict[str, object]) -> List[Dict[str, object]]:
    grouped: Dict[str, List[Dict]] = {}
    for item in prices:
        if not isinstance(item, dict) or "error" in item:
            continue
        symbol = item.get("symbol")
        if not symbol:
            continue
        grouped.setdefault(symbol, []).append(item)

    now = int(time.time())
    venue_limit = hedge_manifest.get("max_network_fee_usd") if isinstance(hedge_manifest, dict) else None
    eligible_venues = _eligible_perp_venues(venues_manifest, venue_limit)
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
        defaults = hedge_manifest.get("defaults", {}) if isinstance(hedge_manifest, dict) else {}
        symbol_overrides = hedge_manifest.get("symbols", {}) if isinstance(hedge_manifest, dict) else {}
        symbol_cfg = symbol_overrides.get(symbol, {}) if isinstance(symbol_overrides, dict) else {}
        hedge_cfg = {
            "spot_notional_usd": symbol_cfg.get("spot_notional_usd", defaults.get("spot_notional_usd", 10000)),
            "perp_taker_bps_roundtrip": symbol_cfg.get("perp_taker_bps_roundtrip", defaults.get("perp_taker_bps_roundtrip", 8)),
            "funding_rate_bps_8h": symbol_cfg.get("funding_rate_bps_8h", defaults.get("funding_rate_bps_8h", 0)),
            "borrow_apr_bps": symbol_cfg.get("borrow_apr_bps", defaults.get("borrow_apr_bps", 0)),
            "expected_hold_hours": symbol_cfg.get("expected_hold_hours", defaults.get("expected_hold_hours", 1)),
        }
        hedge = compute_perps_hedge(
            buy_price=best_ask["mid"],
            sell_price=best_bid["mid"],
            spot_notional_usd=hedge_cfg["spot_notional_usd"],
            dex_fees_bps_roundtrip=fees,
            slip_bps=SLIP_BPS,
            buffer_bps=BUFFER_BPS,
            perp_taker_bps_roundtrip=hedge_cfg["perp_taker_bps_roundtrip"],
            funding_rate_bps_8h=hedge_cfg["funding_rate_bps_8h"],
            borrow_apr_bps=hedge_cfg["borrow_apr_bps"],
            expected_hold_hours=hedge_cfg["expected_hold_hours"],
        )

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
                "perps_hedge": {
                    "config": hedge_cfg,
                    "eligible_venues": eligible_venues,
                    "result": hedge,
                },
            }
        )
    return signals


def generate_signals(
    evm_manifest: Optional[Dict] = None,
    sol_manifest: Optional[Dict] = None,
    focus_targets: Optional[Iterable[str]] = None,
    hedge_manifest: Optional[Dict] = None,
    venues_manifest: Optional[Dict] = None,
) -> Dict[str, object]:
    evm_manifest = evm_manifest if isinstance(evm_manifest, dict) else _load_json(EVM_MANIFEST_PATH, {"pairs": []})
    sol_manifest = sol_manifest if isinstance(sol_manifest, dict) else _load_json(SOL_MANIFEST_PATH, {})
    focus_targets = list(focus_targets) if focus_targets is not None else _load_focus(FOCUS_PATH)
    hedge_manifest = hedge_manifest if isinstance(hedge_manifest, dict) else _load_json(PERPS_HEDGE_PATH, {})
    venues_manifest = venues_manifest if isinstance(venues_manifest, dict) else _load_json(PERPS_VENUES_PATH, {})

    signals: List[Dict[str, object]] = []

    if evm_manifest.get("pairs"):
        prices = fetch_prices_univ2(evm_manifest)
        signals.extend(_best_edges(prices, focus_targets, hedge_manifest, venues_manifest))

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
