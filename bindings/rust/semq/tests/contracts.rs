// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

//! The public API against the specification examples: the canonical config
//! form, the input contract, digests, the file image, concat, diff, floor
//! and build information. Expected values match the core's own unit tests.

use std::collections::{BTreeMap, HashSet};
use std::io::{Cursor, ErrorKind};

use semq::{
    build_info, Codec, CodecConfig, Diff, Encoding, Error, Floor, FloorReport, GateOptions, Id,
    IdKind, Ids, Manifest, Operator, Reason, Which,
};

// --------------------------------------------------------------------------
// Helpers
// --------------------------------------------------------------------------

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

fn unhex(s: &str) -> Vec<u8> {
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).unwrap())
        .collect()
}

fn quant44() -> CodecConfig {
    CodecConfig::quant(4, 4).unwrap()
}

fn manifest(pairs: &[(&str, &str)]) -> Manifest {
    pairs
        .iter()
        .map(|(k, v)| (k.to_string(), v.to_string()))
        .collect()
}

/// Pack quant symbols (one per unit, `bits` each, LSB-first) into one row.
fn pack_quant(symbols: &[u8], bits: u32, bpv: usize) -> Vec<u8> {
    let mut out = vec![0u8; bpv];
    let mut pos = 0usize;
    for &s in symbols {
        for b in 0..bits {
            if (s >> b) & 1 == 1 {
                out[pos >> 3] |= 1 << (pos & 7);
            }
            pos += 1;
        }
    }
    out
}

/// Two rows under quant(4, 4): ids 10 and 20.
fn sample_two_rows() -> Encoding {
    Encoding::new(&[10u64, 20], &[0x07, 0x07, 0x24, 0x01], &quant44(), None).unwrap()
}

/// quant(16, 4), `n` rows of symbol `base`; the first `n_changed` rows have
/// their first `flip` units at `base + 1`.
fn rows_with_changes(n: u64, n_changed: u64, flip: u32, base: u8) -> Encoding {
    let config = CodecConfig::quant(16, 4).unwrap();
    let bpv = config.bytes_per_vector() as usize;
    assert_eq!(bpv, 6);
    let ids: Vec<u64> = (0..n).collect();
    let mut rows = Vec::with_capacity(n as usize * bpv);
    for i in 0..n {
        let mut symbols = [base; 16];
        if i < n_changed {
            for s in symbols.iter_mut().take(flip as usize) {
                *s = base + 1;
            }
        }
        rows.extend(pack_quant(&symbols, 3, bpv));
    }
    Encoding::new(&ids, &rows, &config, None).unwrap()
}

// --------------------------------------------------------------------------
// CodecConfig
// --------------------------------------------------------------------------

#[test]
fn config_canonical_form_and_derived_quantities() {
    let c = quant44();
    assert_eq!(hex(&c.to_bytes()), "02040000000400000000000000");
    assert_eq!(CodecConfig::from_bytes(&c.to_bytes()).unwrap(), c);
    assert_eq!(c.operator(), Operator::Quant);
    assert_eq!(c.dim(), 4);
    assert_eq!(c.bins(), Some(4));
    assert_eq!(c.sectors(), None);
    assert_eq!(c.scale(), None);
    assert_eq!(c.parameter(), 4);
    assert_eq!(c.rule_revision(), 0);
    assert_eq!(c.bytes_per_vector(), 2);
    assert_eq!(c.units_per_row(), 4);
    assert_eq!(c.max_magnitude().map(f32::to_bits), Some(0x3f80_0000)); // 2/sqrt(4)

    let p = CodecConfig::phase(8, 16).unwrap();
    assert_eq!((p.bytes_per_vector(), p.units_per_row()), (2, 4));
    assert_eq!(p.sectors(), Some(16));
    assert_eq!(p.max_magnitude(), None);
    assert_eq!(CodecConfig::phase(8, 17).unwrap().bytes_per_vector(), 4);

    let o = CodecConfig::orbit(5, 50).unwrap();
    assert_eq!((o.bytes_per_vector(), o.units_per_row()), (5, 5));
    assert_eq!(o.scale(), Some(50));
    assert_eq!(o.bins(), None);
    assert_eq!(CodecConfig::orbit_default(5).unwrap(), o);
    assert_eq!(CodecConfig::DEFAULT_SCALE, 50);

    assert_eq!(
        CodecConfig::quant(1024, 64).unwrap().bytes_per_vector(),
        896
    );
    assert_eq!(CodecConfig::quant(3, 4).unwrap().bytes_per_vector(), 2);
}

#[test]
fn config_rejects_out_of_range_fields() {
    let field = |r: semq::Result<CodecConfig>| match r {
        Err(Error::InvalidInput { field, .. }) => field,
        other => panic!("expected InvalidInput, got {other:?}"),
    };
    assert_eq!(field(CodecConfig::quant(4, 1)), Some(2));
    assert_eq!(field(CodecConfig::quant(4, 65)), Some(2));
    assert_eq!(field(CodecConfig::quant(0, 4)), Some(1));
    assert_eq!(field(CodecConfig::quant(65537, 4)), Some(1));
    assert!(CodecConfig::phase(7, 16).is_err());
    assert!(CodecConfig::phase(6, 16).is_err());
    assert!(CodecConfig::phase(6, 17).is_ok());
    assert!(CodecConfig::phase(8, 1).is_err());
    assert!(CodecConfig::phase(8, 257).is_err());
    assert!(CodecConfig::orbit(8, 0).is_err());
    assert!(CodecConfig::orbit(8, (1 << 30) + 1).is_err());
    assert!(CodecConfig::orbit(8, 1 << 30).is_ok());

    let bad_op = [3, 4, 0, 0, 0, 4, 0, 0, 0, 0, 0, 0, 0];
    assert_eq!(field(CodecConfig::from_bytes(&bad_op)), Some(0));
    let bad_revision = [2, 4, 0, 0, 0, 4, 0, 0, 0, 1, 0, 0, 0];
    assert_eq!(field(CodecConfig::from_bytes(&bad_revision)), Some(3));
}

#[test]
fn config_equality_is_by_canonical_bytes() {
    let a = quant44();
    let b = CodecConfig::quant(4, 4).unwrap();
    let c = CodecConfig::quant(4, 3).unwrap();
    assert_eq!(a, b);
    assert_ne!(a, c);
    let set: HashSet<CodecConfig> = [a, b, c].into_iter().collect();
    assert_eq!(set.len(), 2);
    assert_eq!(
        format!("{a:?}"),
        "CodecConfig { operator: \"quant\", dim: 4, bins: 4, rule_revision: 0 }"
    );
}

// --------------------------------------------------------------------------
// Encoding: identities and the file image
// --------------------------------------------------------------------------

#[test]
fn empty_encoding_identities_and_image() {
    let e = Encoding::new(Ids::u64(&[]), &[], &quant44(), None).unwrap();
    assert!(e.is_empty());
    assert_eq!(e.id_kind(), IdKind::U64);
    assert_eq!(
        hex(&e.content_digest()),
        "4528e8a0422f5cde968847e021c85b4e6e78ce68da9e92b2981c62dd48f78f4a"
    );
    assert_eq!(
        hex(&e.state_id()),
        "ef4d1522eb158aa9b6b83cd5d51f80ea2cc59ac3aeb45b69a1c28c99375b55b9"
    );
    let image = e.to_bytes();
    assert_eq!(image.len(), 96);
    assert_eq!(
        image,
        unhex(
            "53454d51020002040000000400000000000000000000000000000000000000004528e8a0422f5cde968847e021c85b4e6e78ce68da9e92b2981c62dd48f78f4aef4d1522eb158aa9b6b83cd5d51f80ea2cc59ac3aeb45b69a1c28c99375b55b9"
        )
    );
    let back = Encoding::from_bytes(&image).unwrap();
    assert_eq!(back.len(), 0);
    assert_eq!(back.id_kind(), IdKind::U64);
    assert_eq!(back, e);
    assert!(e.ids().is_empty());
    assert_eq!(e.ids().as_u64(), Some(&[][..]));
    assert_eq!(e.rows(), &[]);
    assert_eq!(e.iter().count(), 0);

    let utf8 = Encoding::new(Ids::utf8(&[]), &[], &quant44(), None).unwrap();
    assert_eq!(utf8.id_kind(), IdKind::Utf8);
    assert_ne!(utf8.state_id(), e.state_id());
}

#[test]
fn one_row_identities_manifest_and_get() {
    let man = manifest(&[("encoder", "x")]);
    let e = Encoding::new(&[7u64], &[0x07, 0x07], &quant44(), Some(&man)).unwrap();
    assert_eq!(
        hex(&e.content_digest()),
        "1a3d8e8bfbf3429525d0bc11e18a17b75ea49af40b6b441f6863444f71230489"
    );
    assert_eq!(
        hex(&e.state_id()),
        "07d119f5a0a76de95bd4b41110d6005e6fc38cfc398421dd15df2be68adf9f85"
    );
    assert_eq!(e.manifest(), man);
    assert_eq!(e.len(), 1);
    assert_eq!(e.row(0), &[0x07, 0x07]);
    assert_eq!(e.get(&Id::U64(7)).unwrap(), Some(&[0x07u8, 0x07][..]));
    assert_eq!(e.get(&Id::U64(8)).unwrap(), None);
    assert!(matches!(
        e.get(&Id::from("7")),
        Err(Error::InvalidInput { .. })
    ));
    let items: Vec<(Id, &[u8])> = e.iter().collect();
    assert_eq!(items, vec![(Id::U64(7), &[0x07u8, 0x07][..])]);

    // The image round-trips through a stream and through bytes.
    let mut buf = Vec::new();
    e.write(&mut buf).unwrap();
    assert_eq!(buf, e.to_bytes());
    let back = Encoding::read(Cursor::new(&buf)).unwrap();
    assert_eq!(back.state_id(), e.state_id());
    assert_eq!(back.manifest(), man);
    assert_eq!(Encoding::from_bytes(&buf).unwrap(), e);
}

#[test]
fn constructor_rejects_non_canonical_rows_and_duplicates() {
    let c = quant44();
    // Bit 12 is padding.
    match Encoding::new(&[1u64], &[0x07, 0x17], &c, None) {
        Err(Error::InvalidInput {
            row: Some(0),
            field: None,
            ..
        }) => {}
        other => panic!("{other:?}"),
    }
    // High nibble 9 >= 8 sectors: field names the unit.
    let ph = CodecConfig::phase(4, 8).unwrap();
    match Encoding::new(&[1u64], &[0x90], &ph, None) {
        Err(Error::InvalidInput { field: Some(1), .. }) => {}
        other => panic!("{other:?}"),
    }
    // Duplicate ids report the later input row.
    match Encoding::new(&[5u64, 9, 5], &[0; 6], &c, None) {
        Err(Error::InvalidInput { row: Some(2), .. }) => {}
        other => panic!("{other:?}"),
    }
    // Row width is checked by the binding before the call.
    match Encoding::new(&[5u64, 9], &[0; 5], &c, None) {
        Err(Error::InvalidInput {
            row: None,
            field: None,
            ..
        }) => {}
        other => panic!("{other:?}"),
    }
}

// --------------------------------------------------------------------------
// Codec: encode / decode / unpack and the input contract
// --------------------------------------------------------------------------

const THREE_ROWS: [f32; 12] = [
    0.5, 0.5, 0.5, 0.5, // id 3: all symbols 6 (sign 1, bin 2)
    -0.5, -0.5, -0.5, -0.5, // id 1: all symbols 2 (sign 0, bin 2)
    1.0, 0.0, 0.0, 0.0, // id 2: [7, 4, 4, 4]
];

#[test]
fn encode_sorts_ids_and_maps_symbols() {
    let codec = Codec::new(&quant44()).unwrap();
    assert_eq!(codec.config(), &quant44());
    assert!(!codec.backend().is_empty());
    let ids = [3u64, 1, 2];
    let e = codec.encode(&ids, &THREE_ROWS, None).unwrap();
    assert_eq!(e.ids().as_u64(), Some(&[1u64, 2, 3][..]));
    assert_eq!(e.ids().kind(), IdKind::U64);
    assert_eq!(e.ids().len(), 3);
    assert_eq!(e.ids().get(1), Some(Id::U64(2)));
    assert_eq!(e.ids().get(3), None);
    assert_eq!(
        codec.unpack(&e).unwrap(),
        [2, 2, 2, 2, 7, 4, 4, 4, 6, 6, 6, 6]
    );
    let rep = codec.decode(&e).unwrap();
    assert_eq!(rep.len(), 12);
    assert_eq!(rep[0], -0.625); // -(2 + 0.5) * 1.0 / 4
    assert_eq!(rep[4], 0.875); // +(3 + 0.5) / 4
    assert_eq!(rep[5], 0.125); // +(0 + 0.5) / 4
    assert_eq!(rep[8], 0.625);
    // Same input, same bytes, same state.
    let e2 = codec.encode(&ids, &THREE_ROWS, None).unwrap();
    assert_eq!(e2.state_id(), e.state_id());
    assert_eq!(e2, e);
    // Iteration pairs sorted ids with their rows.
    let rows: Vec<(Id, &[u8])> = e.iter().collect();
    assert_eq!(rows.len(), 3);
    assert_eq!(rows[0].0, Id::U64(1));
    assert_eq!(rows[0].1, e.row(0));
    assert_eq!(rows[2].1, e.get(&Id::U64(3)).unwrap().unwrap());
    // The rows rebuild the same Encoding through the low-level constructor.
    let rebuilt = Encoding::new(e.ids(), e.rows(), &quant44(), None).unwrap();
    assert_eq!(rebuilt, e);
}

#[test]
fn encode_three_operators() {
    let v = [0.5f32, 0.5, -0.5, 0.5];
    let orbit = Codec::new(&CodecConfig::orbit(4, 50).unwrap()).unwrap();
    let phase = Codec::new(&CodecConfig::phase(4, 16).unwrap()).unwrap();
    let eo = orbit.encode(&[1u64], &v, None).unwrap();
    let ep = phase.encode(&[1u64], &v, None).unwrap();
    // orbit: 0.5 * 50 = 25 -> digital root 7 -> symbol 7; -0.5 -> 9 + 7 = 16.
    assert_eq!(orbit.unpack(&eo).unwrap(), [7, 7, 16, 7]);
    // phase: (0.5, 0.5) is 45 degrees, where sector 10 of 16 begins, and
    // (-0.5, 0.5) is 135 degrees, where sector 14 begins.
    assert_eq!(phase.unpack(&ep).unwrap(), [10, 14]);
    let rep = orbit.decode(&eo).unwrap();
    assert!((rep[0] - 0.14).abs() < 1e-6); // 7 / 50
    assert!((rep[2] + 0.14).abs() < 1e-6);
    // Cross-config use is Incompatible.
    assert!(matches!(orbit.decode(&ep), Err(Error::Incompatible { .. })));
    assert!(matches!(orbit.unpack(&ep), Err(Error::Incompatible { .. })));
}

#[test]
fn encode_rejects() {
    let codec = Codec::new(&quant44()).unwrap();
    let ids = [1u64, 2];
    let mut v = [1.0f32, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0];

    v[6] = f32::NAN;
    match codec.encode(&ids, &v, None) {
        Err(Error::InvalidInput {
            row: Some(1),
            field: Some(2),
            ..
        }) => {}
        other => panic!("{other:?}"),
    }
    v[6] = 0.0;

    v[0] = 0.9; // norm 0.81
    match codec.encode(&ids, &v, None) {
        Err(Error::InvalidInput { row: Some(0), .. }) => {}
        other => panic!("{other:?}"),
    }
    v[0] = 1.0;

    // Norm at the tolerance boundary: sum of squares 1 + 2^-10 is admitted.
    let mut edge = [1.0f32, 0.03125, 0.0, 0.0];
    assert!(codec.encode(&[1u64], &edge, None).is_ok());
    edge[1] = 0.0316; // just outside
    assert!(matches!(
        codec.encode(&[1u64], &edge, None),
        Err(Error::InvalidInput { .. })
    ));

    // Length mismatches are caught by the binding, with no row.
    match codec.encode(&ids, &v[..7], None) {
        Err(Error::InvalidInput {
            row: None,
            field: None,
            ..
        }) => {}
        other => panic!("{other:?}"),
    }
    match codec.encode(&[1u64], &v, None) {
        Err(Error::InvalidInput {
            row: None,
            field: None,
            ..
        }) => {}
        other => panic!("{other:?}"),
    }

    // Duplicate ids report the later input row.
    match codec.encode(&[4u64, 4], &v, None) {
        Err(Error::InvalidInput { row: Some(1), .. }) => {}
        other => panic!("{other:?}"),
    }

    // n = 0 is fine with an explicit kind (the kind is always explicit here).
    let empty = codec.encode(Ids::u64(&[]), &[], None).unwrap();
    assert!(empty.is_empty());

    // utf8 ids: an empty id is rejected with its row.
    match codec.encode(&["a", ""], &v, None) {
        Err(Error::InvalidInput { row: Some(1), .. }) => {}
        other => panic!("{other:?}"),
    }
}

#[test]
fn utf8_ids_sorted_bytewise() {
    let c = quant44();
    // "b", "a", "ab": bytewise order is a, ab, b.
    let e = Encoding::new(&["b", "a", "ab"], &[1, 0, 2, 0, 3, 0], &c, None).unwrap();
    assert_eq!(e.id_kind(), IdKind::Utf8);
    let ids: Vec<Id> = e.ids().iter().collect();
    assert_eq!(ids, vec![Id::from("a"), Id::from("ab"), Id::from("b")]);
    assert_eq!(e.ids().kind(), IdKind::Utf8);
    assert_eq!(e.ids().len(), 3);
    assert!(e.ids().as_u64().is_none());
    assert_eq!(e.rows(), &[2, 0, 3, 0, 1, 0]);
    assert_eq!(e.get(&Id::from("ab")).unwrap(), Some(&[3u8, 0][..]));
    assert_eq!(e.get(&Id::from("zz")).unwrap(), None);
    assert!(matches!(
        e.get(&Id::U64(1)),
        Err(Error::InvalidInput { .. })
    ));
    let items: Vec<(Id, &[u8])> = e.iter().collect();
    assert_eq!(items[1], (Id::from("ab"), &[3u8, 0][..]));

    // Owned strings are accepted too, with the same result.
    let owned: Vec<String> = ["b", "a", "ab"].iter().map(|s| s.to_string()).collect();
    let e2 = Encoding::new(&owned, &[1, 0, 2, 0, 3, 0], &c, None).unwrap();
    assert_eq!(e2, e);

    // The view feeds back as input, and the image round-trips.
    let e3 = Encoding::new(e.ids(), e.rows(), &c, None).unwrap();
    assert_eq!(e3, e);
    let back = Encoding::from_bytes(&e.to_bytes()).unwrap();
    assert_eq!(back, e);
    assert_eq!(back.ids().iter().collect::<Vec<_>>(), ids);
}

// --------------------------------------------------------------------------
// File reader
// --------------------------------------------------------------------------

#[test]
fn save_load_round_trip() {
    let e = sample_two_rows();
    let bytes = e.to_bytes();
    let mut streamed = Vec::new();
    e.write(&mut streamed).unwrap();
    assert_eq!(streamed, bytes);

    let a = Encoding::from_bytes(&bytes).unwrap();
    let b = Encoding::read(Cursor::new(&bytes)).unwrap();
    assert_eq!(a.state_id(), e.state_id());
    assert_eq!(b.state_id(), e.state_id());
    assert_eq!(a.rows(), e.rows());
    assert_eq!(a.ids().as_u64(), Some(&[10u64, 20][..]));
    assert_eq!(a.config(), e.config());
    assert_eq!(a.to_bytes(), bytes);
}

#[test]
fn load_detects_corruption() {
    let e = sample_two_rows();
    let img = e.to_bytes();
    assert_eq!(img.len(), 28 + 16 + 4 + 4 + 64);

    // A row byte: content digest fails.
    let mut c = img.clone();
    c[28 + 16] ^= 0x01;
    match Encoding::from_bytes(&c) {
        Err(Error::IntegrityError {
            which: Some(Which::Content),
            ..
        }) => {}
        other => panic!("{other:?}"),
    }

    // Truncation and trailing bytes.
    assert!(matches!(
        Encoding::from_bytes(&img[..img.len() - 1]),
        Err(Error::FormatError { .. })
    ));
    let mut trailing = img.clone();
    trailing.push(0);
    assert!(matches!(
        Encoding::from_bytes(&trailing),
        Err(Error::FormatError { .. })
    ));

    // Version 1: the framing section.
    let mut v1 = img.clone();
    v1[4] = 1;
    match Encoding::from_bytes(&v1) {
        Err(Error::FormatError {
            section: Some(0), ..
        }) => {}
        other => panic!("{other:?}"),
    }
    let mut magic = img.clone();
    magic[0] = b'X';
    assert!(matches!(
        Encoding::from_bytes(&magic),
        Err(Error::FormatError { .. })
    ));

    // n = 2^40: rejected by the size checks before any allocation.
    let mut huge = img.clone();
    huge[25] = 0x01;
    match Encoding::from_bytes(&huge) {
        Err(Error::FormatError {
            section: Some(2), ..
        }) => {}
        other => panic!("{other:?}"),
    }

    // A manifest byte with only the state id stale: which = state.
    let with_man = Encoding::new(
        &[10u64, 20],
        &[0x07, 0x07, 0x24, 0x01],
        &quant44(),
        Some(&manifest(&[("k", "v")])),
    )
    .unwrap();
    let mut mi = with_man.to_bytes();
    let n = mi.len();
    mi[n - 64 - 1] = b'w';
    match Encoding::from_bytes(&mi) {
        Err(Error::IntegrityError {
            which: Some(Which::State),
            ..
        }) => {}
        other => panic!("{other:?}"),
    }

    // `read` reports the same failure as an io::Error carrying the Error.
    let err = Encoding::read(Cursor::new(&c)).unwrap_err();
    assert_eq!(err.kind(), ErrorKind::InvalidData);
    assert!(matches!(
        err.get_ref().and_then(|e| e.downcast_ref::<Error>()),
        Some(Error::IntegrityError { .. })
    ));
}

// --------------------------------------------------------------------------
// concat
// --------------------------------------------------------------------------

#[test]
fn concat_is_order_independent() {
    let c = quant44();
    let all_ids = [1u64, 2, 3];
    let all_rows = [0x07u8, 0x07, 0x24, 0x01, 0x11, 0x02];
    let whole = Encoding::new(&all_ids, &all_rows, &c, None).unwrap();
    let parts: Vec<Encoding> = (0..3)
        .map(|i| Encoding::new(&all_ids[i..i + 1], &all_rows[2 * i..2 * i + 2], &c, None).unwrap())
        .collect();
    let want = whole.state_id();
    let ca = parts[0].concat(&[&parts[1], &parts[2]]).unwrap();
    let cb = parts[2].concat(&[&parts[0], &parts[1]]).unwrap();
    assert_eq!(ca.state_id(), want);
    assert_eq!(cb.state_id(), want);
    assert_eq!(ca.ids().as_u64(), Some(&[1u64, 2, 3][..]));

    // Empty is neutral.
    let empty = Encoding::new(Ids::u64(&[]), &[], &c, None).unwrap();
    assert_eq!(whole.concat(&[&empty]).unwrap().state_id(), want);
    assert_eq!(empty.concat(&[&whole]).unwrap().state_id(), want);
    assert_eq!(whole.concat(&[]).unwrap().state_id(), want);

    // Overlap: the repeated id names the part.
    match whole.concat(&[&parts[1]]) {
        Err(Error::InvalidInput { field: Some(1), .. }) => {}
        other => panic!("{other:?}"),
    }
    // Different manifest.
    let m = Encoding::new(
        &all_ids[2..],
        &all_rows[4..],
        &c,
        Some(&manifest(&[("encoder", "x")])),
    )
    .unwrap();
    assert!(matches!(
        parts[0].concat(&[&m]),
        Err(Error::InvalidInput { .. })
    ));
    // Different config (symbols 4, 4, 4, 0 fit under 3 bins too).
    let c2 = CodecConfig::quant(4, 3).unwrap();
    let other = Encoding::new(&all_ids[2..], &all_rows[2..4], &c2, None).unwrap();
    assert!(matches!(
        parts[0].concat(&[&other]),
        Err(Error::Incompatible { .. })
    ));
    // Different kind.
    let utf8 = Encoding::new(&["a"], &all_rows[..2], &c, None).unwrap();
    assert!(matches!(
        parts[0].concat(&[&utf8]),
        Err(Error::Incompatible { .. })
    ));
}

// --------------------------------------------------------------------------
// diff, within, measure
// --------------------------------------------------------------------------

fn reference_and_candidate() -> (Encoding, Encoding) {
    let c = quant44();
    let reference = Encoding::new(
        &[1u64, 2, 3],
        &[0x07, 0x07, 0x24, 0x01, 0x11, 0x02],
        &c,
        Some(&manifest(&[("encoder", "m1"), ("note", "a")])),
    )
    .unwrap();
    // id 3: unit 3 symbol 1 -> 3.
    let candidate = Encoding::new(
        &[2u64, 3, 4],
        &[0x24, 0x01, 0x11, 0x06, 0x00, 0x00],
        &c,
        Some(&manifest(&[("encoder", "m1"), ("run", "7")])),
    )
    .unwrap();
    (reference, candidate)
}

#[test]
fn diff_lists_units_and_manifest() {
    let (reference, candidate) = reference_and_candidate();
    let d = reference.diff(&candidate).unwrap();
    assert_eq!(d.reference_id(), reference.state_id());
    assert_eq!(d.candidate_id(), candidate.state_id());
    assert_eq!(d.config(), &quant44());
    assert_eq!(d.id_kind(), IdKind::U64);
    assert_eq!(d.added(), vec![Id::U64(4)]);
    assert_eq!(d.removed(), vec![Id::U64(1)]);
    assert_eq!(d.changed(), vec![(Id::U64(3), 1)]);
    assert_eq!(d.n_unchanged(), 1);
    assert_eq!(d.units(&Id::U64(3)).unwrap(), vec![(3, 1, 3)]);
    assert_eq!(d.units(&Id::U64(2)).unwrap(), vec![]);
    assert!(matches!(
        d.units(&Id::U64(1)),
        Err(Error::InvalidInput { .. })
    ));
    assert!(matches!(
        d.units(&Id::from("3")),
        Err(Error::InvalidInput { .. })
    ));
    let mut expected = BTreeMap::new();
    expected.insert("note".to_string(), (Some("a".to_string()), None));
    expected.insert("run".to_string(), (None, Some("7".to_string())));
    assert_eq!(d.manifest_changes(), expected);
    assert_eq!(
        format!("{d:?}"),
        "Diff { added: 1, removed: 1, changed: 1, n_unchanged: 1 }"
    );

    // The diff outlives the encodings it was built from.
    drop(reference);
    drop(candidate);
    assert_eq!(d.units(&Id::U64(3)).unwrap(), vec![(3, 1, 3)]);
    assert_eq!(d.changed(), vec![(Id::U64(3), 1)]);

    // removed is non-empty, so no floor admits this diff.
    assert!(!d.within(&floor_for(&d, 1, 4, 4, 4)).unwrap());

    // The report is the schema as plain data.
    let r = d.as_report();
    assert_eq!(r.reference_id, hex(&d.reference_id()));
    assert_eq!(r.candidate_id.len(), 64);
    assert_eq!(r.id_kind, "u64");
    assert_eq!(r.config, quant44());
    assert_eq!(r.added, vec!["4".to_string()]);
    assert_eq!(r.removed, vec!["1".to_string()]);
    assert_eq!(r.changed, vec![("3".to_string(), 1)]);
    assert_eq!(r.n_unchanged, 1);
    assert_eq!(r.manifest_changes, expected);

    // Short circuit: identical states.
    let (same, _) = reference_and_candidate();
    let (same2, _) = reference_and_candidate();
    let d = same.diff(&same2).unwrap();
    assert_eq!(d.n_unchanged(), 3);
    assert!(d.changed().is_empty());
    assert!(d.added().is_empty() && d.removed().is_empty());
    assert!(d.manifest_changes().is_empty());
    assert!(d.within(&floor_for(&d, 1, 0, 1, 0)).unwrap());

    // Different kinds are incompatible.
    let other = Encoding::new(&["a"], &[0x07, 0x07], &quant44(), None).unwrap();
    assert!(matches!(same.diff(&other), Err(Error::Incompatible { .. })));
}

#[test]
fn diff_over_utf8_ids() {
    let c = quant44();
    let a = Encoding::new(&["x", "y"], &[0x07, 0x07, 0x24, 0x01], &c, None).unwrap();
    let b = Encoding::new(&["y", "z"], &[0x24, 0x00, 0x11, 0x02], &c, None).unwrap();
    let d = a.diff(&b).unwrap();
    assert_eq!(d.id_kind(), IdKind::Utf8);
    assert_eq!(d.added(), vec![Id::from("z")]);
    assert_eq!(d.removed(), vec![Id::from("x")]);
    assert_eq!(d.changed(), vec![(Id::from("y"), 1)]);
    // "y": [4, 4, 4, 0] -> [4, 4, 0, 0]; unit 2 goes 4 -> 0.
    assert_eq!(d.units(&Id::from("y")).unwrap(), vec![(2, 4, 0)]);
    assert!(matches!(
        d.units(&Id::U64(1)),
        Err(Error::InvalidInput { .. })
    ));
    assert_eq!(d.as_report().changed, vec![("y".to_string(), 1)]);
}

/// A valid floor bound to `d`'s config, id kind and reference.
/// `floor`, which records no `max_hamming`, read back from JSON with one.
fn with_max(floor: &Floor, max_hamming: u64) -> Option<Floor> {
    let json = floor.to_json();
    Floor::from_json(format!(
        "{},\"max_hamming\":{max_hamming}}}",
        &json[..json.len() - 1]
    ))
    .ok()
}

fn floor_for(d: &Diff, nulls: u64, changed: u64, total: u64, hamming: u64) -> Floor {
    Floor::new(
        d.config(),
        d.id_kind(),
        d.reference_id(),
        nulls,
        changed,
        total,
        hamming,
    )
    .unwrap()
}

#[test]
fn floor_measure_and_within() {
    // Null A: 100 rows, 1 changed by 1 unit. Null B: 1 row changed by 10
    // units, taken against another reference.
    let a0 = rows_with_changes(100, 0, 0, 4);
    let a1 = rows_with_changes(100, 1, 1, 4);
    let b0 = rows_with_changes(1, 0, 0, 4);
    let b1 = rows_with_changes(1, 1, 10, 4);
    let da = a0.diff(&a1).unwrap();
    let db = b0.diff(&b1).unwrap();
    assert_eq!(da.changed().len(), 1);
    assert_eq!(da.n_unchanged(), 99);

    // A alone: the floor records its context and (1, 100, 1).
    let f = Floor::measure([&da]).unwrap();
    assert_eq!(f.config(), &CodecConfig::quant(16, 4).unwrap());
    assert_eq!(f.id_kind(), IdKind::U64);
    assert_eq!(f.reference_id(), a0.state_id());
    assert_eq!(
        (f.nulls(), f.changed_rows(), f.total_rows(), f.hamming()),
        (1, 1, 100, 1)
    );
    assert_eq!((f.max_hamming(), f.distinct_nulls()), (None, None));
    assert_eq!(f, floor_for(&da, 1, 1, 100, 1));
    assert_ne!(f, floor_for(&da, 2, 1, 100, 1));
    assert!(da.within(&f).unwrap());
    // With the per-row check the floor also records its per-row data.
    let per_row = Floor::measure_for([&da], &GateOptions::new().per_row(true)).unwrap();
    assert_eq!(
        (per_row.max_hamming(), per_row.distinct_nulls()),
        (Some(1), Some(1))
    );
    assert_ne!(per_row, f);
    assert_eq!(Floor::measure_for([&da], &GateOptions::new()).unwrap(), f);

    // Two nulls of the same reference: the envelope of both.
    let a2 = rows_with_changes(100, 2, 1, 4);
    let d2 = a0.diff(&a2).unwrap();
    let both = Floor::measure([&da, &d2]).unwrap();
    assert_eq!(
        (
            both.nulls(),
            both.changed_rows(),
            both.total_rows(),
            both.hamming()
        ),
        (2, 2, 100, 1)
    );
    assert!(da.within(&both).unwrap());
    assert!(d2.within(&both).unwrap());

    // Exact boundary: 2 of 100 against 1/100 fails; against 2/100 passes.
    assert!(!d2.within(&f).unwrap());
    assert!(d2.within(&floor_for(&d2, 1, 2, 100, 1)).unwrap());

    // B was taken against another reference: it is neither measured with A
    // (`field` names the offending null) nor judged by A's floor.
    match Floor::measure([&da, &db]) {
        Err(Error::Incompatible { field: Some(1), .. }) => {}
        other => panic!("{other:?}"),
    }
    match db.within(&f) {
        Err(Error::Incompatible { field: None, .. }) => {}
        other => panic!("{other:?}"),
    }

    // Same reference, other config or id kind: Incompatible.
    let other_config = Floor::new(
        &CodecConfig::orbit(16, 50).unwrap(),
        IdKind::U64,
        da.reference_id(),
        1,
        1,
        100,
        1,
    )
    .unwrap();
    assert!(matches!(
        da.within(&other_config),
        Err(Error::Incompatible { .. })
    ));
    let other_kind =
        Floor::new(da.config(), IdKind::Utf8, da.reference_id(), 1, 1, 100, 1).unwrap();
    assert!(matches!(
        da.within(&other_kind),
        Err(Error::Incompatible { .. })
    ));

    // n_common = 0 never passes; an empty candidate is not a rebuild.
    let empty = Encoding::new(
        Ids::u64(&[]),
        &[],
        &CodecConfig::quant(16, 4).unwrap(),
        None,
    )
    .unwrap();
    let de = empty.diff(&empty).unwrap();
    assert!(!de.within(&floor_for(&de, 1, 2, 100, 1)).unwrap());
    assert!(matches!(
        Floor::measure([&de]),
        Err(Error::InvalidInput { .. })
    ));

    // No nulls, or a diff that adds and removes rows.
    assert!(matches!(
        Floor::measure::<&Diff>([]),
        Err(Error::InvalidInput { .. })
    ));
    let (reference, candidate) = reference_and_candidate();
    let not_null = reference.diff(&candidate).unwrap();
    match Floor::measure([&not_null]) {
        Err(Error::InvalidInput { field: Some(0), .. }) => {}
        other => panic!("{other:?}"),
    }
}

#[test]
fn floor_rejects_invalid_fields_at_construction() {
    let c = CodecConfig::quant(16, 4).unwrap();
    let rid = [7u8; 32];
    let invalid = |r: semq::Result<Floor>| {
        assert!(matches!(r, Err(Error::InvalidInput { .. })), "{r:?}");
    };
    invalid(Floor::new(&c, IdKind::U64, rid, 1, 5, 4, 1)); // changed > total
    invalid(Floor::new(&c, IdKind::U64, rid, 1, 0, 0, 1)); // total 0
    invalid(Floor::new(&c, IdKind::U64, rid, 0, 1, 1, 1)); // nulls 0
    invalid(Floor::new(&c, IdKind::U64, rid, 1, 1, 1, 17)); // hamming > units
    let f = Floor::new(&c, IdKind::Utf8, rid, 1, 1, 1, 16).unwrap();
    assert_eq!(f.id_kind(), IdKind::Utf8);
    assert_eq!(f.reference_id(), rid);
    assert_eq!(f.config(), &c);
    assert_eq!(
        (f.nulls(), f.changed_rows(), f.total_rows(), f.hamming()),
        (1, 1, 1, 16)
    );
}

#[test]
fn floor_never_admits_an_encoder_change() {
    let c = quant44();
    let rows = [0x07u8, 0x07, 0x24, 0x01];
    let encode = |pairs: &[(&str, &str)]| {
        Encoding::new(&[1u64, 2], &rows, &c, Some(&manifest(pairs))).unwrap()
    };
    let reference = encode(&[("encoder", "m1")]);

    // A null may change other keys; a floor measured from it admits it.
    let null = reference
        .diff(&encode(&[("encoder", "m1"), ("run", "2")]))
        .unwrap();
    let f = Floor::measure([&null]).unwrap();
    assert!(null.within(&f).unwrap());

    // The same rows under another encoder are never within, and never a
    // null; the same for a new `encoder_revision`.
    let swapped = reference.diff(&encode(&[("encoder", "m2")])).unwrap();
    assert!(swapped.changed().is_empty());
    assert!(!swapped.within(&f).unwrap());
    assert!(!swapped.within(&floor_for(&swapped, 1, 2, 2, 4)).unwrap());
    match Floor::measure([&swapped]) {
        Err(Error::InvalidInput { field: Some(0), .. }) => {}
        other => panic!("{other:?}"),
    }
    let revised = reference
        .diff(&encode(&[("encoder", "m1"), ("encoder_revision", "2")]))
        .unwrap();
    assert!(!revised.within(&f).unwrap());
    match Floor::measure([&null, &revised]) {
        Err(Error::InvalidInput { field: Some(1), .. }) => {}
        other => panic!("{other:?}"),
    }
}

#[test]
fn evaluate_names_every_failed_check_and_the_rows_above_max() {
    // 200 rows; the null changes rows 0..99 by 2 units. The candidate changes
    // rows 0..98 by 2 and row 150 by 10: its p99 ignores row 150, so it is
    // within the floor, and only the per-row check catches it.
    let base = rows_with_changes(200, 0, 0, 4);
    let null = base.diff(&rows_with_changes(200, 100, 2, 4)).unwrap();
    let floor = Floor::measure_for([&null], &GateOptions::new().per_row(true)).unwrap();
    assert_eq!((floor.hamming(), floor.max_hamming()), (2, Some(2)));
    assert_eq!(floor.distinct_nulls(), Some(1));
    let config = CodecConfig::quant(16, 4).unwrap();
    let bpv = config.bytes_per_vector() as usize;
    let ids: Vec<u64> = (0..200).collect();
    let mut rows = Vec::with_capacity(200 * bpv);
    for i in 0..200u64 {
        let flip = if i < 99 {
            2
        } else if i == 150 {
            10
        } else {
            0
        };
        let mut symbols = [4u8; 16];
        symbols.iter_mut().take(flip).for_each(|s| *s = 5);
        rows.extend(pack_quant(&symbols, 3, bpv));
    }
    let hidden = base
        .diff(&Encoding::new(&ids, &rows, &config, None).unwrap())
        .unwrap();
    assert!(hidden.within(&floor).unwrap());
    let plain = hidden.evaluate(&floor, &GateOptions::new()).unwrap();
    assert!(plain.passed() && plain.reasons().is_empty() && plain.rows().is_empty());
    let strict = hidden
        .evaluate(&floor, &GateOptions::new().per_row(true))
        .unwrap();
    assert!(!strict.passed());
    assert_eq!(strict.reasons(), &[Reason::RowAboveMax]);
    assert_eq!(strict.rows(), &[Id::U64(150)]);
    // Every failed check is named, not only the first.
    let tight = with_max(&floor_for(&hidden, 1, 1, 200, 1), 1).unwrap();
    let all = hidden
        .evaluate(&tight, &GateOptions::new().per_row(true))
        .unwrap();
    assert_eq!(
        all.reasons(),
        &[Reason::ChangedRatio, Reason::Hamming, Reason::RowAboveMax]
    );
    assert_eq!(
        all.reasons().iter().map(|r| r.name()).collect::<Vec<_>>(),
        ["changed_ratio", "hamming", "row_above_max"]
    );
    assert_eq!(all.rows().len(), 100);
    // A floor without per-row data refuses the per-row check and keeps its plain verdict.
    let v1 = Floor::measure([&null]).unwrap();
    assert!(hidden.evaluate(&v1, &GateOptions::new()).unwrap().passed());
    match hidden.evaluate(&v1, &GateOptions::new().per_row(true)) {
        Err(Error::Incompatible { message, .. }) => {
            assert!(message.contains("per-row"), "{message}")
        }
        other => panic!("expected Incompatible, got {other:?}"),
    }
}

#[test]
fn floor_report_and_its_strict_inverse() {
    let a0 = rows_with_changes(100, 0, 0, 4);
    let a1 = rows_with_changes(100, 1, 1, 4);
    let da = a0.diff(&a1).unwrap();
    let f = Floor::measure_for([&da], &GateOptions::new().per_row(true)).unwrap();

    let r = f.as_report();
    assert_eq!(
        r,
        FloorReport {
            version: "semq-floor/1".to_string(),
            config: CodecConfig::quant(16, 4).unwrap(),
            id_kind: "u64".to_string(),
            reference_id: hex(&a0.state_id()),
            nulls: 1,
            changed_rows: 1,
            total_rows: 100,
            hamming: 1,
        }
    );
    assert_eq!(r.version, FloorReport::VERSION);
    assert_eq!(
        format!("{f:?}"),
        format!(
            "Floor {{ config: {:?}, id_kind: \"u64\", reference_id: {:?}, nulls: 1, \
             changed_rows: 1, total_rows: 100, hamming: 1, max_hamming: Some(1), \
             distinct_nulls: Some(1) }}",
            r.config, r.reference_id
        )
    );

    // The report does not carry the per-row data, so from_report gives a
    // floor without it, the one measure gives; the JSON form, written and
    // read by the core, gives back the same floor.
    let back = Floor::from_report(&r).unwrap();
    assert_eq!(back, Floor::measure([&da]).unwrap());
    assert_eq!((back.max_hamming(), back.distinct_nulls()), (None, None));
    assert_eq!(back.as_report(), r);
    assert!(da.within(&back).unwrap());
    let json = f.to_json();
    assert_eq!(
        json,
        format!(
            "{{\"version\":\"semq-floor/1\",\"config\":{{\"operator\":\"quant\",\"dim\":16,\"bins\":4,\
             \"rule_revision\":0}},\"id_kind\":\"u64\",\"reference_id\":\"{}\",\"nulls\":1,\
             \"changed_rows\":1,\"total_rows\":100,\"hamming\":1,\"max_hamming\":1,\"distinct_nulls\":1}}",
            r.reference_id
        )
    );
    let from_json = Floor::from_json(&json).unwrap();
    assert_eq!(from_json, f);
    assert_eq!(from_json.to_json(), json);
    assert_eq!(
        Floor::from_json(back.to_json()).unwrap().max_hamming(),
        None
    );
    assert_eq!(
        Floor::from_json(json.replace('{', "{\"note\":[1,{}],")).unwrap(),
        f
    );
    for bad in [
        json.replace("\"max_hamming\":1", "\"max_hamming\":0"),
        json.replace("\"max_hamming\":1", "\"max_hamming\":17"),
        json.replace("\"distinct_nulls\":1", "\"distinct_nulls\":2"),
        json.replace("\"nulls\":1", "\"nulls\":1.0"),
        json.replace("semq-floor/1", "semq-floor/2"),
        json.replace("\"hamming\":1,", ""),
        format!("{json} x"),
        String::from("{}"),
    ] {
        assert!(
            matches!(Floor::from_json(&bad), Err(Error::InvalidInput { .. })),
            "{bad}"
        );
    }
    let set: HashSet<Floor> = [f, from_json, back].into_iter().collect();
    assert_eq!(set.len(), 2);

    // Strict: version, id kind, reference id and every count.
    let invalid = |bad: FloorReport| {
        assert!(
            matches!(Floor::from_report(&bad), Err(Error::InvalidInput { .. })),
            "{bad:?}"
        );
    };
    invalid(FloorReport {
        version: "semq-floor/2".to_string(),
        ..r.clone()
    });
    invalid(FloorReport {
        id_kind: "unknown".to_string(),
        ..r.clone()
    });
    invalid(FloorReport {
        reference_id: r.reference_id[..63].to_string(),
        ..r.clone()
    });
    invalid(FloorReport {
        reference_id: format!("{}0", r.reference_id),
        ..r.clone()
    });
    invalid(FloorReport {
        reference_id: format!("0x{}", &r.reference_id[2..]),
        ..r.clone()
    });
    invalid(FloorReport {
        reference_id: format!("+{}", &r.reference_id[1..]),
        ..r.clone()
    });
    invalid(FloorReport {
        nulls: 0,
        ..r.clone()
    });
    invalid(FloorReport {
        changed_rows: 101,
        ..r.clone()
    });
    invalid(FloorReport {
        total_rows: 0,
        ..r.clone()
    });
    invalid(FloorReport {
        hamming: 17,
        ..r.clone()
    });

    // Another kind survives the inverse but no longer matches the diff;
    // hex digits count whatever their case.
    let utf8 = Floor::from_report(&FloorReport {
        id_kind: "utf8".to_string(),
        ..r.clone()
    })
    .unwrap();
    assert_eq!(utf8.id_kind(), IdKind::Utf8);
    assert!(matches!(da.within(&utf8), Err(Error::Incompatible { .. })));
    let upper = Floor::from_report(&FloorReport {
        reference_id: r.reference_id.to_uppercase(),
        ..r.clone()
    })
    .unwrap();
    assert_eq!(upper.reference_id(), a0.state_id());
    assert_eq!(upper.as_report(), r);
}

#[test]
fn p99_is_nearest_rank() {
    // 101 changed rows with hammings 1..101: k = 101 - 1 = 100 -> value 100.
    let c = CodecConfig::quant(128, 4).unwrap();
    let bpv = c.bytes_per_vector() as usize;
    assert_eq!(bpv, 48);
    let n = 101u64;
    let ids: Vec<u64> = (0..n).collect();
    let mut base = Vec::new();
    let mut cand = Vec::new();
    for i in 0..n as usize {
        let mut symbols = [4u8; 128];
        base.extend(pack_quant(&symbols, 3, bpv));
        for s in symbols.iter_mut().take(i + 1) {
            *s = 5;
        }
        cand.extend(pack_quant(&symbols, 3, bpv));
    }
    let a = Encoding::new(&ids, &base, &c, None).unwrap();
    let b = Encoding::new(&ids, &cand, &c, None).unwrap();
    let d = a.diff(&b).unwrap();
    let f = Floor::measure([&d]).unwrap();
    assert_eq!(
        (f.nulls(), f.changed_rows(), f.total_rows(), f.hamming()),
        (1, 101, 101, 100)
    );
}

// --------------------------------------------------------------------------
// Build info, threading and error rendering
// --------------------------------------------------------------------------

#[test]
fn build_info_is_non_empty() {
    let info = build_info();
    assert_eq!(info.sdk_version, env!("CARGO_PKG_VERSION"));
    assert!(!info.core_version.is_empty());
    assert!(!info.build_id.is_empty());
    assert_eq!(info.backend.len(), 3);
    for op in [Operator::Orbit, Operator::Phase, Operator::Quant] {
        assert!(!info.backend[&op].is_empty(), "{op}");
    }
    let codec = Codec::new(&quant44()).unwrap();
    assert_eq!(codec.backend(), info.backend[&Operator::Quant]);
}

#[test]
fn handles_are_send_and_sync() {
    fn assert_send_sync<T: Send + Sync>() {}
    assert_send_sync::<Codec>();
    assert_send_sync::<Encoding>();
    assert_send_sync::<Diff>();
    assert_send_sync::<CodecConfig>();
    assert_send_sync::<Floor>();

    // A codec shared across threads produces the same state everywhere.
    let codec = Codec::new(&quant44()).unwrap();
    let want = codec.encode(&[3u64, 1, 2], &THREE_ROWS, None).unwrap();
    std::thread::scope(|s| {
        for _ in 0..4 {
            s.spawn(|| {
                let e = codec.encode(&[3u64, 1, 2], &THREE_ROWS, None).unwrap();
                assert_eq!(e, want);
                assert_eq!(codec.unpack(&want).unwrap().len(), 12);
            });
        }
    });
}

#[test]
fn errors_render_their_message() {
    let err = CodecConfig::quant(4, 1).unwrap_err();
    assert!(!err.to_string().is_empty());
    let io: std::io::Error = err.into();
    assert_eq!(io.kind(), ErrorKind::InvalidInput);
    assert_eq!(Which::Content.name(), "content");
    assert_eq!(Id::U64(7).to_string(), "7");
    assert_eq!(Id::from("k").to_string(), "k");
    assert_eq!(Id::from("k").kind(), IdKind::Utf8);
}

#[test]
fn retained_encodings_outlive_cross_thread_diff_owners() {
    use std::sync::Arc;
    let reference = Arc::new(sample_two_rows());
    let id = reference.state_id();
    let threads: Vec<_> = (0..8)
        .map(|_| {
            let reference = Arc::clone(&reference);
            std::thread::spawn(move || {
                let diff = reference.diff(&reference).unwrap();
                drop(reference);
                assert_eq!(diff.reference_id(), id);
                assert_eq!(diff.n_unchanged(), 2);
                assert!(diff.changed().is_empty());
                diff
            })
        })
        .collect();
    drop(reference);
    for thread in threads {
        let diff = thread.join().unwrap();
        assert_eq!(diff.candidate_id(), id);
        drop(diff);
    }
}

/// The first lines a reader writes, and what the Display forms say: the same
/// text every binding produces for this data.
#[test]
fn direct_constructors_and_display_forms() {
    let vectors: [f32; 12] = [0.6, 0.8, 0.0, 0.0, 0.0, 0.6, 0.8, 0.0, 0.0, 0.0, 0.6, 0.8];
    let ids = semq::Ids::utf8(&["doc-1", "doc-2", "doc-3"]);
    let mut manifest = semq::Manifest::new();
    manifest.insert("encoder".to_string(), "example-encoder".to_string());
    manifest.insert("encoder_revision".to_string(), "1".to_string());
    let codec = semq::Codec::quant(4, 4).unwrap();
    assert_eq!(codec.config(), &semq::CodecConfig::quant(4, 4).unwrap());
    assert_eq!(
        semq::Codec::phase(4, 16).unwrap().config().sectors(),
        Some(16)
    );
    assert_eq!(
        semq::Codec::orbit(4, 50).unwrap().config().scale(),
        Some(50)
    );
    assert_eq!(codec.config().to_string(), "quant(dim=4, bins=4)");
    let state = codec.encode(ids, &vectors, Some(&manifest)).unwrap();
    let reference = semq::Encoding::from_bytes(&state.to_bytes()).unwrap();
    assert_eq!(
        reference.to_string(),
        "Encoding(3 rows, quant(dim=4, bins=4), state_id 6e6f8a89bae4...)"
    );
    let mut rebuilt = vectors;
    rebuilt[8..12].copy_from_slice(&[0.8, 0.0, 0.0, 0.6]);
    let diff = reference
        .diff(&codec.encode(ids, &rebuilt, Some(&manifest)).unwrap())
        .unwrap();
    assert_eq!(
        diff.to_string(),
        "1 of 3 rows changed: doc-3 (hamming 3). 0 added, 0 removed."
    );
    let same = reference
        .diff(&codec.encode(ids, &vectors, Some(&manifest)).unwrap())
        .unwrap();
    assert_eq!(same.to_string(), "0 of 3 rows changed. 0 added, 0 removed.");
    let mut other = manifest.clone();
    other.insert("encoder".to_string(), "other".to_string());
    let changed_manifest = reference
        .diff(&codec.encode(ids, &vectors, Some(&other)).unwrap())
        .unwrap();
    assert_eq!(
        changed_manifest.to_string(),
        "0 of 3 rows changed. 0 added, 0 removed. Manifest changed: encoder."
    );
    let mut grown = vectors.to_vec();
    grown.extend_from_slice(&[1.0, 0.0, 0.0, 0.0]);
    let added = reference
        .diff(
            &codec
                .encode(
                    semq::Ids::utf8(&["doc-1", "doc-2", "doc-3", "doc-4"]),
                    &grown,
                    Some(&manifest),
                )
                .unwrap(),
        )
        .unwrap();
    assert_eq!(
        added.to_string(),
        "0 of 3 rows changed. 1 added, 0 removed."
    );
    let nulls: Vec<semq::Diff> = (0..3)
        .map(|_| {
            reference
                .diff(&codec.encode(ids, &vectors, Some(&manifest)).unwrap())
                .unwrap()
        })
        .collect();
    let floor = semq::Floor::measure(&nulls).unwrap();
    assert_eq!(
        floor.to_string(),
        "Floor(0 of 3 rows, hamming 0, from 3 nulls)"
    );
    assert!(!diff.within(&floor).unwrap());
}

/// Every accepted form of Floor::measure, including owned diffs, which must
/// stay alive until the core has read them.
#[test]
fn floor_measure_accepts_borrowed_and_owned_diffs() {
    let codec = semq::Codec::quant(4, 4).unwrap();
    let v = [1.0f32, 0.0, 0.0, 0.0];
    let ids = semq::Ids::u64(&[1]);
    let reference = codec.encode(ids, &v, None).unwrap();
    let null = || {
        reference
            .diff(&codec.encode(ids, &v, None).unwrap())
            .unwrap()
    };
    let owned: Vec<semq::Diff> = vec![null(), null()];
    let slice: Vec<&semq::Diff> = owned.iter().collect();
    let expected = semq::Floor::measure(slice.as_slice()).unwrap();
    assert_eq!(
        semq::Floor::measure([&owned[0], &owned[1]]).unwrap(),
        expected
    );
    assert_eq!(semq::Floor::measure(&owned).unwrap(), expected);
    assert_eq!(semq::Floor::measure(owned.iter()).unwrap(), expected);
    assert_eq!(semq::Floor::measure(owned).unwrap(), expected);
    assert_eq!(
        semq::Floor::measure(vec![null(), null()]).unwrap(),
        expected
    );
}
