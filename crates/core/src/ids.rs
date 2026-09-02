//! Identifiers and time.
//!
//! `EntityId` and `ArtifactId` are separate types over the same
//! representation on purpose. They are not interchangeable — an artifact is
//! a thing that was produced, an entity is a thing that exists — and making
//! the compiler enforce that costs nothing and catches the class of bug
//! where one is passed where the other was meant.
//!
//! `TraceId` threads a single action through request → authorization →
//! execution → receipt → outcome. This increment establishes the identifier
//! only; nothing propagates it across processes yet.

use std::fmt;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};

use crate::error::{CoreError, CoreResult};

/// Monotonic within a process, so ids minted in one run sort by creation.
static COUNTER: AtomicU64 = AtomicU64::new(0);

/// Milliseconds since the Unix epoch.
///
/// Not a wall-clock date type: this is for ordering and receipts, and a
/// full calendar type would invite timezone questions the runtime does not
/// need to answer.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct Timestamp(u64);

impl Timestamp {
    pub fn now() -> Self {
        let millis = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_millis() as u64)
            // A clock before 1970 is a broken clock, not a reason to panic
            // in a runtime that is meant to keep running.
            .unwrap_or(0);
        Self(millis)
    }

    pub const fn from_millis(millis: u64) -> Self {
        Self(millis)
    }

    pub const fn as_millis(self) -> u64 {
        self.0
    }
}

impl fmt::Display for Timestamp {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}ms", self.0)
    }
}

/// Schema version carried by every persisted or transmitted record.
///
/// Present from version 1 rather than added later, because adding a version
/// field to records that lack one requires guessing what the unversioned
/// ones meant.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct SchemaVersion(pub u32);

impl SchemaVersion {
    pub const V1: Self = Self(1);

    pub const fn get(self) -> u32 {
        self.0
    }
}

impl fmt::Display for SchemaVersion {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "v{}", self.0)
    }
}

macro_rules! opaque_id {
    ($name:ident, $prefix:literal, $doc:literal) => {
        #[doc = $doc]
        #[derive(Debug, Clone, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
        #[serde(transparent)]
        pub struct $name(String);

        impl $name {
            /// Mint a new identifier: timestamp, then an in-process counter.
            ///
            /// Sortable by creation time and unique within a run. It is not
            /// globally unique across machines — that needs the identity
            /// crate, which this increment does not implement, so nothing
            /// here should be treated as a cross-machine name yet.
            pub fn generate() -> Self {
                let millis = Timestamp::now().as_millis();
                let seq = COUNTER.fetch_add(1, Ordering::Relaxed);
                Self(format!("{}_{millis:013x}{seq:08x}", $prefix))
            }

            pub fn parse(value: &str) -> CoreResult<Self> {
                let expected = concat!($prefix, "_");
                if !value.starts_with(expected) {
                    return Err(CoreError::Validation(format!(
                        "{} must start with {:?}, got {:?}",
                        stringify!($name),
                        expected,
                        value
                    )));
                }
                if value.len() <= expected.len() {
                    return Err(CoreError::Validation(format!(
                        "{} has an empty body",
                        stringify!($name)
                    )));
                }
                Ok(Self(value.to_owned()))
            }

            pub fn as_str(&self) -> &str {
                &self.0
            }
        }

        impl fmt::Display for $name {
            fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                f.write_str(&self.0)
            }
        }
    };
}

opaque_id!(EntityId, "ent", "Something that exists in the graph.");
opaque_id!(ArtifactId, "art", "Something that was produced and stored.");
opaque_id!(
    TraceId,
    "trc",
    "One action, followed from request through to outcome."
);

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn generated_ids_are_unique() {
        let a = EntityId::generate();
        let b = EntityId::generate();
        assert_ne!(a, b);
    }

    #[test]
    fn generated_ids_sort_by_creation() {
        let a = EntityId::generate();
        let b = EntityId::generate();
        assert!(a < b);
    }

    #[test]
    fn ids_carry_their_kind_in_the_prefix() {
        assert!(EntityId::generate().as_str().starts_with("ent_"));
        assert!(ArtifactId::generate().as_str().starts_with("art_"));
        assert!(TraceId::generate().as_str().starts_with("trc_"));
    }

    #[test]
    fn an_artifact_id_is_not_a_valid_entity_id() {
        let artifact = ArtifactId::generate();
        assert!(EntityId::parse(artifact.as_str()).is_err());
    }

    #[test]
    fn parse_round_trips() {
        let id = EntityId::generate();
        assert_eq!(EntityId::parse(id.as_str()).unwrap(), id);
    }

    #[test]
    fn parse_rejects_an_empty_body() {
        assert!(EntityId::parse("ent_").is_err());
    }

    #[test]
    fn timestamps_are_non_zero_and_ordered() {
        let earlier = Timestamp::from_millis(1);
        let later = Timestamp::from_millis(2);
        assert!(earlier < later);
        assert!(Timestamp::now().as_millis() > 0);
    }

    #[test]
    fn schema_version_one_is_named() {
        assert_eq!(SchemaVersion::V1.get(), 1);
        assert_eq!(SchemaVersion::V1.to_string(), "v1");
    }
}
