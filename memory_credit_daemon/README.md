# Memory Credit Daemon (v0, devnet/localnet by default)

Metering daemon that turns "this run reused state instead of recomputing
it cold" into signed receipts, an append-only credit ledger, and
(optionally) a devnet/localnet SPL token balance.

See [`docs/MEMORY_CREDIT_DAEMON.md`](../docs/MEMORY_CREDIT_DAEMON.md) for
scope, design rationale, and what's tested offline vs. what needs a
networked machine to run against devnet/localnet.

Short version: the token is a verifiable receipt format, not a financial
instrument. Mainnet is refused by default and reachable only via an
explicit `allow_mainnet=True`, and minting there additionally requires a
`proof_of_avoided_work` `MintAuthorization` — issued only for audited,
settled credits against a pool shown to be non-drainable. Two of the
prerequisites the design doc names (an audited integration, and legal
review of what the token represents) remain **unmet**, so the fact that
the code path exists is not a statement that it is ready.

```bash
python -m memory_credit_daemon.cli record "cache hit" 12.0 1.5
python -m memory_credit_daemon.cli balance
python -m memory_credit_daemon.cli verify
python -m memory_credit_daemon.cli mint http://127.0.0.1:8899  # localnet/devnet only
```
