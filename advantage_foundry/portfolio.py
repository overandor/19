"""Explore versus exploit — how much proven work, personalized work, and
experimentation each employee receives today, and which strategies fill it.

Two rules govern this module:

1. The mix is explained to the person it is applied to. A day that looks
   different from yesterday's always comes with the sentence that says why.
2. The system never knowingly assigns a worse strategy to buy a cleaner
   experiment. A challenger must be plausibly competitive with the best proven
   option before anyone's territory is spent testing it.
"""
from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field

from .genome import EvidenceClass, Lifecycle, StrategyGenome

PROVEN       = "proven"
PERSONALIZED = "personalized"
EXPERIMENTAL = "experimental"

BASE_MIX: dict[str, float] = {PROVEN: 0.60, PERSONALIZED: 0.25, EXPERIMENTAL: 0.15}
MAX_EXPERIMENTAL = 0.25

#: A challenger's lower credible bound must reach this fraction of the best
#: proven option's expected effect. Exploration is bounded by what it costs the
#: person doing the exploring.
MIN_EXPECTED_RATIO = 0.85


@dataclass
class Mix:
    proven: float
    personalized: float
    experimental: float
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)

    def as_percentages(self) -> tuple[int, int, int]:
        return (round(self.proven * 100), round(self.personalized * 100),
                round(self.experimental * 100))


@dataclass
class AllocationInputs:
    tenure_days: int
    experiment_opt_in: bool = True
    market_stability: float = 0.7        # 0 = churning, 1 = stable
    evidence_density: float = 0.7        # 0 = we know nothing here, 1 = well mapped
    compliance_risk: str = "low"         # low | moderate | high
    launch_window: bool = False
    reversible: bool = True


def allocate(inputs: AllocationInputs) -> Mix:
    """Compute today's portfolio mix and the one sentence that explains it."""
    experimental = BASE_MIX[EXPERIMENTAL]
    reason = "Standard mix for your experience and territory."

    # Hard zeros first — these are protections, not preferences.
    if inputs.tenure_days < 90:
        return _mix(0.0, "More proven work than usual: you are still onboarding.")
    if not inputs.experiment_opt_in:
        return _mix(0.0, "You have opted out of experiments. Proven and personalized work only.")
    if inputs.compliance_risk == "high":
        return _mix(0.0, "High-risk activity today — no experimental variation is applied.")
    if not inputs.reversible:
        return _mix(0.0, "Today's work cannot be undone, so nothing experimental is assigned.")

    if inputs.launch_window:
        experimental *= 0.5
        reason = "Less experimentation during a launch window."
    elif inputs.evidence_density < 0.4:
        experimental = min(experimental * 1.6, MAX_EXPERIMENTAL)
        reason = "More testing than usual: little is known about territories like yours yet."
    elif inputs.market_stability < 0.4:
        experimental *= 0.6
        reason = "Less experimentation while your market is moving quickly."
    elif inputs.compliance_risk == "moderate":
        experimental *= 0.7
        reason = "Slightly less experimentation given today's activity risk."

    return _mix(round(min(experimental, MAX_EXPERIMENTAL), 4), reason)


def _mix(experimental: float, reason: str) -> Mix:
    """Build a mix, giving the experimental remainder back to proven work."""
    personalized = BASE_MIX[PERSONALIZED]
    proven = round(1.0 - personalized - experimental, 4)
    return Mix(proven=proven, personalized=personalized,
               experimental=experimental, reason=reason)


def slots(mix: Mix, total_items: int = 5) -> dict[str, int]:
    """Turn a mix into whole assignment slots for a day of at most five items."""
    raw = {k: v * total_items for k, v in
           ((PROVEN, mix.proven), (PERSONALIZED, mix.personalized),
            (EXPERIMENTAL, mix.experimental))}
    counts = {k: int(v) for k, v in raw.items()}
    remainder = total_items - sum(counts.values())
    # Hand out leftover slots to the largest fractional parts, but never invent
    # an experimental slot the mix did not actually earn.
    order = sorted(raw, key=lambda k: raw[k] - counts[k], reverse=True)
    for key in order:
        if remainder <= 0:
            break
        if key == EXPERIMENTAL and mix.experimental <= 0:
            continue
        counts[key] += 1
        remainder -= 1
    if remainder > 0:
        counts[PROVEN] += remainder
    return counts


# ── Assignment ───────────────────────────────────────────────────────────

@dataclass
class Assignment:
    """The product's central primitive. Not a task — an operating method,
    its conditions, and its test."""

    assignment_id: str
    employee_id: str
    strategy_id: str
    strategy_name: str
    klass: str                               # proven | personalized | experimental
    constraint_addressed: str
    account_ref: str | None
    sequence: list[str]
    why: str
    evidence: EvidenceClass
    effort_minutes: int
    expected_effect: tuple[float, float]     # band, never a point
    evaluation_days: int
    risk: str
    reversible: bool = True
    #: Experimental participation may never reach a compensation, promotion,
    #: discipline, or ranking surface. Carried on the record so downstream
    #: consumers cannot claim they did not know.
    not_for_evaluation: bool = True
    assigned_at: int = field(default_factory=lambda: int(time.time()))
    actions: tuple[str, ...] = ("complete", "schedule", "modify", "replace",
                                "decline", "data_wrong")

    def to_dict(self) -> dict:
        data = asdict(self)
        data["evidence"] = self.evidence.value
        return data


def classify(genome: StrategyGenome) -> str:
    """Which lane a strategy belongs in, from its own evidence and lifecycle."""
    if genome.evidence is EvidenceClass.EXPERIMENTALLY_SUPPORTED and genome.lifecycle in (
        Lifecycle.SUPPORTED, Lifecycle.EXPANDED, Lifecycle.MONITORED
    ):
        return PROVEN
    if genome.evidence is EvidenceClass.PROBABLE_CONTRIBUTION and genome.lifecycle in (
        Lifecycle.EXPANDED, Lifecycle.MONITORED
    ):
        return PERSONALIZED
    return EXPERIMENTAL


def within_acceptable_band(
    challenger: StrategyGenome,
    best_proven: StrategyGenome | None,
    *,
    ratio: float = MIN_EXPECTED_RATIO,
) -> bool:
    """Is this challenger good enough to be worth someone's real territory?

    Compares the challenger's *lower* credible bound against the best proven
    option's expected effect. A challenger that might be much worse is not a
    bold experiment; it is a cost imposed on an employee who did not choose it.
    """
    if best_proven is None:
        return True
    if challenger.effect_high and challenger.effect_high < best_proven.expected_effect * ratio:
        return False
    floor = challenger.effect_low or challenger.expected_effect
    return floor >= best_proven.expected_effect * ratio


def select(
    genomes: Sequence[StrategyGenome],
    context: dict,
    mix: Mix,
    *,
    employee_id: str,
    constraint: str,
    total_items: int = 5,
) -> list[Assignment]:
    """Pick today's assignments: eligible, compliant, and lane-balanced."""
    eligible: list[tuple[StrategyGenome, float]] = []
    for genome in genomes:
        if genome.lifecycle is Lifecycle.RETIRED:
            continue
        if genome.eligibility.excludes(context):
            continue
        fit = genome.fit(context)
        if fit > 0:
            eligible.append((genome, fit))

    lanes: dict[str, list[tuple[StrategyGenome, float]]] = {
        PROVEN: [], PERSONALIZED: [], EXPERIMENTAL: []}
    for genome, fit in eligible:
        lanes[classify(genome)].append((genome, fit))
    for lane in lanes.values():
        lane.sort(key=lambda pair: pair[1], reverse=True)

    best_proven = lanes[PROVEN][0][0] if lanes[PROVEN] else None
    lanes[EXPERIMENTAL] = [
        (g, f) for g, f in lanes[EXPERIMENTAL]
        if within_acceptable_band(g, best_proven)
    ]

    wanted = slots(mix, total_items)
    assignments: list[Assignment] = []
    for lane_name in (PROVEN, PERSONALIZED, EXPERIMENTAL):
        for genome, fit in lanes[lane_name][:wanted[lane_name]]:
            assignments.append(_build(genome, lane_name, fit, context,
                                      employee_id=employee_id, constraint=constraint))

    # Under-filled lanes fall back to proven work rather than padding the day
    # with experiments nobody asked for.
    shortfall = total_items - len(assignments)
    if shortfall > 0:
        used = {a.strategy_id for a in assignments}
        for genome, fit in lanes[PROVEN] + lanes[PERSONALIZED]:
            if shortfall <= 0:
                break
            if genome.strategy_id in used:
                continue
            assignments.append(_build(genome, classify(genome), fit, context,
                                      employee_id=employee_id, constraint=constraint))
            shortfall -= 1

    return assignments


def _build(
    genome: StrategyGenome,
    lane: str,
    fit: float,
    context: dict,
    *,
    employee_id: str,
    constraint: str,
) -> Assignment:
    low = genome.effect_low or genome.expected_effect
    high = genome.effect_high or genome.expected_effect
    return Assignment(
        assignment_id=f"{employee_id}:{genome.strategy_id}:{int(time.time())}",
        employee_id=employee_id,
        strategy_id=genome.strategy_id,
        strategy_name=genome.name,
        klass=lane,
        constraint_addressed=constraint,
        account_ref=context.get("account_ref"),
        sequence=list(genome.sequence),
        why=_why(genome, lane, context),
        evidence=genome.evidence,
        effort_minutes=genome.execution_cost_minutes,
        expected_effect=(round(low, 4), round(high, 4)),
        evaluation_days=21 if lane == EXPERIMENTAL else 30,
        risk=genome.risk,
        reversible=True,
    )


def _why(genome: StrategyGenome, lane: str, context: dict) -> str:
    barrier = context.get("barrier", "the current barrier")
    if lane == PROVEN:
        return (f"Comparable accounts blocked by {barrier} progressed more often "
                f"after this sequence than after another standard visit.")
    if lane == PERSONALIZED:
        return (f"This matches where you already outperform your matched peers, "
                f"applied to an account blocked by {barrier}.")
    return (f"Promising in comparable accounts blocked by {barrier}. What is not "
            f"yet known is whether the effect transfers to your territory type — "
            f"that is what you are testing.")
