# proof_of_avoided_work

Falsifiable metering for compute-reuse claims.

`memory_credit_daemon/` signs a claim that reused state avoided a cold
recompute. The signature proves who said it; nothing proved the saving,
and the claimant supplied the baseline the payout is computed from. This
package supplies the missing half.

- `commitments.py` — pin a claim to a re-executable unit of work.
- `oracle.py` — take the baseline away from the claimant; price against
  measured cold costs, at the robust centre rather than the tail.
- `audit.py` — commit-reveal sampling that no one can steer in advance or
  dispute afterwards, plus the fraud proofs re-execution yields.
- `economics.py` — solve for an audit rate that makes fraud negative-EV
  without re-executing everything. Bonds buy down audit cost.
- `settlement.py` — escrow, slash, and release only what survived; the
  bridge back to the credit daemon's ledger.

```bash
python -m proof_of_avoided_work plan       # solve for an audit rate
python -m proof_of_avoided_work simulate   # honest vs. cheating claimants
```

Protocol, threat model, economics, and an explicit list of what is *not*
solved: `docs/PROOF_OF_AVOIDED_WORK.md`.
