"""Coverage and fault tests for the hosted-runner CI adaptations."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from select_cargo_ci_packages import DEDICATED, partition

ROOT = Path(__file__).resolve().parents[2]


class CargoPartition(unittest.TestCase):
    def metadata(self):
        names = list(DEDICATED) + [f"codex-fixture-{i}" for i in range(100)]
        return {
            "workspace_members": names,
            "packages": [{"id": name, "name": name} for name in names]
            + [{"id": "dependency", "name": "external-dependency"}],
        }

    def test_every_workspace_package_is_tested_exactly_once(self):
        metadata = self.metadata()
        groups = partition(metadata)
        assigned = [name for names in groups.values() for name in names]
        self.assertCountEqual(assigned, metadata["workspace_members"])
        self.assertEqual(len(assigned), len(set(assigned)))
        for name, shard in DEDICATED.items():
            self.assertEqual(groups[shard], [name])
        metadata["packages"].reverse()
        self.assertEqual(groups, partition(metadata))

    def test_incomplete_metadata_and_ambiguous_names_fail(self):
        metadata = self.metadata()
        metadata["workspace_members"].append("missing")
        with self.assertRaises(ValueError):
            partition(metadata)
        metadata = self.metadata()
        metadata["packages"][1]["name"] = metadata["packages"][0]["name"]
        with self.assertRaises(ValueError):
            partition(metadata)


class VerifiedDownload(unittest.TestCase):
    def download(self, modes):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            curl = directory / "curl"
            curl.write_text(
                "#!/usr/bin/env python3\n"
                "import os, pathlib, sys\n"
                "args = sys.argv[1:]\n"
                "assert '--connect-timeout' in args and '--retry' in args\n"
                "url = args[args.index('--output') - 1]\n"
                "with open(os.environ['CALLS'], 'a') as calls: calls.write(url + '\\n')\n"
                "if url == 'offline': sys.exit(28)\n"
                "pathlib.Path(args[args.index('--output') + 1]).write_bytes(url.encode())\n"
            )
            curl.chmod(0o755)
            output = directory / "archive"
            output.write_bytes(b"previous")
            calls = directory / "calls"
            result = subprocess.run(
                [
                    "bash",
                    str(ROOT / ".github/scripts/download-verified.sh"),
                    str(output),
                    hashlib.sha256(b"verified").hexdigest(),
                    *modes,
                ],
                env=os.environ
                | {"PATH": f"{directory}:{os.environ['PATH']}", "CALLS": str(calls)},
                capture_output=True,
                text=True,
                timeout=10,
            )
            return (
                result.returncode,
                output.read_bytes(),
                calls.read_text().splitlines(),
                list(directory.glob("*.part.*")),
            )

    def test_network_failure_uses_verified_mirror(self):
        code, content, calls, partials = self.download(["offline", "verified"])
        self.assertEqual((code, content, calls, partials), (0, b"verified", ["offline", "verified"], []))

    def test_checksum_failure_does_not_promote_or_try_another_mirror(self):
        code, content, calls, partials = self.download(["tampered", "verified"])
        self.assertNotEqual(code, 0)
        self.assertEqual((content, calls, partials), (b"previous", ["tampered"], []))

    def test_all_sources_down_preserves_existing_file(self):
        code, content, calls, partials = self.download(["offline", "offline"])
        self.assertNotEqual(code, 0)
        self.assertEqual((content, calls, partials), (b"previous", ["offline", "offline"], []))


class AggregateResults(unittest.TestCase):
    def test_only_successful_nonempty_dependencies_pass(self):
        cases = [({}, False), ({"child": {"result": "success"}}, True)]
        cases.extend(
            ({"child": {"result": result}}, False)
            for result in ("failure", "cancelled", "skipped", "timed_out", "unknown")
        )
        for dependencies, accepted in cases:
            with self.subTest(dependencies=dependencies):
                result = subprocess.run(
                    ["python3", str(ROOT / ".github/scripts/check_ci_results.py")],
                    env=os.environ | {"NEEDS": json.dumps(dependencies)},
                    capture_output=True,
                    timeout=10,
                )
                self.assertEqual(result.returncode == 0, accepted)


if __name__ == "__main__":
    unittest.main()
