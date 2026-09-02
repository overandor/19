# Memory Model

Where state lives, and what happens when it will not fit.

## The tiers

```text
24 GB PHYSICAL RAM
=
FAST HOT WORKING SET
```

24GiB is the **reference target** this model is designed against, not a
measured property of any particular machine. The runtime measures rather
than assumes — `LocalResourceSnapshot` reports what is actually there and
`PressureThresholds` are configurable — because a figure that means trouble
on a 16GiB laptop is unremarkable on a 512GiB server.

### RAM — the hot working set

RAM is for what is being used *now*:

- current code
- interactive browser state
- current agents
- active graph neighbourhoods
- hot indexes
- current model/runtime state
- unresolved capability and effect state

The last one is easy to miss and important: a capability request that has
been made and not yet decided, or an effect that has started and not yet
produced a receipt, is unresolved. Paging that out is how a system loses
track of what it was in the middle of doing.

### SSD — everything durable and everything rebuildable

- repositories
- artifacts
- content-addressed objects
- application capsules
- provenance and receipts
- cold histories
- checkpoints
- warm and rebuildable indexes
- models
- bounded swap

### Remote peers — work that can leave

Appropriate when the work is genuinely migratable:

- GPU-heavy inference
- large-model inference
- independent builds
- independent tests
- large graph analysis
- optional storage

"Migratable" is a real property, not an optimistic one. Work holding local
handles, live user input, or private state cannot move, and
`WorkloadMetadata::migratable` defaults to false.

## The pressure ladder

```text
release disposable cache
→ compress
→ checkpoint
→ hyper-forget reconstructable state
→ migrate heavy workload
→ bounded swap
→ throttle
```

Ordered by what it costs the user. Dropping a cache costs a recomputation
nobody notices. Swapping costs every subsequent operation, and a runtime
that reaches for it early feels broken in a way that is hard to diagnose —
which is why it sits second from the end, reached only when the user is
waiting and nothing else remains.

Implemented in `pwr_compute::decide`, as a pure function. It returns a
decision; it does not free, migrate or throttle anything. The component
that acts on decisions does not exist yet, and the ladder is worth arguing
with before anything obeys it.

## The rule that does the work

```text
SSD != RAM-CLASS PERFORMANCE
```

Swap is never added to RAM, never reported as capacity, and never relieves
pressure in the classifier. `law_swap_is_never_counted_as_memory` adds
64GiB of swap to a fully committed machine and asserts the pressure state
does not move.

The reason is not tidiness. A scheduler told it has 24GiB of RAM and 128GiB
of swap, and allowed to add them, will commit to work at a speed the
hardware cannot deliver, and the resulting failure presents as everything
being mysteriously slow rather than as an over-commitment.

The same applies upward: another machine's VRAM is not this machine's, and
`LocalResourceSnapshot` holds only local measurements. Hardware nobody
probed is `GpuStatus::Unprobed`, which is not schedulable — distinct from
`Absent`, and distinct from zero.

## Forgetting

```text
HOT → WARM → COOL → COLD → ARCHIVED
```

Demotion is governed by what it would cost to come back, not by size:

| Reconstruction cost | May be dropped? | Floor |
|---|---|---|
| `Free` | yes | — |
| `Cheap` | no, write first | `Archived` |
| `Moderate` | no, write first | `Archived` |
| `Expensive` | no, write first | `Archived` |
| `Irreplaceable` | **never** | `Cold` |

Irreplaceable state stops at `Cold` because `Archived` is where rehydration
stops being a guarantee. Pinned state never cools at all, whatever the
pressure.

Forgetting is demotion with a recorded cost of return. It is not deletion,
and this increment implements no automatic deletion of any kind.
