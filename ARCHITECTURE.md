# Architecture

The target, and what of it exists.

Read this alongside `BUILD_STATE.md`, which is the authoritative list of
what is implemented. This document describes the shape; that one describes
the state.

## The idea

Today the web connects documents. A URL is a destination, and moving
between destinations means leaving one and arriving at another.

The system this repository is building toward connects **capabilities**. A
site stops being a place and becomes a cell: something that can say what it
is, what it can do, what it is permitted to do, what it will commit, and
what evidence it will produce. A request stops naming a location and starts
naming an outcome.

```text
today:      URL    → server → document
target:     intent → capability graph → allocation → execution
                   → verification → receipt
```

The consequence that matters is that a webpage stops needing to be resident
to exist. Page identity and page memory come apart:

```text
PAGE IDENTITY   persistent
PAGE MEMORY     conditional
```

A hundred pages can be visible while one is awake, the same way a list of a
million rows renders only what is on screen. That is the memory model in
`crates/memory` and, in Python, `memory_shell/`.

## Top-level flow

```text
USER / WORLD
      ↓
Conversation + Browser + Data Observation
      ↓
Production Tightener
      ↓
Semantic / Resource Normalization
      ↓
Web Capital Graph
      ↓
Archetype Compiler
      ↓
Personal Web Runtime
      ↓
Capability Bus            ← crates/capability (foundation exists)
      ↓
Resource Governor         ← crates/compute (foundation exists)
      ↓
Liquid Compute Treasury
      ↓
Local / Remote Physical Execution
      ↓
Receipts                  ← crates/provenance (unsigned only)
      ↓
Outcome Measurement
      ↓
Provenance
      ↓
Compression / Hyper-Forgetting  ← crates/memory (classification only)
      ↓
Selective Expansion
```

Four boxes have foundations. The rest do not exist.

## Domain boundaries

Each is a module with one owner. Marked with what exists today.

| Domain | Owns | State |
|---|---|---|
| `core` | ids, content hashing, units, errors, trace | **implemented** |
| `capability` | Capability, request, decision, consequence class | **implemented** |
| `provenance` | receipt envelopes, signature status | **implemented, unsigned** |
| `memory` | HOT/WARM/COOL/COLD, budgets, hyper-forgetting, rehydration | **classification only** |
| `storage` | content-addressed objects, manifests, integrity | **implemented** |
| `compute` | capacity, reservations, capacity receipts, scheduler, credit, placement | **snapshot + governor decision only** |
| `identity` | MachineIdentity, PeerIdentity, ApplicationIdentity, WebsiteAssetIdentity, signatures | not implemented |
| `web` | navigation, observation, semantic extraction, safe DOM patches | not implemented |
| `web_asset` | persistent WebsiteAsset identity, manifests, deployments, ownership lineage | not implemented |
| `graph` | canonical temporal graph, relationships, entity resolution | not implemented |
| `archetype` | de-resourcification, canonical primitives, pattern extraction | not implemented |
| `application` | Portable Application Capsule, workflow cursor, writer epoch, effect ledger | not implemented |
| `agent` | model-provider abstraction, intent, planning, checkpointing | not implemented |
| `ui` | local HTML/WASM operator interface, browser view, graph view | not implemented |

Crates exist only for the implemented rows. An empty crate is not a
placeholder for work, it is a claim that work has started.

## Where the existing Python fits

Two Python packages are not incidental to this architecture — they are
early implementations of parts of it, built before the Rust foundation and
still the only working versions.

**`memory_shell/`** is the memory domain, in the specific form of an LLM
serving cache. Shared `MAP_SHARED` weights, content-addressed KV reuse
under a byte budget, refcounted eviction, and per-tenant isolation so that
sharing a cache is not an oracle about other people's prompts. It measures
64.1MiB of real RSS where eight private copies would cost 512MiB.

**`proof_of_avoided_work/`** is the part of the compute domain that answers
*"was this work actually avoided?"* — and it earns a specific place in the
target architecture. If a result already exists and is still valid, the
cheapest executor of a job is **nobody**. That makes memory a competitor to
computation rather than a subordinate of it, and it means the system must
be able to tell a genuine reuse from a claimed one. Signed self-reports
cannot: the baseline is supplied by the party being paid. So reuse claims
are pinned to re-executable commitments, priced against an oracle the
claimant does not control, and audited by sampled re-execution at a rate
that makes fraud negative-EV without re-executing everything.

The two compose: the shell produces the measurements, the metering verifies
them. A cache miss is a timed cold execution — a baseline sample. A hit is a
timed reuse — a claim. The component that saves the work is the one that
honestly measures the saving.

Neither is wired into the Rust workspace, and nothing in the workspace
imports them. Reconciling the two is future work, not a claim.

## What is deliberately absent

The brief describes a graph of independently owned cells, capacity
passports, peer compute, and settlement across them. None of that is here,
and this increment does not sketch it in code.

The reason is the failure mode it avoids. A capability graph with no
capability model is a routing table that will route anything. A compute
treasury with no distinction between a credit and a byte will eventually
promise capacity that does not exist. A receipt system that cannot sign
produces records nobody can be held to. Each of those is much harder to
retrofit than to establish, which is why this increment is the
authorization language, the units, the receipt envelope, and the resource
model — and nothing above them.
