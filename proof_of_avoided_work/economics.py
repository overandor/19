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
from enum import Enum


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


# ── liquidity: deterrence once credits are redeemable ───────────────────────
#
# Everything above prices fraud in credits. That is the right unit only
# while credits are a bookkeeping entry. Once a pool will exchange them for
# something, the question becomes whether the pool can be drained, and the
# answer turns on one detail that is easy to get wrong: **what the bond is
# denominated in.**
#
# With a bond held in the quote asset, the credit-denominated rule above is
# already conservative. A cheater dumping into a constant-product pool
# suffers slippage, so they realise *less* than spot for their fraudulent
# credits while the bond they forfeit is unaffected. Deterrence only
# improves.
#
# With a bond held in credits, it inverts. The cheater's dump moves the
# price against the credits, and the bond is priced in exactly the asset
# they just crashed — so the collateral is worth least at the precise
# moment it is slashed. Collateral correlated with the attack it secures is
# a well-known way to lose money, and here it is not a modelling nicety: at
# realistic depths it is the difference between a solvent pool and a
# drainable one. `assess_pool_solvency` prices both cases exactly, by
# selling the slashed bond into the post-dump pool rather than at spot.


class BondDenomination(str, Enum):
    QUOTE = "quote"
    CREDITS = "credits"


@dataclass(frozen=True)
class Bond:
    """Collateral at risk, and — decisively — what it is denominated in."""

    amount: float
    denomination: BondDenomination = BondDenomination.QUOTE

    def __post_init__(self) -> None:
        if self.amount < 0:
            raise ValueError("bond amount must be non-negative")


@dataclass(frozen=True)
class ConstantProductPool:
    """A constant-product pool, priced for the one question that matters:
    how much of the quote asset can be extracted by dumping credits in."""

    credit_reserve: float
    quote_reserve: float
    fee_fraction: float = 0.003

    def __post_init__(self) -> None:
        if self.credit_reserve <= 0 or self.quote_reserve <= 0:
            raise ValueError("both reserves must be positive")
        if not 0.0 <= self.fee_fraction < 1.0:
            raise ValueError("fee_fraction must be in [0, 1)")

    @property
    def spot_price(self) -> float:
        """Quote per credit before slippage. The optimistic number."""
        return self.quote_reserve / self.credit_reserve

    def proceeds(self, credits_in: float) -> float:
        """Quote received for selling `credits_in`, after slippage and fee.

        Bounded above by `quote_reserve` however large the input, which is
        what caps a cheater and makes their worst case an interior k rather
        than "as many fakes as possible".
        """
        if credits_in <= 0:
            return 0.0
        effective = credits_in * (1.0 - self.fee_fraction)
        return self.quote_reserve * effective / (self.credit_reserve + effective)

    def after_selling(self, credits_in: float) -> ConstantProductPool:
        """The pool as it stands once `credits_in` has been dumped into it."""
        if credits_in <= 0:
            return self
        effective = credits_in * (1.0 - self.fee_fraction)
        return ConstantProductPool(
            credit_reserve=self.credit_reserve + effective,
            quote_reserve=self.quote_reserve - self.proceeds(credits_in),
            fee_fraction=self.fee_fraction,
        )

    @property
    def max_drainable_quote(self) -> float:
        """The pool's entire quote side — the asymptote, never quite reached."""
        return self.quote_reserve


@dataclass(frozen=True)
class SolvencyAssessment:
    """Whether a pool can be drained profitably at this audit rate and bond."""

    solvent: bool
    worst_case_claims: int
    worst_case_value_quote: float
    required_bond_quote: float
    bond_value_quote: float
    audit_rate: float
    reason: str


def _detection(audit_rate: float, k: int) -> float:
    return 1.0 - (1.0 - audit_rate) ** k


def slash_value_quote(
    pool: ConstantProductPool, bond: Bond, credits_dumped: float
) -> float:
    """What the forfeited bond is actually worth after the cheater's dump.

    A quote-denominated bond is untouched by the dump. A credit-denominated
    one is sold into the pool the dump has already moved, which is the
    whole point: the collateral is priced in the asset the attack devalues.
    """
    if bond.denomination is BondDenomination.QUOTE:
        return bond.amount
    return pool.after_selling(credits_dumped).proceeds(bond.amount)


def assess_pool_solvency(
    pool: ConstantProductPool,
    audit_rate: float,
    credits_per_fraudulent_claim: float,
    bond: Bond,
    max_claims: int = 10_000,
) -> SolvencyAssessment:
    """Find the cheater's best strategy and check the bond covers it.

    Scans k because the objective is not monotone: proceeds saturate at pool
    depth while detection converges on certainty, so the maximum sits at an
    interior k determined by depth, audit rate and per-claim gain together.
    A closed form exists for particular fee and reserve choices and is not
    worth the fragility — the scan is exact at every k it visits, and the
    tail beyond the break is dominated by `(1-p)^k` decay.
    """
    if not 0.0 < audit_rate <= 1.0:
        raise ValueError("audit_rate must be in (0, 1]")
    if credits_per_fraudulent_claim <= 0:
        raise ValueError("credits_per_fraudulent_claim must be positive")

    worst_k = 1
    worst_value = float("-inf")
    required_bond = 0.0
    worst_bond_value = 0.0

    for k in range(1, max_claims + 1):
        dumped = k * credits_per_fraudulent_claim
        undetected = (1.0 - audit_rate) ** k
        detected = _detection(audit_rate, k)
        gross = pool.proceeds(dumped)
        slash = slash_value_quote(pool, bond, dumped)

        value = undetected * gross - detected * slash
        if value > worst_value:
            worst_value, worst_k, worst_bond_value = value, k, slash
        if detected > 0:
            required_bond = max(required_bond, undetected * gross / detected)
        if undetected * pool.max_drainable_quote < 1e-12:
            # Every larger k is bounded by this and strictly worse for the
            # cheater; nothing beyond it can become the maximum.
            break

    solvent = worst_value <= 0
    if solvent:
        reason = (
            f"a cheater's best strategy is {worst_k} fake claim(s), worth "
            f"{worst_value:.4g} quote — non-positive, so draining the pool "
            "does not pay"
        )
    else:
        reason = (
            f"{worst_k} fake claim(s) nets {worst_value:.4g} quote against a "
            f"bond worth {worst_bond_value:.4g} when slashed. A quote-"
            f"denominated bond of at least {required_bond:.4g} closes it; "
            "raising the audit rate or reducing pool depth also does."
        )

    return SolvencyAssessment(
        solvent=solvent,
        worst_case_claims=worst_k,
        worst_case_value_quote=worst_value,
        required_bond_quote=required_bond,
        bond_value_quote=worst_bond_value,
        audit_rate=audit_rate,
        reason=reason,
    )


def required_bond_for_pool(
    pool: ConstantProductPool,
    audit_rate: float,
    credits_per_fraudulent_claim: float,
    max_claims: int = 10_000,
) -> float:
    """The smallest *quote-denominated* bond that makes every strategy lose.

    Quote-denominated on purpose: there is no credit-denominated bond that
    is safe at every depth, because the cheater controls the price of their
    own collateral.
    """
    return assess_pool_solvency(
        pool,
        audit_rate,
        credits_per_fraudulent_claim,
        Bond(0.0, BondDenomination.QUOTE),
        max_claims=max_claims,
    ).required_bond_quote
