#!/usr/bin/env python3
"""Compare retained Linux CI with the exact official source version.

Only the versioned platform, runner and coverage-preserving adaptations below are permitted.
Test commands, selectors, actions and their conditions must otherwise match.
This program checks files; it never regenerates or repairs them.
"""

import argparse
import difflib
import json
from pathlib import Path
import re
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[2]
REMOVED_RESULTS = ("tests_macos_aarch64", "tests_windows_x64", "tests_windows_arm64")
PLATFORM_WORKFLOWS = {"bazel.yml", "rust-ci.yml", "rust-ci-full.yml", "v8-canary.yml"}
RUNNER_ADAPTER = """    - name: Adapt Codefx hosted Linux resources
      if: runner.os == 'Linux'
      uses: ./.github/actions/codefx-linux-runner

"""
VOICE_SDK_STEP = """      - name: Prepare pinned GNU voice SDK
        if: runner.os == 'Linux' && endsWith(matrix.target, '-linux-gnu')
        uses: ./.github/actions/codefx-linux-voice-sdk
"""
V8_ARCHIVE_STEP = """      - name: Configure rusty_v8 artifact overrides and verify checksums
        if: runner.os == 'Linux'
        uses: ./.github/actions/setup-rusty-v8
        with:
          target: ${{ inputs.target }}
"""
LINUX_RUNTIME_PREPARATION_STEP = """      - name: Prepare Linux runtime payload and compatibility inputs
        if: runner.os == 'Linux'
        env:
          GH_TOKEN: ${{ github.token }}
        shell: bash
        run: |
          set -euo pipefail
          releases="$(python3 ../.github/scripts/resolve_exec_server_releases.py)"
          echo "CODEX_COMPAT_RELEASES=$releases" >> "$GITHUB_ENV"
          cargo build --locked --target "$CODEX_CI_TARGET" --profile "$CODEX_CI_PROFILE" --bin bwrap
          runtime="$CARGO_TARGET_DIR/$CODEX_CI_TARGET/$CODEX_CI_PROFILE"
          digest="$(sha256sum "$runtime/bwrap" | cut -d ' ' -f 1)"
          echo "CODEX_BWRAP_SHA256=$digest" >> "$GITHUB_ENV"
          install -Dm755 "$runtime/bwrap" "$runtime/codex-resources/bwrap"

"""
LINUX_COMPATIBILITY_STEP = """      - name: Resolve Linux compatibility test inputs
        if: runner.os == 'Linux'
        env:
          GH_TOKEN: ${{ github.token }}
        shell: bash
        run: |
          releases="$(python3 ../.github/scripts/resolve_exec_server_releases.py)"
          echo "CODEX_COMPAT_RELEASES=$releases" >> "$GITHUB_ENV"

"""
LINUX_RUNTIME_EXPORT = """            cp "${CARGO_TARGET_DIR}/${CODEX_CI_TARGET}/${CODEX_CI_PROFILE}/bwrap" "${helper_dir}/"
            printf '%s  bwrap\\n' "$CODEX_BWRAP_SHA256" > "${helper_dir}/bwrap.sha256"
"""
LINUX_RUNTIME_RESTORE = """            (cd "$helper_dir" && sha256sum --check bwrap.sha256)
            install -Dm755 "$helper_dir/bwrap" "$helper_target_dir/codex-resources/bwrap"
"""

SDK_PACKAGE_STEPS = '      - name: Download the same-run current source package\n        uses: actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c # v8.0.1\n        with:\n          name: codefx-source-x86_64-unknown-linux-musl\n          path: ${{ runner.temp }}/sdk-package\n\n      - name: Verify candidate provenance and stage SDK executables\n        run: python3 scripts/install/prepare_sdk_package.py --directory "$RUNNER_TEMP/sdk-package" --output "$RUNNER_TEMP/sdk-runtime"\n\n      - name: Warm up the current source CLI\n        run: \'"${CODEX_EXEC_PATH}" --version\'\n\n'


def linux_projection(path: str, text: str) -> str:
    """Apply the documented, bounded differences to official file contents."""
    name = Path(path).name
    if name in PLATFORM_WORKFLOWS:
        text = re.sub(
            r"(?ms)^  (?:test-windows[^:]*|tests_windows[^:]*|tests_macos[^:]*|build-windows[^:]*):\n"
            r".*?(?=^  [a-zA-Z_][\w-]*:|\Z)",
            "",
            text,
        )
        text = re.sub(
            r"(?ms)^          - (?:os|name|runner):.*?"
            r"(?=^          - (?:os|name|runner):|^    \S|\Z)",
            lambda match: (
                match.group()
                if re.search(
                    r"^            (?:runner|target): .*(?:linux|ubuntu)|"
                    r"^          - (?:os|runner): ubuntu",
                    match.group(),
                    re.M,
                )
                else ""
            ),
            text,
        )
        for result in REMOVED_RESULTS:
            text = re.sub(rf"(?m)^.*{result}.*\n", "", text)
        text = re.sub(
            r"(?m)^            runs_on:\n              group:.*\n              labels:.*\n",
            "",
            text,
        )
        text = re.sub(r"(?m)^      runner_(?:group|labels):.*\n", "", text)
        text = text.replace("timeout-minutes: 30", "timeout-minutes: 180")
        text = text.replace("timeout_minutes: 30", "timeout_minutes: 180")
    if name == "v8-canary.yml":
        # Normal builds use the sandbox archive. Canary variants must choose
        # their own feature explicitly so the release variant stays unsandboxed.
        text = text.replace(
            'cargo_args=(test -p codex-v8-poc --target "${TARGET}")',
            'cargo_args=(test -p codex-v8-poc --no-default-features --target "${TARGET}")',
        )
    if name == "bazel.yml":
        # This matrix value only named caches; both entries executed native GNU.
        text = text.replace(
            "          - os: ubuntu-24.04\n            target: x86_64-unknown-linux-musl\n",
            "",
        )
        text = text.replace(
            "name: Bazel test on ${{ matrix.os }} for ${{ matrix.target }}",
            "name: Bazel native GNU tests on ${{ matrix.os }}",
        )
    if name == "sdk.yml":
        text = re.sub(
            r"    runs-on:\n      group:.*\n      labels:.*\n",
            "    runs-on: ubuntu-24.04\n",
            text,
        )
        # SDK tests consume a verified same-run package; no second CLI/V8 build.
        start = text.index("      - name: Prepare Bazel CI")
        end = text.index("      - name: Install dependencies", start)
        text = text[:start] + SDK_PACKAGE_STEPS + text[end:]
        start = text.index("      - name: Save bazel repository cache")
        end = text.index("      - name: Check for a clean worktree", start)
        text = text[:start] + text[end:]
        text = text.replace(
            "    environment:\n      name: bazel\n      deployment: false\n", ""
        )
        text = text.replace(
            "pnpm -r --filter ./sdk/typescript run test",
            "pnpm -r --filter ./sdk/typescript run test --runInBand",
        )
    if name == "rust-ci-full.yml":
        prefix, marker, suffix = text.partition("  lint_build:\n")
        suffix = suffix.replace(
            "      - uses: ./.github/actions/setup-ci\n",
            "      - uses: ./.github/actions/setup-ci\n" + VOICE_SDK_STEP,
            1,
        )
        text = prefix + marker + suffix
    if name == "rust-ci-full-nextest-platform.yml":
        text = text.replace(
            "      - uses: ./.github/actions/setup-ci\n",
            "      - uses: ./.github/actions/setup-ci\n"
            + VOICE_SDK_STEP.replace("matrix.target", "inputs.target"),
        )
        text = text.replace(
            "      - name: Compute lockfile hash\n",
            V8_ARCHIVE_STEP + "      - name: Compute lockfile hash\n",
            1,
        )
        text = text.replace(
            "      - name: Build nextest archive\n",
            LINUX_RUNTIME_PREPARATION_STEP + "      - name: Build nextest archive\n",
            1,
        )
        helper_copy = '            cp "${CARGO_TARGET_DIR}/${CODEX_CI_TARGET}/${CODEX_CI_PROFILE}/codex-linux-sandbox" "${helper_dir}/"\n'
        text = text.replace(helper_copy, helper_copy + LINUX_RUNTIME_EXPORT)
        text = text.replace(
            "      - name: tests\n", LINUX_COMPATIBILITY_STEP + "      - name: tests\n"
        )
        helper_chmod = (
            '            chmod +x "${helper_target_dir}/codex-linux-sandbox"\n'
        )
        text = text.replace(helper_chmod, helper_chmod + LINUX_RUNTIME_RESTORE)
    if name == "rust-ci-full-nextest-platform.yml":
        text = text.replace(
            "      SCCACHE_CACHE_SIZE: 10G",
            '      SCCACHE_CACHE_SIZE: 2G\n      CARGO_PROFILE_CI_TEST_DEBUG: "0"\n      CARGO_PROFILE_CI_TEST_INCREMENTAL: "false"',
        )
        text = text.replace(
            "tool: sccache\n          version: 0.7.5", "tool: sccache@0.12.0"
        )
        text = text.replace(
            "tool: nextest\n          version: 0.9.103", "tool: cargo-nextest@0.9.103"
        )
        text = text.replace("            ~/.cargo/bin/\n", "")
        text = text.replace(
            "cargo-home-${{ env.ARCHIVE_CACHE_RUNNER }}-${{ inputs.target }}-${{ inputs.profile }}-",
            "cargo-sources-v2-${{ runner.os }}-",
        )
    if name == "cargo-deny.yml":
        text = text.replace(
            "        with:\n          rust-version:",
            "        env:\n"
            "          CARGO_HOME: /github/home/cargo-home\n"
            '          CARGO_NET_GIT_FETCH_WITH_CLI: "true"\n'
            "        with:\n          rust-version:",
        )
    if name == "blob-size-policy.yml":
        # Manual validation has no push.before SHA. Inspect the branch's full
        # divergence from the default branch instead of passing an empty base.
        text = text.replace(
            "        id: range\n",
            "        id: range\n"
            "        env:\n"
            "          DEFAULT_BRANCH: ${{ github.event.repository.default_branch }}\n",
        )
        text = text.replace(
            "          else\n            base='${{ github.event.before }}'",
            '          elif [[ "${{ github.event_name }}" == "workflow_dispatch" ]]; then\n'
            "            head='${{ github.sha }}'\n"
            '            base="$(git merge-base "origin/$DEFAULT_BRANCH" "$head")"\n'
            "          else\n            base='${{ github.event.before }}'",
        )
        text = text.replace(
            "      - uses: openai/fence@e017427978b91977d79a3023842166ab79b5b816 # pin@v0.12.2\n"
            "        with:\n          mode: audit\n",
            "",
        )
    if path == ".github/actions/setup-ci/action.yml":
        text = text.replace("meta/install-dotslash@", "facebook/install-dotslash@")
        text = text.replace("  steps:\n", "  steps:\n" + RUNNER_ADAPTER, 1)
        text = text.replace(
            '          echo "CARGO_TARGET_DIR=$cargo_target_dir"',
            '          echo "ZIG_LOCAL_CACHE_DIR=$CI_BUILD_ROOT/zig-local"\n          echo "CARGO_TARGET_DIR=$cargo_target_dir"',
        )
    if path == ".github/actions/setup-rusty-v8/action.yml":
        text += """
    - name: Generate Linux bindings matching the verified native archive
      if: runner.os == 'Linux'
      uses: ./.github/actions/codefx-linux-v8-binding
      with:
        target: ${{ inputs.target }}
"""
    return text


def comparable(text: str) -> str:
    # Comments and blank lines may explain the platform projection locally.
    return "\n".join(
        line.rstrip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def job_blocks(text: str) -> dict[str, str]:
    body = text.partition("\njobs:\n")[2]
    return {
        match[1]: match[0]
        for match in re.finditer(r"(?ms)^  ([\w-]+):\n.*?(?=^  [\w-]+:|\Z)", body)
    }


def gate_errors(blocking: str) -> list[str]:
    jobs = job_blocks(blocking)
    calls = {
        "bazel": "bazel.yml",
        "linux-cargo": "codefx-linux-cargo.yml",
        "blob-size-policy": "blob-size-policy.yml",
        "cargo-deny": "cargo-deny.yml",
        "codespell": "codespell.yml",
        "repo-checks": "repo-checks.yml",
        "rust-ci": "rust-ci.yml",
        "sdk": "sdk.yml",
        "codefx-install": "codefx-install.yml",
        "codefx-source-smoke": "codefx-source-smoke.yml",
    }
    errors = []
    for job, workflow in calls.items():
        block = jobs.get(job, "")
        if f"    uses: ./.github/workflows/{workflow}\n" not in block:
            errors.append(f"Missing required workflow call: {job}")
        if re.search(r"(?m)^    (?:if|continue-on-error):", block):
            errors.append(f"Required workflow must run and propagate failure: {job}")
    required = jobs.get("required", "")
    needs = set(re.findall(r"(?m)^      - ([\w-]+)$", required))
    if needs != set(calls) | {"ci-policy"}:
        errors.append("CI required must depend on all official Linux and Codefx checks")
    if "    if: ${{ always() }}" not in required:
        errors.append("CI required must report failures even when dependencies fail")
    if "run: python3 .github/scripts/check_ci_results.py" not in required:
        errors.append("CI required must reject skipped/cancelled dependencies")
    if "run: python3 .github/scripts/check_upstream_ci.py --upstream" not in jobs.get(
        "ci-policy", ""
    ):
        errors.append("The official baseline comparison must execute")
    if "    needs: [ci-policy, codefx-source-smoke]" not in jobs.get("sdk", ""):
        errors.append("SDK must consume successful same-candidate source packages")
    return errors


def coverage_errors(root: Path) -> list[str]:
    contracts = {
        ".github/workflows/codefx-linux-cargo.yml": (
            "task: [clippy, core, tui, app-server, other-0, other-1, other-2]",
            'cargo clippy --locked --workspace --all-targets --target "$TARGET" -- -D warnings',
            'select_cargo_ci_packages.py --shard "$SHARD"',
            'cargo nextest run --locked --target "$TARGET" --cargo-profile ci-test --no-fail-fast --test-threads 2 "${packages[@]}"',
            'cargo build --locked --profile ci-test --target "$TARGET" --workspace --bins',
            "uses: ./.github/actions/setup-rusty-v8",
            "uses: ./.github/actions/codefx-linux-voice-sdk",
        ),
        ".github/workflows/codefx-extended-ci.yml": (
            "uses: ./.github/workflows/bazel.yml",
            "workflow_dispatch:",
            "branches: [main]",
        ),
        ".github/workflows/rust-ci-full.yml": (
            "uses: ./.github/actions/run-argument-comment-lint",
            "uses: ./.github/workflows/rust-ci-full-nextest-platform.yml",
        ),
        ".github/workflows/sdk.yml": (
            "name: codefx-source-x86_64-unknown-linux-musl",
            "run: python3 scripts/install/prepare_sdk_package.py",
            "uv run --only-group dev --frozen --no-sync pytest",
            "pnpm -r --filter ./sdk/typescript run test --runInBand",
        ),
        ".github/workflows/codefx-source-smoke.yml": (
            "target: x86_64-unknown-linux-musl",
            "target: aarch64-unknown-linux-musl",
            'readelf -h "$binary"',
            "run: python3 scripts/install/smoke_source_package.py",
        ),
    }
    errors = []
    for path, commands in contracts.items():
        text = (root / path).read_text()
        for command in commands:
            if command not in text:
                errors.append(f"Missing coverage contract in {path}: {command}")
        if re.search(r"(?m)^\s*if: false|^    continue-on-error: true", text):
            errors.append(f"Coverage cannot ignore failure or be disabled: {path}")
    return errors


def baseline_errors(root: Path, upstream: Path, files: list[str]) -> list[str]:
    errors = []
    for path in files:
        expected = comparable(linux_projection(path, (upstream / path).read_text()))
        actual = comparable((root / path).read_text())
        if actual != expected:
            errors.append(
                f"Official Linux CI drift: {path}\n"
                + "\n".join(
                    difflib.unified_diff(
                        expected.splitlines(),
                        actual.splitlines(),
                        fromfile="official Linux baseline",
                        tofile=path,
                        n=2,
                    )
                )
            )
    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--upstream", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads((ROOT / ".github/upstream-ci.json").read_text())
    upstream_sha = subprocess.check_output(
        ["git", "-C", str(args.upstream), "rev-parse", "HEAD"], text=True
    ).strip()
    if upstream_sha != manifest["commit"]:
        raise SystemExit("Official checkout does not match upstream-ci.json")
    version = tomllib.loads((ROOT / "codex-rs/Cargo.toml").read_text())["workspace"][
        "package"
    ]["version"]
    if manifest["tag"] != f"rust-v{version}":
        raise SystemExit(
            "Update the official CI baseline together with the source version"
        )
    errors = baseline_errors(ROOT, args.upstream, manifest["files"])
    blocking = (ROOT / ".github/workflows/blocking-ci.yml").read_text()
    errors.extend(gate_errors(blocking))
    errors.extend(coverage_errors(ROOT))
    source_smoke = (ROOT / ".github/workflows/codefx-source-smoke.yml").read_text()
    if re.search(r"(?m)^\s+(?:ref|tag):", source_smoke):
        errors.append("Current source smoke must not check out an older ref or tag")
    for path in (ROOT / ".github/workflows").glob("*.yml"):
        content = path.read_text()
        if re.search(
            r"(?m)^\s*(?:-\s*)?(?:os|runner|runs-on):\s*(?:windows|macos)",
            content,
        ):
            errors.append(f"Unsupported platform runner: {path.name}")
        for called in re.findall(
            r"(?m)^\s*uses: \./\.github/workflows/([\w.-]+\.yml)\s*$", content
        ):
            if not (path.parent / called).is_file():
                errors.append(f"Missing reusable workflow: {called}")
    for obsolete in (
        "rust-release.yml",
        "rust-release-windows.yml",
        "rust-release-provisioned-macos.yml",
        "rusty-v8-release.yml",
        "rust-release-argument-comment-lint.yml",
    ):
        if (ROOT / ".github/workflows" / obsolete).exists():
            errors.append(f"Unsupported upstream publisher restored: {obsolete}")
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"Official Linux CI matches {manifest['tag']} ({manifest['commit']})")
    print(
        "Official Linux Bazel, workspace argument lint, Cargo, SDK and Codefx "
        "coverage is required."
    )


if __name__ == "__main__":
    main()
