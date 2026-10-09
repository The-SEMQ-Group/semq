# Reader fuzzing

`load.c` exercises the public loaders and requires an exact save/load roundtrip
for accepted images. It also reads every input as floor JSON and requires an
accepted floor to save to a form that reads back and saves to the same bytes. When validation reaches the integrity checks, the harness
repairs both digests and retries to exercise row canonicity behind the footer.
All checks remain active in Release builds.

`fuzz_load_smoke` runs the same harness against every `.semq` conformance image
and every `floor-*.json` conformance file,
every truncation up to 4096 bytes, appended bytes and 1024 deterministic
mutations per image. It runs under `ctest`, including the sanitizer jobs.

The `reader-fuzz` CI job builds **both harness and core** with Clang's libFuzzer,
ASan and UBSan, seeds the corpus from conformance and runs for 60 seconds. It
uploads any reproducer on failure. This bounded PR gate is not an exhaustive
campaign. Longer local campaigns use the same target:

```sh
cmake -S . -B build-fuzz -G Ninja -DCMAKE_C_COMPILER=clang \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo -DSEMQ_BUILD_TESTS=OFF \
  -DSEMQ_BUILD_FUZZ=ON -DSEMQ_ENABLE_SANITIZERS=ON
cmake --build build-fuzz --target fuzz_load
build-fuzz/fuzz_load corpus -max_len=4194304 -rss_limit_mb=1024
```

AppleClang installations without `libclang_rt.fuzzer` can run the deterministic
harness; a Clang distribution including that runtime is required for libFuzzer.
