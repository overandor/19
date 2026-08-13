"""Fair comparison — who counts as a peer, and how territory advantage is
divided out before anyone is placed on a percentile.

Nobody is compared to the whole field. A representative working a restricted
rural territory is compared to representatives working restricted rural
territories, and their result is divided by the advantage their territory
supplied before it is compared to anyone at all.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field


@dataclass
class Territory:
    """Territory conditions, expressed as multipliers around a market median.

    ``opportunity``, ``maturity`` and ``resources`` are indexed so that 1.0 is
    the median territory: 1.3 means 30% more of that advantage than median.

    ``access_difficulty`` runs the other way — 1.0 is median, 1.4 means access is
    40% harder than median. Note that the product sketch divided the observed
    result by access difficulty; that is backwards, and would have handed the
    highest adjusted scores to whoever had the *easiest* access. Difficulty
    multiplies the adjusted result instead: doing the same work through harder
    access is worth more, not less.
    """

    territory_id: str
    product: str
    opportunity: float = 1.0
    maturity: float = 1.0
    resources: float = 1.0
    access_difficulty: float = 1.0
    territory_type: str = "mixed"          # urban | rural | integrated | independent | mixed
    restrictions: list[str] = field(default_factory=list)

    @property
    def advantage_multiplier(self) -> float:
        """How much of a result the territory itself supplies.

        Above 1.0 means the territory is doing some of the work.
        """
        difficulty = max(self.access_difficulty, 0.1)
        return round((self.opportunity * self.maturity * self.resources) / difficulty, 4)


@dataclass
class Employee:
    employee_id: str
    name: str
    territory: Territory
    tenure_days: int
    qualifying_accounts: int = 0
    experiment_opt_in: bool = True
    observed_result: float = 0.0                    # raw commercial/progression output
    dimensions: dict[str, float] = field(default_factory=dict)

    @property
    def adjusted_result(self) -> float:
        """Observed result with territory advantage divided out."""
        return round(self.observed_result / max(self.territory.advantage_multiplier, 0.01), 4)

    @property
    def tenure_band(self) -> str:
        if self.tenure_days < 90:
            return "onboarding"
        if self.tenure_days < 365:
            return "first_year"
        if self.tenure_days < 365 * 3:
            return "established"
        return "senior"


@dataclass
class Cohort:
    """A set of genuinely comparable peers, plus the receipt explaining why."""

    members: list[Employee]
    basis: list[str]
    tolerance: float
    sufficient: bool

    @property
    def size(self) -> int:
        return len(self.members)


MIN_COHORT = 12
_TOLERANCE_STEPS = (0.10, 0.20, 0.35, 0.50)


def match_cohort(
    subject: Employee,
    population: Sequence[Employee],
    *,
    min_size: int = MIN_COHORT,
) -> Cohort:
    """Find comparable peers, widening tolerance only as far as necessary.

    Product, market restrictions and tenure band are matched exactly — they
    change what the job *is*, so loosening them would not produce a fairer
    comparison, it would produce a meaningless one. Continuous conditions
    (opportunity, maturity, resources, access difficulty) are matched within a
    tolerance that widens in steps until the cohort is large enough to place
    someone.

    A cohort below ``min_size`` is returned with ``sufficient=False``. Callers
    must suppress the percentile rather than publish a placement drawn from four
    people.
    """
    same_job = [
        peer for peer in population
        if peer.employee_id != subject.employee_id
        and peer.territory.product == subject.territory.product
        and set(peer.territory.restrictions) == set(subject.territory.restrictions)
        and peer.tenure_band == subject.tenure_band
    ]

    basis = [
        f"same product ({subject.territory.product})",
        f"same market restrictions ({', '.join(subject.territory.restrictions) or 'none'})",
        f"comparable tenure ({subject.tenure_band.replace('_', ' ')})",
    ]

    for tolerance in _TOLERANCE_STEPS:
        members = [peer for peer in same_job if _within(subject, peer, tolerance)]
        if len(members) >= min_size:
            return Cohort(
                members=members,
                basis=basis + [
                    f"territory opportunity within {int(tolerance * 100)}%",
                    f"access conditions within {int(tolerance * 100)}%",
                ],
                tolerance=tolerance,
                sufficient=True,
            )

    widest = [peer for peer in same_job if _within(subject, peer, _TOLERANCE_STEPS[-1])]
    return Cohort(
        members=widest,
        basis=basis + [f"territory conditions within {int(_TOLERANCE_STEPS[-1] * 100)}%"],
        tolerance=_TOLERANCE_STEPS[-1],
        sufficient=False,
    )


def _within(subject: Employee, peer: Employee, tolerance: float) -> bool:
    for attr in ("opportunity", "maturity", "resources", "access_difficulty"):
        mine = getattr(subject.territory, attr)
        theirs = getattr(peer.territory, attr)
        if abs(theirs - mine) > tolerance * max(abs(mine), 0.01):
            return False
    return True


def percentile(value: float, comparison: Sequence[float]) -> int | None:
    """Percentile of ``value`` within ``comparison``. ``None`` if empty."""
    if not comparison:
        return None
    below = sum(1 for other in comparison if other < value)
    ties = sum(1 for other in comparison if other == value)
    return round(100 * (below + 0.5 * ties) / len(comparison))


def place(subject: Employee, cohort: Cohort) -> dict:
    """Place an employee against their cohort, raw and adjusted.

    Both numbers are returned together, always. The gap between them is the
    point: it is what separates the employee's execution from their ZIP code.
    """
    if not cohort.members:
        return {
            "percentile_adjusted": None,
            "percentile_raw": None,
            "cohort_size": 0,
            "cohort_basis": cohort.basis,
            "sufficient": False,
            "note": "No comparable peers found. Showing your own trend instead.",
        }

    adjusted = percentile(subject.adjusted_result,
                          [peer.adjusted_result for peer in cohort.members])
    raw = percentile(subject.observed_result,
                     [peer.observed_result for peer in cohort.members])

    note = None
    if not cohort.sufficient:
        note = (f"Only {cohort.size} comparable peers — not enough to place you "
                f"fairly yet. Showing your own trend instead.")

    return {
        "percentile_adjusted": adjusted if cohort.sufficient else None,
        "percentile_raw": raw if cohort.sufficient else None,
        "cohort_size": cohort.size,
        "cohort_basis": cohort.basis,
        "sufficient": cohort.sufficient,
        "territory_advantage": subject.territory.advantage_multiplier,
        "note": note,
    }


# ── Multidimensional competitive score ───────────────────────────────────

SCORE_DIMENSIONS: tuple[str, ...] = (
    "opportunity_realization",
    "account_progression",
    "follow_up_reliability",
    "field_time_efficiency",
    "data_quality",
    "stakeholder_coverage",
    "learning_adaptability",
)


@dataclass
class CompetitiveScore:
    """Seven numbers, deliberately not summed into one.

    Collapsing these into a single rank is the exact move this product exists to
    refuse: it destroys the only information that tells someone what to fix.
    """

    scores: dict[str, float]
    #: Underlying absolute values, kept for tie-breaking. In a tightly matched
    #: cohort every percentile can land on 50, and picking the "weakest"
    #: dimension by dictionary order would hand someone an arbitrary constraint.
    raw: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return dict(self.scores)

    def _rank_key(self, dimension: str):
        return (self.scores[dimension], self.raw.get(dimension, 0.0))

    def constraint(self, *, correctable: Sequence[str] = SCORE_DIMENSIONS) -> str | None:
        """The weakest dimension the employee can actually act on."""
        actionable = [k for k in self.scores if k in set(correctable)]
        if not actionable:
            return None
        return min(actionable, key=self._rank_key)

    def weakest(self) -> str | None:
        """The weakest dimension overall, correctable or not."""
        return min(self.scores, key=self._rank_key) if self.scores else None

    def strength(self) -> str | None:
        return max(self.scores, key=self._rank_key) if self.scores else None


def score_employee(subject: Employee, cohort: Cohort) -> CompetitiveScore:
    """Score each dimension as a cohort percentile, not an absolute grade."""
    scores: dict[str, float] = {}
    raw: dict[str, float] = {}
    for dimension in SCORE_DIMENSIONS:
        mine = subject.dimensions.get(dimension)
        if mine is None:
            continue
        peers = [peer.dimensions[dimension] for peer in cohort.members
                 if dimension in peer.dimensions]
        pct = percentile(mine, peers)
        scores[dimension] = float(pct) if pct is not None else round(mine * 100, 1)
        raw[dimension] = mine
    return CompetitiveScore(scores, raw)


def as_dict(obj) -> dict:
    return asdict(obj)
