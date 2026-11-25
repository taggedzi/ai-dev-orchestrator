import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research.validation.offline_repo import (
    check_command,
    checked_bundle,
    inventory,
    new_root,
    package_union,
    relative_name,
    sha,
    sources_list,
    write_json,
)


class OfflineRepositoryTests(unittest.TestCase):
    def test_conflicting_shared_package_or_archive_path_holds(self):
        original = {
            "name": "alpha",
            "version": "1",
            "architecture": "amd64",
            "bytes": 1,
            "sha256": "a" * 64,
            "archive_path": "pool/main/a/alpha/alpha_1_amd64.deb",
        }
        catalog = {"archives": [original]}
        self.assertEqual(len(package_union([catalog, catalog])), 1)
        for changed in (
            {"version": "2"},
            {"sha256": "b" * 64},
            {"name": "beta"},
            {"archive_path": "pool/main/../alpha.deb"},
        ):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                package_union([catalog, {"archives": [{**original, **changed}]}])

    def test_paths_cannot_escape_or_name_alternate_streams(self):
        for name in (
            "../outside",
            "/absolute",
            "pool//file",
            "pool/./file",
            "pool\\file",
            "pool/file:stream",
            "pool/file\ncommand",
        ):
            with self.subTest(name=name), self.assertRaises(ValueError):
                relative_name(name)
        self.assertEqual(
            str(relative_name("pool/main/a/alpha_1%3a1_amd64.deb")),
            "pool/main/a/alpha_1%3a1_amd64.deb",
        )

    def test_native_command_boundary_rejects_install_download_and_generic_pins(self):
        check_command(["apt-get", "update", "--error-on=any"])
        check_command(
            [
                "apt-get",
                "--simulate",
                "--no-install-recommends",
                "--no-remove",
                "install",
                "alpha=1:2-3",
            ]
        )
        for args in (
            ["apt-get", "install", "alpha=1"],
            ["apt-get", "download", "alpha=1"],
            ["apt-get", "update", "--allow-insecure-repositories"],
            [
                "apt-get",
                "--simulate",
                "--no-install-recommends",
                "--no-remove",
                "install",
                "alpha",
            ],
            ["sh", "-c", "anything"],
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                check_command(args)

    def test_manifest_pin_and_payload_mutations_are_independent_holds(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = root / "payload"
            payload.write_bytes(b"retained-data")
            value = {
                "format": "mcli1-offline-repository-v1",
                "status": "prepared-not-installed",
                "installation_approval": None,
                "qualifies_runtime": False,
                "files": inventory(root),
            }
            write_json(root / "manifest.json", value)
            digest = sha((root / "manifest.json").read_bytes())
            checked_bundle(root, digest)
            with self.assertRaises(ValueError):
                checked_bundle(root, "0" * 64)
            payload.write_bytes(b"changed")
            with self.assertRaises(ValueError):
                checked_bundle(root, digest)
            payload.write_bytes(b"retained-data")
            (root / "extra").write_bytes(b"unreviewed")
            with self.assertRaises(ValueError):
                checked_bundle(root, digest)
            value["installation_approval"] = "invented-authority"
            write_json(root / "manifest.json", value)
            with self.assertRaises(ValueError):
                checked_bundle(root, sha((root / "manifest.json").read_bytes()))

    def test_output_cannot_modify_an_existing_evidence_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            frozen = base / "frozen"
            frozen.mkdir()
            with patch("research.validation.offline_repo.LOCAL", base):
                with self.assertRaises(ValueError):
                    new_root(frozen / "new-child")
                self.assertFalse((frozen / "new-child").exists())
                with self.assertRaises(FileExistsError):
                    new_root(frozen)
                self.assertTrue(new_root(base / "new-attempt").is_dir())

    def test_sources_are_local_and_keep_signature_checks(self):
        root = Path(Path.cwd().anchor) / "public-packages"
        text = sources_list(root)
        self.assertEqual(len(text.splitlines()), 3)
        self.assertIn((root / "repo").as_uri(), text)
        self.assertIn("signed-by=", text)
        self.assertNotIn("trusted=yes", text)
        self.assertNotIn("https:", text)
