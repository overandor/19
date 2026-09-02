//! Memory temperature: what stays resident, and what can be rebuilt.
//!
//! The invariant is
//!
//! ```text
//! RECONSTRUCTABLE STATE != HOT STATE
//! ```
//!
//! Most of what a long-running runtime holds is derivable again from
//! something smaller. An index can be rebuilt from the objects it indexes; a
//! rendered page can be re-rendered from its URL and a little continuity;
//! an embedding can be recomputed. Holding all of it because it might be
//! wanted is how 24GiB disappears.
//!
//! Temperature is the demotion ladder, and the cost of climbing back up is
//! recorded alongside it: state that is cheap to rebuild should cool fast,
//! state that is expensive should cool slowly, and state that cannot be
//! rebuilt at all should not cool past the point where it is still
//! recoverable.
//!
//! **This increment classifies and nothing more.** There is no automatic
//! deletion, no eviction loop, no background demotion. Everything here is a
//! pure function over metadata, so the policy can be argued with before
//! anything acts on it.

use pwr_core::{Bytes, Timestamp};
use serde::{Deserialize, Serialize};

/// How resident a piece of state currently is.
///
/// Ordered from hottest to coldest, so policy can compare.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum MemoryTemperature {
    /// In use right now. Full fidelity, resident.
    Hot,
    /// Recently used. Resident but a candidate for compression.
    Warm,
    /// Compressed or summarised, still local.
    Cool,
    /// On disk only. Rehydration costs a read.
    Cold,
    /// Off the hot path entirely. Rehydration may cost real work.
    Archived,
}

impl MemoryTemperature {
    /// The next step down the ladder, or `None` at the bottom.
    pub const fn cooler(self) -> Option<Self> {
        match self {
            Self::Hot => Some(Self::Warm),
            Self::Warm => Some(Self::Cool),
            Self::Cool => Some(Self::Cold),
            Self::Cold => Some(Self::Archived),
            Self::Archived => None,
        }
    }

    /// Whether state at this temperature still occupies RAM.
    pub const fn is_resident(self) -> bool {
        matches!(self, Self::Hot | Self::Warm)
    }
}

/// How expensive it is to bring something back.
///
/// Separate from size, because the two do not correlate: a small embedding
/// can cost a GPU second to recompute, and a large log costs a disk read.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ReconstructionCost {
    /// Derivable from something already resident.
    Free,
    /// A local read.
    Cheap,
    /// Local computation.
    Moderate,
    /// Remote work, or a lot of local work.
    Expensive,
    /// Cannot be rebuilt. Losing it loses it.
    Irreplaceable,
}

impl ReconstructionCost {
    /// Whether state at this cost may be dropped rather than demoted.
    ///
    /// Only `Free`. Everything else must be written somewhere before it
    /// leaves RAM, and `Irreplaceable` must never be dropped at all.
    pub const fn is_safely_droppable(self) -> bool {
        matches!(self, Self::Free)
    }
}

/// What is known about one piece of state.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct MemoryMetadata {
    pub temperature: MemoryTemperature,
    pub last_access: Timestamp,
    pub access_frequency: u32,
    /// How much this matters to what the user is doing now, in `[0, 1]`.
    pub task_relevance: f64,
    /// How much it matters if this is wrong or lost, in `[0, 1]`.
    pub consequence_weight: f64,
    pub reconstruction_cost: ReconstructionCost,
    pub size_bytes: Bytes,
    /// Pinned state is never demoted, whatever the pressure.
    pub pinned: bool,
}

impl MemoryMetadata {
    pub fn new(size_bytes: Bytes, reconstruction_cost: ReconstructionCost) -> Self {
        Self {
            temperature: MemoryTemperature::Hot,
            last_access: Timestamp::now(),
            access_frequency: 1,
            task_relevance: 1.0,
            consequence_weight: 0.0,
            reconstruction_cost,
            size_bytes,
            pinned: false,
        }
    }

    #[must_use]
    pub fn pinned(mut self) -> Self {
        self.pinned = true;
        self
    }

    #[must_use]
    pub fn with_relevance(mut self, relevance: f64) -> Self {
        self.task_relevance = relevance.clamp(0.0, 1.0);
        self
    }

    #[must_use]
    pub fn with_consequence(mut self, weight: f64) -> Self {
        self.consequence_weight = weight.clamp(0.0, 1.0);
        self
    }

    /// Whether this may cool one step.
    ///
    /// Pinned state never may. Irreplaceable state may not fall below
    /// `Cold`, because `Archived` is where rehydration stops being a
    /// guarantee, and something that cannot be rebuilt must stay somewhere
    /// it can still be read.
    pub const fn may_cool(&self) -> bool {
        if self.pinned {
            return false;
        }
        match self.reconstruction_cost {
            ReconstructionCost::Irreplaceable => !matches!(
                self.temperature,
                MemoryTemperature::Cold | MemoryTemperature::Archived
            ),
            _ => self.temperature.cooler().is_some(),
        }
    }

    /// The temperature after one demotion, or the current one if it may not
    /// cool. Pure: nothing is moved, nothing is freed.
    pub fn cooled(&self) -> MemoryTemperature {
        if !self.may_cool() {
            return self.temperature;
        }
        self.temperature.cooler().unwrap_or(self.temperature)
    }

    /// How worth keeping this is. Higher survives longer.
    ///
    /// Deliberately simple and deliberately explicit: relevance and
    /// consequence pull up, and reconstruction cost pulls up because
    /// re-deriving expensive state is the thing worth avoiding. Size is not
    /// in the score — a large object is not less valuable, it is merely a
    /// bigger win to release, which is the caller's trade to make.
    pub fn retention_score(&self) -> f64 {
        if self.pinned {
            return f64::INFINITY;
        }
        let cost_weight = match self.reconstruction_cost {
            ReconstructionCost::Free => 0.0,
            ReconstructionCost::Cheap => 0.25,
            ReconstructionCost::Moderate => 0.5,
            ReconstructionCost::Expensive => 0.85,
            ReconstructionCost::Irreplaceable => 1.0,
        };
        self.task_relevance + self.consequence_weight + cost_weight
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn meta(cost: ReconstructionCost) -> MemoryMetadata {
        MemoryMetadata::new(Bytes::from_mib(4), cost)
    }

    #[test]
    fn temperatures_are_ordered_hot_to_cold() {
        assert!(MemoryTemperature::Hot < MemoryTemperature::Archived);
        assert!(MemoryTemperature::Warm < MemoryTemperature::Cool);
    }

    #[test]
    fn the_ladder_descends_and_stops() {
        assert_eq!(
            MemoryTemperature::Hot.cooler(),
            Some(MemoryTemperature::Warm)
        );
        assert_eq!(MemoryTemperature::Archived.cooler(), None);
    }

    #[test]
    fn only_hot_and_warm_occupy_ram() {
        assert!(MemoryTemperature::Hot.is_resident());
        assert!(MemoryTemperature::Warm.is_resident());
        assert!(!MemoryTemperature::Cool.is_resident());
        assert!(!MemoryTemperature::Cold.is_resident());
    }

    #[test]
    fn pinned_state_never_cools() {
        let pinned = meta(ReconstructionCost::Free).pinned();
        assert!(!pinned.may_cool());
        assert_eq!(pinned.cooled(), MemoryTemperature::Hot);
    }

    #[test]
    fn ordinary_state_cools_one_step() {
        assert_eq!(
            meta(ReconstructionCost::Cheap).cooled(),
            MemoryTemperature::Warm
        );
    }

    #[test]
    fn irreplaceable_state_stops_at_cold() {
        let mut m = meta(ReconstructionCost::Irreplaceable);
        m.temperature = MemoryTemperature::Cold;
        assert!(!m.may_cool());
        assert_eq!(m.cooled(), MemoryTemperature::Cold);
    }

    #[test]
    fn irreplaceable_state_still_cools_while_it_is_hot() {
        let m = meta(ReconstructionCost::Irreplaceable);
        assert!(m.may_cool());
        assert_eq!(m.cooled(), MemoryTemperature::Warm);
    }

    #[test]
    fn only_free_state_is_droppable() {
        assert!(ReconstructionCost::Free.is_safely_droppable());
        for cost in [
            ReconstructionCost::Cheap,
            ReconstructionCost::Moderate,
            ReconstructionCost::Expensive,
            ReconstructionCost::Irreplaceable,
        ] {
            assert!(
                !cost.is_safely_droppable(),
                "{cost:?} must be written first"
            );
        }
    }

    #[test]
    fn pinned_state_outscores_everything() {
        assert_eq!(
            meta(ReconstructionCost::Free).pinned().retention_score(),
            f64::INFINITY
        );
    }

    #[test]
    fn expensive_state_outscores_cheap_state() {
        let expensive = meta(ReconstructionCost::Expensive);
        let cheap = meta(ReconstructionCost::Cheap);
        assert!(expensive.retention_score() > cheap.retention_score());
    }

    #[test]
    fn relevance_and_consequence_are_clamped() {
        let m = meta(ReconstructionCost::Cheap)
            .with_relevance(5.0)
            .with_consequence(-3.0);
        assert_eq!(m.task_relevance, 1.0);
        assert_eq!(m.consequence_weight, 0.0);
    }

    #[test]
    fn metadata_round_trips_through_json() {
        let m = meta(ReconstructionCost::Moderate).with_relevance(0.5);
        let json = serde_json::to_string(&m).unwrap();
        assert_eq!(serde_json::from_str::<MemoryMetadata>(&json).unwrap(), m);
    }

    #[test]
    fn temperature_names_are_stable_in_json() {
        assert_eq!(
            serde_json::to_string(&MemoryTemperature::Archived).unwrap(),
            "\"ARCHIVED\""
        );
    }
}
