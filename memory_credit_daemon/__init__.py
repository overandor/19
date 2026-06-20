"""v0 metering daemon for recoverable-computational-state reuse.

Records signed receipts when cached/reusable state avoids a cold
recompute, accrues them into a credit ledger, and can mint a devnet or
localnet SPL token representing the accrued balance. See README.md in
this directory and docs/MEMORY_CREDIT_DAEMON.md for scope and limits —
in particular, there is no mainnet code path anywhere in this package.
"""
