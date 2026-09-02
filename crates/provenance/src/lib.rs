//! Receipts: the record that something happened, and who is answerable.
//!
//! The invariant this serves is
//!
//! ```text
//! NO CONSEQUENTIAL EFFECT WITHOUT ATTRIBUTABLE RECEIPT
//! ```
//!
//! and the honest position of this increment is that receipts are recorded
//! but **not signed**. Signing needs the identity crate, which is the next
//! increment. So [`SignatureStatus`] is an explicit field with an
//! [`Unsigned`](SignatureStatus::Unsigned) variant rather than an absent
//! one, and [`ReceiptEnvelope::is_attributable`] returns `false` for it.
//!
//! That distinction matters more than it looks. A receipt with no signature
//! field reads as trustworthy to anything that does not know to ask. A
//! receipt that says `UNSIGNED` cannot be mistaken for evidence.

use pwr_core::{ArtifactId, ContentHash, CoreError, CoreResult, SchemaVersion, Timestamp, TraceId};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

/// What kind of thing this receipt records.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ReceiptType {
    /// Something changed outside this process.
    Effect,
    /// Work ran.
    Execution,
    /// Value moved.
    Settlement,
    /// State was compressed or forgotten.
    Compression,
    /// A choice was made, by a person or by policy.
    Decision,
}

/// Whether anyone can actually be held to this receipt.
///
/// `Unsigned` is the truthful answer for everything this build produces.
/// The other variants exist so that the field does not have to change shape
/// when signing lands — a schema that gains a signature later forces every
/// stored record to be re-interpreted.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Default, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum SignatureStatus {
    /// No signature. Not evidence of anything beyond "this was written".
    #[default]
    Unsigned,
    /// A signature is attached but has not been checked in this process.
    Signed,
    /// A signature was checked and holds.
    Verified,
    /// A signature was checked and does not hold.
    Invalid,
}

impl SignatureStatus {
    /// Whether this receipt can be attributed to anyone.
    ///
    /// Only `Verified`. `Signed` is a claim nobody has checked, which is
    /// exactly as attributable as no signature at all.
    pub const fn is_attributable(self) -> bool {
        matches!(self, Self::Verified)
    }
}

/// An immutable record of one thing that happened.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ReceiptEnvelope {
    pub receipt_id: ArtifactId,
    pub schema_version: SchemaVersion,
    pub receipt_type: ReceiptType,
    /// Who or what did this. A free-form label in this increment; the
    /// identity crate will replace it with a typed identity.
    pub actor: String,
    pub created_at: Timestamp,
    pub trace_id: TraceId,
    pub input_hashes: Vec<ContentHash>,
    pub output_hashes: Vec<ContentHash>,
    /// The receipt before this one, forming a chain per actor.
    pub previous_receipt: Option<ArtifactId>,
    pub metadata: BTreeMap<String, String>,
    pub signature_status: SignatureStatus,
}

impl ReceiptEnvelope {
    /// Record something. Always unsigned — this build cannot sign.
    pub fn new(receipt_type: ReceiptType, actor: impl Into<String>, trace_id: TraceId) -> Self {
        Self {
            receipt_id: ArtifactId::generate(),
            schema_version: SchemaVersion::V1,
            receipt_type,
            actor: actor.into(),
            created_at: Timestamp::now(),
            trace_id,
            input_hashes: Vec::new(),
            output_hashes: Vec::new(),
            previous_receipt: None,
            metadata: BTreeMap::new(),
            signature_status: SignatureStatus::Unsigned,
        }
    }

    #[must_use]
    pub fn with_inputs(mut self, hashes: Vec<ContentHash>) -> Self {
        self.input_hashes = hashes;
        self
    }

    #[must_use]
    pub fn with_outputs(mut self, hashes: Vec<ContentHash>) -> Self {
        self.output_hashes = hashes;
        self
    }

    #[must_use]
    pub fn chained_to(mut self, previous: ArtifactId) -> Self {
        self.previous_receipt = Some(previous);
        self
    }

    /// Attach metadata. Keys are sorted, so the serialization is canonical
    /// and two equal receipts hash the same.
    #[must_use]
    pub fn with_metadata(mut self, key: impl Into<String>, value: impl Into<String>) -> Self {
        self.metadata.insert(key.into(), value.into());
        self
    }

    /// Whether this receipt can be held against anyone.
    ///
    /// False for everything this build writes, and that is the point.
    pub const fn is_attributable(&self) -> bool {
        self.signature_status.is_attributable()
    }

    pub fn validate(&self) -> CoreResult<()> {
        if self.schema_version != SchemaVersion::V1 {
            return Err(CoreError::UnsupportedSchema {
                found: self.schema_version.get(),
                supported: SchemaVersion::V1.get(),
            });
        }
        if self.actor.trim().is_empty() {
            return Err(CoreError::Validation(
                "receipt has no actor; an unattributed receipt records nothing".to_owned(),
            ));
        }
        Ok(())
    }

    /// Parse a receipt from untrusted bytes, rejecting anything malformed.
    pub fn from_json(json: &str) -> CoreResult<Self> {
        let envelope: Self = serde_json::from_str(json)
            .map_err(|err| CoreError::Validation(format!("malformed receipt: {err}")))?;
        envelope.validate()?;
        Ok(envelope)
    }

    pub fn to_json(&self) -> CoreResult<String> {
        serde_json::to_string(self)
            .map_err(|err| CoreError::Persistence(format!("receipt is not serializable: {err}")))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use pwr_core::hash_bytes;

    fn receipt() -> ReceiptEnvelope {
        ReceiptEnvelope::new(ReceiptType::Execution, "runtime", TraceId::generate())
    }

    #[test]
    fn a_new_receipt_is_unsigned() {
        assert_eq!(receipt().signature_status, SignatureStatus::Unsigned);
    }

    #[test]
    fn an_unsigned_receipt_is_not_attributable() {
        assert!(
            !receipt().is_attributable(),
            "this build cannot sign, so no receipt it writes is evidence"
        );
    }

    #[test]
    fn a_merely_signed_receipt_is_not_attributable_either() {
        let mut envelope = receipt();
        envelope.signature_status = SignatureStatus::Signed;
        assert!(
            !envelope.is_attributable(),
            "an unchecked signature is a claim, not attribution"
        );
    }

    #[test]
    fn only_a_verified_signature_attributes() {
        let mut envelope = receipt();
        envelope.signature_status = SignatureStatus::Verified;
        assert!(envelope.is_attributable());
    }

    #[test]
    fn an_invalid_signature_is_not_attributable() {
        let mut envelope = receipt();
        envelope.signature_status = SignatureStatus::Invalid;
        assert!(!envelope.is_attributable());
    }

    #[test]
    fn receipts_round_trip_through_json() {
        let original = receipt()
            .with_inputs(vec![hash_bytes(b"in")])
            .with_outputs(vec![hash_bytes(b"out")])
            .with_metadata("component", "test");
        let restored = ReceiptEnvelope::from_json(&original.to_json().unwrap()).unwrap();
        assert_eq!(restored, original);
    }

    #[test]
    fn malformed_receipts_are_rejected() {
        assert!(ReceiptEnvelope::from_json("{not json").is_err());
        assert!(ReceiptEnvelope::from_json("{}").is_err());
    }

    #[test]
    fn a_receipt_with_no_actor_is_rejected() {
        let mut envelope = receipt();
        envelope.actor = "  ".to_owned();
        assert!(envelope.validate().is_err());
    }

    #[test]
    fn a_future_schema_version_is_rejected() {
        let mut envelope = receipt();
        envelope.schema_version = SchemaVersion(7);
        assert!(matches!(
            envelope.validate(),
            Err(CoreError::UnsupportedSchema { found: 7, .. })
        ));
    }

    #[test]
    fn receipts_chain() {
        let first = receipt();
        let second = receipt().chained_to(first.receipt_id.clone());
        assert_eq!(second.previous_receipt, Some(first.receipt_id));
    }

    #[test]
    fn metadata_serializes_in_a_stable_order() {
        let a = receipt().with_metadata("z", "1").with_metadata("a", "2");
        let json = a.to_json().unwrap();
        assert!(json.find("\"a\"").unwrap() < json.find("\"z\"").unwrap());
    }

    #[test]
    fn every_receipt_type_serializes() {
        for kind in [
            ReceiptType::Effect,
            ReceiptType::Execution,
            ReceiptType::Settlement,
            ReceiptType::Compression,
            ReceiptType::Decision,
        ] {
            let json = serde_json::to_string(&kind).unwrap();
            assert_eq!(serde_json::from_str::<ReceiptType>(&json).unwrap(), kind);
        }
    }
}
