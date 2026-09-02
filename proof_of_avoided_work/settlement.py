"""Escrow, audit, settle — and the bridge back to the credit ledger.

Nothing is credited on arrival. A claim lands in escrow priced against the
oracle, sits through its epoch, and becomes spendable only once the epoch's
audit has run and it has not been disproved. That ordering is the point:
under the old design a claim was worth credits the instant it was signed,
so fraud paid immediately and detection, if it ever came, came too late.

A caught claimant loses more than the one claim. The bond is slashed and
every other claim they had escrowed in that epoch is voided, so the
expected cost of being caught scales with how much they were trying to
extract. The deterrence model in `economics.py` deliberately ignores that
forfeiture and prices only the bond, which makes its audit rate a
conservative one — real deterrence is at least what the model says, not at
most.

`to_compute_reuse_event` is the join back to `memory_credit_daemon`: a
settled entry converts into the daemon's existing `ComputeReuseEvent`
carrying the *oracle's* baseline rather than the claimant's, so the
downstream ledger accrues numbers that survived an audit instead of
numbers somebody typed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .audit import (
    DoubleClaimIndex,
    FraudKind,
    FraudProof,
    Reexecutor,
    audit_claim,
    baseline_inflation_proof,
    is_selected,
)
from .commitments import ReuseClaim
from .oracle import AdmissibleBaseline, BaselineOracle, NoAdmissibleBaselineError


class ClaimState(str, Enum):
    ESCROWED = "escrowed"
    SETTLED = "settled"
    VOID_FRAUD = "void_fraud"


class ClaimRejected(Exception):
    """Raised when a claim cannot enter escrow at all.

    Carries the fraud proof when the rejection is attributable (a double
    claim or a bad signature) rather than merely unpriceable.
    """

    def __init__(self, reason: str, fraud_proof: FraudProof | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.fraud_proof = fraud_proof


@dataclass
class EscrowEntry:
    claim: ReuseClaim
    baseline: AdmissibleBaseline
    provisional_credits: float
    state: ClaimState = ClaimState.ESCROWED
    audited: bool = False
    note: str = ""

    @property
    def credited(self) -> float:
        return self.provisional_credits if self.state is ClaimState.SETTLED else 0.0


@dataclass
class EpochReport:
    epoch: int
    audit_rate: float
    seed_hex: str
    claims_total: int
    claims_selected: int
    settled_claims: int
    voided_claims: int
    settled_credits: float
    voided_credits: float
    slashed_credits: float
    fraud_proofs: list[FraudProof] = field(default_factory=list)
    baseline_samples_added: int = 0

    def summary(self) -> str:
        return (
            f"epoch {self.epoch}: {self.claims_total} claims, "
            f"{self.claims_selected} audited ({self.audit_rate:.1%}), "
            f"{self.settled_claims} settled for {self.settled_credits:g} credits, "
            f"{self.voided_claims} voided, {self.slashed_credits:g} slashed"
        )


class SettlementEngine:
    def __init__(
        self,
        oracle: BaselineOracle,
        auditor_pubkey: str,
        credits_per_second_saved: float = 1.0,
        penalty_multiplier: float = 1.0,
    ) -> None:
        if credits_per_second_saved <= 0:
            raise ValueError("credits_per_second_saved must be positive")
        if not 0.0 <= penalty_multiplier <= 1.0:
            raise ValueError("penalty_multiplier must be in [0, 1]")
        self.oracle = oracle
        self.auditor_pubkey = auditor_pubkey
        self.credits_per_second_saved = credits_per_second_saved
        self.penalty_multiplier = penalty_multiplier
        self._entries: dict[str, EscrowEntry] = {}
        self._dedup = DoubleClaimIndex()
        self._bonds: dict[str, float] = {}
        self._slashed: dict[str, float] = {}
        self._fraud_proofs: list[FraudProof] = []

    # ── bonds ──────────────────────────────────────────────────────────

    def post_bond(self, claimant_pubkey: str, credits: float) -> float:
        if credits < 0:
            raise ValueError("bond must be non-negative")
        self._bonds[claimant_pubkey] = self._bonds.get(claimant_pubkey, 0.0) + credits
        return self._bonds[claimant_pubkey]

    def bond(self, claimant_pubkey: str) -> float:
        return self._bonds.get(claimant_pubkey, 0.0)

    def slashed(self, claimant_pubkey: str) -> float:
        return self._slashed.get(claimant_pubkey, 0.0)

    # ── intake ─────────────────────────────────────────────────────────

    def submit(self, claim: ReuseClaim) -> EscrowEntry:
        """Price a claim against the oracle and hold it in escrow.

        Rejects, rather than discounts, the three cases where crediting
        anything would be guesswork: an unverifiable signature, a repeat of
        a unit already billed this epoch, and a work class with no
        quorum-backed baseline to price against.
        """
        if not claim.verify():
            proof = FraudProof(
                kind=FraudKind.BAD_SIGNATURE,
                claim_id=claim.claim_id,
                claimant_pubkey=claim.claimant_pubkey,
                detail="claim signature does not verify against its stated key",
            )
            self._fraud_proofs.append(proof)
            raise ClaimRejected("signature does not verify", proof)

        duplicate = self._dedup.register(claim)
        if duplicate is not None:
            self._fraud_proofs.append(duplicate)
            self._slash(claim.claimant_pubkey)
            raise ClaimRejected("work unit already claimed this epoch", duplicate)

        try:
            baseline = self.oracle.admissible_baseline(
                claim.commitment.work_class, claim.claimed_baseline_seconds
            )
        except NoAdmissibleBaselineError as exc:
            raise ClaimRejected(str(exc)) from exc

        inflation = baseline_inflation_proof(claim, baseline.bound_seconds)
        if inflation is not None:
            self._fraud_proofs.append(inflation)

        seconds_saved = max(0.0, baseline.seconds - claim.actual_cost_seconds)
        entry = EscrowEntry(
            claim=claim,
            baseline=baseline,
            provisional_credits=seconds_saved * self.credits_per_second_saved,
            note=(
                "hint exceeded the oracle reference; priced at the reference"
                if baseline.hint_ignored
                else ""
            ),
        )
        self._entries[claim.claim_id] = entry
        return entry

    # ── epoch audit ────────────────────────────────────────────────────

    def run_epoch(
        self,
        epoch: int,
        seed: bytes,
        audit_rate: float,
        reexecutor: Reexecutor,
    ) -> EpochReport:
        """Sample, re-execute, slash, and release the survivors."""
        if not 0.0 <= audit_rate <= 1.0:
            raise ValueError("audit_rate must be in [0, 1]")

        entries = [
            e
            for e in self._entries.values()
            if e.claim.epoch == epoch and e.state is ClaimState.ESCROWED
        ]
        selected = [
            e for e in entries if is_selected(seed, e.claim.record_hash, audit_rate)
        ]

        proofs: list[FraudProof] = []
        guilty: set[str] = set()
        samples_added = 0

        for entry in selected:
            verdict = audit_claim(entry.claim, reexecutor)
            entry.audited = True
            if verdict.observed_cold_cost_seconds is not None:
                self.oracle.observe(
                    entry.claim.commitment.work_class,
                    verdict.observed_cold_cost_seconds,
                    self.auditor_pubkey,
                )
                samples_added += 1
            if not verdict.passed and verdict.fraud_proof is not None:
                proofs.append(verdict.fraud_proof)
                guilty.add(entry.claim.claimant_pubkey)

        slashed_total = 0.0
        for pubkey in guilty:
            slashed_total += self._slash(pubkey)

        settled = voided = 0
        settled_credits = voided_credits = 0.0
        for entry in entries:
            if entry.claim.claimant_pubkey in guilty:
                entry.state = ClaimState.VOID_FRAUD
                entry.note = "voided: claimant produced a fraudulent claim this epoch"
                voided += 1
                voided_credits += entry.provisional_credits
            else:
                entry.state = ClaimState.SETTLED
                settled += 1
                settled_credits += entry.provisional_credits

        self._fraud_proofs.extend(proofs)
        return EpochReport(
            epoch=epoch,
            audit_rate=audit_rate,
            seed_hex=seed.hex(),
            claims_total=len(entries),
            claims_selected=len(selected),
            settled_claims=settled,
            voided_claims=voided,
            settled_credits=settled_credits,
            voided_credits=voided_credits,
            slashed_credits=slashed_total,
            fraud_proofs=proofs,
            baseline_samples_added=samples_added,
        )

    # ── views ──────────────────────────────────────────────────────────

    def entries(self, claimant_pubkey: str | None = None) -> list[EscrowEntry]:
        return [
            e
            for e in self._entries.values()
            if claimant_pubkey is None or e.claim.claimant_pubkey == claimant_pubkey
        ]

    def settled_credits(self, claimant_pubkey: str | None = None) -> float:
        return sum(e.credited for e in self.entries(claimant_pubkey))

    def fraud_proofs(self) -> list[FraudProof]:
        return list(self._fraud_proofs)

    def _slash(self, claimant_pubkey: str) -> float:
        bond = self._bonds.get(claimant_pubkey, 0.0)
        amount = bond * self.penalty_multiplier
        self._bonds[claimant_pubkey] = bond - amount
        self._slashed[claimant_pubkey] = self._slashed.get(claimant_pubkey, 0.0) + amount
        return amount


def to_compute_reuse_event(entry: EscrowEntry):
    """Convert a settled entry into the credit daemon's event type.

    Refuses anything not settled, so an unaudited or voided claim cannot
    reach the ledger by this route.
    """
    from memory_credit_daemon.receipts import ComputeReuseEvent

    if entry.state is not ClaimState.SETTLED:
        raise ValueError(
            f"only settled entries may be credited (state={entry.state.value})"
        )
    return ComputeReuseEvent(
        description=(
            f"verified reuse of {entry.claim.commitment.work_class} "
            f"(claim {entry.claim.claim_id[:8]})"
        ),
        baseline_cost_seconds=entry.baseline.seconds,
        actual_cost_seconds=entry.claim.actual_cost_seconds,
    )
