# File format

A `.semq` file holds exactly one Encoding: its config, its ids, one packed
row per id, its manifest and the two identities. Everything in the file is
defined byte by byte here, so a state can be read, checked or reproduced
from any language. The layout is pinned by the
[conformance vectors](https://github.com/The-SEMQ-Group/semq/tree/main/tests/conformance),
which every binding runs.

All integers are little-endian. No floating-point value appears anywhere in
the file. The extension `.semq` is a convention; what identifies the format
is its magic bytes.

## Layout

| Section | Size | Content |
| --- | --- | --- |
| magic | 4 bytes | ASCII `SEMQ` |
| version | `u16` | `2` |
| config | 13 bytes | the codec config, see below |
| `id_kind` | `u8` | `0` = `u64`, `1` = `utf8` |
| `n` | `u64` | number of rows |
| ids section | variable | the ids, sorted |
| rows section | `n × bytes_per_vector` | one packed row per id, in id order |
| manifest section | variable | the manifest pairs, sorted by key |
| footer | 64 bytes | `content_digest` (32) followed by `state_id` (32) |

Sections are contiguous, in this order, with no padding, and the file ends
right after the footer. The bytes from the config through the rows section
are the content `S` whose digest identifies the state.

## Config

Thirteen bytes: the operator, the dimension, the operator's parameter and the
rule revision.

```
u8  operator        0 = orbit, 1 = phase, 2 = quant
u32 dim
u32 parameter       scale (orbit), sectors (phase) or bins (quant)
u32 rule_revision   0
```

Two configs are equal when their thirteen bytes are equal. A config is valid
when `dim` is in `1..65536`; for orbit `scale` is in `1..2^30`; for phase
`dim` is even, `sectors` is in `2..256`, and `dim` is a multiple of 4 when
`sectors <= 16`; for quant `bins` is in `2..64`; and the rule revision is
`0`. Anything else is `InvalidInput` when constructed and `FormatError` when
read from a file.

Example: quant with `dim = 4` and `bins = 4` is
`02 04 00 00 00 04 00 00 00 00 00 00 00`.

The sizes of a row follow from the config and are never stored:

| Quantity | orbit | phase | quant |
| --- | --- | --- | --- |
| `units_per_row` | `dim` | `dim / 2` | `dim` |
| alphabet | 19 symbols | `sectors` | `2 × bins` |
| bits per unit | 8 | 4 when `sectors <= 16`, else 8 | `ceil(log2(2 × bins))` |
| `bytes_per_vector` | `dim` | `dim / 4` or `dim / 2` | `ceil(dim × bits_per_unit / 8)` |

Quant also derives `max_magnitude = (float)(2.0 / sqrt((double)dim))`, the
range it bins over, computed in binary64 with a correctly rounded square
root and cast to binary32.

## Rows

A row is the packed form of one vector, exactly `bytes_per_vector` bytes.

**orbit.** One byte per coordinate, holding a symbol in `0..18`.

**phase.** One symbol per coordinate pair, a sector index in
`0..sectors - 1`. With `sectors <= 16` two symbols share a byte:
`byte[i] = s[2i] | (s[2i + 1] << 4)`, the even pair in the low nibble.
Otherwise each symbol is one byte.

**quant.** Symbols are packed least-significant-bit first into one bit
stream: unit `i` occupies bits `[i × b, (i + 1) × b)`, and bit `k` of the
stream is bit `k mod 8` of byte `k / 8`. A symbol is
`sign × bins + bin`, with `sign = 1` for a non-negative coordinate and
`bin` in `0..bins - 1`. Bits after the last unit are padding and are zero.

A row is canonical when every symbol is inside its alphabet and every
padding bit is zero. Encoders always produce canonical rows, constructors
reject a non-canonical row with `InvalidInput`, and readers reject one with
`FormatError`. Without this rule two different byte strings could unpack to
the same symbols, and "no differences" would no longer mean "same identity".

## Ids

An Encoding has one id kind, and the section is sorted so that the same
set of rows always produces the same bytes.

**`u64`.** `n` unsigned 64-bit integers, 8 bytes each, in increasing numeric
order.

**`utf8`.** A table of `n + 1` `u64` offsets followed by the concatenated id
bytes: `offsets[0] = 0`, offsets strictly increasing, `offsets[n]` equal to
the total length. Each id is 1 to 4096 bytes of valid UTF-8 (no surrogate
code points, no overlong sequences), contains no NUL byte, and is stored as
given, without Unicode normalization. Order is bytewise: compare with
`memcmp` over the shorter length, and on a tie the shorter id comes first.

Strictly increasing order implies uniqueness; a reader rejects any
violation. Hosts check that an id is representable before converting it: a
JavaScript string with a lone surrogate is rejected, never replaced.

## Manifest

A set of key and value pairs, both UTF-8 strings without NUL bytes. Keys are
1 to 256 bytes and unique; values are up to 65536 bytes; there are at most
4096 pairs and the section is at most 16 MiB. No nesting and no non-string
values. The keys `encoder` and `encoder_revision` have a meaning only for
`diff` and the rebuild gate; no key is required.

```
u32 n_pairs
n_pairs times, in increasing bytewise key order:
  u32 key_length, key, u32 value_length, value
```

## Identities

```
S              = config ‖ id_kind ‖ n ‖ ids_section ‖ rows_section
content_digest = SHA-256(S)
state_id       = SHA-256(content_digest ‖ manifest_section)
```

`content_digest` answers "same rows under the same rule, whatever was
declared about them"; `state_id` answers "same state as declared". Two
Encodings are equal when their `state_id` is equal. Both are independent of
the order rows were inserted in and of the file framing. Reports render them
as 64 lowercase hex characters.

The empty quant Encoding with `dim = 4`, `bins = 4`, `u64` ids and an empty
manifest:

```
S              = 02 04 00 00 00 04 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00
content_digest = 4528e8a0422f5cde968847e021c85b4e6e78ce68da9e92b2981c62dd48f78f4a
state_id       = ef4d1522eb158aa9b6b83cd5d51f80ea2cc59ac3aeb45b69a1c28c99375b55b9
```

The same config with one row, id `7`, symbols `[7, 0, 4, 3]` (row bytes
`07 07`) and the manifest `{"encoder": "x"}`:

```
S              = 02 04 00 00 00 04 00 00 00 00 00 00 00 00 01 00 00 00 00 00 00 00 07 00 00 00 00 00 00 00 07 07
content_digest = 1a3d8e8bfbf3429525d0bc11e18a17b75ea49af40b6b441f6863444f71230489
manifest       = 01 00 00 00 07 00 00 00 65 6e 63 6f 64 65 72 01 00 00 00 78
state_id       = 07d119f5a0a76de95bd4b41110d6005e6fc38cfc398421dd15df2be68adf9f85
```

The empty Encoding above as a complete 96-byte file:

```
53 45 4d 51 02 00 02 04 00 00 00 04 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 00 45 28 e8 a0 42 2f 5c de 96 88 47 e0 21 c8 5b 4e 6e 78 ce 68 da 9e 92 b2 98 1c 62 dd 48 f7 8f 4a ef 4d 15 22 eb 15 8a a9 b6 b8 3c d5 d5 1f 80 ea 2c c5 9a c3 ae b4 5b 69 a1 c2 8c 99 37 5b 55 b9
```

## How a file is read

`load` treats every file as untrusted and checks it in a fixed order, so
that nothing proportional to a declared size is allocated, copied or hashed
before the bytes that bound it have been verified:

1. Framing: the buffer is long enough for the fixed sections, the magic is
   `SEMQ` and the version is `2`. Version 1 files are rejected, not read.
2. Config: the thirteen bytes are valid; row sizes are derived from them.
3. Sizes: `id_kind` and `n` are read, every section length is computed with
   overflow checks, each section lies inside the buffer, and the buffer
   ends exactly at the footer. The limits below apply before any section is
   touched.
4. Ids: sorted, unique, and for `utf8` well formed and within the length
   limits.
5. Manifest: within the limits, keys sorted and unique, lengths consistent.
6. Identities: both digests are recomputed from the bytes read and compared
   with the footer. A mismatch is `IntegrityError`, with `which` set to
   `content` when `content_digest` differs and to `state` when only
   `state_id` differs.
7. Rows: every row is canonical.
8. Only then is the Encoding constructed; an error never leaves a partial
   one.

A structural problem is `FormatError` and names the section (or the row)
that failed. A file that is valid but larger than the target can hold is
not corrupt: that is the host's out-of-memory error.

The digests prove that the sections are consistent with each other; they do
not prove who produced the file, since anyone can recompute both over any
content. When authenticity matters, compare `state_id` with a value received
over a channel you trust. Ids and manifest values can contain control
characters, which the `semq` command escapes when it prints them.

## Limits

| Item | Limit |
| --- | --- |
| `dim` | `1..65536` |
| `n` | bounded by the buffer and by `n × bytes_per_vector` fitting in memory |
| `utf8` id | `1..4096` bytes |
| manifest key | `1..256` bytes |
| manifest value | `0..65536` bytes |
| manifest pairs | at most 4096 |
| manifest section | at most 16 MiB |

Exceeding a limit is `FormatError` on read and `InvalidInput` on
construction.
