import hashlib
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from research.validation.guard_packages import package_record
from research.validation.os_update_plan import (
    actions,
    check_apt_command,
    release_dates,
    verify_files,
)


class OsUpdatePlanTests(unittest.TestCase):
    def test_native_apt_commands_cannot_install_or_download(self):
        check_apt_command(["apt-get", "--version"])
        check_apt_command(
            ["apt-get", "--simulate", "--no-remove", "upgrade", "nftables"]
        )
        check_apt_command(
            ["apt-get", "--simulate", "--no-remove", "install", "base=1:1.0-2"]
        )
        for args in (
            ["apt-get", "install", "nftables"],
            ["apt-get", "--simulate", "--no-remove", "download", "nftables"],
            ["apt-get", "--simulate", "--no-remove", "--no-download", "upgrade"],
            [
                "apt-get",
                "--simulate",
                "--no-remove",
                "--allow-unauthenticated",
                "install",
                "nftables",
            ],
            [
                "apt-get",
                "--simulate",
                "--no-remove",
                "install",
                "-oAPT::Get::Simulate=false",
            ],
            ["apt-get", "--simulate", "--no-remove", "remove", "base"],
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                check_apt_command(args)

    def setUp(self):
        self.installed = {"base": "1:1.0-1"}
        self.executor = "Inst base [1:1.0-1] (1:1.0-2 Ubuntu:24.04/noble-updates [amd64]) []\nConf base (1:1.0-2 Ubuntu:24.04/noble-updates [amd64])\n1 upgraded, 0 newly installed, 0 to remove and 0 not upgraded."
        self.guard = self.executor.replace(
            "1 upgraded, 0 newly",
            "Inst nftables (1.0.9-1ubuntu0.1 Ubuntu:24.04/noble-updates [amd64])\nConf nftables (1.0.9-1ubuntu0.1 Ubuntu:24.04/noble-updates [amd64])\n1 upgraded, 1 newly",
        )

    def test_role_transactions_preserve_exact_start_and_configure_versions(self):
        executor, counts = actions(
            self.executor, self.installed, require_nftables=False
        )
        self.assertEqual(
            executor, [{"name": "base", "old_version": "1:1.0-1", "version": "1:1.0-2"}]
        )
        self.assertEqual(
            counts, {"upgrades": 1, "additions": 0, "removals": 0, "held_back": 0}
        )
        guard, counts = actions(self.guard, self.installed, require_nftables=True)
        self.assertEqual(counts["additions"], 1)
        self.assertIsNone(guard[-1]["old_version"])
        for text, require in ((self.executor, True), (self.guard, False)):
            with self.assertRaises(ValueError):
                actions(text, self.installed, require_nftables=require)

    def test_changed_start_or_incomplete_configure_cannot_be_called_ready(self):
        for changed in (
            self.executor.replace("[1:1.0-1]", "[1:1.0-0]"),
            self.executor.replace(" [1:1.0-1]", ""),
            self.executor.replace("Conf base (1:1.0-2", "Conf base (1:1.0-3"),
            self.executor.replace("Conf base", "Conf extra"),
            self.executor.replace(
                "Conf base (1:1.0-2 Ubuntu:24.04/noble-updates [amd64])\n", ""
            ),
            self.executor
            + "\nInst base [1:1.0-1] (1:1.0-2 Ubuntu:24.04/noble-updates [amd64])",
            self.executor + "\nConf base (1:1.0-2 Ubuntu:24.04/noble-updates [amd64])",
        ):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                actions(changed, self.installed, require_nftables=False)

    def test_removals_held_back_wrong_architecture_and_malformed_rows_hold(self):
        for changed in (
            self.executor + "\nRemv other [1.0]",
            self.executor + "\nPurg other [1.0]",
            self.executor.replace("0 not upgraded", "1 not upgraded"),
            self.executor.replace("1 upgraded", "2 upgraded"),
            self.executor.replace("Inst base", "Inst base:i386"),
            self.executor + "\nInst\tother (1.0 Ubuntu:24.04/noble [amd64])",
            self.executor + "\nInst",
            self.executor.replace("1:1.0-2", "1:1.0-1"),
        ):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                actions(changed, self.installed, require_nftables=False)

    def test_large_kernel_bound_is_explicit_and_narrow_download_default_stays(self):
        raw = (
            "Package: linux-image\nVersion: 1.0\nArchitecture: amd64\nFilename: pool/main/l/linux/image.deb\nSize: 9437184\nSHA256: "
            + "a" * 64
        )
        with self.assertRaises(ValueError):
            package_record(raw, "linux-image", "1.0")
        self.assertEqual(
            package_record(raw, "linux-image", "1.0", max_bytes=1024**3)["bytes"],
            9437184,
        )

    def test_retained_metadata_must_have_exact_inventory_and_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "index").write_bytes(b"signed index bytes")
            (root / "receipt.json").write_bytes(b"external digest covers this")
            expected = {
                "index": {
                    "bytes": 18,
                    "sha256": hashlib.sha256(b"signed index bytes").hexdigest(),
                }
            }
            verify_files(root, expected)
            (root / "extra").write_bytes(b"unindexed")
            with self.assertRaises(ValueError):
                verify_files(root, expected)
            (root / "extra").unlink()
            (root / "index").write_bytes(b"changed index byte")
            with self.assertRaises(ValueError):
                verify_files(root, expected)

    def test_signed_release_date_checks_do_not_accept_expired_or_future_data(self):
        now = datetime(2026, 11, 21, 20, tzinfo=timezone.utc)
        data = "Origin: Ubuntu\nSuite: noble-updates\nCodename: noble\nDate: Sat, 21 Nov 2026 19:00:00 +0000\nValid-Until: Sun, 22 Nov 2026 19:00:00 +0000\n"
        result = release_dates(data, now)
        self.assertEqual(result["suite"], "noble-updates")
        stable = data.replace("Suite: noble-updates", "Suite: noble").split(
            "Valid-Until:"
        )[0]
        self.assertIsNone(release_dates(stable, now)["valid_until"])
        for invalid in (
            data.replace("Origin: Ubuntu", "Origin: other"),
            data.replace("Sun, 22 Nov 2026", "Fri, 20 Nov 2026"),
            data.replace("Date: Sat, 21 Nov 2026", "Date: Sun, 22 Nov 2026"),
            data.replace("19:00:00 +0000", "19:00:00"),
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                release_dates(invalid, now)


if __name__ == "__main__":
    unittest.main()
