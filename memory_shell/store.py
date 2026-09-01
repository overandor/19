"""The block store: a byte budget, an eviction policy, and two invariants.

The invariants are what separate a cache from a memory-safety bug and a
side channel respectively:

1. **A pinned block is never evicted.** Refcount above zero means a live
   session is reading those bytes. Freeing them under it is a
   use-after-free that presents as one session receiving another's state.
2. **A tenant can only evict its own blocks.** Without this, a tenant can
   flood the cache, force a victim's working set out, and read the
   victim's occupancy off the resulting slowdown. Per-tenant quotas make
   pressure a tenant applies land on that tenant.

Reads are probe-resistant. A lookup that resolves to a scope the tenant
cannot read returns a miss and leaves the block untouched — no hit
counted, no recency advanced — so "forbidden" and "absent" are
indistinguishable from outside.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .blocks import Accounting, Block, BlockRef, content_id
from .isolation import AccessDenied, IsolationPolicy, Scope, Tenant

Key = tuple[str, str]  # (scope key, block id)


class BudgetExceeded(Exception):
    """Raised when a block cannot fit even after evicting everything evictable."""


@dataclass
class EvictionRecord:
    key: Key
    nbytes: int
    reason: str


class BlockStore:
    def __init__(
        self,
        budget_bytes: int,
        policy: IsolationPolicy | None = None,
    ) -> None:
        if budget_bytes <= 0:
            raise ValueError("budget_bytes must be positive")
        self.budget_bytes = budget_bytes
        self.policy = policy or IsolationPolicy()
        self._blocks: dict[Key, Block] = {}
        # (scope, input id) -> block id. Two levels, because the two
        # questions are different: callers look work up by its *input*,
        # while physical sharing is keyed by the *output*'s content. One
        # level keyed either way loses one of the two wins.
        self._index: dict[Key, str] = {}
        self._scope_bytes: dict[str, int] = {}
        self.accounting = Accounting()
        self.evicted: list[EvictionRecord] = []

    # ── reads ──────────────────────────────────────────────────────────

    def _find(
        self, tenant: Tenant, payload_id: str
    ) -> tuple[Scope, Block] | None:
        """Locate a block in the scopes this tenant may read, counting nothing.

        Separated from `get` so that a caller which has already probed
        does not record a second lookup against the same request — and so
        that a forbidden block is simply not found, rather than found and
        then refused.
        """
        for scope in self.policy.lookup_scopes(tenant):
            block = self._blocks.get((scope.key, payload_id))
            if block is not None:
                return scope, block
        return None

    def get(self, tenant: Tenant, payload_id: str) -> BlockRef | None:
        """Resolve a block id within the scopes this tenant may read.

        Returns None for both "not present" and "present but not yours",
        without distinguishing them in state or statistics.
        """
        found = self._find(tenant, payload_id)
        if found is None:
            self.accounting.misses += 1
            return None
        scope, block = found
        block.touch()
        self.accounting.hits += 1
        self.accounting.logical_bytes += block.nbytes
        return BlockRef(block.block_id, scope.key, block.nbytes)

    def contains(self, tenant: Tenant, payload_id: str) -> bool:
        """Non-counting existence check, for callers that must not perturb stats."""
        return any(
            (scope.key, payload_id) in self._blocks
            for scope in self.policy.lookup_scopes(tenant)
        )

    # ── writes ─────────────────────────────────────────────────────────

    def put(
        self,
        tenant: Tenant,
        payload: bytes,
        kind: str = "kv",
        shareable: bool = False,
        shared_label: str | None = None,
        count_lookup: bool = True,
    ) -> BlockRef:
        """Store state, deduplicating against what the tenant can already see.

        `count_lookup` is False for callers that already probed with `get`,
        so one request never records two lookups.
        """
        payload_id = content_id(payload)

        found = self._find(tenant, payload_id)
        if found is not None:
            scope, block = found
            block.touch()
            if count_lookup:
                self.accounting.hits += 1
            self.accounting.logical_bytes += block.nbytes
            return BlockRef(block.block_id, scope.key, block.nbytes)
        if count_lookup:
            self.accounting.misses += 1

        scope = self.policy.placement(tenant, shareable, shared_label)
        if not self.policy.readable(tenant, scope):
            raise AccessDenied(f"tenant {tenant.tenant_id!r} cannot write to {scope}")

        block = Block.of(payload, kind=kind)
        self._make_room(len(payload), tenant, scope)

        key = (scope.key, block.block_id)
        self._blocks[key] = block
        self._scope_bytes[scope.key] = self._scope_bytes.get(scope.key, 0) + block.nbytes
        self.accounting.resident_bytes += block.nbytes
        self.accounting.logical_bytes += block.nbytes
        return BlockRef(block.block_id, scope.key, block.nbytes)

    # ── input-keyed lookup ─────────────────────────────────────────────

    def lookup(self, tenant: Tenant, input_id: str) -> BlockRef | None:
        """Find the output previously produced for this input.

        Scoped exactly like block reads: an entry another tenant made is
        not merely refused, it is not found, so a probe cannot tell a
        forbidden entry from an absent one.
        """
        for scope in self.policy.lookup_scopes(tenant):
            block_id = self._index.get((scope.key, input_id))
            if block_id is None:
                continue
            block = self._blocks.get((scope.key, block_id))
            if block is None:
                # The block was evicted; the index entry is stale. Drop it
                # rather than resolving to a block that no longer exists.
                del self._index[(scope.key, input_id)]
                continue
            block.touch()
            self.accounting.hits += 1
            self.accounting.logical_bytes += block.nbytes
            return BlockRef(block.block_id, scope.key, block.nbytes)
        self.accounting.misses += 1
        return None

    def store_result(
        self,
        tenant: Tenant,
        input_id: str,
        payload: bytes,
        kind: str = "kv",
        shareable: bool = False,
        shared_label: str | None = None,
    ) -> BlockRef:
        """Store an output and index it under the input that produced it.

        The block itself still deduplicates by content, so two different
        inputs yielding identical output cost one copy while keeping their
        own index entries.
        """
        ref = self.put(
            tenant,
            payload,
            kind=kind,
            shareable=shareable,
            shared_label=shared_label,
            count_lookup=False,
        )
        self._index[(ref.scope, input_id)] = ref.block_id
        return ref

    # ── pinning ────────────────────────────────────────────────────────

    def pin(self, ref: BlockRef) -> None:
        block = self._require(ref)
        block.refcount += 1

    def unpin(self, ref: BlockRef) -> None:
        block = self._blocks.get(ref.key)
        if block is None:
            return
        if block.refcount > 0:
            block.refcount -= 1

    def payload(self, ref: BlockRef) -> bytes:
        """Read a block's bytes, verifying they still hash to its name."""
        block = self._require(ref)
        if not block.verify():
            raise ValueError(
                f"block {ref.block_id[:12]} failed content verification; "
                "refusing to serve possibly-substituted state"
            )
        return block.payload

    # ── eviction ───────────────────────────────────────────────────────

    def _make_room(self, needed: int, tenant: Tenant, scope: Scope) -> None:
        if needed > self.budget_bytes:
            raise BudgetExceeded(
                f"block of {needed} bytes exceeds the whole budget "
                f"({self.budget_bytes} bytes)"
            )

        if tenant.quota_bytes is not None:
            used = self._scope_bytes.get(scope.key, 0)
            if used + needed > tenant.quota_bytes:
                self._evict(needed - (tenant.quota_bytes - used),
                            self._evictable(scope_key=scope.key), "quota")
                used = self._scope_bytes.get(scope.key, 0)
                if used + needed > tenant.quota_bytes:
                    raise BudgetExceeded(
                        f"tenant {tenant.tenant_id!r} quota of "
                        f"{tenant.quota_bytes} bytes cannot fit {needed} more"
                    )

        deficit = self.accounting.resident_bytes + needed - self.budget_bytes
        if deficit <= 0:
            return

        # A tenant's own pressure lands on its own blocks first. Only once
        # its scope is exhausted may global eviction touch anything else,
        # which is what keeps flooding from becoming an occupancy oracle.
        freed = self._evict(deficit, self._evictable(scope_key=scope.key), "budget")
        if freed < deficit:
            self._evict(deficit - freed, self._evictable(), "budget")

        if self.accounting.resident_bytes + needed > self.budget_bytes:
            raise BudgetExceeded(
                f"cannot fit {needed} bytes: {self._pinned_bytes()} bytes are "
                "pinned by live sessions and must not be evicted"
            )

    def _evictable(self, scope_key: str | None = None) -> list[tuple[Key, Block]]:
        items = [
            (key, block)
            for key, block in self._blocks.items()
            if not block.pinned and (scope_key is None or key[0] == scope_key)
        ]
        items.sort(key=lambda kb: kb[1].last_used_at)
        return items

    def _evict(
        self, target_bytes: int, candidates: Iterable[tuple[Key, Block]], reason: str
    ) -> int:
        freed = 0
        for key, block in candidates:
            if freed >= target_bytes:
                break
            del self._blocks[key]
            self._scope_bytes[key[0]] = self._scope_bytes.get(key[0], 0) - block.nbytes
            self.accounting.resident_bytes -= block.nbytes
            self.accounting.evictions += 1
            self.accounting.bytes_evicted += block.nbytes
            self.evicted.append(EvictionRecord(key, block.nbytes, reason))
            freed += block.nbytes
        return freed

    # ── views ──────────────────────────────────────────────────────────

    def _require(self, ref: BlockRef) -> Block:
        block = self._blocks.get(ref.key)
        if block is None:
            raise KeyError(f"block {ref.block_id[:12]} is no longer resident")
        return block

    def _pinned_bytes(self) -> int:
        return sum(b.nbytes for b in self._blocks.values() if b.pinned)

    def scope_bytes(self, scope_key: str) -> int:
        return self._scope_bytes.get(scope_key, 0)

    def block_count(self) -> int:
        return len(self._blocks)

    def pinned_count(self) -> int:
        return sum(1 for b in self._blocks.values() if b.pinned)
