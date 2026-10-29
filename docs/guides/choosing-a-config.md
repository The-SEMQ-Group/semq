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

quant with `2` bins per sign needs 2 bits per coordinate; `4` needs 3; `8`
needs 4; `16` needs 5; `32` needs 6; `64` needs 7. Bit width changes at
thresholds, so measure before assuming a storage tradeoff.

The quant range is fixed by the dimension. Magnitudes are binned on
`[0, 2 / sqrt(dim))` and the sign is kept apart, so the range is
`±2 / sqrt(dim)`: twice the root mean square of a unit vector's coordinates,
which is exactly `1 / sqrt(dim)`. A magnitude at or above `2 / sqrt(dim)`
goes to the last bin. Because a row's squares sum to one, at most a quarter
of its coordinates can reach that; for Gaussian coordinates it is 4.55%. The
fraction depends on your encoder: 4.1% on the SciFact corpus embedded with
`e5-small-v2` at 384 dimensions (benchmark input `scifact-e5`).

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
and SDK revision with deployed states. The
[benchmark summary](../benchmarks/index.md#choose-a-configuration) lists bits,
bytes, search quality and throughput for the five configurations measured.

## 6. Account for the rebuild gate

The configuration also sets what a [rebuild gate](gate-a-rebuild.md) can see.
A unit's symbol changes only when its value crosses a boundary of the rule.
Quant has a boundary at zero for the sign and `bins - 1` on each side,
evenly spaced up to `2 / sqrt(dim)`, and none beyond: `2 × bins - 1` in all.
More bins put more boundaries in the same range, so a small movement is more
likely to change a symbol, whether it comes from rebuild noise or from a real
change. Orbit rounds `x × scale`, so it has a boundary every `1 / scale` at
every magnitude, including the coordinates quant puts in its last bin. Phase
has one every `2π / sectors` of the angle the rule assigns to the pair.

The rebuild benchmark gates each configuration on the same runs: 5,183
SciFact rows, `e5-small-v2` at 384 dimensions, a floor from three null
rebuilds. Every configuration passed the held-out null rebuild and failed the
four pipeline changes. Under the switch to half precision, more bins changed
more rows; no null changed more than 7 rows in any configuration.

| Config | Rows changed by the noisiest null | Rows changed by half precision | p99 hamming, half precision |
| --- | ---: | ---: | ---: |
| quant, 2 bins | 2 | 1,508 | 3 |
| quant, 4 bins | 2 | 2,653 | 4 |
| quant, 8 bins | 3 | 3,961 | 5 |
| phase, 16 sectors | 2 | 2,322 | 3 |
| orbit, scale 50 | 7 | 3,207 | 4 |

Orbit's noisiest null changed 7 rows; for the other configurations it was 2
or 3. At 384 dimensions,
orbit at scale 50 has a boundary every 0.02 at every magnitude, and quant
with 8 bins one every 0.0128, but only inside ±0.102. Which of them sees more
rebuild noise depends on which coordinates the noise moves; counts this
small, from three nulls, do not rank the configurations.

One corpus, one model and three nulls do not establish a trend. The
[false-alarm and detection rates](../benchmarks/rebuild.md#false-alarms-and-detection-power)
were measured with quant and 4 bins only; for another configuration, measure
its floor from your own null rebuilds.

Source: [`rebuild.json`](../assets/benchmarks/summary/rebuild.json), key
`semq`.

## Next steps

- [Compare codecs on real embeddings](../benchmarks/index.md).
- [Check compatibility](../compatibility.md) before exchanging codes across bindings or machines.
