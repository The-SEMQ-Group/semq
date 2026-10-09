# Command-line interface

The Python package installs the `semq` command. It reads `.semq` files and
never encodes: states come from the binding APIs.

| Command | What it does | Exit codes |
| --- | --- | --- |
| `semq show FILE [--json] [--limit N]` | Load and verify a file, print its config, id kind, row count, identities, manifest and first ids | `0`; `2` if the file is invalid |
| `semq diff REF NEW [--floor FLOOR.json [--per-row]] [--json] [--limit N]` | Report what changed between two states; with `--floor`, gate the candidate; with `--per-row`, also fail on any changed row above the floor's `max_hamming` | `0` report, or gate passed; `1` gate failed (a changed `encoder` or `encoder_revision` fails it); `2` could not evaluate, including a floor of another reference, config or id kind, and `--per-row` with a floor without per-row data |
| `semq floor REF NULL... [--min-nulls N] [--per-row]` | Measure a floor from null rebuilds of `REF`; writes only JSON to stdout; with `--per-row`, also record `max_hamming` and `distinct_nulls` | `0`; `2` if any input is not a valid null diff or fewer than `N` nulls are given (default 3) |
| `semq version [--json]` | Print `BuildInfo` plus platform, architecture and runtime | `0`; `2` if the core cannot be loaded |

Human output escapes control characters in ids and manifest values and
truncates long lists (`--limit`); `--json` is complete. `semq diff --json`
prints the [report schema](contracts.md#report-schema) and adds `within`
(the result of `Diff.within`) and `verdict` (`passed`, `reasons`, `rows`)
when `--floor` is given; with `--per-row`, `verdict.passed` includes the
per-row check and decides the exit code.
`floor.json` follows the [floor schema](contracts.md#floor-schema): the
config, the id kind, the reference's `state_id`, how many nulls produced it
and the three counts; with `--per-row`, also `max_hamming` and
`distinct_nulls`. A floor applies only to diffs against that reference.
SEMQ 1.0 reads a floor written without `--per-row`, not one written with
it.

Diagnostics go to stderr. With `--floor`, every changed manifest key is
listed without a second classification in the CLI; the core computes the
verdict, which determines the exit code. When the gate fails, stderr names
every failed check and, with `--per-row`, the rows above `max_hamming`.
`--per-row` needs a floor with per-row data: a floor from `semq floor`
without `--per-row`, or saved by SEMQ 1.0, has none, and the error says to
measure it again with `semq floor --per-row`. When the floor's nulls were
not all the same state (`distinct_nulls > 1`), or the floor does not record
it, and there are fewer than 20, `semq diff --per-row` prints a warning: with `N` such nulls, each check can
reject an unchanged rebuild with probability up to `1/(N+1)`. The warning
does not change the exit code; see
[Gate a rebuild](../guides/gate-a-rebuild.md#4-check-every-row). `--min-nulls`
exists because one null rebuild only shows what that rebuild happened to
do; lowering it, even to `1`, is an explicit choice.

See [Gate a rebuild](../guides/gate-a-rebuild.md) for the workflow.
