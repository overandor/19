"""Experiment contracts — bounded, reversible, visible, and stoppable.

An experiment that cannot state what it does not know is not an experiment. This
module refuses to construct one.
"""
from __future__ import annotations

import hashlib
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field

from .compliance import enforce
from .genome import EvidenceClass, Lifecycle, StrategyGenome

CONTROL = "control"

#: Default guardrails every contract inherits. A contract may add to these; it
#: may not remove one.
BASE_GUARDRAILS = (
    "Approved materials only",
    "No altered claims",
    "No contact frequency above policy",
    "No patient-level targeting",
    "Not used in compensation, ranking, or review",
)


@dataclass
class StopCondition:
    name: str
    description: str
    threshold: float | None = None


@dataclass
class ExperimentContract:
    experiment_id: str
    hypothesis: str
    what_is_known: str
    what_is_unknown: str
    primary_outcome: str
    duration_days: int
    variants: dict[str, StrategyGenome]              # variant name -> strategy
    secondary_outcomes: list[str] = field(default_factory=list)
    min_qualifying_accounts: int = 10
    excluded_conditions: list[str] = field(default_factory=lambda: [
        "active_medical_escalation", "conflicting_local_restriction"])
    exclude_onboarding: bool = True
    guardrails: list[str] = field(default_factory=lambda: list(BASE_GUARDRAILS))
    stop_conditions: list[StopCondition] = field(default_factory=lambda: [
        StopCondition("compliance_exception",
                      "Any compliance exception in a participating territory"),
        StopCondition("negative_outcome",
                      "Progression falls materially below control", threshold=-0.10),
        StopCondition("insufficient_sample",
                      "Too few qualifying accounts to learn anything", threshold=30),
    ])
    risk: str = "low"
    created_at: int = field(default_factory=lambda: int(time.time()))

    def __post_init__(self) -> None:
        if not self.hypothesis.strip():
            raise ValueError("an experiment contract requires a hypothesis")
        if not self.what_is_unknown.strip():
            raise ValueError(
                "an experiment contract requires 'what_is_unknown' — a strategy "
                "whose unknown cannot be named is a guess, not an experiment"
            )
        if CONTROL not in self.variants:
            raise ValueError("every experiment needs a control or valid comparison group")
        if len(self.variants) < 2:
            raise ValueError("an experiment needs at least one variant beyond control")
        for genome in self.variants.values():
            enforce(genome.varies)     # raises ComplianceViolation
        for guardrail in BASE_GUARDRAILS:
            if guardrail not in self.guardrails:
                self.guardrails.append(guardrail)

    # ── Eligibility ──────────────────────────────────────────────────────

    def excludes(self, context: dict) -> str | None:
        """Why this employee/account is not eligible, or ``None``."""
        if self.exclude_onboarding and int(context.get("tenure_days", 0)) < 90:
            return "new hires are excluded from experiments"
        qualifying = int(context.get("qualifying_accounts", 0))
        if qualifying < self.min_qualifying_accounts:
            return (f"needs {self.min_qualifying_accounts} qualifying accounts, "
                    f"has {qualifying}")
        for condition in self.excluded_conditions:
            if condition in set(context.get("conditions", [])):
                return f"excluded while '{condition}' is present"
        if not context.get("experiment_opt_in", True):
            return "employee has opted out of experiments"
        return None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["variants"] = {name: genome.to_dict() for name, genome in self.variants.items()}
        return data


def allocate_variants(
    contract: ExperimentContract,
    candidates: Sequence[dict],
) -> dict[str, str]:
    """Assign eligible participants to control or a variant.

    Allocation is deterministic in ``(experiment_id, employee_id)`` so a
    participant's arm is stable across re-runs and reconstructible during audit,
    without storing an allocation table that could drift from what was shown.

    Each candidate is a dict with ``employee_id`` plus the eligibility context.
    Ineligible candidates are simply absent from the result — they are never
    silently placed in control, which would poison the comparison group.
    """
    arms = sorted(contract.variants)
    allocation: dict[str, str] = {}
    for candidate in candidates:
        employee_id = str(candidate.get("employee_id"))
        if contract.excludes(candidate):
            continue
        digest = hashlib.sha256(
            f"{contract.experiment_id}:{employee_id}".encode()).digest()
        allocation[employee_id] = arms[digest[0] % len(arms)]
    return allocation


@dataclass
class StopDecision:
    should_stop: bool
    condition: str | None = None
    message: str = ""


def check_stop(contract: ExperimentContract, telemetry: dict) -> StopDecision:
    """Evaluate stop conditions against running telemetry.

    ``telemetry`` may carry ``compliance_exceptions`` (int),
    ``variant_progression`` / ``control_progression`` (floats), and
    ``qualifying_sample`` (int).
    """
    if int(telemetry.get("compliance_exceptions", 0)) > 0:
        return StopDecision(True, "compliance_exception",
                            "Stopped: a compliance exception was raised in a "
                            "participating territory.")

    variant = telemetry.get("variant_progression")
    control = telemetry.get("control_progression")
    if variant is not None and control is not None:
        threshold = next((c.threshold for c in contract.stop_conditions
                          if c.name == "negative_outcome"), -0.10)
        if (variant - control) <= (threshold or -0.10):
            return StopDecision(True, "negative_outcome",
                                "Stopped: this approach is performing worse than "
                                "standard work. You are back on standard work.")

    sample = telemetry.get("qualifying_sample")
    elapsed = int(telemetry.get("day_index", 0))
    if sample is not None and elapsed >= contract.duration_days:
        minimum = next((c.threshold for c in contract.stop_conditions
                        if c.name == "insufficient_sample"), 30)
        if sample < (minimum or 30):
            return StopDecision(True, "insufficient_sample",
                                "Closed without a result: too few qualifying "
                                "accounts to learn anything from this test.")

    return StopDecision(False)


def conclude(
    contract: ExperimentContract,
    variant_name: str,
    *,
    lift: float,
    confidence: str,
    sample: int,
) -> EvidenceClass:
    """Assign an evidence class to a concluded arm.

    A controlled comparison with adequate sample and a positive effect earns
    ``EXPERIMENTALLY_SUPPORTED`` — the ceiling. Everything weaker lands lower,
    and a null or ambiguous result lands on ``UNRESOLVED`` rather than being
    quietly dropped from the record.
    """
    if sample < 30:
        return EvidenceClass.UNRESOLVED
    if confidence == "high" and lift > 0:
        return EvidenceClass.EXPERIMENTALLY_SUPPORTED
    if confidence == "moderate" and lift > 0:
        return EvidenceClass.PROBABLE_CONTRIBUTION
    if lift > 0:
        return EvidenceClass.OBSERVED_ASSOCIATION
    return EvidenceClass.UNRESOLVED


def promote(genome: StrategyGenome, evidence: EvidenceClass) -> StrategyGenome:
    """Move a trialled strategy to its next lifecycle state from its result."""
    from .genome import advance  # local import keeps the module graph acyclic

    if evidence.at_least(EvidenceClass.PROBABLE_CONTRIBUTION):
        genome.lifecycle = advance(genome.lifecycle, Lifecycle.SUPPORTED)
    else:
        genome.lifecycle = advance(genome.lifecycle, Lifecycle.RETIRED)
    genome.evidence = evidence
    return genome
