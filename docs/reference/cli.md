# Command-line interface

The Python package installs the `semq` command. It reads `.semq` files and
never encodes: states come from the binding APIs.

| Command | What it does | Exit codes |
| --- | --- | --- |
| `semq show FILE [--json] [--limit N]` | Load and verify a file, print its config, id kind, row count, identities, manifest and first ids | `0`; `2` if the file is invalid |
| `semq diff REF NEW [--floor FLOOR.json [--per-row]] [--json] [--limit N]` | Report what changed between two states; with `--floor`, gate the candidate; with `--per-row`, also fail on any changed row above the floor's `max_hamming` | `0` report, or gate passed; `1` gate failed (a changed `encoder` or `encoder_revision` fails it); `2` could not evaluate, including a floor of another reference, config or id kind, and `--per-row` with a floor that does not record `max_hamming` |
| `semq floor REF NULL... [--min-nulls N]` | Measure a floor from null rebuilds of `REF`; writes only JSON to stdout | `0`; `2` if any input is not a valid null diff or fewer than `N` nulls are given (default 3) |
| `semq version [--json]` | Print `BuildInfo` plus platform, architecture and runtime | `0`; `2` if the core cannot be loaded |

Human output escapes control characters in ids and manifest values and
truncates long lists (`--limit`); `--json` is complete. `semq diff --json`
prints the [report schema](contracts.md#report-schema) and adds `within`
and `verdict` (`passed`, `reasons`, `rows`) when `--floor` is given.
`floor.json` follows the [floor schema](contracts.md#floor-schema): the
config, the id kind, the reference's `state_id`, how many nulls produced it
and the four counts. A floor applies only to diffs against that reference.

Diagnostics go to stderr. With `--floor`, every changed manifest key is
listed without a second classification in the CLI; the core computes the
verdict, which determines the exit code. When the gate fails, stderr names
every failed check and, with `--per-row`, the rows above `max_hamming`.
`--per-row` needs a floor that records `max_hamming`: a floor saved by SEMQ
1.0 does not, so measure it again. `--min-nulls`
exists because one null rebuild only shows what that rebuild happened to
do; lowering it, even to `1`, is an explicit choice.

See [Gate a rebuild](../guides/gate-a-rebuild.md) for the workflow.
