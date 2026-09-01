"""The baseline oracle: where a cold-cost number is allowed to come from.

Baseline inflation is the cheapest attack on any avoided-work meter. If
the claimant supplies the counterfactual ("a cold run would have taken
600s"), the meter measures the claimant's imagination. So the baseline is
taken away from them entirely: credit is computed from an oracle
distribution of *measured* cold costs for the work class, and a claim's
own baseline hint is at most a ceiling on itself, never a source.

Three properties do the work:

* **Robust statistics.** The admissible bound is median + k*sigma_MAD, so
  moving it requires moving the median. A minority of poisoned samples
  cannot; a majority can, which is exactly why the next property exists.
* **Measurer quorum.** A distribution is only usable once enough distinct
  measurers have contributed. One actor cannot stand up a work class
  alone and then bill against it.
* **Signed snapshots.** The bound applied at settlement is published as a
  signed, hash-identified snapshot, so a disputed settlement can be
  recomputed later against the exact numbers that were in force.

Samples are not a separate trust assumption: the audit loop in `audit.py`
re-executes claims cold and feeds those timings back here, so the honest
work an auditor already has to do *is* the measurement programme.
"""
from __future__ import annotations

import statistics
import time
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.signature import Signature

from .commitments import canonical_bytes, digest_object

# Scale factor making the MAD a consistent estimator of sigma for normal data.
MAD_TO_SIGMA = 1.4826

DEFAULT_MIN_SAMPLES = 5
DEFAULT_MIN_MEASURERS = 3
DEFAULT_SIGMA_K = 3.0


class NoAdmissibleBaselineError(Exception):
    """Raised when a work class cannot yet support a credited claim.

    Deliberately fail-closed: an unknown work class earns zero credit
    rather than whatever the claimant asserts.
    """


@dataclass(frozen=True)
class BaselineSample:
    work_class: str
    cold_cost_seconds: float
    measurer_pubkey: str
    measured_at: int = field(default_factory=lambda: int(time.time()))

    def __post_init__(self) -> None:
        if self.cold_cost_seconds <= 0:
            raise ValueError("cold_cost_seconds must be positive")


@dataclass(frozen=True)
class BaselineDistribution:
    work_class: str
    median_seconds: float
    mad_seconds: float
    sample_count: int
    distinct_measurers: int
    sigma_k: float

    @property
    def reference_seconds(self) -> float:
        """The cold cost a claim in this class is *paid* against.

        The robust centre, not the upper tail. Pricing at the tail would
        reward a claimant for asserting a large baseline, which is the
        attack this whole module exists to close.
        """
        return self.median_seconds

    @property
    def admissible_bound_seconds(self) -> float:
        """Above this, a claimed baseline is outside the observed spread.

        This is a detection threshold, never a price: exceeding it makes an
        inflated hint *attributable*, while pricing at `reference_seconds`
        already makes it *worthless*.
        """
        return self.median_seconds + self.sigma_k * MAD_TO_SIGMA * self.mad_seconds

    def digest(self) -> str:
        return digest_object(asdict(self))


@dataclass(frozen=True)
class AdmissibleBaseline:
    """The baseline actually used to price a claim, and how it was reached.

    `seconds` is what the claim is credited against. `reference_seconds` is
    the class's robust centre — the ceiling on `seconds`. `bound_seconds`
    is the inflation-detection threshold, which is higher and is never a
    price.
    """

    work_class: str
    seconds: float
    reference_seconds: float
    bound_seconds: float
    hint_ignored: bool
    distribution_digest: str

    @property
    def exceeded_bound(self) -> bool:
        """True when the hint was not merely optimistic but out of range."""
        return self.hint_ignored and self.seconds < self.bound_seconds


@dataclass(frozen=True)
class SignedSnapshot:
    """A point-in-time, signed publication of every usable distribution."""

    distributions: Dict[str, BaselineDistribution]
    created_at: int
    signer_pubkey: str
    signature: str

    def body(self) -> bytes:
        return canonical_bytes(
            {
                "distributions": {
                    k: asdict(v) for k, v in sorted(self.distributions.items())
                },
                "created_at": self.created_at,
                "signer_pubkey": self.signer_pubkey,
            }
        )

    @property
    def snapshot_id(self) -> str:
        return digest_object({"body": self.body().decode("utf-8")})

    def verify(self) -> bool:
        try:
            sig = Signature.from_string(self.signature)
            pubkey = Pubkey.from_string(self.signer_pubkey)
        except ValueError:
            return False
        return sig.verify(pubkey, self.body())


class BaselineOracle:
    def __init__(
        self,
        min_samples: int = DEFAULT_MIN_SAMPLES,
        min_measurers: int = DEFAULT_MIN_MEASURERS,
        sigma_k: float = DEFAULT_SIGMA_K,
    ) -> None:
        if min_samples < 1 or min_measurers < 1:
            raise ValueError("quorum thresholds must be >= 1")
        if sigma_k < 0:
            raise ValueError("sigma_k must be non-negative")
        self.min_samples = min_samples
        self.min_measurers = min_measurers
        self.sigma_k = sigma_k
        self._samples: Dict[str, List[BaselineSample]] = {}

    def add_sample(self, sample: BaselineSample) -> None:
        self._samples.setdefault(sample.work_class, []).append(sample)

    def observe(
        self, work_class: str, cold_cost_seconds: float, measurer_pubkey: str
    ) -> BaselineSample:
        sample = BaselineSample(work_class, cold_cost_seconds, measurer_pubkey)
        self.add_sample(sample)
        return sample

    def samples(self, work_class: str) -> List[BaselineSample]:
        return list(self._samples.get(work_class, ()))

    def distribution(self, work_class: str) -> Optional[BaselineDistribution]:
        samples = self._samples.get(work_class, [])
        measurers = {s.measurer_pubkey for s in samples}
        if len(samples) < self.min_samples or len(measurers) < self.min_measurers:
            return None
        costs = [s.cold_cost_seconds for s in samples]
        median = statistics.median(costs)
        mad = statistics.median([abs(c - median) for c in costs])
        return BaselineDistribution(
            work_class=work_class,
            median_seconds=median,
            mad_seconds=mad,
            sample_count=len(samples),
            distinct_measurers=len(measurers),
            sigma_k=self.sigma_k,
        )

    def admissible_baseline(
        self, work_class: str, claimed_seconds: Optional[float] = None
    ) -> AdmissibleBaseline:
        """Price a claim's counterfactual: `min(hint, reference)`.

        A claimant may talk their own baseline *down* and never up, so
        overstating it is worth exactly nothing — not merely capped. An
        earlier revision priced an over-large hint at the distribution's
        upper bound instead, and the adversarial simulation in `cli.py`
        promptly showed an inflater out-earning honest claimants by two
        thirds, because the bound sits well above the median that honest
        claimants are paid at. Pricing at the reference removes the
        incentive rather than bounding it.
        """
        dist = self.distribution(work_class)
        if dist is None:
            raise NoAdmissibleBaselineError(
                f"work class {work_class!r} has no quorum-backed baseline "
                f"(needs >= {self.min_samples} samples from "
                f">= {self.min_measurers} distinct measurers)"
            )
        reference = dist.reference_seconds
        if claimed_seconds is None:
            seconds, hint_ignored = reference, False
        else:
            seconds = min(claimed_seconds, reference)
            hint_ignored = claimed_seconds > reference
        return AdmissibleBaseline(
            work_class=work_class,
            seconds=seconds,
            reference_seconds=reference,
            bound_seconds=dist.admissible_bound_seconds,
            hint_ignored=hint_ignored,
            distribution_digest=dist.digest(),
        )

    def snapshot(self, signer: Keypair) -> SignedSnapshot:
        dists = {}
        for work_class in self._samples:
            dist = self.distribution(work_class)
            if dist is not None:
                dists[work_class] = dist
        unsigned = SignedSnapshot(
            distributions=dists,
            created_at=int(time.time()),
            signer_pubkey=str(signer.pubkey()),
            signature="",
        )
        signature = str(signer.sign_message(unsigned.body()))
        return SignedSnapshot(
            distributions=dists,
            created_at=unsigned.created_at,
            signer_pubkey=unsigned.signer_pubkey,
            signature=signature,
        )
