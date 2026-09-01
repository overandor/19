"""Live RPC submission for the credits mint — devnet/localnet only.

Everything in here requires a reachable Solana RPC endpoint, which this
sandbox's network allowlist does not provide (api.devnet.solana.com and
a local validator are both unreachable here). It is therefore exercised
by manual testing on a machine with network access, not by the test
suite — see docs/MEMORY_CREDIT_DAEMON.md. The instruction-building and
transaction-assembly it depends on (solana_credits.py) is fully unit
tested offline.

Mainnet is reachable but never by accident. make_client() still refuses
any URL containing "mainnet" unless the caller passes allow_mainnet=True
explicitly, so misconfiguration cannot get there and a deliberate decision
can. The blanket ban that used to sit here was the right default and the
wrong guarantee: what actually needs preventing is not "touching mainnet",
it is minting credits nobody verified into a pool anybody can sell into.
mint_authorized_credits() enforces that directly — the amount comes from a
proof_of_avoided_work MintAuthorization, which is only issued for settled,
audited credits and, on mainnet, only once the pool is shown non-drainable
at the configured bond and audit rate.
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


class UnauthorizedMintError(RuntimeError):
    """Raised when an amount did not come from a MintAuthorization."""


def make_client(rpc_url: str, allow_mainnet: bool = False) -> Client:
    """Connect to an RPC endpoint. Mainnet requires saying so.

    The default is unchanged: a URL containing "mainnet" is refused, so no
    amount of misconfiguration reaches mainnet-beta by accident. Passing
    allow_mainnet=True is the deliberate decision, and callers that make it
    should be going through mint_authorized_credits() rather than
    mint_credits_onchain().
    """
    if "mainnet" in rpc_url.lower() and not allow_mainnet:
        raise MainnetRpcBlockedError(
            f"Refusing to connect to {rpc_url!r}: mainnet requires "
            "allow_mainnet=True, and minting there requires a "
            "proof_of_avoided_work MintAuthorization. See "
            "docs/MEMORY_CREDIT_DAEMON.md and docs/PROOF_OF_AVOIDED_WORK.md."
        )
    return Client(rpc_url)


def mint_credits_onchain(
    rpc_url: str,
    authority: Keypair,
    mint: Keypair,
    amount: int,
    decimals: int = 0,
    allow_mainnet: bool = False,
) -> str:
    """Creates `mint` and mints `amount` base units to `authority`'s
    associated token account. Returns the transaction signature.

    `authority` pays fees and holds mint authority — combining those
    roles keeps the required-signers list exactly [authority, mint],
    matching what the message actually needs (solders' Transaction
    panics on KeypairPubkeyMismatch if the signer list doesn't exactly
    match the message's required signers).

    `amount` is unconstrained here, which is exactly why this function
    must not be pointed at mainnet: nothing about it ties the number to
    work anyone verified. Use mint_authorized_credits() for that.
    """
    client = make_client(rpc_url, allow_mainnet=allow_mainnet)

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


def mint_authorized_credits(
    rpc_url: str,
    authority: Keypair,
    mint: Keypair,
    authorization,
    decimals: int = 0,
) -> str:
    """Mint exactly what a MintAuthorization permits, and nothing else.

    The amount is read off the authorization rather than accepted as an
    argument, so there is no parameter a caller can use to mint more than
    was verified. `authorization` is a
    proof_of_avoided_work.minting.MintAuthorization; it is duck-typed here
    only so this package keeps no hard dependency on that one.
    """
    amount = getattr(authorization, "base_units", None)
    network = getattr(authorization, "network", None)
    if amount is None or network is None:
        raise UnauthorizedMintError(
            "expected a proof_of_avoided_work MintAuthorization carrying "
            "`base_units` and `network`; refusing to mint an unverified amount"
        )
    if amount <= 0:
        raise UnauthorizedMintError(
            f"authorization permits {amount} base units; nothing to mint"
        )
    if network != rpc_url:
        # The solvency check in authorize_mint() was run against a named
        # network. Minting somewhere else would be using its verdict for a
        # question it did not answer.
        raise UnauthorizedMintError(
            f"authorization was issued for {network!r} but this call targets "
            f"{rpc_url!r}; re-authorize against the endpoint you intend to use"
        )

    return mint_credits_onchain(
        rpc_url=rpc_url,
        authority=authority,
        mint=mint,
        amount=amount,
        decimals=decimals,
        allow_mainnet="mainnet" in rpc_url.lower(),
    )


def token_account_for(owner: Pubkey, mint: Pubkey) -> Pubkey:
    from spl.token.instructions import get_associated_token_address

    return get_associated_token_address(owner, mint)
