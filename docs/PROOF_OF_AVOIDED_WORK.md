# Proof of Avoided Work

## The hole this fills

`memory_credit_daemon/` records that reusing cached state avoided a cold
recompute, signs the record with ed25519, and accrues it into a
hash-chained ledger. Every cryptographic part of that works. The problem
is what it proves.

A signature proves *who said it*. The ledger's integrity proves *nobody
edited it afterwards*. Neither proves the saving happened, and the
number that decides the payout — `baseline_cost_seconds`, the cost of the
cold run that supposedly did not happen — is supplied by the party being
paid. Nothing in the pipeline can contradict it. A claimant who writes
`600.0` instead of `6.0` gets a hundred times the credits and produces a
ledger that verifies perfectly.

That is not a bug in the signing code. It is the counterfactual problem:
the quantity being metered is, by construction, a thing that did not
happen, and so leaves no trace to check against.

This package makes the claim falsifiable. It does not make it
self-proving — that is impossible for a counterfactual — but falsifiable
is enough, because a claim that can be disproved *sometimes* can be made
not worth faking *always*.

## Why this problem is worth solving

Reuse is already billed. Prompt caching, prefix caching, KV-cache reuse,
semantic caches and result memoization all show up as a discount on an
invoice: the provider says "this request hit cache, you pay less."
Whether that discount was real is unverifiable by the customer today, and
the provider is the only party holding the evidence. The same gap sits
under every proposal for a market in reused compute, where the seller is
paid for work they specifically did not do.

Existing verifiable-computation machinery does not close it. ZK proofs of
inference, optimistic fraud proofs and TEE attestation all answer "did
this computation run correctly?" The question here is the inverse — "was
this computation correctly *not* run, and what would it have cost?" — and
the second half of that has no cryptographic answer at all, because the
cost of an execution that did not occur is an empirical fact about a
counterfactual, not a property of a trace.

The inversion is also what makes it tractable. Proving work happened
requires machinery over the whole execution. Disproving a reuse claim
requires only re-running the unit and comparing digests, which is
ordinary computation an auditor can already do. So the problem moves out
of cryptography and into sampling and incentives — a much cheaper place
to be.

**Honest framing:** the above is a thesis about where value would come
from, not a validated market. Nobody has told this repository they will
pay for verified reuse metering. What follows is an engineering result —
a protocol, its economics, and a test suite that carries out the attacks
it claims to stop — not evidence of demand.

## Threat model

Four attacks, all of which the pre-existing daemon permits:

| Attack | What the claimant does | Cost to them today |
|---|---|---|
| **Baseline inflation** | Assert a cold cost far above reality | Nothing; it is a free multiplier |
| **Phantom reuse** | Bill for a unit never computed, or serve a wrong result | Nothing; no one checks the output |
| **Double claim** | Bill the same reuse repeatedly | Nothing; the ledger appends happily |
| **Forgery** | Sign as somebody else | Already prevented by ed25519 |

Out of scope, stated plainly: a claimant who genuinely computed the unit,
genuinely reused it, and genuinely reports both costs, but whose work was
worthless to the buyer. This meters reuse, not usefulness.

## The protocol

### 1. Commitments make a claim checkable — `commitments.py`

A `WorkCommitment` pins `(work_class, input_digest, code_version,
env_digest)`. A `ReuseClaim` binds a served `output_digest` and the cost
actually paid to that commitment, and signs the pair. The commitment is
what lets an auditor re-run *this exact unit* later, which is the only
ground truth available.

This requires the work class to be deterministic under its commitment.
Greedy decoding at a pinned model revision qualifies. Temperature
sampling without a recorded seed does not, and must not be metered here —
non-determinism makes an output mismatch unattributable, which destroys
the fraud proof. This is a real restriction on what can be metered, not a
detail.

### 2. The oracle owns the baseline — `oracle.py`

The claimant is removed from the pricing decision. Credit is computed
against a distribution of *measured* cold costs for the work class:

- **Priced at the robust centre.** A claim is paid against the median,
  never the upper tail. A hint from the claimant can only lower it —
  `min(hint, reference)` — so overstating a baseline is worth exactly
  nothing rather than merely capped.
- **Median/MAD, not mean/σ.** A minority of poisoned samples cannot move
  the reference.
- **Measurer quorum.** A distribution is unusable until enough *distinct*
  measurers have contributed, so one actor cannot stand up a work class
  and bill against it alone.
- **Fail closed.** An unknown work class earns zero, not whatever the
  claimant says.
- **Signed snapshots.** The numbers in force at settlement are published
  and hash-identified, so a disputed settlement can be recomputed.

An earlier revision of this module priced an over-large hint at the
distribution's *upper bound* rather than its median. The adversarial
simulation in `cli.py` immediately showed why that was wrong: an inflater
out-earned honest claimants by about two thirds, because the bound sits
well above the median honest claimants are paid at. Bounding an incentive
is not the same as removing it. `test_inflating_earns_no_more_than_not_hinting`
now pins the corrected behaviour.

### 3. Sampling that nobody can steer or dispute — `audit.py`

The auditor publishes `sha256(seed)` before the epoch opens and reveals
`seed` after it closes. Selection is
`HMAC(seed, claim.record_hash) < audit_rate`.

Before the reveal the seed is unknown, so a claimant cannot shape a claim
to land outside the audited set. After the reveal, selection is a pure
function of public values, so nobody has to take the auditor's word for
which claims were picked. Sampling keys off the signed `record_hash`
rather than a free-form id, so the selection input cannot be ground
without re-signing — and is useless to grind anyway while the seed is
still committed.

Selected claims are re-executed. A mismatch between the re-executed
digest and the served one, or a claimed cost that is not below the
observed cold cost, produces a fraud proof carrying the evidence needed
to re-derive it. Double claims and bad signatures are caught at intake,
where they cost nothing to detect and need no re-execution at all.

Re-execution also *measures a real cold cost*, and that timing is
precisely the sample the oracle needs. Auditing claims and maintaining
the baseline are the same activity, so the oracle needs no separate
trusted measurement programme.

### 4. Nothing is paid until it has survived — `settlement.py`

Claims land in escrow priced against the oracle and settle only after
their epoch's audit. A caught claimant is slashed *and* has every other
claim they escrowed that epoch voided, so the cost of being caught scales
with how much they were extracting.

## The economics — `economics.py`

Re-executing every claim costs about what the work cost, which is more
than the reuse saved. The way out is that claims need not be *checked*,
only *not worth faking*.

**Deterrence floor.** A claimant gaining `g` from a fake and forfeiting a
slash `S` when audited faces `EV = (1-p)g - pS`. Requiring `EV ≤ -mg`:

```
p_min = g(1 + m) / (g + S)
```

**Budget ceiling.** Auditing at rate `p` over `N` claims costs `pNc` for
a re-execution cost `c`. Holding that under a fraction `b` of credited
value `V`:

```
p_max = bV / (Nc)
```

A workable configuration needs `p_min ≤ p_max`. Since `V/N` is the
average credit per claim, the ceiling depends only on what a claim is
worth relative to checking it — while the floor falls as the bond rises.
**Bonds buy down audit cost.** That is the whole reason this is
affordable:

```
$ python -m proof_of_avoided_work plan
deterrence floor : 0.9901% of claims
budget ceiling   : 4.6875% of claims
feasible         : True
audit rate       : 0.9901%
audit cost       : 792.08 credits (1.06% of credited value)
```

A bond of 100× the per-claim gain makes fraud negative-EV while checking
one claim in a hundred, for about 1% of credited value. Repeated fraud
converges on certain detection — 100 fakes at that rate are caught with
probability 63% — so the only surviving strategy is a handful of fakes,
which is exactly what the bond is sized against.

Two honest caveats. The model assumes a risk-neutral claimant, a bond
genuinely at risk, and a known bound on `g` — the last supplied by the
oracle's reference, which is why the oracle is load-bearing for the
economics and not only for correctness. And the model deliberately
ignores the forfeiture of pending claims, which makes its rate
conservative: real deterrence is at least what the model says.

## What is solved, and what is not

**Solved, and tested:**

- Baseline inflation earns nothing (not merely capped).
- Phantom reuse is caught by re-execution and produces a re-derivable proof.
- Double claims are caught at intake for free.
- Audit selection is unpredictable in advance and reproducible afterwards.
- An audit rate can be solved for, and the configurations where none exists
  are reported rather than silently run.
- Only audited-and-survived claims can reach the credit ledger.

**Not solved, and load-bearing:**

- **Privacy.** Re-execution needs the input. For real workloads that means
  the auditor sees the customer's data. The natural resolution is that
  *the party being billed is the party that audits* — a customer already
  holds their own inputs, can re-execute at rate `p`, and needs no third
  party. That collapses the trusted-auditor and privacy problems together
  and is the most promising direction here, but this package does not
  implement it: `SettlementEngine` still takes a single `auditor_pubkey`.
- **A single auditor is trusted to actually re-execute.** Commit-reveal
  makes selection honest; nothing forces the auditor to do the work, or
  stops them colluding with a claimant. Multiple independent auditors with
  cross-checks, or the customer-as-auditor model above, are the obvious
  fixes and neither is built.
- **Oracle bootstrapping.** A new work class has no samples and so earns
  nothing until audits accumulate. Correct, and awkward: the first honest
  user of a new class is unpaid for a while.
- **Sybil measurers.** The quorum counts distinct keys, and keys are free.
  Real deployment needs the measurer set to be permissioned, staked, or
  otherwise costly, which is unaddressed here.
- **Determinism.** Non-deterministic work classes cannot be metered at
  all, which excludes a large share of real inference traffic.
- **Bonds are notional.** They are numbers in a dict. Making them real
  means custody, and custody means the legal and regulatory questions
  `docs/MEMORY_CREDIT_DAEMON.md` already declines to answer.

## Running it

```bash
python -m proof_of_avoided_work plan       # solve for an audit rate
python -m proof_of_avoided_work simulate   # honest vs. cheating claimants
pytest tests/test_proof_of_avoided_work.py
```

`simulate` runs honest claimants, a phantom-reuse cheater and a
baseline-inflater through one epoch. The cheater settles zero credits and
loses their bond; the inflater settles exactly what the honest claimants
do. It is deterministic given `--seed`.

## Scope

This inherits the repository's research-only constraints
(`safety_policies/research_only_policy.md`) and the credit daemon's
limits (`docs/MEMORY_CREDIT_DAEMON.md`): no mainnet path, no trading, no
claim that credits have or should have value. Bonds and slashing here are
bookkeeping in a Python object, not custody of anything.
