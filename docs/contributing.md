---
description: Build the SEMQ documentation, verify examples, and contribute source-grounded SDK guidance.
---

# Contribute to the docs

**Goal:** make a documentation change that renders cleanly and whose examples
run against the supported API.

**Prerequisites:** a source checkout, Python 3.11 or newer, a C/C++ toolchain,
and CMake 3.20 or newer, plus Node.js 22+ and npm for the TypeDoc reference.
Native-language examples also need their toolchains; see the binding READMEs
in the repository.

## 1. Prepare a local documentation environment

From the repository root:

```sh
python -m venv .venv
```

Activate it with `source .venv/bin/activate` on POSIX or
`.venv\Scripts\Activate.ps1` in Windows PowerShell, then install the build tools
and editable SDK:

```sh
python -m pip install --require-hashes -r .github/requirements/docs.txt
python -m pip install --require-hashes -r .github/requirements/test.txt
python -m pip install -e .
npm ci --prefix bindings/ts
mkdocs serve
```

These are the versions CI uses. The first build downloads the fonts and Mermaid
into `.cache/`, so the published site serves them itself and visitors' browsers
make no requests to Google Fonts or a CDN; later builds reuse the cache.

Open the local address printed by MkDocs. The Python reference comes from the
binding docstrings; a working SDK installation also lets you execute its examples.
TypeDoc generates the TypeScript reference during each build.
Its HTML/assets are included in the site, not committed as duplicate sources.
Changing TypeScript sources rebuilds the reference when using `mkdocs serve`.

## 2. Put the material in the right place

| Content | Location |
| --- | --- |
| First successful workflow | `docs/quickstart.md` |
| An individual task | `docs/guides/` |
| Architecture and terminology | `docs/concepts.md` |
| API signatures and behavior | `docs/reference/` and binding docstrings |
| Navigation and rendering | `mkdocs.yml` |
| Executable example checks | `tests/docs/` |

Use English and the terms in the [glossary](concepts.md#glossary). Give task
guides their prerequisites, steps, and an observable result; organize reference
and explanation pages by the questions readers need to answer. Link to the
relevant next task instead of repeating setup instructions or generic conclusions.
Add every published page to the navigation. Keep language tabs in Python, Rust,
Go, TypeScript order and verify each snippet against its source.

Runnable code fences contain complete examples. Signature declarations belong
in reference tables or `text` fences. An optional fragment requiring external
inputs must explain those inputs and place `<!-- docs-test: skip -->` directly
above its fence. Use that marker only when execution really depends on external
setup, such as a model cache; keep the working core examples executable.

## 3. Verify before committing

```sh
mkdocs build --strict
python -m pytest tests/docs -q
```

The strict build checks published pages, navigation, and local anchors. The
tests run Python page examples and check repository Markdown links and page
reachability from the root README and site navigation, including adjacent
READMEs and GitHub Markdown files. These checks do not verify external website
availability.

The `docs` workflow builds the same site and uploads `sdk-docs-preview` for each
PR. Download and extract that artifact to inspect a reviewed build locally.
Public Pages deployment is separately gated by the repository's `PUBLISH_DOCS`
variable; a successful build does not imply that the site is public.

When changing Rust, Go, or TypeScript snippets, prepare the relevant native
library or WASM package using its binding README or CI job, then run that
language's check:

```sh
python tests/docs/run_native_snippets.py rust
python tests/docs/run_native_snippets.py go
python tests/docs/run_native_snippets.py typescript
```

These commands extract the published code fences, compile them against the
local binding, and execute each program independently. Rust builds its bundled
native core; Go compiles its copy of the core in `bindings/go/internal/core`
(regenerate it with `python tools/gen_go_core.py` after changing `src/`);
TypeScript needs the compiled `dist` package, including `dist/wasm` assets. CI
runs each check in its corresponding language job.

For API or codec changes, run the binding tests and the conformance gate
(`python tools/conformance.py build/semq_vectors`).
Changing committed fixture bytes changes the expected output of every binding;
review those changes explicitly. Do not regenerate fixtures just to make a test
pass.

## Next steps

- Read the full [contributor guide](https://github.com/The-SEMQ-Group/semq/blob/main/CONTRIBUTING.md) for repository conventions.
- Use [GitHub issues](https://github.com/The-SEMQ-Group/semq/issues) for reproducible documentation defects.
- Follow the [security policy](https://github.com/The-SEMQ-Group/semq/blob/main/SECURITY.md) when reporting a vulnerability.
