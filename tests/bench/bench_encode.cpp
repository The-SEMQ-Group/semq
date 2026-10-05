// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

//
// bench_encode.cpp — Google Benchmark suite for the SEMQ core.
//
// Measures the hot paths of the public C ABI on deterministic synthetic
// inputs: encode, decode, unpack, save, load, concat, diff and floor
// measure, per operator (orbit, phase, quant), per kernel backend, at
// representative dimensions and row counts.
//
// Naming. Every benchmark is registered as
//
//     <operation>/<operator>/<backend>/dim:<dim>/rows:<rows>
//
// for example `encode/orbit/avx2/dim:768/rows:100000`, so a JSON report
// (`--benchmark_format=json`) parses by splitting the name on '/'. The
// operations that return a new handle (encode, load, concat, diff,
// floor_measure) time only the call, not the free that follows it, through
// Google Benchmark's manual timing; their names therefore carry the
// framework's `/manual_time` suffix. Every entry reports items_per_second
// (vectors/s), bytes_per_second and a few counters: bytes_per_vector,
// file_bytes (save, load), parts (concat), changed_rows (diff,
// floor_measure) and maxrss_mb (POSIX only; the process-wide peak, so it is
// meaningful only when one benchmark is selected with --benchmark_filter).
//
// Backends. The dispatcher honours SEMQ_FORCE_BACKEND when a codec is
// created (src/core/semq_dispatch.c). The suite sets that variable before
// creating each codec and registers an <operator>/<backend> family only when
// the codec really runs the requested kernel: orbit has scalar, avx2 and
// avx512 kernels on x86-64 and scalar, neon and sve on ARM64, phase has
// scalar and neon, quant has scalar, AVX2 and AVX-512 on x86-64 and scalar
// and NEON on ARM64. A kernel the host lacks is
// left out with a note on stderr. Setting SEMQ_FORCE_BACKEND before launch
// restricts the run to that one backend.
//
// Sizes. Dimensions 384, 768 and 1024 with 1, 1 000 and 100 000 rows by
// default. SEMQ_BENCH_SCALE=1 adds 1 000 000 rows for the state operations
// (save, load, concat, diff, floor_measure). The 1M-row encodings are built
// by encoding 100 000-row chunks with disjoint ids and concatenating them,
// so at most 100 000 × dim float32 values (400 MB at dim 1024) are held as
// input at once; the encodings themselves reach 1 GB each for orbit at
// 1M × 1024, so the scale run wants several GB of RAM.
//
// Inputs are unit-norm rows from a seeded PRNG with ascending u64 ids and no
// manifest; the chunks of a 1M-row encoding repeat the same rows under
// different ids. The diff and floor_measure candidates replace 1 row in 100
// by a different unit-norm row (`changed_rows`); the others stay identical.
//
// Quick check, as CI runs it:
//     bench_encode --benchmark_min_time=0.01s --benchmark_filter='rows:(1|1000)(/|$)'
// Full default run with a JSON report:
//     bench_encode --benchmark_format=json --benchmark_out=bench_encode.json
//

#include <benchmark/benchmark.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#if !defined(_WIN32)
#include <sys/resource.h>
#endif

#include "semq.h"

namespace {

// Operator parameters: the defaults of the Python benchmark adapters
// (benchmarks/codecs.py) and of benchmarks/configs/quality-*.json.
constexpr uint32_t kOrbitScale = 50u;
constexpr uint32_t kPhaseSectors = 16u;
constexpr uint32_t kQuantBins = 4u;

constexpr uint32_t kDims[] = {384u, 768u, 1024u};
constexpr uint64_t kRows[] = {1u, 1000u, 100000u};
constexpr uint64_t kScaleRows = 1000000u;
// Largest number of rows generated (and encoded) at once.
constexpr uint64_t kChunkRows = 100000u;
// Candidate encodings change one row in this many.
constexpr uint64_t kChangeStride = 100u;
constexpr uint64_t kSeed = 0x5EBA5E11C0DEC5ull;
constexpr uint64_t kChangedSalt = 0xC4A17ED0000001ull;

struct Spec {
    semq_operator_t op;
    const char* op_name;
    const char* backend;
    uint32_t dim;
    uint64_t rows;
};

struct Operator {
    semq_operator_t op;
    const char* name;
};

constexpr Operator kOperators[] = {
    {SEMQ_ORBIT, "orbit"},
    {SEMQ_PHASE, "phase"},
    {SEMQ_QUANT, "quant"},
};

[[noreturn]] void Fail(const char* what, semq_status_t status, const semq_error_t& err) {
    std::fprintf(stderr,
                 "[bench] %s failed: %s (row %llu, field %llu): %s\n",
                 what,
                 semq_status_name(static_cast<uint32_t>(status)),
                 static_cast<unsigned long long>(err.row),
                 static_cast<unsigned long long>(err.field),
                 err.message);
    std::abort();
}

void Check(const char* what, semq_status_t status, const semq_error_t& err) {
    if (status != SEMQ_OK) {
        Fail(what, status, err);
    }
}

void SetForcedBackend(const char* name) {
#if defined(_WIN32)
    _putenv_s("SEMQ_FORCE_BACKEND", name);
#else
    setenv("SEMQ_FORCE_BACKEND", name, 1);
#endif
}

struct CodecDeleter {
    void operator()(semq_codec_t* c) const {
        semq_codec_free(c);
    }
};
struct EncodingDeleter {
    void operator()(semq_encoding_t* e) const {
        semq_encoding_free(e);
    }
};
struct DiffDeleter {
    void operator()(semq_diff_t* d) const {
        semq_diff_free(d);
    }
};
using CodecPtr = std::unique_ptr<semq_codec_t, CodecDeleter>;
using EncodingPtr = std::unique_ptr<semq_encoding_t, EncodingDeleter>;
using DiffPtr = std::unique_ptr<semq_diff_t, DiffDeleter>;

semq_config_t MakeConfig(semq_operator_t op, uint32_t dim) {
    semq_config_t cfg{};
    semq_error_t err{};
    switch (op) {
        case SEMQ_ORBIT:
            Check("semq_config_orbit", semq_config_orbit(dim, kOrbitScale, &cfg, &err), err);
            break;
        case SEMQ_PHASE:
            Check("semq_config_phase", semq_config_phase(dim, kPhaseSectors, &cfg, &err), err);
            break;
        case SEMQ_QUANT:
            Check("semq_config_quant", semq_config_quant(dim, kQuantBins, &cfg, &err), err);
            break;
    }
    return cfg;
}

// A codec for `spec` on the requested backend, or nullptr when this host
// does not run that kernel for that operator (the dispatcher resolved the
// forced backend to another one).
CodecPtr MakeCodec(const Spec& spec) {
    SetForcedBackend(spec.backend);
    const semq_config_t cfg = MakeConfig(spec.op, spec.dim);
    semq_codec_t* raw = nullptr;
    semq_error_t err{};
    Check("semq_codec_create", semq_codec_create(&cfg, &raw, &err), err);
    CodecPtr codec(raw);
    if (std::strcmp(semq_codec_backend(codec.get()), spec.backend) != 0) {
        return nullptr;
    }
    return codec;
}

// ---------------------------------------------------------------------------
// Deterministic inputs
// ---------------------------------------------------------------------------

uint64_t SplitMix64(uint64_t& state) {
    uint64_t z = (state += 0x9E3779B97F4A7C15ull);
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ull;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBull;
    return z ^ (z >> 31);
}

// One unit-norm row whose values depend only on `row_seed` and `dim`.
void FillRow(float* row, uint32_t dim, uint64_t row_seed) {
    uint64_t state = row_seed;
    double sum_sq = 0.0;
    for (uint32_t i = 0; i < dim; ++i) {
        // 24 random bits mapped to [-1, 1).
        const uint32_t bits = static_cast<uint32_t>(SplitMix64(state) >> 40);
        const float x = static_cast<float>(bits) * (2.0f / 16777216.0f) - 1.0f;
        row[i] = x;
        sum_sq += static_cast<double>(x) * static_cast<double>(x);
    }
    const double inv = 1.0 / std::sqrt(sum_sq);
    for (uint32_t i = 0; i < dim; ++i) {
        row[i] = static_cast<float>(static_cast<double>(row[i]) * inv);
    }
}

uint64_t RowSeed(uint64_t row, bool changed) {
    return (changed ? (kSeed ^ kChangedSalt) : kSeed) + row * 0x2545F4914F6CDD1Dull;
}

// The base rows [0, rows) of `dim` values, unit-norm, row-major. Only one
// matrix is cached, so consecutive benchmarks with the same shape share it
// and the input never exceeds kChunkRows × dim float32 values.
const std::vector<float>& BaseInput(uint32_t dim, uint64_t rows) {
    static uint32_t cached_dim = 0;
    static uint64_t cached_rows = 0;
    static std::vector<float> cache;
    if (cached_dim != dim || cached_rows != rows) {
        cache.clear();
        cache.shrink_to_fit();
        cache.resize(static_cast<size_t>(rows * dim));
        for (uint64_t r = 0; r < rows; ++r) {
            FillRow(cache.data() + static_cast<size_t>(r * dim), dim, RowSeed(r, false));
        }
        cached_dim = dim;
        cached_rows = rows;
    }
    return cache;
}

std::vector<uint64_t> MakeIds(uint64_t base, uint64_t n) {
    std::vector<uint64_t> ids(static_cast<size_t>(n));
    for (uint64_t i = 0; i < n; ++i) {
        ids[static_cast<size_t>(i)] = base + i;
    }
    return ids;
}

semq_ids_t IdsView(const std::vector<uint64_t>& ids) {
    semq_ids_t view{};
    view.kind = SEMQ_ID_U64;
    view.n = static_cast<uint64_t>(ids.size());
    view.u64 = ids.data();
    return view;
}

uint64_t ChangedRows(uint64_t rows) {
    return (rows + kChangeStride - 1u) / kChangeStride;
}

// ---------------------------------------------------------------------------
// State construction helpers (outside the timed regions)
// ---------------------------------------------------------------------------

EncodingPtr Encode(const semq_codec_t* codec, const semq_ids_t& ids, const float* vectors) {
    semq_encoding_t* raw = nullptr;
    semq_error_t err{};
    Check(
        "semq_codec_encode", semq_codec_encode(codec, &ids, vectors, nullptr, 0u, &raw, &err), err);
    return EncodingPtr(raw);
}

// Rows with ids [base, base + n), n ≤ kChunkRows. In the `changed` variant
// every kChangeStride-th row (counted from id 0) is a different row.
EncodingPtr EncodeSlice(
    const semq_codec_t* codec, uint32_t dim, uint64_t base, uint64_t n, bool changed) {
    const std::vector<float>& input = BaseInput(dim, n);
    const float* vectors = input.data();
    std::vector<float> candidate;
    if (changed) {
        candidate = input;
        for (uint64_t i = 0; i < n; ++i) {
            if ((base + i) % kChangeStride == 0u) {
                FillRow(
                    candidate.data() + static_cast<size_t>(i * dim), dim, RowSeed(base + i, true));
            }
        }
        vectors = candidate.data();
    }
    const std::vector<uint64_t> ids = MakeIds(base, n);
    return Encode(codec, IdsView(ids), vectors);
}

EncodingPtr Concat(const std::vector<EncodingPtr>& parts) {
    std::vector<const semq_encoding_t*> raw;
    raw.reserve(parts.size());
    for (const EncodingPtr& p : parts) {
        raw.push_back(p.get());
    }
    semq_encoding_t* out = nullptr;
    semq_error_t err{};
    Check("semq_encoding_concat",
          semq_encoding_concat(raw.data(), static_cast<uint32_t>(raw.size()), &out, &err),
          err);
    return EncodingPtr(out);
}

// `k` encodings that partition the ids [0, rows) into contiguous slices.
std::vector<EncodingPtr> EncodeParts(
    const semq_codec_t* codec, uint32_t dim, uint64_t rows, uint64_t k, bool changed) {
    std::vector<EncodingPtr> parts;
    parts.reserve(static_cast<size_t>(k));
    const uint64_t per_part = rows / k;
    for (uint64_t p = 0; p < k; ++p) {
        const uint64_t base = p * per_part;
        const uint64_t n = (p + 1u == k) ? rows - base : per_part;
        parts.push_back(EncodeSlice(codec, dim, base, n, changed));
    }
    return parts;
}

// How many parts a concat of `rows` rows uses: one 100 000-row chunk per
// part beyond the chunk size, four parts below it, one for tiny inputs.
uint64_t ConcatParts(uint64_t rows) {
    if (rows > kChunkRows) {
        return (rows + kChunkRows - 1u) / kChunkRows;
    }
    return rows >= 4u ? 4u : 1u;
}

// An encoding of ids [0, rows): a single encode up to kChunkRows rows,
// otherwise the concat of kChunkRows-row chunks.
EncodingPtr BuildEncoding(const semq_codec_t* codec, uint32_t dim, uint64_t rows, bool changed) {
    if (rows <= kChunkRows) {
        return EncodeSlice(codec, dim, 0u, rows, changed);
    }
    return Concat(EncodeParts(codec, dim, rows, ConcatParts(rows), changed));
}

std::vector<uint8_t> SaveImage(const semq_encoding_t* enc) {
    std::vector<uint8_t> image(static_cast<size_t>(semq_encoding_file_size(enc)));
    semq_error_t err{};
    Check("semq_encoding_save",
          semq_encoding_save(enc, image.data(), static_cast<uint64_t>(image.size()), &err),
          err);
    return image;
}

DiffPtr Diff(const semq_encoding_t* reference, const semq_encoding_t* candidate) {
    semq_diff_t* raw = nullptr;
    semq_error_t err{};
    Check("semq_encoding_diff", semq_encoding_diff(reference, candidate, &raw, &err), err);
    return DiffPtr(raw);
}

// ---------------------------------------------------------------------------
// Reporting
// ---------------------------------------------------------------------------

void AddPeakRss(benchmark::State& state) {
#if !defined(_WIN32)
    struct rusage usage {};
    if (getrusage(RUSAGE_SELF, &usage) == 0) {
#if defined(__APPLE__)
        const double mb = static_cast<double>(usage.ru_maxrss) / (1024.0 * 1024.0);
#else
        const double mb = static_cast<double>(usage.ru_maxrss) / 1024.0;
#endif
        state.counters["maxrss_mb"] = benchmark::Counter(mb);
    }
#else
    (void)state;
#endif
}

// items = rows per iteration, bytes = `bytes_per_iter` per iteration.
void Finish(benchmark::State& state,
            const Spec& spec,
            const semq_codec_t* codec,
            uint64_t bytes_per_iter) {
    const int64_t iterations = static_cast<int64_t>(state.iterations());
    state.SetItemsProcessed(iterations * static_cast<int64_t>(spec.rows));
    state.SetBytesProcessed(iterations * static_cast<int64_t>(bytes_per_iter));
    state.counters["bytes_per_vector"] = benchmark::Counter(
        static_cast<double>(semq_config_bytes_per_vector(semq_codec_config(codec))));
    AddPeakRss(state);
}

bool Skip(benchmark::State& state, const CodecPtr& codec) {
    if (codec) {
        return false;
    }
    state.SkipWithMessage("backend unavailable on this host");
    return true;
}

// Seconds between two steady_clock readings, for manual timing.
double Seconds(std::chrono::steady_clock::time_point start,
               std::chrono::steady_clock::time_point end) {
    return std::chrono::duration_cast<std::chrono::duration<double>>(end - start).count();
}

// ---------------------------------------------------------------------------
// Benchmarks
// ---------------------------------------------------------------------------

void BM_Encode(benchmark::State& state, Spec spec) {
    CodecPtr codec = MakeCodec(spec);
    if (Skip(state, codec))
        return;
    const std::vector<float>& input = BaseInput(spec.dim, spec.rows);
    const std::vector<uint64_t> ids = MakeIds(0u, spec.rows);
    const semq_ids_t view = IdsView(ids);
    for (auto _ : state) {
        semq_encoding_t* enc = nullptr;
        semq_error_t err{};
        const auto start = std::chrono::steady_clock::now();
        const semq_status_t s =
            semq_codec_encode(codec.get(), &view, input.data(), nullptr, 0u, &enc, &err);
        const auto end = std::chrono::steady_clock::now();
        Check("semq_codec_encode", s, err);
        benchmark::DoNotOptimize(enc);
        state.SetIterationTime(Seconds(start, end));
        semq_encoding_free(enc);
    }
    Finish(state, spec, codec.get(), spec.rows * spec.dim * sizeof(float));
}

void BM_Decode(benchmark::State& state, Spec spec) {
    CodecPtr codec = MakeCodec(spec);
    if (Skip(state, codec))
        return;
    const EncodingPtr enc = BuildEncoding(codec.get(), spec.dim, spec.rows, false);
    std::vector<float> out(static_cast<size_t>(spec.rows * spec.dim));
    for (auto _ : state) {
        semq_error_t err{};
        Check(
            "semq_codec_decode", semq_codec_decode(codec.get(), enc.get(), out.data(), &err), err);
        benchmark::DoNotOptimize(out.data());
        benchmark::ClobberMemory();
    }
    Finish(state, spec, codec.get(), spec.rows * spec.dim * sizeof(float));
}

void BM_Unpack(benchmark::State& state, Spec spec) {
    CodecPtr codec = MakeCodec(spec);
    if (Skip(state, codec))
        return;
    const EncodingPtr enc = BuildEncoding(codec.get(), spec.dim, spec.rows, false);
    const uint64_t units = semq_config_units_per_row(semq_codec_config(codec.get()));
    std::vector<uint8_t> out(static_cast<size_t>(spec.rows * units));
    for (auto _ : state) {
        semq_error_t err{};
        Check(
            "semq_codec_unpack", semq_codec_unpack(codec.get(), enc.get(), out.data(), &err), err);
        benchmark::DoNotOptimize(out.data());
        benchmark::ClobberMemory();
    }
    Finish(state, spec, codec.get(), spec.rows * units);
}

void BM_Save(benchmark::State& state, Spec spec) {
    CodecPtr codec = MakeCodec(spec);
    if (Skip(state, codec))
        return;
    const EncodingPtr enc = BuildEncoding(codec.get(), spec.dim, spec.rows, false);
    const uint64_t size = semq_encoding_file_size(enc.get());
    std::vector<uint8_t> out(static_cast<size_t>(size));
    for (auto _ : state) {
        semq_error_t err{};
        Check("semq_encoding_save", semq_encoding_save(enc.get(), out.data(), size, &err), err);
        benchmark::DoNotOptimize(out.data());
        benchmark::ClobberMemory();
    }
    state.counters["file_bytes"] = benchmark::Counter(static_cast<double>(size));
    Finish(state, spec, codec.get(), size);
}

void BM_Load(benchmark::State& state, Spec spec) {
    CodecPtr codec = MakeCodec(spec);
    if (Skip(state, codec))
        return;
    const std::vector<uint8_t> image =
        SaveImage(BuildEncoding(codec.get(), spec.dim, spec.rows, false).get());
    const uint64_t size = static_cast<uint64_t>(image.size());
    for (auto _ : state) {
        semq_encoding_t* enc = nullptr;
        semq_error_t err{};
        const auto start = std::chrono::steady_clock::now();
        const semq_status_t s = semq_encoding_load(image.data(), size, &enc, &err);
        const auto end = std::chrono::steady_clock::now();
        Check("semq_encoding_load", s, err);
        benchmark::DoNotOptimize(enc);
        state.SetIterationTime(Seconds(start, end));
        semq_encoding_free(enc);
    }
    state.counters["file_bytes"] = benchmark::Counter(static_cast<double>(size));
    Finish(state, spec, codec.get(), size);
}

void BM_Concat(benchmark::State& state, Spec spec) {
    CodecPtr codec = MakeCodec(spec);
    if (Skip(state, codec))
        return;
    const uint64_t k = ConcatParts(spec.rows);
    const std::vector<EncodingPtr> parts = EncodeParts(codec.get(), spec.dim, spec.rows, k, false);
    std::vector<const semq_encoding_t*> raw;
    for (const EncodingPtr& p : parts) {
        raw.push_back(p.get());
    }
    for (auto _ : state) {
        semq_encoding_t* enc = nullptr;
        semq_error_t err{};
        const auto start = std::chrono::steady_clock::now();
        const semq_status_t s =
            semq_encoding_concat(raw.data(), static_cast<uint32_t>(raw.size()), &enc, &err);
        const auto end = std::chrono::steady_clock::now();
        Check("semq_encoding_concat", s, err);
        benchmark::DoNotOptimize(enc);
        state.SetIterationTime(Seconds(start, end));
        semq_encoding_free(enc);
    }
    state.counters["parts"] = benchmark::Counter(static_cast<double>(k));
    const uint64_t bpv = semq_config_bytes_per_vector(semq_codec_config(codec.get()));
    Finish(state, spec, codec.get(), spec.rows * bpv);
}

void BM_Diff(benchmark::State& state, Spec spec) {
    CodecPtr codec = MakeCodec(spec);
    if (Skip(state, codec))
        return;
    const EncodingPtr reference = BuildEncoding(codec.get(), spec.dim, spec.rows, false);
    const EncodingPtr candidate = BuildEncoding(codec.get(), spec.dim, spec.rows, true);
    for (auto _ : state) {
        semq_diff_t* diff = nullptr;
        semq_error_t err{};
        const auto start = std::chrono::steady_clock::now();
        const semq_status_t s = semq_encoding_diff(reference.get(), candidate.get(), &diff, &err);
        const auto end = std::chrono::steady_clock::now();
        Check("semq_encoding_diff", s, err);
        benchmark::DoNotOptimize(diff);
        state.SetIterationTime(Seconds(start, end));
        semq_diff_free(diff);
    }
    state.counters["changed_rows"] =
        benchmark::Counter(static_cast<double>(ChangedRows(spec.rows)));
    const uint64_t bpv = semq_config_bytes_per_vector(semq_codec_config(codec.get()));
    Finish(state, spec, codec.get(), 2u * spec.rows * bpv);
}

void BM_FloorMeasure(benchmark::State& state, Spec spec) {
    CodecPtr codec = MakeCodec(spec);
    if (Skip(state, codec))
        return;
    const EncodingPtr reference = BuildEncoding(codec.get(), spec.dim, spec.rows, false);
    const EncodingPtr candidate = BuildEncoding(codec.get(), spec.dim, spec.rows, true);
    const DiffPtr null_diff = Diff(reference.get(), candidate.get());
    const semq_diff_t* nulls[1] = {null_diff.get()};
    for (auto _ : state) {
        semq_floor_t* floor = nullptr;
        semq_error_t err{};
        const auto start = std::chrono::steady_clock::now();
        const semq_status_t s = semq_floor_measure(nulls, 1u, &floor, &err);
        const auto end = std::chrono::steady_clock::now();
        Check("semq_floor_measure", s, err);
        benchmark::DoNotOptimize(floor);
        state.SetIterationTime(Seconds(start, end));
        semq_floor_free(floor);
    }
    state.counters["nulls"] = benchmark::Counter(1.0);
    state.counters["changed_rows"] =
        benchmark::Counter(static_cast<double>(ChangedRows(spec.rows)));
    const uint64_t bpv = semq_config_bytes_per_vector(semq_codec_config(codec.get()));
    Finish(state, spec, codec.get(), 2u * spec.rows * bpv);
}

// ---------------------------------------------------------------------------
// Registration
// ---------------------------------------------------------------------------

using BenchFn = void (*)(benchmark::State&, Spec);

struct Operation {
    const char* name;
    BenchFn fn;
    bool manual_time;  // the timed region excludes the free of the result
    bool at_scale;     // also registered at kScaleRows when SEMQ_BENCH_SCALE is set
};

constexpr Operation kOperations[] = {
    {"encode", BM_Encode, true, false},
    {"decode", BM_Decode, false, false},
    {"unpack", BM_Unpack, false, false},
    {"save", BM_Save, false, true},
    {"load", BM_Load, true, true},
    {"concat", BM_Concat, true, true},
    {"diff", BM_Diff, true, true},
    {"floor_measure", BM_FloorMeasure, true, true},
};

void Register(const Operation& operation, const Spec& spec) {
    const std::string name = std::string(operation.name) + "/" + spec.op_name + "/" + spec.backend +
                             "/dim:" + std::to_string(spec.dim) +
                             "/rows:" + std::to_string(spec.rows);
    benchmark::internal::Benchmark* b = benchmark::RegisterBenchmark(name, operation.fn, spec);
    if (operation.manual_time) {
        b->UseManualTime();
    }
}

// Backends the dispatcher can be asked for on this architecture. A preset
// SEMQ_FORCE_BACKEND restricts the run to that one.
std::vector<std::string> CandidateBackends() {
    const char* preset = std::getenv("SEMQ_FORCE_BACKEND");
    if (preset != nullptr && *preset != '\0') {
        return {preset};
    }
#if defined(__x86_64__) || defined(_M_X64)
    return {"scalar", "avx2", "avx512"};
#elif defined(__aarch64__) || defined(_M_ARM64)
    return {"scalar", "neon", "sve"};
#else
    return {"scalar"};
#endif
}

bool ScaleEnabled() {
    const char* v = std::getenv("SEMQ_BENCH_SCALE");
    return v != nullptr && *v != '\0' && std::strcmp(v, "0") != 0;
}

}  // namespace

int main(int argc, char** argv) {
    benchmark::Initialize(&argc, argv);
    if (benchmark::ReportUnrecognizedArguments(argc, argv))
        return 1;

    benchmark::AddCustomContext("semq_core_version", semq_core_version());
    benchmark::AddCustomContext("semq_build_id", semq_build_id());
    std::fprintf(stderr, "[bench] semq %s, build %s\n", semq_core_version(), semq_build_id());

    const bool scale = ScaleEnabled();
    const std::vector<std::string> backends = CandidateBackends();

    for (const Operator& op : kOperators) {
        for (const std::string& backend : backends) {
            // Probe once: the kernel an operator runs under this forced
            // backend. Phase has no x86 kernels, so its family exists
            // only as <op>/scalar there.
            const Spec probe{op.op, op.name, backend.c_str(), 64u, 0u};
            if (!MakeCodec(probe)) {
                std::fprintf(stderr,
                             "[bench] %s/%s: not a distinct kernel on this host, skipped\n",
                             op.name,
                             backend.c_str());
                continue;
            }
            for (const uint32_t dim : kDims) {
                for (const uint64_t rows : kRows) {
                    for (const Operation& operation : kOperations) {
                        Register(operation, Spec{op.op, op.name, backend.c_str(), dim, rows});
                    }
                }
                if (scale) {
                    for (const Operation& operation : kOperations) {
                        if (operation.at_scale) {
                            Register(operation,
                                     Spec{op.op, op.name, backend.c_str(), dim, kScaleRows});
                        }
                    }
                }
            }
        }
    }

    benchmark::RunSpecifiedBenchmarks();
    benchmark::Shutdown();
    return 0;
}
