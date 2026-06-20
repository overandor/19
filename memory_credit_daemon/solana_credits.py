"""Builds standard SPL Token Program instructions for a credits mint.

Scope: devnet and localnet only. This module only constructs and signs
instructions/transactions — it never sends anything over the network, so
every function here is exercised by tests/test_memory_credit_daemon.py
without needing RPC access. Submitting a built transaction is handled
by solana_submit.py, which carries an explicit mainnet guard.

This deliberately drives the standard, already-deployed SPL Token
Program directly instead of a custom Anchor program: a credits mint
needs nothing beyond create-account + initialize-mint + mint-to, all of
which the stock token program already provides. See
docs/MEMORY_CREDIT_DAEMON.md for why a custom program was skipped.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from solders.hash import Hash
from solders.instruction import Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.system_program import CreateAccountParams, create_account
from solders.transaction import Transaction
from spl.token.instructions import (
    TOKEN_PROGRAM_ID,
    InitializeMint2Params,
    MintToParams,
    create_associated_token_account,
    get_associated_token_address,
    initialize_mint2,
    mint_to,
)

MINT_ACCOUNT_SPACE = 82

# Rent-exempt minimum (lamports) for an 82-byte SPL mint account, used only
# as an offline fallback when there is no RPC connection available to call
# get_minimum_balance_for_rent_exemption(). Prefer the live value when one
# is reachable (see solana_submit.py).
FALLBACK_MINT_RENT_LAMPORTS = 1_461_600


@dataclass
class CreditMintPlan:
    mint: Pubkey
    mint_authority: Pubkey
    decimals: int
    instructions: List[Instruction]
    associated_token_account: Pubkey


def build_create_mint_instructions(
    payer: Pubkey,
    mint: Pubkey,
    mint_authority: Pubkey,
    decimals: int = 0,
    rent_lamports: int = FALLBACK_MINT_RENT_LAMPORTS,
) -> CreditMintPlan:
    """Instructions to create + initialize a credits mint and the payer's
    associated token account for it. Mints no supply by itself — pair
    with build_mint_to_instruction()."""
    create_ix = create_account(
        CreateAccountParams(
            from_pubkey=payer,
            to_pubkey=mint,
            lamports=rent_lamports,
            space=MINT_ACCOUNT_SPACE,
            owner=TOKEN_PROGRAM_ID,
        )
    )
    init_ix = initialize_mint2(
        InitializeMint2Params(
            decimals=decimals,
            program_id=TOKEN_PROGRAM_ID,
            mint=mint,
            mint_authority=mint_authority,
            freeze_authority=None,
        )
    )
    ata = get_associated_token_address(payer, mint)
    create_ata_ix = create_associated_token_account(payer, payer, mint)
    return CreditMintPlan(
        mint=mint,
        mint_authority=mint_authority,
        decimals=decimals,
        instructions=[create_ix, init_ix, create_ata_ix],
        associated_token_account=ata,
    )


def build_mint_to_instruction(
    mint: Pubkey,
    destination: Pubkey,
    mint_authority: Pubkey,
    amount: int,
) -> Instruction:
    """amount is in the mint's base units (no decimal scaling applied)."""
    return mint_to(
        MintToParams(
            program_id=TOKEN_PROGRAM_ID,
            mint=mint,
            dest=destination,
            mint_authority=mint_authority,
            amount=amount,
            signers=[],
        )
    )


def assemble_transaction(
    instructions: List[Instruction],
    payer: Pubkey,
    signers: List[Keypair],
    recent_blockhash: Optional[Hash] = None,
) -> Transaction:
    """Builds and signs a transaction from instructions.

    Pass a real recent_blockhash (e.g. from
    Client.get_latest_blockhash().value.blockhash on devnet/localnet)
    before submitting. The default Hash.default() only produces a
    structurally valid transaction for offline tests; a node will reject
    it as an unknown/expired blockhash.
    """
    message = Message(instructions, payer)
    blockhash = recent_blockhash if recent_blockhash is not None else Hash.default()
    return Transaction(signers, message, blockhash)
