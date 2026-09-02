//! The error taxonomy.
//!
//! Every variant here answers a different question for the caller, which is
//! the point of having them at all: a `String` tells you something went
//! wrong, a variant tells you whether to retry, re-authorize, refuse, or
//! escalate. `InvariantViolation` is deliberately last and deliberately
//! distinct — it means a law in `INVARIANTS.md` was broken, which is never a
//! condition to handle and always a bug to fix.

use std::fmt;

/// Result alias for the core crate.
pub type CoreResult<T> = Result<T, CoreError>;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CoreError {
    /// Input did not satisfy the type's stated rules.
    Validation(String),
    /// The actor is not permitted to do this.
    Authorization(String),
    /// Content did not match the hash it claimed.
    Integrity { expected: String, actual: String },
    /// A physical resource is unavailable or over-committed.
    Resource(String),
    /// Reading or writing durable state failed.
    Persistence(String),
    /// A stored record is a schema version this build cannot read.
    UnsupportedSchema { found: u32, supported: u32 },
    /// Something outside this process failed.
    ExternalDependency(String),
    /// A documented invariant was violated. Always a bug.
    InvariantViolation(&'static str),
}

impl fmt::Display for CoreError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Validation(msg) => write!(f, "validation error: {msg}"),
            Self::Authorization(msg) => write!(f, "authorization error: {msg}"),
            Self::Integrity { expected, actual } => write!(
                f,
                "integrity error: content hashes to {actual} but {expected} was expected"
            ),
            Self::Resource(msg) => write!(f, "resource error: {msg}"),
            Self::Persistence(msg) => write!(f, "persistence error: {msg}"),
            Self::UnsupportedSchema { found, supported } => write!(
                f,
                "unsupported schema error: record is version {found}, this build reads {supported}"
            ),
            Self::ExternalDependency(msg) => write!(f, "external dependency error: {msg}"),
            Self::InvariantViolation(law) => {
                write!(f, "invariant violation: {law}")
            }
        }
    }
}

impl std::error::Error for CoreError {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn each_variant_names_its_kind() {
        assert!(
            CoreError::Validation("x".into())
                .to_string()
                .starts_with("validation")
        );
        assert!(
            CoreError::Authorization("x".into())
                .to_string()
                .starts_with("authorization")
        );
        assert!(
            CoreError::Resource("x".into())
                .to_string()
                .starts_with("resource")
        );
        assert!(
            CoreError::Persistence("x".into())
                .to_string()
                .starts_with("persistence")
        );
    }

    #[test]
    fn integrity_error_reports_both_hashes() {
        let err = CoreError::Integrity {
            expected: "aaa".into(),
            actual: "bbb".into(),
        };
        let msg = err.to_string();
        assert!(msg.contains("aaa") && msg.contains("bbb"));
    }

    #[test]
    fn schema_error_reports_both_versions() {
        let err = CoreError::UnsupportedSchema {
            found: 9,
            supported: 1,
        };
        let msg = err.to_string();
        assert!(msg.contains('9') && msg.contains('1'));
    }

    #[test]
    fn invariant_violation_names_the_law() {
        let err = CoreError::InvariantViolation("COMPUTE CREDIT != PHYSICAL COMPUTE");
        assert!(err.to_string().contains("COMPUTE CREDIT"));
    }

    #[test]
    fn errors_are_std_errors() {
        fn takes_std_error(_: &dyn std::error::Error) {}
        takes_std_error(&CoreError::Validation("x".into()));
    }
}
