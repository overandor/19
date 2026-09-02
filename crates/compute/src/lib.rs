//! Local resources: what is actually there, how tight it is, what to do.
//!
//! Two invariants shape this module more than anything else:
//!
//! ```text
//! SSD           != RAM-CLASS PERFORMANCE
//! REMOTE VRAM   != LOCAL VRAM
//! ```
//!
//! Both are the same temptation: report a bigger number than the machine
//! has. Swap is presented as memory, a peer's GPU is presented as capacity,
//! and the scheduler then commits to work the hardware cannot do at the
//! speed the plan assumed. So swap is a separate field that is never added
//! to RAM, remote capacity does not appear in a *local* snapshot at all,
//! and anything unmeasured is [`Measured::Unknown`] rather than zero.
//!
//! Zero is the dangerous default. A GPU reported as 0 bytes and a GPU that
//! was never probed are different facts, and only one of them means "do not
//! schedule here".
//!
//! Everything here is pure. [`decide`] returns a [`ResourceDecision`]; it
//! frees nothing, migrates nothing and throttles nothing. The component
//! that acts on the decision is a later increment.

use pwr_core::{Bytes, Measured, Timestamp};
use serde::{Deserialize, Serialize};

/// What is known about the GPU, which on many machines is "nothing".
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case", tag = "status")]
pub enum GpuStatus {
    /// No GPU, confirmed.
    Absent,
    /// A GPU exists and this much of its memory is free.
    Available { total: Bytes, free: Measured<Bytes> },
    /// Nobody has looked. Not the same as `Absent`.
    Unprobed,
}

impl GpuStatus {
    /// Whether GPU work may be scheduled locally.
    ///
    /// `Unprobed` is false: scheduling against unmeasured hardware is how a
    /// plan commits to capacity that may not exist.
    pub const fn is_schedulable(&self) -> bool {
        matches!(self, Self::Available { .. })
    }
}

/// A measurement of this machine at one moment.
///
/// Every field is either a real measurement or explicitly unknown. Nothing
/// is inferred, and nothing is filled in with a plausible default.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LocalResourceSnapshot {
    pub physical_ram_total: Measured<Bytes>,
    pub physical_ram_available: Measured<Bytes>,
    /// Reported separately from RAM and never summed with it.
    pub swap_used: Measured<Bytes>,
    pub swap_total: Measured<Bytes>,
    pub cpu_count: Measured<u32>,
    pub disk_total: Measured<Bytes>,
    pub disk_available: Measured<Bytes>,
    pub gpu_status: GpuStatus,
    pub timestamp: Timestamp,
}

impl LocalResourceSnapshot {
    /// A snapshot that knows nothing. The honest starting point.
    pub fn unknown() -> Self {
        Self {
            physical_ram_total: Measured::Unknown,
            physical_ram_available: Measured::Unknown,
            swap_used: Measured::Unknown,
            swap_total: Measured::Unknown,
            cpu_count: Measured::Unknown,
            disk_total: Measured::Unknown,
            disk_available: Measured::Unknown,
            gpu_status: GpuStatus::Unprobed,
            timestamp: Timestamp::now(),
        }
    }

    /// The fraction of RAM in use, if both figures were measured.
    pub fn ram_used_fraction(&self) -> Option<f64> {
        let total = self.physical_ram_total.as_ref()?;
        let available = self.physical_ram_available.as_ref()?;
        if total.get() == 0 {
            return None;
        }
        let used = total.saturating_sub(*available);
        Some(used.fraction_of(*total))
    }

    /// RAM plus swap is **not** a capacity figure and this method does not
    /// exist. If you came here looking for it, see `INVARIANTS.md`:
    /// `SSD != RAM-CLASS PERFORMANCE`.
    pub fn swap_in_use(&self) -> bool {
        self.swap_used.as_ref().is_some_and(|used| used.get() > 0)
    }
}

/// Thresholds for turning a measurement into a pressure state.
///
/// Configurable because they are not universal. A figure that means trouble
/// on a 16GiB laptop is unremarkable on a 512GiB server, and hard-coding
/// one machine's numbers would make the classifier confidently wrong
/// everywhere else.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct PressureThresholds {
    pub yellow_used_fraction: f64,
    pub orange_used_fraction: f64,
    pub red_used_fraction: f64,
    pub critical_used_fraction: f64,
}

impl Default for PressureThresholds {
    fn default() -> Self {
        Self {
            yellow_used_fraction: 0.70,
            orange_used_fraction: 0.82,
            red_used_fraction: 0.90,
            critical_used_fraction: 0.96,
        }
    }
}

impl PressureThresholds {
    /// Whether the thresholds ascend. Out-of-order thresholds silently
    /// make one state unreachable, so callers can check rather than find out.
    pub fn is_monotonic(&self) -> bool {
        self.yellow_used_fraction < self.orange_used_fraction
            && self.orange_used_fraction < self.red_used_fraction
            && self.red_used_fraction < self.critical_used_fraction
    }
}

/// How tight things are.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum PressureState {
    Green,
    Yellow,
    Orange,
    Red,
    Critical,
    /// Nothing was measured. Deliberately not `Green`.
    Unknown,
}

/// Classify a snapshot.
///
/// An unmeasurable machine returns [`PressureState::Unknown`], never
/// `Green`. "We did not look" and "there is plenty" are different answers,
/// and conflating them means the first machine that fails to report gets
/// scheduled as though it were idle.
pub fn classify(
    snapshot: &LocalResourceSnapshot,
    thresholds: &PressureThresholds,
) -> PressureState {
    let Some(used) = snapshot.ram_used_fraction() else {
        return PressureState::Unknown;
    };
    if used >= thresholds.critical_used_fraction {
        PressureState::Critical
    } else if used >= thresholds.red_used_fraction {
        PressureState::Red
    } else if used >= thresholds.orange_used_fraction {
        PressureState::Orange
    } else if used >= thresholds.yellow_used_fraction {
        PressureState::Yellow
    } else {
        PressureState::Green
    }
}

/// What a workload is and what it would cost to move it.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct WorkloadMetadata {
    pub label: String,
    pub footprint: Bytes,
    /// Whether this can run somewhere else at all. Anything holding local
    /// handles, user input, or private state cannot.
    pub migratable: bool,
    /// Whether its state can be written and rebuilt.
    pub checkpointable: bool,
    /// Whether its memory is a cache that can simply be dropped.
    pub disposable_cache: bool,
    /// How much the user is waiting on it, in `[0, 1]`.
    pub interactive_weight: f64,
}

impl WorkloadMetadata {
    pub fn new(label: impl Into<String>, footprint: Bytes) -> Self {
        Self {
            label: label.into(),
            footprint,
            migratable: false,
            checkpointable: false,
            disposable_cache: false,
            interactive_weight: 1.0,
        }
    }

    #[must_use]
    pub fn migratable(mut self) -> Self {
        self.migratable = true;
        self
    }

    #[must_use]
    pub fn checkpointable(mut self) -> Self {
        self.checkpointable = true;
        self
    }

    #[must_use]
    pub fn disposable_cache(mut self) -> Self {
        self.disposable_cache = true;
        self
    }

    #[must_use]
    pub fn background(mut self) -> Self {
        self.interactive_weight = 0.0;
        self
    }
}

/// What the governor thinks should happen. Nothing acts on this yet.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ResourceDecision {
    KeepLocal,
    ReleaseCache,
    Compress,
    Checkpoint,
    Migrate,
    AllowBoundedSwap,
    Throttle,
    Deny,
}

/// Decide what to do with one workload at one pressure.
///
/// The order of the arms is the pressure ladder from the memory model, and
/// it is ordered by what it costs the user: drop what is free to drop,
/// then compress, then checkpoint, then move work off the machine, and only
/// then reach for swap. Swap is second-to-last on purpose — it is the point
/// where the machine keeps its promises by getting slower, and a runtime
/// that reaches for it early feels broken in a way that is hard to
/// diagnose.
///
/// `Unknown` pressure is treated conservatively rather than optimistically:
/// an unmeasured machine gets `KeepLocal` for interactive work and
/// `Throttle` for background work, because expanding usage on a machine
/// nobody can see is how an unmeasured box falls over.
pub fn decide(pressure: PressureState, workload: &WorkloadMetadata) -> ResourceDecision {
    match pressure {
        PressureState::Green => ResourceDecision::KeepLocal,

        PressureState::Unknown => {
            if workload.interactive_weight > 0.0 {
                ResourceDecision::KeepLocal
            } else {
                ResourceDecision::Throttle
            }
        }

        PressureState::Yellow => {
            if workload.disposable_cache {
                ResourceDecision::ReleaseCache
            } else {
                ResourceDecision::KeepLocal
            }
        }

        PressureState::Orange => {
            if workload.disposable_cache {
                ResourceDecision::ReleaseCache
            } else if workload.checkpointable {
                ResourceDecision::Compress
            } else {
                ResourceDecision::KeepLocal
            }
        }

        PressureState::Red => {
            if workload.disposable_cache {
                ResourceDecision::ReleaseCache
            } else if workload.migratable && workload.interactive_weight < 0.5 {
                ResourceDecision::Migrate
            } else if workload.checkpointable {
                ResourceDecision::Checkpoint
            } else {
                ResourceDecision::Throttle
            }
        }

        PressureState::Critical => {
            if workload.disposable_cache {
                ResourceDecision::ReleaseCache
            } else if workload.migratable {
                ResourceDecision::Migrate
            } else if workload.checkpointable {
                ResourceDecision::Checkpoint
            } else if workload.interactive_weight > 0.0 {
                // The user is waiting and nothing else can be done. Slower
                // is better than killed.
                ResourceDecision::AllowBoundedSwap
            } else {
                ResourceDecision::Deny
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn snapshot(total_gib: u64, available_gib: u64) -> LocalResourceSnapshot {
        LocalResourceSnapshot {
            physical_ram_total: Measured::known(Bytes::from_gib(total_gib)),
            physical_ram_available: Measured::known(Bytes::from_gib(available_gib)),
            ..LocalResourceSnapshot::unknown()
        }
    }

    #[test]
    fn an_unmeasured_machine_is_unknown_not_green() {
        assert_eq!(
            classify(
                &LocalResourceSnapshot::unknown(),
                &PressureThresholds::default()
            ),
            PressureState::Unknown,
            "'nobody looked' must never be reported as 'plenty free'"
        );
    }

    #[test]
    fn pressure_states_track_usage() {
        let t = PressureThresholds::default();
        assert_eq!(classify(&snapshot(24, 24), &t), PressureState::Green);
        assert_eq!(classify(&snapshot(100, 25), &t), PressureState::Yellow);
        assert_eq!(classify(&snapshot(100, 15), &t), PressureState::Orange);
        assert_eq!(classify(&snapshot(100, 8), &t), PressureState::Red);
        assert_eq!(classify(&snapshot(100, 2), &t), PressureState::Critical);
    }

    #[test]
    fn thresholds_are_configurable() {
        let strict = PressureThresholds {
            yellow_used_fraction: 0.10,
            orange_used_fraction: 0.20,
            red_used_fraction: 0.30,
            critical_used_fraction: 0.40,
        };
        assert_eq!(classify(&snapshot(100, 85), &strict), PressureState::Yellow);
    }

    #[test]
    fn default_thresholds_ascend() {
        assert!(PressureThresholds::default().is_monotonic());
    }

    #[test]
    fn out_of_order_thresholds_are_detectable() {
        let broken = PressureThresholds {
            yellow_used_fraction: 0.9,
            orange_used_fraction: 0.5,
            red_used_fraction: 0.6,
            critical_used_fraction: 0.7,
        };
        assert!(!broken.is_monotonic());
    }

    #[test]
    fn a_zero_sized_machine_does_not_divide_by_zero() {
        let mut s = LocalResourceSnapshot::unknown();
        s.physical_ram_total = Measured::known(Bytes::ZERO);
        s.physical_ram_available = Measured::known(Bytes::ZERO);
        assert_eq!(s.ram_used_fraction(), None);
    }

    #[test]
    fn an_unprobed_gpu_is_not_schedulable() {
        assert!(!GpuStatus::Unprobed.is_schedulable());
        assert!(!GpuStatus::Absent.is_schedulable());
        assert!(
            GpuStatus::Available {
                total: Bytes::from_gib(24),
                free: Measured::known(Bytes::from_gib(20)),
            }
            .is_schedulable()
        );
    }

    #[test]
    fn a_gpu_with_unknown_free_memory_is_still_not_a_number() {
        let status = GpuStatus::Available {
            total: Bytes::from_gib(24),
            free: Measured::Unknown,
        };
        let GpuStatus::Available { free, .. } = &status else {
            panic!("expected Available");
        };
        assert!(!free.is_known());
    }

    #[test]
    fn green_pressure_keeps_work_local() {
        let w = WorkloadMetadata::new("editor", Bytes::from_mib(200));
        assert_eq!(
            decide(PressureState::Green, &w),
            ResourceDecision::KeepLocal
        );
    }

    #[test]
    fn caches_go_first() {
        let cache = WorkloadMetadata::new("thumbnails", Bytes::from_mib(400)).disposable_cache();
        for pressure in [
            PressureState::Yellow,
            PressureState::Orange,
            PressureState::Red,
            PressureState::Critical,
        ] {
            assert_eq!(decide(pressure, &cache), ResourceDecision::ReleaseCache);
        }
    }

    #[test]
    fn background_migratable_work_moves_before_interactive_work() {
        let background = WorkloadMetadata::new("index", Bytes::from_gib(2))
            .migratable()
            .background();
        let interactive = WorkloadMetadata::new("editor", Bytes::from_gib(2)).migratable();
        assert_eq!(
            decide(PressureState::Red, &background),
            ResourceDecision::Migrate
        );
        assert_ne!(
            decide(PressureState::Red, &interactive),
            ResourceDecision::Migrate
        );
    }

    #[test]
    fn swap_is_a_last_resort_for_interactive_work_only() {
        let interactive = WorkloadMetadata::new("editor", Bytes::from_gib(4));
        assert_eq!(
            decide(PressureState::Critical, &interactive),
            ResourceDecision::AllowBoundedSwap
        );
        for pressure in [
            PressureState::Yellow,
            PressureState::Orange,
            PressureState::Red,
        ] {
            assert_ne!(
                decide(pressure, &interactive),
                ResourceDecision::AllowBoundedSwap,
                "swap must not be reached for before the ladder is exhausted"
            );
        }
    }

    #[test]
    fn background_work_is_denied_at_critical_rather_than_swapped() {
        let background = WorkloadMetadata::new("batch", Bytes::from_gib(8)).background();
        assert_eq!(
            decide(PressureState::Critical, &background),
            ResourceDecision::Deny
        );
    }

    #[test]
    fn unknown_pressure_is_conservative() {
        let interactive = WorkloadMetadata::new("editor", Bytes::from_gib(1));
        let background = WorkloadMetadata::new("batch", Bytes::from_gib(1)).background();
        assert_eq!(
            decide(PressureState::Unknown, &interactive),
            ResourceDecision::KeepLocal
        );
        assert_eq!(
            decide(PressureState::Unknown, &background),
            ResourceDecision::Throttle
        );
    }

    #[test]
    fn the_decision_is_pure() {
        let w = WorkloadMetadata::new("editor", Bytes::from_gib(1)).checkpointable();
        let first = decide(PressureState::Orange, &w);
        let second = decide(PressureState::Orange, &w);
        assert_eq!(first, second);
        assert_eq!(w.footprint, Bytes::from_gib(1));
    }

    #[test]
    fn snapshots_round_trip_through_json() {
        let s = snapshot(24, 12);
        let json = serde_json::to_string(&s).unwrap();
        assert_eq!(
            serde_json::from_str::<LocalResourceSnapshot>(&json).unwrap(),
            s
        );
    }

    #[test]
    fn swap_use_is_visible_but_separate() {
        let mut s = snapshot(24, 12);
        assert!(!s.swap_in_use());
        s.swap_used = Measured::known(Bytes::from_gib(2));
        assert!(s.swap_in_use());
        // Crucially, the RAM figures are unchanged by swap being in use.
        assert_eq!(s.physical_ram_total, Measured::known(Bytes::from_gib(24)));
    }
}
