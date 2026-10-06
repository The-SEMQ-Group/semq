# Copyright (c) 2026 The SEMQ Group Inc.
# Licensed under the PolyForm Noncommercial License 1.0.0. See LICENSE.md for terms.

"""Independent reference for the vectors that do not depend on the kernels.

Pure Python (hashlib, struct, sorting, no binding). It recomputes canonical
forms, identities, file images, concat, diff and floor from the inputs, so
the core never verifies itself on those contracts. Run it against a
generated vector directory:

    python tests/conformance/reference.py tests/conformance

Exit status is non-zero on the first disagreement.
"""

from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path
from typing import Any

OPERATORS = {"orbit": 0, "phase": 1, "quant": 2}
PARAMETER = {"orbit": "scale", "phase": "sectors", "quant": "bins"}
VERSION = 2


# ---------------------------------------------------------------------------
# Canonical forms
# ---------------------------------------------------------------------------


def config_bytes(operator: str, dim: int, p1: int) -> bytes:
    return struct.pack("<BIII", OPERATORS[operator], dim, p1, 0)


def config_valid(operator: str, dim: int, p1: int) -> int | None:
    """None when valid, else the field index (0 operator, 1 dim, 2 p1)."""
    if operator not in OPERATORS:
        return 0
    if not 1 <= dim <= 65536:
        return 1
    if operator == "orbit" and not 1 <= p1 <= 2**30:
        return 2
    if operator == "phase":
        if not 2 <= p1 <= 256:
            return 2
        if dim % 2 or (p1 <= 16 and dim % 4):
            return 1
    if operator == "quant" and not 2 <= p1 <= 64:
        return 2
    return None


def bits_per_unit(operator: str, p1: int) -> int:
    if operator == "orbit":
        return 8
    if operator == "phase":
        return 4 if p1 <= 16 else 8
    return (2 * p1 - 1).bit_length()


def units_per_row(operator: str, dim: int) -> int:
    return dim // 2 if operator == "phase" else dim


def bytes_per_vector(operator: str, dim: int, p1: int) -> int:
    if operator == "orbit":
        return dim
    if operator == "phase":
        return dim // 4 if p1 <= 16 else dim // 2
    return (dim * bits_per_unit(operator, p1) + 7) // 8


def unpack_row(operator: str, dim: int, p1: int, row: bytes) -> list[int]:
    units = units_per_row(operator, dim)
    if operator == "orbit" or (operator == "phase" and p1 > 16):
        return list(row[:units])
    if operator == "phase":
        return [(row[u >> 1] >> (4 * (u & 1))) & 0x0F for u in range(units)]
    bits = bits_per_unit(operator, p1)
    value = int.from_bytes(row, "little")
    return [(value >> (u * bits)) & ((1 << bits) - 1) for u in range(units)]


def _raw(i: Any) -> bytes:
    return i.encode("utf-8") if isinstance(i, str) else i


def ids_section(kind: str, ids: list[Any]) -> bytes:
    if kind == "u64":
        return b"".join(struct.pack("<Q", i) for i in ids)
    blobs = [_raw(i) for i in ids]
    offsets = [0]
    for b in blobs:
        offsets.append(offsets[-1] + len(b))
    return b"".join(struct.pack("<Q", o) for o in offsets) + b"".join(blobs)


def sort_ids(kind: str, ids: list[Any]) -> list[Any]:
    if kind == "u64":
        return sorted(ids)
    return sorted(ids, key=_raw)


def manifest_section(pairs: dict[str, str]) -> bytes:
    out = struct.pack("<I", len(pairs))
    for key in sorted(pairs, key=lambda k: k.encode("utf-8")):
        kb, vb = key.encode("utf-8"), pairs[key].encode("utf-8")
        out += struct.pack("<I", len(kb)) + kb + struct.pack("<I", len(vb)) + vb
    return out


def identities(cfg: bytes, kind: str, ids: list[Any], rows: list[bytes], manifest: dict[str, str]) -> tuple[bytes, bytes]:
    order = sorted(range(len(ids)), key=lambda i: (ids[i] if kind == "u64" else _raw(ids[i])))
    s = cfg + bytes([0 if kind == "u64" else 1]) + struct.pack("<Q", len(ids))
    s += ids_section(kind, [ids[i] for i in order]) + b"".join(rows[i] for i in order)
    content = hashlib.sha256(s).digest()
    state = hashlib.sha256(content + manifest_section(manifest)).digest()
    return content, state


# ---------------------------------------------------------------------------
# File image (reader with the same order as the core, writer)
# ---------------------------------------------------------------------------


class Image:
    def __init__(self, operator: str, dim: int, p1: int, kind: str, ids: list[Any], rows: list[bytes], manifest: dict[str, str]):
        self.operator, self.dim, self.p1, self.kind = operator, dim, p1, kind
        self.ids, self.rows, self.manifest = ids, rows, manifest

    @property
    def config(self) -> bytes:
        return config_bytes(self.operator, self.dim, self.p1)

    def digests(self) -> tuple[bytes, bytes]:
        return identities(self.config, self.kind, self.ids, self.rows, self.manifest)

    def to_bytes(self) -> bytes:
        content, state = self.digests()
        body = self.config + bytes([0 if self.kind == "u64" else 1]) + struct.pack("<Q", len(self.ids))
        body += ids_section(self.kind, self.ids) + b"".join(self.rows) + manifest_section(self.manifest)
        return b"SEMQ" + struct.pack("<H", VERSION) + body + content + state


def parse(buf: bytes) -> Image:
    """Parse an image with the reader rules; raise ValueError with the failing check."""
    try:
        return _parse(buf)
    except (struct.error, IndexError) as exc:
        raise ValueError(f"structure: {exc}") from exc


def _parse(buf: bytes) -> Image:
    if len(buf) < 28 + 4 + 64:
        raise ValueError("framing: too short")
    if buf[:4] != b"SEMQ":
        raise ValueError("framing: magic")
    if struct.unpack_from("<H", buf, 4)[0] != VERSION:
        raise ValueError("framing: version")
    op, dim, p1, p2 = struct.unpack_from("<BIII", buf, 6)
    operator = {v: k for k, v in OPERATORS.items()}.get(op)
    if operator is None or p2 != 0 or config_valid(operator, dim, p1) is not None:
        raise ValueError("config")
    kind_byte, n = struct.unpack_from("<BQ", buf, 19)
    if kind_byte not in (0, 1):
        raise ValueError("sizes: kind")
    kind = "u64" if kind_byte == 0 else "utf8"
    bpv = bytes_per_vector(operator, dim, p1)
    body = len(buf) - 28 - 64
    if kind == "u64":
        ids_len = n * 8
    else:
        if (n + 1) * 8 > body:
            raise ValueError("sizes: offsets")
        ids_len = (n + 1) * 8 + struct.unpack_from("<Q", buf, 28 + n * 8)[0]
    rows_len = n * bpv
    if ids_len + rows_len > body:
        raise ValueError("sizes: sections")
    man_len = body - ids_len - rows_len
    if man_len < 4 or man_len > 16 * 1024 * 1024:
        raise ValueError("sizes: manifest")
    ids_p, rows_p, man_p = 28, 28 + ids_len, 28 + ids_len + rows_len
    foot_p = man_p + man_len
    ids: list[Any] = []
    if kind == "u64":
        ids = [struct.unpack_from("<Q", buf, ids_p + 8 * i)[0] for i in range(n)]
        if any(ids[i - 1] >= ids[i] for i in range(1, n)):
            raise ValueError("ids: order")
    else:
        offsets = [struct.unpack_from("<Q", buf, ids_p + 8 * i)[0] for i in range(n + 1)]
        base = ids_p + (n + 1) * 8
        total = ids_len - (n + 1) * 8
        if offsets[0] != 0 or (n == 0 and total != 0):
            raise ValueError("ids: offsets")
        prev = None
        for i in range(n):
            a, b = offsets[i], offsets[i + 1]
            if b <= a or b > total or b - a > 4096:
                raise ValueError("ids: offsets")
            raw = buf[base + a : base + b]
            try:
                raw.decode("utf-8", "strict")
            except UnicodeDecodeError as exc:
                raise ValueError("ids: utf8") from exc
            if b"\x00" in raw or "\ud800" <= raw.decode("utf-8") <= "\udfff":
                raise ValueError("ids: utf8")
            if prev is not None and prev >= raw:
                raise ValueError("ids: order")
            prev = raw
            ids.append(raw)
    manifest: dict[str, str] = {}
    pos = man_p
    n_pairs = struct.unpack_from("<I", buf, pos)[0]
    pos += 4
    if n_pairs > 4096:
        raise ValueError("manifest: pairs")
    prev_key = None
    for _ in range(n_pairs):
        klen = struct.unpack_from("<I", buf, pos)[0]
        pos += 4
        key = buf[pos : pos + klen]
        pos += klen
        vlen = struct.unpack_from("<I", buf, pos)[0]
        pos += 4
        value = buf[pos : pos + vlen]
        pos += vlen
        if not 1 <= klen <= 256 or vlen > 65536 or pos > foot_p:
            raise ValueError("manifest: lengths")
        if prev_key is not None and prev_key >= key:
            raise ValueError("manifest: order")
        prev_key = key
        manifest[key.decode("utf-8")] = value.decode("utf-8")
    if pos != foot_p:
        raise ValueError("manifest: trailing")
    content = hashlib.sha256(buf[6:man_p]).digest()
    if content != buf[foot_p : foot_p + 32]:
        raise ValueError("integrity: content")
    state = hashlib.sha256(content + buf[man_p:foot_p]).digest()
    if state != buf[foot_p + 32 : foot_p + 64]:
        raise ValueError("integrity: state")
    rows = [buf[rows_p + i * bpv : rows_p + (i + 1) * bpv] for i in range(n)]
    alphabet = 19 if operator == "orbit" else (p1 if operator == "phase" else 2 * p1)
    for i, row in enumerate(rows):
        if any(s >= alphabet for s in unpack_row(operator, dim, p1, row)):
            raise ValueError(f"rows: symbol row {i}")
        if operator == "quant":
            used = dim * bits_per_unit(operator, p1)
            if int.from_bytes(row, "little") >> used:
                raise ValueError(f"rows: padding row {i}")
    return Image(operator, dim, p1, kind, list(ids), rows, manifest)


# ---------------------------------------------------------------------------
# diff and floor
# ---------------------------------------------------------------------------


def diff(ref: Image, cand: Image) -> dict[str, Any]:
    assert ref.config == cand.config and ref.kind == cand.kind
    r = {ref.ids[i]: ref.rows[i] for i in range(len(ref.ids))}
    c = {cand.ids[i]: cand.rows[i] for i in range(len(cand.ids))}
    added = sort_ids(ref.kind, [i for i in c if i not in r])
    removed = sort_ids(ref.kind, [i for i in r if i not in c])
    changed, unchanged = [], 0
    for i in sort_ids(ref.kind, [i for i in r if i in c]):
        if r[i] == c[i]:
            unchanged += 1
        else:
            a = unpack_row(ref.operator, ref.dim, ref.p1, r[i])
            b = unpack_row(ref.operator, ref.dim, ref.p1, c[i])
            changed.append((i, sum(x != y for x, y in zip(a, b, strict=True))))
    keys = sorted(set(ref.manifest) | set(cand.manifest), key=lambda k: k.encode("utf-8"))
    mchanges = {k: [ref.manifest.get(k), cand.manifest.get(k)] for k in keys if ref.manifest.get(k) != cand.manifest.get(k)}
    render = (lambda i: str(i)) if ref.kind == "u64" else (lambda i: _raw(i).decode("utf-8"))
    return {
        "reference_id": ref.digests()[1].hex(),
        "candidate_id": cand.digests()[1].hex(),
        "id_kind": ref.kind,
        "config": {"operator": ref.operator, "dim": ref.dim, PARAMETER[ref.operator]: ref.p1, "rule_revision": 0},
        "added": [render(i) for i in added],
        "removed": [render(i) for i in removed],
        "changed": [[render(i), h] for i, h in changed],
        "n_unchanged": unchanged,
        "manifest_changes": mchanges,
    }


def p99(values: list[int]) -> int:
    if not values:
        return 0
    k = len(values) - len(values) // 100
    return sorted(values)[k - 1]


FLOOR_KEYS = {
    "semq-floor/1": ("version", "config", "id_kind", "reference_id", "nulls", "changed_rows", "total_rows", "hamming"),
    "semq-floor/2": (
        "version", "config", "id_kind", "reference_id", "nulls", "changed_rows", "total_rows", "hamming", "max_hamming",
    ),
}
REASONS = ("no_common_rows", "removed_rows", "changed_ratio", "hamming", "encoder", "row_above_max")


def validate_floor(floor: dict[str, Any]) -> None:
    """The construction rules: a floor that violates them is InvalidInput."""
    if floor.get("version") not in FLOOR_KEYS or tuple(floor) != FLOOR_KEYS[floor["version"]]:
        raise ValueError("floor: schema")
    if floor["id_kind"] not in ("u64", "utf8"):
        raise ValueError("floor: id_kind")
    if len(bytes.fromhex(floor["reference_id"])) != 32:
        raise ValueError("floor: reference_id")
    for k in FLOOR_KEYS[floor["version"]][4:]:
        if isinstance(floor[k], bool) or not isinstance(floor[k], int) or floor[k] < 0:
            raise ValueError(f"floor: {k}")
    if floor["nulls"] == 0 or floor["total_rows"] == 0 or floor["changed_rows"] > floor["total_rows"]:
        raise ValueError("floor: counts")
    units = units_per_row(floor["config"]["operator"], floor["config"]["dim"])
    if floor["hamming"] > units:
        raise ValueError("floor: hamming")
    if "max_hamming" in floor and not floor["hamming"] <= floor["max_hamming"] <= units:
        raise ValueError("floor: max_hamming")


def compatible(report: dict[str, Any], floor: dict[str, Any]) -> bool:
    return (
        floor["config"] == report["config"]
        and floor["id_kind"] == report["id_kind"]
        and floor["reference_id"] == report["reference_id"]
    )


def evaluate(report: dict[str, Any], floor: dict[str, Any], per_row: bool = False) -> dict[str, Any]:
    """Assumes `validate_floor` and `compatible` hold, and that the floor records
    max_hamming when `per_row` is set (Incompatible otherwise)."""
    n_common = report["n_unchanged"] + len(report["changed"])
    hammings = [h for _, h in report["changed"]]
    failed = {
        "no_common_rows": n_common == 0,
        "removed_rows": bool(report["removed"]),
        "changed_ratio": len(report["changed"]) * floor["total_rows"] > floor["changed_rows"] * n_common,
        "hamming": p99(hammings) > floor["hamming"],
        "encoder": bool({"encoder", "encoder_revision"} & set(report["manifest_changes"])),
        "row_above_max": False,
    }
    rows = [i for i, h in report["changed"] if h > floor["max_hamming"]] if per_row else []
    failed["row_above_max"] = bool(rows)
    reasons = [r for r in REASONS if failed[r]]
    return {"passed": not reasons, "reasons": reasons, "rows": rows}


def within(report: dict[str, Any], floor: dict[str, Any]) -> bool:
    """Assumes `validate_floor` and `compatible` hold."""
    return bool(evaluate(report, floor)["passed"])


def measure(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Assumes every report is a valid null of one reference (asserted)."""
    best = None
    max_p = max_row = 0
    first = reports[0]
    for r in reports:
        assert r["config"] == first["config"] and r["id_kind"] == first["id_kind"]
        assert r["reference_id"] == first["reference_id"]
        n_common = r["n_unchanged"] + len(r["changed"])
        assert n_common > 0 and not r["added"] and not r["removed"]
        assert not ({"encoder", "encoder_revision"} & set(r["manifest_changes"]))
        pair = (len(r["changed"]), n_common)
        if best is None or pair[0] * best[1] > best[0] * pair[1]:
            best = pair
        max_p = max(max_p, p99([h for _, h in r["changed"]]))
        max_row = max([max_row] + [h for _, h in r["changed"]])
    assert best is not None
    return {
        "version": "semq-floor/2",
        "config": first["config"],
        "id_kind": first["id_kind"],
        "reference_id": first["reference_id"],
        "nulls": len(reports),
        "changed_rows": best[0],
        "total_rows": best[1],
        "hamming": max_p,
        "max_hamming": max_row,
    }


# ---------------------------------------------------------------------------
# Checks against a vector directory
# ---------------------------------------------------------------------------


class Mismatch(Exception):
    pass


def expect(cond: bool, what: str) -> None:
    if not cond:
        raise Mismatch(what)


def load_manifest(root: Path, name: str) -> dict[str, Any]:
    return json.loads((root / name / "manifest.json").read_text(encoding="utf-8"))


def check_00(root: Path) -> int:
    n = 0
    for case in load_manifest(root, "00-sha256-fips")["cases"]:
        inp = case["input"]
        msg = inp["ascii"].encode("ascii") if "ascii" in inp else inp["repeat"].encode("ascii") * inp["count"]
        expect(hashlib.sha256(msg).hexdigest() == case["expect"]["digest"], f"sha256 {case['id']}")
        n += 1
    return n


def check_01_02(root: Path) -> int:
    n = 0
    for case in load_manifest(root, "01-config-canonical")["cases"]:
        i = case["input"]
        bad = config_valid(i["operator"], i["dim"], i["parameter"])
        if "error" in case["expect"]:
            expect(bad is not None and case["expect"]["field"] == bad, f"config reject {case['id']}")
        else:
            expect(bad is None and config_bytes(i["operator"], i["dim"], i["parameter"]).hex() == case["expect"]["bytes"], f"config {case['id']}")
        n += 1
    for case in load_manifest(root, "02-config-derived")["cases"]:
        i, e = case["input"], case["expect"]
        expect(bytes_per_vector(i["operator"], i["dim"], i["parameter"]) == e["bytes_per_vector"], f"bpv {case['id']}")
        expect(units_per_row(i["operator"], i["dim"]) == e["units_per_row"], f"units {case['id']}")
        if i["operator"] == "quant":
            import math

            m = struct.unpack("<f", struct.pack("<f", 2.0 / math.sqrt(float(i["dim"]))))[0]
            expect(struct.pack(">f", m).hex() == e["max_magnitude_bits"], f"max_magnitude {case['id']}")
        n += 1
    return n


def check_06_07(root: Path) -> int:
    n = 0
    for case in load_manifest(root, "06-ids-canonical")["cases"]:
        if "sorted" not in case["expect"]:
            continue
        kind = case["input"]["ids"]["kind"]
        values = [int(v) for v in case["input"]["ids"]["values"]] if kind == "u64" else case["input"]["ids"]["values"]
        s = sort_ids(kind, values)
        expect([str(v) for v in s] == case["expect"]["sorted"] if kind == "u64" else s == case["expect"]["sorted"], f"ids order {case['id']}")
        expect(ids_section(kind, s).hex() == case["expect"]["ids_section"], f"ids section {case['id']}")
        n += 1
    for case in load_manifest(root, "07-manifest-canonical")["cases"]:
        if "manifest_section" not in case["expect"]:
            continue
        raw = case["input"].get("pairs")
        if raw is None:
            try:
                raw = [[bytes.fromhex(k).decode("utf-8"), bytes.fromhex(v).decode("utf-8")] for k, v in case["input"]["pairs_hex"]]
            except UnicodeDecodeError:
                continue
        pairs = dict(raw)
        expect(manifest_section(pairs).hex() == case["expect"]["manifest_section"], f"manifest {case['id']}")
        cfg = config_bytes("quant", 4, 4)
        expect(identities(cfg, "u64", [], [], pairs)[1].hex() == case["expect"]["state_id"], f"manifest state {case['id']}")
        n += 1
    return n


def check_08_09(root: Path) -> int:
    n = 0
    images: dict[str, Image] = {}
    for case in load_manifest(root, "09-file")["cases"]:
        if not case["id"].startswith("roundtrip-"):
            continue
        path = root / "09-file" / case["input"]["file"]
        buf = path.read_bytes()
        img = parse(buf)
        images[case["input"]["file"]] = img
        expect(img.to_bytes() == buf, f"image writer {case['id']}")
        expect(len(buf) == case["expect"]["file_size"], f"file size {case['id']}")
        expect(img.digests()[1].hex() == case["expect"]["state_id"], f"state {case['id']}")
        expect(len(img.ids) == case["expect"]["n"] and img.kind == case["expect"]["id_kind"], f"shape {case['id']}")
        n += 1
    for case in load_manifest(root, "08-digests")["cases"]:
        if "file" not in case["input"]:
            continue
        img = parse((root / "08-digests" / case["input"]["file"]).read_bytes())
        content, state = img.digests()
        expect(content.hex() == case["expect"]["content_digest"] and state.hex() == case["expect"]["state_id"], f"digests {case['id']}")
        n += 1
    # Every corrupted file is rejected by the independent reader too.
    for case in load_manifest(root, "09-file")["cases"]:
        inp = case["input"]
        if case["id"].startswith("roundtrip-"):
            continue
        buf = bytearray((root / "09-file" / inp["file"]).read_bytes())
        if "mutate" in inp:
            m = inp["mutate"]
            if m["kind"] == "xor_byte":
                buf[m["at"]] ^= m["value"]
            elif m["kind"] == "set_byte":
                buf[m["at"]] = m["value"]
            elif m["kind"] == "truncate":
                buf = buf[: m["at"]]
            elif m["kind"] == "append_byte":
                buf.append(m["value"])
        try:
            parse(bytes(buf))
        except ValueError:
            n += 1
            continue
        raise Mismatch(f"reference accepted {case['id']}")
    return n


def check_10(root: Path) -> int:
    n = 0
    for case in load_manifest(root, "10-concat")["cases"]:
        if "state_id" not in case["expect"]:
            continue
        parts = [parse((root / "10-concat" / f).read_bytes()) for f in case["input"]["files"]]
        first = parts[0]
        ids = [i for p in parts for i in p.ids]
        rows = [r for p in parts for r in p.rows]
        expect(len(set(ids)) == len(ids), f"concat overlap {case['id']}")
        state = identities(first.config, first.kind, ids, rows, first.manifest)[1]
        expect(state.hex() == case["expect"]["state_id"] and len(ids) == case["expect"]["n"], f"concat {case['id']}")
        n += 1
    return n


def check_11_13(root: Path) -> int:
    n = 0
    for vec in ("11-diff", "13-report"):
        for case in load_manifest(root, vec)["cases"]:
            if "report" not in case["expect"]:
                continue
            ref = parse((root / vec / case["input"]["reference"]).read_bytes())
            cand = parse((root / vec / case["input"]["candidate"]).read_bytes())
            expect(diff(ref, cand) == case["expect"]["report"], f"report {vec} {case['id']}")
            n += 1
    for case in load_manifest(root, "12-floor")["cases"]:
        e = case["expect"]
        d = root / "12-floor"
        if "floor" in case["input"]:
            ref = parse((d / case["input"]["reference"]).read_bytes())
            cand = parse((d / case["input"]["candidate"]).read_bytes())
            floor = case["input"]["floor"]
            try:
                validate_floor(floor)
            except ValueError:
                expect(e.get("error") == "InvalidInput", f"floor rejected {case['id']}")
                n += 1
                continue
            report = diff(ref, cand)
            per_row = case["input"].get("per_row", False)
            if not compatible(report, floor) or (per_row and "max_hamming" not in floor):
                expect(e.get("error") == "Incompatible", f"floor incompatible {case['id']}")
            else:
                expect("within" in e and within(report, floor) == e["within"], f"within {case['id']}")
                expect(evaluate(report, floor, per_row) == e.get("evaluate"), f"evaluate {case['id']}")
            n += 1
        else:
            reports = [diff(parse((d / a).read_bytes()), parse((d / b).read_bytes())) for a, b in case["input"]["null_diffs"]]
            if len({(r["reference_id"], r["id_kind"], json.dumps(r["config"], sort_keys=True)) for r in reports}) > 1:
                expect(e.get("error") == "Incompatible", f"measure incompatible {case['id']}")
            elif "floor" in e:
                expect(measure(reports) == e["floor"], f"measure {case['id']}")
            else:
                try:
                    measure(reports)
                    ok = False
                except AssertionError:
                    ok = True
                expect(ok and e.get("error") == "InvalidInput", f"measure rejects {case['id']}")
            n += 1
    for case in load_manifest(root, "13-report")["cases"]:
        if "floor" in case["expect"]:
            reports = [diff(parse((root / "13-report" / a).read_bytes()), parse((root / "13-report" / b).read_bytes())) for a, b in case["input"]["null_diffs"]]
            expect(measure(reports) == case["expect"]["floor"], f"floor json {case['id']}")
            n += 1
    return n


def main(argv: list[str]) -> int:
    root = Path(argv[1] if len(argv) > 1 else "tests/conformance")
    total = 0
    try:
        for fn in (check_00, check_01_02, check_06_07, check_08_09, check_10, check_11_13):
            total += fn(root)
    except Mismatch as exc:
        print(f"reference: MISMATCH {exc}", file=sys.stderr)
        return 1
    print(f"reference: {total} checks agree with the core")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
