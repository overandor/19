"""Commitments that make a compute-reuse claim checkable after the fact.

The problem this file exists to solve: an ed25519 signature over "I saved
600 seconds" proves *who said it*, not *that it is true*. Signed
self-reports are unfalsifiable, and an unfalsifiable meter cannot be the
basis of a credit.

A `WorkCommitment` pins a claim to a specific, re-executable unit of
work — the same inputs, the same code version, the same environment — so
an auditor can later run that exact unit and compare what comes out
against what the claimant said came out. `ReuseClaim` binds a served
result to that commitment. Neither structure asserts a saving; they only
make the assertion falsifiable, which is the part that was missing.

Determinism caveat, stated once and honoured throughout: this only works
for work classes that are deterministic under their commitment. Greedy
decoding at a fixed seed and a pinned model revision qualifies;
temperature sampling without a recorded seed does not, and such a work
class must not be metered here (see `docs/PROOF_OF_AVOIDED_WORK.md`).
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Mapping, Optional

from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.signature import Signature


def canonical_bytes(payload: object) -> bytes:
    """Byte-exact, order-independent encoding used for every digest here."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_object(payload: object) -> str:
    return digest_bytes(canonical_bytes(payload))


@dataclass(frozen=True)
class WorkCommitment:
    """Identifies one re-executable unit of work.

    `work_class` groups units whose cold cost is comparable — it is the key
    the baseline oracle indexes on, so it must be narrow enough that two
    units in the same class really do cost about the same to compute cold
    (e.g. "llm.prefill:model-rev-8f21:ctx-8k", not "llm").
    """

    work_class: str
    input_digest: str
    code_version: str
    env_digest: str

    def __post_init__(self) -> None:
        for name in ("work_class", "input_digest", "code_version", "env_digest"):
            if not getattr(self, name):
                raise ValueError(f"{name} must be non-empty")

    @classmethod
    def over(
        cls,
        work_class: str,
        payload: bytes,
        code_version: str,
        env: Optional[Mapping[str, object]] = None,
    ) -> "WorkCommitment":
        return cls(
            work_class=work_class,
            input_digest=digest_bytes(payload),
            code_version=code_version,
            env_digest=digest_object(dict(env or {})),
        )

    def digest(self) -> str:
        return digest_object(asdict(self))


@dataclass
class ReuseClaim:
    """A signed assertion that `commitment` was served from reused state.

    `actual_cost_seconds` is the cost the claimant did pay and is cheap to
    bound from the outside. `claimed_baseline_seconds` is what a cold run
    would supposedly have cost — it is carried only as an advisory hint and
    is never used to compute credit; the baseline oracle decides that.
    """

    commitment: WorkCommitment
    output_digest: str
    actual_cost_seconds: float
    epoch: int
    claimant_pubkey: str
    signature: str = ""
    claimed_baseline_seconds: Optional[float] = None
    claim_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: int = field(default_factory=lambda: int(time.time()))

    def __post_init__(self) -> None:
        if self.actual_cost_seconds < 0:
            raise ValueError("actual_cost_seconds must be non-negative")
        if self.epoch < 0:
            raise ValueError("epoch must be non-negative")
        if not self.output_digest:
            raise ValueError("output_digest must be non-empty")

    @property
    def record_hash(self) -> str:
        """Digest of the signed body; also the audit-sampling key.

        Sampling keys off this rather than off `claim_id` so that a
        claimant cannot cheaply grind the value that decides selection —
        changing it requires re-signing, and is useless anyway while the
        epoch seed is still committed but unrevealed.
        """
        return digest_bytes(self.signing_payload())

    @property
    def dedup_key(self) -> str:
        """Same unit, same epoch, same claimant -> the same key, exactly once."""
        return digest_object(
            {
                "commitment": self.commitment.digest(),
                "epoch": self.epoch,
                "claimant": self.claimant_pubkey,
            }
        )

    def signing_payload(self) -> bytes:
        # Excludes `signature` so verify() can rebuild the signed bytes.
        return canonical_bytes(
            {
                "claim_id": self.claim_id,
                "commitment": asdict(self.commitment),
                "output_digest": self.output_digest,
                "actual_cost_seconds": self.actual_cost_seconds,
                "claimed_baseline_seconds": self.claimed_baseline_seconds,
                "epoch": self.epoch,
                "claimant_pubkey": self.claimant_pubkey,
                "created_at": self.created_at,
            }
        )

    def verify(self) -> bool:
        if not self.signature:
            return False
        try:
            sig = Signature.from_string(self.signature)
            pubkey = Pubkey.from_string(self.claimant_pubkey)
        except ValueError:
            return False
        return sig.verify(pubkey, self.signing_payload())

    def to_dict(self) -> dict:
        data = asdict(self)
        data["record_hash"] = self.record_hash
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "ReuseClaim":
        return cls(
            commitment=WorkCommitment(**data["commitment"]),
            output_digest=data["output_digest"],
            actual_cost_seconds=data["actual_cost_seconds"],
            epoch=data["epoch"],
            claimant_pubkey=data["claimant_pubkey"],
            signature=data["signature"],
            claimed_baseline_seconds=data.get("claimed_baseline_seconds"),
            claim_id=data["claim_id"],
            created_at=data["created_at"],
        )


def sign_claim(
    commitment: WorkCommitment,
    output_digest: str,
    actual_cost_seconds: float,
    epoch: int,
    signer: Keypair,
    claimed_baseline_seconds: Optional[float] = None,
) -> ReuseClaim:
    claim = ReuseClaim(
        commitment=commitment,
        output_digest=output_digest,
        actual_cost_seconds=actual_cost_seconds,
        epoch=epoch,
        claimant_pubkey=str(signer.pubkey()),
        claimed_baseline_seconds=claimed_baseline_seconds,
    )
    claim.signature = str(signer.sign_message(claim.signing_payload()))
    return claim
