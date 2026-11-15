# Codefx Linux CI coverage policy

Codefx supports Linux x86_64 and ARM64. Every build, test, formatter and generator
runs in GitHub Actions. Local work is limited to source edits and static review.

## Candidate and upstream provenance

`.github/upstream-ci.json` pins `openai/codex` `rust-v0.166.0` at
`6ff1e1ca3b30fc8b914720681fcf5fe62e95f856`. The policy job compares retained
upstream workflows and helpers against that immutable checkout. It rejects
unlisted changes to commands, selectors, conditions and action pins.

PR validation checks out GitHub's synthetic merge revision. Current-source
packages record the checked-out commit, target, version and archive SHA256.
SDK CI downloads an artifact from the same workflow run and verifies all four
fields against its checkout before extracting or executing it. Published release
packages never substitute for the candidate.

## Required coverage

`blocking-ci.yml` aggregates these checks into `CI required`:

- Baseline and coverage policy, including mutation/fault regression tests.
- Fast Rust formatting, dependency usage, benchmark smoke and lint-tool tests.
- The official Linux Bazel test graph, Clippy and release configuration checks.
- Workspace argument-comment lint whenever Rust or CI inputs change.
- GNU Cargo Clippy over the workspace, including test targets.
- GNU Cargo nextest over every workspace package. Core, TUI and app-server use
  dedicated build groups; other packages are assigned deterministically to three
  groups before compilation. No nextest test-name filter narrows this coverage.
- TypeScript SDK build, lint and integration tests; Python SDK lint/tests and
  an independently installed Python SDK smoke test.
- Dependency/security policy, repository/architecture checks, spelling and size.
- Installer transaction, rollback and failure tests.
- Current-source x86_64/ARM64 musl release-configuration builds, native ELF/ABI
  checks including execution of the V8 ABI probe on each native runner, package
  validation, actual installation and reinstallation.

Every required dependency must succeed. Failure, cancellation, an unexpected
skip or a disconnected producer fails the aggregate. SDK waits for source-package
verification and reuses those executables instead of compiling V8 a second time.

## Extended compatibility

`codefx-extended-ci.yml` also exposes the required Bazel checks as standalone
compatibility checks on main and manual runs. `postmerge-ci.yml` retains full
Linux Cargo and V8 verification;
`rust-ci-full.yml` also supports manual runs and `full-ci` branches. The expensive
workspace argument-comment lint remains in full Cargo CI.

Full verification must pass on the source being released, together with both
native package checks. A successful fast gate does not establish full-suite or
release readiness. Upstream syncs must run full Linux verification before release.
Branch protection must explicitly require `CI required`; the job name alone does
not configure GitHub protection. This PR does not change repository settings.

## Explicit infrastructure adaptations

The policy checker permits only these reviewed transformations:

- Remove unsupported Windows/macOS runners and retired upstream publishers.
- Replace private Linux runners with hosted Ubuntu and allow cold-build budgets.
- Replace the SDK's Bazel CLI build with a verified same-run source package,
  preserving SDK commands and running Jest serially on the small runner.
- Remove the duplicate Bazel test entry labelled musl: its matrix value only
  selected cache names, and both entries built native GNU. Genuine musl coverage
  is supplied by explicit Cargo targets and inspected native packages.
- Disable the local Bazel disk action cache to avoid duplicating cold build
  outputs. Repository download caches remain available; BuildBuddy is optional.
- Set the CI test profile to no debug information and no incremental state.
  Bound sccache to 2 GiB, share download-only Cargo caches across profiles and
  pin installed tool versions using the install action's supported `tool` input.
- Put Zig's local cache outside the checkout and report disk consumption.
- Supply the checksum-verified Codex V8 archive and pinned GNU voice SDK/runtime.
  Keep voice version probes, voice tests and V8 consumers enabled.
- Generate Linux V8 bindings in CI from the pinned headers and sandbox release
  defines. The published Unix archive uses a 64-byte inline TypedArray threshold;
  its size-zero published binding is incompatible. Preserve archive checksum
  verification and test the generated binding against the actual native library.
- Select V8 canary features explicitly with `--no-default-features`, enabling
  `sandbox` only for that native variant. The normal workspace probe defaults to
  the sandbox pair used by production; both canary variants retain all tests.
- Use the canonical DotSlash action URL and the cargo-deny container cache path.
- Omit the unavailable OpenAI Fence audit hook while retaining blob-size checks.

Musl native dependencies use bounded network retries, an alternate libcap source
and atomic checksum-verified promotion. A checksum mismatch fails immediately;
transport failure may try another source. These rules have CI fault coverage.

## Updating the baseline

Update the source version, manifest and policy checkout together. Retain upstream
commands except for the listed transformations. Update regression tests whenever
upstream changes job structure. Run fast, full and native package checks against
one final candidate and report exact commits and Actions links. Pending, skipped,
cancelled and unavailable checks are never reported as passes.
