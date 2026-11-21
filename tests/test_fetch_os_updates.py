import hashlib
import json
import unittest

from research.validation.fetch_os_updates import check_download_command, checked_catalog


class OsArchiveRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.catalog = {
            "schema_version": 1,
            "installation_approval": None,
            "archives": [
                {
                    "name": "nftables",
                    "version": "1.0.9-1ubuntu0.1",
                    "architecture": "amd64",
                    "bytes": 123,
                    "sha256": "a" * 64,
                }
            ],
            "unique_archives": 1,
            "archive_bytes": 123,
            "profiles": {
                "guard": {"package_names": ["nftables"]},
                "executor": {"package_names": []},
            },
        }

    def check(self):
        raw = json.dumps(self.catalog).encode()
        return checked_catalog(raw, hashlib.sha256(raw).hexdigest())

    def test_only_exact_archive_download_commands_are_allowed(self):
        check_download_command(
            [
                "apt-get",
                "download",
                "libc6=2.39-0ubuntu8.12",
                "zlib1g=1:1.3.dfsg-3.1ubuntu2.3",
            ]
        )
        for args in (
            ["apt-get", "install", "nftables=1.0"],
            ["apt-get", "--download-only", "install", "nftables=1.0"],
            ["apt-get", "download", "nftables"],
            ["apt-get", "download", "-oAPT::Get::AllowUnauthenticated=true"],
            ["apt-get", "download"],
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                check_download_command(args)

    def test_catalog_cannot_change_after_external_review(self):
        self.assertEqual(self.check()["archive_bytes"], 123)
        raw = json.dumps(self.catalog).encode()
        with self.assertRaises(ValueError):
            checked_catalog(raw, "0" * 64)

    def test_profile_inventory_and_size_union_are_required(self):
        self.catalog["profiles"]["guard"]["package_names"] = []
        with self.assertRaises(ValueError):
            self.check()
        self.catalog["profiles"]["guard"]["package_names"] = ["nftables"]
        self.catalog["archive_bytes"] = 124
        with self.assertRaises(ValueError):
            self.check()
        self.catalog["archive_bytes"] = 123
        self.catalog["archives"] *= 2
        self.catalog["unique_archives"] = 2
        with self.assertRaises(ValueError):
            self.check()

    def test_unsupported_package_identity_or_architecture_is_rejected(self):
        for field, bad in (
            ("name", "../secret"),
            ("version", "1.0; command"),
            ("architecture", "arm64"),
            ("sha256", "unknown"),
            ("bytes", 2 * 1024**3),
        ):
            original = self.catalog["archives"][0][field]
            self.catalog["archives"][0][field] = bad
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.check()
            self.catalog["archives"][0][field] = original


if __name__ == "__main__":
    unittest.main()
