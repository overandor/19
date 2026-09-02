"""Command line for Proof of Avoided Work.

    python -m proof_of_avoided_work plan       # solve for an audit rate
    python -m proof_of_avoided_work simulate   # run honest vs. cheating claimants

`simulate` is the end-to-end demonstration: a fixed synthetic work class,
a mix of honest and dishonest claimants, and the settlement engine paying
only what survived audit. It is deterministic given `--seed`, so a run is
reproducible and its numbers can be checked by hand.
"""
from __future__ import annotations

import argparse
import hashlib
import random
import sys

from solders.keypair import Keypair

from .audit import ReexecutionResult, SeedCommitment
from .commitments import WorkCommitment, digest_bytes, sign_claim
from .economics import (
    AuditBudget,
    DeterrenceParams,
    detection_probability,
    plan_audit,
)
from .oracle import BaselineOracle
from .settlement import ClaimRejected, SettlementEngine

DEMO_WORK_CLASS = "demo.transform:v1"
DEMO_CODE_VERSION = "demo-1.0.0"


def _demo_cold_cost(input_digest: str) -> float:
    """Deterministic per-unit cold cost, ~8s with spread. Stands in for a
    real cold execution's timing without needing one."""
    slice_ = int(input_digest[:8], 16) / 0xFFFFFFFF
    return 6.0 + 4.0 * slice_


def _demo_output_digest(input_digest: str) -> str:
    return digest_bytes(("demo-output:" + input_digest).encode("utf-8"))


def _demo_reexecutor(commitment: WorkCommitment) -> ReexecutionResult:
    return ReexecutionResult(
        output_digest=_demo_output_digest(commitment.input_digest),
        cold_cost_seconds=_demo_cold_cost(commitment.input_digest),
    )


def _seeded_keypair(tag: str) -> Keypair:
    return Keypair.from_seed(hashlib.sha256(tag.encode("utf-8")).digest())


def cmd_plan(args: argparse.Namespace) -> int:
    params = DeterrenceParams(
        bond_credits=args.bond,
        max_gain_per_fraudulent_claim=args.gain,
        penalty_multiplier=args.penalty_multiplier,
        safety_margin=args.margin,
    )
    budget = AuditBudget(
        claims_per_epoch=args.claims,
        reexecution_cost_credits=args.reexec_cost,
        credited_value_per_epoch=args.credited_value,
        budget_fraction=args.budget_fraction,
    )
    plan = plan_audit(params, budget)
    print(f"deterrence floor : {plan.deterrence_floor:.4%} of claims")
    print(f"budget ceiling   : {plan.budget_ceiling:.4%} of claims")
    print(f"feasible         : {plan.feasible}")
    print(f"audit rate       : {plan.audit_rate:.4%}")
    print(f"audit cost       : {plan.audit_cost_credits:.2f} credits "
          f"({plan.cost_fraction_of_credited_value:.2%} of credited value)")
    for k in (1, 5, 20):
        p = detection_probability(plan.audit_rate, k)
        print(f"caught after {k:>2} fakes: {p:.2%}")
    print(plan.reason)
    return 0 if plan.feasible else 1


def cmd_simulate(args: argparse.Namespace) -> int:
    rng = random.Random(args.seed)
    epoch = 1

    oracle = BaselineOracle(min_samples=5, min_measurers=3)
    auditor = _seeded_keypair("auditor")

    # Seed the oracle from three independent measurers, as the quorum rule
    # requires; in production these samples come from audit re-executions.
    for measurer_tag in ("measurer-a", "measurer-b", "measurer-c"):
        measurer = str(_seeded_keypair(measurer_tag).pubkey())
        for _ in range(3):
            digest = digest_bytes(str(rng.random()).encode("utf-8"))
            oracle.observe(DEMO_WORK_CLASS, _demo_cold_cost(digest), measurer)

    engine = SettlementEngine(
        oracle=oracle,
        auditor_pubkey=str(auditor.pubkey()),
        credits_per_second_saved=1.0,
    )

    honest = [_seeded_keypair(f"honest-{i}") for i in range(args.honest)]
    cheats = [_seeded_keypair(f"cheat-{i}") for i in range(args.cheaters)]
    # Inflaters serve correct results but inflate the baseline hint. They
    # pass audit — nothing they did is disprovable — and gain nothing,
    # because the oracle, not the hint, prices the claim.
    inflaters = [_seeded_keypair(f"inflater-{i}") for i in range(args.inflaters)]
    for kp in honest + cheats + inflaters:
        engine.post_bond(str(kp.pubkey()), args.bond)

    submitted: dict[str, int] = {"honest": 0, "fraudulent": 0, "inflating": 0}
    rejected: list[str] = []

    for i in range(args.claims):
        actors = honest + cheats + inflaters
        actor = actors[i % len(actors)]
        cheating = actor in cheats
        inflating = actor in inflaters
        payload = f"unit-{i}".encode()
        commitment = WorkCommitment.over(
            DEMO_WORK_CLASS, payload, DEMO_CODE_VERSION, {"runtime": "demo"}
        )
        true_output = _demo_output_digest(commitment.input_digest)

        if cheating:
            # Phantom reuse: bill for a unit never actually computed, and
            # inflate the hinted baseline while you are at it.
            output_digest = digest_bytes(f"fabricated-{i}".encode())
            hint = 600.0
        elif inflating:
            output_digest = true_output
            hint = 600.0
        else:
            output_digest = true_output
            hint = None

        claim = sign_claim(
            commitment=commitment,
            output_digest=output_digest,
            actual_cost_seconds=0.25,
            epoch=epoch,
            signer=actor,
            claimed_baseline_seconds=hint,
        )
        bucket = "fraudulent" if cheating else "inflating" if inflating else "honest"
        try:
            engine.submit(claim)
            submitted[bucket] += 1
        except ClaimRejected as exc:
            rejected.append(f"{claim.claim_id[:8]}: {exc.reason}")

    seed_commitment = SeedCommitment(
        seed=hashlib.sha256(f"epoch-seed-{args.seed}".encode()).digest()
    )
    print(f"epoch seed commitment (published before claims): {seed_commitment.commitment}")
    seed = seed_commitment.reveal()

    report = engine.run_epoch(epoch, seed, args.audit_rate, _demo_reexecutor)

    print()
    print(f"claims submitted : {submitted['honest']} honest, "
          f"{submitted['fraudulent']} fraudulent, "
          f"{submitted['inflating']} baseline-inflating")
    if rejected:
        print(f"rejected at intake: {len(rejected)}")
    print(report.summary())
    print()
    by_kind: dict[str, int] = {}
    for proof in engine.fraud_proofs():
        by_kind[proof.kind.value] = by_kind.get(proof.kind.value, 0) + 1
    for kind, count in sorted(by_kind.items()):
        print(f"  fraud proofs [{kind}]: {count}")
    for proof in report.fraud_proofs[:3]:
        print(f"    e.g. claim {proof.claim_id[:8]} by "
              f"{proof.claimant_pubkey[:8]}…: {proof.detail}")
    print()
    for kp in honest:
        print(f"  honest {str(kp.pubkey())[:8]}…: "
              f"{engine.settled_credits(str(kp.pubkey())):.2f} credits settled, "
              f"bond {engine.bond(str(kp.pubkey())):.0f}")
    for kp in inflaters:
        print(f"  inflate {str(kp.pubkey())[:8]}…: "
              f"{engine.settled_credits(str(kp.pubkey())):.2f} credits settled "
              f"(hinted 600s/claim, priced at the oracle reference instead)")
    for kp in cheats:
        print(f"  cheat  {str(kp.pubkey())[:8]}…: "
              f"{engine.settled_credits(str(kp.pubkey())):.2f} credits settled, "
              f"bond {engine.bond(str(kp.pubkey())):.0f} "
              f"(slashed {engine.slashed(str(kp.pubkey())):.0f})")
    print()
    print(f"baseline samples added by this epoch's audits: {report.baseline_samples_added}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="proof_of_avoided_work",
        description="Falsifiable metering for compute-reuse claims.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_plan = sub.add_parser("plan", help="solve for a deterrence-feasible audit rate")
    p_plan.add_argument("--bond", type=float, default=1000.0)
    p_plan.add_argument("--gain", type=float, default=10.0,
                        help="max credits one fraudulent claim can extract")
    p_plan.add_argument("--penalty-multiplier", type=float, default=1.0)
    p_plan.add_argument("--margin", type=float, default=0.0)
    p_plan.add_argument("--claims", type=int, default=10_000)
    p_plan.add_argument("--reexec-cost", type=float, default=8.0,
                        help="credits burned re-executing one unit cold")
    p_plan.add_argument("--credited-value", type=float, default=75_000.0)
    p_plan.add_argument("--budget-fraction", type=float, default=0.05)
    p_plan.set_defaults(func=cmd_plan)

    p_sim = sub.add_parser("simulate", help="run honest vs. cheating claimants")
    p_sim.add_argument("--claims", type=int, default=40)
    p_sim.add_argument("--honest", type=int, default=3)
    p_sim.add_argument("--cheaters", type=int, default=1)
    p_sim.add_argument("--inflaters", type=int, default=1)
    p_sim.add_argument("--bond", type=float, default=500.0)
    p_sim.add_argument("--audit-rate", type=float, default=0.25)
    p_sim.add_argument("--seed", type=int, default=7)
    p_sim.set_defaults(func=cmd_simulate)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
