# Invariants

Laws the system must not break. Each one exists because breaking it is
cheap, tempting, and produces a failure that looks like something else.

Where a law is enforced in code, the enforcement is named. Where it is not
yet enforceable, that is stated rather than left ambiguous — an invariant
nobody checks is a comment.

Executable checks live in `tests/invariants/tests/laws.rs`, run by
`cargo test -p pwr-invariants`.

---

## Authority

### `USER = AUTHORITY ROOT`

Only the person operating the machine can originate authority. Everything
else acts on delegation, and delegation is explicit.

*Enforced:* `Origin::may_hold_native_authority` — true only for `User` and
`System`. `law_only_the_user_is_an_authority_root`.

### `WEB CONTENT != MACHINE AUTHORITY`

A page may ask. It may never decide. Content arriving over the network is
data about the world, not an instruction to the machine.

*Enforced:* `pwr_capability::evaluate` denies any capability at
`LocalEffect` or above from `Origin::WebContent`.
`law_web_origin_native_authority_is_denied`.

### `LLM OUTPUT != AUTHORIZATION`

A model proposes. A person authorizes. A convincing plan is still a
proposal, and the fact that a model produced it is not evidence for it.

*Enforced:* `CapabilityRequest::explicitly_authorized` returns false for
any origin other than `User`, so a request cannot carry its own grant.
`law_model_output_is_a_proposal_not_a_grant`.

### `DATA != INSTRUCTION`

Text that arrived from somewhere is not a command. Unrecognised input is
denied, never guessed at.

*Enforced:* `Capability` is a closed enum; `evaluate_untrusted_json`
turns an unknown capability into a `Deny` rather than a parse error handled
elsewhere. `law_unknown_capability_cannot_execute`.

### `NO SILENT PRIVILEGE EXPANSION`

Nothing consequential is ever allowed without an explicit decision. The
default is deny, and every other answer is earned.

*Enforced:* `law_consequential_capabilities_never_allow_silently`.

---

## Identity

### `WEBSITE IDENTITY != DOMAIN`

A domain is a lease on a name. The thing it points at has its own identity,
which survives the name changing hands.

*Not yet enforceable.* Needs the `web_asset` crate, which does not exist.

### `APPLICATION IDENTITY != MACHINE`

An application is not the box it happens to be running on. It can move; the
machine cannot follow it.

*Not yet enforceable.* Needs the `application` crate, which does not exist.

---

## Physics

These four are the same mistake in different clothes: reporting a larger
number than the hardware has.

### `COMPUTE CREDIT != PHYSICAL COMPUTE`

A credit is an accounting entry. A byte of RAM is a physical fact. They are
both numbers, and a system where they can meet as bare integers will
eventually add one to the other.

*Enforced by the type system:* `Bytes` and `Credits` are distinct types with
no conversion between them, and the sealed `PhysicalQuantity` trait is
implemented for `Bytes` alone. The `compile_fail` doctest on
`pwr_core::units::PhysicalQuantity` proves that handing `Credits` to a
capacity function does not compile — `cargo test --doc` runs it.

### `CAPACITY RECEIPT != PHYSICAL COMPUTE`

A promise that capacity exists is not capacity. A receipt describes what
someone undertook, not what a machine can currently do.

*Not yet enforceable.* Needs capacity reservations, which do not exist.

### `NO PHYSICAL DOUBLE RESERVATION`

The same physical resource must not be promised twice. Two valid-looking
reservations against one GPU is how a scheduler produces work nobody can
run.

*Not yet enforceable.* Needs a reservation ledger, which does not exist.

### `REMOTE VRAM != LOCAL VRAM`

Another machine's memory is not this machine's memory, and hardware nobody
measured is not hardware that works.

*Enforced:* `LocalResourceSnapshot` holds only local measurements;
`GpuStatus::Unprobed` is distinct from `Absent` and is not schedulable; an
unmeasured machine classifies as `PressureState::Unknown`, never `Green`.
`law_unprobed_hardware_is_not_schedulable`,
`law_an_unmeasured_machine_is_not_reported_as_idle`.

### `SSD != RAM-CLASS PERFORMANCE`

Swap keeps a promise by getting slower. Presenting it as memory means
committing to work at a speed the hardware cannot deliver.

*Enforced:* swap is a separate field never summed with RAM, and pressure
classification ignores it entirely.
`law_swap_is_never_counted_as_memory` adds 64GiB of swap to a fully
committed machine and asserts the pressure state does not move.

---

## Memory

### `RECONSTRUCTABLE STATE != HOT STATE`

Most of what a long-running runtime holds can be derived again. Holding it
because it might be wanted is how the working set disappears.

*Enforced:* `ReconstructionCost::is_safely_droppable` is true only for
`Free`; irreplaceable state may not cool past `Cold`; pinned state never
cools. `law_irreplaceable_state_never_cools_past_recoverable`,
`law_only_freely_reconstructable_state_may_be_dropped`,
`law_pinned_state_is_never_demoted`.

---

## Provenance

### `NO CONSEQUENTIAL EFFECT WITHOUT ATTRIBUTABLE RECEIPT`

If something happened and nobody can be held to it, it should not have
happened.

*Partially enforced.* `ReceiptEnvelope` records effects, but this build
**cannot sign**, so `SignatureStatus` is `Unsigned` and
`is_attributable()` returns false for everything it writes. That is the
honest state: receipts exist, attribution does not.
`law_unsigned_receipts_are_not_attributable`,
`law_an_unchecked_signature_is_not_attribution`.

Signing lands with the identity crate in the next increment. Until then
nothing in this system may treat a receipt as evidence.
