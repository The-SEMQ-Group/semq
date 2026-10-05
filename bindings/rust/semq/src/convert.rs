// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

//! Conversions between Rust values and the C ABI: manifests, borrowed
//! views into handles, and hex rendering. Every rule about bytes stays in
//! the core; this module checks only what the C types cannot express.

use std::collections::BTreeMap;
use std::marker::PhantomData;
use std::ptr::{self, NonNull};
use std::slice;

use semq_sys as sys;

use crate::error::{Error, Result};
use crate::ids::ptr_or_null;

/// A manifest: UTF-8 keys to UTF-8 values, stored verbatim and never
/// verified. Keys are at most 256 bytes, values at most 65536 bytes, and
/// there are at most 4096 pairs; the core enforces the limits.
pub type Manifest = BTreeMap<String, String>;

/// A `semq_pair_t` array borrowing a manifest's strings.
pub(crate) struct CManifest<'a> {
    pairs: Vec<sys::semq_pair_t>,
    _borrow: PhantomData<&'a Manifest>,
}

impl CManifest<'_> {
    pub(crate) fn as_ptr(&self) -> *const sys::semq_pair_t {
        ptr_or_null(&self.pairs)
    }

    pub(crate) fn len(&self) -> u32 {
        // Bounded by `u32` in `manifest_to_c`.
        self.pairs.len() as u32
    }
}

/// Build the pair array for a manifest; `None` is the empty manifest.
pub(crate) fn manifest_to_c(manifest: Option<&Manifest>) -> Result<CManifest<'_>> {
    let mut pairs = Vec::new();
    if let Some(manifest) = manifest {
        if u32::try_from(manifest.len()).is_err() {
            return Err(Error::invalid("manifest has too many pairs"));
        }
        pairs.reserve(manifest.len());
        for (i, (key, value)) in manifest.iter().enumerate() {
            let field = Some(i as u64);
            let key_len = u32::try_from(key.len())
                .map_err(|_| Error::invalid_at(None, field, "manifest key is too long"))?;
            let value_len = u32::try_from(value.len())
                .map_err(|_| Error::invalid_at(None, field, "manifest value is too long"))?;
            pairs.push(sys::semq_pair_t {
                key: key.as_ptr(),
                key_len,
                value: ptr_or_null(value.as_bytes()),
                value_len,
            });
        }
    }
    Ok(CManifest {
        pairs,
        _borrow: PhantomData,
    })
}

/// View `len` items at `ptr`; empty when `len` is 0. NULL with a positive length is a core defect.
///
/// # Safety
///
/// When `len > 0`, `ptr` must point to `len` initialized, aligned `T` that
/// stay valid and unmodified for the lifetime `'a`.
pub(crate) unsafe fn borrowed<'a, T>(ptr: *const T, len: usize) -> &'a [T] {
    if len == 0 {
        return &[];
    }
    assert!(!ptr.is_null(), "SEMQ core returned a NULL non-empty buffer");
    // SAFETY: the caller guarantees the pointee and its lifetime.
    unsafe { slice::from_raw_parts(ptr, len) }
}

/// Copy `len` UTF-8 bytes at `ptr` into a `String`; invalid UTF-8 is a core invariant violation.
///
/// # Safety
///
/// As for [`borrowed`], for the duration of the call.
pub(crate) unsafe fn text(ptr: *const u8, len: usize) -> String {
    // SAFETY: forwarded to the caller.
    let bytes = unsafe { borrowed(ptr, len) };
    std::str::from_utf8(bytes)
        .expect("SEMQ core returned invalid UTF-8")
        .to_owned()
}

/// Lowercase hex.
pub(crate) fn hex(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut out = String::with_capacity(bytes.len() * 2);
    for &b in bytes {
        out.push(DIGITS[(b >> 4) as usize] as char);
        out.push(DIGITS[(b & 0x0f) as usize] as char);
    }
    out
}

/// A zeroed part, for arrays the core fills.
pub(crate) fn empty_part() -> sys::semq_part_t {
    sys::semq_part_t {
        ptr: ptr::null(),
        len: 0,
    }
}

/// A handle the core just produced, freed unless [`release`](Self::release)
/// is called: keeps early returns in constructors leak-free.
pub(crate) struct FreeOnDrop<T> {
    ptr: NonNull<T>,
    free: unsafe extern "C" fn(*mut T),
}

impl<T> FreeOnDrop<T> {
    pub(crate) fn new(ptr: NonNull<T>, free: unsafe extern "C" fn(*mut T)) -> FreeOnDrop<T> {
        FreeOnDrop { ptr, free }
    }

    pub(crate) fn ptr(&self) -> *mut T {
        self.ptr.as_ptr()
    }

    /// Hand the handle over without freeing it.
    pub(crate) fn release(self) -> NonNull<T> {
        let ptr = self.ptr;
        std::mem::forget(self);
        ptr
    }
}

impl<T> Drop for FreeOnDrop<T> {
    fn drop(&mut self) {
        // SAFETY: the handle came from the core and is freed exactly once.
        unsafe { (self.free)(self.ptr.as_ptr()) }
    }
}

#[cfg(test)]
mod tests {
    #[test]
    #[should_panic(expected = "SEMQ core returned invalid UTF-8")]
    fn invalid_native_text_is_never_replaced() {
        let bytes = [0xff];
        // SAFETY: the buffer is readable for its entire length.
        unsafe { super::text(bytes.as_ptr(), bytes.len()) };
    }
}
