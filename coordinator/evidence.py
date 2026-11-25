"""Coordinator-owned content-addressed artifacts; never an executor write API."""

import hashlib
import os
import re
import tempfile
from pathlib import Path

from .domain import Conflict, require

MAX_ARTIFACT_BYTES = 32 * 1024 * 1024


class EvidenceStore:
    """Caller must protect this directory from executor and reviewer writes."""

    def __init__(self, root):
        path = Path(root).absolute()
        require(
            path.is_dir() and not path.is_symlink() and not path.is_junction(),
            "evidence directory must be an ordinary trusted directory",
        )
        self.root = path.resolve()

    @classmethod
    def create(cls, root):
        path = Path(root)
        path.mkdir(parents=True, exist_ok=False)
        return cls(path)

    def read(self, checksum):
        require(
            type(checksum) is str and re.fullmatch(r"[0-9a-f]{64}", checksum),
            "invalid evidence digest",
        )
        path = self.root / checksum
        require(
            path.is_file() and not path.is_symlink() and not path.is_junction(),
            "missing or linked evidence artifact",
            Conflict,
        )
        with path.open("rb") as stream:
            info = os.fstat(stream.fileno())
            require(info.st_nlink == 1, "linked evidence artifact", Conflict)
            require(info.st_size <= MAX_ARTIFACT_BYTES, "evidence artifact too large")
            raw = stream.read(MAX_ARTIFACT_BYTES + 1)
        require(
            len(raw) <= MAX_ARTIFACT_BYTES
            and hashlib.sha256(raw).hexdigest() == checksum,
            "evidence artifact changed or incomplete",
            Conflict,
        )
        return raw

    def put(self, raw):
        require(type(raw) is bytes, "evidence must be bytes")
        require(len(raw) <= MAX_ARTIFACT_BYTES, "evidence artifact too large")
        checksum = hashlib.sha256(raw).hexdigest()
        target = self.root / checksum
        # Write and sync a new file before atomic no-replace publication. A crash
        # can leave an unreferenced temporary file; it never replaces prior data.
        descriptor, temporary = tempfile.mkstemp(prefix="pending-", dir=self.root)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, target)
            except FileExistsError:
                pass
        finally:
            Path(temporary).unlink()
        require(self.read(checksum) == raw, "conflicting evidence bytes", Conflict)
        return {"sha256": checksum, "bytes": len(raw)}
