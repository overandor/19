//! The authorization language, and the smallest evaluator that enforces it.
//!
//! This increment defines vocabulary and decisions. Nothing here executes
//! anything — `CapabilityDecision` is a value, and the component that would
//! act on it does not exist yet. That ordering is deliberate: an
//! authorization model added after an execution path has to be retrofitted
//! around whatever the execution path already assumed.
//!
//! Three invariants from `INVARIANTS.md` are enforced here rather than
//! documented and hoped for:
//!
//! ```text
//! WEB CONTENT != MACHINE AUTHORITY
//! LLM OUTPUT  != AUTHORIZATION
//! DATA        != INSTRUCTION
//! ```
//!
//! All three are the same mistake wearing different clothes: text that
//! arrived from somewhere is treated as a decision by someone. A page can
//! *ask*; a model can *propose*; neither is a grant. The evaluator's job is
//! that only the user, or something the user explicitly delegated to, can
//! authorize anything with an effect.

use pwr_core::{CoreError, CoreResult, SchemaVersion, Timestamp, TraceId};
use serde::{Deserialize, Serialize};

/// What is being asked for.
///
/// The list is closed on purpose. An open-ended capability — a string, a
/// wildcard — cannot be evaluated deny-by-default, because there is no way
/// to tell an unrecognised capability from a mistyped one.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Capability {
    Read,
    Navigate,
    PatchDom,
    Network,
    Infer,
    Embed,
    RunTests,
    Build,
    Store,
    Retrieve,
    Write,
    Install,
    Publish,
    Spend,
    Delete,
    Sign,
    Transfer,
}

/// How bad it is if this turns out to have been the wrong call.
///
/// Ordered, so policy can compare rather than enumerate — and so a
/// capability added later cannot quietly slip beneath a threshold check.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ConsequenceClass {
    /// Looks, changes nothing.
    Observational,
    /// Changes something local that can be put back.
    ReversibleLocal,
    /// Changes local state for real.
    LocalEffect,
    /// Reaches another machine.
    RemoteEffect,
    /// Spends, publishes, or signs.
    HighConsequence,
    /// Cannot be undone by anyone.
    Irreversible,
}

impl Capability {
    /// The consequence class of this capability.
    ///
    /// Fixed in code rather than configured: a deployment that could
    /// downgrade `Spend` to `Observational` would have a policy engine that
    /// evaluates whatever it was told to believe.
    pub const fn consequence(self) -> ConsequenceClass {
        match self {
            Self::Read | Self::Retrieve => ConsequenceClass::Observational,
            Self::Navigate | Self::PatchDom | Self::Embed => ConsequenceClass::ReversibleLocal,
            Self::Store | Self::Write | Self::Build | Self::RunTests => {
                ConsequenceClass::LocalEffect
            }
            Self::Network | Self::Infer => ConsequenceClass::RemoteEffect,
            Self::Install | Self::Publish | Self::Sign => ConsequenceClass::HighConsequence,
            Self::Spend | Self::Delete | Self::Transfer => ConsequenceClass::Irreversible,
        }
    }

    /// Whether this reaches past the page and into the machine.
    ///
    /// The dividing line for `WEB CONTENT != MACHINE AUTHORITY`. A page may
    /// ask to read, navigate, or patch its own DOM; anything at
    /// `LocalEffect` or above is the machine's, not the page's.
    pub fn is_native_authority(self) -> bool {
        self.consequence() >= ConsequenceClass::LocalEffect
    }
}

/// Where a request came from. Not who it claims to be for.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case", tag = "kind", content = "detail")]
pub enum Origin {
    /// The person operating the machine. The only authority root.
    User,
    /// The runtime acting on a prior user decision.
    System,
    /// Content from a webpage. Data, never instruction.
    WebContent { url: String },
    /// A model's output. A proposal, never a grant.
    LlmOutput { model: String },
    /// Another machine.
    Peer { peer_id: String },
}

impl Origin {
    /// Whether this origin may hold native authority at all.
    ///
    /// A webpage and a model's output never can, regardless of what they
    /// ask for or how convincingly they ask. That is not a heuristic about
    /// intent — it is the boundary itself.
    pub const fn may_hold_native_authority(&self) -> bool {
        matches!(self, Self::User | Self::System)
    }

    pub const fn label(&self) -> &'static str {
        match self {
            Self::User => "user",
            Self::System => "system",
            Self::WebContent { .. } => "web content",
            Self::LlmOutput { .. } => "llm output",
            Self::Peer { .. } => "peer",
        }
    }
}

/// A request to do something.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CapabilityRequest {
    pub schema_version: SchemaVersion,
    pub trace_id: TraceId,
    pub capability: Capability,
    pub origin: Origin,
    pub subject: String,
    pub requested_at: Timestamp,
    /// Set only by an explicit user decision. A request cannot set it for
    /// itself — see `explicitly_authorized`.
    #[serde(default)]
    pub user_authorized: bool,
}

impl CapabilityRequest {
    pub fn new(capability: Capability, origin: Origin, subject: impl Into<String>) -> Self {
        Self {
            schema_version: SchemaVersion::V1,
            trace_id: TraceId::generate(),
            capability,
            origin,
            subject: subject.into(),
            requested_at: Timestamp::now(),
            user_authorized: false,
        }
    }

    /// Mark this request as carrying an explicit user authorization.
    ///
    /// Only meaningful from `Origin::User`. A webpage or a model setting
    /// the flag on its own request is precisely the escalation this whole
    /// module exists to stop, so the flag is ignored for those origins and
    /// `explicitly_authorized` is what policy actually reads.
    #[must_use]
    pub fn authorized_by_user(mut self) -> Self {
        self.user_authorized = true;
        self
    }

    /// Whether a *credible* explicit authorization is present.
    pub const fn explicitly_authorized(&self) -> bool {
        self.user_authorized && matches!(self.origin, Origin::User)
    }

    /// Structural validity. Malformed requests are denied, not repaired.
    pub fn validate(&self) -> CoreResult<()> {
        if self.subject.trim().is_empty() {
            return Err(CoreError::Validation(
                "capability request has an empty subject".to_owned(),
            ));
        }
        if self.schema_version != SchemaVersion::V1 {
            return Err(CoreError::UnsupportedSchema {
                found: self.schema_version.get(),
                supported: SchemaVersion::V1.get(),
            });
        }
        if let Origin::WebContent { url } = &self.origin
            && url.trim().is_empty()
        {
            return Err(CoreError::Validation(
                "web-origin request has an empty url".to_owned(),
            ));
        }
        Ok(())
    }
}

/// What policy decided.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case", tag = "decision")]
pub enum CapabilityDecision {
    Allow,
    /// Permitted in principle, but a person has to say so first.
    RequireApproval {
        reason: String,
    },
    Deny {
        reason: String,
    },
}

impl CapabilityDecision {
    pub const fn is_allow(&self) -> bool {
        matches!(self, Self::Allow)
    }

    pub const fn is_deny(&self) -> bool {
        matches!(self, Self::Deny { .. })
    }

    pub const fn requires_approval(&self) -> bool {
        matches!(self, Self::RequireApproval { .. })
    }
}

fn deny(reason: impl Into<String>) -> CapabilityDecision {
    CapabilityDecision::Deny {
        reason: reason.into(),
    }
}

/// Evaluate a request. Deny is the default and every other answer is earned.
///
/// The order of the checks is the policy. Structure first, because a
/// malformed request cannot be reasoned about; then origin, because no
/// amount of legitimate-looking content earns a page native authority; then
/// consequence, because the remaining question is only how sure we need the
/// user to be.
pub fn evaluate(request: &CapabilityRequest) -> CapabilityDecision {
    if let Err(err) = request.validate() {
        return deny(format!("malformed request: {err}"));
    }

    let capability = request.capability;

    if capability.is_native_authority() && !request.origin.may_hold_native_authority() {
        return deny(format!(
            "{} may not hold native authority; {:?} is {:?}",
            request.origin.label(),
            capability,
            capability.consequence()
        ));
    }

    match capability.consequence() {
        ConsequenceClass::Observational | ConsequenceClass::ReversibleLocal => {
            CapabilityDecision::Allow
        }
        ConsequenceClass::LocalEffect | ConsequenceClass::RemoteEffect => {
            if request.explicitly_authorized() {
                CapabilityDecision::Allow
            } else {
                CapabilityDecision::RequireApproval {
                    reason: format!(
                        "{:?} has {:?} and was not explicitly authorized",
                        capability,
                        capability.consequence()
                    ),
                }
            }
        }
        ConsequenceClass::HighConsequence | ConsequenceClass::Irreversible => {
            if request.explicitly_authorized() {
                CapabilityDecision::Allow
            } else {
                CapabilityDecision::RequireApproval {
                    reason: format!(
                        "{:?} is {:?} and always needs a person to say so",
                        capability,
                        capability.consequence()
                    ),
                }
            }
        }
    }
}

/// Evaluate a capability parsed from untrusted input.
///
/// The separate entry point exists because deserialization is where an
/// unknown capability actually arrives. `Capability` is a closed enum, so
/// serde rejects anything outside it — this turns that rejection into a
/// `Deny` rather than letting a parse error be handled as a transport
/// problem somewhere far from the security decision.
pub fn evaluate_untrusted_json(json: &str) -> CapabilityDecision {
    match serde_json::from_str::<CapabilityRequest>(json) {
        Ok(request) => evaluate(&request),
        Err(err) => deny(format!("unparseable or unknown capability request: {err}")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn user_request(capability: Capability) -> CapabilityRequest {
        CapabilityRequest::new(capability, Origin::User, "subject")
    }

    fn page_request(capability: Capability) -> CapabilityRequest {
        CapabilityRequest::new(
            capability,
            Origin::WebContent {
                url: "https://example.test/page".to_owned(),
            },
            "subject",
        )
    }

    #[test]
    fn observational_capabilities_are_allowed() {
        assert!(evaluate(&user_request(Capability::Read)).is_allow());
        assert!(evaluate(&user_request(Capability::Retrieve)).is_allow());
    }

    #[test]
    fn reversible_local_capabilities_are_allowed() {
        assert!(evaluate(&user_request(Capability::Navigate)).is_allow());
        assert!(evaluate(&user_request(Capability::PatchDom)).is_allow());
    }

    #[test]
    fn effectful_capabilities_need_approval() {
        assert!(evaluate(&user_request(Capability::Write)).requires_approval());
        assert!(evaluate(&user_request(Capability::Network)).requires_approval());
    }

    #[test]
    fn irreversible_capabilities_need_approval() {
        assert!(evaluate(&user_request(Capability::Spend)).requires_approval());
        assert!(evaluate(&user_request(Capability::Delete)).requires_approval());
        assert!(evaluate(&user_request(Capability::Transfer)).requires_approval());
    }

    #[test]
    fn explicit_user_authorization_allows_high_consequence() {
        let request = user_request(Capability::Spend).authorized_by_user();
        assert!(evaluate(&request).is_allow());
    }

    #[test]
    fn a_page_may_read_and_navigate() {
        assert!(evaluate(&page_request(Capability::Read)).is_allow());
        assert!(evaluate(&page_request(Capability::Navigate)).is_allow());
        assert!(evaluate(&page_request(Capability::PatchDom)).is_allow());
    }

    #[test]
    fn a_page_may_not_reach_the_machine() {
        for capability in [
            Capability::Write,
            Capability::Install,
            Capability::Spend,
            Capability::Sign,
            Capability::Delete,
            Capability::Build,
        ] {
            assert!(
                evaluate(&page_request(capability)).is_deny(),
                "{capability:?} must be denied to web content"
            );
        }
    }

    #[test]
    fn a_page_cannot_authorize_itself() {
        let request = page_request(Capability::Spend).authorized_by_user();
        assert!(
            evaluate(&request).is_deny(),
            "a request setting its own authorization flag is the escalation, \
             not the exception"
        );
    }

    #[test]
    fn model_output_cannot_authorize_itself() {
        let request = CapabilityRequest::new(
            Capability::Install,
            Origin::LlmOutput {
                model: "any".to_owned(),
            },
            "subject",
        )
        .authorized_by_user();
        assert!(evaluate(&request).is_deny());
    }

    #[test]
    fn a_peer_may_not_hold_native_authority() {
        let request = CapabilityRequest::new(
            Capability::Write,
            Origin::Peer {
                peer_id: "peer-1".to_owned(),
            },
            "subject",
        );
        assert!(evaluate(&request).is_deny());
    }

    #[test]
    fn an_empty_subject_is_denied() {
        let request = CapabilityRequest::new(Capability::Read, Origin::User, "   ");
        assert!(evaluate(&request).is_deny());
    }

    #[test]
    fn a_future_schema_version_is_denied() {
        let mut request = user_request(Capability::Read);
        request.schema_version = SchemaVersion(99);
        assert!(evaluate(&request).is_deny());
    }

    #[test]
    fn an_empty_web_origin_url_is_denied() {
        let request = CapabilityRequest::new(
            Capability::Read,
            Origin::WebContent { url: String::new() },
            "subject",
        );
        assert!(evaluate(&request).is_deny());
    }

    #[test]
    fn an_unknown_capability_is_denied() {
        let json = r#"{
            "schema_version": 1,
            "trace_id": "trc_000000000000000000000",
            "capability": "LAUNCH_MISSILES",
            "origin": {"kind": "user"},
            "subject": "s",
            "requested_at": 0,
            "user_authorized": true
        }"#;
        assert!(evaluate_untrusted_json(json).is_deny());
    }

    #[test]
    fn malformed_json_is_denied() {
        assert!(evaluate_untrusted_json("{not json").is_deny());
    }

    #[test]
    fn a_valid_request_survives_a_json_round_trip() {
        let request = user_request(Capability::Read);
        let json = serde_json::to_string(&request).unwrap();
        assert!(evaluate_untrusted_json(&json).is_allow());
    }

    #[test]
    fn consequence_classes_are_ordered() {
        assert!(ConsequenceClass::Observational < ConsequenceClass::Irreversible);
        assert!(ConsequenceClass::LocalEffect < ConsequenceClass::HighConsequence);
    }

    #[test]
    fn native_authority_starts_at_local_effect() {
        assert!(!Capability::Read.is_native_authority());
        assert!(!Capability::PatchDom.is_native_authority());
        assert!(Capability::Write.is_native_authority());
        assert!(Capability::Spend.is_native_authority());
    }

    #[test]
    fn every_capability_has_a_consequence_class() {
        for capability in [
            Capability::Read,
            Capability::Navigate,
            Capability::PatchDom,
            Capability::Network,
            Capability::Infer,
            Capability::Embed,
            Capability::RunTests,
            Capability::Build,
            Capability::Store,
            Capability::Retrieve,
            Capability::Write,
            Capability::Install,
            Capability::Publish,
            Capability::Spend,
            Capability::Delete,
            Capability::Sign,
            Capability::Transfer,
        ] {
            let _ = capability.consequence();
        }
    }
}
