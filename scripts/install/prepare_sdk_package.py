"""Verify candidate provenance before using a same-run native package in SDK CI."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tomllib


def validate(metadata, source, target, version, digest):
    expected = {
        "source_commit": source,
        "target": target,
        "version": version,
        "archive_sha256": digest,
    }
    if metadata != expected:
        raise ValueError("SDK package provenance does not match this candidate")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    target = "x86_64-unknown-linux-musl"
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    version = tomllib.loads(Path("codex-rs/Cargo.toml").read_text())["workspace"][
        "package"
    ]["version"]
    archive = args.directory / f"codex-package-{target}.tar.gz"
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    metadata = json.loads((args.directory / f"codefx-build-{target}.json").read_text())
    validate(metadata, source, target, version, digest)
    args.output.mkdir(parents=True, exist_ok=False)
    with tarfile.open(archive) as package:
        for member in package:
            if not (member.isfile() or member.isdir()):
                raise ValueError(f"Unexpected package member: {member.name}")
            if (
                member.name.startswith("/")
                or ".." in Path(member.name).parts
                or "\\" in member.name
            ):
                raise ValueError(f"Unsafe package member: {member.name}")
        package.extractall(args.output, filter="data")
    package_metadata = json.loads((args.output / "codex-package.json").read_text())
    if package_metadata["target"] != target or package_metadata["version"] != version:
        raise ValueError("SDK package target/version mismatch")
    for name in ("codex", "codex-code-mode-host", "codex-exec-server"):
        binary = args.output / "bin" / name
        with binary.open("rb") as stream:
            header = stream.read(20)
        if header[:5] != b"\x7fELF\x02" or header[18:20] != b"\x3e\x00":
            raise ValueError(f"Expected native x86_64 ELF binary: {name}")
        binary.chmod(0o755)
    with open(os.environ["GITHUB_ENV"], "a") as environment:
        environment.write(f"CODEX_EXEC_PATH={args.output.resolve()}/bin/codex\n")
    print(f"SDK uses verified candidate {source}: {digest}")


if __name__ == "__main__":
    main()
