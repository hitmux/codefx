#!/usr/bin/env bash

set -euo pipefail

# Lint production Linux binaries and their first-party Rust dependencies.
# The previous unrestricted test/binary sweep exhausted hosted runner disk.
# Unit and integration tests remain covered by the separate Bazel test job.
printf '%s\n' \
  "//codex-rs/cli:codex" \
  "//codex-rs/app-server:codex-app-server" \
  "//codex-rs/exec-server:exec-server"
