"""Tests for proof_of_avoided_work/.

Everything runs offline: re-execution is a stub function under the test's
control, which is exactly the seam the protocol is designed around — an
auditor is anything that can recompute a committed unit.

The tests that matter most are the adversarial ones. Each of the four
attacks the design claims to close gets a test that carries it out and
asserts the attacker ends up no better off, and in three cases worse.
"""
import hashlib

import pytest
from solders.keypair import Keypair

from proof_of_avoided_work.audit import (
    FraudKind,
    ReexecutionResult,
    SeedCommitment,
    audit_claim,
    baseline_inflation_proof,
    is_selected,
    select_claims,
    selection_value,
)
from proof_of_avoided_work.commitments import (
    ReuseClaim,
    WorkCommitment,
    digest_bytes,
    sign_claim,
)
from proof_of_avoided_work.economics import (
    AuditBudget,
    DeterrenceParams,
    InfeasibleDeterrenceError,
    detection_probability,
    expected_value_of_fraud,
    minimum_audit_rate,
    plan_audit,
    required_bond,
)
from proof_of_avoided_work.oracle import (
    BaselineOracle,
    BaselineSample,
    NoAdmissibleBaselineError,
)
from proof_of_avoided_work.settlement import (
    ClaimRejected,
    ClaimState,
    SettlementEngine,
    to_compute_reuse_event,
)

WORK_CLASS = "test.transform:v1"
CODE_VERSION = "test-1.0.0"
COLD_SECONDS = 10.0


def keypair(tag: str) -> Keypair:
    return Keypair.from_seed(hashlib.sha256(tag.encode()).digest())


def commitment(unit: str = "unit-1") -> WorkCommitment:
    return WorkCommitment.over(WORK_CLASS, unit.encode(), CODE_VERSION, {"rt": "test"})


def true_output(c: WorkCommitment) -> str:
    return digest_bytes(("out:" + c.input_digest).encode())


def honest_reexecutor(c: WorkCommitment) -> ReexecutionResult:
    return ReexecutionResult(true_output(c), COLD_SECONDS)


def seeded_oracle(min_measurers: int = 3) -> BaselineOracle:
    oracle = BaselineOracle(min_samples=5, min_measurers=min_measurers)
    for i, tag in enumerate(("m-a", "m-b", "m-c")):
        pub = str(keypair(tag).pubkey())
        for j in range(2):
            oracle.observe(WORK_CLASS, COLD_SECONDS + 0.1 * (i + j), pub)
    return oracle


# ── commitments ─────────────────────────────────────────────────────────────

class TestWorkCommitment:
    def test_same_inputs_give_same_digest(self):
        assert commitment().digest() == commitment().digest()

    def test_different_input_gives_different_digest(self):
        assert commitment("a").digest() != commitment("b").digest()

    def test_code_version_is_part_of_identity(self):
        a = WorkCommitment.over(WORK_CLASS, b"x", "v1")
        b = WorkCommitment.over(WORK_CLASS, b"x", "v2")
        assert a.digest() != b.digest()

    def test_env_is_part_of_identity(self):
        a = WorkCommitment.over(WORK_CLASS, b"x", "v1", {"gpu": "a"})
        b = WorkCommitment.over(WORK_CLASS, b"x", "v1", {"gpu": "b"})
        assert a.digest() != b.digest()

    def test_env_key_order_does_not_matter(self):
        a = WorkCommitment.over(WORK_CLASS, b"x", "v1", {"a": 1, "b": 2})
        b = WorkCommitment.over(WORK_CLASS, b"x", "v1", {"b": 2, "a": 1})
        assert a.digest() == b.digest()

    def test_empty_field_rejected(self):
        with pytest.raises(ValueError):
            WorkCommitment("", "d", "v", "e")


class TestReuseClaim:
    def test_signed_claim_verifies(self):
        c = commitment()
        claim = sign_claim(c, true_output(c), 0.5, 1, keypair("alice"))
        assert claim.verify()

    def test_unsigned_claim_does_not_verify(self):
        c = commitment()
        claim = ReuseClaim(c, true_output(c), 0.5, 1, str(keypair("alice").pubkey()))
        assert not claim.verify()

    def test_tampering_with_cost_breaks_signature(self):
        c = commitment()
        claim = sign_claim(c, true_output(c), 0.5, 1, keypair("alice"))
        claim.actual_cost_seconds = 0.01
        assert not claim.verify()

    def test_tampering_with_output_breaks_signature(self):
        c = commitment()
        claim = sign_claim(c, true_output(c), 0.5, 1, keypair("alice"))
        claim.output_digest = digest_bytes(b"other")
        assert not claim.verify()

    def test_claim_signed_by_one_key_does_not_verify_as_another(self):
        c = commitment()
        claim = sign_claim(c, true_output(c), 0.5, 1, keypair("alice"))
        claim.claimant_pubkey = str(keypair("mallory").pubkey())
        assert not claim.verify()

    def test_roundtrip_through_dict(self):
        c = commitment()
        claim = sign_claim(c, true_output(c), 0.5, 1, keypair("alice"), 9.0)
        restored = ReuseClaim.from_dict(claim.to_dict())
        assert restored.verify()
        assert restored.record_hash == claim.record_hash

    def test_dedup_key_matches_for_same_unit_epoch_claimant(self):
        c = commitment()
        a = sign_claim(c, true_output(c), 0.5, 1, keypair("alice"))
        b = sign_claim(c, true_output(c), 0.4, 1, keypair("alice"))
        assert a.dedup_key == b.dedup_key

    def test_dedup_key_differs_across_epochs(self):
        c = commitment()
        a = sign_claim(c, true_output(c), 0.5, 1, keypair("alice"))
        b = sign_claim(c, true_output(c), 0.5, 2, keypair("alice"))
        assert a.dedup_key != b.dedup_key

    def test_negative_cost_rejected(self):
        with pytest.raises(ValueError):
            ReuseClaim(commitment(), "d", -1.0, 1, "pk")


# ── oracle ──────────────────────────────────────────────────────────────────

class TestBaselineOracle:
    def test_no_distribution_below_sample_quorum(self):
        oracle = BaselineOracle(min_samples=5, min_measurers=1)
        pub = str(keypair("m").pubkey())
        for _ in range(4):
            oracle.observe(WORK_CLASS, COLD_SECONDS, pub)
        assert oracle.distribution(WORK_CLASS) is None

    def test_no_distribution_below_measurer_quorum(self):
        oracle = BaselineOracle(min_samples=3, min_measurers=3)
        pub = str(keypair("m").pubkey())
        for _ in range(10):
            oracle.observe(WORK_CLASS, COLD_SECONDS, pub)
        assert oracle.distribution(WORK_CLASS) is None, (
            "one measurer must not be able to stand up a work class alone"
        )

    def test_unknown_work_class_fails_closed(self):
        with pytest.raises(NoAdmissibleBaselineError):
            BaselineOracle().admissible_baseline("never.seen")

    def test_reference_is_the_median_not_the_tail(self):
        oracle = seeded_oracle()
        dist = oracle.distribution(WORK_CLASS)
        assert dist.reference_seconds == dist.median_seconds
        assert dist.admissible_bound_seconds >= dist.reference_seconds

    def test_inflated_hint_is_priced_at_the_reference(self):
        oracle = seeded_oracle()
        baseline = oracle.admissible_baseline(WORK_CLASS, claimed_seconds=10_000.0)
        assert baseline.seconds == baseline.reference_seconds
        assert baseline.hint_ignored

    def test_inflating_earns_no_more_than_not_hinting(self):
        oracle = seeded_oracle()
        inflated = oracle.admissible_baseline(WORK_CLASS, claimed_seconds=10_000.0)
        silent = oracle.admissible_baseline(WORK_CLASS)
        assert inflated.seconds == silent.seconds, (
            "overstating a baseline must be worth exactly nothing"
        )

    def test_claimant_may_talk_their_own_baseline_down(self):
        oracle = seeded_oracle()
        modest = oracle.admissible_baseline(WORK_CLASS, claimed_seconds=1.0)
        assert modest.seconds == 1.0
        assert not modest.hint_ignored

    def test_minority_of_poisoned_samples_barely_moves_the_reference(self):
        oracle = seeded_oracle()
        clean = oracle.distribution(WORK_CLASS).reference_seconds
        attacker = str(keypair("attacker").pubkey())
        for _ in range(4):
            oracle.observe(WORK_CLASS, 100_000.0, attacker)
        poisoned = oracle.distribution(WORK_CLASS).reference_seconds
        assert poisoned < clean * 1.1

    def test_majority_poisoning_does_move_it(self):
        # Stated as a limit, not a defence: the measurer quorum, not the
        # statistics, is what stops a Sybil majority.
        oracle = seeded_oracle()
        for tag in ("p-a", "p-b", "p-c"):
            pub = str(keypair(tag).pubkey())
            for _ in range(10):
                oracle.observe(WORK_CLASS, 100_000.0, pub)
        assert oracle.distribution(WORK_CLASS).reference_seconds > COLD_SECONDS * 10

    def test_snapshot_is_signed_and_verifies(self):
        oracle = seeded_oracle()
        snap = oracle.snapshot(keypair("oracle-signer"))
        assert snap.verify()
        assert WORK_CLASS in snap.distributions

    def test_tampered_snapshot_does_not_verify(self):
        oracle = seeded_oracle()
        snap = oracle.snapshot(keypair("oracle-signer"))
        tampered = type(snap)(
            distributions=snap.distributions,
            created_at=snap.created_at + 1,
            signer_pubkey=snap.signer_pubkey,
            signature=snap.signature,
        )
        assert not tampered.verify()

    def test_zero_cold_cost_sample_rejected(self):
        with pytest.raises(ValueError):
            BaselineSample(WORK_CLASS, 0.0, "pk")


# ── audit sampling ──────────────────────────────────────────────────────────

class TestSelection:
    def test_selection_is_deterministic(self):
        seed = b"\x01" * 32
        c = commitment()
        claim = sign_claim(c, true_output(c), 0.5, 1, keypair("alice"))
        first = selection_value(seed, claim.record_hash)
        assert first == selection_value(seed, claim.record_hash)

    def test_selection_changes_with_seed(self):
        c = commitment()
        claim = sign_claim(c, true_output(c), 0.5, 1, keypair("alice"))
        assert selection_value(b"\x01" * 32, claim.record_hash) != selection_value(
            b"\x02" * 32, claim.record_hash
        )

    def test_rate_zero_selects_nothing_and_one_selects_all(self):
        seed = b"\x03" * 32
        claims = [
            sign_claim(commitment(f"u{i}"), "d" * 64, 0.1, 1, keypair("alice"))
            for i in range(50)
        ]
        assert select_claims(seed, claims, 0.0) == []
        assert len(select_claims(seed, claims, 1.0)) == 50

    def test_selection_rate_is_approximately_honoured(self):
        seed = b"\x04" * 32
        claims = [
            sign_claim(commitment(f"u{i}"), "d" * 64, 0.1, 1, keypair("alice"))
            for i in range(2000)
        ]
        share = len(select_claims(seed, claims, 0.25)) / len(claims)
        assert 0.21 < share < 0.29

    def test_invalid_rate_rejected(self):
        with pytest.raises(ValueError):
            is_selected(b"\x00" * 32, "abc", 1.5)


class TestSeedCommitment:
    def test_reveal_matches_commitment(self):
        sc = SeedCommitment()
        seed = sc.reveal()
        assert SeedCommitment.check_reveal(sc.commitment, seed)

    def test_wrong_seed_is_rejected(self):
        sc = SeedCommitment()
        assert not SeedCommitment.check_reveal(sc.commitment, b"\x09" * 32)

    def test_commitment_hides_the_seed_until_reveal(self):
        seed = b"\x05" * 32
        sc = SeedCommitment(seed=seed)
        assert seed.hex() not in sc.commitment
        assert not sc.revealed
        sc.reveal()
        assert sc.revealed


# ── auditing a single claim ─────────────────────────────────────────────────

class TestAuditClaim:
    def test_honest_claim_passes(self):
        c = commitment()
        claim = sign_claim(c, true_output(c), 0.5, 1, keypair("alice"))
        verdict = audit_claim(claim, honest_reexecutor)
        assert verdict.passed
        assert verdict.observed_cold_cost_seconds == COLD_SECONDS

    def test_phantom_reuse_is_caught(self):
        c = commitment()
        claim = sign_claim(c, digest_bytes(b"fabricated"), 0.5, 1, keypair("mallory"))
        verdict = audit_claim(claim, honest_reexecutor)
        assert not verdict.passed
        assert verdict.fraud_proof.kind is FraudKind.OUTPUT_MISMATCH

    def test_cost_not_below_cold_cost_is_caught(self):
        c = commitment()
        claim = sign_claim(c, true_output(c), COLD_SECONDS + 1, 1, keypair("mallory"))
        verdict = audit_claim(claim, honest_reexecutor)
        assert not verdict.passed
        assert verdict.fraud_proof.kind is FraudKind.IMPOSSIBLE_COST

    def test_bad_signature_is_caught_without_reexecuting(self):
        c = commitment()
        claim = sign_claim(c, true_output(c), 0.5, 1, keypair("alice"))
        claim.actual_cost_seconds = 0.001

        def exploding(_):
            raise AssertionError("must not re-execute an unverifiable claim")

        verdict = audit_claim(claim, exploding)
        assert not verdict.passed
        assert verdict.fraud_proof.kind is FraudKind.BAD_SIGNATURE

    def test_fraud_proof_carries_recheckable_evidence(self):
        c = commitment()
        claim = sign_claim(c, digest_bytes(b"fabricated"), 0.5, 1, keypair("mallory"))
        proof = audit_claim(claim, honest_reexecutor).fraud_proof
        assert proof.evidence["claimed_output_digest"] == claim.output_digest
        assert proof.evidence["commitment_digest"] == c.digest()
        assert proof.digest() == proof.digest()

    def test_verdict_serialises_for_the_audit_record(self):
        import json

        c = commitment()
        claim = sign_claim(c, digest_bytes(b"fabricated"), 0.5, 1, keypair("mallory"))
        payload = json.dumps(audit_claim(claim, honest_reexecutor).to_dict())
        assert FraudKind.OUTPUT_MISMATCH.value in payload

    def test_baseline_inflation_proof_only_above_the_bound(self):
        c = commitment()
        modest = sign_claim(c, true_output(c), 0.5, 1, keypair("alice"), 9.0)
        greedy = sign_claim(c, true_output(c), 0.5, 1, keypair("mallory"), 900.0)
        assert baseline_inflation_proof(modest, 12.0) is None
        assert baseline_inflation_proof(greedy, 12.0).kind is FraudKind.BASELINE_INFLATION


# ── economics ───────────────────────────────────────────────────────────────

class TestEconomics:
    def test_break_even_rate_matches_closed_form(self):
        params = DeterrenceParams(bond_credits=99.0, max_gain_per_fraudulent_claim=1.0)
        assert minimum_audit_rate(params) == pytest.approx(0.01)

    def test_at_the_floor_fraud_is_not_profitable(self):
        params = DeterrenceParams(bond_credits=500.0, max_gain_per_fraudulent_claim=5.0)
        rate = minimum_audit_rate(params)
        assert expected_value_of_fraud(rate, params) == pytest.approx(0.0, abs=1e-9)

    def test_above_the_floor_fraud_loses_money(self):
        params = DeterrenceParams(bond_credits=500.0, max_gain_per_fraudulent_claim=5.0)
        rate = minimum_audit_rate(params) * 1.5
        assert expected_value_of_fraud(rate, params) < 0

    def test_bigger_bond_lowers_the_required_audit_rate(self):
        small = DeterrenceParams(bond_credits=10.0, max_gain_per_fraudulent_claim=1.0)
        large = DeterrenceParams(bond_credits=1000.0, max_gain_per_fraudulent_claim=1.0)
        assert minimum_audit_rate(large) < minimum_audit_rate(small)

    def test_no_bond_means_no_deterrence_at_any_rate(self):
        params = DeterrenceParams(bond_credits=0.0, max_gain_per_fraudulent_claim=1.0)
        assert minimum_audit_rate(params) == pytest.approx(1.0)
        with pytest.raises(InfeasibleDeterrenceError):
            minimum_audit_rate(
                DeterrenceParams(
                    bond_credits=0.0,
                    max_gain_per_fraudulent_claim=1.0,
                    safety_margin=0.1,
                )
            )

    def test_required_bond_inverts_the_floor(self):
        bond = required_bond(0.02, max_gain_per_fraudulent_claim=3.0)
        params = DeterrenceParams(bond_credits=bond, max_gain_per_fraudulent_claim=3.0)
        assert minimum_audit_rate(params) == pytest.approx(0.02)

    def test_repeated_fraud_converges_on_certain_detection(self):
        assert detection_probability(0.05, 1) == pytest.approx(0.05)
        assert detection_probability(0.05, 100) > 0.99
        assert detection_probability(0.05, 0) == 0.0

    def test_feasible_plan_runs_at_the_deterrence_floor(self):
        params = DeterrenceParams(bond_credits=1000.0, max_gain_per_fraudulent_claim=10.0)
        budget = AuditBudget(10_000, 8.0, 75_000.0, 0.05)
        plan = plan_audit(params, budget)
        assert plan.feasible
        assert plan.audit_rate == pytest.approx(plan.deterrence_floor)
        assert plan.cost_fraction_of_credited_value < 0.05 * 1.5

    def test_thin_bond_makes_the_plan_infeasible(self):
        params = DeterrenceParams(bond_credits=1.0, max_gain_per_fraudulent_claim=10.0)
        budget = AuditBudget(10_000, 8.0, 75_000.0, 0.01)
        plan = plan_audit(params, budget)
        assert not plan.feasible
        assert "budget affords only" in plan.reason

    def test_raising_the_bond_rescues_an_infeasible_plan(self):
        budget = AuditBudget(10_000, 8.0, 75_000.0, 0.01)
        thin = plan_audit(
            DeterrenceParams(bond_credits=1.0, max_gain_per_fraudulent_claim=10.0),
            budget,
        )
        thick = plan_audit(
            DeterrenceParams(bond_credits=100_000.0, max_gain_per_fraudulent_claim=10.0),
            budget,
        )
        assert not thin.feasible and thick.feasible

    def test_invalid_params_rejected(self):
        with pytest.raises(ValueError):
            DeterrenceParams(bond_credits=-1.0, max_gain_per_fraudulent_claim=1.0)
        with pytest.raises(ValueError):
            AuditBudget(0, 1.0, 1.0)


# ── settlement, end to end ──────────────────────────────────────────────────

def engine_with_oracle(**kwargs) -> SettlementEngine:
    return SettlementEngine(
        oracle=seeded_oracle(),
        auditor_pubkey=str(keypair("auditor").pubkey()),
        **kwargs,
    )


class TestSettlement:
    def test_claim_is_not_credited_before_its_epoch_is_audited(self):
        engine = engine_with_oracle()
        c = commitment()
        claim = sign_claim(c, true_output(c), 0.5, 1, keypair("alice"))
        entry = engine.submit(claim)
        assert entry.state is ClaimState.ESCROWED
        assert engine.settled_credits() == 0.0

    def test_honest_claim_settles_after_audit(self):
        engine = engine_with_oracle()
        alice = keypair("alice")
        engine.post_bond(str(alice.pubkey()), 100.0)
        c = commitment()
        engine.submit(sign_claim(c, true_output(c), 0.5, 1, alice))
        report = engine.run_epoch(1, b"\x07" * 32, 1.0, honest_reexecutor)
        assert report.settled_claims == 1
        assert engine.settled_credits(str(alice.pubkey())) == pytest.approx(
            COLD_SECONDS + 0.1 - 0.5, abs=0.3
        )

    def test_unknown_work_class_is_rejected_not_credited(self):
        engine = engine_with_oracle()
        c = WorkCommitment.over("unknown.class", b"x", CODE_VERSION)
        claim = sign_claim(c, true_output(c), 0.5, 1, keypair("alice"))
        with pytest.raises(ClaimRejected):
            engine.submit(claim)

    def test_unsigned_claim_is_rejected_at_intake(self):
        engine = engine_with_oracle()
        c = commitment()
        claim = ReuseClaim(c, true_output(c), 0.5, 1, str(keypair("alice").pubkey()))
        with pytest.raises(ClaimRejected) as exc:
            engine.submit(claim)
        assert exc.value.fraud_proof.kind is FraudKind.BAD_SIGNATURE

    def test_double_claim_is_rejected_and_slashed_without_reexecution(self):
        engine = engine_with_oracle()
        mallory = keypair("mallory")
        engine.post_bond(str(mallory.pubkey()), 500.0)
        c = commitment()
        engine.submit(sign_claim(c, true_output(c), 0.5, 1, mallory))
        with pytest.raises(ClaimRejected) as exc:
            engine.submit(sign_claim(c, true_output(c), 0.4, 1, mallory))
        assert exc.value.fraud_proof.kind is FraudKind.DOUBLE_CLAIM
        assert engine.bond(str(mallory.pubkey())) == 0.0

    def test_same_unit_in_a_later_epoch_is_allowed(self):
        engine = engine_with_oracle()
        alice = keypair("alice")
        c = commitment()
        engine.submit(sign_claim(c, true_output(c), 0.5, 1, alice))
        engine.submit(sign_claim(c, true_output(c), 0.5, 2, alice))
        assert len(engine.entries(str(alice.pubkey()))) == 2

    def test_caught_cheater_is_slashed_and_all_their_claims_void(self):
        engine = engine_with_oracle()
        mallory = keypair("mallory")
        engine.post_bond(str(mallory.pubkey()), 500.0)
        for i in range(20):
            c = commitment(f"unit-{i}")
            engine.submit(sign_claim(c, digest_bytes(f"fake-{i}".encode()), 0.5, 1, mallory))
        report = engine.run_epoch(1, b"\x08" * 32, 0.5, honest_reexecutor)
        assert report.fraud_proofs
        assert report.settled_credits == 0.0
        assert report.voided_claims == 20, "forfeiture must cover unaudited claims too"
        assert engine.settled_credits(str(mallory.pubkey())) == 0.0
        assert engine.slashed(str(mallory.pubkey())) == 500.0

    def test_one_cheater_does_not_void_an_honest_claimant(self):
        engine = engine_with_oracle()
        alice, mallory = keypair("alice"), keypair("mallory")
        engine.post_bond(str(alice.pubkey()), 500.0)
        engine.post_bond(str(mallory.pubkey()), 500.0)
        for i in range(10):
            ca = commitment(f"a-{i}")
            engine.submit(sign_claim(ca, true_output(ca), 0.5, 1, alice))
            cm = commitment(f"m-{i}")
            engine.submit(sign_claim(cm, digest_bytes(f"fake-{i}".encode()), 0.5, 1, mallory))
        engine.run_epoch(1, b"\x0a" * 32, 1.0, honest_reexecutor)
        assert engine.settled_credits(str(alice.pubkey())) > 0
        assert engine.settled_credits(str(mallory.pubkey())) == 0.0
        assert engine.bond(str(alice.pubkey())) == 500.0

    def test_inflating_the_baseline_earns_nothing_extra(self):
        engine = engine_with_oracle()
        alice, greedy = keypair("alice"), keypair("greedy")
        ca, cg = commitment("a"), commitment("g")
        engine.submit(sign_claim(ca, true_output(ca), 0.5, 1, alice))
        engine.submit(sign_claim(cg, true_output(cg), 0.5, 1, greedy, 10_000.0))
        engine.run_epoch(1, b"\x0b" * 32, 1.0, honest_reexecutor)
        assert engine.settled_credits(str(greedy.pubkey())) == pytest.approx(
            engine.settled_credits(str(alice.pubkey()))
        )

    def test_inflation_is_recorded_as_attributable(self):
        engine = engine_with_oracle()
        greedy = keypair("greedy")
        c = commitment("g")
        engine.submit(sign_claim(c, true_output(c), 0.5, 1, greedy, 10_000.0))
        kinds = {p.kind for p in engine.fraud_proofs()}
        assert FraudKind.BASELINE_INFLATION in kinds

    def test_reuse_slower_than_cold_earns_no_credit(self):
        engine = engine_with_oracle()
        alice = keypair("alice")
        c = commitment()
        entry = engine.submit(sign_claim(c, true_output(c), 500.0, 1, alice))
        assert entry.provisional_credits == 0.0

    def test_audits_feed_the_baseline_oracle(self):
        engine = engine_with_oracle()
        before = len(engine.oracle.samples(WORK_CLASS))
        alice = keypair("alice")
        for i in range(6):
            c = commitment(f"unit-{i}")
            engine.submit(sign_claim(c, true_output(c), 0.5, 1, alice))
        report = engine.run_epoch(1, b"\x0c" * 32, 1.0, honest_reexecutor)
        assert report.baseline_samples_added == 6
        assert len(engine.oracle.samples(WORK_CLASS)) == before + 6

    def test_audit_selection_is_reproducible_by_a_third_party(self):
        engine = engine_with_oracle()
        alice = keypair("alice")
        claims = []
        for i in range(60):
            c = commitment(f"unit-{i}")
            claim = sign_claim(c, true_output(c), 0.5, 1, alice)
            engine.submit(claim)
            claims.append(claim)
        seed = b"\x0d" * 32
        report = engine.run_epoch(1, seed, 0.3, honest_reexecutor)
        recomputed = select_claims(seed, claims, 0.3)
        assert len(recomputed) == report.claims_selected

    def test_only_settled_entries_reach_the_credit_ledger(self):
        engine = engine_with_oracle()
        mallory = keypair("mallory")
        engine.post_bond(str(mallory.pubkey()), 10.0)
        c = commitment()
        entry = engine.submit(sign_claim(c, digest_bytes(b"fake"), 0.5, 1, mallory))
        with pytest.raises(ValueError):
            to_compute_reuse_event(entry)
        engine.run_epoch(1, b"\x0e" * 32, 1.0, honest_reexecutor)
        assert entry.state is ClaimState.VOID_FRAUD
        with pytest.raises(ValueError):
            to_compute_reuse_event(entry)

    def test_settled_entry_converts_with_the_oracle_baseline(self):
        engine = engine_with_oracle()
        alice = keypair("alice")
        c = commitment()
        entry = engine.submit(sign_claim(c, true_output(c), 0.5, 1, alice, 10_000.0))
        engine.run_epoch(1, b"\x0f" * 32, 1.0, honest_reexecutor)
        event = to_compute_reuse_event(entry)
        assert event.baseline_cost_seconds == entry.baseline.seconds
        assert event.baseline_cost_seconds < 20.0, (
            "the ledger must never see the claimant's 10,000s hint"
        )
        assert event.actual_cost_seconds == 0.5


class TestEndToEndDeterrence:
    def test_cheating_at_the_planned_rate_is_negative_ev(self):
        """The whole protocol in one test: plan a rate, then verify a
        cheater running at that rate loses more than they could gain."""
        gain_per_claim = COLD_SECONDS
        params = DeterrenceParams(
            bond_credits=500.0, max_gain_per_fraudulent_claim=gain_per_claim
        )
        budget = AuditBudget(
            claims_per_epoch=100,
            reexecution_cost_credits=COLD_SECONDS,
            credited_value_per_epoch=100 * gain_per_claim,
            budget_fraction=0.10,
        )
        plan = plan_audit(params, budget)
        assert plan.feasible
        assert expected_value_of_fraud(plan.audit_rate, params) <= 0

        engine = engine_with_oracle()
        mallory = keypair("mallory")
        engine.post_bond(str(mallory.pubkey()), params.bond_credits)
        for i in range(100):
            c = commitment(f"unit-{i}")
            engine.submit(sign_claim(c, digest_bytes(f"fake-{i}".encode()), 0.5, 1, mallory))

        caught_at_least_once = False
        for seed_byte in range(1, 21):
            probe = SettlementEngine(
                oracle=seeded_oracle(),
                auditor_pubkey=str(keypair("auditor").pubkey()),
            )
            probe.post_bond(str(mallory.pubkey()), params.bond_credits)
            for i in range(100):
                c = commitment(f"unit-{i}")
                probe.submit(
                    sign_claim(c, digest_bytes(f"fake-{i}".encode()), 0.5, 1, mallory)
                )
            report = probe.run_epoch(
                1, bytes([seed_byte]) * 32, plan.audit_rate, honest_reexecutor
            )
            if report.fraud_proofs:
                caught_at_least_once = True
                assert report.settled_credits == 0.0
                assert report.slashed_credits == params.bond_credits

        assert caught_at_least_once, (
            "100 fakes at the planned rate should be caught in most epochs; "
            f"detection probability is "
            f"{detection_probability(plan.audit_rate, 100):.2%}"
        )
