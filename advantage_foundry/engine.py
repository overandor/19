"""The engine — one call per screen, and nothing the screens do not need.

Screen-to-call map (see ``docs/ADVANTAGE_FOUNDRY_UI_SPEC.md``):

===================  ==============================
My Edge              :meth:`AdvantageFoundry.my_edge`
Today                :meth:`AdvantageFoundry.today`
Experiment           :meth:`AdvantageFoundry.experiment`
Why It Worked        :meth:`AdvantageFoundry.why_it_worked`
Strategy Portfolio   :meth:`AdvantageFoundry.strategy_portfolio`
===================  ==============================
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from . import cohort as cohort_mod
from .attribution import AttributionRecord, separate_components
from .cohort import Cohort, Employee, match_cohort, place, score_employee
from .diffusion import (
    ContextResult,
    assess_decay,
    assess_portability,
    assess_repeatability,
    plan_diffusion,
)
from .experiments import ExperimentContract, check_stop
from .genome import StrategyGenome
from .governance import manager_safe
from .portfolio import EXPERIMENTAL, AllocationInputs, Assignment, allocate, select

#: Human-readable labels for the competitive score dimensions.
DIMENSION_LABELS: dict[str, str] = {
    "opportunity_realization": "Opportunity realization",
    "account_progression": "Account progression",
    "follow_up_reliability": "Follow-up reliability",
    "field_time_efficiency": "Field-time efficiency",
    "data_quality": "Data and CRM quality",
    "stakeholder_coverage": "Stakeholder coverage",
    "learning_adaptability": "Learning adaptability",
}

#: Constraints the employee cannot fix themselves. Diagnosing one of these
#: routes it to the manager instead of generating actions — this is the
#: anti-blame guarantee from the UI spec.
NOT_EMPLOYEE_CORRECTABLE = frozenset({"opportunity_realization"})


@dataclass
class AdvantageFoundry:
    """In-memory reference implementation of the five-screen engine."""

    population: list[Employee] = field(default_factory=list)
    strategies: list[StrategyGenome] = field(default_factory=list)
    contracts: dict[str, ExperimentContract] = field(default_factory=dict)
    outcomes: dict[str, AttributionRecord] = field(default_factory=dict)
    results: dict[str, list[ContextResult]] = field(default_factory=dict)

    # ── Lookup ───────────────────────────────────────────────────────────

    def employee(self, employee_id: str) -> Employee:
        for person in self.population:
            if person.employee_id == employee_id:
                return person
        raise KeyError(f"unknown employee: {employee_id}")

    def _cohort(self, subject: Employee) -> Cohort:
        return match_cohort(subject, self.population)

    # ── Screen 1: My Edge ────────────────────────────────────────────────

    def my_edge(self, employee_id: str, context: dict | None = None) -> dict:
        subject = self.employee(employee_id)
        peers = self._cohort(subject)
        position = place(subject, peers)
        score = score_employee(subject, peers)

        # The employee's plan is built from their weakest *correctable* dimension.
        # If something they cannot fix is weaker still, it is reported separately
        # and routed to the manager rather than turned into actions they cannot take.
        correctable_dims = [d for d in score.to_dict() if d not in NOT_EMPLOYEE_CORRECTABLE]
        constraint_key = score.constraint(correctable=correctable_dims)
        weakest_key = score.weakest()
        territory_constraint = (
            weakest_key if weakest_key in NOT_EMPLOYEE_CORRECTABLE else None)
        strength_key = score.strength()

        moves = {}
        if context is not None:
            for assignment in self.today(employee_id, context)["items"]:
                moves.setdefault(assignment["klass"], assignment["text"])

        projection = None
        if position["percentile_adjusted"] is not None and constraint_key:
            base = position["percentile_adjusted"]
            projection = (min(base + 10, 99), min(base + 16, 99))

        return {
            "position": {
                **position,
                "projection": projection,
            },
            "strength": DIMENSION_LABELS.get(strength_key or "", "—"),
            "constraint": {
                "label": DIMENSION_LABELS.get(constraint_key or "", "—"),
                "key": constraint_key,
                "correctable": constraint_key is not None,
            },
            "territory_constraint": None if territory_constraint is None else {
                "label": DIMENSION_LABELS[territory_constraint],
                "key": territory_constraint,
                "correctable": False,
                "note": "This is a territory condition, not something you can fix. "
                        "It has been routed to your manager.",
            },
            "scores": {DIMENSION_LABELS[k]: v for k, v in score.to_dict().items()},
            "moves": moves,
        }

    # ── Screen 2: Today ──────────────────────────────────────────────────

    def today(self, employee_id: str, context: dict) -> dict:
        subject = self.employee(employee_id)
        peers = self._cohort(subject)
        score = score_employee(subject, peers)
        correctable_dims = [d for d in score.to_dict() if d not in NOT_EMPLOYEE_CORRECTABLE]
        constraint_key = score.constraint(correctable=correctable_dims) or "account_progression"

        mix = allocate(AllocationInputs(
            tenure_days=subject.tenure_days,
            experiment_opt_in=subject.experiment_opt_in,
            market_stability=float(context.get("market_stability", 0.7)),
            evidence_density=float(context.get("evidence_density", 0.7)),
            compliance_risk=str(context.get("compliance_risk", "low")),
            launch_window=bool(context.get("launch_window", False)),
            reversible=bool(context.get("reversible", True)),
        ))

        enriched = {
            **context,
            "tenure_days": subject.tenure_days,
            "qualifying_accounts": subject.qualifying_accounts,
            "territory_type": subject.territory.territory_type,
        }
        assignments = select(
            self.strategies, enriched, mix,
            employee_id=employee_id,
            constraint=DIMENSION_LABELS.get(constraint_key, constraint_key),
        )

        return {
            "items": [self._row(a) for a in assignments],
            "portfolio_mix": dict(zip(("proven", "personalized", "experimental"),
                                      mix.as_percentages())),
            "mix_reason": mix.reason,
            "empty_state": (
                "No high-confidence work for today. Here are the commitments "
                "worth clearing." if not assignments else None
            ),
        }

    @staticmethod
    def _row(assignment: Assignment) -> dict:
        row = assignment.to_dict()
        row["text"] = assignment.strategy_name
        row["experimental"] = assignment.klass == EXPERIMENTAL
        return row

    # ── Screen 3: Experiment ─────────────────────────────────────────────

    def experiment(self, experiment_id: str, *, day_index: int = 0,
                   telemetry: dict | None = None) -> dict:
        contract = self.contracts[experiment_id]
        variant = next(name for name in sorted(contract.variants) if name != "control")
        genome = contract.variants[variant]

        stop = check_stop(contract, {**(telemetry or {}), "day_index": day_index})

        return {
            "hypothesis": contract.hypothesis,
            "what_is_known": contract.what_is_known,
            "what_is_unknown": contract.what_is_unknown,
            "selection_reason": (
                f"You have at least {contract.min_qualifying_accounts} qualifying "
                f"accounts and no excluded conditions."
            ),
            "sequence": list(genome.sequence),
            "duration_days": contract.duration_days,
            "day_index": day_index,
            "primary_outcome": contract.primary_outcome,
            "guardrails": list(contract.guardrails),
            "stop_conditions": [c.description for c in contract.stop_conditions],
            "risk": contract.risk,
            "evidence": genome.evidence.value,
            "evidence_display": genome.evidence.display,
            "can_stop": True,
            # Hard-coded, not configurable: visible peer variants contaminate the
            # comparison and turn a distributed test into one shared behaviour.
            "peer_variants_visible": False,
            "stopped": stop.should_stop,
            "stop_message": stop.message or None,
        }

    # ── Screen 4: Why It Worked ──────────────────────────────────────────

    def why_it_worked(self, outcome_id: str, *, similar_accounts: int = 0) -> dict:
        record = self.outcomes[outcome_id]
        payload = record.display()
        payload["next_move"] = (
            f"{similar_accounts} of your accounts match this pattern."
            if similar_accounts else None
        )
        payload["credit_ledger"] = {
            entry["actor"]: entry["band"] for entry in payload["contributors"]
        }
        return payload

    # ── Screen 5: Strategy Portfolio (manager) ───────────────────────────

    def strategy_portfolio(self, *, candidate_contexts: Sequence[str] = ()) -> dict:
        rows: list[dict] = []
        open_questions: list[str] = []

        for genome in self.strategies:
            results = self.results.get(genome.strategy_id, [])
            portability = assess_portability(results)
            repeatability = assess_repeatability(results)
            decay = assess_decay(results)
            plan = plan_diffusion(genome, portability, repeatability, decay,
                                  candidate_contexts=candidate_contexts)

            rows.append({
                "name": genome.name,
                "strategy_id": genome.strategy_id,
                "evidence": genome.evidence.value,
                "evidence_display": genome.evidence.display,
                "adjusted_lift": (genome.effect_low, genome.effect_high),
                "best_fit": portability.strong_fit,
                "known_failure": genome.known_failure,
                "portability": portability.portability.value,
                "decay": decay.value,
                "active_users": len({r.representative_id for r in results
                                     if r.representative_id}),
                "decision": plan.decision,
                "rationale": plan.rationale,
                "repeatability": repeatability.to_dict(),
            })

            if portability.untested:
                open_questions.append(
                    f"{genome.name}: untested in {', '.join(portability.untested[:3])}")

        # Negative and null results sort alongside winners, never below a fold.
        rows.sort(key=lambda r: {"retire": 0, "scale": 1, "hold": 2, "continue": 3}
                  .get(r["decision"], 4))

        payload = {
            "strategies": rows,
            "open_questions": open_questions,
            "separation": separate_components(list(self.outcomes.values())),
        }
        return manager_safe(payload)


__all__ = ["DIMENSION_LABELS", "AdvantageFoundry", "cohort_mod"]
