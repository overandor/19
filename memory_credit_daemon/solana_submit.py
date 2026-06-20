"""Live RPC submission for the credits mint — devnet/localnet only.

Everything in here requires a reachable Solana RPC endpoint, which this
sandbox's network allowlist does not provide (api.devnet.solana.com and
a local validator are both unreachable here). It is therefore exercised
by manual testing on a machine with network access, not by the test
suite — see docs/MEMORY_CREDIT_DAEMON.md. The instruction-building and
transaction-assembly it depends on (solana_credits.py) is fully unit
tested offline.

make_client() refuses any RPC URL containing "mainnet" so this module
has no path to mainnet-beta even by misconfiguration.
"""
from __future__ import annotations

from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from .solana_credits import (
    MINT_ACCOUNT_SPACE,
    build_create_mint_instructions,
    build_mint_to_instruction,
)
from .solana_credits import assemble_transaction as _assemble_transaction


class MainnetRpcBlockedError(RuntimeError):
    pass


def make_client(rpc_url: str) -> Client:
    if "mainnet" in rpc_url.lower():
        raise MainnetRpcBlockedError(
            f"Refusing to connect to {rpc_url!r}: this module only supports "
            "devnet/localnet endpoints. See docs/MEMORY_CREDIT_DAEMON.md."
        )
    return Client(rpc_url)


def mint_credits_onchain(
    rpc_url: str,
    authority: Keypair,
    mint: Keypair,
    amount: int,
    decimals: int = 0,
) -> str:
    """Creates `mint` and mints `amount` base units to `authority`'s
    associated token account. Returns the transaction signature.

    `authority` pays fees and holds mint authority — combining those
    roles keeps the required-signers list exactly [authority, mint],
    matching what the message actually needs (solders' Transaction
    panics on KeypairPubkeyMismatch if the signer list doesn't exactly
    match the message's required signers).

    Devnet/localnet only — make_client() raises MainnetRpcBlockedError
    for any URL containing "mainnet".
    """
    client = make_client(rpc_url)

    rent_lamports = client.get_minimum_balance_for_rent_exemption(MINT_ACCOUNT_SPACE).value
    plan = build_create_mint_instructions(
        payer=authority.pubkey(),
        mint=mint.pubkey(),
        mint_authority=authority.pubkey(),
        decimals=decimals,
        rent_lamports=rent_lamports,
    )
    mint_ix = build_mint_to_instruction(
        mint=mint.pubkey(),
        destination=plan.associated_token_account,
        mint_authority=authority.pubkey(),
        amount=amount,
    )
    blockhash = client.get_latest_blockhash().value.blockhash
    tx = _assemble_transaction(
        instructions=[*plan.instructions, mint_ix],
        payer=authority.pubkey(),
        signers=[authority, mint],
        recent_blockhash=blockhash,
    )
    resp = client.send_transaction(tx)
    return str(resp.value)


def token_account_for(owner: Pubkey, mint: Pubkey) -> Pubkey:
    from spl.token.instructions import get_associated_token_address

    return get_associated_token_address(owner, mint)
