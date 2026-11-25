"""Actual controller for owner-bound Python-only startup qualification tests."""

import json
import os
import subprocess
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
from research.validation import startup_qualification as qualification
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
original_prior = start.recovery_host.prior_snapshot
original_intervening = start.recovery_host.intervening_snapshot
original_latest = start.recovery_host.latest_snapshot


def prior_snapshot():
    if grant.get("format") == start.RECOVERY_FORMAT:
        return grant["recovery"]["prior"]  # Explicit synthetic prior-process facts.
    return original_prior()


def intervening_snapshot():
    if grant.get("format") == start.RECOVERY_FORMAT:
        return grant["recovery"]["intervening"]
    return original_intervening()


def latest_snapshot():
    if grant.get("format") == start.RECOVERY_FORMAT:
        return grant["recovery"]["latest"]
    return original_latest()


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
        frame = snapshot(grant["boot"])
        if grant.get("format") == start.RECOVERY_FORMAT:
            frame["machine"] = frame["machine"].replace(b'"poweroff"', b'"aborted"')
            frame["medium"] = frame["medium"].replace(b"locked write", b"created")
        return frame

    with (
        patch.object(start, "_InputLocks", NoInputLocks),
        patch.object(start.frontend, "HEADLESS", Path(sys.executable).resolve()),
        patch.object(
            start.frontend, "HEADLESS_SHA256", digest(Path(sys.executable).read_bytes())
        ),
        patch.object(start.frontend, "_FrontendProcess", factory),
        patch.object(start.recovery_host, "prior_snapshot", prior_snapshot),
        patch.object(start.recovery_host, "intervening_snapshot", intervening_snapshot),
        patch.object(start.recovery_host, "latest_snapshot", latest_snapshot),
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
                if grant.get("format") == start.RECOVERY_FORMAT:
                    initial = probe()
                    initial["session"] = {
                        "vm_uuid": grant["boot"]["target"]["vm_uuid"],
                        "state_before": "Unlocked",
                        "state_after": "Unlocked",
                        "pid": 0,
                    }
                    waiting = adapter.observe(initial)
                    assert adapter.joined is None
                    start.owner.publish(
                        root / "recovery.wait.json",
                        canonical(
                            {**waiting, "original_lease": adapter.packet["lease"]}
                        ),
                    )
                leaf = json.loads((root / "family-2.json").read_bytes())
                probe_stamp = time.monotonic_ns()
                progress = adapter.observe_startup_session(
                    {
                        "format": "mcli1-startup-session-probe-v1",
                        "observed_mono_ns": probe_stamp,
                        "finished_mono_ns": probe_stamp,
                        "session_raw": canonical(
                            {
                                "format": "mcli1-native-session-read-v1",
                                "version": start.session_observer.VERSION,
                                "revision": start.session_observer.REVISION,
                                "vm_uuid": grant["boot"]["target"]["vm_uuid"],
                                "state_before": 2,
                                "state_after": 2,
                                "machine_before": 11,
                                "machine_after": 11,
                                "pid": leaf["pid"],
                            }
                        ),
                    }
                )
                assert (
                    adapter.joined is None and progress["profile_observation_allowed"]
                )
                start.owner.publish(
                    root / "controller.probe.json",
                    canonical(
                        {
                            **progress,
                            "original_lease": adapter.packet["lease"],
                            "joined": False,
                        }
                    ),
                )
                frame = snapshot(grant["boot"])
                frame["machine"] = frame["machine"].replace(b'"poweroff"', b'"running"')
                frame["session"] = {
                    "vm_uuid": grant["boot"]["target"]["vm_uuid"],
                    "state_before": "Locked",
                    "state_after": "Locked",
                    "pid": leaf["pid"],
                }
                if mode == "graceful-contention":
                    writer = subprocess.Popen(
                        [
                            sys.executable,
                            "-I",
                            "-B",
                            str(Path(__file__).with_name("frontend_journal_writer.py")),
                            str(root),
                        ],
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        close_fds=True,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    end = time.monotonic() + 3
                    while (
                        not (root / "journal-writer.ready.json").exists()
                        and writer.poll() is None
                        and time.monotonic() < end
                    ):
                        time.sleep(0.005)
                    assert (root / "journal-writer.ready.json").exists()
                    writer_identity = start.host.process_identity(writer.pid)
                    note = adapter._journal_note

                    def release_writer(phase, stage, error=None, **facts):
                        note(phase, stage, error, **facts)
                        if (
                            phase == "session-bind"
                            and stage == "begin-failed"
                            and not (root / "journal-writer.release").exists()
                        ):
                            (root / "journal-writer.release").write_text(
                                "release known scratch writer"
                            )

                    adapter._journal_note = release_writer
                    adapter.observe(frame)
                    assert writer.wait(timeout=3) == 0
                    start.owner.publish(
                        root / "controller.journal.writer.json",
                        canonical(
                            {
                                "process": writer_identity,
                                "exit": 0,
                                "begin_busy_count": sum(
                                    e["stage"] == "begin-failed"
                                    for e in adapter.journal_trace
                                ),
                                "native_VM_calls": 0,
                            }
                        ),
                    )
                else:
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
                if mode == "qualification-loss":
                    samples = []
                    for _ in range(2):
                        frame["observed_mono_ns"] = time.monotonic_ns()
                        adapter.observe(frame)
                        samples.append(
                            {
                                "observed_mono_ns": frame["observed_mono_ns"],
                                "session": frame["session"],
                                "members": adapter.family.members(),
                            }
                        )
                    qualification._controller_loss_exit(
                        root, digest(canonical(grant)), adapter, samples
                    )
                if mode in {"graceful", "recovery-graceful", "graceful-contention"}:
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
