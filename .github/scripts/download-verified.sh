#!/usr/bin/env bash
# Transport failures may use a mirror; a checksum mismatch always fails closed.
set -euo pipefail

destination="${1:?destination required}"
expected="${2:?SHA256 required}"
shift 2
[[ "$expected" =~ ^[0-9a-f]{64}$ && $# -gt 0 ]]
mkdir -p "$(dirname "$destination")"
partial="${destination}.part.$$"
trap 'rm -f "$partial"' EXIT
for url in "$@"; do
  if curl --fail --silent --show-error --location \
    --connect-timeout 15 --max-time 180 \
    --retry 3 --retry-delay 2 --retry-max-time 240 --retry-connrefused \
    "$url" --output "$partial"; then
    printf '%s  %s\n' "$expected" "$partial" | sha256sum --check -
    mv "$partial" "$destination"
    exit 0
  fi
  rm -f "$partial"
done
echo 'All verified download sources failed' >&2
exit 1
