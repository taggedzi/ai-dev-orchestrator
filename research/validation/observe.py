"""Trusted-side marker observation and sealed synthetic source collection."""

import os
import time
from pathlib import Path
from uuid import UUID

from .bundle import digest, inventory, safe_path
from .store import Hold


def markers(path, operation):
    operation = str(UUID(str(operation)))
    path = Path(path)
    if path.is_symlink() or path.stat().st_size > 128 * 1024:
        raise Hold("invalid or oversized marker file")
    raw = path.read_bytes()
    if raw and not raw.endswith(b"\n"):
        raise Hold("incomplete marker line")
    phases = []
    for line in raw.decode("ascii").splitlines():
        parts = line.split(" ")
        if (
            len(parts) != 2
            or str(UUID(parts[0])) != parts[0]
            or parts[1] not in ("effect", "child-ready", "child-late")
        ):
            raise Hold("invalid marker grammar")
        if parts[0] == operation:
            phases.append(parts[1])
    return {
        "operation": operation,
        "phases": phases,
        "sha256": digest(raw),
        "bytes": len(raw),
    }


def wait_marker(path, operation, phase, seconds=5):
    if not 0 < seconds <= 30:
        raise ValueError("observer timeout must be in (0,30]")
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            result = markers(path, operation)
            if phase in result["phases"]:
                return result
        except FileNotFoundError:
            pass
        time.sleep(0.02)
    raise Hold("marker barrier not observed; fault must not fire")


def release_gate(directory, operation):
    """Publish one operation's gate; mount/observer independence is a host gate."""
    operation = str(UUID(str(operation)))
    root = Path(directory)
    if root.is_symlink() or not root.is_dir():
        raise Hold("invalid control directory")
    temporary = root / f"release-{operation}.tmp"
    with temporary.open("xb") as stream:
        stream.write((operation + "\n").encode("ascii"))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, root / "release")


def seal(source, destination, *, stop_receipt):
    """Use only after independently verified stop; caller supplies its evidence ID."""
    if not stop_receipt:
        raise Hold("missing independent stop receipt")
    root = Path(source)
    if root.is_symlink():
        raise Hold("source root is a link")
    files = inventory(root)
    if len(files) > 128 or sum(row["bytes"] for row in files.values()) > 10 * 1024**2:
        raise Hold("artifact limits")
    for name in files:
        if any(part.casefold() == ".git" for part in safe_path(name).parts):
            raise Hold("Git metadata must not enter the executor source copy")
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    for name, expected in files.items():
        data = root.joinpath(*safe_path(name).parts).read_bytes()
        if digest(data) != expected["sha256"]:
            raise Hold("source changed during sealed collection")
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        if os.name != "nt":
            target.chmod(0o755 if expected["mode"] == "100755" else 0o644)
    if inventory(root) != files or inventory(destination) != files:
        raise Hold("source changed or collection differs")
    return {"stop_receipt": stop_receipt, "files": files}
