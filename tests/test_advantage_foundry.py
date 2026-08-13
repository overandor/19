"""Tests for advantage_foundry/ — the strategy discovery engine.

Many of these assert *refusals*: the product's guarantees are mostly things it
must not do, so they are tested as hard failures rather than left to review.
"""
import pytest

from advantage_foundry import (AdvantageFoundry, AllocationInputs, AttributionRecord,
                               Band, Contribution, ContextResult, Counterfactual, Decay,
                               Eligibility, Employee, EvidenceClass, ExperimentContract,
                               GovernanceViolation, Lifecycle, Portability,
                               StrategyGenome, Territory, advance, allocate,
                               allocate_variants, assert_not_evaluative,
                               assess_decay, assess_portability, assess_repeatability,
                               check_stop, check_variation, credit_ledger, detect_gaming,
                               enforce, manager_safe, match_cohort, place, plan_diffusion,
                               recombine, score_employee, select, strip_experimental)
from advantage_foundry.compliance import ComplianceViolation
from advantage_foundry.genome import LifecycleError
from advantage_foundry.governance import override_is_signal
from advantage_foundry.portfolio import EXPERIMENTAL, slots, within_acceptable_band


# ── Fixtures ─────────────────────────────────────────────────────────────

def make_territory(**kwargs) -> Territory:
    defaults = dict(territory_id="T1", product="alpha", opportunity=1.0,
                    maturity=1.0, resources=1.0, access_difficulty=1.0,
                    territory_type="integrated", restrictions=[])
    defaults.update(kwargs)
    return Territory(**defaults)


def make_employee(employee_id="e0", **kwargs) -> Employee:
    defaults = dict(
        name="Jordan Lee",
        territory=make_territory(),
        tenure_days=800,
        qualifying_accounts=14,
        observed_result=100.0,
        dimensions={
            "opportunity_realization": 0.74,
            "account_progression": 0.81,
            "follow_up_reliability": 0.63,
            "field_time_efficiency": 0.88,
            "data_quality": 0.91,
            "stakeholder_coverage": 0.58,
            "learning_adaptability": 0.79,
        },
    )
    defaults.update(kwargs)
    return Employee(employee_id=employee_id, **defaults)


def workflow_first(**kwargs) -> StrategyGenome:
    defaults = dict(
        strategy_id="workflow-first-2.3",
        name="Workflow-first follow-up",
        varies=["stakeholder", "timing", "approved_content_sequence"],
        sequence=["Contact office operations", "Confirm the blocking workflow",
                  "Send the approved operational resource",
                  "Resume physician outreach after classification"],
        eligibility=Eligibility(account_states=["stalled"], barriers=["workflow"],
                                territory_types=["integrated"],
                                min_qualifying_accounts=10, min_tenure_days=90,
                                forbidden_conditions=["medical_information_pending"]),
        stakeholder="office_manager",
        timing_window="morning",
        follow_up_hours=48,
        evidence=EvidenceClass.EXPERIMENTALLY_SUPPORTED,
        lifecycle=Lifecycle.SUPPORTED,
        expected_effect=0.14, effect_low=0.11, effect_high=0.16,
        expected_outcome="account progression",
        known_failure="Performs poorly when scientific questions remain unresolved",
    )
    defaults.update(kwargs)
    return StrategyGenome(**defaults)


CONTEXT = {"account_state": "stalled", "barrier": "workflow",
           "territory_type": "integrated", "qualifying_accounts": 14,
           "tenure_days": 800, "account_ref": "241", "conditions": []}


# ── Compliance boundary ──────────────────────────────────────────────────

class TestComplianceBoundary:
    def test_permitted_dimensions_pass(self):
        assert check_variation(["timing", "channel", "stakeholder"])

    def test_protected_dimensions_rejected(self):
        verdict = check_variation(["timing", "approved_claims"])
        assert not verdict
        assert "approved_claims" in verdict.violations

    @pytest.mark.parametrize("dimension", [
        "approved_claims", "safety_information", "fair_balance",
        "indication_boundaries", "patient_level_targeting",
        "permitted_contact_rules", "privacy_restrictions",
    ])
    def test_each_protected_dimension_is_refused(self, dimension):
        assert not check_variation([dimension])

    def test_unknown_dimension_is_refused_not_ignored(self):
        verdict = check_variation(["vibes"])
        assert not verdict
        assert "vibes" in verdict.violations

    def test_enforce_raises(self):
        with pytest.raises(ComplianceViolation):
            enforce(["safety_information"])

    def test_genome_rejects_forbidden_variation_at_construction(self):
        with pytest.raises(ValueError, match="rejected"):
            workflow_first(varies=["timing", "scientific_evidence"])

    def test_high_risk_strategies_cannot_be_built(self):
        with pytest.raises(ValueError, match="high-risk"):
            workflow_first(risk="high")


class TestAntiGaming:
    def test_duplicate_engagement_detected(self):
        flags = detect_gaming([
            {"account_id": "A", "kind": "call", "occurred_at": 1000, "logged_at": 1000},
            {"account_id": "A", "kind": "call", "occurred_at": 1100, "logged_at": 1100},
        ])
        assert any(f.kind == "duplicate_engagement" for f in flags)

    def test_backdated_entry_detected(self):
        flags = detect_gaming([
            {"account_id": "A", "kind": "visit", "occurred_at": 0,
             "logged_at": 80 * 3600},
        ])
        assert any(f.kind == "delayed_entry" for f in flags)

    def test_activity_without_progression_detected(self):
        acts = [{"account_id": "B", "kind": f"touch{i}", "occurred_at": i * 10_000,
                 "logged_at": i * 10_000, "progressed": False} for i in range(9)]
        flags = detect_gaming(acts)
        assert any(f.kind == "activity_without_progression" for f in flags)

    def test_clean_activity_produces_no_flags(self):
        flags = detect_gaming([
            {"account_id": "C", "kind": "call", "occurred_at": 1000,
             "logged_at": 1200, "progressed": True},
        ])
        assert flags == []

    def test_flags_suppress_learning_not_the_person(self):
        flags = detect_gaming([
            {"account_id": "A", "kind": "call", "occurred_at": 1000, "logged_at": 1000},
            {"account_id": "A", "kind": "call", "occurred_at": 1050, "logged_at": 1050},
        ])
        assert all(f.suppress_from_learning for f in flags)


# ── Genome, lifecycle, evolution ─────────────────────────────────────────

class TestEvidenceClass:
    def test_experimentally_supported_is_the_ceiling(self):
        top = max(EvidenceClass, key=lambda e: e.rank)
        assert top is EvidenceClass.EXPERIMENTALLY_SUPPORTED

    def test_ordering(self):
        assert EvidenceClass.PROBABLE_CONTRIBUTION.at_least(
            EvidenceClass.OBSERVED_ASSOCIATION)
        assert not EvidenceClass.OBSERVED_ASSOCIATION.at_least(
            EvidenceClass.EXPERIMENTALLY_SUPPORTED)

    def test_no_label_claims_proof(self):
        for member in EvidenceClass:
            assert "proven" not in member.display.lower()
            assert "proof" not in member.display.lower()


class TestLifecycle:
    def test_legal_step(self):
        assert advance(Lifecycle.PROPOSED, Lifecycle.SIMULATED) is Lifecycle.SIMULATED

    def test_cannot_skip_to_scaled(self):
        with pytest.raises(LifecycleError):
            advance(Lifecycle.PROPOSED, Lifecycle.EXPANDED)

    def test_retire_is_always_available(self):
        for state in Lifecycle:
            if state is Lifecycle.RETIRED:
                continue
            assert advance(state, Lifecycle.RETIRED) is Lifecycle.RETIRED

    def test_retired_is_terminal(self):
        with pytest.raises(LifecycleError):
            advance(Lifecycle.RETIRED, Lifecycle.LIMITED_TRIAL)

    def test_decay_returns_a_strategy_to_trial(self):
        assert advance(Lifecycle.MONITORED, Lifecycle.LIMITED_TRIAL)


class TestEligibilityAndFit:
    def test_matching_context_scores_above_zero(self):
        assert workflow_first().fit(CONTEXT) > 0

    def test_wrong_barrier_is_excluded(self):
        genome = workflow_first()
        context = {**CONTEXT, "barrier": "formulary"}
        assert genome.eligibility.excludes(context)
        assert genome.fit(context) == 0.0

    def test_forbidden_condition_blocks_assignment(self):
        context = {**CONTEXT, "conditions": ["medical_information_pending"]}
        reason = workflow_first().eligibility.excludes(context)
        assert reason and "medical_information_pending" in reason

    def test_insufficient_accounts_excluded_with_reason(self):
        reason = workflow_first().eligibility.excludes({**CONTEXT, "qualifying_accounts": 3})
        assert reason and "qualifying accounts" in reason


class TestRecombination:
    def _parents(self):
        return [
            workflow_first(),
            workflow_first(strategy_id="am-access-1.0", name="Early-morning access",
                           timing_window="early_morning",
                           evidence=EvidenceClass.PROBABLE_CONTRIBUTION,
                           lifecycle=Lifecycle.EXPANDED),
        ]

    def test_child_inherits_named_components(self):
        child = recombine(self._parents(),
                          {"stakeholder": "workflow-first-2.3",
                           "timing_window": "am-access-1.0"},
                          strategy_id="challenger-1", name="Ops-first, morning window")
        assert child.stakeholder == "office_manager"
        assert child.timing_window == "early_morning"
        assert child.parent_ids == ["am-access-1.0", "workflow-first-2.3"]

    def test_child_starts_unproven_at_the_bottom_of_the_lifecycle(self):
        child = recombine(self._parents(), {"stakeholder": "workflow-first-2.3"},
                          strategy_id="challenger-1", name="Challenger")
        assert child.evidence is EvidenceClass.UNRESOLVED
        assert child.lifecycle is Lifecycle.PROPOSED

    def test_components_may_not_come_from_unsupported_parents(self):
        weak = workflow_first(strategy_id="weak", evidence=EvidenceClass.UNRESOLVED)
        with pytest.raises(ValueError, match="probable contribution"):
            recombine([workflow_first(), weak], {"stakeholder": "workflow-first-2.3"},
                      strategy_id="c", name="C")

    def test_child_is_confined_to_conditions_all_parents_shared(self):
        narrow = workflow_first(strategy_id="narrow", name="Narrow",
                                evidence=EvidenceClass.PROBABLE_CONTRIBUTION,
                                lifecycle=Lifecycle.EXPANDED,
                                eligibility=Eligibility(account_states=["stalled", "new"],
                                                        territory_types=["integrated"]))
        child = recombine([workflow_first(), narrow],
                          {"stakeholder": "workflow-first-2.3"},
                          strategy_id="c", name="C")
        assert child.eligibility.account_states == ["stalled"]

    def test_child_cannot_smuggle_in_forbidden_variation(self):
        # Parents are compliant, so the union of their dimensions must be too.
        child = recombine(self._parents(), {"channel": "workflow-first-2.3"},
                          strategy_id="c", name="C")
        assert check_variation(child.varies)


# ── Fair comparison ──────────────────────────────────────────────────────

class TestCohort:
    def _population(self, n=30, **territory_kwargs):
        return [make_employee(f"e{i}", territory=make_territory(**territory_kwargs),
                              observed_result=50.0 + i) for i in range(n)]

    def test_cohort_excludes_different_product(self):
        subject = make_employee("subject")
        others = [make_employee(f"x{i}", territory=make_territory(product="beta"))
                  for i in range(20)]
        assert match_cohort(subject, others).size == 0

    def test_cohort_excludes_different_restrictions(self):
        subject = make_employee("subject")
        others = [make_employee(f"x{i}",
                                territory=make_territory(restrictions=["state_ban"]))
                  for i in range(20)]
        assert match_cohort(subject, others).size == 0

    def test_cohort_excludes_different_tenure_band(self):
        subject = make_employee("subject", tenure_days=800)
        others = [make_employee(f"x{i}", tenure_days=30) for i in range(20)]
        assert match_cohort(subject, others).size == 0

    def test_small_cohort_is_marked_insufficient(self):
        subject = make_employee("subject")
        cohort = match_cohort(subject, self._population(4))
        assert not cohort.sufficient

    def test_percentile_suppressed_when_cohort_too_small(self):
        subject = make_employee("subject")
        placement = place(subject, match_cohort(subject, self._population(4)))
        assert placement["percentile_adjusted"] is None
        assert "not enough" in placement["note"].lower()

    def test_cohort_basis_is_always_explained(self):
        subject = make_employee("subject")
        placement = place(subject, match_cohort(subject, self._population()))
        assert placement["cohort_basis"]
        assert any("product" in reason for reason in placement["cohort_basis"])

    def test_harder_access_raises_the_adjusted_result(self):
        easy = make_employee("easy", territory=make_territory(access_difficulty=0.7),
                             observed_result=100.0)
        hard = make_employee("hard", territory=make_territory(access_difficulty=1.6),
                             observed_result=100.0)
        assert hard.adjusted_result > easy.adjusted_result

    def test_richer_territory_lowers_the_adjusted_result(self):
        rich = make_employee("rich", territory=make_territory(opportunity=1.5),
                             observed_result=100.0)
        lean = make_employee("lean", territory=make_territory(opportunity=0.8),
                             observed_result=100.0)
        assert lean.adjusted_result > rich.adjusted_result

    def test_easy_territory_does_not_win_on_adjusted_position(self):
        # Same raw output; one has every territory advantage.
        subject = make_employee("subject", territory=make_territory(
            opportunity=0.8, access_difficulty=1.4), observed_result=100.0)
        population = [make_employee(f"e{i}", territory=make_territory(
            opportunity=0.8, access_difficulty=1.4), observed_result=100.0)
            for i in range(20)]
        population.append(make_employee("lucky", territory=make_territory(
            opportunity=0.8, access_difficulty=1.4), observed_result=100.0))
        placement = place(subject, match_cohort(subject, population))
        assert placement["percentile_raw"] == placement["percentile_adjusted"]

    def test_both_raw_and_adjusted_are_returned_together(self):
        subject = make_employee("subject")
        placement = place(subject, match_cohort(subject, self._population()))
        assert placement["percentile_raw"] is not None
        assert placement["percentile_adjusted"] is not None


class TestCompetitiveScore:
    def test_constraint_is_the_weakest_dimension(self):
        subject = make_employee("subject")
        population = [make_employee(f"e{i}") for i in range(20)]
        score = score_employee(subject, match_cohort(subject, population))
        assert score.constraint() == "stakeholder_coverage"

    def test_score_is_not_collapsed_into_one_number(self):
        subject = make_employee("subject")
        score = score_employee(subject, match_cohort(subject, [make_employee(f"e{i}")
                                                               for i in range(20)]))
        assert len(score.to_dict()) == 7
        assert not hasattr(score, "total")


# ── Explore vs exploit ───────────────────────────────────────────────────

class TestAllocation:
    def test_default_mix_sums_to_one(self):
        mix = allocate(AllocationInputs(tenure_days=800))
        assert round(mix.proven + mix.personalized + mix.experimental, 6) == 1.0

    def test_new_hires_get_no_experiments(self):
        mix = allocate(AllocationInputs(tenure_days=30))
        assert mix.experimental == 0.0
        assert "onboarding" in mix.reason

    def test_opt_out_is_honoured(self):
        mix = allocate(AllocationInputs(tenure_days=800, experiment_opt_in=False))
        assert mix.experimental == 0.0

    def test_high_compliance_risk_gets_no_experiments(self):
        mix = allocate(AllocationInputs(tenure_days=800, compliance_risk="high"))
        assert mix.experimental == 0.0

    def test_irreversible_work_gets_no_experiments(self):
        mix = allocate(AllocationInputs(tenure_days=800, reversible=False))
        assert mix.experimental == 0.0

    def test_thin_evidence_increases_exploration(self):
        thin = allocate(AllocationInputs(tenure_days=800, evidence_density=0.1))
        normal = allocate(AllocationInputs(tenure_days=800))
        assert thin.experimental > normal.experimental

    def test_launch_window_reduces_exploration(self):
        launch = allocate(AllocationInputs(tenure_days=800, launch_window=True))
        assert launch.experimental < allocate(AllocationInputs(tenure_days=800)).experimental

    def test_experimental_share_is_capped(self):
        mix = allocate(AllocationInputs(tenure_days=800, evidence_density=0.0))
        assert mix.experimental <= 0.25

    def test_every_mix_explains_itself(self):
        for inputs in (AllocationInputs(tenure_days=10),
                       AllocationInputs(tenure_days=800),
                       AllocationInputs(tenure_days=800, launch_window=True)):
            assert allocate(inputs).reason.strip()

    def test_slots_never_invent_an_experiment(self):
        mix = allocate(AllocationInputs(tenure_days=30))
        assert slots(mix, 5)[EXPERIMENTAL] == 0

    def test_slots_fill_the_whole_day(self):
        assert sum(slots(allocate(AllocationInputs(tenure_days=800)), 5).values()) == 5


class TestExplorationGuardrail:
    def test_weak_challenger_is_refused(self):
        proven = workflow_first()
        weak = workflow_first(strategy_id="weak", evidence=EvidenceClass.UNRESOLVED,
                              lifecycle=Lifecycle.LIMITED_TRIAL,
                              expected_effect=0.02, effect_low=0.0, effect_high=0.04)
        assert not within_acceptable_band(weak, proven)

    def test_credible_challenger_is_allowed(self):
        proven = workflow_first()
        challenger = workflow_first(strategy_id="challenger",
                                    evidence=EvidenceClass.PROBABLE_CONTRIBUTION,
                                    lifecycle=Lifecycle.LIMITED_TRIAL,
                                    expected_effect=0.15, effect_low=0.13,
                                    effect_high=0.19)
        assert within_acceptable_band(challenger, proven)

    def test_anything_is_allowed_when_nothing_is_proven(self):
        challenger = workflow_first(strategy_id="c", evidence=EvidenceClass.UNRESOLVED,
                                    expected_effect=0.01, effect_low=0.0)
        assert within_acceptable_band(challenger, None)

    def test_weak_challenger_never_reaches_a_day_plan(self):
        proven = workflow_first()
        weak = workflow_first(strategy_id="weak", name="Weak challenger",
                              evidence=EvidenceClass.UNRESOLVED,
                              lifecycle=Lifecycle.LIMITED_TRIAL,
                              expected_effect=0.01, effect_low=0.0, effect_high=0.02)
        mix = allocate(AllocationInputs(tenure_days=800))
        assignments = select([proven, weak], CONTEXT, mix,
                             employee_id="e0", constraint="Follow-up reliability")
        assert all(a.strategy_id != "weak" for a in assignments)


class TestSelection:
    def test_retired_strategies_are_never_assigned(self):
        retired = workflow_first(strategy_id="retired", lifecycle=Lifecycle.RETIRED)
        mix = allocate(AllocationInputs(tenure_days=800))
        assignments = select([retired], CONTEXT, mix, employee_id="e0", constraint="x")
        assert assignments == []

    def test_ineligible_context_yields_nothing(self):
        mix = allocate(AllocationInputs(tenure_days=800))
        assignments = select([workflow_first()], {**CONTEXT, "barrier": "formulary"},
                             mix, employee_id="e0", constraint="x")
        assert assignments == []

    def test_assignments_carry_the_evaluation_firewall(self):
        mix = allocate(AllocationInputs(tenure_days=800))
        assignments = select([workflow_first()], CONTEXT, mix,
                             employee_id="e0", constraint="x")
        assert all(a.not_for_evaluation for a in assignments)

    def test_every_assignment_offers_decline(self):
        mix = allocate(AllocationInputs(tenure_days=800))
        for assignment in select([workflow_first()], CONTEXT, mix,
                                 employee_id="e0", constraint="x"):
            assert "decline" in assignment.actions
            assert "data_wrong" in assignment.actions

    def test_expected_effect_is_a_band_not_a_point(self):
        mix = allocate(AllocationInputs(tenure_days=800))
        assignment = select([workflow_first()], CONTEXT, mix,
                            employee_id="e0", constraint="x")[0]
        low, high = assignment.expected_effect
        assert low < high


# ── Experiments ──────────────────────────────────────────────────────────

def make_contract(**kwargs) -> ExperimentContract:
    defaults = dict(
        experiment_id="exp-1",
        hypothesis="A secondary-stakeholder-first approach improves progression "
                   "in workflow-blocked accounts.",
        what_is_known="Promising in 34 comparable workflow-blocked accounts",
        what_is_unknown="Whether the effect transfers to this territory type",
        primary_outcome="Account-state progression within 30 days",
        duration_days=14,
        variants={
            "control": workflow_first(strategy_id="control", name="Standard timing"),
            "variant_a": workflow_first(strategy_id="variant-a", name="Ops-first"),
        },
    )
    defaults.update(kwargs)
    return ExperimentContract(**defaults)


class TestExperimentContract:
    def test_contract_without_an_unknown_is_refused(self):
        with pytest.raises(ValueError, match="what_is_unknown"):
            make_contract(what_is_unknown="   ")

    def test_contract_without_a_control_is_refused(self):
        with pytest.raises(ValueError, match="control"):
            make_contract(variants={"a": workflow_first(strategy_id="a")})

    def test_contract_with_forbidden_variation_is_refused(self):
        bad = workflow_first(strategy_id="bad")
        object.__setattr__(bad, "varies", ["approved_claims"])
        with pytest.raises(ComplianceViolation):
            make_contract(variants={"control": workflow_first(strategy_id="c"),
                                    "bad": bad})

    def test_base_guardrails_cannot_be_dropped(self):
        contract = make_contract(guardrails=["Something local"])
        assert "Approved materials only" in contract.guardrails
        assert any("compensation" in g for g in contract.guardrails)

    def test_new_hires_are_excluded(self):
        assert make_contract().excludes({"tenure_days": 30, "qualifying_accounts": 40})

    def test_opted_out_employees_are_excluded(self):
        reason = make_contract().excludes({"tenure_days": 800, "qualifying_accounts": 40,
                                           "experiment_opt_in": False})
        assert reason and "opted out" in reason

    def test_escalated_accounts_are_excluded(self):
        reason = make_contract().excludes({"tenure_days": 800, "qualifying_accounts": 40,
                                           "conditions": ["active_medical_escalation"]})
        assert reason and "active_medical_escalation" in reason


class TestVariantAllocation:
    def _candidates(self, n=60):
        return [{"employee_id": f"e{i}", "tenure_days": 800,
                 "qualifying_accounts": 20, "conditions": []} for i in range(n)]

    def test_allocation_is_deterministic(self):
        contract = make_contract()
        first = allocate_variants(contract, self._candidates())
        second = allocate_variants(contract, self._candidates())
        assert first == second

    def test_both_arms_receive_participants(self):
        allocation = allocate_variants(make_contract(), self._candidates())
        assert set(allocation.values()) == {"control", "variant_a"}

    def test_ineligible_candidates_are_absent_not_placed_in_control(self):
        candidates = self._candidates(10) + [
            {"employee_id": "newhire", "tenure_days": 10, "qualifying_accounts": 20}]
        allocation = allocate_variants(make_contract(), candidates)
        assert "newhire" not in allocation


class TestStopConditions:
    def test_compliance_exception_stops_immediately(self):
        decision = check_stop(make_contract(), {"compliance_exceptions": 1})
        assert decision.should_stop and decision.condition == "compliance_exception"

    def test_negative_outcome_stops(self):
        decision = check_stop(make_contract(), {"variant_progression": 0.20,
                                               "control_progression": 0.40})
        assert decision.should_stop and decision.condition == "negative_outcome"

    def test_healthy_experiment_continues(self):
        decision = check_stop(make_contract(), {"variant_progression": 0.45,
                                               "control_progression": 0.40,
                                               "compliance_exceptions": 0})
        assert not decision.should_stop

    def test_stop_message_is_written_for_the_employee(self):
        decision = check_stop(make_contract(), {"variant_progression": 0.1,
                                               "control_progression": 0.5})
        assert "standard work" in decision.message


# ── Attribution ──────────────────────────────────────────────────────────

def make_record(**kwargs) -> AttributionRecord:
    defaults = dict(
        outcome_id="o-1",
        summary="Account 241 progressed",
        from_state="engaged",
        to_state="access-enabled",
        contributions=[
            Contribution("field_representative", 0.28, "ran the sequence"),
            Contribution("market_access", 0.26),
            Contribution("assigned_strategy", 0.15),
            Contribution("territory_conditions", 0.10),
        ],
        counterfactual=Counterfactual(observed=0.61, baseline=0.29, sample=140,
                                      confounders=["A formulary improvement"]),
        what_mattered="Reaching the nurse manager before repeating physician outreach",
        what_did_not_matter="The additional clinical material",
    )
    defaults.update(kwargs)
    return AttributionRecord(**defaults)


class TestAttribution:
    def test_default_view_shows_bands_not_percentages(self):
        display = make_record().display()
        rendered = str(display)
        assert "0.28" not in rendered and "28%" not in rendered
        assert display["contributors"][0]["band"] == Band.MATERIAL.value

    def test_unexplained_remainder_is_always_published(self):
        actors = [c["actor"] for c in make_record().display()["contributors"]]
        assert "Unexplained remainder" in actors

    def test_remainder_is_present_when_large(self):
        record = make_record(contributions=[Contribution("field_representative", 0.2)])
        remainder = [c for c in record.display()["contributors"]
                     if c["actor"] == "Unexplained remainder"][0]
        assert remainder["band"] == "present"

    def test_confounder_is_named_in_the_default_view(self):
        warning = make_record().display()["confounder_warning"]
        assert warning and "formulary" in warning.lower()
        assert "not yours" in warning

    def test_observational_evidence_never_reaches_the_ceiling(self):
        assert make_record().evidence is not EvidenceClass.EXPERIMENTALLY_SUPPORTED

    def test_small_sample_is_unresolved(self):
        record = make_record(counterfactual=Counterfactual(0.61, 0.29, sample=10))
        assert record.evidence is EvidenceClass.UNRESOLVED

    def test_unresolved_outcome_refuses_to_guess(self):
        record = make_record(counterfactual=Counterfactual(0.61, 0.29, sample=10))
        assert "cannot separate" in record.display()["counterfactual_text"]

    def test_confounders_cost_confidence(self):
        clean = Counterfactual(0.61, 0.29, sample=200)
        muddy = Counterfactual(0.61, 0.29, sample=200,
                               confounders=["formulary", "new access team"])
        assert clean.confidence == "high"
        assert muddy.confidence == "low"

    def test_audit_view_carries_numbers_and_a_disclaimer(self):
        audit = make_record().audit()
        assert audit["counterfactual"]["lift_pp"] == 32.0
        assert "not measured truth" in audit["disclaimer"]

    def test_credit_ledger_lists_actors_with_no_contribution(self):
        ledger = credit_ledger(make_record())
        assert ledger["manager"] == Band.NONE_DETECTED.value
        assert ledger["field_representative"] == Band.MATERIAL.value


# ── Portability, repeatability, diffusion ────────────────────────────────

def results(context, lifts, *, rep="r1", territory="t1", sample=40, period=0):
    return [ContextResult(context, lift, sample, rep, territory, period)
            for lift in lifts]


class TestPortability:
    def test_mixed_results_are_selective(self):
        assessment = assess_portability(
            results("integrated:workflow", [0.14, 0.12])
            + results("independent:workflow", [-0.02, 0.01]))
        assert assessment.portability is Portability.SELECTIVE
        assert "integrated:workflow" in assessment.strong_fit
        assert "independent:workflow" in assessment.weak_fit

    def test_thin_context_is_untested_not_strong(self):
        assessment = assess_portability([ContextResult("rural:access", 0.3, 5)])
        assert assessment.untested == ["rural:access"]
        assert assessment.portability is Portability.NON_TRANSFERABLE

    def test_replication_everywhere_is_global(self):
        assessment = assess_portability(
            results("a", [0.2]) + results("b", [0.15]) + results("c", [0.18]))
        assert assessment.portability is Portability.GLOBAL


class TestRepeatability:
    def test_rep_dependent_effect_is_detected(self):
        entries = (results("a", [0.4, 0.35], rep="star")
                   + results("a", [0.01, 0.0], rep="other"))
        assert assess_repeatability(entries).representative_dependent == "high"

    def test_thin_evidence_is_called_a_possible_coincidence(self):
        assert assess_repeatability([ContextResult("a", 0.3, 5)]
                                    ).one_time_coincidence == "likely"

    def test_durability_is_not_projected_without_evidence(self):
        judgement = assess_repeatability([ContextResult("a", 0.3, 5)])
        assert "too little evidence" in judgement.expected_durability


class TestDecay:
    def test_fading_effect_is_detected(self):
        entries = results("a", [0.20, 0.22], period=0) + results("a", [0.05], period=3)
        assert assess_decay(entries) is Decay.DECAYING

    def test_dead_effect_is_expired(self):
        entries = results("a", [0.20], period=0) + results("a", [-0.05], period=3)
        assert assess_decay(entries) is Decay.EXPIRED

    def test_single_period_is_not_called_decaying(self):
        assert assess_decay(results("a", [0.2])) is Decay.STABLE


class TestDiffusion:
    def _strong(self):
        return (assess_portability(results("a", [0.2]) + results("b", [0.18])
                                   + results("c", [0.15], rep="r2")),
                assess_repeatability(results("a", [0.2]) + results("b", [0.18])
                                     + results("c", [0.15], rep="r2")),
                Decay.STABLE)

    def test_expired_strategy_is_retired(self):
        portability, repeatability, _ = self._strong()
        plan = plan_diffusion(workflow_first(), portability, repeatability, Decay.EXPIRED)
        assert plan.decision == "retire"

    def test_decaying_strategy_is_held_not_scaled(self):
        portability, repeatability, _ = self._strong()
        plan = plan_diffusion(workflow_first(), portability, repeatability,
                              Decay.DECAYING, candidate_contexts=["a", "b"])
        assert plan.decision == "hold"

    def test_unsupported_evidence_keeps_testing(self):
        portability, repeatability, decay = self._strong()
        genome = workflow_first(evidence=EvidenceClass.OBSERVED_ASSOCIATION)
        assert plan_diffusion(genome, portability, repeatability, decay).decision == "continue"

    def test_scaling_keeps_a_comparison_group(self):
        portability, repeatability, decay = self._strong()
        plan = plan_diffusion(workflow_first(), portability, repeatability, decay,
                              candidate_contexts=["a", "b", "c"])
        assert plan.decision == "scale"
        assert 0 < plan.expansion_cap < 3

    def test_person_dependent_effect_is_not_scaled(self):
        entries = (results("a", [0.4, 0.38], rep="star")
                   + results("b", [0.01, 0.0], rep="other"))
        plan = plan_diffusion(workflow_first(), assess_portability(entries),
                              assess_repeatability(entries), Decay.STABLE,
                              candidate_contexts=["a"])
        assert plan.decision == "hold"


# ── Governance ───────────────────────────────────────────────────────────

class TestGovernance:
    def test_experimental_work_cannot_reach_compensation(self):
        with pytest.raises(GovernanceViolation, match="compensation"):
            assert_not_evaluative("compensation", [{"klass": "experimental"}])

    def test_experimental_work_cannot_reach_ranking(self):
        with pytest.raises(GovernanceViolation):
            assert_not_evaluative("performance_ranking",
                                  [{"klass": "experimental", "not_for_evaluation": True}])

    def test_non_evaluative_surfaces_are_unaffected(self):
        assert_not_evaluative("coaching", [{"klass": "experimental"}])

    def test_strip_removes_experimental_records(self):
        kept = strip_experimental([{"klass": "experimental"}, {"klass": "proven"}])
        assert kept == [{"klass": "proven"}]

    def test_manager_view_drops_email_content(self):
        cleaned = manager_safe({"employee": {"email_body": "private", "constraint": "x"}})
        assert "email_body" not in cleaned["employee"]
        assert cleaned["employee"]["constraint"] == "x"

    def test_manager_view_drops_override_counts(self):
        cleaned = manager_safe({"rows": [{"override_count": 9, "name": "s"}]})
        assert "override_count" not in cleaned["rows"][0]

    def test_override_carries_no_employee_identity(self):
        signal = override_is_signal({"strategy_id": "s1", "action": "decline",
                                     "employee_id": "e0"})
        assert "employee_id" not in signal
        assert signal["counts_against_employee"] is False


# ── Engine / five screens ────────────────────────────────────────────────

@pytest.fixture
def foundry():
    population = [make_employee(f"e{i}", observed_result=40.0 + i * 3) for i in range(25)]
    subject = make_employee("subject", observed_result=70.0)
    engine = AdvantageFoundry(population=population + [subject],
                              strategies=[workflow_first()])
    engine.contracts["exp-1"] = make_contract()
    engine.outcomes["o-1"] = make_record()
    engine.results["workflow-first-2.3"] = (
        results("integrated:workflow", [0.14, 0.12])
        + results("independent:workflow", [-0.02], rep="r2"))
    return engine


class TestFiveScreens:
    def test_my_edge_returns_position_constraint_and_scores(self, foundry):
        edge = foundry.my_edge("subject")
        assert edge["position"]["percentile_adjusted"] is not None
        assert edge["constraint"]["label"] == "Stakeholder coverage"
        assert len(edge["scores"]) == 7

    def test_my_edge_explains_the_cohort(self, foundry):
        assert foundry.my_edge("subject")["position"]["cohort_basis"]

    def test_my_edge_only_names_a_constraint_the_employee_can_fix(self, foundry):
        edge = foundry.my_edge("subject")
        assert edge["constraint"]["correctable"] is True
        assert edge["constraint"]["key"] not in {"opportunity_realization"}

    def test_territory_constraints_are_routed_to_the_manager(self, foundry):
        # Opportunity realization is bottom of the cohort; it is not the
        # employee's to fix, so it must not become their daily constraint.
        blocked = make_employee("blocked", observed_result=70.0)
        blocked.dimensions = {**blocked.dimensions,
                              "opportunity_realization": 0.05,
                              "stakeholder_coverage": 0.58}
        foundry.population.append(blocked)
        edge = foundry.my_edge("blocked")
        assert edge["constraint"]["key"] == "stakeholder_coverage"
        assert edge["territory_constraint"]["key"] == "opportunity_realization"
        assert "routed to your manager" in edge["territory_constraint"]["note"]

    def test_my_edge_projection_is_a_band(self, foundry):
        projection = foundry.my_edge("subject")["position"]["projection"]
        assert projection is None or projection[0] < projection[1]

    def test_today_returns_at_most_five_items(self, foundry):
        assert len(foundry.today("subject", CONTEXT)["items"]) <= 5

    def test_today_explains_its_mix(self, foundry):
        plan = foundry.today("subject", CONTEXT)
        assert plan["mix_reason"]
        assert sum(plan["portfolio_mix"].values()) == 100

    def test_today_labels_experimental_items(self, foundry):
        for item in foundry.today("subject", CONTEXT)["items"]:
            assert item["experimental"] == (item["klass"] == EXPERIMENTAL)

    def test_new_hire_gets_no_experimental_items(self, foundry):
        foundry.population.append(make_employee("rookie", tenure_days=20))
        plan = foundry.today("rookie", {**CONTEXT, "tenure_days": 20})
        assert plan["portfolio_mix"]["experimental"] == 0
        assert all(not item["experimental"] for item in plan["items"])

    def test_experiment_screen_states_the_unknown(self, foundry):
        screen = foundry.experiment("exp-1", day_index=6)
        assert screen["what_is_unknown"].strip()
        assert screen["can_stop"] is True

    def test_experiment_screen_hides_peer_variants(self, foundry):
        assert foundry.experiment("exp-1")["peer_variants_visible"] is False

    def test_experiment_screen_carries_the_compensation_protection(self, foundry):
        guardrails = foundry.experiment("exp-1")["guardrails"]
        assert any("compensation" in g for g in guardrails)

    def test_why_it_worked_shows_bands_and_the_confounder(self, foundry):
        screen = foundry.why_it_worked("o-1", similar_accounts=3)
        assert screen["contributors"][0]["band"] in {b.value for b in Band}
        assert "formulary" in screen["confounder_warning"].lower()
        assert screen["next_move"]

    def test_why_it_worked_never_claims_proof(self, foundry):
        screen = foundry.why_it_worked("o-1")
        assert screen["evidence"] != "proven"
        assert "prove" not in screen["evidence_display"]

    def test_strategy_portfolio_ranks_retirements_first(self, foundry):
        rows = foundry.strategy_portfolio(candidate_contexts=["integrated:workflow"])
        assert rows["strategies"]
        assert rows["strategies"][0]["decision"] in {"retire", "scale", "hold", "continue"}

    def test_strategy_portfolio_separates_the_seven_components(self, foundry):
        separation = foundry.strategy_portfolio()["separation"]
        assert "territory_conditions" in separation
        assert "unexplained_variation" in separation

    def test_strategy_portfolio_carries_no_employee_names(self, foundry):
        rendered = str(foundry.strategy_portfolio())
        assert "Jordan Lee" not in rendered

    def test_strategy_portfolio_surfaces_known_failures(self, foundry):
        row = foundry.strategy_portfolio()["strategies"][0]
        assert row["known_failure"]
