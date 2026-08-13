"""Attribution — what probably caused the outcome, said honestly.

Two commitments are load-bearing here:

* **Bands, not decimals.** The default view says "material contribution", never
  "27.43%". Point estimates exist, but they live in the audit payload and are
  labelled as model output.
* **The remainder is published.** Whatever the known actors do not explain is
  reported as unexplained. Distributing 100% of every outcome across the actors
  you happen to have data for is the fake-causality dashboard this product is
  defined against.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Sequence

from .genome import EvidenceClass


class Band(str, Enum):
    MATERIAL      = "material"
    MODERATE      = "moderate"
    LIMITED       = "limited"
    POSSIBLE      = "possible"
    NONE_DETECTED = "none detected"


#: Residual above this fraction is reported as "present" rather than "minimal".
UNEXPLAINED_THRESHOLD = 0.15


def band_for(share: float) -> Band:
    if share >= 0.25:
        return Band.MATERIAL
    if share >= 0.12:
        return Band.MODERATE
    if share >= 0.05:
        return Band.LIMITED
    if share > 0.0:
        return Band.POSSIBLE
    return Band.NONE_DETECTED


@dataclass
class Contribution:
    actor: str
    share: float                 # audit-only; never rendered by default
    note: str = ""

    @property
    def band(self) -> Band:
        return band_for(self.share)


@dataclass
class Counterfactual:
    """What probably would have happened without the strategy."""

    observed: float
    baseline: float              # matched comparison, not last quarter's number
    sample: int
    confounders: List[str] = field(default_factory=list)

    @property
    def lift_pp(self) -> float:
        return round((self.observed - self.baseline) * 100, 1)

    @property
    def confidence(self) -> str:
        """Confidence degrades with small samples and with named confounders.

        A concurrent formulary change does not merely add noise — it offers a
        complete alternative explanation, so it costs a confidence level rather
        than a rounding error.
        """
        if self.sample < 30:
            return "low"
        level = 2 if self.sample >= 120 else 1        # 2 = high, 1 = moderate
        level -= min(len(self.confounders), 2)
        return {2: "high", 1: "moderate"}.get(level, "low")

    @property
    def primary_confounder(self) -> Optional[str]:
        return self.confounders[0] if self.confounders else None


@dataclass
class AttributionRecord:
    outcome_id: str
    summary: str
    from_state: str
    to_state: str
    contributions: List[Contribution]
    counterfactual: Counterfactual
    what_mattered: str = ""
    what_did_not_matter: Optional[str] = None
    created_at: int = field(default_factory=lambda: int(time.time()))

    # ── Evidence ─────────────────────────────────────────────────────────

    @property
    def unexplained(self) -> float:
        return round(max(0.0, 1.0 - sum(c.share for c in self.contributions)), 4)

    @property
    def evidence(self) -> EvidenceClass:
        """The strongest label this record has actually earned.

        ``EXPERIMENTALLY_SUPPORTED`` is reserved for outcomes measured against a
        real allocated comparison group — it is granted by
        :func:`advantage_foundry.experiments.conclude`, not inferred from
        observational data here, however good that data looks.
        """
        if self.counterfactual.sample < 30:
            return EvidenceClass.UNRESOLVED
        if self.counterfactual.confidence == "low":
            return EvidenceClass.OBSERVED_ASSOCIATION
        if self.counterfactual.lift_pp <= 0:
            return EvidenceClass.UNRESOLVED
        return EvidenceClass.PROBABLE_CONTRIBUTION

    # ── Rendering ────────────────────────────────────────────────────────

    def display(self) -> Dict:
        """The default view. Bands and sentences — no shares, no decimals."""
        contributors = [
            {"actor": c.actor, "band": c.band.value, "note": c.note}
            for c in sorted(self.contributions, key=lambda c: c.share, reverse=True)
        ]
        contributors.append({
            "actor": "Unexplained remainder",
            "band": "present" if self.unexplained > UNEXPLAINED_THRESHOLD else "minimal",
            "note": "",
        })

        cf = self.counterfactual
        if self.evidence is EvidenceClass.UNRESOLVED:
            counterfactual_text = (
                "We cannot separate your contribution from what else moved in "
                "your territory this period."
            )
        else:
            counterfactual_text = (
                f"Comparable accounts progressed {round(cf.baseline * 100)}% of the "
                f"time. Estimated lift {cf.lift_pp:+.0f} points, "
                f"{cf.confidence} confidence."
            )

        return {
            "outcome_id": self.outcome_id,
            "summary": self.summary,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "evidence": self.evidence.value,
            "evidence_display": self.evidence.display,
            "contributors": contributors,
            "counterfactual_text": counterfactual_text,
            "confounder_warning": (
                f"{cf.primary_confounder} happened in the same window. "
                f"Some of this is not yours."
                if cf.primary_confounder else None
            ),
            "what_mattered": self.what_mattered,
            "what_did_not_matter": self.what_did_not_matter,
            "audit_available": True,
        }

    def audit(self) -> Dict:
        """Precise model output, explicitly labelled as such."""
        return {
            "outcome_id": self.outcome_id,
            "disclaimer": "Model output, not measured truth. Estimates carry "
                          "the assumptions of the matched comparison set.",
            "contributions": [asdict(c) for c in self.contributions],
            "unexplained_share": self.unexplained,
            "counterfactual": {
                "observed": self.counterfactual.observed,
                "baseline": self.counterfactual.baseline,
                "lift_pp": self.counterfactual.lift_pp,
                "sample": self.counterfactual.sample,
                "confidence": self.counterfactual.confidence,
                "confounders": list(self.counterfactual.confounders),
            },
        }


# ── Organizational credit ledger ─────────────────────────────────────────

LEDGER_ACTORS = (
    "field_representative",
    "market_access",
    "assigned_strategy",
    "manager",
    "territory_conditions",
    "external_market",
)


def credit_ledger(record: AttributionRecord) -> Dict[str, str]:
    """Roll an outcome up into the standing contributor categories.

    Actors with no measured contribution are listed as ``none detected`` rather
    than omitted: the absence of a market-access contribution is exactly the kind
    of claim a sales organization later argues about.
    """
    by_actor = {c.actor: c for c in record.contributions}
    ledger = {
        actor: (by_actor[actor].band.value if actor in by_actor else Band.NONE_DETECTED.value)
        for actor in LEDGER_ACTORS
    }
    ledger["unexplained_remainder"] = (
        "present" if record.unexplained > UNEXPLAINED_THRESHOLD else "minimal")
    return ledger


def separate_components(records: Sequence[AttributionRecord]) -> Dict[str, str]:
    """The manager's seven-way separation, aggregated across outcomes.

    This is what stops a manager promoting the person with the easiest territory:
    employee skill and territory conditions are never allowed to collapse into a
    single number.
    """
    totals: Dict[str, float] = {actor: 0.0 for actor in LEDGER_ACTORS}
    for record in records:
        for contribution in record.contributions:
            if contribution.actor in totals:
                totals[contribution.actor] += contribution.share

    count = max(len(records), 1)
    separated = {actor: band_for(total / count).value for actor, total in totals.items()}
    separated["unexplained_variation"] = band_for(
        sum(r.unexplained for r in records) / count).value
    return separated
