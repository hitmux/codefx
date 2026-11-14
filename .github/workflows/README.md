# Codefx CI policy (Linux-only)

The fork validates and publishes **Linux x86_64 and ARM64**. Windows/macOS
runners and release artifacts are outside the supported release matrix.

- `blocking-ci.yml` is the single required PR gate. It runs the upstream Linux
  Bazel graph, fast Rust checks, SDK checks, repository checks, and Codefx
  installer safety checks.
- `bazel.yml` is the upstream Bazel test command with only the GNU and musl
  Linux matrix entries retained. It does not shard or rewrite the test graph.
- `rust-ci.yml` keeps fast Cargo validation and argument-comment lint.
- `postmerge-ci.yml` runs heavier Cargo and V8 suites on main, including ARM64.
- `codefx-rust-v0.166-release.yml` verifies two Linux musl packages, digests,
  provenance, smoke tests, and installers before promotion.
- `ci-maintenance.yml` prunes disposable caches and logs with a dry-run mode;
  published releases remain untouched.

When syncing Codex upstream, keep the Codefx CI policy files and run
`python3 .github/scripts/check_upstream_ci.py` before opening a PR.
If upstream changes workflow assumptions, update the checker deliberately.
