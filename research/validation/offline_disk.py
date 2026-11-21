"""Read a stopped base VDI and export a sparse GPT partition for debugfs.

Preparation utility only: no filesystem mounting, journal replay, or disk writes
to the source. Supports only the observed VDI 1.1 dynamic base-image layout.
"""

import argparse
import ctypes
import hashlib
import json
import os
import struct
import zlib
from pathlib import Path


class Disk:
    def __init__(self, file):
        self.file = file
        self.length = os.fstat(file.fileno()).st_size
        header = self.exact(0, 512)
        u32 = lambda offset: struct.unpack_from("<I", header, offset)[0]
        if (u32(64), u32(68), u32(76)) != (0xBEDA107F, 0x10001, 1):
            raise ValueError("only dynamic VDI 1.1 base images are supported")
        if u32(72) < 400 or any(header[424:456]) or u32(380) != 0:
            raise ValueError("unsupported VDI header, parent, or block extras")
        self.block = u32(376)
        self.size = struct.unpack_from("<Q", header, 368)[0]
        count, allocated = u32(384), u32(388)
        self.data = u32(344)
        if (
            self.block != 1024**2
            or self.size > 64 * 1024**3
            or self.size <= 0
            or count != (self.size + self.block - 1) // self.block
            or u32(340) < 72 + u32(72)
            or u32(340) + 4 * count > self.data
            or self.data + allocated * self.block > self.length
        ):
            raise ValueError("invalid or unsupported VDI bounds")
        self.map = struct.unpack("<" + "I" * count, self.exact(u32(340), 4 * count))
        used = [n for n in self.map if n < 0xFFFFFFFE]
        if (
            len(used) != allocated
            or len(set(used)) != allocated
            or any(n >= allocated for n in used)
        ):
            raise ValueError("invalid VDI block map")

    def exact(self, offset, size):
        if offset < 0 or size < 0 or offset + size > self.length:
            raise ValueError("source read outside file")
        self.file.seek(offset)
        data = self.file.read(size)
        if len(data) != size:
            raise ValueError("truncated source")
        return data

    def read(self, offset, size):
        if offset < 0 or size < 0 or offset + size > self.size:
            raise ValueError("virtual read outside disk")
        parts = []
        while size:
            number, within = divmod(offset, self.block)
            length = min(size, self.block - within)
            physical = self.map[number]
            parts.append(
                bytes(length)
                if physical >= 0xFFFFFFFE
                else self.exact(self.data + physical * self.block + within, length)
            )
            offset += length
            size -= length
        return b"".join(parts)

    def partition(self, number):
        header = bytearray(self.read(512, 512))
        if header[:8] != b"EFI PART":
            raise ValueError("GPT required")
        length, expected = struct.unpack_from("<II", header, 12)
        if length < 92 or length > 512:
            raise ValueError("invalid GPT header size")
        header[16:20] = bytes(4)
        if zlib.crc32(header[:length]) != expected:
            raise ValueError("GPT header checksum mismatch")
        lba, count, entry_size, crc = struct.unpack_from("<QIII", header, 72)
        if not 1 <= number <= count <= 256 or entry_size != 128:
            raise ValueError("unsupported GPT entry layout")
        entries = self.read(lba * 512, count * entry_size)
        if zlib.crc32(entries) != crc:
            raise ValueError("GPT entries checksum mismatch")
        entry = entries[(number - 1) * entry_size : number * entry_size]
        first, last = struct.unpack_from("<QQ", entry, 32)
        usable_first, usable_last = struct.unpack_from("<QQ", header, 40)
        if not any(entry[:16]) or not usable_first <= first <= last <= usable_last:
            raise ValueError("invalid GPT partition")
        if (last + 1) * 512 > self.size:
            raise ValueError("partition outside virtual disk")
        return first * 512, (last - first + 1) * 512


def sparse(file, length):
    if os.name == "nt":
        import msvcrt

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = msvcrt.get_osfhandle(file.fileno())
        api = kernel.DeviceIoControl
        api.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        api.restype = ctypes.c_int
        returned = ctypes.c_ulong()
        if not api(
            handle,
            0x900C4,
            None,
            0,
            None,
            0,
            ctypes.byref(returned),
            None,
        ):
            raise OSError(ctypes.get_last_error(), "cannot mark destination sparse")
        # The Windows CRT ftruncate path zero-fills the extended range. Set EOF
        # directly on the sparse file so unwritten regions remain holes.
        position = kernel.SetFilePointerEx
        position.argtypes = [
            ctypes.c_void_p,
            ctypes.c_longlong,
            ctypes.c_void_p,
            ctypes.c_ulong,
        ]
        position.restype = ctypes.c_int
        eof = kernel.SetEndOfFile
        eof.argtypes = [ctypes.c_void_p]
        eof.restype = ctypes.c_int
        if not position(handle, length, None, 0) or not eof(handle):
            raise OSError(ctypes.get_last_error(), "cannot extend sparse destination")
    else:
        file.truncate(length)


def export(source, destination, number, expected_hash):
    source, destination = Path(source), Path(destination)
    with source.open("rb") as original:
        before = hashlib.file_digest(original, "sha256").hexdigest()
        if before != expected_hash:
            raise ValueError("source differs from stopped-image receipt")
        disk = Disk(original)
        start, length = disk.partition(number)
        if disk.read(start + 1080, 2) != b"\x53\xef":
            raise ValueError("selected partition is not an ext filesystem")
        copied = 0
        chunks = hashlib.sha256()
        with destination.open("x+b", buffering=0) as output:
            sparse(output, length)
            offset = 0
            while offset < length:
                size = min(disk.block - (start + offset) % disk.block, length - offset)
                physical = disk.map[(start + offset) // disk.block]
                if physical < 0xFFFFFFFE:
                    data = disk.read(start + offset, size)
                    output.seek(offset)
                    if output.write(data) != size:
                        raise OSError("partial output write")
                    output.seek(offset)
                    if output.read(size) != data:
                        raise OSError("copy verification failed")
                    chunks.update(struct.pack("<QQ", offset, size) + data)
                    copied += size
                offset += size
            output.flush()
            os.fsync(output.fileno())
        original.seek(0)
        after = hashlib.file_digest(original, "sha256").hexdigest()
        if after != before:
            raise ValueError("source changed during read-only export; discard copy")
    return {
        "source_sha256_before": before,
        "source_sha256_after": after,
        "partition": number,
        "partition_offset": start,
        "logical_bytes": length,
        "copied_bytes": copied,
        "allocated_ranges_sha256": chunks.hexdigest(),
        "classification": "read-only stopped-disk copy; unreplayed filesystem, not a clean-image qualification",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--partition", type=int, default=2)
    parser.add_argument("--source-sha256", required=True)
    args = parser.parse_args()
    result = export(args.source, args.destination, args.partition, args.source_sha256)
    args.destination.with_suffix(".receipt.json").write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
