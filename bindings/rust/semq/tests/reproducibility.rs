// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

//! The Rust host of the reproducibility fixture.
//!
//! Encodes the 1,000 real embeddings of `tests/reproducibility` with every
//! configuration of its `expected.json` and compares `content_digest`,
//! `state_id` and the saved file's bytes. The other bindings run the same
//! comparison. A missing fixture is skipped with a message.
//!
//! The standard library has no SHA-256, so the file bytes are hashed with
//! the core's `semq_sha256`; the expected value comes from Python's
//! `hashlib`, so a wrong hash on either side fails the test.

use std::fs;
use std::path::{Path, PathBuf};

use semq::{Codec, CodecConfig, Encoding, Ids, Manifest};
use serde_json::Value;

fn fixture_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../tests/reproducibility")
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

fn sha256(data: &[u8]) -> [u8; 32] {
    let mut out = [0u8; 32];
    // SAFETY: `data` is a valid slice of `data.len()` bytes and `out` holds 32.
    unsafe { semq_sys::semq_sha256(data.as_ptr(), data.len() as u64, out.as_mut_ptr()) };
    out
}

fn json(dir: &Path, name: &str) -> Value {
    let raw = fs::read(dir.join(name)).unwrap_or_else(|err| panic!("{name}: {err}"));
    serde_json::from_slice(&raw).unwrap_or_else(|err| panic!("{name}: {err}"))
}

#[test]
fn reproducibility() {
    let dir = fixture_root();
    let raw = match fs::read(dir.join("vectors.f32")) {
        Ok(raw) => raw,
        Err(err) => {
            eprintln!("reproducibility fixture missing, skipped ({err})");
            return;
        }
    };
    let meta = json(&dir, "ids.json");
    let expected = json(&dir, "expected.json");

    let vectors: Vec<f32> = raw
        .chunks_exact(4)
        .map(|b| f32::from_le_bytes([b[0], b[1], b[2], b[3]]))
        .collect();
    let values: Vec<&str> = meta["values"]
        .as_array()
        .expect("ids.json: values")
        .iter()
        .map(|v| v.as_str().expect("ids.json: utf8 id"))
        .collect();
    assert_eq!(expected["id_kind"], "utf8");
    let manifest: Manifest = expected["manifest"]
        .as_object()
        .expect("expected.json: manifest")
        .iter()
        .map(|(k, v)| (k.clone(), v.as_str().expect("manifest value").to_owned()))
        .collect();

    let configs = expected["configs"]
        .as_object()
        .expect("expected.json: configs");
    for (name, expect) in configs {
        let spec = &expect["config"];
        let dim = spec["dim"].as_u64().unwrap() as u32;
        let parameter = spec["parameter"].as_u64().unwrap() as u32;
        let config = match spec["operator"].as_str().unwrap() {
            "quant" => CodecConfig::quant(dim, parameter),
            "phase" => CodecConfig::phase(dim, parameter),
            "orbit" => CodecConfig::orbit(dim, parameter),
            other => panic!("{name}: unknown operator {other}"),
        }
        .unwrap();
        let codec = Codec::new(&config).unwrap();
        let state = codec
            .encode(Ids::utf8(&values), &vectors, Some(&manifest))
            .unwrap_or_else(|err| panic!("{name}: encode: {err}"));
        let data = state.to_bytes();

        assert_eq!(
            hex(&state.content_digest()),
            expect["content_digest"],
            "{name}: content_digest"
        );
        assert_eq!(
            hex(&state.state_id()),
            expect["state_id"],
            "{name}: state_id"
        );
        assert_eq!(
            data.len() as u64,
            expect["file_size"].as_u64().unwrap(),
            "{name}: file size"
        );
        assert_eq!(
            hex(&sha256(&data)),
            expect["file_sha256"],
            "{name}: file sha256"
        );
        let loaded = Encoding::from_bytes(&data).unwrap();
        assert_eq!(loaded.state_id(), state.state_id(), "{name}: load");
        eprintln!("{name}: state_id {}", hex(&state.state_id()));
    }
}
