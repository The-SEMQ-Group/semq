// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

//! BuildInfo: the identity of this build.

use std::collections::BTreeMap;
use std::ffi::CStr;
use std::os::raw::c_char;

use semq_sys as sys;

use crate::config::Operator;

/// The version of this crate, reported as `sdk_version`.
pub(crate) const SDK_VERSION: &str = env!("CARGO_PKG_VERSION");

/// Versions and kernel selection of the linked core.
///
/// `backend` maps each operator to the kernel the core runs for it on this
/// host. `build_id` identifies a reproducible build recipe; it is not a
/// provenance proof. No file is hashed at runtime.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BuildInfo {
    /// Version of this crate.
    pub sdk_version: String,
    /// Version compiled into the core from its `VERSION` file.
    pub core_version: String,
    /// Effective kernel per operator (`"scalar"`, `"neon"`, `"avx2"`, ...).
    pub backend: BTreeMap<Operator, String>,
    /// Compile-time build recipe identifier of the core.
    pub build_id: String,
}

/// Query the linked core.
pub fn build_info() -> BuildInfo {
    let backend = [Operator::Orbit, Operator::Phase, Operator::Quant]
        .into_iter()
        // SAFETY: the core returns a static string for any operator value.
        .map(|op| {
            let name = static_str(unsafe { sys::semq_backend_name(op.as_raw()) });
            (op, name.to_owned())
        })
        .collect();
    BuildInfo {
        sdk_version: SDK_VERSION.to_owned(),
        core_version: core_version().to_owned(),
        backend,
        build_id: build_id().to_owned(),
    }
}

pub(crate) fn core_version() -> &'static str {
    // SAFETY: returns a compile-time string literal.
    static_str(unsafe { sys::semq_core_version() })
}

pub(crate) fn build_id() -> &'static str {
    // SAFETY: returns a compile-time string literal.
    static_str(unsafe { sys::semq_build_id() })
}

pub(crate) fn status_name(status: u32) -> &'static str {
    // SAFETY: returns a string literal for any status value.
    static_str(unsafe { sys::semq_status_name(status) })
}

/// A NUL-terminated string literal the core owns; empty when NULL or not
/// UTF-8. The library is never unloaded, so the borrow is `'static`.
fn static_str(ptr: *const c_char) -> &'static str {
    if ptr.is_null() {
        return "";
    }
    // SAFETY: non-null, NUL-terminated, with static storage in the core.
    unsafe { CStr::from_ptr(ptr) }.to_str().unwrap_or("")
}
