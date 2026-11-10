#!/usr/bin/env python3
"""Bound disposable Bazel CAS snapshots before uploading them to Actions cache."""

import argparse
import os
from pathlib import Path


def bound_cache(root: Path, max_bytes: int) -> tuple[int, int]:
    if not root.exists():
        return 0, 0
    entries = []
    for directory, _, filenames in os.walk(root):
        for filename in filenames:
            path = Path(directory) / filename
            if path.is_symlink():
                continue
            try:
                stat = path.stat()
            except FileNotFoundError:
                continue
            entries.append(
                (max(stat.st_atime_ns, stat.st_mtime_ns), str(path), stat.st_size)
            )
    total = sum(size for _, _, size in entries)
    removed = 0
    for _, name, size in sorted(entries):
        if total <= max_bytes:
            break
        try:
            Path(name).unlink()
        except FileNotFoundError:
            continue
        removed += 1
        total -= size
    return removed, total


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--max-gib", type=int, default=2)
    args = parser.parse_args()
    if args.max_gib < 1:
        parser.error("--max-gib must be positive")
    removed, retained = bound_cache(args.path, args.max_gib * 1024 ** 3)
    print(
        f"Bazel cache: removed {removed} files; retained {retained / (1024**3):.2f} GiB"
    )
