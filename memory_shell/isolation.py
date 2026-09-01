"""Why a shared cache needs a security model at all.

Sharing reusable state between sessions is what saves the memory. It is
also, done naively, an information leak — and the leak is not theoretical.
If tenant B's request returns fast because tenant A already cached that
exact prefix, B has learned that A processed that content. Repeat the
probe over a dictionary of candidate documents and the cache becomes an
oracle answering "has anyone here seen this?" about other people's
prompts.

So the rule is default-deny: state derived from a tenant's input is
private to that tenant, and identical bytes belonging to two tenants are
deliberately stored twice. That costs memory, and it is the right trade —
the savings come from what can be shared *safely*, which is plenty:

* **Model weights.** Identical for everyone, public, and the single
  largest resident cost. Sharing these is where most of the win is, and
  it leaks nothing, because knowing which model is loaded is not a secret.
* **Declared-public prefixes.** A system prompt or template the operator
  marks shareable. The declaration is explicit and per-block; nothing is
  promoted to shared because it merely happens to be popular.

Anything else stays private, and a tenant probing a scope it cannot read
is answered exactly as it would be on a genuine miss: no hit is recorded
against the block, its recency is not advanced, and the caller cannot
distinguish the two. A denial that updates statistics is still a channel.

Eviction is the second channel, and quotas are the answer. If one tenant
can flood the cache and force another's working set out, the victim's
subsequent slowdown is observable, and the flooder learns about the
victim's occupancy. Per-tenant byte quotas mean a tenant can only ever
evict its own blocks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

WEIGHTS_SCOPE = "shared:weights"


class Visibility(str, Enum):
    PRIVATE = "private"
    SHARED = "shared"


@dataclass(frozen=True)
class Scope:
    """The namespace a block lives in. Part of its key, not a label on it."""

    kind: Visibility
    label: str

    @classmethod
    def tenant(cls, tenant_id: str) -> Scope:
        if not tenant_id:
            raise ValueError("tenant_id must be non-empty")
        return cls(Visibility.PRIVATE, f"tenant:{tenant_id}")

    @classmethod
    def shared(cls, label: str) -> Scope:
        if not label:
            raise ValueError("shared scope label must be non-empty")
        return cls(Visibility.SHARED, label if ":" in label else f"shared:{label}")

    @property
    def key(self) -> str:
        return self.label

    def __str__(self) -> str:
        return self.label


@dataclass(frozen=True)
class Tenant:
    """A trust boundary.

    `shared_scopes` is what this tenant may read beyond its own — an
    allow-list, so a new shared scope is invisible until someone grants it
    rather than readable until someone remembers to forbid it.
    """

    tenant_id: str
    shared_scopes: frozenset[str] = field(default_factory=frozenset)
    quota_bytes: int | None = None

    def __post_init__(self) -> None:
        if not self.tenant_id:
            raise ValueError("tenant_id must be non-empty")
        if self.quota_bytes is not None and self.quota_bytes <= 0:
            raise ValueError("quota_bytes must be positive when set")

    @property
    def private_scope(self) -> Scope:
        return Scope.tenant(self.tenant_id)

    def may_read(self, scope: Scope) -> bool:
        if scope.kind is Visibility.PRIVATE:
            return scope == self.private_scope
        return scope.key in self.shared_scopes

    def granted(self, *scope_keys: str) -> Tenant:
        return Tenant(
            tenant_id=self.tenant_id,
            shared_scopes=self.shared_scopes | frozenset(scope_keys),
            quota_bytes=self.quota_bytes,
        )


class AccessDenied(Exception):
    """Raised on an attempt to *write* into a scope the tenant cannot use.

    Reads are never denied with an exception — that would itself
    distinguish "exists but forbidden" from "absent". A forbidden read is
    reported as a miss.
    """


@dataclass
class IsolationPolicy:
    """Decides where a block goes and who may see it.

    `allow_shared_publication` gates whether tenants may publish into
    shared scopes at all. Operators serving mutually distrusting tenants
    can turn it off entirely and keep only the weight sharing, which is
    the bulk of the saving anyway.
    """

    allow_shared_publication: bool = True

    def placement(
        self,
        tenant: Tenant,
        shareable: bool = False,
        shared_label: str | None = None,
    ) -> Scope:
        """The scope a new block is written into. Private unless declared."""
        if not shareable:
            return tenant.private_scope
        if not self.allow_shared_publication:
            raise AccessDenied(
                "shared publication is disabled; this deployment shares only "
                "model weights across tenants"
            )
        scope = Scope.shared(shared_label or "public")
        if not tenant.may_read(scope):
            raise AccessDenied(
                f"tenant {tenant.tenant_id!r} may not publish into {scope}"
            )
        return scope

    def readable(self, tenant: Tenant, scope: Scope) -> bool:
        return tenant.may_read(scope)

    def lookup_scopes(self, tenant: Tenant) -> list[Scope]:
        """Scopes searched on a read, private first.

        Order matters for correctness, not just speed: a tenant's own copy
        must win, so that revoking a shared grant can never silently change
        which bytes a session sees mid-flight.
        """
        scopes = [tenant.private_scope]
        for key in sorted(tenant.shared_scopes):
            scopes.append(Scope(Visibility.SHARED, key))
        return scopes
