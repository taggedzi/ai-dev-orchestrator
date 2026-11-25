"""Synthetic VDI/GPT checks; never open a VM or a real filesystem."""

import hashlib
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from research.validation.offline_disk import Disk, export

BLOCK = 1024**2


def image(path):
    virtual = bytearray(8 * BLOCK)
    entries = bytearray(128 * 128)
    entries[128:144] = b"p" * 16
    struct.pack_into("<QQ", entries, 128 + 32, 4096, 12287)
    virtual[1024 : 1024 + len(entries)] = entries
    header = bytearray(512)
    header[:8] = b"EFI PART"
    struct.pack_into("<I", header, 12, 92)
    struct.pack_into(
        "<QQQQ", header, 24, 1, len(virtual) // 512 - 1, 34, len(virtual) // 512 - 34
    )
    struct.pack_into("<QIII", header, 72, 2, 128, 128, zlib.crc32(entries))
    struct.pack_into("<I", header, 16, zlib.crc32(header[:92]))
    virtual[512:1024] = header
    virtual[2 * BLOCK + 1080 : 2 * BLOCK + 1082] = b"\x53\xef"
    virtual[3 * BLOCK : 3 * BLOCK + 5] = b"hello"
    vdi = bytearray(512)
    for offset, value in [
        (64, 0xBEDA107F),
        (68, 0x10001),
        (72, 400),
        (76, 1),
        (340, 512),
        (344, BLOCK),
        (376, BLOCK),
        (384, 8),
        (388, 3),
    ]:
        struct.pack_into("<I", vdi, offset, value)
    struct.pack_into("<Q", vdi, 368, len(virtual))
    with path.open("wb") as output:
        output.write(vdi)
        output.write(
            struct.pack(
                "<8I",
                0,
                0xFFFFFFFF,
                1,
                2,
                0xFFFFFFFE,
                0xFFFFFFFF,
                0xFFFFFFFF,
                0xFFFFFFFF,
            )
        )
        output.seek(BLOCK)
        output.write(virtual[:BLOCK] + virtual[2 * BLOCK : 4 * BLOCK])
    return virtual


class OfflineDiskTests(unittest.TestCase):
    def test_base_map_reads_allocated_zero_and_cross_block_ranges(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "disk.vdi"
            virtual = image(path)
            with path.open("rb") as file:
                disk = Disk(file)
                for offset, size in [
                    (0, 512),
                    (BLOCK - 10, 30),
                    (BLOCK, BLOCK),
                    (4 * BLOCK, BLOCK),
                    (3 * BLOCK, 5),
                ]:
                    self.assertEqual(
                        disk.read(offset, size), virtual[offset : offset + size]
                    )
                self.assertEqual(disk.partition(2), (2 * BLOCK, 4 * BLOCK))
                for offset, size in [(-1, 1), (disk.size, 1), (0, -1)]:
                    with self.assertRaises(ValueError):
                        disk.read(offset, size)

    def test_parent_corrupt_map_and_gpt_checksums_are_rejected(self):
        for offset, value in [
            (424, b"x"),
            (512 + 8, struct.pack("<I", 0)),
            (BLOCK + 512 + 16, b"\xff"),
            (BLOCK + 1024 + 128, b"x"),
        ]:
            with (
                self.subTest(offset=offset),
                tempfile.TemporaryDirectory() as temporary,
            ):
                path = Path(temporary) / "disk.vdi"
                image(path)
                with path.open("r+b") as file:
                    file.seek(offset)
                    file.write(value)
                with path.open("rb") as file, self.assertRaises(ValueError):
                    Disk(file).partition(2)

    def test_export_matches_partition_preserves_source_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, destination = root / "disk.vdi", root / "root.ext4"
            virtual = image(source)
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            result = export(source, destination, 2, before)
            self.assertEqual(destination.read_bytes(), virtual[2 * BLOCK : 6 * BLOCK])
            self.assertLess(result["copied_bytes"], result["logical_bytes"])
            self.assertEqual(result["source_sha256_after"], before)
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
            with self.assertRaises(FileExistsError):
                export(source, destination, 2, before)
            with self.assertRaises(ValueError):
                export(source, root / "wrong.ext4", 2, "0" * 64)
            self.assertFalse((root / "wrong.ext4").exists())


if __name__ == "__main__":
    unittest.main()
