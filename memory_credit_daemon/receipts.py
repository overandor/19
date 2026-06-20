"""Signed receipts for recoverable-computational-state reuse events.

A receipt attests, with an ed25519 signature, that a given amount of
cold-recompute cost was avoided by reusing previously-computed state.
This is the unit the credit ledger in ledger.py accrues.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field

from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.signature import Signature

GENESIS_HASH = "0" * 64


@dataclass
class ComputeReuseEvent:
    description: str
    baseline_cost_seconds: float
    actual_cost_seconds: float
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    occurred_at: int = field(default_factory=lambda: int(time.time()))

    def __post_init__(self) -> None:
        if self.baseline_cost_seconds < 0 or self.actual_cost_seconds < 0:
            raise ValueError("costs must be non-negative")

    @property
    def seconds_saved(self) -> float:
        return max(0.0, self.baseline_cost_seconds - self.actual_cost_seconds)


@dataclass
class Receipt:
    event: ComputeReuseEvent
    credits: float
    prev_hash: str
    signer_pubkey: str
    signature: str
    receipt_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: int = field(default_factory=lambda: int(time.time()))

    @property
    def record_hash(self) -> str:
        return hashlib.sha256(self._signing_payload()).hexdigest()

    def verify(self) -> bool:
        sig = Signature.from_string(self.signature)
        pubkey = Pubkey.from_string(self.signer_pubkey)
        return sig.verify(pubkey, self._signing_payload())

    def to_dict(self) -> dict:
        d = asdict(self)
        d["record_hash"] = self.record_hash
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "Receipt":
        event = ComputeReuseEvent(**data["event"])
        return cls(
            event=event,
            credits=data["credits"],
            prev_hash=data["prev_hash"],
            signer_pubkey=data["signer_pubkey"],
            signature=data["signature"],
            receipt_id=data["receipt_id"],
            created_at=data["created_at"],
        )

    def _signing_payload(self) -> bytes:
        # Deliberately excludes `signature` itself, so verify() can
        # recompute the exact bytes that were signed.
        return json.dumps(
            {
                "receipt_id": self.receipt_id,
                "event": asdict(self.event),
                "credits": self.credits,
                "prev_hash": self.prev_hash,
                "created_at": self.created_at,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")


def sign_event(
    event: ComputeReuseEvent,
    signer: Keypair,
    prev_hash: str,
    credits_per_second_saved: float = 1.0,
) -> Receipt:
    """Scores an event into credits and returns a signed Receipt."""
    receipt = Receipt(
        event=event,
        credits=event.seconds_saved * credits_per_second_saved,
        prev_hash=prev_hash,
        signer_pubkey=str(signer.pubkey()),
        signature="",
    )
    receipt.signature = str(signer.sign_message(receipt._signing_payload()))
    return receipt
