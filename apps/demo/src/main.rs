//! Walks the foundation end to end.
//!
//! Not a runtime — there isn't one yet. This exercises each crate through
//! its public API so the behaviour can be seen rather than taken on trust,
//! and so a change that quietly weakens a boundary is visible in output as
//! well as in a test name.

use pwr_capability::{Capability, CapabilityRequest, Origin, evaluate, evaluate_untrusted_json};
use pwr_compute::{
    GpuStatus, LocalResourceSnapshot, PressureThresholds, WorkloadMetadata, classify, decide,
};
use pwr_core::{Bytes, Level, LogEvent, Measured, TraceId, hash_bytes, verify_bytes};
use pwr_memory::{MemoryMetadata, MemoryTemperature, ReconstructionCost};
use pwr_provenance::{ReceiptEnvelope, ReceiptType};
use pwr_storage::ObjectStore;

fn rule(title: &str) {
    println!("\n\x1b[1m{title}\x1b[0m");
    println!("{}", "─".repeat(title.len()));
}

fn main() {
    println!("\x1b[1mPersonal Web Runtime — foundation walkthrough\x1b[0m");

    let trace = TraceId::generate();
    println!("trace: {trace}");

    // ── capability ─────────────────────────────────────────────────────
    rule("1. Authorization: a page may ask, never decide");

    let page = Origin::WebContent {
        url: "https://example.test/checkout".to_owned(),
    };

    for (label, request) in [
        (
            "user reads a file",
            CapabilityRequest::new(Capability::Read, Origin::User, "notes.md"),
        ),
        (
            "page reads its own DOM",
            CapabilityRequest::new(Capability::Read, page.clone(), "document"),
        ),
        (
            "user spends, unauthorized",
            CapabilityRequest::new(Capability::Spend, Origin::User, "wallet"),
        ),
        (
            "user spends, authorized",
            CapabilityRequest::new(Capability::Spend, Origin::User, "wallet").authorized_by_user(),
        ),
        (
            "page installs a package",
            CapabilityRequest::new(Capability::Install, page.clone(), "malware"),
        ),
        (
            "page authorizes ITSELF to spend",
            CapabilityRequest::new(Capability::Spend, page, "wallet").authorized_by_user(),
        ),
        (
            "model output installs a package",
            CapabilityRequest::new(
                Capability::Install,
                Origin::LlmOutput {
                    model: "some-model".to_owned(),
                },
                "package",
            )
            .authorized_by_user(),
        ),
    ] {
        let decision = evaluate(&request);
        let mark = if decision.is_allow() {
            "\x1b[32mALLOW  \x1b[0m"
        } else if decision.requires_approval() {
            "\x1b[33mAPPROVE\x1b[0m"
        } else {
            "\x1b[31mDENY   \x1b[0m"
        };
        println!("  {mark} {label}");
    }

    let unknown = r#"{"schema_version":1,"trace_id":"trc_x","capability":"LAUNCH_MISSILES",
                      "origin":{"kind":"user"},"subject":"s","requested_at":0,
                      "user_authorized":true}"#;
    let decision = evaluate_untrusted_json(unknown);
    println!(
        "  \x1b[31mDENY   \x1b[0m unknown capability arriving as data: {}",
        if decision.is_deny() {
            "refused"
        } else {
            "ACCEPTED — BUG"
        }
    );

    // ── provenance ─────────────────────────────────────────────────────
    rule("2. Provenance: recorded, but not evidence");

    let receipt = ReceiptEnvelope::new(ReceiptType::Decision, "demo", trace.clone())
        .with_inputs(vec![hash_bytes(b"request")])
        .with_metadata("component", "capability");

    println!("  receipt      {}", receipt.receipt_id);
    println!("  signature    {:?}", receipt.signature_status);
    println!(
        "  attributable {}   <- this build cannot sign, so nothing it writes is evidence",
        receipt.is_attributable()
    );

    // ── storage ────────────────────────────────────────────────────────
    rule("3. Storage: content-addressed, verified on read");

    let root = std::env::temp_dir().join("pwr-demo-store");
    let store = ObjectStore::open(&root).expect("store opens");

    let hash = store.put(b"the real thing").expect("put");
    println!("  stored       {}", hash.short());
    println!(
        "  read back    {:?}",
        String::from_utf8_lossy(&store.get(&hash).expect("get"))
    );

    let a = store.put(b"identical").expect("put");
    let b = store.put(b"identical").expect("put");
    println!("  same bytes   one object: {}", a == b);

    // Corrupt it behind the store's back.
    let corrupted = hash_bytes(b"the real thing");
    match verify_bytes(b"tampered!!!", &corrupted) {
        Err(err) => println!("  corruption   detected: {err}"),
        Ok(()) => println!("  corruption   NOT DETECTED — BUG"),
    }
    let _ = std::fs::remove_dir_all(&root);

    // ── memory ─────────────────────────────────────────────────────────
    rule("4. Memory: forgetting is demotion with a cost of return");

    for (label, meta) in [
        (
            "rebuildable index",
            MemoryMetadata::new(Bytes::from_mib(64), ReconstructionCost::Free),
        ),
        (
            "recomputable embedding",
            MemoryMetadata::new(Bytes::from_mib(8), ReconstructionCost::Expensive),
        ),
        (
            "user's unsaved draft",
            MemoryMetadata::new(Bytes::from_mib(1), ReconstructionCost::Irreplaceable),
        ),
        (
            "pinned session state",
            MemoryMetadata::new(Bytes::from_mib(2), ReconstructionCost::Cheap).pinned(),
        ),
    ] {
        println!(
            "  {label:<24} {:?} -> {:?}   droppable: {}",
            meta.temperature,
            meta.cooled(),
            meta.reconstruction_cost.is_safely_droppable()
        );
    }

    let mut irreplaceable =
        MemoryMetadata::new(Bytes::from_mib(1), ReconstructionCost::Irreplaceable);
    irreplaceable.temperature = MemoryTemperature::Cold;
    println!(
        "  {:<24} {:?} -> {:?}   (stops at COLD; ARCHIVED is where rehydration stops being a guarantee)",
        "irreplaceable at COLD",
        irreplaceable.temperature,
        irreplaceable.cooled()
    );

    // ── compute ────────────────────────────────────────────────────────
    rule("5. Resources: swap is not memory, unmeasured is not idle");

    let thresholds = PressureThresholds::default();

    println!(
        "  unmeasured machine        -> {:?}   (not GREEN)",
        classify(&LocalResourceSnapshot::unknown(), &thresholds)
    );

    let mut tight = LocalResourceSnapshot::unknown();
    tight.physical_ram_total = Measured::known(Bytes::from_gib(24));
    tight.physical_ram_available = Measured::known(Bytes::ZERO);
    let before = classify(&tight, &thresholds);

    tight.swap_used = Measured::known(Bytes::from_gib(64));
    tight.swap_total = Measured::known(Bytes::from_gib(128));
    let after = classify(&tight, &thresholds);

    println!("  24GiB fully committed     -> {before:?}");
    println!(
        "  + 64GiB of swap           -> {after:?}   (unchanged: swap keeps promises by getting slower)"
    );
    println!(
        "  unprobed GPU schedulable  -> {}",
        GpuStatus::Unprobed.is_schedulable()
    );

    println!("\n  governor decisions at each pressure:");
    let cache = WorkloadMetadata::new("thumbnail cache", Bytes::from_mib(400)).disposable_cache();
    let batch = WorkloadMetadata::new("background index", Bytes::from_gib(2))
        .migratable()
        .background();
    let editor = WorkloadMetadata::new("interactive editor", Bytes::from_gib(4));

    println!(
        "    {:<22} {:<16} {:<16} {}",
        "", "cache", "background", "interactive"
    );
    for pressure in [
        pwr_compute::PressureState::Green,
        pwr_compute::PressureState::Yellow,
        pwr_compute::PressureState::Orange,
        pwr_compute::PressureState::Red,
        pwr_compute::PressureState::Critical,
    ] {
        // Width specifiers do not pad `{:?}`, so each cell is rendered
        // to a String first and then padded.
        println!(
            "    {:<22} {:<16} {:<16} {}",
            format!("{pressure:?}"),
            format!("{:?}", decide(pressure, &cache)),
            format!("{:?}", decide(pressure, &batch)),
            format!("{:?}", decide(pressure, &editor)),
        );
    }

    // ── logging ────────────────────────────────────────────────────────
    rule("6. Logging: redaction with no escape hatch");

    let event = LogEvent::new(Level::Warn, "demo", "login_attempt")
        .with_trace(trace)
        .with_field("user", "alice")
        .with_field("password", "hunter2")
        .with_field("session_id", "abc123");

    println!("  {}", event.to_json());
    println!(
        "  leaked the password: {}",
        event.to_json().contains("hunter2")
    );

    println!("\n\x1b[1mAll six behaviours above are asserted in tests.\x1b[0m");
    println!("cargo test --workspace   |   cargo test -p pwr-invariants");
}
