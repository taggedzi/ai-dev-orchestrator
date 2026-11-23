"""Actual nested-job controller for Python-only containment tests."""

import json
import os
import sys
import time
import traceback
from pathlib import Path

workspace = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(workspace))
from research.validation.frontend_process import _FrontendProcess
from research.validation.owner_process import publish
from research.validation.windows_readonly import _run

root, mode = Path(sys.argv[1]), sys.argv[2]


def retain_error(kind, value, trace):
    (root / "controller.error.txt").write_text(
        "".join(traceback.format_exception(kind, value, trace)), encoding="utf-8"
    )


sys.excepthook = retain_error
family = _FrontendProcess(
    sys.executable,
    ["-I", "-B", str(Path(__file__).with_name("frontend_family.py")), str(root), "0"],
)
try:
    family.resume(lambda _: None)
    end = time.monotonic() + 6
    while len(list(root.glob("family-*.json"))) < 3 and time.monotonic() < end:
        time.sleep(0.01)
    members = family.members()
    assert (
        len(
            [
                p
                for p in members
                if Path(p["image"]).resolve() == Path(sys.executable).resolve()
            ]
        )
        == 3
    )
    query = _run(
        Path(sys.executable),
        ["-I", "-B", "-c", "print('bounded query')"],
        time.time_ns() + 4 * 10**9,
        time.monotonic_ns() + 4 * 10**9,
    )
    assert query["exit"] == 0 and query["job_active_processes"] == 0
    publish(
        root / "controller.ready.json",
        json.dumps(
            {"members": members, "query_exit": query["exit"], "query_job_reaped": True}
        ).encode(),
    )
    if mode == "abrupt":
        os._exit(0)
    end = time.monotonic() + 8
    while not (root / "controller.finish").exists() and time.monotonic() < end:
        time.sleep(0.01)
    (root / "family.finish").write_text("finish")
    end = time.monotonic() + 3
    while family.job.active() and time.monotonic() < end:
        time.sleep(0.01)
    publish(root / "controller.terminal.json", json.dumps(family.retire()).encode())
finally:
    family.retire()
    (root / "family.stderr").write_bytes(family.stderr)
