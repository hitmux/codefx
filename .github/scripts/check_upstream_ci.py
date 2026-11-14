#!/usr/bin/env python3
"""Compare retained Linux CI with the exact official source version.

Only platform removal and the explicit runner adaptations below are permitted.
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
    if name == "sdk.yml":
        text = re.sub(
            r"    runs-on:\n      group:.*\n      labels:.*\n",
            "    runs-on: ubuntu-24.04\n",
            text,
        )
        text = text.replace("timeout-minutes: 20", "timeout-minutes: 180")
    if name == "cargo-deny.yml":
        text = text.replace(
            "        with:\n          rust-version:",
            "        env:\n"
            "          CARGO_HOME: /github/home/cargo-home\n"
            '          CARGO_NET_GIT_FETCH_WITH_CLI: "true"\n'
            "        with:\n          rust-version:",
        )
    if name == "blob-size-policy.yml":
        text = text.replace(
            "      - uses: openai/fence@e017427978b91977d79a3023842166ab79b5b816 # pin@v0.12.2\n"
            "        with:\n          mode: audit\n",
            "",
        )
    if path == ".github/actions/setup-ci/action.yml":
        text = text.replace("meta/install-dotslash@", "facebook/install-dotslash@")
        text = text.replace("  steps:\n", "  steps:\n" + RUNNER_ADAPTER, 1)
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
        errors.append("CI required must depend on all official and Codefx checks")
    if "    if: ${{ always() }}" not in required:
        errors.append("CI required must report failures even when dependencies fail")
    if "run: python3 .github/scripts/check_ci_results.py" not in required:
        errors.append("CI required must reject skipped/cancelled dependencies")
    if "run: python3 .github/scripts/check_upstream_ci.py --upstream" not in jobs.get(
        "ci-policy", ""
    ):
        errors.append("The official baseline comparison must execute")
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
    print("All official Linux and Codefx checks are required.")


if __name__ == "__main__":
    main()
