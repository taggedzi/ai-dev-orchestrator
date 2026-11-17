#!/usr/bin/env python3
"""Bounded marker writer for the isolated M1-11 Linux fixture."""

import argparse
import os
import stat
import time
from pathlib import Path
from uuid import UUID


MARKERS = Path("/fixture-effect/markers.log")
RELEASE = Path("/fixture-control/release")
WAIT_SECONDS = 30


def record(operation: UUID, phase: str) -> None:
    entry = f"{operation} {phase}\n".encode("ascii")
    flags = os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK
    fd = os.open(MARKERS, flags)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("marker target must be a regular file")
        if os.write(fd, entry) != len(entry):
            raise OSError("short marker write")
        os.fsync(fd)
    finally:
        os.close(fd)


def wait_for_release(operation: UUID, deadline: float) -> bool:
    expected = f"{operation}\n".encode("ascii")
    while time.monotonic() < deadline:
        try:
            with RELEASE.open("rb") as gate:
                if gate.read(len(expected) + 1) == expected:
                    return True
        except FileNotFoundError:
            pass
        time.sleep(0.05)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("append", "cancel"))
    parser.add_argument("operation", type=UUID)
    args = parser.parse_args()
    deadline = time.monotonic() + WAIT_SECONDS

    record(args.operation, "effect")
    if args.mode == "append":
        return 0 if wait_for_release(args.operation, deadline) else 124

    child = os.fork()
    if child == 0:
        record(args.operation, "child-ready")
        if not wait_for_release(args.operation, deadline):
            return 124
        record(args.operation, "child-late")
        return 0

    _, status = os.waitpid(child, 0)
    exit_code = os.waitstatus_to_exitcode(status)
    return exit_code if exit_code >= 0 else 128 - exit_code


if __name__ == "__main__":
    raise SystemExit(main())
