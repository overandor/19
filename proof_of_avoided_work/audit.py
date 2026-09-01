"""Selecting claims to check, and proving the ones that lied.

Two things have to be true of the selection at once: a claimant must not
be able to predict it while claiming, and anyone must be able to recompute
it afterwards. Commit-reveal gives both. The auditor publishes
`sha256(seed)` before the epoch opens and reveals `seed` after it closes;
selection is `HMAC(seed, claim.record_hash)` compared against the audit
rate. During the epoch the seed is unknown, so a claimant cannot steer a
claim into the unaudited set; after the reveal the whole selection is a
pure function of public values, so nobody has to trust the auditor's word
about which claims were picked.

A fraud proof here is a fact a third party can re-derive, not a verdict to
be taken on faith:

* `OUTPUT_MISMATCH` — re-execution produced a different digest than the
  claim served. The reuse was phantom or corrupt.
* `IMPOSSIBLE_COST` — the claimed cost is not below the observed cold
  cost, so nothing was avoided.
* `BASELINE_INFLATION` — the hinted baseline exceeded what the oracle's
  own samples admit.
* `DOUBLE_CLAIM` — the same unit billed twice in one epoch. Costs nothing
  to detect and needs no re-execution, so it is checked on every claim
  rather than only on sampled ones.
* `BAD_SIGNATURE` — the claim does not verify against its stated key.

Auditing produces a second, less obvious good: re-execution measures a
genuine cold cost, and that timing is exactly the sample the baseline
oracle needs. Checking claims and maintaining the baseline are the same
activity, which is why the oracle does not need its own trusted
measurement programme.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from enum import Enum

from .commitments import ReuseClaim, WorkCommitment, digest_object

# HMAC-SHA256 output width, used to normalise the selection value to [0, 1).
_HASH_SPACE = 2 ** 256


class FraudKind(str, Enum):
    OUTPUT_MISMATCH = "output_mismatch"
    IMPOSSIBLE_COST = "impossible_cost"
    BASELINE_INFLATION = "baseline_inflation"
    DOUBLE_CLAIM = "double_claim"
    BAD_SIGNATURE = "bad_signature"


@dataclass(frozen=True)
class FraudProof:
    """A re-derivable statement that one claim was false."""

    kind: FraudKind
    claim_id: str
    claimant_pubkey: str
    detail: str
    evidence: dict[str, object] = field(default_factory=dict)

    def digest(self) -> str:
        return digest_object(
            {
                "kind": self.kind.value,
                "claim_id": self.claim_id,
                "claimant_pubkey": self.claimant_pubkey,
                "detail": self.detail,
                "evidence": self.evidence,
            }
        )


@dataclass(frozen=True)
class ReexecutionResult:
    """What a cold re-run of a committed unit produced."""

    output_digest: str
    cold_cost_seconds: float

    def __post_init__(self) -> None:
        if self.cold_cost_seconds <= 0:
            raise ValueError("cold_cost_seconds must be positive")
        if not self.output_digest:
            raise ValueError("output_digest must be non-empty")


Reexecutor = Callable[[WorkCommitment], ReexecutionResult]


class SeedCommitment:
    """Commit-reveal over the epoch's sampling seed."""

    def __init__(self, seed: bytes | None = None) -> None:
        self._seed = seed if seed is not None else secrets.token_bytes(32)
        self.commitment = hashlib.sha256(self._seed).hexdigest()
        self.created_at = int(time.time())
        self._revealed = False

    @staticmethod
    def commitment_for(seed: bytes) -> str:
        return hashlib.sha256(seed).hexdigest()

    @staticmethod
    def check_reveal(commitment: str, seed: bytes) -> bool:
        return hmac.compare_digest(
            commitment, SeedCommitment.commitment_for(seed)
        )

    def reveal(self) -> bytes:
        self._revealed = True
        return self._seed

    @property
    def revealed(self) -> bool:
        return self._revealed


def selection_value(seed: bytes, record_hash: str) -> float:
    """Deterministic, seed-keyed value in [0, 1) for one claim."""
    mac = hmac.new(seed, record_hash.encode("utf-8"), hashlib.sha256).digest()
    return int.from_bytes(mac, "big") / _HASH_SPACE


def is_selected(seed: bytes, record_hash: str, audit_rate: float) -> bool:
    if not 0.0 <= audit_rate <= 1.0:
        raise ValueError("audit_rate must be in [0, 1]")
    return selection_value(seed, record_hash) < audit_rate


def select_claims(
    seed: bytes, claims: list[ReuseClaim], audit_rate: float
) -> list[ReuseClaim]:
    return [c for c in claims if is_selected(seed, c.record_hash, audit_rate)]


@dataclass(frozen=True)
class AuditVerdict:
    claim_id: str
    passed: bool
    fraud_proof: FraudProof | None = None
    observed_cold_cost_seconds: float | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        if self.fraud_proof is not None:
            data["fraud_proof"]["kind"] = self.fraud_proof.kind.value
        return data


class DoubleClaimIndex:
    """Remembers every dedup key seen, so a repeat is provable for free."""

    def __init__(self) -> None:
        self._seen: dict[str, str] = {}

    def register(self, claim: ReuseClaim) -> FraudProof | None:
        prior = self._seen.get(claim.dedup_key)
        if prior is not None:
            return FraudProof(
                kind=FraudKind.DOUBLE_CLAIM,
                claim_id=claim.claim_id,
                claimant_pubkey=claim.claimant_pubkey,
                detail="work unit already claimed in this epoch by this claimant",
                evidence={
                    "dedup_key": claim.dedup_key,
                    "first_claim_id": prior,
                    "epoch": claim.epoch,
                },
            )
        self._seen[claim.dedup_key] = claim.claim_id
        return None

    def __len__(self) -> int:
        return len(self._seen)


def audit_claim(claim: ReuseClaim, reexecutor: Reexecutor) -> AuditVerdict:
    """Re-execute one claim's unit and compare against what it asserted."""
    if not claim.verify():
        return AuditVerdict(
            claim_id=claim.claim_id,
            passed=False,
            fraud_proof=FraudProof(
                kind=FraudKind.BAD_SIGNATURE,
                claim_id=claim.claim_id,
                claimant_pubkey=claim.claimant_pubkey,
                detail="claim signature does not verify against its stated key",
            ),
        )

    result = reexecutor(claim.commitment)

    if result.output_digest != claim.output_digest:
        return AuditVerdict(
            claim_id=claim.claim_id,
            passed=False,
            observed_cold_cost_seconds=result.cold_cost_seconds,
            fraud_proof=FraudProof(
                kind=FraudKind.OUTPUT_MISMATCH,
                claim_id=claim.claim_id,
                claimant_pubkey=claim.claimant_pubkey,
                detail="re-execution of the committed unit produced a different result",
                evidence={
                    "claimed_output_digest": claim.output_digest,
                    "reexecuted_output_digest": result.output_digest,
                    "commitment_digest": claim.commitment.digest(),
                },
            ),
        )

    if claim.actual_cost_seconds >= result.cold_cost_seconds:
        return AuditVerdict(
            claim_id=claim.claim_id,
            passed=False,
            observed_cold_cost_seconds=result.cold_cost_seconds,
            fraud_proof=FraudProof(
                kind=FraudKind.IMPOSSIBLE_COST,
                claim_id=claim.claim_id,
                claimant_pubkey=claim.claimant_pubkey,
                detail="claimed cost is not below observed cold cost, so nothing was avoided",
                evidence={
                    "actual_cost_seconds": claim.actual_cost_seconds,
                    "observed_cold_cost_seconds": result.cold_cost_seconds,
                },
            ),
        )

    return AuditVerdict(
        claim_id=claim.claim_id,
        passed=True,
        observed_cold_cost_seconds=result.cold_cost_seconds,
    )


def baseline_inflation_proof(
    claim: ReuseClaim, bound_seconds: float
) -> FraudProof | None:
    """Flag a hint that exceeds what the oracle's samples admit.

    Settlement already clips to the bound, so inflation cannot pay; this
    exists to make a repeated attempt attributable rather than silent.
    """
    hint = claim.claimed_baseline_seconds
    if hint is None or hint <= bound_seconds:
        return None
    return FraudProof(
        kind=FraudKind.BASELINE_INFLATION,
        claim_id=claim.claim_id,
        claimant_pubkey=claim.claimant_pubkey,
        detail="claimed baseline exceeds the oracle's admissible bound",
        evidence={
            "claimed_baseline_seconds": hint,
            "admissible_bound_seconds": bound_seconds,
            "work_class": claim.commitment.work_class,
        },
    )
