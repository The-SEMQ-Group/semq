// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

//! The Rust host runner: every conformance case through the public surface.
//!
//! Each vector directory under `tests/conformance` holds a `manifest.json`
//! of cases. One test per vector executes them with the public API only,
//! compares with the expectations and collects failures by case id; a
//! vector directory that is absent is skipped with a message. Cases a host
//! cannot execute are skipped as unsupported, as the vector document
//! allows:
//!
//! * vector 00: the Rust host has no SHA-256 of its own (the standard
//!   library has none and the binding hashes nothing host-side), so there
//!   is no platform reference to check; the core's SHA-256 is exercised by
//!   the C tests and pinned through every digest of vectors 04 and 07-13;
//! * vector 04 `empty-without-kind`: an `Ids` value always states its kind
//!   (`Ids::utf8(&[])` is the empty `utf8` set), so a kindless id set
//!   cannot be sent;
//! * vector 07 `duplicate-key`: a `Manifest` is a `BTreeMap`, whose keys
//!   are unique;
//! * vector 15 rounding modes: Rust cannot set the FP rounding mode.
//!
//! Bytes that are not UTF-8 (the `values_hex` and `pairs_hex` inputs of
//! vectors 06 and 07, and the lone surrogate) cannot become a `&str`: the
//! host's string type rejects them before the core, which is the
//! `InvalidInput` verdict those cases expect.

use std::any::Any;
use std::fmt;
use std::fs;
use std::panic::{self, AssertUnwindSafe};
use std::path::{Path, PathBuf};

use semq::{
    Codec, CodecConfig, Diff, DiffReport, Encoding, Error, Floor, GateOptions, Id, Ids, Manifest,
    Which,
};
use serde_json::{json, Map, Value};

// --------------------------------------------------------------------------
// The runner
// --------------------------------------------------------------------------

/// One case passed, or the host cannot execute it.
enum Outcome {
    Pass,
    Skip(String),
}

/// `Err` is the failure message; the runner prefixes the case id.
type CaseResult = Result<Outcome, String>;

macro_rules! fail {
    ($($arg:tt)*) => {
        return Err(format!($($arg)*))
    };
}

macro_rules! ensure {
    ($cond:expr, $($arg:tt)*) => {
        if !$cond {
            fail!($($arg)*);
        }
    };
}

/// `map_err` with a label, for the SDK's and the file system's errors.
trait Context<T> {
    fn context(self, what: impl fmt::Display) -> Result<T, String>;
}

impl<T, E: fmt::Display> Context<T> for Result<T, E> {
    fn context(self, what: impl fmt::Display) -> Result<T, String> {
        self.map_err(|err| format!("{what}: {err}"))
    }
}

/// The vectors: SEMQ_CONFORMANCE_DIR when set (a published crate tested
/// outside the checkout), else the checkout's tests/conformance.
fn conformance_root() -> PathBuf {
    match std::env::var_os("SEMQ_CONFORMANCE_DIR") {
        Some(dir) => PathBuf::from(dir),
        None => Path::new(env!("CARGO_MANIFEST_DIR")).join("../../../tests/conformance"),
    }
}

/// An explicit vector directory must hold every vector: a missing one is a
/// failure, not a skip.
fn vectors_required() -> bool {
    std::env::var_os("SEMQ_CONFORMANCE_DIR").is_some()
}

/// Run every case of one vector directory and fail with the collected
/// failures, each under its case id.
fn run_vector(name: &str, run: fn(&Path, &Value) -> CaseResult) {
    let dir = conformance_root().join(name);
    let raw = match fs::read(dir.join("manifest.json")) {
        Ok(raw) => raw,
        Err(err) if !vectors_required() => {
            eprintln!("{name}: skipped, no manifest ({err})");
            return;
        }
        Err(err) => panic!("{name}: no manifest under SEMQ_CONFORMANCE_DIR ({err})"),
    };
    let manifest: Value =
        serde_json::from_slice(&raw).unwrap_or_else(|err| panic!("{name}/manifest.json: {err}"));
    let cases = manifest["cases"]
        .as_array()
        .unwrap_or_else(|| panic!("{name}/manifest.json: no cases"));
    let mut passed = 0usize;
    let mut skipped = Vec::new();
    let mut failed = Vec::new();
    for case in cases {
        let id = case["id"].as_str().unwrap_or("<no id>");
        match panic::catch_unwind(AssertUnwindSafe(|| run(&dir, case))) {
            Ok(Ok(Outcome::Pass)) => passed += 1,
            Ok(Ok(Outcome::Skip(why))) => skipped.push(format!("{id}: {why}")),
            Ok(Err(why)) => failed.push(format!("{id}: {why}")),
            Err(payload) => failed.push(format!("{id}: panicked: {}", panic_message(&*payload))),
        }
    }
    eprintln!(
        "{name}: {} cases, {passed} passed, {} skipped, {} failed",
        cases.len(),
        skipped.len(),
        failed.len()
    );
    for line in &skipped {
        eprintln!("  skipped {line}");
    }
    assert!(
        failed.is_empty(),
        "{name}: {} of {} cases failed\n  {}",
        failed.len(),
        cases.len(),
        failed.join("\n  ")
    );
}

fn panic_message(payload: &(dyn Any + Send)) -> String {
    if let Some(text) = payload.downcast_ref::<&str>() {
        (*text).to_owned()
    } else if let Some(text) = payload.downcast_ref::<String>() {
        text.clone()
    } else {
        "non-string panic payload".to_owned()
    }
}

// --------------------------------------------------------------------------
// Manifest access
// --------------------------------------------------------------------------

fn field<'a>(value: &'a Value, key: &str) -> Result<&'a Value, String> {
    value
        .get(key)
        .ok_or_else(|| format!("manifest: no {key:?}"))
}

/// A key that is present and not `null`.
fn has(value: &Value, key: &str) -> bool {
    matches!(value.get(key), Some(v) if !v.is_null())
}

fn str_field<'a>(value: &'a Value, key: &str) -> Result<&'a str, String> {
    field(value, key)?
        .as_str()
        .ok_or_else(|| format!("manifest: {key:?} is not a string"))
}

fn u64_field(value: &Value, key: &str) -> Result<u64, String> {
    field(value, key)?
        .as_u64()
        .ok_or_else(|| format!("manifest: {key:?} is not an integer"))
}

fn u32_field(value: &Value, key: &str) -> Result<u32, String> {
    u32::try_from(u64_field(value, key)?).map_err(|_| format!("manifest: {key:?} overflows u32"))
}

fn usize_field(value: &Value, key: &str) -> Result<usize, String> {
    usize::try_from(u64_field(value, key)?).map_err(|_| format!("manifest: {key:?} overflows"))
}

fn bool_field(value: &Value, key: &str) -> Result<bool, String> {
    field(value, key)?
        .as_bool()
        .ok_or_else(|| format!("manifest: {key:?} is not a boolean"))
}

/// An integer that may be absent or `null`.
fn opt_u64(value: &Value, key: &str) -> Result<Option<u64>, String> {
    match value.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(v) => v
            .as_u64()
            .map(Some)
            .ok_or_else(|| format!("manifest: {key:?} is not an integer")),
    }
}

/// A string that may be absent or `null`.
fn opt_str<'a>(value: &'a Value, key: &str) -> Result<Option<&'a str>, String> {
    match value.get(key) {
        None | Some(Value::Null) => Ok(None),
        Some(v) => v
            .as_str()
            .map(Some)
            .ok_or_else(|| format!("manifest: {key:?} is not a string")),
    }
}

fn array_field<'a>(value: &'a Value, key: &str) -> Result<&'a [Value], String> {
    field(value, key)?
        .as_array()
        .map(Vec::as_slice)
        .ok_or_else(|| format!("manifest: {key:?} is not an array"))
}

/// The items of an array of strings.
fn strings(values: &[Value]) -> Result<Vec<&str>, String> {
    values
        .iter()
        .map(|v| {
            v.as_str()
                .ok_or_else(|| format!("manifest: {v} is not a string"))
        })
        .collect()
}

/// A `[first, second]` array of strings.
fn pair_of(value: &Value) -> Result<(&str, &str), String> {
    let items = value
        .as_array()
        .map(Vec::as_slice)
        .ok_or_else(|| format!("manifest: {value} is not a pair"))?;
    match strings(items)?.as_slice() {
        [first, second] => Ok((first, second)),
        _ => fail!("manifest: {value} is not a pair"),
    }
}

/// `shape` as `(rows, columns)`.
fn shape_of(input: &Value) -> Result<(usize, usize), String> {
    let shape = array_field(input, "shape")?;
    let dims: Option<Vec<usize>> = shape
        .iter()
        .map(|v| v.as_u64().and_then(|n| usize::try_from(n).ok()))
        .collect();
    match dims.as_deref() {
        Some([rows, cols]) => Ok((*rows, *cols)),
        _ => fail!("manifest: shape {shape:?} is not [rows, cols]"),
    }
}

/// The `input` and `expect` objects of a case.
fn parts(case: &Value) -> Result<(&Value, &Value), String> {
    Ok((field(case, "input")?, field(case, "expect")?))
}

// --------------------------------------------------------------------------
// Inputs
// --------------------------------------------------------------------------

/// A config as the manifests spell it: the parameter under its operator key
/// or under `parameter`. The inner result is the core's verdict.
fn try_config(spec: &Value) -> Result<semq::Result<CodecConfig>, String> {
    let operator = str_field(spec, "operator")?;
    let dim = u32_field(spec, "dim")?;
    let parameter = ["bins", "sectors", "scale", "parameter"]
        .into_iter()
        .find(|key| has(spec, key))
        .ok_or_else(|| "manifest: config has no parameter".to_owned())?;
    let parameter = u32_field(spec, parameter)?;
    Ok(match operator {
        "quant" => CodecConfig::quant(dim, parameter),
        "phase" => CodecConfig::phase(dim, parameter),
        "orbit" => CodecConfig::orbit(dim, parameter),
        other => fail!("manifest: unknown operator {other:?}"),
    })
}

fn config_of(spec: &Value) -> Result<CodecConfig, String> {
    try_config(spec)?.context("config")
}

/// An id set the runner owns; `view` is the input the API takes.
enum OwnedIds {
    U64(Vec<u64>),
    Utf8(Vec<String>),
}

impl OwnedIds {
    fn view(&self) -> Ids<'_> {
        match self {
            OwnedIds::U64(ids) => Ids::u64(ids),
            OwnedIds::Utf8(ids) => Ids::from(ids.as_slice()),
        }
    }

    fn len(&self) -> usize {
        match self {
            OwnedIds::U64(ids) => ids.len(),
            OwnedIds::Utf8(ids) => ids.len(),
        }
    }
}

/// `{"kind": "u64" | "utf8", "values": [...]}`, `u64` values as decimal.
fn ids_of(spec: &Value) -> Result<OwnedIds, String> {
    let values = strings(array_field(spec, "values")?)?;
    match str_field(spec, "kind")? {
        "u64" => u64s(&values).map(OwnedIds::U64),
        "utf8" => Ok(OwnedIds::Utf8(
            values.iter().map(|v| (*v).to_owned()).collect(),
        )),
        other => fail!("manifest: unknown id kind {other:?}"),
    }
}

fn u64s(values: &[&str]) -> Result<Vec<u64>, String> {
    values
        .iter()
        .map(|v| v.parse::<u64>().context(format!("id {v:?}")))
        .collect()
}

fn range_ids(n: usize) -> Vec<u64> {
    (0..n as u64).collect()
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

fn unhex(text: &str) -> Result<Vec<u8>, String> {
    ensure!(text.len() % 2 == 0, "hex {text:?} has an odd length");
    (0..text.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&text[i..i + 2], 16).context(format!("hex {text:?}")))
        .collect()
}

/// 8-character bit patterns as float32 values.
fn f32_from_hex(words: &[Value]) -> Result<Vec<f32>, String> {
    strings(words)?
        .iter()
        .map(|w| {
            u32::from_str_radix(w, 16)
                .map(f32::from_bits)
                .context(format!("vectors_f32 {w:?}"))
        })
        .collect()
}

fn read_file(dir: &Path, name: &str) -> Result<Vec<u8>, String> {
    fs::read(dir.join(name)).context(name)
}

/// A little-endian float32 file, checked against `shape` when given.
fn read_f32(dir: &Path, name: &str, shape: Option<(usize, usize)>) -> Result<Vec<f32>, String> {
    let bytes = read_file(dir, name)?;
    ensure!(
        bytes.len() % 4 == 0,
        "{name}: {} bytes is not a float32 array",
        bytes.len()
    );
    let out: Vec<f32> = bytes
        .chunks_exact(4)
        .map(|c| f32::from_le_bytes([c[0], c[1], c[2], c[3]]))
        .collect();
    if let Some((rows, cols)) = shape {
        ensure!(
            out.len() == rows * cols,
            "{name}: {} values, shape [{rows}, {cols}]",
            out.len()
        );
    }
    Ok(out)
}

fn load(dir: &Path, name: &str) -> Result<Encoding, String> {
    Encoding::from_bytes(&read_file(dir, name)?).context(name)
}

fn diff_files(dir: &Path, reference: &str, candidate: &str) -> Result<Diff, String> {
    load(dir, reference)?
        .diff(&load(dir, candidate)?)
        .context(format!("diff {reference} {candidate}"))
}

/// The diffs of the `[reference, candidate]` pairs of a `null_diffs` input.
fn null_diffs(dir: &Path, pairs: &[Value]) -> Result<Vec<Diff>, String> {
    pairs
        .iter()
        .map(|pair| {
            let (reference, candidate) = pair_of(pair)?;
            diff_files(dir, reference, candidate)
        })
        .collect()
}

// --------------------------------------------------------------------------
// Expectations
// --------------------------------------------------------------------------

fn error_name(err: &Error) -> &'static str {
    match err {
        Error::InvalidInput { .. } => "InvalidInput",
        Error::Incompatible { .. } => "Incompatible",
        Error::FormatError { .. } => "FormatError",
        Error::IntegrityError { .. } => "IntegrityError",
        Error::Unsupported { .. } => "Unsupported",
        Error::Native { .. } => "Native",
    }
}

/// Check `err` against an expected `{error, row, field, which}`. `field` is
/// `section` for `FormatError`, as in the other host runners.
fn assert_error(err: &Error, want: &Value) -> Result<(), String> {
    let name = str_field(want, "error")?;
    ensure!(
        error_name(err) == name,
        "want {name}, got {}: {err}",
        error_name(err)
    );
    let (row, field, which): (Option<u64>, Option<u64>, Option<&str>) = match err {
        Error::InvalidInput { row, field, .. } => (*row, *field, None),
        Error::Incompatible { field, .. } => (None, *field, None),
        Error::FormatError { row, section, .. } => (*row, *section, None),
        Error::IntegrityError { which, .. } => (None, None, which.map(Which::name)),
        Error::Unsupported { .. } => (None, None, None),
        Error::Native { row, field, .. } => (*row, *field, None),
    };
    if let Some(want_row) = opt_u64(want, "row")? {
        ensure!(
            row == Some(want_row),
            "row: got {row:?}, want {want_row} ({err})"
        );
    }
    if let Some(want_field) = opt_u64(want, "field")? {
        ensure!(
            field == Some(want_field),
            "field: got {field:?}, want {want_field} ({err})"
        );
    }
    if let Some(want_which) = opt_str(want, "which")? {
        ensure!(
            which == Some(want_which),
            "which: got {which:?}, want {want_which:?} ({err})"
        );
    }
    Ok(())
}

/// Apply the case's expectation to a result: an expected error is asserted
/// and `None` returned; otherwise the value is returned for the caller to
/// check.
fn verdict<T>(expect: &Value, result: semq::Result<T>) -> Result<Option<T>, String> {
    if has(expect, "error") {
        match result {
            Err(err) => assert_error(&err, expect).map(|()| None),
            Ok(_) => fail!("want {}, got no error", str_field(expect, "error")?),
        }
    } else {
        result.map(Some).context("unexpected error")
    }
}

/// A case that must expect an error: the result is checked against it.
fn assert_rejected<T>(expect: &Value, result: semq::Result<T>) -> CaseResult {
    ensure!(has(expect, "error"), "the case expects no error: {expect}");
    verdict(expect, result).map(|_| Outcome::Pass)
}

/// The verdict of a host representation check: bytes the host's string
/// type cannot carry are rejected before the core, which the case must
/// expect as `InvalidInput`.
fn host_rejects(expect: &Value) -> CaseResult {
    ensure!(
        opt_str(expect, "error")? == Some("InvalidInput"),
        "the host rejects the input, but the case expects {expect}"
    );
    Ok(Outcome::Pass)
}

/// The `config` object of the report schema.
fn config_value(config: &CodecConfig) -> Value {
    let mut out = Map::new();
    out.insert("operator".to_owned(), config.operator().name().into());
    out.insert("dim".to_owned(), config.dim().into());
    out.insert(
        config.operator().parameter_name().to_owned(),
        config.parameter().into(),
    );
    out.insert("rule_revision".to_owned(), config.rule_revision().into());
    Value::Object(out)
}

fn diff_report_value(report: &DiffReport) -> Value {
    let changed: Vec<Value> = report
        .changed
        .iter()
        .map(|(id, hamming)| json!([id, hamming]))
        .collect();
    let manifest_changes: Map<String, Value> = report
        .manifest_changes
        .iter()
        .map(|(key, (before, after))| (key.clone(), json!([before, after])))
        .collect();
    json!({
        "reference_id": report.reference_id,
        "candidate_id": report.candidate_id,
        "id_kind": report.id_kind,
        "config": config_value(&report.config),
        "added": report.added,
        "removed": report.removed,
        "changed": changed,
        "n_unchanged": report.n_unchanged,
        "manifest_changes": manifest_changes,
    })
}

/// Compare the report form of `diff` with the expected object.
fn assert_report(diff: &Diff, want: &Value) -> Result<(), String> {
    let got = diff_report_value(&diff.as_report());
    ensure!(&got == want, "report:\n got {got}\nwant {want}");
    Ok(())
}

/// The floor's JSON form, parsed.
fn floor_value(floor: &Floor) -> Value {
    serde_json::from_str(&floor.to_json()).expect("the core writes valid JSON")
}

/// Compare the JSON form of `floor` with the expected object.
fn assert_floor(floor: &Floor, want: &Value) -> Result<(), String> {
    let got = floor_value(floor);
    ensure!(&got == want, "floor:\n got {got}\nwant {want}");
    Ok(())
}

/// The floor a manifest gives as a JSON object, read by the core; the inner
/// result is its verdict on that object.
fn floor_of(raw: &Value) -> Result<semq::Result<Floor>, String> {
    Ok(Floor::from_json(raw.to_string()))
}

/// The first index where `got` and `want` differ by more than `ulps`,
/// measured on the signed int32 bit patterns as the other runners do.
fn ulp_apart(got: &[f32], want: &[f32], ulps: i64) -> Option<usize> {
    (0..want.len()).find(|&i| {
        let g = i64::from(got[i].to_bits() as i32);
        let w = i64::from(want[i].to_bits() as i32);
        (g - w).abs() > ulps
    })
}

// --------------------------------------------------------------------------
// Vectors
// --------------------------------------------------------------------------

fn vector_00(_dir: &Path, _case: &Value) -> CaseResult {
    // The host has no SHA-256 of its own to hold against the FIPS vectors;
    // the core's is pinned through every digest of vectors 04 and 07-13.
    Ok(Outcome::Skip(
        "unsupported: the Rust host has no SHA-256 entry point".to_owned(),
    ))
}

fn vector_01(_dir: &Path, case: &Value) -> CaseResult {
    let (input, expect) = parts(case)?;
    let Some(config) = verdict(expect, try_config(input)?)? else {
        return Ok(Outcome::Pass);
    };
    let bytes = config.to_bytes();
    let want = str_field(expect, "bytes")?;
    ensure!(
        hex(&bytes) == want,
        "bytes: got {}, want {want}",
        hex(&bytes)
    );
    let back = CodecConfig::from_bytes(&bytes).context("from_bytes")?;
    ensure!(back == config, "round trip: got {back:?}, want {config:?}");
    Ok(Outcome::Pass)
}

fn vector_02(_dir: &Path, case: &Value) -> CaseResult {
    let (input, expect) = parts(case)?;
    let config = config_of(input)?;
    let bytes_per_vector = u32_field(expect, "bytes_per_vector")?;
    ensure!(
        config.bytes_per_vector() == bytes_per_vector,
        "bytes_per_vector: got {}, want {bytes_per_vector}",
        config.bytes_per_vector()
    );
    let units_per_row = u32_field(expect, "units_per_row")?;
    ensure!(
        config.units_per_row() == units_per_row,
        "units_per_row: got {}, want {units_per_row}",
        config.units_per_row()
    );
    if str_field(input, "operator")? == "quant" {
        let bits = config
            .max_magnitude()
            .map(|m| format!("{:08x}", m.to_bits()))
            .ok_or_else(|| "max_magnitude: not available for quant".to_owned())?;
        let want = str_field(expect, "max_magnitude_bits")?;
        ensure!(bits == want, "max_magnitude_bits: got {bits}, want {want}");
    }
    Ok(Outcome::Pass)
}

fn vector_03(dir: &Path, case: &Value) -> CaseResult {
    let (input, expect) = parts(case)?;
    let config = config_of(field(input, "config")?)?;
    let codec = Codec::new(&config).context("codec")?;
    let (n, dim) = shape_of(input)?;
    let vectors = read_f32(dir, str_field(input, "vectors_file")?, Some((n, dim)))?;
    let enc = codec
        .encode(&range_ids(n), &vectors, None)
        .context("encode")?;
    let rows_file = str_field(expect, "rows_file")?;
    ensure!(
        enc.rows() == read_file(dir, rows_file)?.as_slice(),
        "rows differ from {rows_file}"
    );
    let symbols_file = str_field(expect, "symbols_file")?;
    let symbols = codec.unpack(&enc).context("unpack")?;
    ensure!(
        symbols == read_file(dir, symbols_file)?,
        "symbols differ from {symbols_file}"
    );
    Ok(Outcome::Pass)
}

fn vector_04(_dir: &Path, case: &Value) -> CaseResult {
    let (input, expect) = parts(case)?;
    let config = config_of(field(input, "config")?)?;
    let codec = Codec::new(&config).context("codec")?;
    let dim = config.dim() as usize;
    let id = str_field(case, "id")?;
    if has(input, "host") {
        // Representation checks the host performs before the core.
        return match id {
            // `encode` takes `&[f32]`: a `&[f64]` does not compile, so there
            // is nothing to execute.
            "float64-input" => Ok(Outcome::Pass),
            "wrong-width" => {
                let result = codec.encode(&[1u64], &vec![0f32; dim - 1], None);
                ensure!(
                    matches!(result, Err(Error::InvalidInput { .. })),
                    "want InvalidInput, got {result:?}"
                );
                Ok(Outcome::Pass)
            }
            other => fail!("unknown host case {other:?}"),
        };
    }
    if id == "empty-without-kind" {
        // `Ids::u64(&[])` and `Ids::utf8(&[])` are the empty sets of their
        // kinds; the core's rejection of a kindless set is exercised by the
        // C tests.
        return Ok(Outcome::Skip(
            "unsupported: an `Ids` value always states its kind".to_owned(),
        ));
    }
    let ids = ids_of(field(input, "ids")?)?;
    let mut vectors = f32_from_hex(array_field(input, "vectors_f32")?)?;
    ensure!(
        vectors.len() % dim == 0,
        "vectors_f32: {} values for dim {dim}",
        vectors.len()
    );
    vectors.truncate(ids.len() * dim);
    let Some(enc) = verdict(expect, codec.encode(ids.view(), &vectors, None))? else {
        return Ok(Outcome::Pass);
    };
    let want = str_field(expect, "content_digest")?;
    let got = hex(&enc.content_digest());
    ensure!(got == want, "content_digest: got {got}, want {want}");
    Ok(Outcome::Pass)
}

fn vector_05(dir: &Path, case: &Value) -> CaseResult {
    let (input, expect) = parts(case)?;
    let config = config_of(field(input, "config")?)?;
    let codec = Codec::new(&config).context("codec")?;
    let (n, dim) = shape_of(input)?;
    let rows_file = str_field(input, "rows_file")?;
    let rows = read_file(dir, rows_file)?;
    let bpv = config.bytes_per_vector() as usize;
    ensure!(
        rows.len() == n * bpv,
        "{rows_file}: {} bytes for {n} rows of {bpv}",
        rows.len()
    );
    let enc = Encoding::new(&range_ids(n), &rows, &config, None).context("Encoding::new")?;
    let got = codec.decode(&enc).context("decode")?;
    let want = read_f32(
        dir,
        str_field(expect, "representatives_file")?,
        Some((n, dim)),
    )?;
    ensure!(
        got.len() == want.len(),
        "decode: {} values, want {}",
        got.len(),
        want.len()
    );
    let tolerance = i64::try_from(u64_field(expect, "tolerance_ulp")?)
        .map_err(|_| "manifest: tolerance_ulp overflows".to_owned())?;
    if let Some(i) = ulp_apart(&got, &want, tolerance) {
        fail!(
            "representative {i}: got {:08x}, want {:08x} (tolerance {tolerance} ulp, backend {})",
            got[i].to_bits(),
            want[i].to_bits(),
            codec.backend()
        );
    }
    Ok(Outcome::Pass)
}

fn vector_06(_dir: &Path, case: &Value) -> CaseResult {
    let (input, expect) = parts(case)?;
    let config = CodecConfig::quant(4, 4).context("config")?;
    let bpv = config.bytes_per_vector() as usize;
    let zero_rows = |n: usize| vec![0u8; n * bpv];
    match str_field(case, "id")? {
        "utf8-too-long" => {
            let long = "x".repeat(usize_field(input, "length")?);
            let result = Encoding::new(&[long.as_str()], &zero_rows(1), &config, None);
            return assert_rejected(expect, result);
        }
        "lone-surrogate" => {
            // The UTF-8 encoding of U+D800 (`ed a0 80`) is not a `&str`:
            // the host's string type rejects it before the core, and the
            // compiler rejects the literal.
            return host_rejects(expect);
        }
        _ => {}
    }
    let spec = field(input, "ids")?;
    if has(spec, "values_hex") {
        // Ids that are not valid UTF-8 travel as hex; those that are not a
        // `String` are rejected by the host, the rest by the core.
        let mut ids = Vec::new();
        for word in strings(array_field(spec, "values_hex")?)? {
            match String::from_utf8(unhex(word)?) {
                Ok(id) => ids.push(id),
                Err(_) => return host_rejects(expect),
            }
        }
        let result = Encoding::new(ids.as_slice(), &zero_rows(ids.len()), &config, None);
        return assert_rejected(expect, result);
    }
    let ids = ids_of(spec)?;
    let enc =
        Encoding::new(ids.view(), &zero_rows(ids.len()), &config, None).context("Encoding::new")?;
    let got: Vec<String> = enc.ids().iter().map(|id| id.to_string()).collect();
    let want = strings(array_field(expect, "sorted")?)?;
    ensure!(got == want, "sorted: got {got:?}, want {want:?}");
    let section = str_field(expect, "ids_section")?;
    let image = enc.to_bytes();
    let end = 28 + section.len() / 2;
    ensure!(
        image.len() >= end,
        "image: {} bytes, ids section ends at {end}",
        image.len()
    );
    let got = hex(&image[28..end]);
    ensure!(got == section, "ids_section:\n got {got}\nwant {section}");
    Ok(Outcome::Pass)
}

fn vector_07(_dir: &Path, case: &Value) -> CaseResult {
    let (input, expect) = parts(case)?;
    let config = CodecConfig::quant(4, 4).context("config")?;
    let mut raw_pairs: Vec<(String, String)> = Vec::new();
    if has(input, "pairs") {
        for pair in array_field(input, "pairs")? {
            let (key, value) = pair_of(pair)?;
            raw_pairs.push((key.to_owned(), value.to_owned()));
        }
    } else {
        // Non-ASCII inputs travel as hex; bytes that are not a `String`
        // are rejected by the host before the core.
        for pair in array_field(input, "pairs_hex")? {
            let (key, value) = pair_of(pair)?;
            match (
                String::from_utf8(unhex(key)?),
                String::from_utf8(unhex(value)?),
            ) {
                (Ok(key), Ok(value)) => raw_pairs.push((key, value)),
                _ => return host_rejects(expect),
            }
        }
    }
    let mut pairs = Manifest::new();
    let mut duplicate = false;
    for (key, value) in raw_pairs {
        duplicate |= pairs.insert(key, value).is_some();
    }
    if duplicate {
        // The host has no way to send a duplicate key; the core's
        // rejection is exercised by the C tests.
        return Ok(Outcome::Skip(
            "unsupported: a Manifest is a BTreeMap, whose keys are unique".to_owned(),
        ));
    }
    let result = Encoding::new(Ids::u64(&[]), &[], &config, Some(&pairs));
    let Some(enc) = verdict(expect, result)? else {
        return Ok(Outcome::Pass);
    };
    let image = enc.to_bytes();
    ensure!(image.len() >= 28 + 64, "image: {} bytes", image.len());
    let section = hex(&image[28..image.len() - 64]);
    let want = str_field(expect, "manifest_section")?;
    ensure!(
        section == want,
        "manifest_section:\n got {section}\nwant {want}"
    );
    let want = str_field(expect, "state_id")?;
    let got = hex(&enc.state_id());
    ensure!(got == want, "state_id: got {got}, want {want}");
    let got = enc.manifest();
    ensure!(got == pairs, "manifest: got {got:?}, want {pairs:?}");
    Ok(Outcome::Pass)
}

fn vector_08(dir: &Path, case: &Value) -> CaseResult {
    let (input, expect) = parts(case)?;
    let config = config_of(field(input, "config")?)?;
    if has(input, "file") {
        let enc = load(dir, str_field(input, "file")?)?;
        ensure!(
            enc.config() == &config,
            "config: got {:?}, want {config:?}",
            enc.config()
        );
        let want = str_field(expect, "content_digest")?;
        let got = hex(&enc.content_digest());
        ensure!(got == want, "content_digest: got {got}, want {want}");
        let want = str_field(expect, "state_id")?;
        let got = hex(&enc.state_id());
        ensure!(got == want, "state_id: got {got}, want {want}");
        return Ok(Outcome::Pass);
    }
    let codec = Codec::new(&config).context("codec")?;
    let dim = config.dim() as usize;
    let vectors_file = str_field(input, "vectors_file")?;
    let vectors = read_f32(dir, vectors_file, None)?;
    ensure!(
        vectors.len() % dim == 0,
        "{vectors_file}: {} values for dim {dim}",
        vectors.len()
    );
    let want = str_field(expect, "state_id")?;
    for order in array_field(input, "orders")? {
        let order = order
            .as_array()
            .map(Vec::as_slice)
            .ok_or_else(|| format!("manifest: order {order} is not an array"))?;
        let ids = u64s(&strings(order)?)?;
        // Ids are 1-based indices into the vectors file.
        let mut rows = Vec::with_capacity(ids.len() * dim);
        for &id in &ids {
            let index = usize::try_from(id)
                .ok()
                .and_then(|i| i.checked_sub(1))
                .ok_or_else(|| format!("order id {id} is not 1-based"))?;
            let row = vectors
                .get(index * dim..(index + 1) * dim)
                .ok_or_else(|| format!("order id {id} is past the vectors file"))?;
            rows.extend_from_slice(row);
        }
        let enc = codec
            .encode(&ids, &rows, None)
            .context(format!("encode {ids:?}"))?;
        let got = hex(&enc.state_id());
        ensure!(
            got == want,
            "order {ids:?}: state_id got {got}, want {want}"
        );
    }
    Ok(Outcome::Pass)
}

fn vector_09(dir: &Path, case: &Value) -> CaseResult {
    let (input, expect) = parts(case)?;
    let mut buf = read_file(dir, str_field(input, "file")?)?;
    if has(input, "mutate") {
        let mutate = field(input, "mutate")?;
        let at = usize_field(mutate, "at")?;
        let value = u8::try_from(u64_field(mutate, "value")?)
            .map_err(|_| "manifest: mutate.value is not a byte".to_owned())?;
        let kind = str_field(mutate, "kind")?;
        match kind {
            "xor_byte" | "set_byte" => {
                let byte = buf
                    .get_mut(at)
                    .ok_or_else(|| format!("mutate at {at}: past the end"))?;
                if kind == "xor_byte" {
                    *byte ^= value;
                } else {
                    *byte = value;
                }
            }
            "truncate" => {
                ensure!(at <= buf.len(), "truncate at {at}: past the end");
                buf.truncate(at);
            }
            "append_byte" => buf.push(value),
            other => fail!("unknown mutation {other:?}"),
        }
    }
    let Some(enc) = verdict(expect, Encoding::from_bytes(&buf))? else {
        return Ok(Outcome::Pass);
    };
    let file_size = usize_field(expect, "file_size")?;
    ensure!(
        buf.len() == file_size,
        "file_size: got {}, want {file_size}",
        buf.len()
    );
    let want = str_field(expect, "state_id")?;
    let got = hex(&enc.state_id());
    ensure!(got == want, "state_id: got {got}, want {want}");
    let n = usize_field(expect, "n")?;
    ensure!(enc.len() == n, "n: got {}, want {n}", enc.len());
    let id_kind = str_field(expect, "id_kind")?;
    ensure!(
        enc.id_kind().name() == id_kind,
        "id_kind: got {}, want {id_kind}",
        enc.id_kind()
    );
    ensure!(
        enc.to_bytes() == buf,
        "round trip: to_bytes() differs from the file"
    );
    Ok(Outcome::Pass)
}

fn vector_10(dir: &Path, case: &Value) -> CaseResult {
    let (input, expect) = parts(case)?;
    let parts: Vec<Encoding> = strings(array_field(input, "files")?)?
        .iter()
        .map(|name| load(dir, name))
        .collect::<Result<_, _>>()?;
    let (first, rest) = parts
        .split_first()
        .ok_or_else(|| "manifest: files is empty".to_owned())?;
    let others: Vec<&Encoding> = rest.iter().collect();
    let Some(result) = verdict(expect, first.concat(&others))? else {
        return Ok(Outcome::Pass);
    };
    let want = str_field(expect, "state_id")?;
    let got = hex(&result.state_id());
    ensure!(got == want, "state_id: got {got}, want {want}");
    let n = usize_field(expect, "n")?;
    ensure!(result.len() == n, "n: got {}, want {n}", result.len());
    Ok(Outcome::Pass)
}

fn vector_11(dir: &Path, case: &Value) -> CaseResult {
    let (input, expect) = parts(case)?;
    let reference = load(dir, str_field(input, "reference")?)?;
    let candidate = load(dir, str_field(input, "candidate")?)?;
    let Some(diff) = verdict(expect, reference.diff(&candidate))? else {
        return Ok(Outcome::Pass);
    };
    assert_report(&diff, field(expect, "report")?)?;
    if let Some(id) = opt_u64(input, "units_of")? {
        let units = diff.units(&Id::U64(id)).context(format!("units({id})"))?;
        let got: Vec<Value> = units
            .iter()
            .map(|&(unit, reference, candidate)| json!([unit, reference, candidate]))
            .collect();
        let want = array_field(expect, "units")?;
        ensure!(got.as_slice() == want, "units: got {got:?}, want {want:?}");
    }
    Ok(Outcome::Pass)
}

fn vector_12(dir: &Path, case: &Value) -> CaseResult {
    let (input, expect) = parts(case)?;
    if has(input, "floor_json") {
        let bytes = read_file(dir, str_field(input, "floor_json")?)?;
        let Some(floor) = verdict(expect, Floor::from_json(&bytes))? else {
            return Ok(Outcome::Pass);
        };
        assert_floor(&floor, field(expect, "floor")?)?;
        let want = str_field(expect, "json")?;
        ensure!(
            floor.to_json() == want,
            "json:\n got {}\nwant {want}",
            floor.to_json()
        );
        return Ok(Outcome::Pass);
    }
    if has(input, "null_diffs") {
        let diffs = null_diffs(dir, array_field(input, "null_diffs")?)?;
        let Some(floor) = verdict(expect, Floor::measure(&diffs))? else {
            return Ok(Outcome::Pass);
        };
        assert_floor(&floor, field(expect, "floor")?)?;
        for (i, diff) in diffs.iter().enumerate() {
            let within = diff.within(&floor).context(format!("within(null {i})"))?;
            ensure!(within, "null diff {i} is not within its own floor");
        }
        return Ok(Outcome::Pass);
    }
    let diff = diff_files(
        dir,
        str_field(input, "reference")?,
        str_field(input, "candidate")?,
    )?;
    // A floor is validated at construction, so an invalid one is rejected
    // before it is applied.
    let raw = field(input, "floor")?;
    let floor = match floor_of(raw)? {
        Ok(floor) => floor,
        Err(err) => return verdict(expect, Err::<(), _>(err)).map(|_| Outcome::Pass),
    };
    ensure!(
        &floor_value(&floor) == raw,
        "floor does not round-trip: {}",
        floor_value(&floor)
    );
    let per_row = has(input, "per_row") && bool_field(input, "per_row")?;
    let options = GateOptions::new().per_row(per_row);
    let Some(got) = verdict(expect, diff.evaluate(&floor, &options))? else {
        return Ok(Outcome::Pass);
    };
    let got = json!({
        "passed": got.passed(),
        "reasons": got.reasons().iter().map(|r| r.name()).collect::<Vec<_>>(),
        "rows": got.rows().iter().map(|i| i.to_string()).collect::<Vec<_>>(),
    });
    let want = field(expect, "evaluate")?;
    ensure!(&got == want, "evaluate: got {got}, want {want}");
    let within = diff.within(&floor).context("within")?;
    let want = bool_field(expect, "within")?;
    ensure!(within == want, "within: got {within}, want {want}");
    Ok(Outcome::Pass)
}

fn vector_13(dir: &Path, case: &Value) -> CaseResult {
    let (input, expect) = parts(case)?;
    if has(expect, "report") {
        let diff = diff_files(
            dir,
            str_field(input, "reference")?,
            str_field(input, "candidate")?,
        )?;
        assert_report(&diff, field(expect, "report")?)?;
        return Ok(Outcome::Pass);
    }
    let diffs = null_diffs(dir, array_field(input, "null_diffs")?)?;
    let floor = Floor::measure(&diffs).context("measure")?;
    let want = field(expect, "floor")?;
    assert_floor(&floor, want)?;
    // The report form reads back as the same floor.
    let back = floor_of(want)?.context("from_json")?;
    ensure!(back == floor, "from_json: got {back:?}, want {floor:?}");
    Ok(Outcome::Pass)
}

fn vector_15(_dir: &Path, case: &Value) -> CaseResult {
    let (input, expect) = parts(case)?;
    if has(input, "rounding_mode") {
        return Ok(Outcome::Skip(
            "unsupported: Rust cannot set the FP rounding mode".to_owned(),
        ));
    }
    let config = config_of(field(input, "config")?)?;
    let codec = Codec::new(&config).context("codec")?;
    let ids = ids_of(field(input, "ids")?)?;
    let vectors = f32_from_hex(array_field(input, "vectors_f32")?)?;
    let enc = codec.encode(ids.view(), &vectors, None).context("encode")?;
    let want = str_field(expect, "content_digest")?;
    let got = hex(&enc.content_digest());
    ensure!(got == want, "content_digest: got {got}, want {want}");
    Ok(Outcome::Pass)
}

// --------------------------------------------------------------------------
// One test per vector directory
// --------------------------------------------------------------------------

#[test]
fn vector_00_sha256_fips() {
    run_vector("00-sha256-fips", vector_00);
}

#[test]
fn vector_01_config_canonical() {
    run_vector("01-config-canonical", vector_01);
}

#[test]
fn vector_02_config_derived() {
    run_vector("02-config-derived", vector_02);
}

#[test]
fn vector_03_encode() {
    run_vector("03-encode", vector_03);
}

#[test]
fn vector_04_encode_rejects() {
    run_vector("04-encode-rejects", vector_04);
}

#[test]
fn vector_05_decode() {
    run_vector("05-decode", vector_05);
}

#[test]
fn vector_06_ids_canonical() {
    run_vector("06-ids-canonical", vector_06);
}

#[test]
fn vector_07_manifest_canonical() {
    run_vector("07-manifest-canonical", vector_07);
}

#[test]
fn vector_08_digests() {
    run_vector("08-digests", vector_08);
}

#[test]
fn vector_09_file() {
    run_vector("09-file", vector_09);
}

#[test]
fn vector_10_concat() {
    run_vector("10-concat", vector_10);
}

#[test]
fn vector_11_diff() {
    run_vector("11-diff", vector_11);
}

#[test]
fn vector_12_floor() {
    run_vector("12-floor", vector_12);
}

#[test]
fn vector_13_report() {
    run_vector("13-report", vector_13);
}

#[test]
fn vector_15_fp_environment() {
    run_vector("15-fp-environment", vector_15);
}
