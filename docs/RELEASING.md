# Releasing

The SDK has one version for all four packages, kept in `VERSION` in SemVer
form. A version is published by pushing its tag to a commit on `main`; the
[release workflow](../.github/workflows/release.yml) does the rest.

| Tag | Kind | Where it goes |
| --- | --- | --- |
| `vX.Y.Z-rc.N` | Release candidate | CodeArtifact while the repository is private; PyPI, crates.io, npm (dist-tag `next`) and the Go module once it is public |
| `vX.Y.Z` | Release | PyPI, crates.io, npm (dist-tag `latest`) and the Go module; needs the public repository |

Each registry spells a release candidate its own way: `X.Y.ZrcN` on PyPI,
`X.Y.Z-rc.N` on crates.io and npm, and `bindings/go/vX.Y.Z-rc.N` for Go. No
installer picks a release candidate unless asked for it. Every version gets a
GitHub Release and a section in CHANGELOG.md, which the documentation lists
on its release history page.

## Prepare the version

1. On a branch from `main`, run

   ```sh
   python tools/version.py set X.Y.Z-rc.N   # or X.Y.Z
   ```

   It writes the version to `VERSION`, both Rust crates, the npm package, its
   lockfile and `bindings/ts/src/version.ts`, and turns the `[Unreleased]`
   section of CHANGELOG.md into the section of this version. Edit the notes if
   needed. A release after its last candidate with no new changes gets the
   note "No changes since X.Y.Z-rc.N".
2. Open a pull request, get it reviewed and merge it with CI green.
3. Confirm that the version is unused on PyPI, crates.io and npm. Published
   versions cannot be replaced with different bytes.

## Configure the channels

Every release tag needs the `AWS_AVX512_ROLE_ARN` secret: before publishing,
the workflow runs the conformance vectors with the Linux wheel on an Intel
instance with AVX-512, which GitHub's Linux runners lack. The role and the
instance template are defined in semq-infra (`ec2-avx512/`).

Release candidates from the private repository also need the CodeArtifact
variables (`CODEARTIFACT_DOMAIN`, `CODEARTIFACT_DOMAIN_OWNER`,
`CODEARTIFACT_REPOSITORY`, `AWS_REGION`) and the `AWS_ROLE_ARN` secret.

Publishing to the public registries also needs:

- Trusted Publishers that name this repository, workflow `release.yml`
  and the environments `pypi-release`, `crates-release` and `npm-release`.
  crates.io needs one for `semq-sys` and one for `semq`. A local check cannot
  validate registry-side settings.
- `CRATES_TRUSTED_PUBLISHING=true`, and either `NPM_TRUSTED_PUBLISHING=true` or
  an `NPM_PUBLISH_TOKEN` secret (see below).
- `RELEASE_PUBLISH_ENABLED=true`, set only when the release is approved.
  Set `CODEARTIFACT_PUBLISH_ENABLED=true` too if the version should also go to
  CodeArtifact.

## Rehearse

Run the release workflow by hand on any branch to exercise the whole pipeline
without publishing:

```sh
gh workflow run release.yml --ref <branch>
```

A rehearsal uses the version the files declare, skips the tag and changelog
checks, and builds, tests and installs every package as a release would. It
creates no attestation, publishes nothing and creates no GitHub Release. Run
one on any pull request that changes the release workflow or its actions,
because pull request CI does not run this workflow.

## Publish

Push the tag to the merged commit:

```sh
git tag vX.Y.Z-rc.N <commit on main>
git push origin vX.Y.Z-rc.N
```

The workflow checks the tag against every declared version and CHANGELOG.md,
checks that the commit is on `main`, runs the test suite, builds the packages,
installs them in external consumers without a checkout, and runs the Linux
wheel on an AVX-512 instance. Only then does it publish. On crates.io it publishes `semq-sys` before `semq`. The Go module tag
`bindings/go/vX.Y.Z` is pushed after PyPI, crates.io and npm succeed, and the
GitHub Release is created last, with the version's CHANGELOG.md section as its
notes.

## First npm release only

`@semq/sdk` does not have a published npm version yet, so it cannot use npm
Trusted Publishing for its first publish. Shortly before the first public
release, create a short-lived granular token with package publish permission
and **Bypass 2FA** enabled, then replace the GitHub secret `NPM_PUBLISH_TOKEN`.
Do not rely on a token created earlier without checking its expiry and
permissions. The workflow publishes the package with public access.

After the first successful npm publish, configure its Trusted Publisher for
this repository, workflow `release.yml`, and environment `npm-release`,
allowing `npm publish`. Set `NPM_TRUSTED_PUBLISHING=true`, remove the
`NPM_PUBLISH_TOKEN` secret, and revoke the token on npm. Later releases use
OIDC for npm as well as PyPI and crates.io.

## After the workflow

Install the published versions in clean projects from each registry the tag
reached. Check that the Go module resolves at
`github.com/The-SEMQ-Group/semq/bindings/go@vX.Y.Z` and that a program using
it builds with `go get` alone, since the module compiles its copy of the core
with cgo. See [Installation](installation.md).

The registry uploads are not atomic. If a publish job fails, inspect the
registries before retrying it; a rerun skips crates already on crates.io.
Never move a published tag or overwrite a published version: fix forward with
a new version. Once the release is complete, unset `RELEASE_PUBLISH_ENABLED`
until the next approved release.
