"""Governance guards — the constraints that must not be design decisions.

Everything here exists because a well-meaning downstream feature would otherwise
eventually do it: join experiment participation to a compensation table, put an
override count in a review packet, or pipe email bodies into a manager's feed.
These are functions, not guidelines, so the violation is a test failure.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Sequence

#: Surfaces where experimental participation may never appear.
EVALUATIVE_SURFACES = frozenset({
    "compensation", "promotion", "discipline", "termination", "performance_ranking",
})

#: Fields a manager view may never carry, regardless of caller.
MANAGER_FORBIDDEN_FIELDS = frozenset({
    "email_body", "email_subject", "email_snippet", "message_content",
    "location_trail", "activity_feed", "override_count", "decline_count",
    "experiment_acceptance_rate", "keystrokes", "login_times",
})


class GovernanceViolation(Exception):
    """Raised when a guarded constraint is about to be broken."""


def assert_not_evaluative(surface: str, records: Sequence[Dict]) -> None:
    """Block experimental assignments from reaching an evaluative surface."""
    if surface not in EVALUATIVE_SURFACES:
        return
    offending = [r for r in records
                 if r.get("klass") == "experimental" or r.get("not_for_evaluation")]
    if offending:
        raise GovernanceViolation(
            f"{len(offending)} experimental assignment(s) reached the '{surface}' "
            f"surface. Experiment participation may never determine pay, promotion, "
            f"discipline, or ranking."
        )


def strip_experimental(records: Iterable[Dict]) -> List[Dict]:
    """Remove experimental participation before any evaluative aggregation."""
    return [r for r in records
            if r.get("klass") != "experimental" and not r.get("not_for_evaluation")]


def manager_safe(payload: Dict) -> Dict:
    """Return a manager-facing payload with surveillance fields removed.

    Recurses, because the leak is always a nested field somebody added later.
    """
    def clean(value):
        if isinstance(value, dict):
            return {k: clean(v) for k, v in value.items()
                    if k not in MANAGER_FORBIDDEN_FIELDS}
        if isinstance(value, list):
            return [clean(v) for v in value]
        return value

    return clean(payload)


def override_is_signal(override: Dict) -> Dict:
    """Convert an employee override into a learning record.

    An override is data about the recommendation, never a fact about the person.
    The employee id is deliberately dropped: nothing downstream can accumulate a
    per-person disobedience score from what this function returns.
    """
    return {
        "strategy_id": override.get("strategy_id"),
        "action": override.get("action"),          # modify | replace | decline | data_wrong
        "context": override.get("context", {}),
        "stated_reason": override.get("reason"),   # optional, never required
        "interpretation": "recommendation_mismatch",
        "counts_against_employee": False,
    }
