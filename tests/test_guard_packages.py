import unittest
from pathlib import PurePosixPath

from research.validation.guard_packages import (
    additions,
    configuration,
    package_record,
    paragraphs,
)


class GuardPackageTests(unittest.TestCase):
    def test_new_only_resolution_and_upgrade_removal_holds(self):
        new = "Inst libnftables1 (1.0.9-1ubuntu0.1 Ubuntu:24.04/noble-updates [amd64])\nInst nftables (1.0.9-1ubuntu0.1 Ubuntu:24.04/noble-updates [amd64])\nConf nftables (1.0.9-1ubuntu0.1 Ubuntu:24.04/noble-updates [amd64])"
        self.assertEqual(
            [r["name"] for r in additions(new)], ["libnftables1", "nftables"]
        )
        for unsupported in (
            new + "\nRemv libc6 [2.39]",
            new + "\nPurg other [1.0]",
            "Inst nftables [1.0.9-1build1] (1.0.9-1ubuntu0.1 Ubuntu:24.04/noble-updates [amd64])",
            new
            + "\nInst nftables (1.0.9-1ubuntu0.1 Ubuntu:24.04/noble-updates [amd64])",
            "Inst other (1.0 Ubuntu:24.04/noble [amd64])",
            "",
        ):
            with self.subTest(unsupported=unsupported), self.assertRaises(ValueError):
                additions(unsupported)

    def test_deb822_continuations_are_data_and_duplicates_hold(self):
        self.assertEqual(
            paragraphs("Package: nftables\nDescription: first\n second\n"),
            [{"Package": "nftables", "Description": "first\n second"}],
        )
        for invalid in (
            " orphan",
            "Package: nftables\nPackage: injected",
            "not a field",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                paragraphs(invalid)

    def test_package_identity_and_signed_digest_constraints(self):
        metadata = (
            "Package: nftables\nVersion: 1.0.9-1build1\nArchitecture: amd64\nFilename: pool/main/n/nftables/nftables_1.0.9-1build1_amd64.deb\nSize: 12345\nSHA256: "
            + "a" * 64
            + "\nDepends: libnftables1 (= 1.0.9-1build1)\n"
        )
        record = package_record(metadata, "nftables", "1.0.9-1build1")
        self.assertEqual(record["bytes"], 12345)
        self.assertEqual(record["sha256"], "a" * 64)
        for source in (
            metadata.replace("Architecture: amd64", "Architecture: arm64"),
            metadata.replace("pool/main/n/nftables/", "pool/main/../nftables/"),
            metadata.replace("pool/main/", "https://other.invalid/"),
            metadata.replace("12345", "999999999"),
            metadata.replace("SHA256: " + "a" * 64, "SHA256: abc"),
            metadata + "\n" + metadata.replace("Size: 12345", "Size: 12346"),
            metadata.replace("Version: 1.0.9-1build1", "Version: 1.0.10"),
        ):
            with self.subTest(source=source), self.assertRaises(ValueError):
                package_record(source, "nftables", "1.0.9-1build1")

    def test_config_value_cannot_inject_apt_hooks_or_sources(self):
        self.assertIn(
            'Dir::State::status "/tmp/guard/target-status";',
            configuration(PurePosixPath("/tmp/guard")),
        )
        for path in (
            '/tmp/guard"; DPkg::Pre-Invoke "bad',
            "/tmp/guard\nnew",
            "/tmp/guard\\new",
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                configuration(PurePosixPath(path))


if __name__ == "__main__":
    unittest.main()
