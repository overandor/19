"""Portability, repeatability, and selective diffusion.

A strategy that worked is not yet a strategy that travels. This module decides
where a validated advantage is allowed to go, and refuses the reflex of pushing
every winner to everybody — which would destroy the comparison groups that
produced the finding in the first place.
"""
from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Sequence

from .genome import EvidenceClass, StrategyGenome


class Portability(str, Enum):
    GLOBAL           = "global"
    SELECTIVE        = "selective"
    LOCAL            = "local"
    NON_TRANSFERABLE = "non_transferable"


class Decay(str, Enum):
    STABLE   = "stable"
    DECAYING = "decaying"
    EXPIRED  = "expired"


@dataclass
class ContextResult:
    """One measured application of a strategy in one kind of place."""

    context_key: str                 # e.g. "integrated_system:workflow_blocked"
    lift: float                      # points of progression vs matched comparison
    sample: int
    representative_id: Optional[str] = None
    territory_id: Optional[str] = None
    period: int = 0                  # ordinal period, for decay checks


@dataclass
class PortabilityAssessment:
    portability: Portability
    strong_fit: List[str] = field(default_factory=list)
    weak_fit: List[str] = field(default_factory=list)
    untested: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        data = asdict(self)
        data["portability"] = self.portability.value
        return data


MIN_CONTEXT_SAMPLE = 20


def assess_portability(
    results: Sequence[ContextResult],
    *,
    all_contexts: Sequence[str] = (),
) -> PortabilityAssessment:
    """Classify where a strategy replicates, from measured results per context."""
    by_context: Dict[str, List[ContextResult]] = {}
    for result in results:
        by_context.setdefault(result.context_key, []).append(result)

    strong, weak, untested = [], [], []
    for context, entries in by_context.items():
        sample = sum(e.sample for e in entries)
        mean_lift = statistics.fmean(e.lift for e in entries)
        if sample < MIN_CONTEXT_SAMPLE:
            untested.append(context)
        elif mean_lift > 0.05:
            strong.append(context)
        else:
            weak.append(context)

    untested.extend(c for c in all_contexts if c not in by_context)

    tested = len(strong) + len(weak)
    if tested == 0:
        portability = Portability.NON_TRANSFERABLE
    elif len(strong) == tested and tested >= 3:
        portability = Portability.GLOBAL
    elif strong and weak:
        portability = Portability.SELECTIVE
    elif strong:
        portability = Portability.LOCAL
    else:
        portability = Portability.NON_TRANSFERABLE

    return PortabilityAssessment(portability, sorted(strong), sorted(weak), sorted(set(untested)))


@dataclass
class Repeatability:
    """Is this a method, a person, a place, or a coincidence?"""

    one_time_coincidence: str
    representative_dependent: str
    territory_dependent: str
    method_dependent: str
    expected_durability: str

    def to_dict(self) -> Dict:
        return asdict(self)


def _dependence(groups: Dict[str, List[float]]) -> str:
    """How much of the effect rides on which group you happen to be in."""
    means = [statistics.fmean(v) for v in groups.values() if v]
    if len(means) < 2:
        return "unknown"
    spread = max(means) - min(means)
    if spread > 0.20:
        return "high"
    if spread > 0.08:
        return "moderate"
    return "low"


def assess_repeatability(results: Sequence[ContextResult]) -> Repeatability:
    """Separate method quality from a strong employee, an easy territory, and luck."""
    by_rep: Dict[str, List[float]] = {}
    by_territory: Dict[str, List[float]] = {}
    for result in results:
        if result.representative_id:
            by_rep.setdefault(result.representative_id, []).append(result.lift)
        if result.territory_id:
            by_territory.setdefault(result.territory_id, []).append(result.lift)

    total_sample = sum(r.sample for r in results)
    lifts = [r.lift for r in results]
    positive = sum(1 for lift in lifts if lift > 0)

    rep_dep = _dependence(by_rep)
    terr_dep = _dependence(by_territory)

    if total_sample < 30 or len(results) < 3:
        coincidence = "likely"
    elif positive / max(len(lifts), 1) >= 0.7:
        coincidence = "unlikely"
    else:
        coincidence = "possible"

    # The method is credited only with what survives after person and place are
    # accounted for. A result that moves with whoever runs it is not a method.
    method_dep = "high" if (coincidence == "unlikely"
                            and rep_dep in ("low", "unknown")
                            and terr_dep in ("low", "moderate", "unknown")) else "moderate"

    if coincidence == "likely":
        durability = "unknown — too little evidence to project"
    elif method_dep == "high" and terr_dep == "low":
        durability = "six to twelve months under current market conditions"
    elif method_dep == "high":
        durability = "three to six months under current market conditions"
    else:
        durability = "one to three months; re-test before relying on it"

    return Repeatability(
        one_time_coincidence=coincidence,
        representative_dependent=rep_dep,
        territory_dependent=terr_dep,
        method_dependent=method_dep,
        expected_durability=durability,
    )


def assess_decay(results: Sequence[ContextResult]) -> Decay:
    """Compare recent periods against earlier ones."""
    periods = sorted({r.period for r in results})
    if len(periods) < 2:
        return Decay.STABLE

    midpoint = periods[len(periods) // 2]
    earlier = [r.lift for r in results if r.period < midpoint]
    recent = [r.lift for r in results if r.period >= midpoint]
    if not earlier or not recent:
        return Decay.STABLE

    before, after = statistics.fmean(earlier), statistics.fmean(recent)
    if after <= 0:
        return Decay.EXPIRED
    if after < before * 0.6:
        return Decay.DECAYING
    return Decay.STABLE


# ── Selective diffusion ──────────────────────────────────────────────────

@dataclass
class DiffusionPlan:
    decision: str                    # scale | continue | hold | retire
    rationale: str
    eligible_contexts: List[str] = field(default_factory=list)
    expansion_cap: int = 0           # how many territories in the next wave

    def to_dict(self) -> Dict:
        return asdict(self)


def plan_diffusion(
    genome: StrategyGenome,
    portability: PortabilityAssessment,
    repeatability: Repeatability,
    decay: Decay,
    *,
    candidate_contexts: Sequence[str] = (),
) -> DiffusionPlan:
    """Decide where a strategy goes next.

    Expansion is capped and staged even for the strongest result. A method that
    is deployed everywhere at once can never be measured again — the comparison
    group is gone, and with it the ability to notice the method decaying.
    """
    if decay is Decay.EXPIRED:
        return DiffusionPlan("retire",
                             "Effect has gone to zero in recent periods. Retire and "
                             "give the field time back.")

    if genome.expected_effect < 0 or (portability.portability is Portability.NON_TRANSFERABLE
                                      and portability.weak_fit):
        return DiffusionPlan("retire",
                             "No context replicates the effect. Retire as a default.")

    eligible = [c for c in candidate_contexts if c in set(portability.strong_fit)]

    if not genome.evidence.at_least(EvidenceClass.PROBABLE_CONTRIBUTION):
        return DiffusionPlan("continue",
                             "Not yet separable from territory conditions. Keep testing "
                             "under controlled allocation.",
                             eligible_contexts=eligible)

    if repeatability.one_time_coincidence == "likely":
        return DiffusionPlan("hold",
                             "Too few observations to rule out coincidence. Hold at "
                             "current footprint.",
                             eligible_contexts=eligible)

    if decay is Decay.DECAYING:
        return DiffusionPlan("hold",
                             "Effect is fading. Hold and re-test before expanding.",
                             eligible_contexts=eligible)

    if repeatability.representative_dependent == "high":
        return DiffusionPlan("hold",
                             "Results ride on who is running it, not on the method. "
                             "Coach the sequence before expanding it.",
                             eligible_contexts=eligible)

    if genome.evidence is EvidenceClass.EXPERIMENTALLY_SUPPORTED and eligible:
        # Half the eligible footprint, so the other half stays a comparison group.
        return DiffusionPlan("scale",
                             f"Replicates in {len(portability.strong_fit)} context type(s). "
                             f"Expand to matched territories in one wave, keeping the rest "
                             f"as comparison.",
                             eligible_contexts=eligible,
                             expansion_cap=max(1, len(eligible) // 2))

    return DiffusionPlan("continue",
                         "Promising but not yet experimentally separated. Continue "
                         "controlled testing.",
                         eligible_contexts=eligible)
