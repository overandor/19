"""Why you do not have to re-execute everything.

Verifying an avoided-work claim costs roughly what the work itself cost —
re-execution is the only ground truth — so a meter that checks every claim
spends more than the reuse ever saved and is worthless. The way out is
that the meter does not need every claim to be *checked*; it needs every
claim to be *not worth faking*.

Two inequalities decide whether a configuration can exist at all.

Deterrence floor. A claimant risking a bond, who gains `g` credits from a
fraudulent claim and forfeits a slash `S` when audited, faces
`EV = (1-p)*g - p*S`. Requiring `EV <= -margin*g` gives

    p_min = g * (1 + margin) / (g + S)

Budget ceiling. Auditing at rate `p` over `N` claims costs `p*N*c`, where
`c` is the cost of one cold re-execution. Holding that under a fraction
`b` of the credited value `V` gives

    p_max = b * V / (N * c)

A workable meter needs `p_min <= p_max`. Read together they say something
useful and non-obvious: since `V/N` is the average credit per claim,
`p_max` depends only on how much a typical claim is worth relative to
checking it, while `p_min` falls as the bond rises. **Bonds buy down audit
cost.** A large enough bond makes honest metering affordable at an audit
rate low enough that the re-execution bill stays a rounding error — which
is the whole reason this is a tractable problem rather than a restatement
of verifiable computation.

Everything here is arithmetic on stated assumptions, not an empirical
claim. The assumptions that matter — a bond that is actually at risk, a
fixed known `g`, a rational risk-neutral claimant — are listed in
`docs/PROOF_OF_AVOIDED_WORK.md` along with what breaks when they fail.
"""
from __future__ import annotations

from dataclasses import dataclass


class InfeasibleDeterrenceError(Exception):
    """Raised when no audit rate in (0, 1] can deter the modelled fraud."""


@dataclass(frozen=True)
class DeterrenceParams:
    """Inputs to the deterrence floor.

    bond_credits: stake the claimant forfeits from, denominated in credits.
    max_gain_per_fraudulent_claim: the largest `g` a single fraudulent
        claim can extract — with an oracle-clipped baseline this is bounded
        by the admissible bound, which is why the oracle is load-bearing
        for the economics and not just for correctness.
    penalty_multiplier: fraction of the bond actually slashed, in [0, 1].
    safety_margin: extra deterrence beyond break-even, as a multiple of g.
    """

    bond_credits: float
    max_gain_per_fraudulent_claim: float
    penalty_multiplier: float = 1.0
    safety_margin: float = 0.0

    def __post_init__(self) -> None:
        if self.bond_credits < 0:
            raise ValueError("bond_credits must be non-negative")
        if self.max_gain_per_fraudulent_claim <= 0:
            raise ValueError("max_gain_per_fraudulent_claim must be positive")
        if not 0.0 <= self.penalty_multiplier <= 1.0:
            raise ValueError("penalty_multiplier must be in [0, 1]")
        if self.safety_margin < 0:
            raise ValueError("safety_margin must be non-negative")

    @property
    def slash_credits(self) -> float:
        return self.bond_credits * self.penalty_multiplier


def minimum_audit_rate(params: DeterrenceParams) -> float:
    """Smallest audit rate making a single fraudulent claim negative-EV."""
    g = params.max_gain_per_fraudulent_claim
    s = params.slash_credits
    rate = g * (1.0 + params.safety_margin) / (g + s)
    if rate > 1.0:
        raise InfeasibleDeterrenceError(
            f"deterrence needs an audit rate of {rate:.3f}; even auditing every "
            "claim does not deter this gain at this bond. Raise the bond, raise "
            "the penalty multiplier, or cap the per-claim gain."
        )
    return rate


def required_bond(
    audit_rate: float,
    max_gain_per_fraudulent_claim: float,
    penalty_multiplier: float = 1.0,
    safety_margin: float = 0.0,
) -> float:
    """Bond needed to deter at a *chosen* audit rate (the floor, inverted)."""
    if not 0.0 < audit_rate <= 1.0:
        raise ValueError("audit_rate must be in (0, 1]")
    if max_gain_per_fraudulent_claim <= 0:
        raise ValueError("max_gain_per_fraudulent_claim must be positive")
    if not 0.0 < penalty_multiplier <= 1.0:
        raise ValueError("penalty_multiplier must be in (0, 1]")
    g = max_gain_per_fraudulent_claim
    slash = g * (1.0 + safety_margin) / audit_rate - g
    return max(0.0, slash / penalty_multiplier)


def expected_value_of_fraud(audit_rate: float, params: DeterrenceParams) -> float:
    """EV of one fraudulent claim. Negative means cheating does not pay."""
    if not 0.0 <= audit_rate <= 1.0:
        raise ValueError("audit_rate must be in [0, 1]")
    g = params.max_gain_per_fraudulent_claim
    return (1.0 - audit_rate) * g - audit_rate * params.slash_credits


def detection_probability(audit_rate: float, fraudulent_claims: int) -> float:
    """Chance at least one of `k` independently sampled fakes is caught.

    The reason a cheater cannot simply absorb the per-claim EV: repeated
    fraud converges on certain detection, so the only surviving strategy is
    a small number of fakes, which is precisely what the bond is sized for.
    """
    if not 0.0 <= audit_rate <= 1.0:
        raise ValueError("audit_rate must be in [0, 1]")
    if fraudulent_claims < 0:
        raise ValueError("fraudulent_claims must be non-negative")
    return 1.0 - (1.0 - audit_rate) ** fraudulent_claims


@dataclass(frozen=True)
class AuditBudget:
    """Inputs to the budget ceiling."""

    claims_per_epoch: int
    reexecution_cost_credits: float
    credited_value_per_epoch: float
    budget_fraction: float = 0.05

    def __post_init__(self) -> None:
        if self.claims_per_epoch <= 0:
            raise ValueError("claims_per_epoch must be positive")
        if self.reexecution_cost_credits <= 0:
            raise ValueError("reexecution_cost_credits must be positive")
        if self.credited_value_per_epoch < 0:
            raise ValueError("credited_value_per_epoch must be non-negative")
        if not 0.0 < self.budget_fraction <= 1.0:
            raise ValueError("budget_fraction must be in (0, 1]")

    @property
    def max_affordable_rate(self) -> float:
        spend = self.budget_fraction * self.credited_value_per_epoch
        return min(1.0, spend / (self.claims_per_epoch * self.reexecution_cost_credits))


def audit_cost_credits(audit_rate: float, budget: AuditBudget) -> float:
    return audit_rate * budget.claims_per_epoch * budget.reexecution_cost_credits


@dataclass(frozen=True)
class AuditPlan:
    """The resolved configuration: an audit rate, or why none exists."""

    feasible: bool
    audit_rate: float
    deterrence_floor: float
    budget_ceiling: float
    audit_cost_credits: float
    cost_fraction_of_credited_value: float
    reason: str


def plan_audit(params: DeterrenceParams, budget: AuditBudget) -> AuditPlan:
    """Resolve floor and ceiling into a rate to actually run at.

    Picks the floor when one exists — auditing above the deterrence
    threshold buys no additional deterrence and only costs money.
    """
    try:
        floor = minimum_audit_rate(params)
    except InfeasibleDeterrenceError as exc:
        return AuditPlan(
            feasible=False,
            audit_rate=1.0,
            deterrence_floor=float("inf"),
            budget_ceiling=budget.max_affordable_rate,
            audit_cost_credits=audit_cost_credits(1.0, budget),
            cost_fraction_of_credited_value=float("inf"),
            reason=str(exc),
        )
    ceiling = budget.max_affordable_rate
    feasible = floor <= ceiling
    rate = floor if feasible else ceiling
    cost = audit_cost_credits(rate, budget)
    value = budget.credited_value_per_epoch
    fraction = float("inf") if value == 0 else cost / value
    if feasible:
        reason = (
            f"auditing {rate:.1%} of claims deters fraud at a bond of "
            f"{params.bond_credits:g} credits for {fraction:.2%} of credited value"
        )
    else:
        reason = (
            f"deterrence needs {floor:.1%} of claims audited but the budget "
            f"affords only {ceiling:.1%}. Raise the bond (lowering the floor), "
            "raise the budget fraction, or cut re-execution cost."
        )
    return AuditPlan(
        feasible=feasible,
        audit_rate=rate,
        deterrence_floor=floor,
        budget_ceiling=ceiling,
        audit_cost_credits=cost,
        cost_fraction_of_credited_value=fraction,
        reason=reason,
    )
