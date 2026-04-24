"""Evaluation engine — scores hypotheses against historical signal data."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class EvaluationResult:
    hypothesis_id: str
    evaluated_at: int = field(default_factory=lambda: int(time.time()))
    observations: int = 0
    positive_edge_count: int = 0
    hit_rate: float = 0.0
    mean_edge_bps: float = 0.0
    max_edge_bps: float = 0.0
    min_edge_bps: float = 0.0
    verdict: str = "insufficient_data"  # viable | marginal | rejected | insufficient_data
    score: float = 0.0                  # 0-100

    def to_dict(self) -> Dict:
        return asdict(self)


class EvaluationEngine:
    """Evaluates a hypothesis against a stream of signal observations."""

    VIABLE_HIT_RATE   = 0.40
    VIABLE_MEAN_EDGE  = 0.0
    MARGINAL_HIT_RATE = 0.20

    def __init__(self, results_path: Optional[Path] = None) -> None:
        self.results_path = results_path
        self._results: List[Dict] = []
        if results_path and results_path.exists():
            try:
                self._results = json.loads(results_path.read_text())
            except (json.JSONDecodeError, OSError):
                self._results = []

    def evaluate(self, hypothesis: Dict, signals: List[Dict]) -> EvaluationResult:
        """Score a hypothesis against matching signals."""
        hyp_symbols = set(hypothesis.get("symbols", []))
        hyp_venues  = set(hypothesis.get("venues", []))

        matching = [
            s for s in signals
            if (not hyp_symbols or s.get("symbol") in hyp_symbols)
            and (not hyp_venues  or s.get("sell_venue") in hyp_venues
                                 or s.get("buy_venue")  in hyp_venues)
        ]

        result = EvaluationResult(hypothesis_id=hypothesis.get("id", "unknown"))

        if not matching:
            return result

        edges = [s.get("edge_bps", 0) for s in matching]
        positive = [e for e in edges if e > 0]

        result.observations        = len(edges)
        result.positive_edge_count = len(positive)
        result.hit_rate            = len(positive) / len(edges)
        result.mean_edge_bps       = sum(edges) / len(edges)
        result.max_edge_bps        = max(edges)
        result.min_edge_bps        = min(edges)
        result.verdict             = self._verdict(result)
        result.score               = self._score(result)

        return result

    def batch_evaluate(self, hypotheses: List[Dict], signals: List[Dict]) -> List[EvaluationResult]:
        return [self.evaluate(h, signals) for h in hypotheses]

    def save(self, results: List[EvaluationResult]) -> None:
        if not self.results_path:
            return
        self.results_path.parent.mkdir(parents=True, exist_ok=True)
        existing = {r["hypothesis_id"]: r for r in self._results}
        for r in results:
            existing[r.hypothesis_id] = r.to_dict()
        self._results = list(existing.values())
        self.results_path.write_text(json.dumps(self._results, separators=(",", ":")))

    def load_all(self) -> List[Dict]:
        return list(self._results)

    def _verdict(self, r: EvaluationResult) -> str:
        if r.observations < 3:
            return "insufficient_data"
        if r.hit_rate >= self.VIABLE_HIT_RATE and r.mean_edge_bps >= self.VIABLE_MEAN_EDGE:
            return "viable"
        if r.hit_rate >= self.MARGINAL_HIT_RATE:
            return "marginal"
        return "rejected"

    def _score(self, r: EvaluationResult) -> float:
        if r.observations == 0:
            return 0.0
        hit_component  = r.hit_rate * 40.0
        edge_component = max(0.0, min(r.mean_edge_bps / 50.0, 1.0)) * 40.0
        obs_component  = min(r.observations / 20.0, 1.0) * 20.0
        return round(hit_component + edge_component + obs_component, 2)
