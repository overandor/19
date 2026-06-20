"""Append-only, hash-chained ledger of credit receipts.

Each receipt's `prev_hash` must equal the `record_hash` of the receipt
before it, and each receipt's signature must verify against its signer.
verify_chain() checks both for the full history, so a rewritten or
re-ordered receipt is detectable.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from solders.keypair import Keypair

from .receipts import GENESIS_HASH, ComputeReuseEvent, Receipt, sign_event


@dataclass
class ChainBreak:
    index: int
    reason: str


class CreditLedger:
    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path
        self._receipts: List[Receipt] = []
        if path and path.exists():
            data = json.loads(path.read_text())
            self._receipts = [Receipt.from_dict(r) for r in data]

    @property
    def receipts(self) -> List[Receipt]:
        return list(self._receipts)

    def record_event(
        self,
        event: ComputeReuseEvent,
        signer: Keypair,
        credits_per_second_saved: float = 1.0,
    ) -> Receipt:
        prev_hash = self._receipts[-1].record_hash if self._receipts else GENESIS_HASH
        receipt = sign_event(event, signer, prev_hash, credits_per_second_saved)
        self._receipts.append(receipt)
        self._persist()
        return receipt

    def balance(self, signer_pubkey: Optional[str] = None) -> float:
        return sum(
            r.credits
            for r in self._receipts
            if signer_pubkey is None or r.signer_pubkey == signer_pubkey
        )

    def verify_chain(self) -> List[ChainBreak]:
        breaks: List[ChainBreak] = []
        expected_prev = GENESIS_HASH
        for i, receipt in enumerate(self._receipts):
            if receipt.prev_hash != expected_prev:
                breaks.append(ChainBreak(i, "prev_hash does not match preceding record"))
            if not receipt.verify():
                breaks.append(ChainBreak(i, "signature does not verify"))
            expected_prev = receipt.record_hash
        return breaks

    def _persist(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps([r.to_dict() for r in self._receipts], indent=2))
