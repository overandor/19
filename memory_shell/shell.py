"""The shell itself: sessions, reuse, and the loop back to metering.

A session asks the shell to produce the result of some work. The shell
either finds that work's output already resident — in a scope this tenant
is allowed to read — and returns it without recomputing, or it computes
it, measures what that cost, and stores it.

That second path is worth dwelling on, because it closes the gap that
`proof_of_avoided_work` could not close by itself. PoAW needs a baseline
oracle fed by *measured* cold costs from identified measurers, and it
needs claims whose `actual_cost_seconds` came from an instrument rather
than a keyboard. A cache miss is precisely a cold execution, timed, of a
unit whose commitment the shell already computed. So every miss is a
baseline sample and every hit is a claim, both produced as a side effect
of the shell doing its ordinary job.

That is the whole architecture in one sentence: the thing that saves the
memory is also the thing that honestly measures how much it saved.

Wiring to PoAW is optional. Without a signer the shell is a plain
memory-reducing cache; with one, it emits signed claims into a settlement
engine and cold-cost samples into an oracle.
"""
from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from .blocks import Accounting, BlockRef, content_id, resident_set_bytes
from .isolation import IsolationPolicy, Tenant
from .store import BlockStore
from .weights import WeightRegistry

Compute = Callable[[], bytes]


@dataclass
class WorkResult:
    output: bytes
    reused: bool
    cost_seconds: float
    nbytes: int
    work_class: str
    baseline_seconds: float = 0.0

    @property
    def saved_seconds(self) -> float:
        """Time not spent, and zero on a miss — a cold run saves nothing."""
        if not self.reused:
            return 0.0
        return max(0.0, self.baseline_seconds - self.cost_seconds)


@dataclass
class ShellStats:
    accounting: Accounting
    weights_resident_bytes: int
    weights_saved_bytes: int
    rss_bytes: int | None
    claims_emitted: int
    baseline_samples: int

    def summary(self) -> str:
        rss = "unavailable" if self.rss_bytes is None else _mib(self.rss_bytes)
        return (
            f"{self.accounting.summary()}; weights "
            f"{_mib(self.weights_resident_bytes)} resident, "
            f"{_mib(self.weights_saved_bytes)} saved by sharing; "
            f"process RSS {rss}; {self.claims_emitted} claims, "
            f"{self.baseline_samples} baseline samples"
        )


def _mib(nbytes: int) -> str:
    return f"{nbytes / (1024 * 1024):.1f}MiB"


class Session:
    """One tenant's live handle on the shell.

    Pins are deliberately transient. `run` pins a block only while it is
    reading it and releases it immediately, because the result handed back
    is a copy and needs no further protection. A session that pinned every
    result it ever produced would, on a long enough conversation, pin the
    entire budget and then fail to allocate against itself — the cache
    equivalent of a deadlock.

    A caller that genuinely needs state kept resident across turns — a
    multi-turn conversation holding its KV prefix, say — asks for it with
    `hold=True`. That is an explicit, bounded working set rather than an
    accidental unbounded one, and it is the caller's business to keep it
    smaller than the budget.
    """

    def __init__(self, shell: MemoryShell, tenant: Tenant) -> None:
        self.shell = shell
        self.tenant = tenant
        self._pins: list[BlockRef] = []

    def run(
        self,
        work_class: str,
        payload: bytes,
        compute: Compute,
        shareable: bool = False,
        shared_label: str | None = None,
        hold: bool = False,
    ) -> WorkResult:
        store = self.shell.store
        key = content_id(payload)

        ref = store.lookup(self.tenant, key)
        if ref is not None:
            # Pin across the read so the block cannot be freed mid-copy,
            # then release unless the caller asked to hold it.
            store.pin(ref)
            try:
                started = time.perf_counter()
                output = bytes(store.payload(ref))
                elapsed = time.perf_counter() - started
            finally:
                if hold:
                    self._pins.append(ref)
                else:
                    store.unpin(ref)
            baseline = self.shell.observed_baseline(work_class)
            self.shell._on_reuse(work_class, payload, output, elapsed, self.tenant)
            return WorkResult(
                output=output,
                reused=True,
                cost_seconds=elapsed,
                nbytes=len(output),
                work_class=work_class,
                baseline_seconds=baseline,
            )

        started = time.perf_counter()
        output = compute()
        elapsed = time.perf_counter() - started
        if not isinstance(output, (bytes, bytearray, memoryview)):
            raise TypeError("compute() must return bytes-like state")
        output = bytes(output)

        # Indexed by the input's id, stored by the output's content: the
        # lookup above already recorded this request's miss.
        stored = store.store_result(
            self.tenant,
            key,
            output,
            kind=work_class,
            shareable=shareable,
            shared_label=shared_label,
        )
        if hold:
            store.pin(stored)
            self._pins.append(stored)
        self.shell._on_cold(work_class, elapsed)
        return WorkResult(
            output=output,
            reused=False,
            cost_seconds=elapsed,
            nbytes=len(output),
            work_class=work_class,
            baseline_seconds=elapsed,
        )

    @property
    def held_bytes(self) -> int:
        """Bytes this session is keeping resident via `hold=True`."""
        return sum(ref.nbytes for ref in self._pins)

    def close(self) -> None:
        for ref in self._pins:
            self.shell.store.unpin(ref)
        self._pins.clear()


class MemoryShell:
    def __init__(
        self,
        budget_bytes: int,
        policy: IsolationPolicy | None = None,
        code_version: str = "memory_shell-0.1.0",
        signer=None,
        oracle=None,
        settlement=None,
        env: dict | None = None,
    ) -> None:
        self.store = BlockStore(budget_bytes, policy)
        self.weights = WeightRegistry()
        self.code_version = code_version
        self.env = env or {"runtime": "memory_shell"}
        self.signer = signer
        self.oracle = oracle
        self.settlement = settlement
        self.epoch = 1
        self.claims: list[object] = []
        self._cold_samples: dict[str, list[float]] = {}
        self._baseline_sample_count = 0

    @contextmanager
    def session(self, tenant: Tenant) -> Iterator[Session]:
        session = Session(self, tenant)
        try:
            yield session
        finally:
            session.close()

    def load_weights(self, path):
        return self.weights.acquire(path)

    def observed_baseline(self, work_class: str) -> float:
        """Mean measured cold cost for this class, or 0 if never seen cold."""
        samples = self._cold_samples.get(work_class, [])
        return sum(samples) / len(samples) if samples else 0.0

    # ── metering hooks ─────────────────────────────────────────────────

    def _on_cold(self, work_class: str, elapsed: float) -> None:
        """A miss is a timed cold execution — exactly a baseline sample."""
        self._cold_samples.setdefault(work_class, []).append(elapsed)
        if self.oracle is not None and self.signer is not None and elapsed > 0:
            self.oracle.observe(work_class, elapsed, str(self.signer.pubkey()))
            self._baseline_sample_count += 1

    def _on_reuse(
        self,
        work_class: str,
        payload: bytes,
        output: bytes,
        elapsed: float,
        tenant: Tenant,
    ) -> None:
        """A hit is a reuse claim, with a measured cost rather than a stated one."""
        if self.signer is None:
            return
        from proof_of_avoided_work.commitments import WorkCommitment, sign_claim

        commitment = WorkCommitment.over(
            work_class, payload, self.code_version, self.env
        )
        claim = sign_claim(
            commitment=commitment,
            output_digest=content_id(output),
            actual_cost_seconds=elapsed,
            epoch=self.epoch,
            signer=self.signer,
        )
        self.claims.append(claim)
        if self.settlement is not None:
            from proof_of_avoided_work.settlement import ClaimRejected

            try:
                self.settlement.submit(claim)
            except ClaimRejected:
                # An unpriceable or duplicate claim is not a serving error:
                # the tenant still gets their result, it simply earns nothing.
                pass

    def stats(self) -> ShellStats:
        return ShellStats(
            accounting=self.store.accounting,
            weights_resident_bytes=self.weights.resident_bytes,
            weights_saved_bytes=self.weights.saved_bytes,
            rss_bytes=resident_set_bytes(),
            claims_emitted=len(self.claims),
            baseline_samples=self._baseline_sample_count,
        )
