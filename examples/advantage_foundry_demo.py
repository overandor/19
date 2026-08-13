"""Print the five screens for one synthetic representative.

    python examples/advantage_foundry_demo.py

Everything here is fabricated data. The point is to show the shape of each
screen's payload, including the parts the product refuses to state confidently.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from advantage_foundry import (AdvantageFoundry, AttributionRecord, Contribution,
                               ContextResult, Counterfactual, Eligibility, Employee,
                               EvidenceClass, ExperimentContract, Lifecycle,
                               StrategyGenome, Territory)

DIMENSIONS = {
    "opportunity_realization": 0.74,
    "account_progression": 0.81,
    "follow_up_reliability": 0.63,
    "field_time_efficiency": 0.88,
    "data_quality": 0.91,
    "stakeholder_coverage": 0.58,
    "learning_adaptability": 0.79,
}


def territory(**kwargs) -> Territory:
    base = dict(territory_id="T-integrated", product="alpha", opportunity=1.0,
                maturity=1.0, resources=1.0, access_difficulty=1.2,
                territory_type="integrated", restrictions=[])
    base.update(kwargs)
    return Territory(**base)


def build() -> AdvantageFoundry:
    workflow_first = StrategyGenome(
        strategy_id="workflow-first-2.3",
        name="Contact operations before repeating physician outreach",
        varies=["stakeholder", "timing", "approved_content_sequence"],
        sequence=["Contact office operations",
                  "Identify the workflow owner",
                  "Confirm the blocking process",
                  "Deliver the approved operational material",
                  "Resume physician engagement after clarification"],
        eligibility=Eligibility(account_states=["stalled"], barriers=["workflow"],
                                territory_types=["integrated"],
                                min_qualifying_accounts=10, min_tenure_days=90,
                                forbidden_conditions=["medical_information_pending"]),
        stakeholder="office_manager", timing_window="morning", follow_up_hours=48,
        evidence=EvidenceClass.EXPERIMENTALLY_SUPPORTED, lifecycle=Lifecycle.SUPPORTED,
        expected_effect=0.14, effect_low=0.11, effect_high=0.16,
        expected_outcome="account progression",
        known_failure="Performs poorly when scientific questions remain unresolved",
    )
    commitments = StrategyGenome(
        strategy_id="commitments-1.0",
        name="Close open commitments before adding new visits",
        varies=["follow_up_interval", "administrative_execution"],
        sequence=["List unresolved commitments", "Complete the oldest eight",
                  "Only then schedule new visits"],
        eligibility=Eligibility(barriers=["workflow", "follow_up"]),
        evidence=EvidenceClass.EXPERIMENTALLY_SUPPORTED, lifecycle=Lifecycle.MONITORED,
        expected_effect=0.12, effect_low=0.09, effect_high=0.15,
        execution_cost_minutes=20, expected_outcome="account progression",
    )
    coordinator_first = StrategyGenome(
        strategy_id="coordinator-first-0.1",
        name="Test nurse-coordinator-first sequencing",
        varies=["stakeholder", "timing"],
        sequence=["Contact the nurse coordinator", "Confirm the testing workflow",
                  "Follow up with the physician within 72 hours"],
        eligibility=Eligibility(account_states=["stalled"], barriers=["workflow"],
                                min_qualifying_accounts=10, min_tenure_days=90),
        stakeholder="nurse_coordinator",
        evidence=EvidenceClass.PROBABLE_CONTRIBUTION, lifecycle=Lifecycle.LIMITED_TRIAL,
        expected_effect=0.15, effect_low=0.12, effect_high=0.21,
    )

    remote_follow_up = StrategyGenome(
        strategy_id="remote-follow-up-1.4",
        name="Replace two afternoon visits with remote follow-ups",
        varies=["channel", "route", "account_prioritization"],
        sequence=["Drop the two lowest-probability afternoon visits",
                  "Send the approved follow-up remotely",
                  "Reinvest the time in an access-ready account"],
        eligibility=Eligibility(barriers=["workflow", "follow_up"], min_tenure_days=90),
        channel="remote",
        evidence=EvidenceClass.PROBABLE_CONTRIBUTION, lifecycle=Lifecycle.EXPANDED,
        expected_effect=0.13, effect_low=0.10, effect_high=0.17,
        execution_cost_minutes=15,
        expected_outcome="field-time efficiency",
    )

    # Peers vary independently on each dimension, so the subject's profile has
    # real peaks and troughs rather than one flat percentile.
    population = [
        Employee(employee_id=f"peer-{i}", name=f"Peer {i}", territory=territory(),
                 tenure_days=700 + i, qualifying_accounts=12,
                 observed_result=60.0 + i * 2.5,
                 dimensions={key: round(value + ((i * 7 + offset * 13) % 11 - 5) * 0.03, 4)
                             for offset, (key, value) in enumerate(DIMENSIONS.items())})
        for i in range(24)
    ]
    subject = Employee(employee_id="jordan-lee", name="Jordan Lee", territory=territory(),
                       tenure_days=760, qualifying_accounts=14, observed_result=78.0,
                       dimensions=dict(DIMENSIONS))

    foundry = AdvantageFoundry(
        population=population + [subject],
        strategies=[workflow_first, commitments, remote_follow_up, coordinator_first])

    foundry.contracts["exp-coordinator"] = ExperimentContract(
        experiment_id="exp-coordinator",
        hypothesis="Early operational alignment increases the probability of a "
                   "meaningful physician discussion in workflow-blocked accounts.",
        what_is_known="Promising in 34 comparable workflow-blocked accounts.",
        what_is_unknown="Whether the effect transfers to territories with this "
                        "access profile.",
        primary_outcome="Account-state progression within 30 days",
        secondary_outcomes=["Response rate", "Time required", "Follow-up completion"],
        duration_days=14,
        variants={"control": commitments, "coordinator_first": coordinator_first},
    )

    foundry.outcomes["acct-241"] = AttributionRecord(
        outcome_id="acct-241",
        summary="Account 241 progressed",
        from_state="engaged",
        to_state="access-enabled",
        contributions=[
            Contribution("field_representative", 0.28, "ran the sequence in order"),
            Contribution("market_access", 0.26, "resolved the reimbursement path"),
            Contribution("assigned_strategy", 0.15),
            Contribution("territory_conditions", 0.10),
        ],
        counterfactual=Counterfactual(observed=0.61, baseline=0.29, sample=140,
                                      confounders=["A formulary improvement"]),
        what_mattered="Reaching the nurse manager before repeating physician outreach",
        what_did_not_matter="The additional clinical material",
    )

    foundry.results["workflow-first-2.3"] = [
        ContextResult("integrated:workflow_blocked", 0.15, 60, "rep-a", "t-1", 0),
        ContextResult("integrated:workflow_blocked", 0.13, 55, "rep-b", "t-2", 1),
        ContextResult("independent:workflow_blocked", -0.02, 40, "rep-c", "t-3", 1),
    ]
    foundry.results["commitments-1.0"] = [
        ContextResult("all:follow_up", 0.12, 90, "rep-a", "t-1", 0),
        ContextResult("all:follow_up", 0.11, 80, "rep-d", "t-4", 1),
        ContextResult("rural:follow_up", 0.09, 45, "rep-e", "t-5", 1),
    ]
    foundry.results["coordinator-first-0.1"] = [
        ContextResult("integrated:workflow_blocked", 0.16, 34, "rep-a", "t-1", 1),
    ]
    return foundry


CONTEXT = {
    "account_state": "stalled",
    "barrier": "workflow",
    "account_ref": "241",
    "conditions": [],
    "market_stability": 0.7,
    "evidence_density": 0.6,
    "compliance_risk": "low",
}


def show(title: str, payload) -> None:
    print(f"\n{'=' * 68}\n{title}\n{'=' * 68}")
    print(json.dumps(payload, indent=2, default=str))


def main() -> None:
    foundry = build()
    show("1 · MY EDGE", foundry.my_edge("jordan-lee", CONTEXT))
    show("2 · TODAY", foundry.today("jordan-lee", CONTEXT))
    show("3 · EXPERIMENT", foundry.experiment("exp-coordinator", day_index=6,
                                              telemetry={"variant_progression": 0.44,
                                                         "control_progression": 0.40}))
    show("4 · WHY IT WORKED", foundry.why_it_worked("acct-241", similar_accounts=3))
    show("5 · STRATEGY PORTFOLIO", foundry.strategy_portfolio(
        candidate_contexts=["integrated:workflow_blocked", "all:follow_up",
                            "rural:follow_up"]))


if __name__ == "__main__":
    main()
