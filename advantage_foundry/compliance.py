"""Compliance boundary — what a strategy is allowed to vary, and what it is not.

This module is a hard gate, not advice. Every strategy, experiment, and
assignment passes through :func:`check_variation` before it can be scheduled,
shown, or measured. A violation is a rejection, never a warning.

The rule the whole product rests on: the system may experiment with *how
approved work is organized*. It may not experiment with medical truth.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Iterable, List, Sequence


class Dimension(str, Enum):
    """A dimension of a strategy that could, in principle, be varied."""

    # ── Permitted: organization of approved work ──────────────────────────
    TIMING              = "timing"
    CHANNEL             = "channel"
    ROUTE               = "route"
    STAKEHOLDER         = "stakeholder"
    CONTENT_SEQUENCE    = "approved_content_sequence"
    WORKFLOW            = "workflow_organization"
    FOLLOW_UP_INTERVAL  = "follow_up_interval"
    ACCOUNT_PRIORITY    = "account_prioritization"
    ADMIN_EXECUTION     = "administrative_execution"

    # ── Forbidden: medical, promotional, and privacy truth ────────────────
    APPROVED_CLAIMS     = "approved_claims"
    SAFETY_INFORMATION  = "safety_information"
    SCIENTIFIC_EVIDENCE = "scientific_evidence"
    FAIR_BALANCE        = "fair_balance"
    INDICATION          = "indication_boundaries"
    PRIVACY             = "privacy_restrictions"
    PROMOTIONAL_PERMS   = "promotional_permissions"
    PATIENT_TARGETING   = "patient_level_targeting"
    CONTACT_PERMISSION  = "permitted_contact_rules"


MUTABLE: frozenset = frozenset({
    Dimension.TIMING,
    Dimension.CHANNEL,
    Dimension.ROUTE,
    Dimension.STAKEHOLDER,
    Dimension.CONTENT_SEQUENCE,
    Dimension.WORKFLOW,
    Dimension.FOLLOW_UP_INTERVAL,
    Dimension.ACCOUNT_PRIORITY,
    Dimension.ADMIN_EXECUTION,
})

IMMUTABLE: frozenset = frozenset(set(Dimension) - MUTABLE)


@dataclass
class ComplianceVerdict:
    allowed: bool
    violations: List[str] = field(default_factory=list)
    reason: str = ""

    def __bool__(self) -> bool:  # `if verdict:` reads naturally at call sites
        return self.allowed


class ComplianceViolation(Exception):
    """Raised when forbidden variation reaches an execution path."""


def check_variation(dimensions: Iterable[str]) -> ComplianceVerdict:
    """Verify that a strategy varies only permitted dimensions.

    Unknown dimension names are treated as violations. A dimension the boundary
    has never heard of has not been reviewed, and unreviewed variation in a
    regulated channel is exactly the failure mode this gate exists to prevent.
    """
    violations: List[str] = []
    unknown: List[str] = []

    for raw in dimensions:
        try:
            dim = Dimension(raw)
        except ValueError:
            unknown.append(str(raw))
            continue
        if dim in IMMUTABLE:
            violations.append(dim.value)

    if violations or unknown:
        parts = []
        if violations:
            parts.append("varies protected dimension(s): " + ", ".join(sorted(violations)))
        if unknown:
            parts.append("unreviewed dimension(s): " + ", ".join(sorted(unknown)))
        return ComplianceVerdict(False, violations + unknown, "; ".join(parts))

    return ComplianceVerdict(True, [], "varies only permitted dimensions")


def enforce(dimensions: Iterable[str]) -> None:
    """Raise :class:`ComplianceViolation` if any dimension is out of bounds."""
    verdict = check_variation(dimensions)
    if not verdict:
        raise ComplianceViolation(verdict.reason)


# ── Anti-gaming detectors ────────────────────────────────────────────────
#
# These flag *data quality*, not people. A flag suppresses an outcome from the
# learning set — it never produces a performance penalty, and it is never shown
# to a manager as a behavioral score.

@dataclass
class GamingFlag:
    kind: str
    detail: str
    suppress_from_learning: bool = True


def detect_gaming(activities: Sequence[Dict]) -> List[GamingFlag]:
    """Inspect logged activity for patterns that corrupt the evidence base.

    Each activity is a dict with at least ``account_id``, ``kind``,
    ``occurred_at`` and ``logged_at`` (epoch seconds), and optionally
    ``progressed`` (bool) and ``stage_delta`` (int).
    """
    flags: List[GamingFlag] = []

    # Duplicate engagements: same account, same kind, within five minutes.
    seen: Dict[tuple, List[int]] = {}
    for act in activities:
        key = (act.get("account_id"), act.get("kind"))
        seen.setdefault(key, []).append(int(act.get("occurred_at", 0)))
    for (account_id, kind), stamps in seen.items():
        stamps.sort()
        for earlier, later in zip(stamps, stamps[1:]):
            if later - earlier < 300:
                flags.append(GamingFlag(
                    "duplicate_engagement",
                    f"{kind} logged twice on {account_id} within {later - earlier}s",
                ))
                break

    # Backdated entry: logged more than 72h after the activity it describes.
    for act in activities:
        lag = int(act.get("logged_at", 0)) - int(act.get("occurred_at", 0))
        if lag > 72 * 3600:
            flags.append(GamingFlag(
                "delayed_entry",
                f"{act.get('kind')} on {act.get('account_id')} logged {lag // 3600}h late",
            ))

    # Activity theater: high volume on an account with no state movement at all.
    per_account: Dict[str, List[Dict]] = {}
    for act in activities:
        per_account.setdefault(str(act.get("account_id")), []).append(act)
    for account_id, acts in per_account.items():
        if len(acts) >= 8 and not any(a.get("progressed") for a in acts):
            flags.append(GamingFlag(
                "activity_without_progression",
                f"{len(acts)} logged touches on {account_id}, no state change",
            ))

    # Stage manipulation: an account walked backwards then forwards again.
    for account_id, acts in per_account.items():
        deltas = [int(a.get("stage_delta", 0)) for a in sorted(
            acts, key=lambda a: int(a.get("occurred_at", 0)))]
        for back, forward in zip(deltas, deltas[1:]):
            if back < 0 < forward:
                flags.append(GamingFlag(
                    "stage_oscillation",
                    f"{account_id} regressed then advanced within the window",
                ))
                break

    return flags
