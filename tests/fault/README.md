# Allocation failures

`semq_fault` builds the production sources with a private allocator counter.
The control symbols and counters do not exist in the published libraries.
`test_alloc` fails each allocation ordinal in ten public operation paths, for
both ID kinds. Every failure must return `NOMEM`, leave an unpublished handle
NULL, preserve the reference's identity and return to the baseline number of
live allocations. It also checks normal success and complete cleanup.

The target runs under `ctest`; Linux and macOS CI instrument it with ASan/UBSan.
