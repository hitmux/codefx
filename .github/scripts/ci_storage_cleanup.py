#!/usr/bin/env python3
"""Bound disposable Actions storage without touching published releases."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from datetime import datetime, timezone

REPO = "hitmux/codefx"
LOG_PREFIXES = ("bazel-execution-logs-", "cargo-timings-", "v8-canary-")
LEGACY_CACHE = re.compile(
    r"(windows|macos|codefx-bazel-actions-v1-|bazel-action-|bazel-cache-|codefx-native-.*-v1-)",
    re.IGNORECASE,
)


def api_pages(endpoint: str):
    raw = subprocess.check_output(
        ["gh", "api", "--paginate", f"repos/{REPO}/{endpoint}?per_page=100"],
        text=True,
    )
    decoder = json.JSONDecoder()
    pos = 0
    while pos < len(raw):
        while pos < len(raw) and raw[pos].isspace():
            pos += 1
        if pos >= len(raw):
            break
        page, pos = decoder.raw_decode(raw, pos)
        yield page


def age_days(value: str, now: datetime) -> float:
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (now - timestamp).total_seconds() / 86400


def stale_cache(item: dict, now: datetime) -> bool:
    key = item.get("key", "")
    access = item.get("last_accessed_at") or item.get("created_at")
    if not access:
        return False
    minimum_days = 4 if LEGACY_CACHE.search(key) else 14
    return age_days(access, now) >= minimum_days


def stale_artifact(item: dict, now: datetime) -> bool:
    name = item.get("name", "")
    created = item.get("created_at")
    return bool(
        created and name.startswith(LOG_PREFIXES) and age_days(created, now) >= 10
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="delete eligible objects")
    parser.add_argument("--max-delete", type=int, default=100)
    args = parser.parse_args()
    if not 1 <= args.max_delete <= 500:
        parser.error("--max-delete must be 1..500")
    if args.apply and (
        os.getenv("GITHUB_ACTIONS") != "true"
        or os.getenv("GITHUB_REPOSITORY") != REPO
        or os.getenv("GITHUB_EVENT_NAME") not in {"schedule", "workflow_dispatch"}
    ):
        parser.error(
            "Destructive mode is only allowed in the scheduled/manual repository workflow"
        )

    now = datetime.now(timezone.utc)
    candidates = []
    for page in api_pages("actions/caches"):
        for obj in page.get("actions_caches", []):
            if stale_cache(obj, now):
                candidates.append(("cache", obj))
    for page in api_pages("actions/artifacts"):
        for obj in page.get("artifacts", []):
            if stale_artifact(obj, now):
                candidates.append(("artifact", obj))

    candidates.sort(
        key=lambda item: (
            item[1].get("last_accessed_at") or item[1].get("created_at") or ""
        )
    )
    eligible = candidates[: args.max_delete]
    total_bytes = 0
    for kind, obj in eligible:
        ident = obj["id"]
        name = obj.get("name") or obj.get("key", "")
        size = obj.get("size_in_bytes", 0)
        total_bytes += size
        print(
            f"{'DELETE' if args.apply else 'DRY-RUN'} {kind}: "
            f"{ident} {size / 1024**2:.1f} MiB {name}"
        )
        if args.apply:
            endpoint = "actions/caches" if kind == "cache" else "actions/artifacts"
            subprocess.run(
                ["gh", "api", "--method", "DELETE", f"repos/{REPO}/{endpoint}/{ident}"],
                check=True,
            )

    message = (
        f"Actions storage cleanup: mode={'apply' if args.apply else 'dry-run'}, "
        f"eligible={len(candidates)}, selected={len(eligible)}, "
        f"bytes={total_bytes / 1024**3:.2f} GiB. "
        "GitHub Release assets, provenance, and native transfer artifacts are excluded."
    )
    print(message)
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as stream:
            stream.write(f"### Codefx CI storage maintenance\n\n{message}\n")


if __name__ == "__main__":
    main()
