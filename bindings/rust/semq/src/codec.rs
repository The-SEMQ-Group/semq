// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

//! Codec: the machine that applies a CodecConfig.

use std::ffi::CStr;
use std::fmt;
use std::ptr::{self, NonNull};

use semq_sys as sys;

use crate::config::CodecConfig;
use crate::convert::{manifest_to_c, Manifest};
use crate::encoding::Encoding;
use crate::error::{check, new_error, Error, Result};
use crate::ids::{ptr_or_null, Ids};

/// An immutable encoder for one [`CodecConfig`], safe to share between
/// threads. Freed on drop.
pub struct Codec {
    ptr: NonNull<sys::semq_codec_t>,
    config: CodecConfig,
}

// SAFETY: a codec is immutable after construction and the core keeps no
// global or thread-local state, so sharing and moving it is sound.
unsafe impl Send for Codec {}
unsafe impl Sync for Codec {}

impl Drop for Codec {
    fn drop(&mut self) {
        // SAFETY: the handle came from `semq_codec_create` and is freed once.
        unsafe { sys::semq_codec_free(self.ptr.as_ptr()) }
    }
}

impl Codec {
    /// Build a codec for `config`.
    /// A codec for [`CodecConfig::quant`]: sign and magnitude bin per coordinate.
    pub fn quant(dim: u32, bins: u32) -> Result<Codec> {
        Codec::new(&CodecConfig::quant(dim, bins)?)
    }

    /// A codec for [`CodecConfig::phase`]: angular sector per coordinate pair.
    pub fn phase(dim: u32, sectors: u32) -> Result<Codec> {
        Codec::new(&CodecConfig::phase(dim, sectors)?)
    }

    /// A codec for [`CodecConfig::orbit`]: one discrete symbol per coordinate.
    pub fn orbit(dim: u32, scale: u32) -> Result<Codec> {
        Codec::new(&CodecConfig::orbit(dim, scale)?)
    }

    pub fn new(config: &CodecConfig) -> Result<Codec> {
        let mut out: *mut sys::semq_codec_t = ptr::null_mut();
        let mut err = new_error();
        // SAFETY: the config is valid and the out-pointers are live.
        let status = unsafe { sys::semq_codec_create(config.as_raw(), &mut out, &mut err) };
        check(status, &err, "codec")?;
        let ptr = NonNull::new(out).ok_or_else(|| {
            Error::native(
                "codec",
                sys::SEMQ_ERR_INTERNAL,
                None,
                None,
                "core returned a null codec",
            )
        })?;
        Ok(Codec {
            ptr,
            config: *config,
        })
    }

    /// The configuration this codec applies.
    pub fn config(&self) -> &CodecConfig {
        &self.config
    }

    /// The kernel the core runs for this operator on this host
    /// (`"scalar"`, `"neon"`, `"avx2"`, ...).
    pub fn backend(&self) -> &str {
        // SAFETY: the handle is live; the core returns a static string.
        let name = unsafe { sys::semq_codec_backend(self.ptr.as_ptr()) };
        if name.is_null() {
            return "";
        }
        // SAFETY: non-null and NUL-terminated, valid for the codec's life.
        unsafe { CStr::from_ptr(name) }.to_str().unwrap_or("")
    }

    /// Encode `vectors` under `ids`.
    ///
    /// `vectors` holds `n × dim` float32 values, row-major, one unit-norm row
    /// per id (`n = ids.len()`); any other length is `InvalidInput`. The
    /// core applies the input contract to every row (subnormal
    /// canonicalization, finiteness, the unit-norm check and the
    /// round-to-nearest requirement); row errors carry the input row index
    /// and the coordinate. The result holds sorted ids, canonical rows, the
    /// manifest and both digests.
    pub fn encode<'a>(
        &self,
        ids: impl Into<Ids<'a>>,
        vectors: &[f32],
        manifest: Option<&Manifest>,
    ) -> Result<Encoding> {
        let ids = ids.into();
        let dim = self.config.dim() as usize;
        let n = ids.len();
        if vectors.len() % dim != 0 {
            return Err(Error::invalid(format!(
                "vectors has {} values, not a multiple of dim {dim}",
                vectors.len()
            )));
        }
        let rows = vectors.len() / dim;
        if rows != n {
            return Err(Error::invalid(format!("{n} ids but {rows} vectors")));
        }
        let c_ids = ids.c_ids();
        let pairs = manifest_to_c(manifest)?;
        let mut out: *mut sys::semq_encoding_t = ptr::null_mut();
        let mut err = new_error();
        // SAFETY: `vectors` holds `n × dim` floats and the ids and manifest
        // views borrow data that outlives the call.
        let status = unsafe {
            sys::semq_codec_encode(
                self.ptr.as_ptr(),
                c_ids.as_raw(),
                ptr_or_null(vectors),
                pairs.as_ptr(),
                pairs.len(),
                &mut out,
                &mut err,
            )
        };
        check(status, &err, "encode")?;
        Encoding::from_raw(out, "encode")
    }

    /// Representatives, `n × dim` float32, row `i` for `encoding.ids()[i]`.
    /// Not normalized, and outside the byte-identity contract.
    /// `Incompatible` when the encoding's config differs.
    pub fn decode(&self, encoding: &Encoding) -> Result<Vec<f32>> {
        let mut out = vec![0f32; encoding.len() * self.config.dim() as usize];
        let mut err = new_error();
        // SAFETY: the core checks the config before writing `n × dim` floats.
        let status = unsafe {
            sys::semq_codec_decode(
                self.ptr.as_ptr(),
                encoding.as_ptr(),
                out.as_mut_ptr(),
                &mut err,
            )
        };
        check(status, &err, "decode")?;
        Ok(out)
    }

    /// Symbols, `n × units_per_row` bytes, one per unit.
    /// `Incompatible` when the encoding's config differs.
    pub fn unpack(&self, encoding: &Encoding) -> Result<Vec<u8>> {
        let mut out = vec![0u8; encoding.len() * self.config.units_per_row() as usize];
        let mut err = new_error();
        // SAFETY: the core checks the config before writing `n × units` bytes.
        let status = unsafe {
            sys::semq_codec_unpack(
                self.ptr.as_ptr(),
                encoding.as_ptr(),
                out.as_mut_ptr(),
                &mut err,
            )
        };
        check(status, &err, "unpack")?;
        Ok(out)
    }
}

impl fmt::Debug for Codec {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("Codec")
            .field("config", &self.config)
            .field("backend", &self.backend())
            .finish()
    }
}
