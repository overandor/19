#!/usr/bin/env python3
import json
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from scripts import solana_stub as sol
from scripts.edge_math import edge_bps
from scripts.evm_univ2 import fetch_prices_univ2
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
MIN_PERP_VENUES = 4
MAX_PERP_VENUES = 14
NETWORK_PRIORITIES = {"base": 0, "solana": 1, "arbitrum": 2, "hyperliquid": 3, "bsc": 4}


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


def _merge_hedge_cfg(hedge_manifest: Dict[str, object], symbol: str) -> Dict[str, object]:
    defaults = hedge_manifest.get("defaults", {}) if isinstance(hedge_manifest, dict) else {}
    symbol_overrides = hedge_manifest.get("symbols", {}) if isinstance(hedge_manifest, dict) else {}
    symbol_cfg = symbol_overrides.get(symbol, {}) if isinstance(symbol_overrides, dict) else {}
    merged = {
        "spot_notional_usd": symbol_cfg.get("spot_notional_usd", defaults.get("spot_notional_usd", 10000)),
        "perp_taker_bps_roundtrip": symbol_cfg.get(
            "perp_taker_bps_roundtrip", defaults.get("perp_taker_bps_roundtrip", 8)
        ),
        "funding_rate_bps_8h": symbol_cfg.get("funding_rate_bps_8h", defaults.get("funding_rate_bps_8h", 0)),
        "borrow_apr_bps": symbol_cfg.get("borrow_apr_bps", defaults.get("borrow_apr_bps", 0)),
        "expected_hold_hours": symbol_cfg.get("expected_hold_hours", defaults.get("expected_hold_hours", 1)),
        "max_network_fee_usd": symbol_cfg.get(
            "max_network_fee_usd",
            hedge_manifest.get("max_network_fee_usd", defaults.get("max_network_fee_usd", 0.10)),
        ),
        "preferred_networks": symbol_cfg.get(
            "preferred_networks", defaults.get("preferred_networks", ["base", "solana", "arbitrum", "hyperliquid", "bsc"])
        ),
        "min_venues": symbol_cfg.get("min_venues", defaults.get("min_venues", MIN_PERP_VENUES)),
        "max_venues": symbol_cfg.get("max_venues", defaults.get("max_venues", MAX_PERP_VENUES)),
    }
    min_venues = max(int(merged["min_venues"]), MIN_PERP_VENUES)
    max_venues = min(int(merged["max_venues"]), MAX_PERP_VENUES)
    if max_venues < min_venues:
        max_venues = min_venues
    merged["min_venues"] = min_venues
    merged["max_venues"] = max_venues
    return merged


def _select_perp_venues(venues_manifest: Dict[str, object], hedge_cfg: Dict[str, object]) -> Dict[str, object]:
    venues = venues_manifest.get("venues", []) if isinstance(venues_manifest, dict) else []
    max_fee_usd = float(hedge_cfg.get("max_network_fee_usd", 0.10))
    preferred = [str(x) for x in hedge_cfg.get("preferred_networks", [])]
    preferred_order = {name: idx for idx, name in enumerate(preferred)}

    filtered: List[Dict[str, object]] = []
    for row in venues:
        if not isinstance(row, dict):
            continue
        fee = row.get("estimated_network_fee_usd")
        venue = row.get("venue")
        network = row.get("network")
        if fee is None or venue is None or network is None:
            continue
        fee_f = float(fee)
        if fee_f > max_fee_usd:
            continue
        filtered.append(
            {
                "venue": str(venue),
                "network": str(network),
                "instrument_type": str(row.get("instrument_type", "perps")),
                "estimated_network_fee_usd": fee_f,
                "notes": str(row.get("notes", "")),
            }
        )

    filtered.sort(
        key=lambda x: (
            preferred_order.get(x["network"], NETWORK_PRIORITIES.get(x["network"], 99)),
            x["estimated_network_fee_usd"],
            x["venue"],
        )
    )

    selected = filtered[: int(hedge_cfg["max_venues"])]
    return {
        "selected": selected,
        "selected_count": len(selected),
        "required_min_count": int(hedge_cfg["min_venues"]),
        "is_min_satisfied": len(selected) >= int(hedge_cfg["min_venues"]),
    }


def _best_edges(
    prices: Iterable[Dict],
    targets: Iterable[str],
    hedge_manifest: Dict[str, object],
    venues_manifest: Dict[str, object],
) -> List[Dict[str, object]]:
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

        hedge_cfg = _merge_hedge_cfg(hedge_manifest, symbol)
        venue_selection = _select_perp_venues(venues_manifest, hedge_cfg)
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
                    "eligible_venues": venue_selection["selected"],
                    "eligible_venues_meta": {
                        "selected_count": venue_selection["selected_count"],
                        "required_min_count": venue_selection["required_min_count"],
                        "is_min_satisfied": venue_selection["is_min_satisfied"],
                    },
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
