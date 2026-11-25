import hashlib
import io
import lzma
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research.validation.engine_metadata import (
    engine_rows,
    fetch_index,
    index_record,
    main,
)


def identity(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


class Response(io.BytesIO):
    status = 200

    def geturl(self):
        return "https://archive.ubuntu.com/index"


class Opener:
    def __init__(self, data):
        self.data = data

    def open(self, url, timeout):
        return Response(self.data)


class EngineMetadataTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.raw = b"Package: docker.io\nVersion: 1\n\n"
        self.compressed = lzma.compress(self.raw)
        self.row = {
            "suite": "noble",
            "url": "https://archive.ubuntu.com/index",
            "compressed": identity(self.compressed),
            "expanded": identity(self.raw),
        }

    def tearDown(self):
        self.temporary.cleanup()

    def test_both_signed_identities_are_checked_and_no_code_is_executed(self):
        result = fetch_index(self.row, self.root, Opener(self.compressed))
        self.assertEqual(result.read_bytes(), self.raw)
        self.assertEqual(engine_rows(result)[0]["Package"], "docker.io")
        self.assertEqual(
            {p.name for p in self.root.iterdir()},
            {"noble-Packages", "noble-Packages.xz"},
        )

    def test_wrong_hash_and_oversized_compressed_or_expanded_data_hold(self):
        for index, change in enumerate(
            (
                {"compressed": {**identity(self.compressed), "sha256": "0" * 64}},
                {
                    "compressed": {
                        **identity(self.compressed),
                        "bytes": len(self.compressed) - 1,
                    }
                },
                {"expanded": {**identity(self.raw), "bytes": len(self.raw) - 1}},
                {"expanded": {**identity(self.raw), "sha256": "0" * 64}},
            )
        ):
            root = self.root / str(index)
            root.mkdir()
            with self.subTest(index=index), self.assertRaises(ValueError):
                fetch_index({**self.row, **change}, root, Opener(self.compressed))

    def test_redirect_and_unexpected_extra_expansion_are_not_accepted(self):
        with (
            patch.object(
                Response, "geturl", return_value="https://other.invalid/index"
            ),
            self.assertRaises(ValueError),
        ):
            fetch_index(self.row, self.root, Opener(self.compressed))
        root = self.root / "concatenated"
        root.mkdir()
        data = self.compressed + lzma.compress(b"unexpected")
        with self.assertRaises(ValueError):
            fetch_index({**self.row, "compressed": identity(data)}, root, Opener(data))

    def test_valid_concatenated_empty_stream_and_padding_are_accepted(self):
        data = self.compressed + b"\0" * 4 + lzma.compress(b"") + b"\0" * 8
        result = fetch_index(
            {**self.row, "compressed": identity(data)}, self.root, Opener(data)
        )
        self.assertEqual(result.read_bytes(), self.raw)
        invalid = self.compressed + b"\0"
        other = self.root / "bad-padding"
        other.mkdir()
        with self.assertRaises(ValueError):
            fetch_index(
                {**self.row, "compressed": identity(invalid)}, other, Opener(invalid)
            )

    def test_signed_release_selection_rejects_wrong_suite_duplicate_and_large_entries(
        self,
    ):
        release = {
            "Origin": "Ubuntu",
            "Codename": "noble",
            "Suite": "noble-updates",
            "SHA256": f"{'a' * 64} 10 universe/binary-amd64/Packages.xz\n {'b' * 64} 20 universe/binary-amd64/Packages",
        }
        self.assertIn("/by-hash/SHA256/" + "a" * 64, index_record(release)["url"])
        for changes in (
            {"Suite": "jammy"},
            {"Origin": "Other"},
            {
                "SHA256": release["SHA256"]
                + f"\n {'c' * 64} 10 universe/binary-amd64/Packages.xz"
            },
            {"SHA256": release["SHA256"].replace(" 10 ", f" {65 * 1024**2} ")},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                index_record({**release, **changes})

    def test_final_package_without_blank_separator_is_retained(self):
        path = self.root / "Packages"
        path.write_bytes(self.raw.rstrip())
        self.assertEqual(engine_rows(path)[0]["Version"], "1")

    def test_default_invocation_has_no_collection_or_network_action(self):
        with (
            patch("sys.argv", ["engine_metadata"]),
            patch("research.validation.engine_metadata.plan", return_value=[]),
            patch("research.validation.engine_metadata.collect") as collect,
            patch("sys.stdout", new_callable=io.StringIO) as output,
        ):
            main()
        collect.assert_not_called()
        self.assertIn('"mode": "preview"', output.getvalue())


if __name__ == "__main__":
    unittest.main()
