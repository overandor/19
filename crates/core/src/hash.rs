//! The one content-hashing abstraction.
//!
//! Deliberately singular. Multiple hashing implementations in different
//! crates is how a content-addressed system ends up with two names for the
//! same bytes, at which point deduplication silently stops working and
//! integrity checks start disagreeing with each other. Every crate in this
//! workspace hashes through here.

use std::fmt;

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::error::{CoreError, CoreResult};

/// A SHA-256 content hash, rendered as lowercase hex.
///
/// The algorithm is part of the type rather than a parameter: a value that
/// might be one of several digests is not a content address, because two
/// such values cannot be compared for identity.
#[derive(Debug, Clone, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(transparent)]
pub struct ContentHash(String);

impl ContentHash {
    pub const HEX_LEN: usize = 64;

    /// Parse a hex digest, rejecting anything that is not one.
    pub fn parse(value: &str) -> CoreResult<Self> {
        if value.len() != Self::HEX_LEN {
            return Err(CoreError::Validation(format!(
                "content hash must be {} hex characters, got {}",
                Self::HEX_LEN,
                value.len()
            )));
        }
        if !value.bytes().all(|b| b.is_ascii_hexdigit()) {
            return Err(CoreError::Validation(
                "content hash contains non-hex characters".to_owned(),
            ));
        }
        Ok(Self(value.to_ascii_lowercase()))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }

    /// A short prefix, for logs and messages. Never for identity.
    pub fn short(&self) -> &str {
        &self.0[..12]
    }
}

impl fmt::Display for ContentHash {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

/// Hash bytes into a content address.
pub fn hash_bytes(bytes: &[u8]) -> ContentHash {
    let digest = Sha256::digest(bytes);
    ContentHash(hex_lower(&digest))
}

/// Check bytes against a hash they claim to have.
///
/// Returns `Err(IntegrityError)` rather than `false` on mismatch: a
/// corrupted object is an error to propagate, not a boolean to accidentally
/// ignore at a call site.
pub fn verify_bytes(bytes: &[u8], expected: &ContentHash) -> CoreResult<()> {
    let actual = hash_bytes(bytes);
    if &actual == expected {
        Ok(())
    } else {
        Err(CoreError::Integrity {
            expected: expected.to_string(),
            actual: actual.to_string(),
        })
    }
}

/// Whether bytes match, for callers that genuinely want a predicate.
pub fn bytes_match(bytes: &[u8], expected: &ContentHash) -> bool {
    verify_bytes(bytes, expected).is_ok()
}

fn hex_lower(bytes: &[u8]) -> String {
    let mut out = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        out.push(char::from_digit((byte >> 4) as u32, 16).expect("nibble is < 16"));
        out.push(char::from_digit((byte & 0x0f) as u32, 16).expect("nibble is < 16"));
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn same_input_gives_same_hash() {
        assert_eq!(hash_bytes(b"hello"), hash_bytes(b"hello"));
    }

    #[test]
    fn changed_input_gives_a_different_hash() {
        assert_ne!(hash_bytes(b"hello"), hash_bytes(b"hellp"));
    }

    #[test]
    fn empty_input_hashes() {
        assert_eq!(hash_bytes(b"").as_str().len(), ContentHash::HEX_LEN);
    }

    #[test]
    fn matches_the_known_sha256_of_abc() {
        // Cross-checks against the published SHA-256 test vector, so a
        // change of algorithm cannot pass unnoticed.
        assert_eq!(
            hash_bytes(b"abc").as_str(),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
    }

    #[test]
    fn verification_accepts_the_original_bytes() {
        let hash = hash_bytes(b"payload");
        assert!(verify_bytes(b"payload", &hash).is_ok());
    }

    #[test]
    fn corruption_is_detected() {
        let hash = hash_bytes(b"payload");
        let err = verify_bytes(b"payl0ad", &hash).unwrap_err();
        assert!(matches!(err, CoreError::Integrity { .. }));
    }

    #[test]
    fn truncation_is_detected() {
        let hash = hash_bytes(b"payload");
        assert!(verify_bytes(b"payloa", &hash).is_err());
    }

    #[test]
    fn parse_rejects_wrong_length() {
        assert!(ContentHash::parse("abc").is_err());
    }

    #[test]
    fn parse_rejects_non_hex() {
        assert!(ContentHash::parse(&"z".repeat(64)).is_err());
    }

    #[test]
    fn parse_round_trips_a_real_hash() {
        let hash = hash_bytes(b"round trip");
        assert_eq!(ContentHash::parse(hash.as_str()).unwrap(), hash);
    }

    #[test]
    fn parse_is_case_insensitive_but_normalises() {
        let hash = hash_bytes(b"case");
        let upper = hash.as_str().to_ascii_uppercase();
        assert_eq!(ContentHash::parse(&upper).unwrap(), hash);
    }
}
