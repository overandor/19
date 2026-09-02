//! Canonical primitives for the Personal Web Runtime.
//!
//! Every other crate in the workspace depends on this one and none of it
//! depends on them, so this is where anything that must have exactly one
//! definition lives: the content hash, the identifier types, the units, the
//! error taxonomy.
//!
//! What is deliberately *not* here: business logic. This crate defines the
//! vocabulary the rest of the system argues in.

pub mod error;
pub mod hash;
pub mod ids;
pub mod log;
pub mod units;

pub use error::{CoreError, CoreResult};
pub use hash::{ContentHash, bytes_match, hash_bytes, verify_bytes};
pub use ids::{ArtifactId, EntityId, SchemaVersion, Timestamp, TraceId};
pub use log::{Level, LogEvent};
pub use units::{Bytes, Credits, Measured, PhysicalQuantity};
