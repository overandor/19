//! Content-addressed object storage, and the schema discipline around it.
//!
//! Objects are named by the hash of their contents, so the store has no
//! opinion about where a thing came from and no way to hold two different
//! objects under one name. Writes are idempotent by construction: storing
//! the same bytes twice is one object.
//!
//! Reads verify. Every `get` re-hashes what it read and compares, so
//! silent corruption on disk surfaces as an [`CoreError::Integrity`] at the
//! call site rather than as strange behaviour somewhere downstream. That
//! costs a hash per read and is worth it — a content-addressed store that
//! does not check content addresses is just a filesystem with awkward
//! filenames.
//!
//! See `docs/adr/0001-local-persistence.md` for why this is files rather
//! than SQLite.

use std::fs;
use std::path::{Path, PathBuf};

use pwr_core::{ContentHash, CoreError, CoreResult, SchemaVersion, hash_bytes, verify_bytes};
use serde::{Deserialize, Serialize, de::DeserializeOwned};

/// The schema version this build writes and can read.
pub const CURRENT_SCHEMA: SchemaVersion = SchemaVersion::V1;

/// A record with its schema version attached.
///
/// The version is stored *outside* the payload so it can be read without
/// first parsing the payload — which matters precisely in the case that
/// motivates versioning, where this build does not know the payload's
/// shape.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct StoredRecord<T> {
    pub schema_version: SchemaVersion,
    pub payload: T,
}

impl<T> StoredRecord<T> {
    pub fn new(payload: T) -> Self {
        Self {
            schema_version: CURRENT_SCHEMA,
            payload,
        }
    }
}

/// Read a record, refusing versions this build does not understand.
///
/// Three outcomes, deliberately distinct: a current record parses, a future
/// record fails with [`CoreError::UnsupportedSchema`] naming both versions,
/// and malformed bytes fail as a validation error. Collapsing the middle
/// case into "malformed" would tell an operator their data is corrupt when
/// it is merely newer than their binary.
pub fn load_record<T: DeserializeOwned>(json: &str) -> CoreResult<StoredRecord<T>> {
    /// Reads only the version, so a payload this build cannot parse still
    /// produces the right error.
    #[derive(Deserialize)]
    struct VersionProbe {
        schema_version: SchemaVersion,
    }

    let probe: VersionProbe = serde_json::from_str(json)
        .map_err(|err| CoreError::Validation(format!("record is not readable: {err}")))?;

    if probe.schema_version != CURRENT_SCHEMA {
        return Err(CoreError::UnsupportedSchema {
            found: probe.schema_version.get(),
            supported: CURRENT_SCHEMA.get(),
        });
    }

    serde_json::from_str(json)
        .map_err(|err| CoreError::Validation(format!("record payload is malformed: {err}")))
}

pub fn dump_record<T: Serialize>(record: &StoredRecord<T>) -> CoreResult<String> {
    serde_json::to_string(record)
        .map_err(|err| CoreError::Persistence(format!("record is not serializable: {err}")))
}

/// A content-addressed object store on the local filesystem.
#[derive(Debug, Clone)]
pub struct ObjectStore {
    root: PathBuf,
}

impl ObjectStore {
    /// Open (creating if needed) a store rooted at `root`.
    pub fn open(root: impl Into<PathBuf>) -> CoreResult<Self> {
        let root = root.into();
        fs::create_dir_all(&root)
            .map_err(|err| CoreError::Persistence(format!("cannot create {root:?}: {err}")))?;
        Ok(Self { root })
    }

    /// Store bytes, returning their content address.
    ///
    /// Writing the same bytes again is a no-op that returns the same hash,
    /// so callers never need to check first.
    pub fn put(&self, bytes: &[u8]) -> CoreResult<ContentHash> {
        let hash = hash_bytes(bytes);
        let path = self.path_for(&hash);

        if path.exists() {
            return Ok(hash);
        }

        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).map_err(|err| {
                CoreError::Persistence(format!("cannot create {parent:?}: {err}"))
            })?;
        }

        // Write to a temporary name and rename into place, so a crash
        // mid-write cannot leave a partial object under a hash that claims
        // to describe complete content.
        let temp = path.with_extension("partial");
        fs::write(&temp, bytes)
            .map_err(|err| CoreError::Persistence(format!("cannot write {temp:?}: {err}")))?;
        fs::rename(&temp, &path)
            .map_err(|err| CoreError::Persistence(format!("cannot commit {path:?}: {err}")))?;

        Ok(hash)
    }

    /// Read bytes back, verifying they still hash to their name.
    pub fn get(&self, hash: &ContentHash) -> CoreResult<Vec<u8>> {
        let path = self.path_for(hash);
        let bytes = fs::read(&path).map_err(|err| {
            CoreError::Persistence(format!("cannot read object {}: {err}", hash.short()))
        })?;
        verify_bytes(&bytes, hash)?;
        Ok(bytes)
    }

    pub fn contains(&self, hash: &ContentHash) -> bool {
        self.path_for(hash).exists()
    }

    /// Store a schema-versioned record, returning its content address.
    pub fn put_record<T: Serialize>(&self, payload: T) -> CoreResult<ContentHash> {
        let json = dump_record(&StoredRecord::new(payload))?;
        self.put(json.as_bytes())
    }

    /// Read a schema-versioned record back.
    pub fn get_record<T: DeserializeOwned>(&self, hash: &ContentHash) -> CoreResult<T> {
        let bytes = self.get(hash)?;
        let json = String::from_utf8(bytes)
            .map_err(|err| CoreError::Validation(format!("record is not utf-8: {err}")))?;
        Ok(load_record::<T>(&json)?.payload)
    }

    pub fn root(&self) -> &Path {
        &self.root
    }

    /// Objects are sharded by the first two hex characters, so one
    /// directory does not accumulate every object in the store.
    fn path_for(&self, hash: &ContentHash) -> PathBuf {
        let hex = hash.as_str();
        self.root.join(&hex[..2]).join(&hex[2..])
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
    struct Sample {
        name: String,
        count: u32,
    }

    fn temp_root(tag: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "pwr-storage-{tag}-{}",
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_nanos())
                .unwrap_or(0)
        ))
    }

    fn store(tag: &str) -> (ObjectStore, PathBuf) {
        let root = temp_root(tag);
        (ObjectStore::open(&root).unwrap(), root)
    }

    #[test]
    fn objects_round_trip() {
        let (store, root) = store("round-trip");
        let hash = store.put(b"payload").unwrap();
        assert_eq!(store.get(&hash).unwrap(), b"payload");
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn identical_bytes_are_one_object() {
        let (store, root) = store("dedup");
        let first = store.put(b"same").unwrap();
        let second = store.put(b"same").unwrap();
        assert_eq!(first, second);
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn different_bytes_are_different_objects() {
        let (store, root) = store("distinct");
        assert_ne!(store.put(b"a").unwrap(), store.put(b"b").unwrap());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn a_missing_object_is_a_persistence_error() {
        let (store, root) = store("missing");
        let hash = hash_bytes(b"never stored");
        assert!(matches!(store.get(&hash), Err(CoreError::Persistence(_))));
        assert!(!store.contains(&hash));
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn corruption_on_disk_is_detected_on_read() {
        let (store, root) = store("corruption");
        let hash = store.put(b"trustworthy").unwrap();

        // Tamper with the stored object behind the store's back.
        let path = store.path_for(&hash);
        fs::write(&path, b"tampered!!!").unwrap();

        assert!(
            matches!(store.get(&hash), Err(CoreError::Integrity { .. })),
            "a content-addressed store that does not check content addresses \
             is a filesystem with awkward filenames"
        );
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn records_round_trip_with_their_schema_version() {
        let (store, root) = store("records");
        let sample = Sample {
            name: "x".into(),
            count: 3,
        };
        let hash = store.put_record(sample.clone()).unwrap();
        assert_eq!(store.get_record::<Sample>(&hash).unwrap(), sample);
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn a_v1_record_loads() {
        let json = r#"{"schema_version":1,"payload":{"name":"x","count":1}}"#;
        assert_eq!(load_record::<Sample>(json).unwrap().payload.count, 1);
    }

    #[test]
    fn a_future_schema_version_fails_safely() {
        let json = r#"{"schema_version":99,"payload":{"name":"x","count":1}}"#;
        assert!(matches!(
            load_record::<Sample>(json),
            Err(CoreError::UnsupportedSchema {
                found: 99,
                supported: 1
            })
        ));
    }

    #[test]
    fn a_future_record_with_an_unreadable_payload_still_reports_the_version() {
        // The point of probing the version separately: this build cannot
        // parse the payload, and must still say "too new" rather than
        // "corrupt".
        let json = r#"{"schema_version":42,"payload":{"totally":"different"}}"#;
        assert!(matches!(
            load_record::<Sample>(json),
            Err(CoreError::UnsupportedSchema { found: 42, .. })
        ));
    }

    #[test]
    fn a_malformed_record_fails_safely() {
        assert!(matches!(
            load_record::<Sample>("{not json"),
            Err(CoreError::Validation(_))
        ));
    }

    #[test]
    fn a_record_missing_its_version_fails_safely() {
        let json = r#"{"payload":{"name":"x","count":1}}"#;
        assert!(load_record::<Sample>(json).is_err());
    }

    #[test]
    fn a_current_record_with_a_wrong_payload_is_a_validation_error() {
        let json = r#"{"schema_version":1,"payload":{"name":"x"}}"#;
        assert!(matches!(
            load_record::<Sample>(json),
            Err(CoreError::Validation(_))
        ));
    }

    #[test]
    fn objects_are_sharded_across_directories() {
        let (store, root) = store("sharding");
        let hash = store.put(b"shard me").unwrap();
        let path = store.path_for(&hash);
        assert_eq!(
            path.parent()
                .unwrap()
                .file_name()
                .unwrap()
                .to_str()
                .unwrap(),
            &hash.as_str()[..2]
        );
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn no_partial_files_remain_after_a_write() {
        let (store, root) = store("no-partials");
        store.put(b"complete").unwrap();
        let partials = walk(&root)
            .into_iter()
            .filter(|p| p.extension().is_some_and(|e| e == "partial"))
            .count();
        assert_eq!(partials, 0);
        let _ = fs::remove_dir_all(root);
    }

    fn walk(dir: &Path) -> Vec<PathBuf> {
        let mut found = Vec::new();
        let Ok(entries) = fs::read_dir(dir) else {
            return found;
        };
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() {
                found.extend(walk(&path));
            } else {
                found.push(path);
            }
        }
        found
    }
}
