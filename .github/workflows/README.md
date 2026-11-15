# Codefx Linux CI

All validation runs in GitHub Actions. See [CI_POLICY.md](../CI_POLICY.md) for
the immutable upstream baseline, coverage requirements and allowed adaptations.

`blocking-ci.yml` validates the PR merge revision and produces `CI required`.
It requires the official Linux Bazel graph and workspace argument-comment lint,
fast Rust checks, complete GNU Cargo package test coverage and Clippy,
SDK tests, dependency/repository policy, installer safety and current-source
amd64 musl packages. ARM64, macOS and Windows are outside the supported matrix.
Failed, cancelled or unexpectedly skipped dependencies
fail the aggregate.

`codefx-linux-cargo.yml` partitions workspace packages before compilation so a
single runner does not link and archive the complete workspace. It retains core
retry, TUI/update and app-server tests. It runs tests directly with nextest.

`codefx-source-smoke.yml` builds and installs the actual candidate packages.
`sdk.yml` consumes the successful same-run x86_64 package after checking its source,
version, target and digest. It does not rebuild the CLI or reuse a published tag.
`codefx-native-smoke.yml` checks published releases separately.

`codefx-extended-ci.yml` also runs the required Bazel checks independently on main
or manually. `postmerge-ci.yml` retains full Linux Cargo and V8 validation.
Full Cargo includes remote-environment tests and also supports manual execution
and `full-ci` branches.

For an upstream upgrade or release, run full Linux amd64 validation and its native
package check on the final candidate. A green fast gate is not a full CI pass.
Use Actions run links and exact commits when reporting results. Branch protection
must explicitly require the aggregate; workflows do not configure it themselves.
