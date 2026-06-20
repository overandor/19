"""v0 CLI for the memory credit daemon. Run as `python -m memory_credit_daemon.cli <command>`.

All commands operate on a local, signed ledger file. Nothing here talks
to a network by default — `mint` is the one command that does, and only
against the devnet/localnet RPC URL you pass it (see solana_submit.py's
mainnet guard).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from solders.keypair import Keypair

from .ledger import CreditLedger
from .receipts import ComputeReuseEvent
from .solana_submit import MainnetRpcBlockedError, mint_credits_onchain

DEFAULT_LEDGER_PATH = Path("memory_credit_daemon/.data/ledger.json")
DEFAULT_KEY_PATH = Path("memory_credit_daemon/.data/daemon_keypair.json")


def _load_or_create_signer(key_path: Path) -> Keypair:
    if key_path.exists():
        return Keypair.from_json(key_path.read_text())
    key_path.parent.mkdir(parents=True, exist_ok=True)
    signer = Keypair()
    key_path.write_text(signer.to_json())
    return signer


def cmd_record(args: argparse.Namespace) -> int:
    signer = _load_or_create_signer(args.key_path)
    ledger = CreditLedger(args.ledger_path)
    event = ComputeReuseEvent(
        description=args.description,
        baseline_cost_seconds=args.baseline_cost_seconds,
        actual_cost_seconds=args.actual_cost_seconds,
    )
    receipt = ledger.record_event(event, signer, credits_per_second_saved=args.rate)
    print(f"recorded receipt {receipt.receipt_id}: +{receipt.credits:.4f} credits")
    return 0


def cmd_balance(args: argparse.Namespace) -> int:
    ledger = CreditLedger(args.ledger_path)
    print(f"{ledger.balance():.4f}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    ledger = CreditLedger(args.ledger_path)
    breaks = ledger.verify_chain()
    if not breaks:
        print(f"ok: {len(ledger.receipts)} receipts verified")
        return 0
    for b in breaks:
        print(f"break at receipt {b.index}: {b.reason}", file=sys.stderr)
    return 1


def cmd_mint(args: argparse.Namespace) -> int:
    signer = _load_or_create_signer(args.key_path)
    ledger = CreditLedger(args.ledger_path)
    balance = ledger.balance(str(signer.pubkey()))
    amount = args.amount if args.amount is not None else int(balance)
    if amount <= 0:
        print(f"nothing to mint (ledger balance: {balance:.4f})", file=sys.stderr)
        return 1

    mint = Keypair()
    try:
        signature = mint_credits_onchain(args.rpc_url, signer, mint, amount, args.decimals)
    except MainnetRpcBlockedError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(f"minted {amount} credits to {signer.pubkey()}")
    print(f"mint address: {mint.pubkey()}")
    print(f"tx signature: {signature}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="memory_credit_daemon")
    parser.add_argument("--ledger-path", type=Path, default=DEFAULT_LEDGER_PATH)
    parser.add_argument("--key-path", type=Path, default=DEFAULT_KEY_PATH)
    sub = parser.add_subparsers(dest="command", required=True)

    record = sub.add_parser("record", help="record a compute-reuse event")
    record.add_argument("description")
    record.add_argument("baseline_cost_seconds", type=float)
    record.add_argument("actual_cost_seconds", type=float)
    record.add_argument("--rate", type=float, default=1.0, help="credits per second saved")
    record.set_defaults(func=cmd_record)

    balance = sub.add_parser("balance", help="print the total ledger balance")
    balance.set_defaults(func=cmd_balance)

    verify = sub.add_parser("verify", help="verify the ledger's hash chain and signatures")
    verify.set_defaults(func=cmd_verify)

    mint = sub.add_parser("mint", help="mint the ledger balance as a devnet/localnet SPL token")
    mint.add_argument("rpc_url", help="devnet or localnet RPC URL only — mainnet is refused")
    mint.add_argument("--amount", type=int, default=None, help="defaults to the full balance")
    mint.add_argument("--decimals", type=int, default=0)
    mint.set_defaults(func=cmd_mint)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
