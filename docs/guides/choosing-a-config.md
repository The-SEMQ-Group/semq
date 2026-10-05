# Choose an operator and configuration

**Goal:** select an operator and its parameter to match your data and the
result you need.

**Prerequisites:** understand [CodecConfig and Codec](../concepts.md), know
your vectors' dimension and normalization policy, and have a representative
evaluation sample. Install a binding before running the example below.

## 1. Start from the data

Every operator admits unit-norm float32 rows only; normalize in your own
pipeline first. If you truncate a Matryoshka embedding to a smaller dimension,
normalize the truncated vector again before encoding.

| You need | Config | What a symbol keeps |
| --- | --- | --- |
| Compact retrieval-quality codes | `CodecConfig.quant(dim, bins)` | The sign and a magnitude bin of one coordinate |
| Angular structure of coordinate pairs | `CodecConfig.phase(dim, sectors)` | The sector of the pair `(2i, 2i + 1)` |
| Coordinate-level codes for comparison | `CodecConfig.orbit(dim, scale=50)` | One discrete symbol per coordinate |

## 2. Parameters and their ranges

| Config | Parameter | Range and effect |
| --- | --- | --- |
| all | `dim` | `1..65536` |
| quant | `bins` | `2..64` magnitude bins per sign; `ceil(log2(2 * bins))` bits per coordinate; the range `max_magnitude = 2 / sqrt(dim)` is derived, not chosen |
| phase | `sectors` | `2..256`; `dim` must be even, and divisible by 4 when `sectors <= 16` (nibble packing) |
| orbit | `scale` | `1..2^30`; default `50` |

quant with `4` bins per sign needs 3 bits per coordinate; `8` needs 4; `16`
needs 5; `32` needs 6; `64` needs 7. Bit width changes at thresholds, so
measure before assuming a storage tradeoff. The quant range is fixed by the
dimension: for unit-norm rows it clips only a tail of coordinates; the
fraction clipped is a property of your encoder, not a constant.

## 3. Inspect a configuration before adopting it

This complete Python example encodes a small corpus and reports its layout.
Save it as `inspect_config.py` and run `python inspect_config.py` after
[installation](../installation.md).

```python
import numpy as np
from semq import Codec

corpus = np.array(
    [[1, 0, 0, 0], [0, 1, 0, 0], [-1, 0, 0, 0], [0, -1, 0, 0]],
    dtype=np.float32,
)
codec = Codec.quant(dim=4, bins=4)
config = codec.config
state = codec.encode(corpus, ids=["a", "b", "c", "d"])
symbols = codec.unpack(state)
assert state.rows.shape == (4, config.bytes_per_vector)
assert symbols.shape == (4, config.units_per_row)
print("bytes per vector:", config.bytes_per_vector)
print("symbols per vector:", config.units_per_row)
print("max magnitude:", config.max_magnitude)
print("state_id:", state.state_id.hex()[:16])
```

**Expected result:** 2 bytes per vector, 4 symbols per vector, a max
magnitude of `1.0` (`2 / sqrt(4)`), and a stable `state_id` prefix. This is a
shape check; the small corpus is not a quality benchmark.

## 4. Keep the config with the state

A `.semq` file carries its config, so a loaded state knows its rule. When
two states must be compared they must share the config and the id kind;
`diff` and `concat` reject anything else. Record the config alongside the
encoder identity in the manifest so a rebuild can be judged.

## 5. Evaluate before changing defaults

Change one setting at a time and re-encode for each candidate. Compare
quality and storage on held-out data with the
[benchmark protocol](benchmark-protocol.md). Record the selected configuration
and SDK revision with deployed states.

## Next steps

- [Compare codecs on real embeddings](../benchmarks/index.md).
- [Check compatibility](../compatibility.md) before exchanging codes across bindings or machines.
