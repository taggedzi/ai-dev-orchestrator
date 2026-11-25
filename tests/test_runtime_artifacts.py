"""Archive retrieval integrity and refusal controls; no upstream downloads."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research.validation import runtime_artifacts as runtime
from research.validation.bundle import digest
from research.validation.store import Hold


class RuntimeArtifactTests(unittest.TestCase):
    def test_reviewed_catalog_rejects_changed_bytes(self):
        value = runtime.catalog()
        self.assertEqual(len(value["artifacts"]), 186)
        self.assertEqual(sum(r["bytes"] for r in value["artifacts"]), 142502826)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "catalog.json"
            path.write_bytes(runtime.CATALOG.read_bytes() + b" ")
            with patch.object(runtime, "CATALOG", path), self.assertRaises(Hold):
                runtime.catalog()

    def test_wrong_archive_bytes_never_become_retained_inputs(self):
        row = {
            "filename": "example.whl",
            "url": "https://files.pythonhosted.org/packages/example.whl",
            "bytes": 4,
            "sha256": digest(b"safe"),
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "archives").mkdir()
            for raw in [b"evil", b"oversized"]:
                with patch.object(runtime.urllib.request, "build_opener") as factory:
                    factory.return_value.open.return_value = io.BytesIO(raw)
                    with self.assertRaises(Hold):
                        runtime.collect_one(root, row)
            self.assertEqual(list((root / "archives").iterdir()), [])
            with patch.object(runtime.urllib.request, "build_opener") as factory:
                factory.return_value.open.return_value = io.BytesIO(b"safe")
                observation = runtime.collect_one(root, row)
            self.assertEqual(observation["sha256"], digest(b"safe"))
            with patch.object(runtime.urllib.request, "build_opener") as factory:
                factory.return_value.open.return_value = io.BytesIO(b"safe")
                with self.assertRaises(FileExistsError):
                    runtime.collect_one(root, row)

    def test_failed_retrieval_retains_hold_and_does_not_reuse_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            root = workspace / ".local/validation/inputs"
            with (
                patch.object(runtime, "WORKSPACE", workspace),
                patch.object(runtime, "rooted", lambda p: Path(p)),
                patch.object(
                    runtime,
                    "catalog",
                    return_value={"artifacts": [{"filename": "bad"}]},
                ),
                patch.object(runtime, "collect_one", side_effect=Hold("wrong hash")),
            ):
                with self.assertRaises(Hold):
                    runtime.collect(root, "")
                self.assertFalse(root.exists())
                receipt = runtime.collect(root, "test-only-approval")
                self.assertEqual(receipt["status"], "hold")
                self.assertEqual(receipt["errors"][0]["filename"], "bad")
                self.assertEqual(
                    json.loads((root / "receipt.json").read_bytes()), receipt
                )
                with self.assertRaises(FileExistsError):
                    runtime.collect(root, "test-only-approval")
                with self.assertRaises(ValueError):
                    runtime.collect(workspace / "elsewhere", "test-only-approval")


if __name__ == "__main__":
    unittest.main()
