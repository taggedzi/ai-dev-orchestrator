"""Image preparation pins and data-only intake controls; no Docker or network."""

import io
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research.validation import image_context as image
from research.validation.bundle import digest
from research.validation.store import Hold


class ImageContextTests(unittest.TestCase):
    def test_reviewed_inputs_and_base_image_digests_are_bound(self):
        value = image.inputs()
        self.assertEqual(len(value["assets"]), 7)
        self.assertEqual(value["terminal_backend"], "subprocess")
        dockerfile = image.INPUTS.with_name("MinimalAgentServer.Dockerfile").read_text()
        for base in value["base_images"]:
            self.assertIn("@sha256:" + base["manifest_sha256"], dockerfile)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "inputs.json"
            path.write_bytes(image.INPUTS.read_bytes() + b" ")
            with patch.object(image, "INPUTS", path), self.assertRaises(Hold):
                image.inputs()

    def test_source_intake_refuses_links_and_path_escapes(self):
        cases = [
            (image.PREFIX + "/openhands-sdk/link", tarfile.SYMTYPE),
            (image.PREFIX + "/openhands-sdk/../escape", tarfile.REGTYPE),
            (image.PREFIX + "/openhands-sdk/test.", tarfile.REGTYPE),
        ]
        for name, kind in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "source.tar.gz"
                with tarfile.open(path, "w:gz") as archive:
                    info = tarfile.TarInfo(name)
                    info.type = kind
                    info.linkname = "../../outside"
                    info.size = 1 if kind == tarfile.REGTYPE else 0
                    archive.addfile(info, io.BytesIO(b"x") if info.size else None)
                with self.assertRaises((ValueError, Hold)):
                    image.source_files(path)

    def test_asset_hash_mismatch_and_redirect_are_refused(self):
        row = {
            "url": "https://nodejs.org/pinned",
            "filename": "node",
            "bytes": 4,
            "sha256": digest(b"safe"),
        }
        with patch.object(image.urllib.request, "build_opener") as factory:
            factory.return_value.open.return_value = io.BytesIO(b"evil")
            with self.assertRaises(Hold):
                image.fetch_asset(row)
        with self.assertRaises(Hold):
            image.ArtifactRedirect().redirect_request(
                None, None, 302, "", {}, "https://unapproved.invalid/asset"
            )


if __name__ == "__main__":
    unittest.main()
