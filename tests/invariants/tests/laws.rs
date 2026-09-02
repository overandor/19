//! Executable checks that the laws in `INVARIANTS.md` actually hold.
//!
//! These are not unit tests of a module. Each one names a law and tries to
//! break it through the public API, so that a future change which quietly
//! weakens a boundary fails here rather than in production. Where a law can
//! be enforced by the type system instead, it is — see the `compile_fail`
//! doctest on `pwr_core::units::PhysicalQuantity`, which proves that credits
//! cannot be passed where physical capacity is required.
//!
//! Laws that cannot yet be checked are listed at the bottom of this file
//! with the reason, rather than being silently absent.

use pwr_capability::{
    Capability, CapabilityRequest, ConsequenceClass, Origin, evaluate, evaluate_untrusted_json,
};
use pwr_compute::{GpuStatus, LocalResourceSnapshot, PressureState, PressureThresholds, classify};
use pwr_core::{Bytes, CoreError, Measured, PhysicalQuantity, hash_bytes, verify_bytes};
use pwr_memory::{MemoryMetadata, MemoryTemperature, ReconstructionCost};
use pwr_provenance::{ReceiptEnvelope, ReceiptType, SignatureStatus};
use pwr_storage::{StoredRecord, load_record};

// ── USER = AUTHORITY ROOT ───────────────────────────────────────────────────

#[test]
fn law_only_the_user_is_an_authority_root() {
    for origin in [
        Origin::WebContent {
            url: "https://example.test".to_owned(),
        },
        Origin::LlmOutput {
            model: "any".to_owned(),
        },
        Origin::Peer {
            peer_id: "peer".to_owned(),
        },
    ] {
        assert!(
            !origin.may_hold_native_authority(),
            "{} must not be an authority root",
            origin.label()
        );
    }
    assert!(Origin::User.may_hold_native_authority());
}

// ── WEB CONTENT != MACHINE AUTHORITY ────────────────────────────────────────

#[test]
fn law_web_origin_native_authority_is_denied() {
    let page = Origin::WebContent {
        url: "https://example.test/evil".to_owned(),
    };
    for capability in [
        Capability::Write,
        Capability::Install,
        Capability::Publish,
        Capability::Spend,
        Capability::Delete,
        Capability::Sign,
        Capability::Transfer,
        Capability::Build,
        Capability::RunTests,
        Capability::Store,
        Capability::Network,
        Capability::Infer,
    ] {
        let request = CapabilityRequest::new(capability, page.clone(), "target");
        assert!(
            evaluate(&request).is_deny(),
            "{capability:?} must be denied to web content"
        );
    }
}

#[test]
fn law_a_page_cannot_grant_itself_authority() {
    let request = CapabilityRequest::new(
        Capability::Spend,
        Origin::WebContent {
            url: "https://example.test".to_owned(),
        },
        "wallet",
    )
    .authorized_by_user();
    assert!(
        evaluate(&request).is_deny(),
        "setting the authorization flag on your own request is the attack"
    );
}

// ── LLM OUTPUT != AUTHORIZATION ─────────────────────────────────────────────

#[test]
fn law_model_output_is_a_proposal_not_a_grant() {
    let request = CapabilityRequest::new(
        Capability::Install,
        Origin::LlmOutput {
            model: "some-model".to_owned(),
        },
        "package",
    )
    .authorized_by_user();
    assert!(evaluate(&request).is_deny());
}

// ── DATA != INSTRUCTION ─────────────────────────────────────────────────────

#[test]
fn law_unknown_capability_cannot_execute() {
    // An unrecognised capability arriving as data must not be interpreted
    // as an instruction to do something.
    for body in [
        r#"{"schema_version":1,"trace_id":"trc_x","capability":"LAUNCH","origin":{"kind":"user"},"subject":"s","requested_at":0}"#,
        r#"{"schema_version":1,"trace_id":"trc_x","capability":"*","origin":{"kind":"user"},"subject":"s","requested_at":0}"#,
        r#"{"schema_version":1,"trace_id":"trc_x","capability":"read","origin":{"kind":"user"},"subject":"s","requested_at":0}"#,
    ] {
        assert!(
            evaluate_untrusted_json(body).is_deny(),
            "unknown capability must be denied, not guessed at: {body}"
        );
    }
}

#[test]
fn law_malformed_requests_are_denied_not_repaired() {
    for body in ["", "{", "null", "[]", r#"{"capability":"READ"}"#] {
        assert!(evaluate_untrusted_json(body).is_deny(), "{body:?}");
    }
}

// ── NO SILENT PRIVILEGE EXPANSION ───────────────────────────────────────────

#[test]
fn law_consequential_capabilities_never_allow_silently() {
    for capability in [
        Capability::Write,
        Capability::Network,
        Capability::Install,
        Capability::Publish,
        Capability::Sign,
        Capability::Spend,
        Capability::Delete,
        Capability::Transfer,
    ] {
        let request = CapabilityRequest::new(capability, Origin::User, "target");
        let decision = evaluate(&request);
        assert!(
            !decision.is_allow(),
            "{capability:?} was allowed without explicit authorization"
        );
    }
}

#[test]
fn law_native_authority_starts_at_local_effect() {
    for capability in [Capability::Read, Capability::Navigate, Capability::PatchDom] {
        assert!(!capability.is_native_authority());
        assert!(capability.consequence() < ConsequenceClass::LocalEffect);
    }
}

// ── NO CONSEQUENTIAL EFFECT WITHOUT ATTRIBUTABLE RECEIPT ────────────────────

#[test]
fn law_unsigned_receipts_are_not_attributable() {
    let receipt = ReceiptEnvelope::new(
        ReceiptType::Effect,
        "runtime",
        pwr_core::TraceId::generate(),
    );
    assert_eq!(receipt.signature_status, SignatureStatus::Unsigned);
    assert!(
        !receipt.is_attributable(),
        "this build cannot sign, so it must not present its receipts as evidence"
    );
}

#[test]
fn law_an_unchecked_signature_is_not_attribution() {
    let mut receipt = ReceiptEnvelope::new(
        ReceiptType::Settlement,
        "runtime",
        pwr_core::TraceId::generate(),
    );
    receipt.signature_status = SignatureStatus::Signed;
    assert!(!receipt.is_attributable());
    receipt.signature_status = SignatureStatus::Invalid;
    assert!(!receipt.is_attributable());
    receipt.signature_status = SignatureStatus::Verified;
    assert!(receipt.is_attributable());
}

// ── malformed persisted state is rejected ───────────────────────────────────

#[test]
fn law_malformed_persisted_state_is_rejected() {
    #[derive(serde::Serialize, serde::Deserialize)]
    struct Payload {
        value: u32,
    }

    assert!(load_record::<Payload>("{not json").is_err());
    assert!(load_record::<Payload>(r#"{"payload":{"value":1}}"#).is_err());
    assert!(matches!(
        load_record::<Payload>(r#"{"schema_version":999,"payload":{"value":1}}"#),
        Err(CoreError::UnsupportedSchema { .. })
    ));

    let good = serde_json::to_string(&StoredRecord::new(Payload { value: 7 })).unwrap();
    assert_eq!(load_record::<Payload>(&good).unwrap().payload.value, 7);
}

#[test]
fn law_corrupted_content_is_detected() {
    let hash = hash_bytes(b"the real thing");
    assert!(verify_bytes(b"the real thing", &hash).is_ok());
    assert!(matches!(
        verify_bytes(b"something else", &hash),
        Err(CoreError::Integrity { .. })
    ));
}

// ── COMPUTE CREDIT != PHYSICAL COMPUTE ──────────────────────────────────────

#[test]
fn law_only_physical_quantities_can_be_reserved() {
    // The compiler enforces the other half: passing `Credits` to this
    // function does not compile. See the `compile_fail` doctest on
    // `pwr_core::units::PhysicalQuantity`, which `cargo test --doc` runs.
    fn reserve<T: PhysicalQuantity>(amount: T) -> u64 {
        amount.magnitude()
    }
    assert_eq!(reserve(Bytes::from_gib(2)), 2 * 1024 * 1024 * 1024);
}

// ── SSD != RAM-CLASS PERFORMANCE ────────────────────────────────────────────

#[test]
fn law_swap_is_never_counted_as_memory() {
    let mut snapshot = LocalResourceSnapshot::unknown();
    snapshot.physical_ram_total = Measured::known(Bytes::from_gib(24));
    // Fully committed, so the classification is unambiguous and the only
    // thing the assertion below can be measuring is the effect of swap.
    snapshot.physical_ram_available = Measured::known(Bytes::ZERO);

    let without_swap = classify(&snapshot, &PressureThresholds::default());

    snapshot.swap_used = Measured::known(Bytes::from_gib(64));
    snapshot.swap_total = Measured::known(Bytes::from_gib(128));
    let with_swap = classify(&snapshot, &PressureThresholds::default());

    assert_eq!(
        without_swap, with_swap,
        "adding 64GiB of swap must not relieve memory pressure; swap is not RAM"
    );
    assert_eq!(with_swap, PressureState::Critical);
}

// ── REMOTE VRAM != LOCAL VRAM ───────────────────────────────────────────────

#[test]
fn law_unprobed_hardware_is_not_schedulable() {
    assert!(!GpuStatus::Unprobed.is_schedulable());
    assert!(!GpuStatus::Absent.is_schedulable());
    assert!(
        GpuStatus::Available {
            total: Bytes::from_gib(24),
            free: Measured::known(Bytes::from_gib(20))
        }
        .is_schedulable()
    );
}

#[test]
fn law_an_unmeasured_machine_is_not_reported_as_idle() {
    assert_eq!(
        classify(
            &LocalResourceSnapshot::unknown(),
            &PressureThresholds::default()
        ),
        PressureState::Unknown
    );
}

// ── RECONSTRUCTABLE STATE != HOT STATE ──────────────────────────────────────

#[test]
fn law_irreplaceable_state_never_cools_past_recoverable() {
    let mut meta = MemoryMetadata::new(Bytes::from_mib(1), ReconstructionCost::Irreplaceable);
    meta.temperature = MemoryTemperature::Cold;
    assert!(!meta.may_cool());
    assert_eq!(meta.cooled(), MemoryTemperature::Cold);
}

#[test]
fn law_only_freely_reconstructable_state_may_be_dropped() {
    assert!(ReconstructionCost::Free.is_safely_droppable());
    for cost in [
        ReconstructionCost::Cheap,
        ReconstructionCost::Moderate,
        ReconstructionCost::Expensive,
        ReconstructionCost::Irreplaceable,
    ] {
        assert!(!cost.is_safely_droppable(), "{cost:?}");
    }
}

#[test]
fn law_pinned_state_is_never_demoted() {
    let meta = MemoryMetadata::new(Bytes::from_mib(1), ReconstructionCost::Free).pinned();
    assert!(!meta.may_cool());
    assert_eq!(meta.cooled(), MemoryTemperature::Hot);
}

// ── Laws not yet executable, and why ────────────────────────────────────────
//
// WEBSITE IDENTITY    != DOMAIN          — needs the `web_asset` crate.
// APPLICATION IDENTITY!= MACHINE         — needs the `application` crate.
// CAPACITY RECEIPT    != PHYSICAL COMPUTE— needs capacity reservations.
// NO PHYSICAL DOUBLE RESERVATION         — needs a reservation ledger.
//
// None of those crates exist in this increment. They are listed in
// BUILD_STATE.md under NOT_IMPLEMENTED rather than represented by empty
// modules, because a directory is not an implementation and an absent test
// is more honest than a vacuous one.
