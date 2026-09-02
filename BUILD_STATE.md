# Build State

The resumable checkpoint. Update after every production increment.

```text
SYSTEM:
Unified Personal Web / Web Capital / Compute Runtime

CURRENT_PHASE:
Foundation

STATUS:
IN_PROGRESS

LAST_VALIDATED:
2026-09-01T22:24:44Z
```

## IMPLEMENTED

Each has source, tests, and a command that passes. See FOUNDATION_REPORT.md
for the evidence table.

- **`crates/core`** — `ContentHash` (SHA-256, single implementation),
  `EntityId`/`ArtifactId`/`TraceId`, `Timestamp`, `SchemaVersion`,
  `Bytes`/`Credits`/`Measured`, the sealed `PhysicalQuantity` trait, the
  error taxonomy, and structured logging with mandatory redaction.
- **`crates/capability`** — 17 capabilities, 6 consequence classes, request
  origins, and a deny-by-default evaluator.
- **`crates/provenance`** — `ReceiptEnvelope` with explicit
  `SignatureStatus`. Unsigned only; see PARTIAL.
- **`crates/memory`** — `MemoryTemperature`, `ReconstructionCost`,
  `MemoryMetadata`, pure demotion rules. No deletion of any kind.
- **`crates/compute`** — `LocalResourceSnapshot`, `GpuStatus`,
  configurable `PressureThresholds`, `classify`, and the pure `decide`
  governor function.
- **`crates/storage`** — content-addressed object store with crash-safe
  writes, verify-on-read, and schema-versioned records.
- **`tests/invariants`** — 19 executable checks of the laws in
  INVARIANTS.md.
- **`apps/demo`** — a runnable walkthrough of every crate through its
  public API (`cargo run -p pwr-demo`), and `demo.sh`, which runs the
  whole stack: memory_shell, proof_of_avoided_work, then the foundation.
- Documentation: REPOSITORY_AUDIT.md, INVARIANTS.md, ARCHITECTURE.md,
  MEMORY_MODEL.md, COGNITIVE_RUNTIME.md, docs/adr/0001-local-persistence.md.

## PARTIAL

- **Signing.** `SignatureStatus` exists and `is_attributable()` correctly
  returns false for everything this build writes, but nothing can sign.
  `NO CONSEQUENTIAL EFFECT WITHOUT ATTRIBUTABLE RECEIPT` is therefore
  documented and half-enforced. Signing lands with `identity`.
- **Resource measurement.** `LocalResourceSnapshot` is defined and
  `LocalResourceSnapshot::unknown()` is honest, but **nothing populates it
  from the operating system**. Every field is `Unknown` until a platform
  probe exists. `classify` correctly returns `PressureState::Unknown` for
  such a snapshot.
- **Migration interface.** `load_record` rejects future and malformed
  versions correctly, but there is only version 1, so no migration has been
  written or exercised.
- **Trace identity.** `TraceId` exists and `LogEvent` carries it. Nothing
  propagates it across a request → authorization → execution → receipt
  chain, because there is no execution path.
- **CI.** `.github/workflows/test.yml` runs ruff and pytest only. It does
  **not** build or test the Rust workspace. Adding that is the first item
  of the next increment.

## NOT_IMPLEMENTED

No crate, no code, no stub. Listed because they are in the brief, not
because work has started.

- `identity` — MachineIdentity, PeerIdentity, ApplicationIdentity,
  WebsiteAssetIdentity, wallet references, signatures
- `web` — navigation, observation, semantic extraction, safe DOM patches
- `web_asset` — WebsiteAsset identity, manifests, deployments, lineage
- `graph` — canonical temporal graph, entity resolution, neighbourhoods
- `archetype` — de-resourcification, pattern extraction, lifecycle
- `application` — Portable Application Capsule, workflow cursor, writer
  epoch, effect ledger, migration
- `agent` — model-provider abstraction, intent, planning, checkpointing
- `ui` — HTML/WASM operator interface
- Capacity reservations, capacity receipts, scheduler, compute credit
  ledger, remote execution placement
- Peer compute, capacity passports, capability routing
- Ollama or any local-model integration
- The MicroPage / virtualized-browsing extension

## BLOCKED

- **Nothing is blocked on this machine.** `cargo` reaches crates.io here,
  contradicting `docs/MEMORY_CREDIT_DAEMON.md`, which describes a different
  sandbox. See REPOSITORY_AUDIT.md.
- `cargo audit` and `cargo deny` are NOT_AVAILABLE. Not installed; not
  fatal. Dependency list is three third-party crates.
- The macOS `.dmg` in `packaging/` cannot be built here — `hdiutil` is
  macOS-only. The script refuses to run off macOS rather than emitting
  something that is not a disk image.

## KNOWN_FAILURES

- **`main` is red.** Its last `test` run (30130065414) fails at the ruff
  step because ruff 0.16 widened its default rule set and
  `requirements-dev.txt` was unpinned. This branch pins `ruff<0.16` and is
  green; the repo-wide cleanup that would let the pin be lifted has not
  been done.
- **`improvement_proposals/proposal-example.json` does not validate against
  its own schema.** Pre-existing; see REPOSITORY_AUDIT.md.

## NEXT_ACTION

Identity + signed provenance + content-addressed storage:

1. Add the Rust workspace to `.github/workflows/test.yml` so `cargo fmt`,
   `clippy` and `test` gate alongside ruff and pytest.
2. `crates/identity`: keypairs, `MachineIdentity`, `PeerIdentity`.
3. Sign `ReceiptEnvelope`; make `SignatureStatus::Verified` reachable and
   turn `NO CONSEQUENTIAL EFFECT WITHOUT ATTRIBUTABLE RECEIPT` into a
   fully enforced law.
4. A platform probe that populates `LocalResourceSnapshot` on Linux and
   macOS, leaving unmeasurable fields `Unknown`.

## VALIDATION AT THIS CHECKPOINT

```text
cargo fmt --all -- --check          exit 0
cargo clippy --workspace --all-targets  exit 0
cargo build --workspace             exit 0
cargo test --workspace              exit 0   (137 tests)
python3 -m pytest -q                exit 0   (211 tests)
ruff check .                        exit 0
```
