# Memory Credit Daemon (v0, devnet/localnet only)

Metering daemon that turns "this run reused state instead of recomputing
it cold" into signed receipts, an append-only credit ledger, and
(optionally) a devnet/localnet SPL token balance.

See [`docs/MEMORY_CREDIT_DAEMON.md`](../docs/MEMORY_CREDIT_DAEMON.md) for
scope, design rationale, and what's tested offline vs. what needs a
networked machine to run against devnet/localnet. Short version: no
mainnet path exists in this code, and the token is a verifiable receipt
format, not a financial instrument.

```bash
python -m memory_credit_daemon.cli record "cache hit" 12.0 1.5
python -m memory_credit_daemon.cli balance
python -m memory_credit_daemon.cli verify
python -m memory_credit_daemon.cli mint http://127.0.0.1:8899  # localnet/devnet only
```
