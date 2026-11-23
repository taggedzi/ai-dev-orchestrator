"""Actual controller for owner-bound Python-only startup qualification tests."""

import json
import os
import sys
import time
import traceback
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

workspace = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(workspace))
sys.path.insert(0, str(workspace / "tests"))
from research.validation import frontend_start as start
from research.validation.store import Hold, Store
from research.validation.transfer_commands import canonical, digest
from research.validation.windows_readonly import _run
from tests.fixtures.frontend_start_support import NoInputLocks
from tests.test_boot_preconditions import snapshot

root = Path(sys.argv[1])
request = json.loads((root / "controller.request.json").read_bytes())
grant, receipts, mode = request["grant"], request["receipts"], request["mode"]


def retain_error(kind, value, trace):
    (root / "controller.error.txt").write_text(
        "".join(traceback.format_exception(kind, value, trace)), encoding="utf-8"
    )


sys.excepthook = retain_error
original = start.frontend._FrontendProcess


def factory(exe, args):
    assert exe == Path(sys.executable).resolve()
    assert args == ["--startvm", grant["boot"]["target"]["vm_uuid"], "--vrde", "off"]
    if mode == "flood":
        actual = [
            "-I",
            "-B",
            "-c",
            "import sys,time;sys.stdout.write('x'*70000);sys.stdout.flush();time.sleep(30)",
        ]
    else:
        actual = [
            "-I",
            "-B",
            str(Path(__file__).with_name("frontend_family.py")),
            str(root),
            "0",
        ]
    family = original(exe, actual)
    if mode == "lost-resume-ack":
        resume = family.resume

        def lost(gate):
            resume(gate)
            raise Hold("test-only lost native Python resume acknowledgement")

        family.resume = lost
    return family


with closing(Store(root / "owner.sqlite")) as store:
    calls = []

    def probe():
        calls.append(1)
        if mode == "deny-gate" and len(calls) == 2:
            store.fence("test-only final suspended gate revocation")
        return snapshot(grant["boot"])

    with (
        patch.object(start, "_InputLocks", NoInputLocks),
        patch.object(start.frontend, "HEADLESS", Path(sys.executable).resolve()),
        patch.object(
            start.frontend, "HEADLESS_SHA256", digest(Path(sys.executable).read_bytes())
        ),
        patch.object(start.frontend, "_FrontendProcess", factory),
    ):
        adapter = start._PreparedStart(store, probe)
        try:
            raw = canonical(grant)
            try:
                adapter.start(raw, digest(raw), *map(canonical, receipts))
            except Hold:
                if mode not in {"lost-resume-ack", "deny-gate"}:
                    raise
            if mode not in {"flood", "unsettled", "lost-resume-ack", "deny-gate"}:
                end = time.monotonic() + 5
                while (
                    len(list(root.glob("family-*.json"))) < 3
                    and adapter.terminal is None
                    and time.monotonic() < end
                ):
                    time.sleep(0.01)
                members = adapter.family.members()
                leaf = json.loads((root / "family-2.json").read_bytes())
                frame = snapshot(grant["boot"])
                frame["machine"] = frame["machine"].replace(b'"poweroff"', b'"running"')
                frame["session"] = {
                    "vm_uuid": grant["boot"]["target"]["vm_uuid"],
                    "state_before": "Locked",
                    "state_after": "Locked",
                    "pid": leaf["pid"],
                }
                adapter.observe(frame)
                query = _run(
                    Path(sys.executable),
                    ["-I", "-B", "-c", "print('query')"],
                    time.time_ns() + 4 * 10**9,
                    time.monotonic_ns() + 4 * 10**9,
                )
                start.owner.publish(
                    root / "controller.ready.json",
                    canonical(
                        {
                            "members": members,
                            "query_reaped": query["exit"] == 0
                            and query["job_active_processes"] == 0,
                            "guest_ready": False,
                        }
                    ),
                )
                if mode == "abrupt":
                    os._exit(0)
                if mode == "graceful":
                    (root / "allow.surrogate.stop").write_text(
                        "Python surrogate exit after original stop effect"
                    )
                    adapter.request_owner_stop()
            end = time.monotonic() + 10
            while adapter.terminal is None and time.monotonic() < end:
                time.sleep(0.01)
            result = adapter.close()
            start.owner.publish(root / "controller.terminal.json", canonical(result))
        finally:
            adapter.close()
