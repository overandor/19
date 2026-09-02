//! Dimensional units for physical resources.
//!
//! This module exists because of one invariant:
//!
//! ```text
//! COMPUTE CREDIT != PHYSICAL COMPUTE
//! ```
//!
//! A credit is an accounting entry. Bytes of RAM are a physical fact. They
//! are both "numbers" and a system that lets them meet as bare `u64`s will
//! eventually add one to the other, or reserve capacity it does not have
//! because a credit balance was read as a byte count. So they are separate
//! types with no arithmetic between them, and the compiler refuses the
//! mistake instead of a reviewer having to catch it.
//!
//! `tests/invariants` proves the separation holds.

use std::fmt;

use serde::{Deserialize, Serialize};

/// A quantity of physical memory, in bytes.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(transparent)]
pub struct Bytes(pub u64);

impl Bytes {
    pub const ZERO: Self = Self(0);

    pub const fn from_mib(mib: u64) -> Self {
        Self(mib * 1024 * 1024)
    }

    pub const fn from_gib(gib: u64) -> Self {
        Self(gib * 1024 * 1024 * 1024)
    }

    pub const fn get(self) -> u64 {
        self.0
    }

    pub fn as_mib(self) -> f64 {
        self.0 as f64 / (1024.0 * 1024.0)
    }

    pub fn as_gib(self) -> f64 {
        self.0 as f64 / (1024.0 * 1024.0 * 1024.0)
    }

    /// Saturating so an accounting slip cannot wrap into a huge number and
    /// be read as spare capacity.
    pub const fn saturating_sub(self, other: Self) -> Self {
        Self(self.0.saturating_sub(other.0))
    }

    pub const fn saturating_add(self, other: Self) -> Self {
        Self(self.0.saturating_add(other.0))
    }

    /// What fraction of `total` this is. Zero when `total` is zero, rather
    /// than a division by zero or a NaN that later compares false to
    /// everything.
    pub fn fraction_of(self, total: Self) -> f64 {
        if total.0 == 0 {
            0.0
        } else {
            self.0 as f64 / total.0 as f64
        }
    }
}

impl fmt::Display for Bytes {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        if self.0 >= 1024 * 1024 * 1024 {
            write!(f, "{:.2}GiB", self.as_gib())
        } else {
            write!(f, "{:.1}MiB", self.as_mib())
        }
    }
}

/// An accounting entry. Never a physical quantity.
///
/// Has no conversion to or from [`Bytes`] anywhere in this workspace, and
/// must not acquire one: the exchange rate between a credit and a byte is a
/// policy decision, not a cast.
#[derive(Debug, Clone, Copy, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(transparent)]
pub struct Credits(pub f64);

impl Credits {
    pub const ZERO: Self = Self(0.0);

    pub const fn get(self) -> f64 {
        self.0
    }

    pub fn is_finite_and_non_negative(self) -> bool {
        self.0.is_finite() && self.0 >= 0.0
    }
}

impl fmt::Display for Credits {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{:.4} credits", self.0)
    }
}

mod sealed {
    pub trait Sealed {}
    impl Sealed for super::Bytes {}
}

/// Marks a type as a real, physical quantity that can be reserved.
///
/// Sealed, and implemented for [`Bytes`] alone. This is the executable
/// half of the invariant
///
/// ```text
/// COMPUTE CREDIT != PHYSICAL COMPUTE
/// ```
///
/// A scheduler generic over `PhysicalQuantity` cannot be handed [`Credits`]
/// — not by convention, but because the program does not compile:
///
/// ```compile_fail
/// use pwr_core::units::{Credits, PhysicalQuantity};
/// fn reserve<T: PhysicalQuantity>(_amount: T) {}
/// reserve(Credits(10.0));
/// ```
///
/// while the physical quantity is accepted:
///
/// ```
/// use pwr_core::units::{Bytes, PhysicalQuantity};
/// fn reserve<T: PhysicalQuantity>(_amount: T) {}
/// reserve(Bytes::from_gib(1));
/// ```
pub trait PhysicalQuantity: sealed::Sealed + Copy {
    /// The magnitude, in this quantity's own unit.
    fn magnitude(self) -> u64;
}

impl PhysicalQuantity for Bytes {
    fn magnitude(self) -> u64 {
        self.0
    }
}

/// A measurement that may genuinely be unavailable.
///
/// The alternative — a sentinel like `0` or `u64::MAX` — is how a runtime
/// ends up reporting a GPU with no memory, or scheduling against capacity
/// nobody measured. An unknown value must stay visibly unknown all the way
/// to whoever decides what to do about it.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Measured<T> {
    Known(T),
    Unknown,
}

impl<T> Measured<T> {
    pub fn known(value: T) -> Self {
        Self::Known(value)
    }

    pub const fn is_known(&self) -> bool {
        matches!(self, Self::Known(_))
    }

    pub fn value(self) -> Option<T> {
        match self {
            Self::Known(value) => Some(value),
            Self::Unknown => None,
        }
    }

    pub fn as_ref(&self) -> Option<&T> {
        match self {
            Self::Known(value) => Some(value),
            Self::Unknown => None,
        }
    }
}

impl<T: fmt::Display> fmt::Display for Measured<T> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Known(value) => write!(f, "{value}"),
            Self::Unknown => f.write_str("unknown"),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn byte_conversions() {
        assert_eq!(Bytes::from_gib(1), Bytes(1_073_741_824));
        assert_eq!(Bytes::from_mib(1024), Bytes::from_gib(1));
        assert!((Bytes::from_gib(24).as_gib() - 24.0).abs() < f64::EPSILON);
    }

    #[test]
    fn subtraction_saturates_instead_of_wrapping() {
        assert_eq!(Bytes(1).saturating_sub(Bytes(5)), Bytes::ZERO);
    }

    #[test]
    fn addition_saturates() {
        assert_eq!(Bytes(u64::MAX).saturating_add(Bytes(1)), Bytes(u64::MAX));
    }

    #[test]
    fn fraction_of_zero_is_zero_not_nan() {
        assert_eq!(Bytes(5).fraction_of(Bytes::ZERO), 0.0);
    }

    #[test]
    fn fraction_of_total() {
        assert!((Bytes(50).fraction_of(Bytes(200)) - 0.25).abs() < f64::EPSILON);
    }

    #[test]
    fn display_picks_a_readable_unit() {
        assert_eq!(Bytes::from_gib(2).to_string(), "2.00GiB");
        assert_eq!(Bytes::from_mib(16).to_string(), "16.0MiB");
    }

    #[test]
    fn credits_validate_their_own_range() {
        assert!(Credits(1.5).is_finite_and_non_negative());
        assert!(!Credits(-1.0).is_finite_and_non_negative());
        assert!(!Credits(f64::NAN).is_finite_and_non_negative());
        assert!(!Credits(f64::INFINITY).is_finite_and_non_negative());
    }

    #[test]
    fn unknown_measurements_stay_unknown() {
        let unknown: Measured<Bytes> = Measured::Unknown;
        assert!(!unknown.is_known());
        assert_eq!(unknown.value(), None);
        assert_eq!(unknown.to_string(), "unknown");
    }

    #[test]
    fn bytes_are_a_physical_quantity() {
        fn reserve<T: PhysicalQuantity>(amount: T) -> u64 {
            amount.magnitude()
        }
        assert_eq!(reserve(Bytes::from_mib(1)), 1024 * 1024);
    }

    #[test]
    fn known_measurements_carry_their_value() {
        let known = Measured::known(Bytes::from_gib(24));
        assert!(known.is_known());
        assert_eq!(known.value(), Some(Bytes::from_gib(24)));
    }
}
