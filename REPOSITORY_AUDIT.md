# Repository Audit

What is actually in this repository, as of 2026-09-01T22:21:34Z, on branch
`claude/nuclear-launch-innovation-seed-bvz2pa` at commit `667d3eb`.

This describes what exists. Planned work appears only in the sections that
say so.

## Languages present

| Extension | Files | Notes |
|---|---|---|
| `.json` | 69 | Mostly research artifacts and registries, not source |
| `.md` | 67 | Documentation and generated reports |
| `.py` | 46 | The working codebase |
| `.yml` / `.yaml` | 16 | GitHub Actions workflows |
| `.jsonl` | 11 | Signal history records |
| `.sh` | 3 | Packaging scripts |
| `.rs` | 9 | The Rust workspace added by this increment |
| `.html` | 1 | `index.html`, a static dashboard |

Before this increment the repository was **Python only**. There was no Rust
workspace, no crate, and no `Cargo.toml`.

## Toolchains available on this machine

Verified by running each one, not assumed:

| Tool | Version | Notes |
|---|---|---|
| `rustc` | 1.94.1 | edition 2024 supported and used |
| `cargo` | 1.94.1 | **can reach crates.io** from this sandbox |
| `python3` | 3.11.15 | |
| `node` | 22.22.2 | no JS in the repository yet |
| `npm` / `pnpm` / `yarn` | 10.9.7 / 10.33.0 / 1.22.22 | unused |
| `sqlite3` CLI | absent | Python's `sqlite3` module is present (3.45.1) |
| `wasm-pack` | absent | relevant when the WASM UI is built |

The crates.io reachability matters and contradicts an existing claim.
`docs/MEMORY_CREDIT_DAEMON.md` states that a custom Anchor program could
not be built because "cargo couldn't reach crates.io from there". That was
true of the sandbox that document was written in; it is **not** true here,
verified by fetching and compiling `serde` and `sha2`. The old statement
is not wrong about its own environment, but it should not be read as a
property of the project.

## Python packages (pre-existing)

| Package | What it is |
|---|---|
| `core/` | Ingestion, feature, hypothesis, evaluation engines and an approval gate |
| `memory_credit_daemon/` | Signed compute-reuse receipts, hash-chained ledger, SPL credits mint |
| `proof_of_avoided_work/` | Falsifiable metering: commitments, baseline oracle, audit sampling, settlement, pool solvency, mint authorization |
| `memory_shell/` | Content-addressed reuse, shared `MAP_SHARED` weights, tenant isolation, stdio remote front end |
| `scripts/` | Research automation invoked by workflows |
| `backend.py` | A FastAPI service |
| `packaging/` | macOS `.dmg` build script, installer, launchd agent |

## Test frameworks

- **pytest** — `pytest.ini` sets `testpaths = tests`, `asyncio_mode = auto`.
  211 tests, all passing.
- **cargo test** — added by this increment. 130 tests, all passing.

The two coexist: `tests/invariants/` is a Rust crate inside pytest's
`testpaths`, which is harmless because pytest only collects `test_*.py`.

## Build and CI

`.github/workflows/` holds 14 workflows. `test.yml` is the one that gates:
it installs `requirements-dev.txt`, runs `ruff check .`, then `pytest`.

**It does not build or test the Rust workspace.** Adding that is a CI
change this increment has not made; see BUILD_STATE.md.

## Generated files — do not edit by hand

- `weekly_research_reviews/`, `change_summaries/`, `evaluation_reports/`,
  `signal_discovery_reports/` — written by scheduled workflows.
- `cache/focus.json` — rewritten by the test suite on every run.
- `.last_evolve_utc`, `.last_harvest_utc`, `report.txt`, `SHASUMS256.txt`.
- `__pycache__/`, `/target/` — ignored.

## Existing architecture documentation

`REDESIGN_PLAN.md`, `docs/repo_redesign_plan.md`, `docs/RESEARCH_LAB_REDESIGN.md`
and `docs/module_architecture.md` all describe the repository's **prior**
identity as a speculative-signal research lab. They are accurate about that
system and say nothing about the runtime this increment begins.

They are left in place rather than rewritten: the research pipeline still
exists and still runs.

## Duplicated and unfinished implementations

- **Two redesign plans.** `REDESIGN_PLAN.md` (root) and
  `docs/REDESIGN_PLAN.md` overlap substantially. Neither is authoritative
  for the runtime.
- **`improvement_proposals/proposal-example.json` does not match its own
  schema.** It uses `channel`/`reference` where the schema requires
  `event_type`/`url`/`timestamp_utc`, a numeric `change_confidence` where
  the schema has an enum `confidence`, and `status: "draft_pr_open"` which
  is not in the schema's enum. The schema is authoritative; the example is
  stale.
- **Pinned dependencies masking upstream breaks.** `solana<0.40` and
  `ruff<0.16` are both pinned with recorded reasons. `main`'s last `test`
  run is red for the ruff one.
- **Empty research directories.** Many directories listed in `README.md`
  contain only a placeholder `README.md`.

## Git state

- Branch: `claude/nuclear-launch-innovation-seed-bvz2pa`
- Base: `main` at `b7f1574`
- Open PR: overandor/19#45 (draft), CI green on its head
- No uncommitted user work was present when this increment began; the
  in-progress liquidity work was committed first as `667d3eb`.

## What this audit does not claim

None of the systems in the user's brief — Personal Web Runtime, Web Capital
Browser, Web Asset Protocol, Web Capital Graph, Archetype Compiler, Liquid
Compute Treasury, Portable Application Capsules, peer compute — exist in
this repository. This increment builds the foundation they would sit on,
and BUILD_STATE.md lists them under NOT_IMPLEMENTED.
