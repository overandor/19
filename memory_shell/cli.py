"""Command line for memory_shell.

    python -m memory_shell measure   # real RSS measurement of weight sharing
    python -m memory_shell demo      # multi-tenant savings and isolation
    python -m memory_shell serve     # the stdio service sshd invokes

`measure` writes a temporary file and maps it N times, touching every
page, then reports what the kernel says about RSS. The numbers are
measured on the machine it runs on, not modelled.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

from .blocks import resident_set_bytes
from .isolation import IsolationPolicy, Tenant
from .remote import (
    ProtocolError,
    RemoteShellService,
    serve,
    tenant_from_environment,
)
from .shell import MemoryShell
from .weights import measure_sharing


def _mib(nbytes: int | None) -> str:
    if nbytes is None:
        return "unavailable"
    return f"{nbytes / (1024 * 1024):.1f}MiB"


def cmd_measure(args: argparse.Namespace) -> int:
    size = args.size_mib * 1024 * 1024
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "weights.bin"
        path.write_bytes(os.urandom(size))
        result = measure_sharing(path, mappings=args.workers)

    print(f"weights file      : {_mib(result['file_bytes'])}")
    print(f"workers           : {result['mappings']}")
    print(f"private copies    : {_mib(result['naive_bytes'])}  (what N copies cost)")
    print(f"shared mapping    : {_mib(result['registry_resident_bytes'])}")
    print(f"saved             : {_mib(result['registry_saved_bytes'])}")
    print(f"measured RSS delta: {_mib(result['rss_delta_bytes'])}  (kernel, after touching every page)")

    delta = result["rss_delta_bytes"]
    if delta is not None and delta < result["naive_bytes"] // 2:
        print("\nRSS tracks the number of distinct models, not the number of workers.")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    budget = args.budget_mib * 1024 * 1024
    shell = MemoryShell(budget)

    system_prompt = b"You are a careful assistant." * 64
    alice = Tenant("alice").granted("shared:public")
    bob = Tenant("bob").granted("shared:public")
    carol = Tenant("carol")  # no grant: sees nothing shared

    kv_bytes = args.kv_mib * 1024 * 1024

    def kv_for(text: bytes) -> bytes:
        """Stands in for prefill output, at a realistic KV size.

        A few MiB per cached prefix is the right order for a mid-sized
        model, and using it here keeps the reported savings legible rather
        than rounding to zero.
        """
        seed = text * (kv_bytes // len(text) + 1)
        return seed[:kv_bytes]

    print("Three tenants, all sending the same system prompt.\n")

    for tenant in (alice, bob):
        with shell.session(tenant) as session:
            result = session.run(
                "prefill.system",
                system_prompt,
                lambda: kv_for(system_prompt),
                shareable=True,
                shared_label="public",
            )
            print(f"  {tenant.tenant_id:<6} system prompt: "
                  f"{'reused' if result.reused else 'computed'}")

    with shell.session(carol) as session:
        result = session.run(
            "prefill.system", system_prompt, lambda: kv_for(system_prompt)
        )
        print(f"  {carol.tenant_id:<6} system prompt: "
              f"{'reused' if result.reused else 'computed'}  "
              "(no grant to the shared scope, so a private copy)")

    print("\nNow each sends a private document.\n")
    secret = b"CONFIDENTIAL merger terms" * 32
    with shell.session(alice) as session:
        session.run("prefill.doc", secret, lambda: kv_for(secret))

    probe_hit = False
    with shell.session(bob) as session:
        result = session.run("prefill.doc", secret, lambda: kv_for(secret))
        probe_hit = result.reused
    print(f"  bob probes alice's document: "
          f"{'REUSED — leak!' if probe_hit else 'computed, no signal'}")

    acc = shell.store.accounting
    print()
    print(f"  logical  : {_mib(acc.logical_bytes)}  (what private copies would cost)")
    print(f"  resident : {_mib(acc.resident_bytes)}")
    print(f"  saved    : {_mib(acc.saved_bytes)}  ({acc.dedup_ratio:.2f}x)")
    print(f"  hit rate : {acc.hit_rate:.1%}")
    print(f"  blocks   : {shell.store.block_count()}")
    print(f"  RSS      : {_mib(resident_set_bytes())}")
    print()
    print("The identical secret is stored twice, on purpose. Deduplicating it")
    print("would let bob detect that alice processed that exact document.")
    return 0 if not probe_hit else 1


def cmd_serve(args: argparse.Namespace) -> int:
    """Run the stdio service. sshd invokes this as a forced command."""
    try:
        tenant = tenant_from_environment()
    except ProtocolError as exc:
        # An unidentified session is a configuration error, not a runtime
        # one: exit cleanly rather than serving traffic with no tenant.
        print(f"refusing to serve: {exc}", file=sys.stderr)
        return 2

    shell = MemoryShell(
        args.budget_mib * 1024 * 1024,
        policy=IsolationPolicy(allow_shared_publication=args.allow_shared),
    )

    def unconfigured(work_class: str, payload: bytes) -> bytes:
        raise RuntimeError(
            "no compute backend configured; wire MemoryShell into your "
            "inference runtime before serving traffic"
        )

    service = RemoteShellService(shell=shell, tenant=tenant, compute=unconfigured)
    served = serve(service, sys.stdin.buffer, sys.stdout.buffer)
    print(f"served {served} requests for {tenant.tenant_id}", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="memory_shell",
        description="A sandboxed shell that cuts an LLM server's resident memory.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_measure = sub.add_parser("measure", help="measure real weight-sharing savings")
    p_measure.add_argument("--size-mib", type=int, default=64)
    p_measure.add_argument("--workers", type=int, default=8)
    p_measure.set_defaults(func=cmd_measure)

    p_demo = sub.add_parser("demo", help="multi-tenant savings and isolation")
    p_demo.add_argument("--budget-mib", type=int, default=256)
    p_demo.add_argument("--kv-mib", type=int, default=8,
                        help="size of each cached prefix, standing in for real KV")
    p_demo.set_defaults(func=cmd_demo)

    p_serve = sub.add_parser("serve", help="stdio service for sshd to invoke")
    p_serve.add_argument("--budget-mib", type=int, default=1024)
    p_serve.add_argument("--allow-shared", action="store_true")
    p_serve.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
