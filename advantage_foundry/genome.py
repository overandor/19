"""Strategy genome — the structured representation that makes strategies
comparable, modifiable, and transferable.

A strategy is not a sentence in a playbook. It is a set of typed fields, so the
system can hold the stakeholder constant while varying the timing, notice that a
method works in integrated systems but fails in independent practices, and
recombine supported components into a new challenger without inventing anything.
"""
from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from enum import Enum

from .compliance import check_variation


class EvidenceClass(str, Enum):
    """The only four things the product may claim about a strategy.

    Ordered. ``EXPERIMENTALLY_SUPPORTED`` is the ceiling — there is no
    "proven", and no label that means "the model is certain".
    """

    UNRESOLVED               = "unresolved"
    OBSERVED_ASSOCIATION     = "observed_association"
    PROBABLE_CONTRIBUTION    = "probable_contribution"
    EXPERIMENTALLY_SUPPORTED = "experimentally_supported"

    @property
    def rank(self) -> int:
        return _EVIDENCE_ORDER.index(self)

    def at_least(self, other: EvidenceClass) -> bool:
        return self.rank >= other.rank

    @property
    def display(self) -> str:
        return {
            EvidenceClass.UNRESOLVED: "cannot be attributed yet",
            EvidenceClass.OBSERVED_ASSOCIATION: "appeared together — no causal claim",
            EvidenceClass.PROBABLE_CONTRIBUTION: "likely helped, after adjustment",
            EvidenceClass.EXPERIMENTALLY_SUPPORTED: "beat a real comparison group",
        }[self]


_EVIDENCE_ORDER = [
    EvidenceClass.UNRESOLVED,
    EvidenceClass.OBSERVED_ASSOCIATION,
    EvidenceClass.PROBABLE_CONTRIBUTION,
    EvidenceClass.EXPERIMENTALLY_SUPPORTED,
]


class Lifecycle(str, Enum):
    PROPOSED      = "proposed"
    SIMULATED     = "simulated"
    SHADOW_TESTED = "shadow_tested"
    LIMITED_TRIAL = "limited_trial"
    SUPPORTED     = "supported"
    EXPANDED      = "expanded"
    MONITORED     = "monitored"
    RETIRED       = "retired"


# A strategy may only advance one step at a time. It may be retired from
# anywhere — including mid-trial, which is what makes experiments reversible.
_TRANSITIONS: dict[Lifecycle, set] = {
    Lifecycle.PROPOSED:      {Lifecycle.SIMULATED, Lifecycle.RETIRED},
    Lifecycle.SIMULATED:     {Lifecycle.SHADOW_TESTED, Lifecycle.RETIRED},
    Lifecycle.SHADOW_TESTED: {Lifecycle.LIMITED_TRIAL, Lifecycle.RETIRED},
    Lifecycle.LIMITED_TRIAL: {Lifecycle.SUPPORTED, Lifecycle.RETIRED},
    Lifecycle.SUPPORTED:     {Lifecycle.EXPANDED, Lifecycle.MONITORED, Lifecycle.RETIRED},
    Lifecycle.EXPANDED:      {Lifecycle.MONITORED, Lifecycle.RETIRED},
    # Decay is detected under monitoring; a decayed strategy goes back to trial
    # rather than being silently kept or silently dropped.
    Lifecycle.MONITORED:     {Lifecycle.LIMITED_TRIAL, Lifecycle.EXPANDED, Lifecycle.RETIRED},
    Lifecycle.RETIRED:       set(),
}


class LifecycleError(Exception):
    """Raised on an illegal strategy state transition."""


def advance(current: Lifecycle, target: Lifecycle) -> Lifecycle:
    """Return ``target`` if the transition is legal, else raise."""
    if target not in _TRANSITIONS[current]:
        legal = ", ".join(sorted(s.value for s in _TRANSITIONS[current])) or "none"
        raise LifecycleError(
            f"{current.value} -> {target.value} is not a legal transition (legal: {legal})"
        )
    return target


# ── Eligibility ──────────────────────────────────────────────────────────

@dataclass
class Eligibility:
    """The conditions under which a strategy is allowed to be assigned.

    Empty collections mean "unconstrained on this axis". ``forbidden_*`` fields
    are hard exclusions and are checked before any fit scoring — a strategy that
    must not be used is never merely a low-scoring option.
    """

    account_states: list[str]       = field(default_factory=list)
    barriers: list[str]             = field(default_factory=list)
    territory_types: list[str]      = field(default_factory=list)
    min_qualifying_accounts: int    = 0
    min_tenure_days: int            = 0
    forbidden_account_states: list[str] = field(default_factory=list)
    forbidden_conditions: list[str]     = field(default_factory=list)

    def excludes(self, context: dict) -> str | None:
        """Return a human-readable exclusion reason, or ``None`` if eligible."""
        state = context.get("account_state")
        if state and state in self.forbidden_account_states:
            return f"account state '{state}' is excluded by this strategy"

        for condition in self.forbidden_conditions:
            if condition in set(context.get("conditions", [])):
                return f"blocking condition present: {condition}"

        if self.account_states and state not in self.account_states:
            return f"account state '{state}' is outside the strategy's use conditions"

        barrier = context.get("barrier")
        if self.barriers and barrier not in self.barriers:
            return f"barrier '{barrier}' is not what this strategy addresses"

        territory = context.get("territory_type")
        if self.territory_types and territory not in self.territory_types:
            return f"territory type '{territory}' is outside tested conditions"

        qualifying = int(context.get("qualifying_accounts", 0))
        if qualifying < self.min_qualifying_accounts:
            return (f"needs {self.min_qualifying_accounts} qualifying accounts, "
                    f"employee has {qualifying}")

        tenure = int(context.get("tenure_days", 0))
        if tenure < self.min_tenure_days:
            return f"needs {self.min_tenure_days} days tenure, employee has {tenure}"

        return None


@dataclass
class StrategyGenome:
    """A structured, comparable, recombinable strategy."""

    strategy_id: str
    name: str
    varies: list[str]                                   # compliance dimensions
    sequence: list[str]                                 # the literal steps
    eligibility: Eligibility = field(default_factory=Eligibility)
    stakeholder: str | None = None
    channel: str | None = None
    timing_window: str | None = None
    follow_up_hours: int | None = None
    content: str | None = None
    escalation_rule: str | None = None
    stopping_condition: str | None = None
    expected_outcome: str = ""
    evidence: EvidenceClass = EvidenceClass.UNRESOLVED
    lifecycle: Lifecycle = Lifecycle.PROPOSED
    expected_effect: float = 0.0                        # cohort-relative, 0-1 scale
    effect_low: float = 0.0                             # lower credible bound
    effect_high: float = 0.0
    execution_cost_minutes: int = 30
    known_failure: str | None = None
    risk: str = "low"                                   # low | moderate
    parent_ids: list[str] = field(default_factory=list)  # for recombined challengers
    created_at: int = field(default_factory=lambda: int(time.time()))

    def __post_init__(self) -> None:
        verdict = check_variation(self.varies)
        if not verdict:
            raise ValueError(f"strategy '{self.name}' rejected: {verdict.reason}")
        if self.risk not in {"low", "moderate"}:
            raise ValueError("risk must be 'low' or 'moderate'; high-risk work is "
                             "never assigned experimentally")

    # ── Matching ─────────────────────────────────────────────────────────

    def fit(self, context: dict) -> float:
        """Score 0.0-1.0 for how well this strategy suits a context.

        Returns 0.0 for an excluded context — callers should check
        :meth:`Eligibility.excludes` when they need the reason, not just the
        score, because the reason is what the UI shows.
        """
        if self.eligibility.excludes(context):
            return 0.0

        # Specificity is a virtue: a strategy that names the exact barrier it
        # addresses is a better match than one that names nothing at all.
        hits, possible = 0.0, 0.0
        for declared, observed in (
            (self.eligibility.account_states, context.get("account_state")),
            (self.eligibility.barriers, context.get("barrier")),
            (self.eligibility.territory_types, context.get("territory_type")),
        ):
            if declared:
                possible += 1
                if observed in declared:
                    hits += 1

        specificity = (hits / possible) if possible else 0.5
        confidence = (self.evidence.rank + 1) / len(_EVIDENCE_ORDER)
        return round(0.5 * specificity + 0.3 * confidence + 0.2 * self.expected_effect, 4)

    # ── Evolution ────────────────────────────────────────────────────────

    def components(self) -> dict[str, object]:
        """Decompose into the reusable parts a challenger can inherit."""
        return {
            "stakeholder": self.stakeholder,
            "channel": self.channel,
            "timing_window": self.timing_window,
            "follow_up_hours": self.follow_up_hours,
            "content": self.content,
            "sequence": list(self.sequence),
            "escalation_rule": self.escalation_rule,
        }

    def to_dict(self) -> dict:
        data = asdict(self)
        data["evidence"] = self.evidence.value
        data["lifecycle"] = self.lifecycle.value
        return data


def recombine(
    parents: Sequence[StrategyGenome],
    take: dict[str, str],
    *,
    strategy_id: str,
    name: str,
) -> StrategyGenome:
    """Build a new challenger from components of supported parents.

    ``take`` maps a component name to the ``strategy_id`` it is inherited from,
    e.g. ``{"stakeholder": "workflow-first-2.3", "timing_window": "am-access-1.0"}``.

    This is bounded evolution, not improvisation: every component of the child
    already survived measurement in a parent, the child inherits the union of its
    parents' varied dimensions (so the compliance gate still applies), and it
    enters the lifecycle at ``PROPOSED`` with ``UNRESOLVED`` evidence. Nothing is
    generated — only recombined.
    """
    by_id = {p.strategy_id: p for p in parents}
    missing = set(take.values()) - set(by_id)
    if missing:
        raise ValueError(f"unknown parent strategy id(s): {', '.join(sorted(missing))}")

    for parent in parents:
        if not parent.evidence.at_least(EvidenceClass.PROBABLE_CONTRIBUTION):
            raise ValueError(
                f"'{parent.name}' has evidence '{parent.evidence.value}' — components "
                "may only be inherited from strategies with at least probable contribution"
            )

    child_parts: dict[str, object] = {}
    for component, parent_id in take.items():
        parent_components = by_id[parent_id].components()
        if component not in parent_components:
            raise ValueError(f"'{component}' is not a recombinable component")
        child_parts[component] = parent_components[component]

    varies = sorted({d for p in parents for d in p.varies})
    sequence = list(child_parts.pop("sequence", [])) or [
        step for p in parents for step in p.sequence
    ]

    # The child is only assignable where *every* parent was assignable. Inheriting
    # the intersection of use conditions keeps a recombined strategy from wandering
    # into contexts none of its components were ever measured in.
    def _intersect(attr: str) -> list[str]:
        declared = [set(getattr(p.eligibility, attr)) for p in parents
                    if getattr(p.eligibility, attr)]
        if not declared:
            return []
        common = set.intersection(*declared)
        return sorted(common)

    eligibility = Eligibility(
        account_states=_intersect("account_states"),
        barriers=_intersect("barriers"),
        territory_types=_intersect("territory_types"),
        min_qualifying_accounts=max(p.eligibility.min_qualifying_accounts for p in parents),
        min_tenure_days=max(p.eligibility.min_tenure_days for p in parents),
        forbidden_account_states=sorted({s for p in parents
                                         for s in p.eligibility.forbidden_account_states}),
        forbidden_conditions=sorted({c for p in parents
                                     for c in p.eligibility.forbidden_conditions}),
    )

    return StrategyGenome(
        strategy_id=strategy_id,
        name=name,
        varies=varies,
        sequence=sequence,
        eligibility=eligibility,
        expected_outcome="; ".join(sorted({p.expected_outcome for p in parents if p.expected_outcome})),
        execution_cost_minutes=max(p.execution_cost_minutes for p in parents),
        risk="moderate" if any(p.risk == "moderate" for p in parents) else "low",
        evidence=EvidenceClass.UNRESOLVED,
        lifecycle=Lifecycle.PROPOSED,
        parent_ids=sorted({p.strategy_id for p in parents}),
        **child_parts,  # type: ignore[arg-type]
    )
