"""Advantage Foundry — a controlled market for organizational strategies.

Different credible strategies are assigned to comparable employees, executed
under controlled conditions, measured against fair baselines, causally
evaluated, and selectively redistributed to the contexts where they are most
likely to repeat.

The five things a user ever needs to understand: your position, your constraint,
your strategy, your result, what changes next. Everything below that line is
implementation detail and stays out of the interface.

See ``docs/ADVANTAGE_FOUNDRY.md`` and ``docs/ADVANTAGE_FOUNDRY_UI_SPEC.md``.
"""
from __future__ import annotations

from .attribution import (AttributionRecord, Band, Contribution, Counterfactual,
                          credit_ledger, separate_components)
from .cohort import (Cohort, CompetitiveScore, Employee, Territory, match_cohort,
                     place, score_employee)
from .compliance import (ComplianceViolation, Dimension, check_variation,
                         detect_gaming, enforce)
from .diffusion import (ContextResult, Decay, Portability, assess_decay,
                        assess_portability, assess_repeatability, plan_diffusion)
from .engine import AdvantageFoundry
from .experiments import ExperimentContract, StopCondition, allocate_variants, check_stop
from .genome import (Eligibility, EvidenceClass, Lifecycle, StrategyGenome,
                     advance, recombine)
from .governance import (GovernanceViolation, assert_not_evaluative, manager_safe,
                         override_is_signal, strip_experimental)
from .portfolio import Assignment, AllocationInputs, Mix, allocate, select

__all__ = [
    "AdvantageFoundry",
    "Assignment", "AllocationInputs", "Mix", "allocate", "select",
    "AttributionRecord", "Band", "Contribution", "Counterfactual",
    "credit_ledger", "separate_components",
    "Cohort", "CompetitiveScore", "Employee", "Territory", "match_cohort",
    "place", "score_employee",
    "ComplianceViolation", "Dimension", "check_variation", "detect_gaming", "enforce",
    "ContextResult", "Decay", "Portability", "assess_decay", "assess_portability",
    "assess_repeatability", "plan_diffusion",
    "Eligibility", "EvidenceClass", "Lifecycle", "StrategyGenome", "advance", "recombine",
    "ExperimentContract", "StopCondition", "allocate_variants", "check_stop",
    "GovernanceViolation", "assert_not_evaluative", "manager_safe",
    "override_is_signal", "strip_experimental",
]
