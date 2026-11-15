"""Reject stale candidates and changed artifacts before executing SDK binaries."""

import unittest

from prepare_sdk_package import validate


class CandidateProvenance(unittest.TestCase):
    def test_only_exact_source_target_version_and_digest_are_accepted(self):
        metadata = {
            "source_commit": "a" * 40,
            "target": "x86_64-unknown-linux-musl",
            "version": "0.166.0",
            "archive_sha256": "b" * 64,
        }
        args = tuple(metadata.values())
        validate(metadata, *args)
        for key in metadata:
            with self.subTest(field=key), self.assertRaises(ValueError):
                validate(metadata | {key: "different"}, *args)


if __name__ == "__main__":
    unittest.main()
