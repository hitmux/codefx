#!/usr/bin/env bash

set -euo pipefail

# Verify production Linux Rust entrypoints under release-only cfg.
# Avoid rebuilding every integration test in the unrestricted workspace.
printf '%s\n' \
  "//codex-rs/cli:codex" \
  "//codex-rs/app-server:codex-app-server" \
  "//codex-rs/exec-server:exec-server" \
  "//codex-rs/linux-sandbox:codex-linux-sandbox"
