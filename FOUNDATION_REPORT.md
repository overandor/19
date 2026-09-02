# Foundation Report

Evidence for the first production increment.

A file existing is not an implementation. Every claim below names a source
file, a test file, a command, and what the command actually printed.

```text
FOUNDATION_STATUS: PARTIAL
```

PARTIAL, not PASS. The completion gate in the brief is met on every item
except one: CI does not build or test the Rust workspace, so "the workspace
builds" is true on this machine and unproven on any other. That is a real
gap and is the first item of the next increment rather than something to
round up.

## IMPLEMENTED_AND_VERIFIED

| Capability | Source | Tests | Command | Result |
|---|---|---|---|---|
| Content hashing, one implementation | `crates/core/src/hash.rs` | same file, 10 tests | `cargo test -p pwr-core` | ok, 41 passed |
| SHA-256 correctness vs published vector | `crates/core/src/hash.rs` | `matches_the_known_sha256_of_abc` | `cargo test -p pwr-core` | ok |
| Corruption detected on verify | `crates/core/src/hash.rs` | `corruption_is_detected` | `cargo test -p pwr-core` | ok |
| Identifiers, timestamps, schema versions | `crates/core/src/ids.rs` | same file, 8 tests | `cargo test -p pwr-core` | ok |
| Error taxonomy | `crates/core/src/error.rs` | same file, 5 tests | `cargo test -p pwr-core` | ok |
| Units, `Bytes` vs `Credits` separation | `crates/core/src/units.rs` | same file, 10 tests | `cargo test -p pwr-core` | ok |
| Credits rejected as physical capacity, **at compile time** | `crates/core/src/units.rs` (`PhysicalQuantity`) | `compile_fail` doctest | `cargo test --doc -p pwr-core` | ok, 1 passed |
| Structured logging with mandatory redaction | `crates/core/src/log.rs` | same file, 7 tests | `cargo test -p pwr-core` | ok |
| 17 capabilities, 6 consequence classes | `crates/capability/src/lib.rs` | same file, 19 tests | `cargo test -p pwr-capability` | ok, 19 passed |
| Deny-by-default policy | `crates/capability/src/lib.rs` | `a_page_may_not_reach_the_machine`, `an_unknown_capability_is_denied` | `cargo test -p pwr-capability` | ok |
| Receipt envelope, explicit signature status | `crates/provenance/src/lib.rs` | same file, 12 tests | `cargo test -p pwr-provenance` | ok, 12 passed |
| Memory temperature and demotion rules | `crates/memory/src/lib.rs` | same file, 13 tests | `cargo test -p pwr-memory` | ok, 13 passed |
| Pressure classification, configurable thresholds | `crates/compute/src/lib.rs` | same file, 17 tests | `cargo test -p pwr-compute` | ok, 17 passed |
| Resource governor decision, pure | `crates/compute/src/lib.rs` | `the_decision_is_pure`, `swap_is_a_last_resort_...` | `cargo test -p pwr-compute` | ok |
| Content-addressed store, crash-safe writes | `crates/storage/src/lib.rs` | same file, 14 tests | `cargo test -p pwr-storage` | ok, 14 passed |
| Persistence round-trip | `crates/storage/src/lib.rs` | `objects_round_trip`, `records_round_trip_...` | `cargo test -p pwr-storage` | ok |
| Schema rejection (future and malformed) | `crates/storage/src/lib.rs` | `a_future_schema_version_fails_safely`, `a_malformed_record_fails_safely` | `cargo test -p pwr-storage` | ok |
| Invariant laws | `tests/invariants/tests/laws.rs` | 19 tests | `cargo test -p pwr-invariants` | ok, 19 passed |
| Existing Python suite unbroken | `tests/` | 211 tests | `python3 -m pytest -q` | 211 passed |
| Python lint unbroken | — | — | `ruff check .` | All checks passed |

Full run:

```text
cargo fmt --all -- --check              exit 0
cargo clippy --workspace --all-targets  exit 0
cargo build --workspace                 exit 0
cargo test --workspace                  exit 0   (137 tests)
python3 -m pytest -q                    exit 0   (211 tests)
ruff check .                            exit 0
```

## IMPLEMENTED_NOT_FULLY_VERIFIED

| Item | Why not fully verified |
|---|---|
| The Rust workspace builds | Verified on this machine only. CI does not run cargo, so nothing proves it builds elsewhere. |
| `packaging/build_dmg.sh` | Syntax-checked and dry-run. `hdiutil` is macOS-only; never executed for real. |

## PARTIAL

| Item | What exists | What does not |
|---|---|---|
| Provenance | `ReceiptEnvelope`, `SignatureStatus`, correct `is_attributable()` | Nothing can sign. Every receipt this build writes is `Unsigned` and therefore not evidence. |
| Resource measurement | The snapshot type, `Measured::Unknown`, honest classification | Nothing populates it from the OS. Every field is `Unknown` until a platform probe exists. |
| Schema migration | Version probing, correct rejection of future and malformed records | Only version 1 exists, so no migration has been written or exercised. |
| Trace identity | `TraceId`, carried by `LogEvent` | Nothing propagates it through request → authorization → execution → receipt. There is no execution path. |

## NOT_IMPLEMENTED

`identity`, `web`, `web_asset`, `graph`, `archetype`, `application`,
`agent`, `ui`; capacity reservations, capacity receipts, scheduler, compute
credit ledger, remote placement; peer compute, capacity passports,
capability routing; Ollama integration; the MicroPage extension.

No crate, no stub, no placeholder directory. See BUILD_STATE.md.

## BLOCKED

| Item | Status |
|---|---|
| `cargo audit` | NOT_AVAILABLE — not installed. Not fatal; three third-party crates (`serde`, `serde_json`, `sha2`). |
| `cargo deny` | NOT_AVAILABLE — not installed. |
| `npm audit` | NOT_AVAILABLE — npm is present but there is no `package.json`. |
| macOS `.dmg` build | BLOCKED off macOS — `hdiutil` does not exist here. |

Nothing else is blocked. In particular `cargo` **can** reach crates.io from
this sandbox, which contradicts a claim in `docs/MEMORY_CREDIT_DAEMON.md`
written in a different environment. See REPOSITORY_AUDIT.md.

## Completion gate

| Requirement | Met |
|---|---|
| repository reality documented | yes — REPOSITORY_AUDIT.md |
| architecture frozen | yes — ARCHITECTURE.md |
| invariants exist | yes — INVARIANTS.md, 19 executable |
| workspace builds | yes here, **not proven in CI** |
| foundational types compile | yes |
| capability policy exists | yes |
| resource model exists | yes |
| content hashing exists | yes |
| persistence foundation exists | yes |
| tests pass | yes — 137 Rust, 211 Python |
| build state updated | yes — BUILD_STATE.md |
| nothing knowingly broken | yes — Python suite and lint unchanged |

One row is short of green, so the status is PARTIAL and the state is
resumable.
