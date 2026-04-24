"""Approval gate — enforces human-in-the-loop review before any state mutation."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional


class GateDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    PENDING  = "pending"


@dataclass
class GateRecord:
    proposal_id: str
    action_type: str
    payload: Dict
    submitted_at: int = field(default_factory=lambda: int(time.time()))
    decision: str = GateDecision.PENDING
    decided_at: Optional[int] = None
    reviewer: Optional[str] = None
    reason: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)


class ApprovalGate:
    """
    Enforces the research-only constraint: no automated mutation of manifests,
    signals, or proposals without an explicit human approval record.
    """

    ALLOWED_ACTION_TYPES = {
        "update_manifest",
        "promote_hypothesis",
        "archive_signal",
        "update_safety_policy",
        "run_simulation",
    }

    def __init__(self, log_path: Optional[Path] = None) -> None:
        self.log_path = log_path
        self._records: Dict[str, Dict] = {}
        if log_path and log_path.exists():
            try:
                for rec in json.loads(log_path.read_text()):
                    self._records[rec["proposal_id"]] = rec
            except (json.JSONDecodeError, OSError):
                pass

    def request(self, proposal_id: str, action_type: str, payload: Dict) -> GateRecord:
        """Register a new proposal awaiting human review."""
        if action_type not in self.ALLOWED_ACTION_TYPES:
            raise ValueError(
                f"Unknown action type '{action_type}'. "
                f"Allowed: {sorted(self.ALLOWED_ACTION_TYPES)}"
            )
        if proposal_id in self._records:
            raise ValueError(f"Proposal '{proposal_id}' already exists.")

        record = GateRecord(proposal_id=proposal_id, action_type=action_type, payload=payload)
        self._records[proposal_id] = record.to_dict()
        self._persist()
        return record

    def approve(self, proposal_id: str, reviewer: str, reason: str = "") -> GateRecord:
        return self._decide(proposal_id, GateDecision.APPROVED, reviewer, reason)

    def reject(self, proposal_id: str, reviewer: str, reason: str = "") -> GateRecord:
        return self._decide(proposal_id, GateDecision.REJECTED, reviewer, reason)

    def status(self, proposal_id: str) -> Optional[Dict]:
        return self._records.get(proposal_id)

    def pending(self) -> List[Dict]:
        return [r for r in self._records.values() if r["decision"] == GateDecision.PENDING]

    def execute(self, proposal_id: str) -> Dict:
        """Return the approved payload. Raises if not yet approved."""
        record = self._records.get(proposal_id)
        if not record:
            raise KeyError(f"No proposal '{proposal_id}' found.")
        if record["decision"] != GateDecision.APPROVED:
            raise PermissionError(
                f"Proposal '{proposal_id}' has decision='{record['decision']}'. "
                "Only approved proposals may be executed."
            )
        return record["payload"]

    def summary(self) -> Dict:
        counts: Dict[str, int] = {d.value: 0 for d in GateDecision}
        for r in self._records.values():
            counts[r["decision"]] = counts.get(r["decision"], 0) + 1
        return {"total": len(self._records), **counts}

    def _decide(
        self, proposal_id: str, decision: GateDecision, reviewer: str, reason: str
    ) -> GateRecord:
        record = self._records.get(proposal_id)
        if not record:
            raise KeyError(f"No proposal '{proposal_id}' found.")
        if record["decision"] != GateDecision.PENDING:
            raise ValueError(f"Proposal '{proposal_id}' already decided: {record['decision']}")
        record["decision"]   = decision.value
        record["decided_at"] = int(time.time())
        record["reviewer"]   = reviewer
        record["reason"]     = reason
        self._records[proposal_id] = record
        self._persist()
        return GateRecord(**record)

    def _persist(self) -> None:
        if not self.log_path:
            return
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.write_text(
            json.dumps(list(self._records.values()), separators=(",", ":"))
        )
