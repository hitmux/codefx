#!/usr/bin/env python3
"""Exercise the effective resource policy after setup-bazel rewrites its rc file."""

import os
from pathlib import Path
import subprocess
import tempfile


def verify() -> None:
    with tempfile.TemporaryDirectory(prefix="codefx-bazel-policy-") as temp:
        root = Path(temp)
        cache = root / "action-cache"
        # Bazelisk must exercise this checkout's pinned Bazel, not latest.
        (root / ".bazelversion").write_text(
            (Path(__file__).resolve().parents[2] / ".bazelversion").read_text()
        )
        (root / "MODULE.bazel").write_text('module(name = "resource_probe")\n')
        (root / ".bazelrc").write_text(f"common --disk_cache={cache}\n")
        (root / "BUILD.bazel").write_text(
            'load(":probe.bzl", "resource_test")\n'
            'genrule(name = "probe", outs = ["probe.txt"], '
            'cmd = "echo verified > $@")\n'
            'resource_test(name = "test_budget")\n'
        )
        (root / "probe.bzl").write_text(
            "def _impl(ctx):\n"
            '    out = ctx.actions.declare_file(ctx.label.name + ".sh")\n'
            "    ctx.actions.write(out, '#!/bin/sh\\nset -eu\\n"
            "test $RUST_TEST_THREADS = 2\\n', is_executable = True)\n"
            "    return [DefaultInfo(executable = out)]\n"
            "resource_test = rule(implementation = _impl, test = True)\n"
        )
        bazel = ["bazel", f"--output_base={root / 'output'}"]
        try:
            result = subprocess.run(
                [*bazel, "build", "--announce_rc", "//:probe"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=120,
                check=True,
            )
            # These options must survive setup-bazel and override the workspace
            # rc. The positive control below proves the cache probe is live.
            for option in (
                "--disk_cache=",
                "--local_resources=cpu=HOST_CPUS",
                "--local_resources=memory=4096",
            ):
                if option not in result.stderr:
                    raise RuntimeError(f"Effective rc policy missing {option}")
            if cache.exists() and any(cache.iterdir()):
                raise RuntimeError("setup-bazel re-enabled the disk action cache")
            result = subprocess.run(
                [*bazel, "test", "--announce_rc", "--test_output=errors", "//:test_budget"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=120,
                check=True,
            )
            for option in (
                "--local_test_jobs=1",
                "--test_env=RUST_TEST_THREADS=2",
            ):
                if option not in result.stderr:
                    raise RuntimeError(f"Effective test budget missing {option}")
            if cache.exists() and any(cache.iterdir()):
                raise RuntimeError("Test invocation re-enabled the disk action cache")
            # Force another action and explicitly enable caching as a control.
            (root / "BUILD.bazel").write_text(
                'genrule(name = "probe", outs = ["probe.txt"], '
                'cmd = "echo control > $@")\n'
            )
            subprocess.run(
                [*bazel, "build", f"--disk_cache={cache}", "//:probe"],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=120,
                check=True,
            )
            if not cache.exists() or not any(cache.iterdir()):
                raise RuntimeError("Disk cache positive control did not populate")
        except subprocess.CalledProcessError as error:
            # The isolated probe never has credentials in its command line.
            print(error.stdout)
            print(error.stderr)
            raise
        finally:
            subprocess.run([*bazel, "shutdown"], cwd=root, timeout=30, check=False)
    print("Verified Bazel CPU/memory/test budgets and disabled disk action cache")


if __name__ == "__main__":
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise SystemExit("This build probe runs only in GitHub Actions")
    verify()
