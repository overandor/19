"""Feature extraction engine — derives ML-ready features from raw signal dicts."""
from __future__ import annotations

import math
import time
from typing import Dict, List, Optional


class FeatureEngine:
    """Transforms raw signal observations into a flat numeric feature vector."""

    VENUE_INDEX: Dict[str, int] = {
        "UNISWAP_V2": 0,
        "SUSHISWAP":  1,
        "RAYDIUM":    2,
        "ORCA":       3,
        "GATE_IO":    4,
    }

    def extract(self, signal: Dict) -> Dict[str, float]:
        """Return a flat dict of numeric features for a single signal."""
        now = int(time.time())
        ts  = signal.get("ts", now)
        ttl = signal.get("ttl_seconds", 30) or 30
        assumptions = signal.get("assumptions") or {}

        edge_gross = signal.get("edge_bps_gross", 0) or 0
        edge_net   = signal.get("edge_bps", 0) or 0
        best_bid   = signal.get("best_bid", 0) or 0
        best_ask   = signal.get("best_ask", 0) or 0
        fees_bps   = assumptions.get("fees_bps", 30) or 30

        spread_abs = abs(best_bid - best_ask) if best_bid and best_ask else 0.0
        mid_price  = (best_bid + best_ask) / 2 if best_bid and best_ask else 0.0
        spread_rel = spread_abs / mid_price if mid_price else 0.0
        age_fraction = min(1.0, (now - ts) / ttl)

        sell_venue = signal.get("sell_venue", "")
        buy_venue  = signal.get("buy_venue", "")

        return {
            "edge_gross_bps":  float(edge_gross),
            "edge_net_bps":    float(edge_net),
            "edge_positive":   1.0 if edge_net > 0 else 0.0,
            "spread_abs":      float(spread_abs),
            "spread_rel":      float(spread_rel),
            "mid_price_log":   math.log(mid_price) if mid_price > 0 else 0.0,
            "fees_bps":        float(fees_bps),
            "age_fraction":    float(age_fraction),
            "ttl_seconds":     float(ttl),
            "sell_venue_idx":  float(self.VENUE_INDEX.get(sell_venue, -1)),
            "buy_venue_idx":   float(self.VENUE_INDEX.get(buy_venue, -1)),
            "chain_evm":       1.0 if signal.get("chain") == "EVM" else 0.0,
            "chain_gate":      1.0 if signal.get("chain") == "GATE_IO" else 0.0,
        }

    def extract_batch(self, signals: List[Dict]) -> List[Dict[str, float]]:
        return [self.extract(s) for s in signals]

    def feature_names(self) -> List[str]:
        return list(self.extract({}).keys())

    def to_vector(self, signal: Dict) -> List[float]:
        feats = self.extract(signal)
        return [feats[k] for k in self.feature_names()]

    def normalise(
        self,
        features: List[Dict[str, float]],
        mins: Optional[Dict[str, float]] = None,
        maxs: Optional[Dict[str, float]] = None,
    ) -> List[Dict[str, float]]:
        """Min-max normalise a batch of feature dicts."""
        if not features:
            return features
        keys = list(features[0].keys())
        if mins is None:
            mins = {k: min(f[k] for f in features) for k in keys}
        if maxs is None:
            maxs = {k: max(f[k] for f in features) for k in keys}
        result = []
        for f in features:
            normed = {}
            for k in keys:
                rng = maxs[k] - mins[k]
                normed[k] = (f[k] - mins[k]) / rng if rng else 0.0
            result.append(normed)
        return result
