"""Hypothesis generation engine for the speculative signal research lab."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class Hypothesis:
    id: str
    signal_class: str
    description: str
    venues: List[str]
    symbols: List[str]
    expected_edge_bps: float
    confidence: float        # 0-1
    created_at: int = field(default_factory=lambda: int(time.time()))
    status: str = "pending"  # pending | approved | rejected | tested
    rationale: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)


class HypothesisEngine:
    """Generates and manages signal hypotheses from observed market data."""

    SIGNAL_CLASSES = [
        "price_gap",
        "triangular_hint",
        "stale_oracle",
        "depth_kink",
        "funding_divergence",
    ]

    def __init__(self, registry_path: Optional[Path] = None) -> None:
        self.registry_path = registry_path
        self._registry: List[Dict] = []
        if registry_path and registry_path.exists():
            try:
                self._registry = json.loads(registry_path.read_text())
            except (json.JSONDecodeError, OSError):
                self._registry = []

    def generate(self, signals: List[Dict], max_hypotheses: int = 10) -> List[Hypothesis]:
        """Derive hypotheses from a list of raw signal observations."""
        candidates: List[Hypothesis] = []
        for sig in signals:
            edge = sig.get("edge_bps", 0)
            symbol = sig.get("symbol", "")
            sell_venue = sig.get("sell_venue", "")
            buy_venue = sig.get("buy_venue", "")

            if not symbol:
                continue

            sig_class = self._classify(sig)
            confidence = self._confidence_score(sig)
            hyp_id = f"{sig_class}|{symbol}|{int(time.time())}"

            h = Hypothesis(
                id=hyp_id,
                signal_class=sig_class,
                description=(
                    f"Potential {sig_class} between {sell_venue} (sell) and "
                    f"{buy_venue} (buy) for {symbol}. "
                    f"Gross edge {sig.get('edge_bps_gross', 0):.1f} bps, "
                    f"net {edge:.1f} bps after costs."
                ),
                venues=[v for v in [sell_venue, buy_venue] if v],
                symbols=[symbol],
                expected_edge_bps=edge,
                confidence=confidence,
                rationale=self._rationale(sig),
            )
            candidates.append(h)

        candidates.sort(key=lambda h: h.confidence * h.expected_edge_bps, reverse=True)
        return candidates[:max_hypotheses]

    def save(self, hypotheses: List[Hypothesis]) -> None:
        if not self.registry_path:
            return
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        existing = {h["id"]: h for h in self._registry}
        for h in hypotheses:
            existing[h.id] = h.to_dict()
        self._registry = list(existing.values())
        self.registry_path.write_text(json.dumps(self._registry, separators=(",", ":")))

    def load_all(self) -> List[Dict]:
        return list(self._registry)

    def _classify(self, sig: Dict) -> str:
        edge_gross = sig.get("edge_bps_gross", 0)
        edge_net   = sig.get("edge_bps", 0)
        chain      = sig.get("chain", "")

        if chain == "GATE_IO":
            return "funding_divergence"
        if edge_gross > 5 and edge_net < 0:
            return "stale_oracle"
        if edge_gross > 20:
            return "price_gap"
        return "triangular_hint"

    def _confidence_score(self, sig: Dict) -> float:
        edge_gross = abs(sig.get("edge_bps_gross", 0))
        age = int(time.time()) - sig.get("ts", int(time.time()))
        ttl = sig.get("ttl_seconds", 30) or 30
        freshness = max(0.0, 1.0 - age / ttl)
        edge_score = min(1.0, edge_gross / 50.0)
        return round(0.6 * freshness + 0.4 * edge_score, 4)

    def _rationale(self, sig: Dict) -> str:
        parts = [
            f"chain={sig.get('chain','')}",
            f"fees_bps={sig.get('assumptions', {}).get('fees_bps', '?')}",
            f"slip_bps={sig.get('assumptions', {}).get('slip_bps', '?')}",
        ]
        return "; ".join(parts)
