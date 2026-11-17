"""Partition workspace packages before compilation, without dropping tests."""

import argparse
import hashlib
import json
import sys

SHARDS = ("core", "tui", "app-server", "other-0", "other-1", "other-2")
DEDICATED = {
    "codex-core": "core",
    "codex-tui": "tui",
    "codex-app-server": "app-server",
}


def partition(metadata):
    members = set(metadata["workspace_members"])
    packages = [p for p in metadata["packages"] if p["id"] in members]
    if {p["id"] for p in packages} != members:
        raise ValueError("Cargo metadata omitted workspace members")
    names = [p["name"] for p in packages]
    if len(names) != len(set(names)):
        raise ValueError("Ambiguous workspace package names")
    result = {shard: [] for shard in SHARDS}
    for name in sorted(names):
        shard = DEDICATED.get(name)
        if shard is None:
            bucket = int.from_bytes(hashlib.sha256(name.encode()).digest()[:4]) % 3
            shard = f"other-{bucket}"
        result[shard].append(name)
    if any(not names for names in result.values()):
        raise ValueError("Empty Cargo test shard")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard", choices=SHARDS, required=True)
    args = parser.parse_args()
    groups = partition(json.load(sys.stdin))
    print("\n".join(groups[args.shard]))
    print(json.dumps(groups, sort_keys=True), file=sys.stderr)


if __name__ == "__main__":
    main()
