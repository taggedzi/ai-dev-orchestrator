"""Artifact and execution-boundary checks; no upstream package or network used."""

import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research.validation.gsd_export import (
    COMMIT,
    INTEGRITY,
    TARBALL_URL,
    check_metadata,
    environment,
    unpack,
    verify_archive,
)
from research.validation.store import Hold


def metadata():
    return {
        "name": "@opengsd/gsd-core",
        "version": "1.21.0",
        "gitHead": COMMIT,
        "engines": {"node": ">=24.0.0"},
        "dist": {"tarball": TARBALL_URL, "integrity": INTEGRITY},
    }


def archive(path, entries):
    with tarfile.open(path, "w:gz") as output:
        for name, kind, data in entries:
            info = tarfile.TarInfo(name)
            info.type = kind
            if kind == tarfile.REGTYPE:
                info.size = len(data)
                output.addfile(info, io.BytesIO(data))
            else:
                info.linkname = "../../outside"
                output.addfile(info)


class GsdExportTests(unittest.TestCase):
    def test_metadata_requires_reviewed_commit_engine_url_and_integrity(self):
        raw = json.dumps(metadata()).encode()
        self.assertEqual(check_metadata(raw)["gitHead"], COMMIT)
        for change in [
            {"gitHead": "different"},
            {"engines": {"node": ">=22"}},
            {"name": "another-package"},
            {"version": "1.22.0"},
            {
                "dist": {
                    "tarball": "https://elsewhere.invalid/package",
                    "integrity": INTEGRITY,
                }
            },
            {"dist": {"tarball": TARBALL_URL, "integrity": "sha512-different"}},
        ]:
            with self.assertRaises(Hold):
                check_metadata(json.dumps(metadata() | change).encode())
        with self.assertRaises(ValueError):
            check_metadata(b'{"version":"1.21.0","version":"2"}')

    def test_extraction_and_independent_archive_inventory_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "package.tgz"
            archive(
                path, [("package/bin/tool.cjs", tarfile.REGTYPE, b"trusted source\n")]
            )
            result = unpack(path, root)
            self.assertEqual(
                (root / "package/bin/tool.cjs").read_bytes(), b"trusted source\n"
            )
            self.assertEqual(result, unpack(path))
            self.assertEqual(result["files"], 1)
            with self.assertRaises(FileExistsError):
                unpack(path, root)

    def test_archive_rejects_escapes_aliases_links_duplicates_and_special_files(self):
        cases = [
            [(name, tarfile.REGTYPE, b"x")]
            for name in [
                "/absolute",
                "package/../escape",
                "package/a\\b",
                "package/C:alias",
                "package/NUL",
                "package/trailing.",
                "package/trailing ",
                "other-root/file",
            ]
        ]
        cases += [
            [("package/a", kind, b"")]
            for kind in [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE]
        ]
        cases += [
            [
                ("package/a", tarfile.REGTYPE, b"1"),
                ("package/a", tarfile.REGTYPE, b"2"),
            ],
            [
                ("package/A/x", tarfile.REGTYPE, b"1"),
                ("package/a/y", tarfile.REGTYPE, b"2"),
            ],
        ]
        for entries in cases:
            with (
                self.subTest(entries=entries),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary)
                path = root / "package.tgz"
                archive(path, entries)
                target = root / "extract"
                target.mkdir()
                with self.assertRaises((Hold, ValueError)):
                    unpack(path, target)
                self.assertFalse((root / "escape").exists())

    def test_fixed_archive_integrity_rejects_unreviewed_bytes(self):
        with self.assertRaises(Hold):
            verify_archive(b"different package")

    def test_query_environment_excludes_credentials_and_node_injection(self):
        with patch.dict(
            "os.environ",
            {
                "OPENAI_API_KEY": "synthetic-secret",
                "NODE_OPTIONS": "--require=unsafe",
                "GSD_PROJECT_ROOT": "other-project",
                "GIT_CONFIG": "other-config",
                "PATH": "trusted-tool-path",
                "SYSTEMROOT": "system-root",
            },
            clear=True,
        ):
            result = environment(Path("isolated-home"))
        for key in ["OPENAI_API_KEY", "NODE_OPTIONS", "GSD_PROJECT_ROOT", "GIT_CONFIG"]:
            self.assertNotIn(key, result)
        self.assertEqual(result["PATH"], "trusted-tool-path")
        self.assertEqual(result["NODE_DISABLE_COMPILE_CACHE"], "1")
        self.assertEqual(result["HOME"], "isolated-home")


if __name__ == "__main__":
    unittest.main()
