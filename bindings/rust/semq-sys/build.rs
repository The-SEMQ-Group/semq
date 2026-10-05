// Copyright (c) 2026 The SEMQ Group Inc.
// Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

//! Link an explicit shared core, or build the bundled C sources statically.
//!
//! Release archives contain `native/`, generated from the single core source
//! tree by tools/package_artifacts.py. Checkout builds may use that source
//! tree directly. Consumers need a C toolchain and CMake, never the checkout
//! or a runtime library path. SEMQ_LIBRARY_PATH/SEMQ_NATIVE_DIR remain explicit
//! shared-library overrides for development and instrumented builds.

use std::path::{Path, PathBuf};

fn main() {
    println!("cargo:rerun-if-env-changed=SEMQ_LIBRARY_PATH");
    println!("cargo:rerun-if-env-changed=SEMQ_NATIVE_DIR");
    let shared = std::env::var_os("SEMQ_LIBRARY_PATH")
        .map(PathBuf::from)
        .map(|p| {
            if p.is_file() {
                p.parent().map(Path::to_path_buf).unwrap_or(p)
            } else {
                p
            }
        })
        .or_else(|| std::env::var_os("SEMQ_NATIVE_DIR").map(PathBuf::from));
    if let Some(dir) = shared {
        println!("cargo:rustc-link-search=native={}", dir.display());
        println!("cargo:rustc-link-lib=dylib=semq");
        // Dependent executables still use the OS loader's library search path.
        return;
    }

    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let bundled = manifest.join("native");
    let source = if bundled.join("CMakeLists.txt").is_file() {
        bundled
    } else {
        let checkout = manifest.join("../../..");
        assert!(
            checkout.join("include/semq.h").is_file(),
            "semq-sys archive lacks its native sources; package with tools/package_artifacts.py"
        );
        checkout
    };
    println!("cargo:rerun-if-changed={}", source.join("src").display());
    println!(
        "cargo:rerun-if-changed={}",
        source.join("include").display()
    );
    println!(
        "cargo:rerun-if-changed={}",
        source.join("CMakeLists.txt").display()
    );
    println!(
        "cargo:rerun-if-changed={}",
        source.join("VERSION").display()
    );
    println!(
        "cargo:rerun-if-changed={}",
        source.join("SOURCE_REVISION").display()
    );
    let dst = cmake::Config::new(source)
        .define("SEMQ_BUILD_TESTS", "OFF")
        .define("SEMQ_BUILD_BENCHMARKS", "OFF")
        .define("SEMQ_ENABLE_SANITIZERS", "OFF")
        .define("CMAKE_INSTALL_LIBDIR", "lib")
        .build();
    println!(
        "cargo:rustc-link-search=native={}",
        dst.join("lib").display()
    );
    let target_os = std::env::var("CARGO_CFG_TARGET_OS").expect("Cargo provides target OS");
    if target_os == "windows" {
        println!("cargo:rustc-link-lib=static=semq_static");
    } else {
        println!("cargo:rustc-link-lib=static=semq");
        println!("cargo:rustc-link-lib=m");
    }
}
