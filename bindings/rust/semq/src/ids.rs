// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

//! Identifiers: one owned id, and a borrowed sequence of ids of one kind.

use std::fmt;
use std::marker::PhantomData;
use std::ptr;

use semq_sys as sys;

/// The two id kinds. One per Encoding, never mixed.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum IdKind {
    /// Unsigned 64-bit integers, ordered numerically.
    U64 = 0,
    /// Non-empty UTF-8 strings of at most 4096 bytes, ordered bytewise.
    Utf8 = 1,
}

impl IdKind {
    /// `"u64"` or `"utf8"`.
    pub fn name(self) -> &'static str {
        match self {
            IdKind::U64 => "u64",
            IdKind::Utf8 => "utf8",
        }
    }

    pub(crate) fn as_raw(self) -> u32 {
        self as u32
    }

    pub(crate) fn from_raw(kind: u32) -> Option<IdKind> {
        match kind {
            sys::SEMQ_ID_U64 => Some(IdKind::U64),
            sys::SEMQ_ID_UTF8 => Some(IdKind::Utf8),
            _ => None,
        }
    }
}

impl fmt::Display for IdKind {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.name())
    }
}

/// One owned id of either kind.
#[derive(Debug, Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub enum Id {
    /// A `u64` id.
    U64(u64),
    /// A `utf8` id.
    Utf8(String),
}

impl Id {
    /// The kind of this id.
    pub fn kind(&self) -> IdKind {
        match self {
            Id::U64(_) => IdKind::U64,
            Id::Utf8(_) => IdKind::Utf8,
        }
    }
}

impl From<u64> for Id {
    fn from(id: u64) -> Id {
        Id::U64(id)
    }
}

impl From<String> for Id {
    fn from(id: String) -> Id {
        Id::Utf8(id)
    }
}

impl From<&str> for Id {
    fn from(id: &str) -> Id {
        Id::Utf8(id.to_owned())
    }
}

/// Decimal for `u64`, the text itself for `utf8`: the report rendering.
impl fmt::Display for Id {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Id::U64(v) => write!(f, "{v}"),
            Id::Utf8(s) => f.write_str(s),
        }
    }
}

/// A borrowed sequence of ids of one kind.
///
/// It is the input of [`Codec::encode`](crate::Codec::encode) and
/// [`Encoding::new`](crate::Encoding::new), built from `&[u64]`, `&[&str]`
/// or `&[String]` (also arrays and `Vec`s of those, via `From`), and the
/// view returned by [`Encoding::ids`](crate::Encoding::ids). The view of a
/// `u64` Encoding is zero-copy ([`as_u64`](Self::as_u64)); `utf8` ids are
/// materialized one at a time by [`get`](Self::get) and [`iter`](Self::iter).
/// A view feeds back as input unchanged.
#[derive(Clone, Copy)]
pub struct Ids<'a> {
    repr: Repr<'a>,
}

#[derive(Clone, Copy)]
enum Repr<'a> {
    U64(&'a [u64]),
    Str(&'a [&'a str]),
    String(&'a [String]),
    /// Sorted `utf8` ids owned by an Encoding: `n + 1` offsets and the bytes.
    Packed {
        offsets: &'a [u64],
        bytes: &'a [u8],
    },
}

impl<'a> Ids<'a> {
    /// `u64` ids.
    pub fn u64(ids: &'a [u64]) -> Ids<'a> {
        Ids {
            repr: Repr::U64(ids),
        }
    }

    /// `utf8` ids.
    pub fn utf8(ids: &'a [&'a str]) -> Ids<'a> {
        Ids {
            repr: Repr::Str(ids),
        }
    }

    pub(crate) fn packed(offsets: &'a [u64], bytes: &'a [u8]) -> Ids<'a> {
        assert!(
            !offsets.is_empty(),
            "SEMQ core omitted the UTF-8 end offset"
        );
        Ids {
            repr: Repr::Packed { offsets, bytes },
        }
    }

    /// The kind of every id in the sequence.
    pub fn kind(&self) -> IdKind {
        match self.repr {
            Repr::U64(_) => IdKind::U64,
            Repr::Str(_) | Repr::String(_) | Repr::Packed { .. } => IdKind::Utf8,
        }
    }

    /// Number of ids.
    pub fn len(&self) -> usize {
        match self.repr {
            Repr::U64(s) => s.len(),
            Repr::Str(s) => s.len(),
            Repr::String(s) => s.len(),
            Repr::Packed { offsets, .. } => offsets.len() - 1,
        }
    }

    /// `true` when there are no ids.
    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    /// The ids as a slice, for the `u64` kind.
    pub fn as_u64(&self) -> Option<&'a [u64]> {
        match self.repr {
            Repr::U64(s) => Some(s),
            _ => None,
        }
    }

    /// Id `i`, or `None` past the end.
    pub fn get(&self, i: usize) -> Option<Id> {
        match self.repr {
            Repr::U64(s) => s.get(i).map(|&v| Id::U64(v)),
            Repr::Str(s) => s.get(i).map(|&v| Id::Utf8(v.to_owned())),
            Repr::String(s) => s.get(i).map(|v| Id::Utf8(v.clone())),
            Repr::Packed { offsets, bytes } => {
                if i >= self.len() {
                    return None;
                }
                let start = usize::try_from(offsets[i]).expect("SEMQ core offset exceeds usize");
                let end = usize::try_from(offsets[i + 1]).expect("SEMQ core offset exceeds usize");
                let text = bytes
                    .get(start..end)
                    .expect("SEMQ core returned out-of-range UTF-8 offsets");
                Some(Id::Utf8(
                    std::str::from_utf8(text)
                        .expect("SEMQ core returned invalid UTF-8")
                        .to_owned(),
                ))
            }
        }
    }

    /// The ids in sequence order.
    pub fn iter(&self) -> impl Iterator<Item = Id> + 'a {
        let this = *self;
        (0..this.len()).map(move |i| {
            this.get(i)
                .expect("index is within the borrowed ID sequence")
        })
    }

    /// The C view of the sequence. `utf8` ids from `&str`/`String` slices
    /// are flattened into buffers the result owns.
    pub(crate) fn c_ids(&self) -> CIds<'a> {
        let mut raw = sys::semq_ids_t {
            kind: self.kind().as_raw(),
            n: self.len() as u64,
            u64: ptr::null(),
            utf8_offsets: ptr::null(),
            utf8_bytes: ptr::null(),
        };
        let mut offsets = Vec::new();
        let mut bytes = Vec::new();
        match self.repr {
            Repr::U64(s) => raw.u64 = ptr_or_null(s),
            Repr::Packed { offsets, bytes } => {
                raw.utf8_offsets = ptr_or_null(offsets);
                raw.utf8_bytes = ptr_or_null(bytes);
            }
            Repr::Str(s) => flatten(s.iter().map(|v| v.as_bytes()), &mut offsets, &mut bytes),
            Repr::String(s) => flatten(s.iter().map(|v| v.as_bytes()), &mut offsets, &mut bytes),
        }
        if !offsets.is_empty() {
            raw.utf8_offsets = offsets.as_ptr();
            raw.utf8_bytes = ptr_or_null(&bytes);
        }
        CIds {
            raw,
            _offsets: offsets,
            _bytes: bytes,
            _borrow: PhantomData,
        }
    }
}

impl fmt::Debug for Ids<'_> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_list().entries(self.iter()).finish()
    }
}

impl<'a> From<&'a [u64]> for Ids<'a> {
    fn from(ids: &'a [u64]) -> Ids<'a> {
        Ids::u64(ids)
    }
}

impl<'a> From<&'a [&'a str]> for Ids<'a> {
    fn from(ids: &'a [&'a str]) -> Ids<'a> {
        Ids::utf8(ids)
    }
}

impl<'a> From<&'a [String]> for Ids<'a> {
    fn from(ids: &'a [String]) -> Ids<'a> {
        Ids {
            repr: Repr::String(ids),
        }
    }
}

impl<'a, const N: usize> From<&'a [u64; N]> for Ids<'a> {
    fn from(ids: &'a [u64; N]) -> Ids<'a> {
        Ids::u64(ids)
    }
}

impl<'a, const N: usize> From<&'a [&'a str; N]> for Ids<'a> {
    fn from(ids: &'a [&'a str; N]) -> Ids<'a> {
        Ids::utf8(ids)
    }
}

impl<'a, const N: usize> From<&'a [String; N]> for Ids<'a> {
    fn from(ids: &'a [String; N]) -> Ids<'a> {
        Ids::from(&ids[..])
    }
}

impl<'a> From<&'a Vec<u64>> for Ids<'a> {
    fn from(ids: &'a Vec<u64>) -> Ids<'a> {
        Ids::u64(ids)
    }
}

impl<'a> From<&'a Vec<&'a str>> for Ids<'a> {
    fn from(ids: &'a Vec<&'a str>) -> Ids<'a> {
        Ids::utf8(ids)
    }
}

impl<'a> From<&'a Vec<String>> for Ids<'a> {
    fn from(ids: &'a Vec<String>) -> Ids<'a> {
        Ids::from(ids.as_slice())
    }
}

/// A `semq_ids_t` plus the buffers its pointers may refer to.
pub(crate) struct CIds<'a> {
    raw: sys::semq_ids_t,
    _offsets: Vec<u64>,
    _bytes: Vec<u8>,
    _borrow: PhantomData<&'a ()>,
}

impl CIds<'_> {
    pub(crate) fn as_raw(&self) -> *const sys::semq_ids_t {
        &self.raw
    }
}

fn flatten<'b>(items: impl Iterator<Item = &'b [u8]>, offsets: &mut Vec<u64>, bytes: &mut Vec<u8>) {
    offsets.push(0);
    for item in items {
        bytes.extend_from_slice(item);
        offsets.push(bytes.len() as u64);
    }
}

/// The slice's pointer, or NULL when it is empty (the core's convention).
pub(crate) fn ptr_or_null<T>(slice: &[T]) -> *const T {
    if slice.is_empty() {
        ptr::null()
    } else {
        slice.as_ptr()
    }
}

#[cfg(test)]
mod tests {
    use super::Ids;

    #[test]
    #[should_panic(expected = "out-of-range UTF-8 offsets")]
    fn corrupt_native_offsets_do_not_drop_an_id() {
        let ids = Ids::packed(&[0, 2], b"a");
        let _ = ids.iter().collect::<Vec<_>>();
    }

    #[test]
    fn packed_ids_preserve_out_of_bounds_lookup() {
        let ids = Ids::packed(&[0, 1], b"a");
        assert!(ids.get(1).is_none());
        assert!(ids.get(usize::MAX).is_none());
    }
}
