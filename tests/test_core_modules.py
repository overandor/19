"""Tests for core/ modules."""
import time
import pytest

from core.hypothesis_engine import HypothesisEngine, Hypothesis
from core.evaluation_engine import EvaluationEngine
from core.feature_engine import FeatureEngine
from core.approval_gate import ApprovalGate, GateDecision


# ── Shared fixtures ────────────────────────────────────────────────────────

SAMPLE_SIGNAL = {
    "chain": "EVM",
    "symbol": "WETH/USDC",
    "best_bid": 3438.23,
    "best_ask": 3435.23,
    "sell_venue": "UNISWAP_V2",
    "buy_venue": "SUSHISWAP",
    "edge_bps_gross": 8.71,
    "edge_bps": -26.28,
    "ttl_seconds": 30,
    "ts": int(time.time()),
    "assumptions": {"fees_bps": 30, "slip_bps": 3, "buffer_bps": 2},
}


# ── HypothesisEngine ──────────────────────────────────────────────────────

class TestHypothesisEngine:
    def test_generate_returns_hypothesis(self):
        engine = HypothesisEngine()
        hyps = engine.generate([SAMPLE_SIGNAL])
        assert len(hyps) >= 1
        assert isinstance(hyps[0], Hypothesis)

    def test_generate_empty_signals(self):
        engine = HypothesisEngine()
        assert engine.generate([]) == []

    def test_generate_classifies_gate_as_funding(self):
        gate_sig = {**SAMPLE_SIGNAL, "chain": "GATE_IO", "symbol": "BTC/USDT"}
        engine = HypothesisEngine()
        hyps = engine.generate([gate_sig])
        assert hyps[0].signal_class == "funding_divergence"

    def test_max_hypotheses_respected(self):
        signals = [SAMPLE_SIGNAL] * 20
        engine = HypothesisEngine()
        hyps = engine.generate(signals, max_hypotheses=5)
        assert len(hyps) <= 5

    def test_confidence_between_zero_and_one(self):
        engine = HypothesisEngine()
        hyps = engine.generate([SAMPLE_SIGNAL])
        assert 0.0 <= hyps[0].confidence <= 1.0


# ── EvaluationEngine ──────────────────────────────────────────────────────

class TestEvaluationEngine:
    def test_evaluate_no_matching_signals(self):
        engine = EvaluationEngine()
        hyp = {"id": "h1", "symbols": ["XYZ/USDC"], "venues": []}
        result = engine.evaluate(hyp, [SAMPLE_SIGNAL])
        assert result.observations == 0
        assert result.verdict == "insufficient_data"

    def test_evaluate_positive_edge(self):
        pos_signal = {**SAMPLE_SIGNAL, "edge_bps": 15.0}
        hyp = {"id": "h1", "symbols": ["WETH/USDC"], "venues": []}
        engine = EvaluationEngine()
        result = engine.evaluate(hyp, [pos_signal, pos_signal, pos_signal])
        assert result.hit_rate == 1.0
        assert result.verdict == "viable"

    def test_score_range(self):
        pos_signal = {**SAMPLE_SIGNAL, "edge_bps": 5.0}
        hyp = {"id": "h1", "symbols": ["WETH/USDC"], "venues": []}
        engine = EvaluationEngine()
        result = engine.evaluate(hyp, [pos_signal] * 10)
        assert 0.0 <= result.score <= 100.0

    def test_batch_evaluate_length(self):
        engine = EvaluationEngine()
        hyps = [{"id": f"h{i}", "symbols": ["WETH/USDC"], "venues": []} for i in range(3)]
        results = engine.batch_evaluate(hyps, [SAMPLE_SIGNAL])
        assert len(results) == 3


# ── FeatureEngine ─────────────────────────────────────────────────────────

class TestFeatureEngine:
    def test_extract_returns_dict(self):
        engine = FeatureEngine()
        feats = engine.extract(SAMPLE_SIGNAL)
        assert isinstance(feats, dict)

    def test_all_values_are_floats(self):
        engine = FeatureEngine()
        feats = engine.extract(SAMPLE_SIGNAL)
        for k, v in feats.items():
            assert isinstance(v, float), f"{k} is not float"

    def test_chain_evm_flag(self):
        engine = FeatureEngine()
        feats = engine.extract(SAMPLE_SIGNAL)
        assert feats["chain_evm"] == 1.0
        assert feats["chain_gate"] == 0.0

    def test_to_vector_length(self):
        engine = FeatureEngine()
        vec = engine.to_vector(SAMPLE_SIGNAL)
        assert len(vec) == len(engine.feature_names())

    def test_normalise_range(self):
        engine = FeatureEngine()
        signals = [SAMPLE_SIGNAL, {**SAMPLE_SIGNAL, "edge_bps": 50.0}]
        feats = engine.extract_batch(signals)
        normed = engine.normalise(feats)
        for row in normed:
            for v in row.values():
                assert 0.0 <= v <= 1.0 + 1e-9


# ── ApprovalGate ──────────────────────────────────────────────────────────

class TestApprovalGate:
    def test_request_and_approve(self):
        gate = ApprovalGate()
        gate.request("p1", "update_manifest", {"key": "val"})
        record = gate.approve("p1", reviewer="alice", reason="looks good")
        assert record.decision == GateDecision.APPROVED

    def test_reject(self):
        gate = ApprovalGate()
        gate.request("p2", "run_simulation", {})
        record = gate.reject("p2", reviewer="bob", reason="not ready")
        assert record.decision == GateDecision.REJECTED

    def test_execute_requires_approval(self):
        gate = ApprovalGate()
        gate.request("p3", "archive_signal", {})
        with pytest.raises(PermissionError):
            gate.execute("p3")

    def test_execute_after_approve_returns_payload(self):
        gate = ApprovalGate()
        payload = {"signal_id": "abc"}
        gate.request("p4", "archive_signal", payload)
        gate.approve("p4", reviewer="alice")
        result = gate.execute("p4")
        assert result == payload

    def test_duplicate_proposal_raises(self):
        gate = ApprovalGate()
        gate.request("p5", "run_simulation", {})
        with pytest.raises(ValueError):
            gate.request("p5", "run_simulation", {})

    def test_unknown_action_type_raises(self):
        gate = ApprovalGate()
        with pytest.raises(ValueError, match="Unknown action type"):
            gate.request("p6", "launch_rockets", {})

    def test_pending_list(self):
        gate = ApprovalGate()
        gate.request("p7", "promote_hypothesis", {})
        gate.request("p8", "run_simulation", {})
        gate.approve("p7", reviewer="alice")
        pending = gate.pending()
        assert len(pending) == 1
        assert pending[0]["proposal_id"] == "p8"

    def test_summary(self):
        gate = ApprovalGate()
        gate.request("s1", "run_simulation", {})
        gate.approve("s1", reviewer="alice")
        gate.request("s2", "archive_signal", {})
        summary = gate.summary()
        assert summary["total"] == 2
        assert summary["approved"] == 1
        assert summary["pending"] == 1
