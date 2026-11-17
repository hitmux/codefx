#!/usr/bin/env python3
"""Record resource headroom during CI, including failures before cache upload."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def sample() -> dict:
    usage = shutil.disk_usage(os.environ["GITHUB_WORKSPACE"])
    return {
        "time": time.time(),
        "disk_total": usage.total,
        "disk_free": usage.free,
    }


def report(path: Path) -> None:
    samples = [sample()]
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                samples.append(json.loads(line))
            except json.JSONDecodeError:
                # A cancelled writer can leave an incomplete final sample.
                continue
    minimum = min(item["disk_free"] for item in samples) / 1024**3
    message = (
        f"Bazel runner minimum free disk: {minimum:.2f} GiB ({len(samples)} samples)"
    )
    print(message)
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as stream:
        stream.write(f"\n{message}\n")
    subprocess.run(["df", "-h", os.environ["GITHUB_WORKSPACE"]], check=True)
    subprocess.run(["free", "-h"], check=True)
    for directory in (
        os.environ["CI_BUILD_ROOT"],
        str(Path.home() / ".cache/bazel-disk-cache"),
    ):
        if Path(directory).exists():
            subprocess.run(["du", "-h", "--max-depth=1", directory], check=False)


def main() -> None:
    directory = Path(os.environ["RUNNER_TEMP"]) / "bazel-execution-logs"
    directory.mkdir(exist_ok=True)
    path = directory / "resources.jsonl"
    if sys.argv[1:] == ["watch"]:
        with path.open("a", buffering=1) as stream:
            while True:
                stream.write(json.dumps(sample()) + "\n")
                time.sleep(15)
    elif sys.argv[1:] == ["report"]:
        report(path)
    else:
        raise SystemExit("Expected watch or report")


if __name__ == "__main__":
    main()
