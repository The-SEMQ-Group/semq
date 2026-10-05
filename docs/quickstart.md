# Quickstart

Encode three vectors into a state, save it, load it back, and compare it
with a rebuild. After [installation](installation.md), this takes a few
minutes and needs no model, network call, or downloaded dataset.

First the whole lifecycle in a dozen lines: encode, save, load, diff. Then
the question the floor answers: is a rebuild's change noise, or a real change?

## 1. Understand the inputs

Every example uses the same three embeddings of dimension 4, under the ids
`doc-1`, `doc-2` and `doc-3`. Each row has unit length, which every operator
requires: `0.6² + 0.8² = 1`. The manifest records which encoder produced them.

The examples use **quant** with four magnitude bins per sign: each
coordinate becomes one symbol for its sign and its size.

## 2. Encode, save, load and diff

Use the application directory and run command from your
[installation tab](installation.md). Each program writes `corpus.semq` into
its working directory, loads it back, and diffs it against a rebuild in which
`doc-3` changed.

=== "Python"

    ```python
    import numpy as np
    from semq import Codec, Encoding

    vectors = np.array([
        [0.6, 0.8, 0.0, 0.0],
        [0.0, 0.6, 0.8, 0.0],
        [0.0, 0.0, 0.6, 0.8],
    ], dtype=np.float32)
    ids = ["doc-1", "doc-2", "doc-3"]
    manifest = {"encoder": "example-encoder", "encoder_revision": "1"}

    codec = Codec.quant(dim=4, bins=4)
    codec.encode(vectors, ids=ids, manifest=manifest).save("corpus.semq")

    reference = Encoding.load("corpus.semq")
    print(reference)

    rebuilt = vectors.copy()
    rebuilt[2] = [0.8, 0.0, 0.0, 0.6]  # doc-3 changed
    print(reference.diff(codec.encode(rebuilt, ids=ids, manifest=manifest)))
    ```

=== "Rust"

    ```rust
    use semq::{Codec, Encoding, Ids, Manifest};

    fn main() -> Result<(), Box<dyn std::error::Error>> {
        let vectors: [f32; 12] = [
            0.6, 0.8, 0.0, 0.0,
            0.0, 0.6, 0.8, 0.0,
            0.0, 0.0, 0.6, 0.8,
        ];
        let ids = Ids::utf8(&["doc-1", "doc-2", "doc-3"]);
        let manifest = Manifest::from([
            ("encoder".to_string(), "example-encoder".to_string()),
            ("encoder_revision".to_string(), "1".to_string()),
        ]);

        let codec = Codec::quant(4, 4)?;
        let state = codec.encode(ids, &vectors, Some(&manifest))?;
        std::fs::write("corpus.semq", state.to_bytes())?;

        let reference = Encoding::from_bytes(&std::fs::read("corpus.semq")?)?;
        println!("{reference}");

        let mut rebuilt = vectors;
        rebuilt[8..].copy_from_slice(&[0.8, 0.0, 0.0, 0.6]); // doc-3 changed
        println!("{}", reference.diff(&codec.encode(ids, &rebuilt, Some(&manifest))?)?);
        Ok(())
    }
    ```

=== "Go"

    ```go
    package main

    import (
        "fmt"
        "os"

        semq "github.com/The-SEMQ-Group/semq/bindings/go"
    )

    func check(err error) { if err != nil { panic(err) } }

    func main() {
        vectors := []float32{
            0.6, 0.8, 0.0, 0.0,
            0.0, 0.6, 0.8, 0.0,
            0.0, 0.0, 0.6, 0.8,
        }
        ids := semq.UTF8IDs("doc-1", "doc-2", "doc-3")
        manifest := map[string]string{"encoder": "example-encoder", "encoder_revision": "1"}

        codec, err := semq.NewQuantCodec(4, 4)
        check(err)
        defer codec.Close()
        state, err := codec.Encode(ids, vectors, manifest)
        check(err)
        check(os.WriteFile("corpus.semq", state.Bytes(), 0o644))
        state.Close()

        data, err := os.ReadFile("corpus.semq")
        check(err)
        reference, err := semq.Load(data)
        check(err)
        defer reference.Close()
        fmt.Println(reference)

        rebuilt := append([]float32(nil), vectors...)
        copy(rebuilt[8:], []float32{0.8, 0.0, 0.0, 0.6}) // doc-3 changed
        candidate, err := codec.Encode(ids, rebuilt, manifest)
        check(err)
        defer candidate.Close()
        diff, err := reference.Diff(candidate)
        check(err)
        defer diff.Close()
        fmt.Println(diff)
    }
    ```

=== "TypeScript"

    ```typescript
    import { readFileSync, writeFileSync } from "node:fs";
    import { Codec, Encoding } from "@semq/sdk";

    const vectors = new Float32Array([
      0.6, 0.8, 0.0, 0.0,
      0.0, 0.6, 0.8, 0.0,
      0.0, 0.0, 0.6, 0.8,
    ]);
    const ids = ["doc-1", "doc-2", "doc-3"];
    const manifest = { encoder: "example-encoder", encoder_revision: "1" };

    const codec = await Codec.quant(4, 4);
    writeFileSync("corpus.semq", codec.encode({ ids, vectors, manifest }).toBytes());

    const reference = Encoding.fromBytes(readFileSync("corpus.semq"));
    console.log(String(reference));

    const rebuilt = vectors.slice();
    rebuilt.set([0.8, 0.0, 0.0, 0.6], 8); // doc-3 changed
    console.log(String(reference.diff(codec.encode({ ids, vectors: rebuilt, manifest }))));
    ```

Every program prints:

```text
Encoding(3 rows, quant(dim=4, bins=4), state_id 6e6f8a89bae4...)
1 of 3 rows changed: doc-3 (hamming 3). 0 added, 0 removed.
```

The state loaded from `corpus.semq` has the identity it was saved with. The
diff names the row that changed and its hamming distance: three of the four
symbols of `doc-3` differ.

## 3. Tell rebuild noise from a real change

Re-running an encoder on the same corpus moves coordinates a little. A
**null rebuild** is that: the unchanged corpus through the same encoder again.
The program below measures a floor from three null rebuilds, then checks two
candidates against it: another noisy rebuild, and the rebuild in which `doc-3`
changed. The numbered markers explain the stand-in for the encoder, the floor
and the gate.

=== "Python"

    ```python
    import numpy as np
    from semq import Codec, Floor

    vectors = np.array([
        [0.6, 0.8, 0.0, 0.0],
        [0.0, 0.6, 0.8, 0.0],
        [0.0, 0.0, 0.6, 0.8],
    ], dtype=np.float32)
    ids = ["doc-1", "doc-2", "doc-3"]
    manifest = {"encoder": "example-encoder", "encoder_revision": "1"}


    def rebuild(vectors, seed):  # (1)!
        noise = 1e-3 * np.sin(seed + np.arange(vectors.size)).reshape(vectors.shape)
        noisy = (vectors + noise).astype(np.float32)
        return noisy / np.linalg.norm(noisy, axis=1, keepdims=True)


    codec = Codec.quant(dim=4, bins=4)
    reference = codec.encode(vectors, ids=ids, manifest=manifest)


    def compare(candidate):
        return reference.diff(codec.encode(candidate, ids=ids, manifest=manifest))


    floor = Floor.measure([compare(rebuild(vectors, seed)) for seed in (1, 2, 3)])  # (2)!
    print(floor)

    noisy = compare(rebuild(vectors, 4))
    print(noisy)
    print(noisy.within(floor))  # (3)!

    edited = vectors.copy()
    edited[2] = [0.8, 0.0, 0.0, 0.6]  # doc-3 changed
    changed = compare(edited)
    print(changed)
    print(changed.within(floor))
    ```

    1. Stands in for re-running your encoder, with about `1e-3` of repeatable
       noise. It is not part of SEMQ. In your pipeline, a null rebuild is the
       unchanged corpus through the same encoder again.
    2. The floor is the envelope of the three null rebuilds: the worst ratio of
       changed rows and the largest hamming distance any of them produced,
       bound to this reference, config and id kind.
    3. The gate. A candidate is within the floor when it removes no rows,
       changes no more of the shared rows than the floor's ratio, stays within
       its hamming bound, and keeps `encoder` and `encoder_revision`.

=== "Rust"

    ```rust
    use semq::{Codec, Diff, Floor, Ids, Manifest};

    fn rebuild(vectors: &[f32], seed: usize) -> Vec<f32> {  // (1)!
        let mut noisy: Vec<f32> = vectors
            .iter()
            .enumerate()
            .map(|(i, &x)| (f64::from(x) + 1e-3 * ((seed + i) as f64).sin()) as f32)
            .collect();
        for row in noisy.chunks_mut(4) {
            let norm = row.iter().map(|x| x * x).sum::<f32>().sqrt();
            row.iter_mut().for_each(|x| *x /= norm);
        }
        noisy
    }

    fn main() -> Result<(), Box<dyn std::error::Error>> {
        let vectors: [f32; 12] = [
            0.6, 0.8, 0.0, 0.0,
            0.0, 0.6, 0.8, 0.0,
            0.0, 0.0, 0.6, 0.8,
        ];
        let ids = Ids::utf8(&["doc-1", "doc-2", "doc-3"]);
        let manifest = Manifest::from([
            ("encoder".to_string(), "example-encoder".to_string()),
            ("encoder_revision".to_string(), "1".to_string()),
        ]);

        let codec = Codec::quant(4, 4)?;
        let reference = codec.encode(ids, &vectors, Some(&manifest))?;
        let compare = |candidate: &[f32]| -> semq::Result<Diff> {
            reference.diff(&codec.encode(ids, candidate, Some(&manifest))?)
        };

        let nulls = (1..=3)
            .map(|seed| compare(&rebuild(&vectors, seed)))
            .collect::<semq::Result<Vec<_>>>()?;
        let floor = Floor::measure(&nulls)?;  // (2)!
        println!("{floor}");

        let noisy = compare(&rebuild(&vectors, 4))?;
        println!("{noisy}");
        println!("{}", noisy.within(&floor)?);  // (3)!

        let mut edited = vectors;
        edited[8..].copy_from_slice(&[0.8, 0.0, 0.0, 0.6]); // doc-3 changed
        let changed = compare(&edited)?;
        println!("{changed}");
        println!("{}", changed.within(&floor)?);
        Ok(())
    }
    ```

    1. Stands in for re-running your encoder, with about `1e-3` of repeatable
       noise. It is not part of SEMQ. In your pipeline, a null rebuild is the
       unchanged corpus through the same encoder again.
    2. The floor is the envelope of the three null rebuilds: the worst ratio of
       changed rows and the largest hamming distance any of them produced,
       bound to this reference, config and id kind.
    3. The gate. A candidate is within the floor when it removes no rows,
       changes no more of the shared rows than the floor's ratio, stays within
       its hamming bound, and keeps `encoder` and `encoder_revision`.

=== "Go"

    ```go
    package main

    import (
        "fmt"
        "math"

        semq "github.com/The-SEMQ-Group/semq/bindings/go"
    )

    func check(err error) { if err != nil { panic(err) } }

    func rebuild(vectors []float32, seed int) []float32 {  // (1)!
        noisy := make([]float32, len(vectors))
        for i, x := range vectors {
            noisy[i] = float32(float64(x) + 1e-3*math.Sin(float64(seed+i)))
        }
        for r := 0; r < len(noisy); r += 4 {
            var sum float32
            for _, x := range noisy[r : r+4] { sum += x * x }
            norm := float32(math.Sqrt(float64(sum)))
            for c := r; c < r+4; c++ { noisy[c] /= norm }
        }
        return noisy
    }

    func main() {
        vectors := []float32{
            0.6, 0.8, 0.0, 0.0,
            0.0, 0.6, 0.8, 0.0,
            0.0, 0.0, 0.6, 0.8,
        }
        ids := semq.UTF8IDs("doc-1", "doc-2", "doc-3")
        manifest := map[string]string{"encoder": "example-encoder", "encoder_revision": "1"}

        codec, err := semq.NewQuantCodec(4, 4)
        check(err)
        defer codec.Close()
        reference, err := codec.Encode(ids, vectors, manifest)
        check(err)
        defer reference.Close()
        compare := func(candidate []float32) *semq.Diff {
            encoded, err := codec.Encode(ids, candidate, manifest)
            check(err)
            defer encoded.Close() // the Diff keeps the rows it needs
            diff, err := reference.Diff(encoded)
            check(err)
            return diff
        }

        var nulls []*semq.Diff
        for seed := 1; seed <= 3; seed++ {
            nulls = append(nulls, compare(rebuild(vectors, seed)))
        }
        floor, err := semq.MeasureFloor(nulls)  // (2)!
        check(err)
        fmt.Println(floor)

        noisy := compare(rebuild(vectors, 4))
        fmt.Println(noisy)
        within, err := noisy.Within(floor)  // (3)!
        check(err)
        fmt.Println(within)

        edited := append([]float32(nil), vectors...)
        copy(edited[8:], []float32{0.8, 0.0, 0.0, 0.6}) // doc-3 changed
        changed := compare(edited)
        fmt.Println(changed)
        within, err = changed.Within(floor)
        check(err)
        fmt.Println(within)
    }
    ```

    1. Stands in for re-running your encoder, with about `1e-3` of repeatable
       noise. It is not part of SEMQ. In your pipeline, a null rebuild is the
       unchanged corpus through the same encoder again.
    2. The floor is the envelope of the three null rebuilds: the worst ratio of
       changed rows and the largest hamming distance any of them produced,
       bound to this reference, config and id kind.
    3. The gate. A candidate is within the floor when it removes no rows,
       changes no more of the shared rows than the floor's ratio, stays within
       its hamming bound, and keeps `encoder` and `encoder_revision`.

=== "TypeScript"

    ```typescript
    import { Codec, Floor } from "@semq/sdk";

    const vectors = new Float32Array([
      0.6, 0.8, 0.0, 0.0,
      0.0, 0.6, 0.8, 0.0,
      0.0, 0.0, 0.6, 0.8,
    ]);
    const ids = ["doc-1", "doc-2", "doc-3"];
    const manifest = { encoder: "example-encoder", encoder_revision: "1" };

    function rebuild(vectors: Float32Array, seed: number): Float32Array {  // (1)!
      const noisy = vectors.map((x, i) => x + 1e-3 * Math.sin(seed + i));
      for (let r = 0; r < noisy.length; r += 4) {
        const row = noisy.subarray(r, r + 4);
        const norm = Math.hypot(...row);
        row.forEach((x, c) => { row[c] = x / norm; });
      }
      return noisy;
    }

    const codec = await Codec.quant(4, 4);
    const reference = codec.encode({ ids, vectors, manifest });
    const compare = (candidate: Float32Array) =>
      reference.diff(codec.encode({ ids, vectors: candidate, manifest }));

    const floor = Floor.measure([1, 2, 3].map((seed) => compare(rebuild(vectors, seed))));  // (2)!
    console.log(String(floor));

    const noisy = compare(rebuild(vectors, 4));
    console.log(String(noisy));
    console.log(noisy.within(floor));  // (3)!

    const edited = vectors.slice();
    edited.set([0.8, 0.0, 0.0, 0.6], 8); // doc-3 changed
    const changed = compare(edited);
    console.log(String(changed));
    console.log(changed.within(floor));
    ```

    1. Stands in for re-running your encoder, with about `1e-3` of repeatable
       noise. It is not part of SEMQ. In your pipeline, a null rebuild is the
       unchanged corpus through the same encoder again.
    2. The floor is the envelope of the three null rebuilds: the worst ratio of
       changed rows and the largest hamming distance any of them produced,
       bound to this reference, config and id kind.
    3. The gate. A candidate is within the floor when it removes no rows,
       changes no more of the shared rows than the floor's ratio, stays within
       its hamming bound, and keeps `encoder` and `encoder_revision`.

## 4. Check the result

Every program prints the following; Python writes the two booleans as `True`
and `False`.

```text
Floor(3 of 3 rows, hamming 2, from 3 nulls)
3 of 3 rows changed: doc-1 (hamming 1), doc-2 (hamming 1), doc-3 (hamming 1). 0 added, 0 removed.
true
1 of 3 rows changed: doc-3 (hamming 3). 0 added, 0 removed.
false
```

The zeros in these vectors sit exactly on the sign boundary, so the noise of
a rebuild flips some of their symbols: across the three null rebuilds every
row changed, by at most two symbols. That is the floor. The noisy candidate
stays within it and passes. The changed `doc-3` moves three symbols, more than
any null rebuild did, so it fails. Real embeddings rarely sit exactly on a
boundary; these do so that a dozen numbers show what rebuild noise looks like.

For the full machine-readable report, call `diff.as_dict()` in Python or run
`semq diff --json --floor FLOOR.json`; see the
[report schema](reference/contracts.md#report-schema) and the
[CLI reference](reference/cli.md).

The same float32 input, ids and manifest produce the same `state_id` in every
language and on every supported architecture. The shared
[conformance vectors](https://github.com/The-SEMQ-Group/semq/tree/main/tests/conformance)
pin the bytes and verdicts every binding is checked against.

From a shell, the Python package installs the `semq` command:

```sh
semq show corpus.semq
```

## Next steps

- [Gate a rebuild](guides/gate-a-rebuild.md): measure a floor from null rebuilds and gate candidates with the CLI.
- [Choose a configuration](guides/choosing-a-config.md): operators, bins, sectors and scale.
- [Concepts and architecture](concepts.md): states, identities and what a diff can tell you.
- [API reference](reference/index.md): every public operation.
