#!/usr/bin/env python3
# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.
"""Check the FFI mirrors against semq.h and layouts emitted by the C compiler.

No parser runs in a consumer installation. The small declaration grammar is
closed: unfamiliar header syntax is an error, never silently skipped.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def clean(text: str) -> str:
    return re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)


def declaration(text: str, parameter: bool = False) -> tuple[str, str]:
    match = re.fullmatch(r"\s*(.*?)\b(\w+)\s*(?:\[(\d+)\])?\s*", text, re.S)
    if not match or not match[1].strip():
        raise ValueError(f"unsupported C declaration: {text}")
    typ = " ".join(re.findall(r"\w+|\*", match[1]))
    if match[3]:
        typ += " *" if parameter else f" [{match[3]}]"
    return match[2], typ


def declarations(text: str) -> tuple[dict, dict]:
    structs = {}
    for body, name in re.findall(r"typedef\s+struct\s*\{(.*?)\}\s*(\w+)\s*;", text, re.S):
        structs[name] = [declaration(f) for f in body.split(";") if f.strip()]
    functions = {}
    for ret, name, args in re.findall(r"([\w\s*]+?)\b(semq_\w+)\s*\(([^()]*)\)\s*;", text):
        ret = " ".join(ret.replace("SEMQ_API", "").split())
        # Only function lines are admitted; typedefs cannot match this form.
        ret = " ".join(re.findall(r"\w+|\*", ret))
        params = [] if args.strip() in ("", "void") else [declaration(a, True)[1] for a in args.split(",")]
        functions[name] = (ret, params)
    return structs, functions


def header() -> tuple[str, dict, dict, list[str]]:
    text = clean((ROOT / "include/semq.h").read_text(encoding="utf-8"))
    structs, functions = declarations(text)
    assert len(functions) == len(re.findall(r"^SEMQ_API\b", text, re.M)), "unparsed ABI function"
    constants = re.findall(r"\b(SEMQ_\w+)\s*=", text)
    constants += re.findall(r"^#define (SEMQ_\w+) (?!__)(.+)$", text, re.M)
    constants = [v[0] if isinstance(v, tuple) else v for v in constants]
    return text, structs, functions, constants


def c_probe(structs: dict, constants: list[str]) -> str:
    body = ['/*', ' * Copyright (c) 2026 The SEMQ Group Inc.',
            ' * Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.', ' */', '',
            '/* Generated from semq.h by tools/check_abi.py; do not edit. */',
            '#include "semq.h"', '#include <stdio.h>', 'int main(void) {']
    values = {"pointer.size": "sizeof(void*)"}
    for typ, fields in structs.items():
        values[typ + ".size"] = f"sizeof({typ})"
        values[typ + ".align"] = f"_Alignof({typ})"
        values.update({f"{typ}.{name}": f"offsetof({typ}, {name})" for name, _ in fields})
    values["semq_status_t.size"] = "sizeof(semq_status_t)"
    values["semq_status_t.align"] = "_Alignof(semq_status_t)"
    values.update({name: name for name in constants})
    for name, expr in values.items():
        body.append(f'    printf("{name}=%llu\\n", (unsigned long long)({expr}));')
    return "\n".join(body + ['    return 0;', '}', ''])


def result(command: list[str]) -> dict[str, int]:
    out = subprocess.check_output(command, text=True)
    return {key: int(value) for line in out.splitlines() for key, value in [line.split("=")]}


def rust_type(typ: str) -> str:
    array = re.search(r" \[(\d+)\]$", typ)
    if array:
        return f"[{rust_type(typ[:array.start()])}; {array[1]}]"
    parts = typ.split("*")
    base = parts[0].split()
    const = "const" in base
    base = [v for v in base if v != "const"]
    assert len(base) == 1, typ
    t = {"uint8_t": "u8", "uint32_t": "u32", "uint64_t": "u64", "char": "c_char", "int": "c_int", "float": "f32", "void": "()"}.get(base[0], base[0])
    for qualifiers in parts[1:]:
        t = ("*const " if const else "*mut ") + t
        assert qualifiers.strip() in ("", "const"), typ
        const = "const" in qualifiers
    return t


def check_rust(structs: dict, functions: dict, source: str) -> None:
    text = clean(source)
    actual = {}
    for name, args, ret in re.findall(r"pub fn (\w+)\((.*?)\)\s*(?:->\s*([^;]+))?;", text, re.S):
        params = [a.split(":", 1)[1] for a in args.split(",") if a.strip()]
        actual[name] = (ret or "()", params)
    def squash(t: str) -> str:
        return re.sub(r"\s+", "", t)

    def normalize(f: tuple[str, list[str]]) -> tuple[str, list[str]]:
        return squash(f[0]), [squash(p) for p in f[1]]

    expected = {n: (rust_type(ret), [rust_type(p) for p in args]) for n, (ret, args) in functions.items()}
    assert {n: normalize(v) for n, v in actual.items()} == {n: normalize(v) for n, v in expected.items()}, "Rust function signatures drifted from semq.h"
    for typ, fields in structs.items():
        body = re.search(r"pub struct " + typ + r"\s*\{(.*?)\}", text, re.S)
        assert body, typ
        actual_fields = [(n, squash(t)) for n, t in re.findall(r"pub (\w+): ([^,]+),", body[1])]
        assert actual_fields == [(n, squash(rust_type(t))) for n, t in fields], f"Rust fields: {typ}"


def check_ts(functions: dict, source: str, cmake: str) -> None:
    text = clean(source)
    actual = {n: (ret, re.findall(r":\s*(\w+)", args)) for n, args, ret in re.findall(r"(\w+):\s*\(([^()]*)\)\s*=>\s*(\w+);", text)}
    bound = re.findall(r'(\w+):\s*(num|big|str|nil)\("(semq_\w+)"\)', text)
    assert len(bound) == len(functions) == len(actual), "TS function inventory"
    def host(t: str) -> str:
        return {"void": "void", "const char *": "string", "uint64_t": "bigint"}.get(t, "number")
    for local, wrapper, name in bound:
        ret, args = functions[name]
        assert actual[local] == (host(ret), [host(a) for a in args]), f"TS signature: {name}"
        assert wrapper == {"void": "nil", "string": "str", "bigint": "big", "number": "num"}[host(ret)], f"TS return adapter: {name}"
    exports = re.search(r'"-sEXPORTED_FUNCTIONS=([^"\n]+)"', cmake)
    assert exports, "WASM export list missing"
    assert set(exports[1].split(",")) == {"_malloc", "_free"} | {"_" + n for n in functions}, "WASM export list drifted"


def check_python(structs: dict, functions: dict, source: str) -> str:
    assignments = [n for n in ast.parse(source).body if isinstance(n, ast.Assign)]
    cdef = next(ast.literal_eval(n.value) for n in assignments if any(isinstance(t, ast.Name) and t.id == "_CDEF" for t in n.targets))
    actual_structs, actual_funcs = declarations(clean(cdef))
    assert actual_structs == structs, "Python POD fields drifted from semq.h"
    assert actual_funcs == functions, "Python function signatures drifted from semq.h"
    return cdef


def rust_probe(structs: dict, constants: list[str]) -> str:
    path = (ROOT / "bindings/rust/semq-sys/src/lib.rs").as_posix()
    lines = [f'#[path = "{path}"] #[allow(dead_code)] mod sys;', 'use std::mem::{size_of, align_of, offset_of};', 'fn main() {']
    for typ, fields in structs.items():
        for key, expression in [("size", f"size_of::<sys::{typ}>()"), ("align", f"align_of::<sys::{typ}>()")]:
            lines.append(f'println!("{typ}.{key}={{}}", {expression});')
        for name, _ in fields:
            lines.append(f'println!("{typ}.{name}={{}}", offset_of!(sys::{typ}, {name}));')
    lines.append('println!("semq_status_t.size={}", size_of::<sys::semq_status_t>());')
    lines.append('println!("semq_status_t.align={}", align_of::<sys::semq_status_t>());')
    for name in constants:
        lines.append(f'println!("{name}={{}}", sys::{name});')
    return "\n".join(lines + ['}'])


def ts_layout(values: dict[str, int], structs: dict) -> str:
    obj = {typ.removeprefix("semq_").removesuffix("_t"): {key.split(".", 1)[1]: value for key, value in values.items() if key.startswith(typ + ".")} for typ in structs}
    obj["constants"] = {k: v for k, v in values.items() if k.startswith("SEMQ_") and k != "SEMQ_NONE"}
    return '// Generated from the wasm32 C compiler by tools/check_abi.py --write-layout.\nexport const ABI = ' + json.dumps(obj, indent=2) + ' as const;\n'


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", type=Path, help="compiled native semq_abi executable")
    parser.add_argument("--wasm-probe", type=Path, help="compiled wasm32 semq_abi.js")
    parser.add_argument("--write-probe", action="store_true")
    parser.add_argument("--write-layout", action="store_true")
    parser.add_argument("--rust", action="store_true", help="compile and run Rust POD layout probe")
    args = parser.parse_args()
    _, structs, functions, constants = header()
    probe = ROOT / "tests/abi/layout.c"
    generated = c_probe(structs, constants)
    if args.write_probe:
        probe.parent.mkdir(exist_ok=True)
        probe.write_text(generated, encoding="utf-8")
    assert probe.read_text(encoding="utf-8") == generated, "regenerate C layout probe with --write-probe"
    cdef = check_python(structs, functions, (ROOT / "bindings/python/semq/_ffi.py").read_text(encoding="utf-8"))
    check_rust(structs, functions, (ROOT / "bindings/rust/semq-sys/src/lib.rs").read_text(encoding="utf-8"))
    check_ts(functions, (ROOT / "bindings/ts/src/native.ts").read_text(encoding="utf-8"), (ROOT / "CMakeLists.txt").read_text(encoding="utf-8"))
    if args.probe:
        from cffi import FFI
        values = result([str(args.probe.resolve())])
        for filename in ["_ffi.py", "config.py"]:
            tree = ast.parse((ROOT / "bindings/python/semq" / filename).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, int):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and "SEMQ_" + target.id in values:
                            assert node.value.value == values["SEMQ_" + target.id], target.id
        ffi = FFI()
        ffi.cdef(cdef)
        for typ, fields in structs.items():
            assert ffi.sizeof(typ) == values[typ + ".size"], typ
            assert ffi.alignof(typ) == values[typ + ".align"], typ
            for name, _ in fields:
                assert ffi.offsetof(typ, name) == values[typ + "." + name], (typ, name)
        if args.rust:
            with tempfile.TemporaryDirectory(prefix="semq-abi-") as tmp:
                source = Path(tmp) / "probe.rs"
                source.write_text(rust_probe(structs, constants), encoding="utf-8")
                exe = Path(tmp) / ("probe.exe" if os.name == "nt" else "probe")
                subprocess.run(["rustc", "--edition=2021", str(source), "-o", str(exe)], check=True)
                for key, value in result([str(exe)]).items():
                    assert value == values[key], f"Rust layout/value: {key}"
        print("Native layouts: C compiler == cffi" + (" == Rust" if args.rust else ""))
    if args.wasm_probe:
        values = result(["node", str(args.wasm_probe.resolve())])
        assert values["pointer.size"] == 4, "not a wasm32 probe"
        layout = ROOT / "bindings/ts/src/layout.ts"
        expected = ts_layout(values, structs)
        if args.write_layout:
            layout.write_text(expected, encoding="utf-8")
        assert layout.read_text(encoding="utf-8") == expected, "TypeScript layouts differ from wasm32 C compiler"
        print("WASM layouts: C compiler == TypeScript")
    print(f"ABI signatures, fields and exports match semq.h: {len(functions)} functions, {len(structs)} PODs")


if __name__ == "__main__":
    main()
