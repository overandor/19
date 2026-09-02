"""memory_shell — a sandboxed shell that cuts an LLM server's resident memory.

Two mechanisms, in order of how much they save:

* **Shared weights.** One `MAP_SHARED` mapping per model file instead of a
  private copy per worker. This is the bulk of the saving and it leaks
  nothing, because weights carry no tenant data.
* **Content-addressed reuse.** KV and prefix state named by the hash of
  its contents, so identical state has one physical copy, refcounted so a
  block in use is never evicted, under a byte budget with per-tenant
  quotas.

The "secure" is load-bearing rather than decorative. A shared cache is an
information leak unless sharing is scoped: a fast response tells a prober
that someone else cached that exact content. So state derived from tenant
input is private by default and identical bytes from two tenants are
stored twice on purpose; only weights and explicitly declared-public
prefixes cross the boundary. See `isolation.py`.

It also closes the loop for `proof_of_avoided_work`: a cache miss is a
timed cold execution (a baseline sample) and a hit is a reuse claim with a
measured cost. The component that saves the memory is the one that
honestly measures the saving.
"""

from .blocks import (
    Accounting,
    Block,
    BlockRef,
    content_id,
    resident_set_bytes,
)
from .isolation import (
    WEIGHTS_SCOPE,
    AccessDenied,
    IsolationPolicy,
    Scope,
    Tenant,
    Visibility,
)
from .shell import MemoryShell, Session, ShellStats, WorkResult
from .store import BlockStore, BudgetExceeded, EvictionRecord
from .weights import SharedWeights, WeightRegistry, measure_sharing

__all__ = [
    "WEIGHTS_SCOPE",
    "AccessDenied",
    "Accounting",
    "Block",
    "BlockRef",
    "BlockStore",
    "BudgetExceeded",
    "EvictionRecord",
    "IsolationPolicy",
    "MemoryShell",
    "Scope",
    "Session",
    "SharedWeights",
    "ShellStats",
    "Tenant",
    "Visibility",
    "WeightRegistry",
    "WorkResult",
    "content_id",
    "measure_sharing",
    "resident_set_bytes",
]
