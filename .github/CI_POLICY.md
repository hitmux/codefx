# Upstream CI sync and cache policy

Codefx supports **Linux x86_64 and ARM64** release packages. The pre-merge
Bazel matrix checks x86_64 GNU and musl; post-merge Rust/V8 CI adds ARM64.

## On every Codex upstream sync

1. Merge or cherry-pick upstream source changes onto a dedicated sync branch.
2. Keep Codefx-specific `.github/workflows`, `.github/actions`,
   `.github/scripts`, and `scripts/install` overrides under review.
3. Run `python3 .github/scripts/check_upstream_ci.py`.
4. Review upstream `MODULE.bazel`, `MODULE.bazel.lock`, `Cargo.lock`,
   toolchain, and V8 changes for cache invalidation and new CI dependencies.
5. Open a PR. `blocking-ci/ci-policy` checks workflow references and Linux
   release coverage before expensive Bazel/Rust jobs. Run full post-merge CI
   and verified Linux release smoke before publishing.

The policy guard intentionally fails when upstream adds unsupported Windows
or macOS runners or restores abandoned publisher workflows. Update the guard
and this document whenever platform policy deliberately changes.

## Cache and concurrency

- Repository archive cache: one content-addressed Linux key shared by Bazel
  GNU, musl, ARM64, tests, Clippy and release steps.
- Compiled Bazel action cache: separated by target/toolchain, shared between
  test, Clippy and release; bounded to 2 GiB per target.
- Native Cargo: share downloaded registry/git sources across Linux targets,
  use a 1 GiB target-specific sccache rather than archiving `codex-rs/target`.
- Linux Bazel: at most four matrix jobs at a time and four local Bazel workers
  without BuildBuddy. Remote execution/cache may improve cold-shard reuse;
  verify actual BuildBuddy availability before relying on it.
- Cache entries are immutable. New commits publish new snapshots and restore
  older compatible ones through prefix matching. Source/toolchain differences
  are verified by Bazel's action keys.

## Storage cleanup

`ci-maintenance.yml` runs weekly on main and has a dry-run manual mode.
It deletes old, disposable CI logs/canary artifacts and caches only after
an age threshold. GitHub Releases and verification/provenance assets are
never deleted by this workflow. Review the cleanup log and cache hit rate
before adjusting any retention threshold.

Measure GitHub runner minutes, CI wall-clock time, cache hit percentage, and
peak disk usage across several comparable PR revisions before claiming an
80% cost reduction.
