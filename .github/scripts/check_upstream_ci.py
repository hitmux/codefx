#!/usr/bin/env python3
"""Codefx upstream-sync guard: keep the fork's Linux-only CI/release contract."""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT / ".github" / "workflows"
ISSUES = []


def require(condition: bool, explanation: str) -> None:
    if not condition:
        ISSUES.append(explanation)


def read(relative: str) -> str:
    path = ROOT / relative
    if not path.is_file():
        ISSUES.append(f"Missing policy input: {relative}")
        return ""
    return path.read_text(encoding="utf-8")


ACTIVE = (
    "blocking-ci.yml", "bazel.yml", "rust-ci.yml", "rust-ci-full.yml",
    "v8-canary.yml", "codefx-install.yml", "codefx-platform-release.yml",
    "codefx-native-package.yml", "codefx-native-smoke.yml",
    "codefx-rust-v0.166-release.yml", "postmerge-ci.yml",
)
for file in ACTIVE:
    content = read(f".github/workflows/{file}")
    # Match actual runner declarations and inline matrix entries. Unreachable
    # Windows helper code in reusable upstream dependencies is allowed.
    forbidden = (
        r"(?mi)^\s*(?:-\s*)?(?:runner|runs-on|os):\s*['\"]?(?:windows|macos)",
        r"(?mi)^\s*-\s*\{\s*runner:\s*(?:windows|macos)",
        r"(?mi)^\s*os:\s*\[[^\]]*\b(?:windows|macos)",
    )
    require(not any(re.search(pattern, content) for pattern in forbidden),
            f"Unsupported Windows/macOS runner or matrix in {file}")

# A sync must not restore the abandoned upstream publishing workflow.
for obsolete in (
    "rust-release.yml", "rust-release-windows.yml",
    "rust-release-provisioned-macos.yml", "rusty-v8-release.yml",
    "rust-release-argument-comment-lint.yml",
):
    require(not (WF / obsolete).exists(), f"Obsolete upstream publisher restored: {obsolete}")

# Every local reusable workflow call must resolve after any upstream file move.
for path in WF.glob("*.yml"):
    content = path.read_text(encoding="utf-8")
    for name in re.findall(
        r"(?m)^\s*uses:\s*\./\.github/workflows/([\w.-]+\.yml)\s*$", content
    ):
        require((WF / name).is_file(), f"{path.name} calls missing workflow {name}")

blocking = read(".github/workflows/blocking-ci.yml")
require("  ci-policy:" in blocking and "needs: ci-policy" in blocking,
        "The CI compatibility preflight must gate heavy PR tests")
require("      - ci-policy" in blocking, "CI required job must depend on ci-policy")
require('".github/workflows/**"' in blocking,
        "Upstream workflow changes must trigger the merge gate")

bazel = read(".github/workflows/bazel.yml")
require("x86_64-unknown-linux-gnu" in bazel and "x86_64-unknown-linux-musl" in bazel,
        "Bazel GNU and musl Linux coverage must remain")
require("      max-parallel: 4" in bazel and "--jobs=4" in bazel,
        "Bazel Linux concurrency and local compilation must stay bounded")
require("test-windows-shard:" not in bazel and "test-windows-native-main:" not in bazel,
        "Windows Bazel jobs reintroduced")

prepare = read(".github/actions/prepare-bazel-ci/action.yml")
wrapper = read(".github/scripts/run-bazel-ci.sh")
require("bazel-repo-linux-v2-" in prepare, "Shared Linux repository cache missing")
require("codefx-bazel-actions-v2-" in prepare and "CODEFX_BAZEL_ACTION_CACHE" in wrapper,
        "Test, Clippy and release must share a bounded action cache")
require("experimental_disk_cache_gc_max_size=2G" in wrapper,
        "Bazel disk cache GC limit removed")

platforms = read(".github/workflows/codefx-platform-release.yml")
release = read(".github/workflows/codefx-rust-v0.166-release.yml")
smoke = read(".github/workflows/codefx-native-smoke.yml")
for target in ("x86_64-unknown-linux-musl", "aarch64-unknown-linux-musl"):
    for label, content in (("platforms", platforms), ("release", release), ("smoke", smoke)):
        require(target in content, f"{label}: missing release target {target}")
for label, content in (("platforms", platforms), ("smoke", smoke)):
    require("pc-windows-msvc" not in content, f"{label}: Windows release target restored")
require("targets=(\"x86_64-unknown-linux-musl\", \"aarch64-unknown-linux-musl\")" in release,
        "Release gate must require exactly two Linux packages")

if ISSUES:
    for message in ISSUES:
        print(f"CI POLICY ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)
print(f"Codefx upstream CI policy passed ({len(ACTIVE)} active workflows checked)")
