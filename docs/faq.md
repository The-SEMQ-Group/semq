# Frequently asked questions

## What does SEMQ take as input?

Unit-norm, finite float32 vectors from your embedding model or numeric
pipeline, each under an id you choose. SEMQ does not embed text, normalize
vectors, or attach document metadata beyond the manifest you declare.

## Why must rows be unit-norm?

The operator rules are defined for directions. The core checks that the sum
of squares of every row is within `2^-10` of one and rejects the row with
its index otherwise; normalization stays in your pipeline, where the model's
own convention is known.

## What is the difference between `content_digest` and `state_id`?

`content_digest` covers the config, the id kind, the ids and the rows: the
same corpus under the same rule has the same digest whatever the manifest
says. `state_id` adds the manifest, so it changes when you declare a
different encoder. Equality of states means equality of `state_id`.

## Are reconstructed vectors equal to the originals?

No. Quantization maps many values to the same symbol, and `decode` returns
one representative per symbol. Representatives are not normalized, and
re-encoding one through `encode` is not guaranteed to reproduce the row.

## Can I encode in Python and load in another language?

Yes. Every binding calls the same core, and the
[conformance vectors](https://github.com/The-SEMQ-Group/semq/tree/main/tests/conformance)
pin the bytes and verdicts of every operation. A `.semq` file carries its
config, so the loader needs nothing else.

## What does a floor measure?

The variation your own rebuilds show when nothing changed on purpose: the
worst ratio of changed rows and the largest p99 hamming across the null
rebuilds you measured, and, measured with `--per-row`, the largest hamming
of any row. The floor remembers where it was measured (config, id kind,
reference, number of nulls) and applies only to diffs against that
reference. It is an envelope of observation, not a probability; see
[how many nulls](guides/gate-a-rebuild.md#how-many-nulls) a floor needs.

## Why does `within` ignore added rows?

A rebuild may ingest new documents. The gate cannot judge rows that have no
counterpart, so they are reported and left to you; removed rows always fail
the gate, because a candidate that lost rows is not a rebuild of the same
corpus.

## Which error do I get for what?

`InvalidInput` for arguments that violate their contract, `Incompatible`
for two states that differ in config or id kind, `FormatError` and
`IntegrityError` for files, `Unsupported` for an unsupported floating-point
environment, and `Native` for defects. See the errors page of your binding.

## Next steps

To correct or extend an answer, follow [Contribute to the docs](contributing.md).
