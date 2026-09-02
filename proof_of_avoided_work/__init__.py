"""Proof of Avoided Work — making a compute-reuse claim falsifiable.

`memory_credit_daemon` records signed claims that reused state avoided a
cold recompute. The signature proves authorship; nothing proved the
saving, and the claimant supplied the counterfactual, so the meter could
be inflated at will. This package supplies the missing half: commitments
that pin a claim to a re-executable unit, an oracle that owns the
baseline, randomized post-hoc audits that make fraud negative-EV without
re-executing everything, and settlement that pays only what survived.

See `docs/PROOF_OF_AVOIDED_WORK.md` for the protocol and its assumptions.
"""

from .audit import (
    AuditVerdict,
    DoubleClaimIndex,
    FraudKind,
    FraudProof,
    ReexecutionResult,
    SeedCommitment,
    audit_claim,
    is_selected,
    select_claims,
    selection_value,
)
from .commitments import ReuseClaim, WorkCommitment, sign_claim
from .economics import (
    AuditBudget,
    AuditPlan,
    Bond,
    BondDenomination,
    ConstantProductPool,
    DeterrenceParams,
    InfeasibleDeterrenceError,
    SolvencyAssessment,
    assess_pool_solvency,
    detection_probability,
    expected_value_of_fraud,
    minimum_audit_rate,
    plan_audit,
    required_bond,
    required_bond_for_pool,
    slash_value_quote,
)
from .minting import (
    MintAuthorization,
    PoolInsolventError,
    UnsafeCollateralError,
    UnverifiedCreditsError,
    authorize_mint,
    is_mainnet,
)
from .oracle import (
    BaselineOracle,
    BaselineSample,
    NoAdmissibleBaselineError,
)
from .settlement import (
    ClaimRejected,
    ClaimState,
    EpochReport,
    EscrowEntry,
    SettlementEngine,
    to_compute_reuse_event,
)

__all__ = [
    "AuditBudget",
    "AuditPlan",
    "AuditVerdict",
    "BaselineOracle",
    "BaselineSample",
    "Bond",
    "BondDenomination",
    "ClaimRejected",
    "ClaimState",
    "ConstantProductPool",
    "DeterrenceParams",
    "DoubleClaimIndex",
    "EpochReport",
    "EscrowEntry",
    "FraudKind",
    "FraudProof",
    "InfeasibleDeterrenceError",
    "MintAuthorization",
    "NoAdmissibleBaselineError",
    "PoolInsolventError",
    "ReexecutionResult",
    "ReuseClaim",
    "SeedCommitment",
    "SettlementEngine",
    "SolvencyAssessment",
    "UnsafeCollateralError",
    "UnverifiedCreditsError",
    "WorkCommitment",
    "assess_pool_solvency",
    "audit_claim",
    "authorize_mint",
    "detection_probability",
    "expected_value_of_fraud",
    "is_mainnet",
    "is_selected",
    "minimum_audit_rate",
    "plan_audit",
    "required_bond",
    "required_bond_for_pool",
    "select_claims",
    "selection_value",
    "sign_claim",
    "slash_value_quote",
    "to_compute_reuse_event",
]
