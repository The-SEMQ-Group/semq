// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

//! CodecConfig: the rule, discriminated by operator.

use std::fmt;
use std::hash::{Hash, Hasher};

use semq_sys as sys;

use crate::error::{check, new_error, Error, Result};

/// The three operators. Values are pinned in the canonical form.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum Operator {
    /// Digital-root symbol per coordinate; parameter `scale`.
    Orbit = 0,
    /// Angular sector per coordinate pair; parameter `sectors`.
    Phase = 1,
    /// Sign and magnitude bin per coordinate; parameter `bins`.
    Quant = 2,
}

impl Operator {
    /// `"orbit"`, `"phase"` or `"quant"`.
    pub fn name(self) -> &'static str {
        match self {
            Operator::Orbit => "orbit",
            Operator::Phase => "phase",
            Operator::Quant => "quant",
        }
    }

    /// The name of the operator's parameter: `"scale"`, `"sectors"` or `"bins"`.
    pub fn parameter_name(self) -> &'static str {
        match self {
            Operator::Orbit => "scale",
            Operator::Phase => "sectors",
            Operator::Quant => "bins",
        }
    }

    pub(crate) fn as_raw(self) -> u32 {
        self as u32
    }

    fn from_raw(op: u32) -> Option<Operator> {
        match op {
            sys::SEMQ_ORBIT => Some(Operator::Orbit),
            sys::SEMQ_PHASE => Some(Operator::Phase),
            sys::SEMQ_QUANT => Some(Operator::Quant),
            _ => None,
        }
    }
}

impl fmt::Display for Operator {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.name())
    }
}

type Constructor =
    unsafe extern "C" fn(u32, u32, *mut sys::semq_config_t, *mut sys::semq_error_t) -> u32;

/// An immutable value: operator, dimension and the operator's parameter.
///
/// Build one with [`quant`](Self::quant), [`phase`](Self::phase) or
/// [`orbit`](Self::orbit). Equality and hashing are those of the 13
/// canonical bytes. The parameter accessors [`bins`](Self::bins),
/// [`sectors`](Self::sectors), [`scale`](Self::scale) and
/// [`max_magnitude`](Self::max_magnitude) return `None` for the operators
/// they do not apply to; [`parameter`](Self::parameter) is the one that does.
#[derive(Clone, Copy)]
pub struct CodecConfig {
    raw: sys::semq_config_t,
    bytes: [u8; 13],
    operator: Operator,
}

impl CodecConfig {
    /// The orbit scale used by [`orbit_default`](Self::orbit_default).
    pub const DEFAULT_SCALE: u32 = 50;

    /// orbit: digital-root symbol per coordinate; `scale` in `[1, 2^30]`.
    pub fn orbit(dim: u32, scale: u32) -> Result<CodecConfig> {
        Self::make(sys::semq_config_orbit, dim, scale, "config_orbit")
    }

    /// orbit with the default scale, [`DEFAULT_SCALE`](Self::DEFAULT_SCALE).
    pub fn orbit_default(dim: u32) -> Result<CodecConfig> {
        Self::orbit(dim, Self::DEFAULT_SCALE)
    }

    /// phase: angular sector per coordinate pair; `dim` even, `sectors` in
    /// `[2, 256]`, and `dim` a multiple of 4 when `sectors <= 16`.
    pub fn phase(dim: u32, sectors: u32) -> Result<CodecConfig> {
        Self::make(sys::semq_config_phase, dim, sectors, "config_phase")
    }

    /// quant: sign and magnitude bin per coordinate; `bins` in `[2, 64]`.
    pub fn quant(dim: u32, bins: u32) -> Result<CodecConfig> {
        Self::make(sys::semq_config_quant, dim, bins, "config_quant")
    }

    fn make(ctor: Constructor, dim: u32, p1: u32, operation: &'static str) -> Result<CodecConfig> {
        let mut raw = sys::semq_config_t {
            op: 0,
            dim: 0,
            p1: 0,
            p2: 0,
        };
        let mut err = new_error();
        // SAFETY: both out-pointers are valid for the call.
        let status = unsafe { ctor(dim, p1, &mut raw, &mut err) };
        check(status, &err, operation)?;
        Self::from_raw(raw, operation)
    }

    /// Parse the 13-byte canonical form.
    pub fn from_bytes(bytes: &[u8; 13]) -> Result<CodecConfig> {
        let mut raw = sys::semq_config_t {
            op: 0,
            dim: 0,
            p1: 0,
            p2: 0,
        };
        let mut err = new_error();
        // SAFETY: `bytes` holds 13 readable bytes; the out-pointers are valid.
        let status = unsafe { sys::semq_config_from_bytes(bytes.as_ptr(), &mut raw, &mut err) };
        check(status, &err, "config_from_bytes")?;
        Self::from_raw(raw, "config_from_bytes")
    }

    /// Wrap a struct the core produced or validated.
    pub(crate) fn from_raw(
        raw: sys::semq_config_t,
        operation: &'static str,
    ) -> Result<CodecConfig> {
        let mut err = new_error();
        // SAFETY: `raw` is a complete struct; the error pointer is valid.
        let status = unsafe { sys::semq_config_validate(&raw, &mut err) };
        check(status, &err, operation)?;
        let operator = Operator::from_raw(raw.op).ok_or_else(|| {
            Error::native(
                operation,
                sys::SEMQ_ERR_INTERNAL,
                None,
                None,
                "validated config has an unknown operator",
            )
        })?;
        let mut bytes = [0u8; 13];
        // SAFETY: `raw` is valid and `bytes` has room for the 13-byte form.
        unsafe { sys::semq_config_to_bytes(&raw, bytes.as_mut_ptr()) };
        Ok(CodecConfig {
            raw,
            bytes,
            operator,
        })
    }

    pub(crate) fn as_raw(&self) -> &sys::semq_config_t {
        &self.raw
    }

    /// The 13-byte canonical form.
    pub fn to_bytes(self) -> [u8; 13] {
        self.bytes
    }

    /// The operator.
    pub fn operator(self) -> Operator {
        self.operator
    }

    /// The vector dimension.
    pub fn dim(self) -> u32 {
        self.raw.dim
    }

    /// The operator rule revision (`0`).
    pub fn rule_revision(self) -> u32 {
        self.raw.p2
    }

    /// The operator's parameter: `scale`, `sectors` or `bins`.
    pub fn parameter(self) -> u32 {
        self.raw.p1
    }

    /// The orbit scale; `None` for other operators.
    pub fn scale(self) -> Option<u32> {
        (self.operator == Operator::Orbit).then_some(self.raw.p1)
    }

    /// The phase sector count; `None` for other operators.
    pub fn sectors(self) -> Option<u32> {
        (self.operator == Operator::Phase).then_some(self.raw.p1)
    }

    /// The quant bin count per sign; `None` for other operators.
    pub fn bins(self) -> Option<u32> {
        (self.operator == Operator::Quant).then_some(self.raw.p1)
    }

    /// Bytes of one canonical row.
    pub fn bytes_per_vector(self) -> u32 {
        // SAFETY: `raw` is valid.
        unsafe { sys::semq_config_bytes_per_vector(&self.raw) }
    }

    /// Symbols per row: `dim` for orbit and quant, `dim / 2` for phase.
    pub fn units_per_row(self) -> u32 {
        // SAFETY: `raw` is valid.
        unsafe { sys::semq_config_units_per_row(&self.raw) }
    }

    /// quant only: `(float)(2.0 / sqrt(dim))`, computed by the core; `None`
    /// for other operators.
    pub fn max_magnitude(self) -> Option<f32> {
        // SAFETY: `raw` is valid.
        (self.operator == Operator::Quant)
            .then(|| unsafe { sys::semq_config_max_magnitude(&self.raw) })
    }
}

impl PartialEq for CodecConfig {
    fn eq(&self, other: &CodecConfig) -> bool {
        self.bytes == other.bytes
    }
}

impl Eq for CodecConfig {}

impl Hash for CodecConfig {
    fn hash<H: Hasher>(&self, state: &mut H) {
        self.bytes.hash(state);
    }
}

/// `quant(dim=4, bins=4)`: the form the other summaries embed.
impl fmt::Display for CodecConfig {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "{}(dim={}, {}={})",
            self.operator().name(),
            self.dim(),
            self.operator().parameter_name(),
            self.parameter()
        )
    }
}

impl fmt::Debug for CodecConfig {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("CodecConfig")
            .field("operator", &self.operator.name())
            .field("dim", &self.raw.dim)
            .field(self.operator.parameter_name(), &self.raw.p1)
            .field("rule_revision", &self.raw.p2)
            .finish()
    }
}
