#!/usr/bin/env python3
"""Install and run a native package built from the current CI revision.

The installer fixture redirects downloads to the newly built archive. Neither
the archive nor the executables are fixtures; no published release is reused.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import tomllib

from release_package import verify
from test_install_sh import run_installer_in


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--target", required=True)
    args = parser.parse_args()
    version = tomllib.loads(Path("codex-rs/Cargo.toml").read_text())["workspace"][
        "package"
    ]["version"]
    archive = args.directory / f"codex-package-{args.target}.tar.gz"
    verify(archive, args.target, version)
    checksum = args.directory / "codex-package_SHA256SUMS"
    with archive.open("rb") as archive_file:
        archive_digest = hashlib.file_digest(archive_file, "sha256").hexdigest()
    checksum.write_text(f"{archive_digest}  {archive.name}\n")
    metadata = json.dumps(
        {
            "tag_name": f"rust-v{version}",
            "assets": [
                {"name": archive.name, "digest": f"sha256:{archive_digest}"},
                {
                    "name": checksum.name,
                    "digest": "sha256:" + hashlib.sha256(checksum.read_bytes()).hexdigest(),
                },
            ],
        }
    )
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    (args.directory / f"codefx-build-{args.target}.json").write_text(
        json.dumps(
            {
                "source_commit": source,
                "target": args.target,
                "version": version,
                "archive_sha256": archive_digest,
            },
            indent=2,
        )
        + "\n"
    )
    with tempfile.TemporaryDirectory(prefix="codefx native install ") as temp:
        root = Path(temp)
        for replacement in (True, False):
            result, requests = run_installer_in(
                root,
                version,
                archive_path=archive.resolve(),
                checksum_path=checksum.resolve(),
                metadata_json=metadata,
                replacement_wrapper=replacement,
            )
            if result.returncode:
                raise RuntimeError(result.stdout + result.stderr)
            if replacement and not any(archive.name in url for url in requests):
                raise RuntimeError("Installer did not fetch the current source archive")
            binary = root / "install-bin/codex"
            output = subprocess.check_output([str(binary), "--version"], text=True)
            if output.strip() != f"codefx {version}":
                raise RuntimeError(f"Unexpected installed version: {output}")
        env = os.environ | {"CODEX_HOME": str(root / "codex-home")}
        subprocess.run(
            [str(binary), "app-server", "daemon", "update", "--help"],
            env=env,
            check=True,
            timeout=30,
        )
        standalone = root / "codex-home/packages/standalone"
        if (standalone / ".transaction").exists():
            raise RuntimeError("Installer left an unfinished transaction")
    print(f"Current source {source}: {args.target} package and installation verified")


if __name__ == "__main__":
    main()
