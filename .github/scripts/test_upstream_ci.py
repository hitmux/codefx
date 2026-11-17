"""Regression coverage for accidentally weakened Linux CI gates."""

from pathlib import Path
import shutil
import tempfile
import unittest

import check_upstream_ci as policy


class LinuxProjection(unittest.TestCase):
    def test_linux_test_archives_keep_the_verified_runtime_payload(self):
        path = ".github/workflows/rust-ci-full-nextest-platform.yml"
        official = (
            "      - name: Build nextest archive\n"
            "        run: cargo nextest archive --workspace\n"
            '            cp "${CARGO_TARGET_DIR}/${CODEX_CI_TARGET}/${CODEX_CI_PROFILE}/codex-linux-sandbox" "${helper_dir}/"\n'
            "      - name: tests\n"
            '            chmod +x "${helper_target_dir}/codex-linux-sandbox"\n'
            '            cargo nextest run --archive-file "$archive_file"\n'
        )
        projected = policy.linux_projection(path, official)
        self.assertIn("CODEX_BWRAP_SHA256", projected)
        self.assertIn("sha256sum --check bwrap.sha256", projected)
        self.assertIn("run: cargo nextest archive --workspace", projected)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "fork"
            upstream = Path(temp) / "upstream"
            for directory in (root, upstream):
                (directory / path).parent.mkdir(parents=True)
            (upstream / path).write_text(official)
            (root / path).write_text(projected)
            self.assertEqual(policy.baseline_errors(root, upstream, [path]), [])
            for mutation in (
                projected.replace(" --bin bwrap", " --bin codex"),
                projected.replace("sha256sum --check bwrap.sha256", "true"),
                projected.replace(policy.LINUX_RUNTIME_EXPORT, ""),
            ):
                with self.subTest(mutation=mutation):
                    (root / path).write_text(mutation)
                    self.assertTrue(policy.baseline_errors(root, upstream, [path]))

    def test_workspace_argument_comment_lint_stays_in_the_pr_graph(self):
        path = ".github/workflows/rust-ci.yml"
        official = (
            "jobs:\n  argument_comment_lint_prebuilt:\n"
            "    runs-on: ubuntu-24.04\n"
            "    steps:\n      - uses: ./.github/actions/run-argument-comment-lint\n"
            "  results:\n    needs: [argument_comment_lint_prebuilt]\n"
            "    run: summarize\n"
        )
        projected = policy.linux_projection(path, official)
        self.assertEqual(projected, official)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "fork"
            upstream = Path(temp) / "upstream"
            for directory in (root, upstream):
                (directory / path).parent.mkdir(parents=True)
            (upstream / path).write_text(official)
            for mutation in (
                projected.replace(
                    "      - uses: ./.github/actions/run-argument-comment-lint\n", ""
                ),
                projected.replace(
                    "needs: [argument_comment_lint_prebuilt]", "needs: []"
                ),
                projected.replace("    steps:\n", "    if: false\n    steps:\n"),
            ):
                with self.subTest(mutation=mutation):
                    (root / path).write_text(mutation)
                    self.assertTrue(policy.baseline_errors(root, upstream, [path]))

    def test_linux_binding_generation_preserves_archive_verification(self):
        path = ".github/actions/setup-rusty-v8/action.yml"
        official = "runs:\n  using: composite\n  steps:\n    - run: sha256sum --check manifest\n"
        projected = policy.linux_projection(path, official)
        self.assertIn("sha256sum --check manifest", projected)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "fork"
            upstream = Path(temp) / "upstream"
            for directory in (root, upstream):
                (directory / path).parent.mkdir(parents=True)
            (upstream / path).write_text(official)
            (root / path).write_text(projected)
            self.assertEqual(policy.baseline_errors(root, upstream, [path]), [])
            for mutation in (
                projected.replace("sha256sum --check manifest", "true"),
                projected.replace("if: runner.os == 'Linux'", "if: false"),
                projected.replace("codefx-linux-v8-binding", "unverified-binding"),
            ):
                (root / path).write_text(mutation)
                self.assertTrue(policy.baseline_errors(root, upstream, [path]))

    def test_linux_matrices_keep_commands_and_drop_other_platforms(self):
        source = (
            "jobs:\n  test:\n    strategy:\n      matrix:\n        include:\n"
            "          - os: macos-15-xlarge\n            target: aarch64-apple-darwin\n"
            "          - os: ubuntu-24.04\n            target: x86_64-unknown-linux-gnu\n"
            "          - os: ubuntu-24.04\n            target: x86_64-unknown-linux-musl\n"
            "          - os: ubuntu-24.04-arm\n            target: aarch64-unknown-linux-gnu\n"
            "          - os: ubuntu-24.04-arm\n            target: aarch64-unknown-linux-musl\n"
            "          - os: windows-latest\n            target: x86_64-pc-windows-msvc\n"
            "    steps:\n      - run: bazel test //...\n"
        )
        projected = policy.linux_projection(
            ".github/workflows/rust-ci-full.yml", source
        )
        self.assertIn("target: x86_64-unknown-linux-gnu", projected)
        self.assertIn("target: x86_64-unknown-linux-musl", projected)
        self.assertIn("run: bazel test //...", projected)
        self.assertNotIn("target: aarch64-apple-darwin", projected)
        self.assertNotIn("target: x86_64-pc-windows-msvc", projected)
        self.assertNotIn("target: aarch64-unknown-linux-gnu", projected)
        self.assertNotIn("target: aarch64-unknown-linux-musl", projected)

    def test_named_linux_lint_matrix_is_retained(self):
        source = (
            "jobs:\n  lint:\n    strategy:\n      matrix:\n        include:\n"
            "          - name: Linux\n            runner: ubuntu-24.04\n"
            "            timeout_minutes: 30\n"
            "          - name: Windows\n            runner: windows-x64\n"
            "    steps:\n      - run: lint\n"
        )
        projected = policy.linux_projection(".github/workflows/rust-ci.yml", source)
        self.assertIn("name: Linux", projected)
        self.assertIn("timeout_minutes: 180", projected)
        self.assertNotIn("name: Windows", projected)
        self.assertIn("run: lint", projected)

    def test_v8_linux_smoke_keeps_target_and_ignored_tests(self):
        source = (
            "jobs:\n  build:\n    strategy:\n      matrix:\n        include:\n"
            "          - runner: ubuntu-24.04\n"
            "            target: x86_64-unknown-linux-musl\n"
            "          - runner: macos-15-xlarge\n"
            "            target: aarch64-apple-darwin\n"
            "    steps:\n"
            '      - run: cargo test --target "${TARGET}" -- --include-ignored\n'
            "  build-windows-source:\n    runs-on: windows-2025\n"
        )
        projected = policy.linux_projection(".github/workflows/v8-canary.yml", source)
        self.assertIn("target: x86_64-unknown-linux-musl", projected)
        self.assertIn('--target "${TARGET}" -- --include-ignored', projected)
        self.assertNotIn("build-windows-source", projected)
        self.assertNotIn("target: aarch64-apple-darwin", projected)

    def test_v8_canary_selects_each_native_feature_variant_explicitly(self):
        path = ".github/workflows/v8-canary.yml"
        official = (
            'cargo_args=(test -p codex-v8-poc --target "${TARGET}")\n'
            'if [[ "${SANDBOX}" == "true" ]]; then\n'
            "  cargo_args+=(--features sandbox)\n"
            "fi\n"
            "cargo_args+=(-- --include-ignored)\n"
        )
        projected = policy.linux_projection(path, official)
        self.assertIn("--no-default-features", projected)
        self.assertIn("--features sandbox", projected)
        self.assertIn("--include-ignored", projected)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "fork"
            upstream = Path(temp) / "upstream"
            for directory in (root, upstream):
                (directory / path).parent.mkdir(parents=True)
            (upstream / path).write_text(official)
            (root / path).write_text(projected)
            self.assertEqual(policy.baseline_errors(root, upstream, [path]), [])
            for mutation in (
                projected.replace(" --no-default-features", ""),
                projected.replace("--features sandbox", "--features wrong"),
                projected.replace("--include-ignored", "--ignored"),
            ):
                with self.subTest(mutation=mutation):
                    (root / path).write_text(mutation)
                    self.assertTrue(policy.baseline_errors(root, upstream, [path]))

    def test_nextest_archive_prepares_verified_v8_inputs(self):
        path = ".github/workflows/rust-ci-full-nextest-platform.yml"
        official = (
            "jobs:\n  archive:\n    steps:\n"
            "      - uses: ./.github/actions/setup-ci\n"
            "      - name: Compute lockfile hash\n"
            "        run: sha256sum Cargo.lock\n"
            "      - run: cargo nextest archive --workspace\n"
        )
        projected = policy.linux_projection(path, official)
        self.assertIn(policy.V8_ARCHIVE_STEP, projected)
        self.assertIn("run: cargo nextest archive --workspace", projected)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "fork"
            upstream = Path(temp) / "upstream"
            for directory in (root, upstream):
                (directory / path).parent.mkdir(parents=True)
            (upstream / path).write_text(official)
            (root / path).write_text(projected)
            self.assertEqual(policy.baseline_errors(root, upstream, [path]), [])
            for mutation in (
                projected.replace(policy.V8_ARCHIVE_STEP, ""),
                projected.replace("if: runner.os == 'Linux'\n", "if: false\n"),
                projected.replace("target: ${{ inputs.target }}", "target: wrong"),
            ):
                with self.subTest(mutation=mutation):
                    (root / path).write_text(mutation)
                    self.assertTrue(policy.baseline_errors(root, upstream, [path]))

    def test_missing_command_and_new_skip_condition_are_drift(self):
        path = ".github/workflows/rust-ci.yml"
        official = (
            "jobs:\n  shear:\n    steps:\n      - run: cargo shear --deny-warnings\n"
        )
        mutations = (
            official.replace("      - run: cargo shear --deny-warnings\n", ""),
            official.replace("      - run:", "      - if: false\n        run:"),
            official.replace("--deny-warnings", "--deny-warnings || true"),
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "fork"
            upstream = Path(temp) / "upstream"
            for directory in (root, upstream):
                (directory / path).parent.mkdir(parents=True)
            (upstream / path).write_text(official)
            for mutation in mutations:
                with self.subTest(mutation=mutation):
                    (root / path).write_text(mutation)
                    self.assertTrue(policy.baseline_errors(root, upstream, [path]))
            (root / path).write_text(official)
            self.assertEqual(policy.baseline_errors(root, upstream, [path]), [])

    def test_full_ci_keeps_amd64_fan_in_and_removes_other_platform_jobs(self):
        source = (
            "jobs:\n  tests_macos_aarch64:\n    run: macos\n"
            "  tests_linux_x64_remote:\n    run: linux\n"
            "  tests_linux_arm64:\n    run: arm\n"
            "  tests_windows_x64:\n    run: windows\n"
            "  results:\n    needs:\n      - tests_linux_x64_remote\n      - tests_linux_arm64\n"
            "      - tests_macos_aarch64\n      - tests_windows_x64\n"
            "    run: summarize\n"
        )
        projected = policy.linux_projection(
            ".github/workflows/rust-ci-full.yml", source
        )
        self.assertIn("tests_linux_x64_remote", projected)
        self.assertNotIn("tests_linux_arm64", projected)
        self.assertIn("run: summarize", projected)
        self.assertNotIn("tests_macos_aarch64", projected)
        self.assertNotIn("tests_windows_x64", projected)

    def test_full_ci_removes_arm64_only_conditions(self):
        source = (
            "jobs:\n  lint_build:\n"
            "    env:\n"
            "      USE_SCCACHE: ${{ (startsWith(matrix.runner, 'windows') || (matrix.runner == 'macos-15-xlarge' && matrix.target == 'x86_64-apple-darwin')) && 'false' || 'true' }}\n"
            "    steps:\n"
            "      - if: ${{ matrix.target == 'x86_64-unknown-linux-musl' || matrix.target == 'aarch64-unknown-linux-musl'}}\n"
        )
        projected = policy.linux_projection(
            ".github/workflows/rust-ci-full.yml", source
        )
        self.assertIn('USE_SCCACHE: "true"', projected)
        self.assertNotIn("aarch64", projected)
        self.assertNotIn("macos-15", projected)
        self.assertNotIn("windows", projected)


class BazelResourcePolicy(unittest.TestCase):
    def test_postmerge_caller_must_allow_the_v8_child_read_permission(self):
        path = ".github/workflows/postmerge-ci.yml"
        source = (
            "on:\n  push:\n    branches: [main]\n"
            "jobs:\n  v8-canary:\n    name: v8-canary\n"
            "    uses: ./.github/workflows/v8-canary.yml\n"
        )
        projected = policy.linux_projection(path, source)
        self.assertIn("workflow_dispatch:", projected)
        self.assertIn("actions: read", projected)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "root"
            upstream = Path(temp) / "upstream"
            for directory, content in ((root, projected), (upstream, source)):
                file = directory / path
                file.parent.mkdir(parents=True)
                file.write_text(content)
            self.assertEqual(policy.baseline_errors(root, upstream, [path]), [])
            for original in ("  workflow_dispatch:\n", "      actions: read\n"):
                with self.subTest(original=original):
                    (root / path).write_text(projected.replace(original, ""))
                    self.assertTrue(policy.baseline_errors(root, upstream, [path]))

    def test_setup_bazel_must_preserve_and_verify_the_resource_policy(self):
        path = ".github/actions/prepare-bazel-ci/action.yml"
        source = (
            "        output-base: ${{ steps.setup_ci.outputs.bazel-output-base }}\n"
        )
        projected = policy.linux_projection(path, source)
        self.assertIn("bazelrc:", projected)
        self.assertIn("verify_bazel_resources.py", projected)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "root"
            upstream = Path(temp) / "upstream"
            for directory, content in ((root, projected), (upstream, source)):
                file = directory / path
                file.parent.mkdir(parents=True)
                file.write_text(content)
            self.assertEqual(policy.baseline_errors(root, upstream, [path]), [])
            for original in (
                "        bazelrc:",
                "verify_bazel_resources.py",
                "bazel_resource_usage.py watch",
            ):
                with self.subTest(original=original):
                    (root / path).write_text(projected.replace(original, "disabled"))
                    self.assertTrue(policy.baseline_errors(root, upstream, [path]))

    def test_cold_build_budget_keeps_all_bazel_commands(self):
        source = (
            "jobs:\n  test:\n    timeout-minutes: 30\n"
            "    steps:\n      - run: bazel test //...\n"
            "      - name: Upload Bazel execution logs\n"
        )
        projected = policy.linux_projection(".github/workflows/bazel.yml", source)
        self.assertIn("timeout-minutes: 360", projected)
        self.assertIn("run: bazel test //...", projected)
        self.assertIn("bazel_resource_usage.py report", projected)


class RequiredGate(unittest.TestCase):
    def test_unsupported_architectures_cannot_return_to_custom_matrices(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            shutil.copytree(
                policy.ROOT / ".github/workflows", root / ".github/workflows"
            )
            self.assertEqual(policy.coverage_errors(root), [])
            for name in ("codefx-source-smoke.yml", "codefx-platform-release.yml"):
                path = root / ".github/workflows" / name
                original = path.read_text()
                path.write_text(
                    original
                    + "\n          - runner: ubuntu-24.04-arm\n            target: aarch64-unknown-linux-musl\n"
                )
                self.assertTrue(policy.coverage_errors(root))
                path.write_text(original)

    def setUp(self):
        self.blocking = (policy.ROOT / ".github/workflows/blocking-ci.yml").read_text()

    def test_all_current_checks_are_required(self):
        self.assertEqual(policy.gate_errors(self.blocking), [])

    def test_disconnected_bazel_cargo_or_sdk_cannot_pass(self):
        for job in ("bazel", "linux-cargo", "sdk"):
            with self.subTest(job=job):
                weakened = self.blocking.replace(f"      - {job}\n", "")
                self.assertTrue(policy.gate_errors(weakened))
                weakened = self.blocking.replace(
                    f"uses: ./.github/workflows/{'codefx-linux-cargo' if job == 'linux-cargo' else job}.yml",
                    "uses: ./.github/workflows/rust-ci.yml",
                )
                self.assertTrue(policy.gate_errors(weakened))

    def test_required_call_cannot_ignore_failure_or_run_conditionally(self):
        for job in ("bazel", "sdk"):
            for condition in ("if: false", "continue-on-error: true"):
                weakened = self.blocking.replace(
                    f"  {job}:\n", f"  {job}:\n    {condition}\n"
                )
                self.assertTrue(policy.gate_errors(weakened))

    def test_required_coverage_is_preserved(self):
        self.assertEqual(policy.coverage_errors(policy.ROOT), [])

    def test_sdk_cannot_use_a_package_without_a_successful_producer(self):
        weakened = self.blocking.replace(
            "needs: [ci-policy, codefx-source-smoke]", "needs: ci-policy"
        )
        self.assertTrue(policy.gate_errors(weakened))

    def test_terminal_gate_cannot_be_skipped_after_failure(self):
        weakened = self.blocking.replace("    if: ${{ always() }}\n", "")
        self.assertTrue(policy.gate_errors(weakened))


if __name__ == "__main__":
    unittest.main()
