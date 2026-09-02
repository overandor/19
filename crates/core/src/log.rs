//! Structured logging, with redaction that is not optional.
//!
//! Logs are where secrets leak. Not through a deliberate decision — through
//! a struct that gained a `token` field months after someone wrote
//! `debug!("{:?}", request)`. So this module does not offer a way to log an
//! arbitrary value: an event is a set of explicitly named fields, and every
//! field name is checked against a deny-list before the value is recorded.
//!
//! A field whose name looks like a secret is stored as `"[redacted]"` and
//! the event carries a count of what was redacted, so the redaction is
//! visible rather than silent. Silent redaction and no redaction look the
//! same in a log file.
//!
//! This emits structured records; it does not choose a sink. Wiring it to
//! stderr, a file, or a collector is the runtime's job and is not part of
//! this increment.

use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};

use crate::ids::{Timestamp, TraceId};

/// Field names that must never carry a value into a log.
///
/// Matched as substrings, case-insensitively, so `auth_token`,
/// `Authorization` and `user_password_hash` are all caught by the entries
/// below.
const REDACT_SUBSTRINGS: &[&str] = &[
    "password",
    "passwd",
    "secret",
    "token",
    "cookie",
    "session_id",
    "private_key",
    "privatekey",
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "seed_phrase",
    "mnemonic",
    "form_value",
];

pub const REDACTED: &str = "[redacted]";

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Level {
    Debug,
    Info,
    Warn,
    Error,
}

/// One structured log record.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct LogEvent {
    pub timestamp: Timestamp,
    pub level: Level,
    pub component: String,
    pub event: String,
    pub trace_id: Option<TraceId>,
    pub fields: BTreeMap<String, String>,
    /// How many fields were redacted. Non-zero means something was withheld.
    pub redacted_count: usize,
}

impl LogEvent {
    pub fn new(level: Level, component: impl Into<String>, event: impl Into<String>) -> Self {
        Self {
            timestamp: Timestamp::now(),
            level,
            component: component.into(),
            event: event.into(),
            trace_id: None,
            fields: BTreeMap::new(),
            redacted_count: 0,
        }
    }

    #[must_use]
    pub fn with_trace(mut self, trace_id: TraceId) -> Self {
        self.trace_id = Some(trace_id);
        self
    }

    /// Attach a field, redacting it if its name looks like a secret.
    ///
    /// There is deliberately no escape hatch. A caller that genuinely needs
    /// to record a sensitive value should not be doing it through the log.
    #[must_use]
    pub fn with_field(mut self, key: impl Into<String>, value: impl Into<String>) -> Self {
        let key = key.into();
        if should_redact(&key) {
            self.fields.insert(key, REDACTED.to_owned());
            self.redacted_count += 1;
        } else {
            self.fields.insert(key, value.into());
        }
        self
    }

    pub fn to_json(&self) -> String {
        // A log line that cannot be serialized must not take the process
        // with it, so this degrades to a minimal record rather than
        // returning an error nobody at a log site will handle.
        serde_json::to_string(self).unwrap_or_else(|_| {
            format!(
                r#"{{"level":"ERROR","component":"log","event":"unserializable_event","original":"{}"}}"#,
                self.event.escape_debug()
            )
        })
    }
}

/// Whether a field name must be redacted.
pub fn should_redact(key: &str) -> bool {
    let lowered = key.to_ascii_lowercase();
    REDACT_SUBSTRINGS
        .iter()
        .any(|needle| lowered.contains(needle))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ordinary_fields_are_recorded() {
        let event = LogEvent::new(Level::Info, "storage", "object_written")
            .with_field("hash", "abc123")
            .with_field("bytes", "4096");
        assert_eq!(event.fields.get("hash").unwrap(), "abc123");
        assert_eq!(event.redacted_count, 0);
    }

    #[test]
    fn secrets_are_redacted_by_field_name() {
        for key in [
            "password",
            "api_key",
            "Authorization",
            "session_id",
            "auth_token",
            "user_cookie",
            "private_key",
            "SEED_PHRASE",
            "form_value_ssn",
        ] {
            let event = LogEvent::new(Level::Info, "web", "submit").with_field(key, "hunter2");
            assert_eq!(
                event.fields.get(key).map(String::as_str),
                Some(REDACTED),
                "{key} must be redacted"
            );
            assert!(
                !event.to_json().contains("hunter2"),
                "{key} leaked its value"
            );
        }
    }

    #[test]
    fn redaction_is_counted_and_therefore_visible() {
        let event = LogEvent::new(Level::Warn, "auth", "login")
            .with_field("user", "alice")
            .with_field("password", "hunter2")
            .with_field("token", "xyz");
        assert_eq!(event.redacted_count, 2);
        assert!(event.to_json().contains("\"redacted_count\":2"));
    }

    #[test]
    fn matching_is_case_insensitive_and_substring_based() {
        assert!(should_redact("X-Auth-Token"));
        assert!(should_redact("user_password_hash"));
        assert!(!should_redact("username"));
        assert!(!should_redact("component"));
    }

    #[test]
    fn events_carry_the_required_fields() {
        let trace = TraceId::generate();
        let event = LogEvent::new(Level::Error, "compute", "migration_failed").with_trace(trace);
        let json = event.to_json();
        for required in ["timestamp", "level", "component", "event", "trace_id"] {
            assert!(json.contains(required), "missing {required}");
        }
    }

    #[test]
    fn events_round_trip() {
        let event = LogEvent::new(Level::Debug, "core", "probe").with_field("k", "v");
        let restored: LogEvent = serde_json::from_str(&event.to_json()).unwrap();
        assert_eq!(restored, event);
    }

    #[test]
    fn levels_are_ordered() {
        assert!(Level::Debug < Level::Error);
    }
}
