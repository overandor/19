# Memory Credit Daemon (v0, devnet/localnet only)

`memory_credit_daemon/` is a small prototype for one narrow idea: when a
research run reuses previously-computed state instead of recomputing it
cold, that avoided cost can be recorded as a signed receipt, accrued into
a ledger, and — only if you choose to — minted as a devnet or localnet
SPL token so the balance is visible outside the ledger file itself.

## Scope, in one paragraph

This is a metering and bookkeeping tool, not a financial product. There
is no mainnet code path anywhere in this package, no price discovery, no
liquidity pool, and no claim that the resulting token has, or should
have, real value. `solana_submit.make_client()` raises
`MainnetRpcBlockedError` for any RPC URL containing `"mainnet"`, so this
isn't just a documentation promise — it's enforced in code. Treating the
credits token as tradeable or speculative is explicitly out of scope;
see "Why a token at all" below for why it exists at all.

This complements, and does not relax, the repository's existing
research-only constraints (`safety_policies/research_only_policy.md`):
nothing here places trades, and the credits ledger has no relationship
to the signal-research pipeline's outputs.

## Components

- `receipts.py` — `ComputeReuseEvent` (a baseline cost vs. an actual
  cost) and `Receipt` (an ed25519-signed, hash-linked attestation of the
  resulting credits). Signing uses a `solders.keypair.Keypair`.
- `ledger.py` — `CreditLedger`: an append-only, hash-chained JSON store
  of receipts. `verify_chain()` re-checks every signature and every
  `prev_hash` link, so a receipt edited after the fact is detectable.
- `solana_credits.py` — builds the standard SPL Token Program
  instructions (create-account, initialize-mint, create-ATA, mint-to)
  and assembles/signs a `Transaction` from them. Pure construction, no
  network calls — this is what the test suite exercises.
- `solana_submit.py` — the live path: fetches rent and a recent
  blockhash from an RPC endpoint, submits the transaction, and carries
  the mainnet guard described above.
- `cli.py` — `python -m memory_credit_daemon.cli {record,balance,verify,mint}`.

## Why a token at all

The point isn't to give the credits a market — it's to make "this
process saved N seconds of recompute" a portable, verifiable artifact
instead of a number trapped in one process's local ledger file. An SPL
balance is just a more interoperable receipt format. If that distinction
collapses in practice — if the balance starts getting treated as
tradeable rather than as a verifiable log of compute reuse — that's a
sign to stop, not a sign the next step is a liquidity pool.

## Why the standard SPL Token Program instead of a custom Anchor program

A credits mint needs exactly three things: create a mint account,
initialize it, and mint to a destination. The standard, already-deployed
SPL Token Program (`spl.token.instructions`, bundled with the `solana`
pip package) provides all three directly, so a custom Anchor program
adds Rust/Anchor build tooling without adding capability. (It was also
not possible to compile or test a custom Anchor program in the sandbox
this was built in — `cargo` couldn't reach `crates.io` from there — so
even setting the capability question aside, only the dependency-free
path could actually be verified before being committed.)

## What's tested here vs. what needs your own machine

`tests/test_memory_credit_daemon.py` runs fully offline and covers:

- receipt signing, verification, and tamper detection
- the ledger's hash chain, balance accrual, and persistence
- building and signing the create-mint + mint-to transaction
- the mainnet guard, for both blocked and allowed URLs

It does **not** call `solana_submit.mint_credits_onchain()`, because
doing so requires a reachable Solana RPC endpoint (devnet or a local
validator), and the sandbox this was built in has no route to either —
`api.devnet.solana.com` isn't in its network allowlist, and there's no
local validator running. To actually mint on devnet or localnet, run the
CLI from a machine that has one of those:

```bash
# devnet (get a keypair funded via `solana airdrop` first)
python -m memory_credit_daemon.cli mint https://api.devnet.solana.com

# or a local validator (`solana-test-validator`)
python -m memory_credit_daemon.cli mint http://127.0.0.1:8899
```

`mint` mints the signer's current ledger balance (or `--amount`, in base
units) to a freshly generated mint, using the daemon's own keypair
(`memory_credit_daemon/.data/daemon_keypair.json`, created on first use)
as both fee payer and mint authority.

## CLI walkthrough

```bash
python -m memory_credit_daemon.cli record "cache hit on focus ranker" 12.0 1.5
python -m memory_credit_daemon.cli record "warm reuse" 5.0 0.0
python -m memory_credit_daemon.cli balance   # -> 15.5
python -m memory_credit_daemon.cli verify    # -> ok: 2 receipts verified
```

`record` takes a description, a baseline (cold) cost in seconds, and the
actual cost incurred; credits default to 1 per second saved
(`--rate` to change that). Ledger and key paths default under
`memory_credit_daemon/.data/` and can be overridden with
`--ledger-path`/`--key-path`.

## Mainnet

Not in scope for this package. A real deployment would need an audited
program (or at minimum an audited integration), legal review of what the
token represents and who's liable for it, and a much harder answer to
"what happens when the credits/seconds-saved conversion rate is wrong"
than a v0 prototype can give. `make_client()` enforces this in code
rather than leaving it as a README warning.
