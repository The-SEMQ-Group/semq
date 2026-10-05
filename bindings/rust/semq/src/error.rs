// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

//! The six error kinds of the SDK, and the status mapping from the core.

use std::fmt;
use std::io;

use semq_sys as sys;

use crate::build;

/// `Result` with this crate's [`Error`].
pub type Result<T> = std::result::Result<T, Error>;

/// Which integrity check failed on load: the check, not a cause.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Which {
    /// The content digest over config, ids and rows.
    Content,
    /// The state id over the content digest and the manifest.
    State,
}

impl Which {
    /// `"content"` or `"state"`.
    pub fn name(self) -> &'static str {
        match self {
            Which::Content => "content",
            Which::State => "state",
        }
    }

    fn from_raw(which: u32) -> Option<Which> {
        match which {
            sys::SEMQ_WHICH_CONTENT => Some(Which::Content),
            sys::SEMQ_WHICH_STATE => Some(Which::State),
            _ => None,
        }
    }
}

impl fmt::Display for Which {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.name())
    }
}

/// An error from the SDK. Each core status maps to exactly one variant.
///
/// Out-of-memory in the core (`SEMQ_ERR_NOMEM`) is reported as
/// [`Error::Native`] with `status = 6`; allocation failures on the Rust side
/// abort through `std::alloc` as anywhere else. I/O failures in
/// [`Encoding::read`](crate::Encoding::read) and
/// [`Encoding::write`](crate::Encoding::write) are `std::io::Error`.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum Error {
    /// An argument violates its contract: a non-finite or non-unit row, a
    /// width mismatch, a non-canonical row, a duplicate id, a config field
    /// out of range, an invalid manifest, an invalid floor or null diff.
    ///
    /// `row` is the input row at fault when one is; `field` is the
    /// coordinate, column, part or pair index, or the config field
    /// (0 operator, 1 dim, 2 parameter, 3 rule revision) when one applies.
    #[error("{message}")]
    InvalidInput {
        row: Option<u64>,
        field: Option<u64>,
        message: String,
    },
    /// Two states differ in config or id kind (`decode`, `unpack`, `diff`,
    /// `concat`).
    #[error("{message}")]
    Incompatible { field: Option<u64>, message: String },
    /// A file image is not a valid version 2 image. `section` names the
    /// section that failed (0 framing, 1 config, 2 sizes, 3 ids, 4 manifest,
    /// 5 footer, 6 rows); `row` is the row index when a row is not canonical.
    #[error("{message}")]
    FormatError {
        row: Option<u64>,
        section: Option<u64>,
        message: String,
    },
    /// A file image's digest does not match its footer.
    #[error("{message}")]
    IntegrityError {
        which: Option<Which>,
        message: String,
    },
    /// The operation, or the floating-point environment (rounding mode not
    /// round-to-nearest-even), is not supported.
    #[error("{message}")]
    Unsupported {
        operation: &'static str,
        message: String,
    },
    /// A defect in the core or the binding. Carries what a bug report needs
    /// and never input data.
    #[error(
        "{message} [operation={operation} status={status} sdk={sdk_version} \
         core={core_version} build={build_id}]"
    )]
    Native {
        operation: &'static str,
        status: u32,
        row: Option<u64>,
        field: Option<u64>,
        message: String,
        sdk_version: &'static str,
        core_version: &'static str,
        build_id: &'static str,
    },
}

impl Error {
    /// A representation error found by the binding, with no row or field.
    pub(crate) fn invalid(message: impl Into<String>) -> Error {
        Error::InvalidInput {
            row: None,
            field: None,
            message: message.into(),
        }
    }

    /// A representation error found by the binding, at a row or field.
    pub(crate) fn invalid_at(
        row: Option<u64>,
        field: Option<u64>,
        message: impl Into<String>,
    ) -> Error {
        Error::InvalidInput {
            row,
            field,
            message: message.into(),
        }
    }

    pub(crate) fn native(
        operation: &'static str,
        status: u32,
        row: Option<u64>,
        field: Option<u64>,
        message: impl Into<String>,
    ) -> Error {
        Error::Native {
            operation,
            status,
            row,
            field,
            message: message.into(),
            sdk_version: build::SDK_VERSION,
            core_version: build::core_version(),
            build_id: build::build_id(),
        }
    }
}

impl From<Error> for io::Error {
    fn from(err: Error) -> io::Error {
        let kind = match err {
            Error::InvalidInput { .. } | Error::Incompatible { .. } => io::ErrorKind::InvalidInput,
            Error::FormatError { .. } | Error::IntegrityError { .. } => io::ErrorKind::InvalidData,
            Error::Unsupported { .. } => io::ErrorKind::Unsupported,
            Error::Native { .. } => io::ErrorKind::Other,
        };
        io::Error::new(kind, err)
    }
}

/// A fresh error report to pass to the core.
pub(crate) fn new_error() -> sys::semq_error_t {
    sys::semq_error_t {
        status: sys::SEMQ_OK,
        which: sys::SEMQ_WHICH_NONE,
        row: sys::SEMQ_NONE,
        field: sys::SEMQ_NONE,
        message: [0; 128],
    }
}

/// Map a core status and its report to `Result`.
pub(crate) fn check(
    status: sys::semq_status_t,
    err: &sys::semq_error_t,
    operation: &'static str,
) -> Result<()> {
    if status == sys::SEMQ_OK {
        return Ok(());
    }
    let mut message = message_of(err);
    if message.is_empty() {
        message = build::status_name(status).to_owned();
    }
    let row = opt(err.row);
    let field = opt(err.field);
    Err(match status {
        sys::SEMQ_ERR_INVALID_INPUT => Error::InvalidInput {
            row,
            field,
            message,
        },
        sys::SEMQ_ERR_INCOMPATIBLE => Error::Incompatible { field, message },
        sys::SEMQ_ERR_FORMAT => Error::FormatError {
            row,
            section: field,
            message,
        },
        sys::SEMQ_ERR_INTEGRITY => Error::IntegrityError {
            which: Which::from_raw(err.which),
            message,
        },
        sys::SEMQ_ERR_UNSUPPORTED => Error::Unsupported { operation, message },
        _ => Error::native(operation, status, row, field, message),
    })
}

fn opt(value: u64) -> Option<u64> {
    (value != sys::SEMQ_NONE).then_some(value)
}

/// The NUL-terminated message of a report, lossily decoded.
fn message_of(err: &sys::semq_error_t) -> String {
    let bytes: Vec<u8> = err
        .message
        .iter()
        .take_while(|&&c| c != 0)
        // `c_char` is `i8` or `u8` depending on the target; the cast is a
        // no-op on the latter.
        .map(|&c| {
            #[allow(clippy::unnecessary_cast)]
            let byte = c as u8;
            byte
        })
        .collect();
    String::from_utf8_lossy(&bytes).into_owned()
}
