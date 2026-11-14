# Codefx Linux CI

The fork uses the official CI for the corresponding Codex release, retains its
Linux checks and adds Codefx checks. The immutable baseline and permitted runner
adaptations are documented in [CI_POLICY.md](../CI_POLICY.md).

## Pull requests

`blocking-ci.yml` checks GitHub's synthetic merge commit. Its `CI required`
result requires the official Bazel tests, Clippy and release build checks,
fast Rust checks, SDK checks, dependency policy and repository checks, plus
Codefx baseline policy, installer safety and current-source native packages.
A job with a deleted command or a credential-dependent skip is not equivalent
to the official check. The baseline guard verifies the retained implementations.

`codefx-source-smoke.yml` builds Linux x86_64 and ARM64 musl packages from the
same revision and installs the actual native executables. It has no publication
permissions and never substitutes an older published package for the candidate.
`codefx-native-smoke.yml` separately verifies explicitly selected published tags;
that result does not validate current source.

## Full Linux verification

`postmerge-ci.yml` calls `rust-ci-full.yml` and `v8-canary.yml` on main.
The full Rust workflow preserves the official Linux Cargo Clippy/release matrix,
nextest archive/shard coverage and remote-environment tests. It also supports
manual runs and branches containing `full-ci` for verification before merge.
Windows/macOS jobs are removed; private Linux runners use hosted Ubuntu.

On an upstream sync, update the source version, baseline manifest, pinned
checkout and official CI/helper files together. CI rejects unexpected drift.
Run full Linux CI and release package validation before publication.

All verification and formatting runs in GitHub Actions. Locally, edit files
and review static Git differences only.
