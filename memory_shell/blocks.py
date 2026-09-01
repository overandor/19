"""Content-addressed blocks: the unit of reusable state.

An LLM server's resident memory is dominated by two things — the weights
and the attention KV cache — and both are heavily redundant across
sessions. Two requests sharing a system prompt compute byte-identical KV
for that prefix; two sessions on the same model hold byte-identical
weights. Naive serving pays for each copy.

A block is a slice of that state named by the SHA-256 of its contents, so
identical state has one name and therefore one physical copy. Everything
above this file — the budget, the eviction policy, the tenant isolation —
is bookkeeping over that single idea.

Two byte counts are tracked throughout, and the distinction is the whole
point:

* **logical bytes** — what the state would cost if every reference held
  its own copy. This is the naive figure.
* **resident bytes** — what the unique blocks actually cost.

Their difference is the memory the shell saves, and it is measured rather
than estimated: both are exact sums over real buffers.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field


def content_id(payload: bytes) -> str:
    """A block's name. Identical bytes anywhere get the same name."""
    return hashlib.sha256(payload).hexdigest()


@dataclass
class Block:
    """One deduplicated slice of reusable state.

    `refcount` is how many live sessions currently pin this block. A block
    at zero is evictable; a block above zero must not be freed, because
    something is reading it. Eviction that ignores this is the classic way
    to turn a cache into a use-after-free.
    """

    block_id: str
    payload: bytes
    kind: str = "kv"
    refcount: int = 0
    created_at: float = field(default_factory=time.monotonic)
    last_used_at: float = field(default_factory=time.monotonic)
    hits: int = 0

    @classmethod
    def of(cls, payload: bytes, kind: str = "kv") -> Block:
        return cls(block_id=content_id(payload), payload=payload, kind=kind)

    @property
    def nbytes(self) -> int:
        return len(self.payload)

    @property
    def pinned(self) -> bool:
        return self.refcount > 0

    def touch(self) -> None:
        self.last_used_at = time.monotonic()
        self.hits += 1

    def verify(self) -> bool:
        """Re-derive the name from the contents.

        A block whose payload no longer hashes to its id has been
        corrupted or substituted, and serving it would hand one session
        another's state under a trusted name.
        """
        return content_id(self.payload) == self.block_id


@dataclass(frozen=True)
class BlockRef:
    """A session's claim on a block, scoped to the tenant that took it.

    The scope travels with the reference rather than sitting only in the
    store's index, so an isolation check can never be skipped by holding
    a reference obtained elsewhere.
    """

    block_id: str
    scope: str
    nbytes: int

    @property
    def key(self) -> tuple[str, str]:
        return (self.scope, self.block_id)


@dataclass
class Accounting:
    """Exact byte counts. No estimates enter this class."""

    logical_bytes: int = 0
    resident_bytes: int = 0
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    bytes_evicted: int = 0

    @property
    def saved_bytes(self) -> int:
        """Memory not spent because references shared a physical block."""
        return max(0, self.logical_bytes - self.resident_bytes)

    @property
    def dedup_ratio(self) -> float:
        """Logical bytes served per resident byte held. 1.0 means no sharing."""
        if self.resident_bytes == 0:
            return 0.0
        return self.logical_bytes / self.resident_bytes

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total else 0.0

    def summary(self) -> str:
        return (
            f"resident {_mib(self.resident_bytes)} vs logical "
            f"{_mib(self.logical_bytes)} — saved {_mib(self.saved_bytes)} "
            f"({self.dedup_ratio:.2f}x), hit rate {self.hit_rate:.1%}, "
            f"{self.evictions} evictions"
        )


def _mib(nbytes: int) -> str:
    return f"{nbytes / (1024 * 1024):.1f}MiB"


def resident_set_bytes() -> int | None:
    """This process's real RSS, so claimed savings can be checked.

    Returns None off Linux rather than guessing. The shell's own
    accounting is exact, but a number that never gets compared against
    what the kernel thinks is a number worth distrusting.
    """
    try:
        with open("/proc/self/statm", "r") as fh:
            fields = fh.read().split()
        return int(fields[1]) * 4096
    except (OSError, IndexError, ValueError):
        return None
