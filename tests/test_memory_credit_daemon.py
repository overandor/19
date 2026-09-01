"""Tests for memory_credit_daemon/.

Everything here runs fully offline: receipt signing/verification, the
hash-chained ledger, and SPL instruction/transaction construction never
make a network call. solana_submit.mint_credits_onchain() itself is not
exercised here since it requires a reachable devnet/localnet RPC
endpoint — only its mainnet guard (make_client) is.
"""
import json

import pytest
from solders.keypair import Keypair
from solders.system_program import ID as SYSTEM_PROGRAM_ID

from memory_credit_daemon.ledger import CreditLedger
from memory_credit_daemon.receipts import GENESIS_HASH, ComputeReuseEvent, sign_event
from memory_credit_daemon.solana_credits import (
    TOKEN_PROGRAM_ID,
    assemble_transaction,
    build_create_mint_instructions,
    build_mint_to_instruction,
)
from memory_credit_daemon.solana_submit import MainnetRpcBlockedError, make_client


# ── ComputeReuseEvent / receipts ────────────────────────────────────────────

class TestComputeReuseEvent:
    def test_seconds_saved(self):
        event = ComputeReuseEvent("cache hit", baseline_cost_seconds=10.0, actual_cost_seconds=2.0)
        assert event.seconds_saved == 8.0

    def test_seconds_saved_floors_at_zero(self):
        event = ComputeReuseEvent("slower reuse", baseline_cost_seconds=2.0, actual_cost_seconds=10.0)
        assert event.seconds_saved == 0.0

    def test_negative_cost_rejected(self):
        with pytest.raises(ValueError):
            ComputeReuseEvent("bad", baseline_cost_seconds=-1.0, actual_cost_seconds=0.0)


class TestSignEvent:
    def test_verify_passes_for_untampered_receipt(self):
        signer = Keypair()
        event = ComputeReuseEvent("cache hit", baseline_cost_seconds=10.0, actual_cost_seconds=1.0)
        receipt = sign_event(event, signer, GENESIS_HASH)
        assert receipt.verify() is True
        assert receipt.credits == 9.0
        assert receipt.signer_pubkey == str(signer.pubkey())

    def test_verify_fails_if_credits_tampered(self):
        signer = Keypair()
        event = ComputeReuseEvent("cache hit", baseline_cost_seconds=10.0, actual_cost_seconds=1.0)
        receipt = sign_event(event, signer, GENESIS_HASH)
        receipt.credits = 999.0
        assert receipt.verify() is False

    def test_verify_fails_for_wrong_signer(self):
        signer = Keypair()
        impostor = Keypair()
        event = ComputeReuseEvent("cache hit", baseline_cost_seconds=10.0, actual_cost_seconds=1.0)
        receipt = sign_event(event, signer, GENESIS_HASH)
        receipt.signer_pubkey = str(impostor.pubkey())
        assert receipt.verify() is False

    def test_credits_per_second_saved_rate(self):
        signer = Keypair()
        event = ComputeReuseEvent("cache hit", baseline_cost_seconds=10.0, actual_cost_seconds=0.0)
        receipt = sign_event(event, signer, GENESIS_HASH, credits_per_second_saved=0.5)
        assert receipt.credits == 5.0

    def test_round_trip_through_dict(self):
        signer = Keypair()
        event = ComputeReuseEvent("cache hit", baseline_cost_seconds=10.0, actual_cost_seconds=1.0)
        receipt = sign_event(event, signer, GENESIS_HASH)
        from memory_credit_daemon.receipts import Receipt

        restored = Receipt.from_dict(json.loads(json.dumps(receipt.to_dict())))
        assert restored.verify() is True
        assert restored.record_hash == receipt.record_hash


# ── CreditLedger ─────────────────────────────────────────────────────────

class TestCreditLedger:
    def test_record_event_accrues_balance(self):
        signer = Keypair()
        ledger = CreditLedger()
        ledger.record_event(
            ComputeReuseEvent("a", baseline_cost_seconds=5.0, actual_cost_seconds=1.0), signer
        )
        ledger.record_event(
            ComputeReuseEvent("b", baseline_cost_seconds=3.0, actual_cost_seconds=0.0), signer
        )
        assert ledger.balance() == 4.0 + 3.0

    def test_chain_links_receipts(self):
        signer = Keypair()
        ledger = CreditLedger()
        first = ledger.record_event(
            ComputeReuseEvent("a", baseline_cost_seconds=5.0, actual_cost_seconds=1.0), signer
        )
        second = ledger.record_event(
            ComputeReuseEvent("b", baseline_cost_seconds=3.0, actual_cost_seconds=0.0), signer
        )
        assert first.prev_hash == GENESIS_HASH
        assert second.prev_hash == first.record_hash

    def test_verify_chain_clean(self):
        signer = Keypair()
        ledger = CreditLedger()
        for i in range(3):
            ledger.record_event(
                ComputeReuseEvent(f"e{i}", baseline_cost_seconds=5.0, actual_cost_seconds=1.0),
                signer,
            )
        assert ledger.verify_chain() == []

    def test_verify_chain_detects_tamper(self):
        signer = Keypair()
        ledger = CreditLedger()
        ledger.record_event(
            ComputeReuseEvent("a", baseline_cost_seconds=5.0, actual_cost_seconds=1.0), signer
        )
        ledger.record_event(
            ComputeReuseEvent("b", baseline_cost_seconds=3.0, actual_cost_seconds=0.0), signer
        )
        ledger.receipts[1].credits = 1_000_000.0
        breaks = ledger.verify_chain()
        assert len(breaks) == 1
        assert breaks[0].index == 1

    def test_balance_filters_by_signer(self):
        alice, bob = Keypair(), Keypair()
        ledger = CreditLedger()
        ledger.record_event(
            ComputeReuseEvent("a", baseline_cost_seconds=5.0, actual_cost_seconds=0.0), alice
        )
        ledger.record_event(
            ComputeReuseEvent("b", baseline_cost_seconds=7.0, actual_cost_seconds=0.0), bob
        )
        assert ledger.balance(str(alice.pubkey())) == 5.0
        assert ledger.balance(str(bob.pubkey())) == 7.0
        assert ledger.balance() == 12.0

    def test_persists_and_reloads(self, tmp_path):
        signer = Keypair()
        path = tmp_path / "ledger.json"
        ledger = CreditLedger(path)
        ledger.record_event(
            ComputeReuseEvent("a", baseline_cost_seconds=5.0, actual_cost_seconds=1.0), signer
        )

        reloaded = CreditLedger(path)
        assert reloaded.balance() == 4.0
        assert reloaded.verify_chain() == []


# ── solana_credits (offline instruction/transaction building) ───────────

class TestSolanaCredits:
    def test_create_mint_instructions_use_token_program(self):
        payer = Keypair()
        mint = Keypair()
        plan = build_create_mint_instructions(payer.pubkey(), mint.pubkey(), payer.pubkey())
        create_ix, init_ix, create_ata_ix = plan.instructions
        assert create_ix.program_id == SYSTEM_PROGRAM_ID
        assert init_ix.program_id == TOKEN_PROGRAM_ID
        assert plan.associated_token_account != mint.pubkey()

    def test_full_mint_transaction_builds_and_signs(self):
        authority = Keypair()
        mint = Keypair()
        plan = build_create_mint_instructions(authority.pubkey(), mint.pubkey(), authority.pubkey())
        mint_ix = build_mint_to_instruction(
            mint.pubkey(), plan.associated_token_account, authority.pubkey(), amount=1_000
        )
        tx = assemble_transaction(
            instructions=[*plan.instructions, mint_ix],
            payer=authority.pubkey(),
            signers=[authority, mint],
        )
        assert len(tx.signatures) == 2
        assert len(bytes(tx)) > 0

    def test_mismatched_signers_raise(self):
        authority = Keypair()
        mint = Keypair()
        bystander = Keypair()
        plan = build_create_mint_instructions(authority.pubkey(), mint.pubkey(), authority.pubkey())
        with pytest.raises(BaseException):
            assemble_transaction(
                instructions=plan.instructions,
                payer=authority.pubkey(),
                signers=[authority, mint, bystander],
            )


# ── solana_submit mainnet guard ───────────────────────────────────────────

class TestMainnetGuard:
    @pytest.mark.parametrize(
        "rpc_url",
        [
            "https://api.mainnet-beta.solana.com",
            "https://my-rpc.MAINNET.example.com",
        ],
    )
    def test_blocks_mainnet_urls(self, rpc_url):
        with pytest.raises(MainnetRpcBlockedError):
            make_client(rpc_url)

    @pytest.mark.parametrize(
        "rpc_url",
        [
            "https://api.devnet.solana.com",
            "http://127.0.0.1:8899",
        ],
    )
    def test_allows_devnet_and_localnet_urls(self, rpc_url):
        make_client(rpc_url)


# ── mainnet is reachable, but only deliberately and only for verified credits ──

class TestMainnetOptIn:
    def test_mainnet_is_still_refused_by_default(self):
        with pytest.raises(MainnetRpcBlockedError):
            make_client("https://api.mainnet-beta.solana.com")

    def test_mainnet_requires_an_explicit_opt_in(self):
        client = make_client(
            "https://api.mainnet-beta.solana.com", allow_mainnet=True
        )
        assert client is not None

    def test_devnet_and_localnet_are_unaffected(self):
        assert make_client("https://api.devnet.solana.com") is not None
        assert make_client("http://127.0.0.1:8899") is not None


class TestAuthorizedMinting:
    def test_a_bare_number_is_not_an_authorization(self):
        from memory_credit_daemon.solana_submit import (
            UnauthorizedMintError,
            mint_authorized_credits,
        )

        with pytest.raises(UnauthorizedMintError, match="MintAuthorization"):
            mint_authorized_credits(
                "https://api.devnet.solana.com",
                Keypair(),
                Keypair(),
                authorization=1_000_000,
            )

    def test_zero_authorized_credits_mint_nothing(self):
        from memory_credit_daemon.solana_submit import (
            UnauthorizedMintError,
            mint_authorized_credits,
        )
        from proof_of_avoided_work.minting import MintAuthorization

        auth = MintAuthorization("pk", 0.4, 1, 0, 0, "https://api.devnet.solana.com")
        with pytest.raises(UnauthorizedMintError, match="nothing to mint"):
            mint_authorized_credits(
                "https://api.devnet.solana.com", Keypair(), Keypair(), auth
            )

    def test_an_authorization_cannot_be_replayed_against_another_network(self):
        """A solvency verdict is about one pool on one network."""
        from memory_credit_daemon.solana_submit import (
            UnauthorizedMintError,
            mint_authorized_credits,
        )
        from proof_of_avoided_work.minting import MintAuthorization

        auth = MintAuthorization("pk", 500.0, 1, 0, 0, "https://api.devnet.solana.com")
        with pytest.raises(UnauthorizedMintError, match="re-authorize"):
            mint_authorized_credits(
                "https://api.mainnet-beta.solana.com", Keypair(), Keypair(), auth
            )
