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
    DeterrenceParams,
    InfeasibleDeterrenceError,
    detection_probability,
    expected_value_of_fraud,
    minimum_audit_rate,
    plan_audit,
    required_bond,
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
    "ClaimRejected",
    "ClaimState",
    "DeterrenceParams",
    "DoubleClaimIndex",
    "EpochReport",
    "EscrowEntry",
    "FraudKind",
    "FraudProof",
    "InfeasibleDeterrenceError",
    "NoAdmissibleBaselineError",
    "ReexecutionResult",
    "ReuseClaim",
    "SeedCommitment",
    "SettlementEngine",
    "WorkCommitment",
    "audit_claim",
    "detection_probability",
    "expected_value_of_fraud",
    "is_selected",
    "minimum_audit_rate",
    "plan_audit",
    "required_bond",
    "select_claims",
    "selection_value",
    "sign_claim",
    "to_compute_reuse_event",
]
