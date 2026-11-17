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
        (root / "MODULE.bazel").write_text('module(name = "resource_probe")\n')
        (root / ".bazelrc").write_text(f"common --disk_cache={cache}\n")
        (root / "BUILD.bazel").write_text(
            'genrule(name = "probe", outs = ["probe.txt"], '
            'cmd = "echo verified > $@")\n'
        )
        bazel = ["bazel", f"--output_base={root / 'output'}", "--announce_rc"]
        try:
            result = subprocess.run(
                [*bazel, "build", "//:probe"],
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
                "--local_resources=cpu=2",
                "--local_resources=memory=4096",
            ):
                if option not in result.stderr:
                    raise RuntimeError(f"Effective rc policy missing {option}")
            if cache.exists() and any(cache.iterdir()):
                raise RuntimeError("setup-bazel re-enabled the disk action cache")
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
            subprocess.run(
                [*bazel, "shutdown"], cwd=root, timeout=30, check=False
            )
    print("Verified effective Bazel CPU/memory caps and disabled disk action cache")


if __name__ == "__main__":
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise SystemExit("This build probe runs only in GitHub Actions")
    verify()
