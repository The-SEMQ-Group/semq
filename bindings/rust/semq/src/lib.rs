// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

//! SEMQ: deterministic symbolic encoding of float32 vectors.
//!
//! Five values and one service, backed by a C core that owns every rule:
//!
//! * [`CodecConfig`]: the rule (`quant`, `phase` or `orbit`).
//! * [`Codec`]: encodes unit-norm float32 vectors into an [`Encoding`].
//! * [`Encoding`]: ids, canonical rows, a manifest and two identities;
//!   `write`/`read`, `concat` and `diff`.
//! * [`Diff`]: added, removed and changed ids with hamming distances.
//! * [`Floor`]: the envelope of variation observed in null diffs, bound to
//!   the config, id kind and reference it was measured against.
//! * [`BuildInfo`] from [`build_info`].
//!
//! Errors are the six variants of [`Error`]. Handles are freed on drop and
//! are `Send + Sync`; the views into an [`Encoding`] borrow it.
//!
//! # Quickstart
//!
//! ```no_run
//! use std::collections::BTreeMap;
//! use std::fs::File;
//!
//! use semq::{Codec, CodecConfig, Encoding, Floor};
//!
//! fn main() -> Result<(), Box<dyn std::error::Error>> {
//!     // The rule: quant, 4 dimensions, 4 magnitude bins per sign.
//!     let config = CodecConfig::quant(4, 4)?;
//!     let codec = Codec::new(&config)?;
//!
//!     // Unit-norm float32 rows, one per id, in any order.
//!     let ids = [3u64, 1, 2];
//!     let vectors = [
//!         0.5f32, 0.5, 0.5, 0.5, //
//!         -0.5, -0.5, -0.5, -0.5, //
//!         1.0, 0.0, 0.0, 0.0,
//!     ];
//!     let manifest = BTreeMap::from([("encoder".to_string(), "my-model@1".to_string())]);
//!     let reference = codec.encode(&ids, &vectors, Some(&manifest))?;
//!
//!     // Save, then load in another process: the identity is the same.
//!     reference.write(File::create("reference.semq")?)?;
//!     let loaded = Encoding::read(File::open("reference.semq")?)?;
//!     assert_eq!(loaded.state_id(), reference.state_id());
//!
//!     // Measure the floor from a null rebuild of the reference, then
//!     // compare a candidate against it.
//!     let null = loaded.diff(&codec.encode(&ids, &vectors, Some(&manifest))?)?;
//!     let floor = Floor::measure([&null])?;
//!     let candidate = codec.encode(&ids, &vectors, Some(&manifest))?;
//!     let diff = loaded.diff(&candidate)?;
//!     println!(
//!         "changed {} of {} shared rows; within floor: {}",
//!         diff.changed().len(),
//!         diff.n_unchanged() + diff.changed().len() as u64,
//!         diff.within(&floor)?
//!     );
//!     Ok(())
//! }
//! ```

#![deny(unsafe_op_in_unsafe_fn)]

mod build;
mod codec;
mod config;
mod convert;
mod diff;
mod encoding;
mod error;
mod floor;
mod gate;
mod ids;

pub use build::{build_info, BuildInfo};
pub use codec::Codec;
pub use config::{CodecConfig, Operator};
pub use convert::Manifest;
pub use diff::{Diff, DiffReport};
pub use encoding::Encoding;
pub use error::{Error, Result, Which};
pub use floor::{Floor, FloorReport};
pub use gate::{GateOptions, Reason, Verdict};
pub use ids::{Id, IdKind, Ids};
