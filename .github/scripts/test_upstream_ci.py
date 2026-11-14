"""Regression coverage for accidentally weakened Linux CI gates."""

from pathlib import Path
import tempfile
import unittest

import check_upstream_ci as policy


class LinuxProjection(unittest.TestCase):
    def test_linux_matrices_keep_commands_and_drop_other_platforms(self):
        source = (
            "jobs:\n  test:\n    strategy:\n      matrix:\n        include:\n"
            "          - os: macos-15-xlarge\n            target: aarch64-apple-darwin\n"
            "          - os: ubuntu-24.04\n            target: x86_64-unknown-linux-gnu\n"
            "          - os: windows-latest\n            target: x86_64-pc-windows-msvc\n"
            "    steps:\n      - run: bazel test //...\n"
        )
        projected = policy.linux_projection(".github/workflows/bazel.yml", source)
        self.assertIn("target: x86_64-unknown-linux-gnu", projected)
        self.assertIn("run: bazel test //...", projected)
        self.assertNotIn("target: aarch64-apple-darwin", projected)
        self.assertNotIn("target: x86_64-pc-windows-msvc", projected)

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

    def test_full_ci_keeps_linux_fan_in_and_removes_platform_jobs(self):
        source = (
            "jobs:\n  tests_macos_aarch64:\n    run: macos\n"
            "  tests_linux_arm64:\n    run: linux\n"
            "  tests_windows_x64:\n    run: windows\n"
            "  results:\n    needs:\n      - tests_linux_arm64\n"
            "      - tests_macos_aarch64\n      - tests_windows_x64\n"
            "    run: summarize\n"
        )
        projected = policy.linux_projection(
            ".github/workflows/rust-ci-full.yml", source
        )
        self.assertIn("tests_linux_arm64", projected)
        self.assertIn("run: summarize", projected)
        self.assertNotIn("tests_macos_aarch64", projected)
        self.assertNotIn("tests_windows_x64", projected)


class RequiredGate(unittest.TestCase):
    def setUp(self):
        self.blocking = (policy.ROOT / ".github/workflows/blocking-ci.yml").read_text()

    def test_all_current_checks_are_required(self):
        self.assertEqual(policy.gate_errors(self.blocking), [])

    def test_disconnected_bazel_or_sdk_cannot_pass(self):
        for job in ("bazel", "sdk"):
            with self.subTest(job=job):
                weakened = self.blocking.replace(f"      - {job}\n", "")
                self.assertTrue(policy.gate_errors(weakened))
                weakened = self.blocking.replace(
                    f"uses: ./.github/workflows/{job}.yml",
                    "uses: ./.github/workflows/rust-ci.yml",
                )
                self.assertTrue(policy.gate_errors(weakened))

    def test_required_call_cannot_ignore_failure_or_run_conditionally(self):
        for condition in ("if: false", "continue-on-error: true"):
            weakened = self.blocking.replace("  sdk:\n", f"  sdk:\n    {condition}\n")
            self.assertTrue(policy.gate_errors(weakened))

    def test_terminal_gate_cannot_be_skipped_after_failure(self):
        weakened = self.blocking.replace("    if: ${{ always() }}\n", "")
        self.assertTrue(policy.gate_errors(weakened))


if __name__ == "__main__":
    unittest.main()
