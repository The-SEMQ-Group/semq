// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

//! Encoding: a state with an identity.

use std::fmt;
use std::io::{self, Read, Write};
use std::ptr::{self, NonNull};

use semq_sys as sys;

use crate::config::CodecConfig;
use crate::convert::{borrowed, empty_part, hex, manifest_to_c, text, FreeOnDrop, Manifest};
use crate::diff::Diff;
use crate::error::{check, new_error, Error, Result};
use crate::ids::{ptr_or_null, Id, IdKind, Ids};

/// An immutable set of ids with one canonical row each, a manifest and two
/// identities.
///
/// `content_digest` identifies the rows under the rule; `state_id` adds the
/// manifest. Equality of two Encodings is equality of `state_id`. Safe to
/// share between threads; freed on drop. The views [`rows`](Self::rows),
/// [`row`](Self::row), [`get`](Self::get) and [`ids`](Self::ids) borrow the
/// handle's memory.
pub struct Encoding {
    ptr: NonNull<sys::semq_encoding_t>,
    config: CodecConfig,
    id_kind: IdKind,
}

// SAFETY: an encoding is immutable after construction and the core keeps no
// mutable semantic state. Retention/release of the shared Encodings uses
// atomic reference counts on every supported target (enforced at C build).
// Rust borrows prevent Drop while a call or returned slice uses the handle.
unsafe impl Send for Encoding {}
unsafe impl Sync for Encoding {}

impl Drop for Encoding {
    fn drop(&mut self) {
        // SAFETY: the handle came from the core and is freed exactly once.
        unsafe { sys::semq_encoding_free(self.ptr.as_ptr()) }
    }
}

impl Encoding {
    /// Build from rows the caller already holds: `ids.len()` rows of
    /// `config.bytes_per_vector()` bytes, in input order, aligned with `ids`.
    ///
    /// The core sorts by id, rejects duplicates (`InvalidInput` naming the
    /// later row), checks row canonicity (symbols in the alphabet, padding
    /// zero), validates the manifest, copies the rows once and computes both
    /// digests. An empty `ids` gives the empty Encoding of its kind.
    pub fn new<'a>(
        ids: impl Into<Ids<'a>>,
        rows: &[u8],
        config: &CodecConfig,
        manifest: Option<&Manifest>,
    ) -> Result<Encoding> {
        let ids = ids.into();
        let n = ids.len();
        let bpv = config.bytes_per_vector() as usize;
        let expected = n
            .checked_mul(bpv)
            .ok_or_else(|| Error::invalid("rows length overflows"))?;
        if rows.len() != expected {
            return Err(Error::invalid(format!(
                "{n} ids need {expected} row bytes ({bpv} per row), got {}",
                rows.len()
            )));
        }
        let c_ids = ids.c_ids();
        let pairs = manifest_to_c(manifest)?;
        let mut out: *mut sys::semq_encoding_t = ptr::null_mut();
        let mut err = new_error();
        // SAFETY: `rows` holds `n × bpv` bytes; the id and manifest views
        // borrow data that outlives the call.
        let status = unsafe {
            sys::semq_encoding_create(
                config.as_raw(),
                c_ids.as_raw(),
                ptr_or_null(rows),
                pairs.as_ptr(),
                pairs.len(),
                &mut out,
                &mut err,
            )
        };
        check(status, &err, "encoding")?;
        Self::from_raw(out, "encoding")
    }

    /// Take ownership of a handle the core just produced.
    pub(crate) fn from_raw(
        ptr: *mut sys::semq_encoding_t,
        operation: &'static str,
    ) -> Result<Encoding> {
        let ptr = NonNull::new(ptr).ok_or_else(|| {
            Error::native(
                operation,
                sys::SEMQ_ERR_INTERNAL,
                None,
                None,
                "core returned a null encoding",
            )
        })?;
        let guard = FreeOnDrop::new(ptr, sys::semq_encoding_free);
        // SAFETY: the handle is live and owns the config it points to.
        let raw = unsafe { *sys::semq_encoding_config(guard.ptr()) };
        let config = CodecConfig::from_raw(raw, operation)?;
        // SAFETY: the handle is live.
        let kind = unsafe { sys::semq_encoding_id_kind(guard.ptr()) };
        let id_kind = IdKind::from_raw(kind).ok_or_else(|| {
            Error::native(
                operation,
                sys::SEMQ_ERR_INTERNAL,
                None,
                None,
                "encoding has an unknown id kind",
            )
        })?;
        Ok(Encoding {
            ptr: guard.release(),
            config,
            id_kind,
        })
    }

    pub(crate) fn as_ptr(&self) -> *const sys::semq_encoding_t {
        self.ptr.as_ptr()
    }

    // ---- persistence -----------------------------------------------------

    /// Parse a complete file image. Validates framing, config, sizes and
    /// limits, ids, manifest, both digests and row canonicity, in that
    /// order; the bytes are copied.
    pub fn from_bytes(image: &[u8]) -> Result<Encoding> {
        let mut out: *mut sys::semq_encoding_t = ptr::null_mut();
        let mut err = new_error();
        // SAFETY: `image` is readable for its length; out-pointers are live.
        let status = unsafe {
            sys::semq_encoding_load(ptr_or_null(image), image.len() as u64, &mut out, &mut err)
        };
        check(status, &err, "load")?;
        Self::from_raw(out, "load")
    }

    /// Read a file image to its end and parse it as [`from_bytes`](Self::from_bytes).
    ///
    /// A malformed or corrupt image is an `io::Error` of kind `InvalidData`
    /// whose source is the [`Error`]; call `from_bytes` on the bytes to get
    /// the typed error directly.
    pub fn read(mut reader: impl Read) -> io::Result<Encoding> {
        let mut image = Vec::new();
        reader.read_to_end(&mut image)?;
        Self::from_bytes(&image).map_err(io::Error::from)
    }

    /// Write the file image. Atomic replacement of a file (temporary file
    /// plus rename) is the caller's responsibility.
    pub fn write(&self, mut writer: impl Write) -> io::Result<()> {
        for part in self.parts() {
            if !part.is_empty() {
                writer.write_all(part)?;
            }
        }
        Ok(())
    }

    /// The file image.
    pub fn to_bytes(&self) -> Vec<u8> {
        // SAFETY: the handle is live.
        let size = unsafe { sys::semq_encoding_file_size(self.ptr.as_ptr()) } as usize;
        let mut out = Vec::with_capacity(size);
        for part in self.parts() {
            out.extend_from_slice(part);
        }
        out
    }

    /// The five ordered parts of the file image, borrowed from the handle.
    fn parts(&self) -> [&[u8]; 5] {
        let mut raw = [empty_part(); 5];
        // SAFETY: the handle is live and `raw` has room for 5 parts.
        unsafe { sys::semq_encoding_save_parts(self.ptr.as_ptr(), raw.as_mut_ptr()) };
        // SAFETY: each part points into memory the handle owns for its life.
        raw.map(|p| unsafe { borrowed(p.ptr, p.len as usize) })
    }

    // ---- access ----------------------------------------------------------

    /// The configuration the rows were produced under.
    pub fn config(&self) -> &CodecConfig {
        &self.config
    }

    /// The kind of every id.
    pub fn id_kind(&self) -> IdKind {
        self.id_kind
    }

    /// Number of rows.
    pub fn len(&self) -> usize {
        // SAFETY: the handle is live.
        unsafe { sys::semq_encoding_len(self.ptr.as_ptr()) as usize }
    }

    /// `true` when there are no rows.
    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    /// Canonical rows in id order, `n × bytes_per_vector` bytes, zero-copy.
    pub fn rows(&self) -> &[u8] {
        let mut len = 0u64;
        // SAFETY: the handle is live and `len` is a valid out-pointer.
        let ptr = unsafe { sys::semq_encoding_rows(self.ptr.as_ptr(), &mut len) };
        // SAFETY: the rows live as long as the handle, which `&self` borrows.
        unsafe { borrowed(ptr, len as usize) }
    }

    /// Row `i` (in id order), zero-copy.
    ///
    /// # Panics
    ///
    /// When `i >= len()`.
    pub fn row(&self, i: usize) -> &[u8] {
        let bpv = self.config.bytes_per_vector() as usize;
        let rows = self.rows();
        i.checked_mul(bpv)
            .and_then(|start| rows.get(start..start + bpv))
            .unwrap_or_else(|| panic!("row index {i} out of range for {} rows", self.len()))
    }

    /// The sorted ids, borrowed from the handle.
    pub fn ids(&self) -> Ids<'_> {
        let n = self.len();
        match self.id_kind {
            IdKind::U64 => {
                // SAFETY: the handle is live; the ids live as long as it.
                let ptr = unsafe { sys::semq_encoding_ids_u64(self.ptr.as_ptr()) };
                Ids::u64(unsafe { borrowed(ptr, n) })
            }
            IdKind::Utf8 => {
                let mut len = 0u64;
                // SAFETY: as above; `len` is a valid out-pointer.
                let (offsets, bytes) = unsafe {
                    (
                        sys::semq_encoding_ids_utf8_offsets(self.ptr.as_ptr()),
                        sys::semq_encoding_ids_utf8_bytes(self.ptr.as_ptr(), &mut len),
                    )
                };
                // SAFETY: `n + 1` offsets and `len` bytes, owned by the handle.
                Ids::packed(unsafe { borrowed(offsets, n + 1) }, unsafe {
                    borrowed(bytes, len as usize)
                })
            }
        }
    }

    /// The row of `id`, or `None` when absent. `InvalidInput` when the id's
    /// kind is not the Encoding's.
    pub fn get(&self, id: &Id) -> Result<Option<&[u8]>> {
        Ok(self.index_of(id)?.map(|i| self.row(i)))
    }

    fn index_of(&self, id: &Id) -> Result<Option<usize>> {
        let mut index = sys::SEMQ_NONE;
        let mut err = new_error();
        // SAFETY: the handle is live; the id bytes outlive the call.
        let status = match id {
            Id::U64(v) => unsafe {
                sys::semq_encoding_find_u64(self.ptr.as_ptr(), *v, &mut index, &mut err)
            },
            Id::Utf8(s) => unsafe {
                sys::semq_encoding_find_utf8(
                    self.ptr.as_ptr(),
                    ptr_or_null(s.as_bytes()),
                    s.len() as u64,
                    &mut index,
                    &mut err,
                )
            },
        };
        check(status, &err, "get")?;
        Ok((index != sys::SEMQ_NONE).then_some(index as usize))
    }

    /// The manifest.
    pub fn manifest(&self) -> Manifest {
        // SAFETY: the handle is live.
        let n = unsafe { sys::semq_encoding_manifest_len(self.ptr.as_ptr()) };
        let mut out = Manifest::new();
        for i in 0..n {
            let mut pair = sys::semq_pair_t {
                key: ptr::null(),
                key_len: 0,
                value: ptr::null(),
                value_len: 0,
            };
            let mut err = new_error();
            // SAFETY: `i < n`; the out-pointers are live.
            let status = unsafe {
                sys::semq_encoding_manifest_pair(self.ptr.as_ptr(), i, &mut pair, &mut err)
            };
            check(status, &err, "accessor")
                .expect("SEMQ core violated an infallible accessor contract");
            // SAFETY: the pair points into memory the handle owns.
            let (key, value) = unsafe {
                (
                    text(pair.key, pair.key_len as usize),
                    text(pair.value, pair.value_len as usize),
                )
            };
            out.insert(key, value);
        }
        out
    }

    /// SHA-256 over the config, ids and rows.
    pub fn content_digest(&self) -> [u8; 32] {
        let mut out = [0u8; 32];
        // SAFETY: the handle is live and `out` has room for 32 bytes.
        unsafe { sys::semq_encoding_content_digest(self.ptr.as_ptr(), out.as_mut_ptr()) };
        out
    }

    /// SHA-256 over the content digest and the manifest: the state's identity.
    pub fn state_id(&self) -> [u8; 32] {
        let mut out = [0u8; 32];
        // SAFETY: the handle is live and `out` has room for 32 bytes.
        unsafe { sys::semq_encoding_state_id(self.ptr.as_ptr(), out.as_mut_ptr()) };
        out
    }

    /// The `(id, row)` pairs in id order.
    pub fn iter(&self) -> impl Iterator<Item = (Id, &'_ [u8])> + '_ {
        let bpv = self.config.bytes_per_vector() as usize;
        self.ids().iter().zip(self.rows().chunks_exact(bpv))
    }

    // ---- verbs -----------------------------------------------------------

    /// Merge with Encodings of the same config and id kind (else `Incompatible`),
    /// the same manifest and pairwise-disjoint ids (else
    /// `InvalidInput`, `field` naming the part). Order-independent; the
    /// empty Encoding is neutral.
    pub fn concat(&self, others: &[&Encoding]) -> Result<Encoding> {
        let mut parts: Vec<*const sys::semq_encoding_t> = Vec::with_capacity(others.len() + 1);
        parts.push(self.as_ptr());
        parts.extend(others.iter().map(|e| e.as_ptr()));
        let k = u32::try_from(parts.len())
            .map_err(|_| Error::invalid("concat takes fewer than 2^32 parts"))?;
        let mut out: *mut sys::semq_encoding_t = ptr::null_mut();
        let mut err = new_error();
        // SAFETY: every part is a live handle; the array holds `k` pointers.
        let status = unsafe { sys::semq_encoding_concat(parts.as_ptr(), k, &mut out, &mut err) };
        check(status, &err, "concat")?;
        Self::from_raw(out, "concat")
    }

    /// `self` is the reference, `candidate` the state under review.
    /// `Incompatible` when config or id kind differ.
    pub fn diff(&self, candidate: &Encoding) -> Result<Diff> {
        let mut out: *mut sys::semq_diff_t = ptr::null_mut();
        let mut err = new_error();
        // SAFETY: both handles are live; the out-pointers are valid.
        let status = unsafe {
            sys::semq_encoding_diff(self.as_ptr(), candidate.as_ptr(), &mut out, &mut err)
        };
        check(status, &err, "diff")?;
        Diff::from_raw(out, "diff")
    }
}

/// Equality of `state_id`.
impl PartialEq for Encoding {
    fn eq(&self, other: &Encoding) -> bool {
        self.state_id() == other.state_id()
    }
}

impl Eq for Encoding {}

/// `Encoding(3 rows, quant(dim=4, bins=4), state_id 40c3aa20252d...)`, the
/// same text as the other bindings.
impl fmt::Display for Encoding {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let id = hex(&self.state_id());
        write!(
            f,
            "Encoding({} rows, {}, state_id {}...)",
            self.len(),
            self.config(),
            &id[..12]
        )
    }
}

impl fmt::Debug for Encoding {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("Encoding")
            .field("config", &self.config)
            .field("id_kind", &self.id_kind)
            .field("len", &self.len())
            .field("state_id", &hex(&self.state_id()))
            .finish()
    }
}
