"""The gate between verified credits and a token anyone can sell.

`memory_credit_daemon.cli.cmd_mint` derives its amount from
`CreditLedger.balance()` — the sum of *self-reported* receipts — and
`--amount` lets a caller name any number outright. On devnet that is
harmless. Pointed at a real pool it is a faucet: fabricate receipts, mint,
sell, repeat.

So minting goes through here instead, and this module will only ever
authorise credits that came out of `SettlementEngine` **settled** — audited,
or in an epoch where nobody was caught, and priced against the oracle's
baseline rather than a claimant's. Escrowed and voided claims are worth
zero, and there is no parameter that overrides the amount.

The second rule is the one the arithmetic in `economics.py` forced:

    **A bond must never be denominated in the credits it secures.**

A cheater's dump moves the price of the credits, so a credit-denominated
bond is worth least at the exact moment it is slashed — the collateral is
priced in the asset the attack devalues. At realistic depths that is the
difference between a solvent pool and a drainable one, so it is refused
here rather than warned about.

Nothing in this module signs or submits anything. It answers "how much may
be minted, and is that safe", and hands back an authorization the caller
still has to act on.
"""
from __future__ import annotations

from dataclasses import dataclass

from .economics import (
    Bond,
    BondDenomination,
    ConstantProductPool,
    SolvencyAssessment,
    assess_pool_solvency,
)
from .settlement import ClaimState, SettlementEngine


class UnverifiedCreditsError(Exception):
    """Raised when the credits asked for did not survive an audit."""


class PoolInsolventError(Exception):
    """Raised when minting into this pool would be profitable to attack."""


class UnsafeCollateralError(Exception):
    """Raised for a bond denominated in the credits it is meant to secure."""


def is_mainnet(network: str) -> bool:
    return "mainnet" in network.lower()


@dataclass(frozen=True)
class MintAuthorization:
    """Permission to mint a specific amount, and the evidence for it."""

    claimant_pubkey: str
    credits: float
    settled_claims: int
    escrowed_claims: int
    voided_claims: int
    network: str
    solvency: SolvencyAssessment | None = None

    @property
    def base_units(self) -> int:
        """Whole credits. Fractions are dropped, never rounded up."""
        return int(self.credits)

    def summary(self) -> str:
        headline = (
            f"{self.credits:.4f} credits from {self.settled_claims} settled "
            f"claim(s) for {self.claimant_pubkey[:8]}…"
        )
        parts = [headline]
        if self.escrowed_claims:
            parts.append(f"{self.escrowed_claims} still escrowed (worth nothing yet)")
        if self.voided_claims:
            parts.append(f"{self.voided_claims} voided by fraud")
        if self.solvency is not None:
            parts.append(self.solvency.reason)
        return "; ".join(parts)


def authorize_mint(
    engine: SettlementEngine,
    claimant_pubkey: str,
    network: str,
    pool: ConstantProductPool | None = None,
    bond: Bond | None = None,
    audit_rate: float | None = None,
    credits_per_fraudulent_claim: float | None = None,
) -> MintAuthorization:
    """Decide how much may be minted, refusing rather than trimming.

    On a test network, settled credits are enough. On mainnet the pool must
    also be shown non-drainable at the configured audit rate and bond,
    because a token nobody can sell cannot be drained and a token anybody
    can sell must not be mintable by lying.
    """
    entries = engine.entries(claimant_pubkey)
    settled = [e for e in entries if e.state is ClaimState.SETTLED]
    escrowed = [e for e in entries if e.state is ClaimState.ESCROWED]
    voided = [e for e in entries if e.state is ClaimState.VOID_FRAUD]

    credits = sum(e.credited for e in settled)
    if credits <= 0:
        raise UnverifiedCreditsError(
            f"no settled credits for {claimant_pubkey[:8]}…: "
            f"{len(escrowed)} claim(s) are still escrowed and {len(voided)} "
            "were voided. Run the epoch audit before minting."
        )

    solvency: SolvencyAssessment | None = None
    if is_mainnet(network):
        if pool is None or bond is None or audit_rate is None:
            raise PoolInsolventError(
                "minting to mainnet requires the pool, the bond and the audit "
                "rate, so solvency can be checked before real value is at risk"
            )
        if bond.denomination is BondDenomination.CREDITS:
            raise UnsafeCollateralError(
                "the bond is denominated in the credits it secures. A dump "
                "moves the price of that collateral, so it is worth least "
                "exactly when it is slashed. Post the bond in the quote asset."
            )
        per_claim = credits_per_fraudulent_claim
        if per_claim is None:
            # Absent a stated cap, assume the worst a single claim could be
            # worth: everything this claimant just had settled.
            per_claim = credits
        solvency = assess_pool_solvency(pool, audit_rate, per_claim, bond)
        if not solvency.solvent:
            raise PoolInsolventError(solvency.reason)

    return MintAuthorization(
        claimant_pubkey=claimant_pubkey,
        credits=credits,
        settled_claims=len(settled),
        escrowed_claims=len(escrowed),
        voided_claims=len(voided),
        network=network,
        solvency=solvency,
    )
