"""Original authority, durable start, runtime join and retirement failure paths."""

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from research.validation import frontend_start as start
from research.validation.owner_launch import SuspendedChild
from research.validation.store import Hold, Store
from research.validation.transfer_commands import canonical, digest
from tests import test_boot_preconditions as preconditions
from tests import test_owner_launch as owner_tests
from tests import test_stopped_backup as backup_tests
from tests.fixtures.frontend_start_support import NoInputLocks, bind


class FakeFamily:
    def __init__(self, _exe, _args):
        self.identity = {
            "pid": 123456,
            "created_filetime": 1,
            "image": str(start.frontend.HEADLESS),
        }
        self.fault = threading.Event()
        self.resumed = False
        self.terminal = None
        self.exit = None
        self.extra = []
        self.stdout, self.stderr = bytearray(), bytearray()
        self.lose_ack = False
        self.job = SimpleNamespace(active=lambda: 0 if self.exit == 0 else 1)

    def resume(self, gate):
        gate(self.identity)
        self.resumed = True
        if self.lose_ack:
            raise Hold("injected lost resume acknowledgement")

    def members(self, *, allow_retired=False):
        return [self.identity, *self.extra]

    def poll(self):
        return self.exit

    def retire(self):
        self.terminal = {
            "status": "fake-family-reaped",
            "job_active_processes": 0,
            "root_exit": self.exit,
            **{
                name + "_bytes": len(getattr(self, name))
                for name in ("stdout", "stderr")
            },
            **{
                name + "_sha256": digest(getattr(self, name))
                for name in ("stdout", "stderr")
            },
        }
        return self.terminal


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        preconditions.PreparedTests.setUp(self)
        self.packet["controller"]["pid"], self.packet["bootstrap"]["pid"] = (
            os.getpid(),
            9999992,
        )
        self.identities = {
            self.packet[k]["pid"]: self.packet[k]
            for k in ("owner", "controller", "bootstrap")
        }
        raw = canonical(self.packet)
        (self.root / "owner.sealed.json").write_bytes(raw)
        ready = json.loads((self.root / "owner.ready.json").read_bytes())
        ready["launch_sha256"] = digest(raw)
        (self.root / "owner.ready.json").write_bytes(canonical(ready))
        b, _ = preconditions.grant_for(self.root, self.packet)
        b["caller"] = {"role": "controller", "process": self.packet["controller"]}
        self.grant, self.receipts = bind(b, preconditions.snapshot(b))
        real = start.boot.watch_owner
        self.addCleanup(patch.stopall)
        patch.object(
            start.boot,
            "watch_owner",
            lambda store, b, *_args: real(
                store,
                b,
                identity=lambda pid: self.identities.get(pid),
                jobs=lambda _: None,
            ),
        ).start()
        patch.object(start, "controller_limits", lambda _: None).start()
        patch.object(start, "image_environment", lambda _: None).start()
        patch.object(start, "_InputLocks", NoInputLocks).start()
        patch.object(start.frontend, "_FrontendProcess", FakeFamily).start()
        self.adapter = start._PreparedStart(
            self.store, lambda: preconditions.snapshot(self.grant["boot"])
        )
        self.addCleanup(self.adapter.close)

    def launch(self):
        raw = canonical(self.grant)
        return self.adapter.start(raw, digest(raw), *map(canonical, self.receipts))

    def frame(self, pid=None, state="running"):
        frame = preconditions.snapshot(self.grant["boot"])
        frame["machine"] = frame["machine"].replace(
            b'"poweroff"', json.dumps(state).encode()
        )
        frame["session"] = {
            "vm_uuid": self.grant["boot"]["target"]["vm_uuid"],
            "state_before": "Locked",
            "state_after": "Locked",
            "pid": pid or self.adapter.family.identity["pid"],
        }
        return frame

    def wait_retired(self):
        end = time.monotonic() + 2
        while self.adapter.terminal is None and time.monotonic() < end:
            time.sleep(0.01)
        self.assertIsNotNone(self.adapter.terminal)
        self.assertFalse(self.adapter.terminal["original_stop_accepted"])
        self.assertFalse(self.adapter.terminal["VM_poweroff_proven"])

    def waiting_frame(self, states=None, before="Spawning", after="Locked", pid=0):
        frame = self.frame(state="running")
        frame["session"].update(state_before=before, state_after=after, pid=pid)
        frame["startup_transition"] = {
            "format": "mcli1-startup-wait-v1",
            "machine_states": states or ["poweroff", "starting", "running", "running"],
        }
        return frame

    def session_probe(self, *, state="starting", session="Locked", pid=None):
        native = start.session_observer
        stamp = time.monotonic_ns()
        return {
            "format": "mcli1-startup-session-probe-v1",
            "observed_mono_ns": stamp,
            "finished_mono_ns": stamp,
            "session_raw": canonical(
                {
                    "format": "mcli1-native-session-read-v1",
                    "version": native.VERSION,
                    "revision": native.REVISION,
                    "vm_uuid": self.grant["boot"]["target"]["vm_uuid"],
                    "state_before": {"Unlocked": 1, "Locked": 2, "Spawning": 3}[
                        session
                    ],
                    "state_after": {"Unlocked": 1, "Locked": 2, "Spawning": 3}[session],
                    "machine_before": native.MACHINE_STATES[state],
                    "machine_after": native.MACHINE_STATES[state],
                    "pid": (self.adapter.family.identity["pid"] if pid is None else pid)
                    if session == "Locked"
                    else 0,
                }
            ),
        }

    def test_session_probe_waits_without_join_or_lease_renewal(self):
        self.launch()
        lease = dict(self.store.db.execute("SELECT * FROM lease").fetchone())
        started = self.adapter.started_mono
        wait = self.adapter.observe_startup_session(
            self.session_probe(state="poweroff", session="Unlocked")
        )
        self.assertFalse(wait["profile_observation_allowed"])
        ready = self.adapter.observe_startup_session(self.session_probe())
        self.assertTrue(ready["profile_observation_allowed"])
        self.assertFalse(ready["guest_ready"])
        self.assertIsNone(self.adapter.joined)
        self.assertFalse((self.root / "frontend.session.receipt.json").exists())
        self.assertEqual(self.adapter.started_mono, started)
        self.assertEqual(
            dict(self.store.db.execute("SELECT * FROM lease").fetchone()), lease
        )
        frame = self.frame()
        frame["machine"] = frame["machine"].replace(
            b'"memory"="1024"', b'"memory"="2048"'
        )
        with self.assertRaises(Hold):
            self.adapter.observe(frame)
        self.assertIsNone(self.adapter.joined)

    def test_session_probe_rejects_foreign_pid_and_retains_containment(self):
        self.launch()
        with self.assertRaisesRegex(Hold, "outside frontend family"):
            self.adapter.observe_startup_session(self.session_probe(pid=777))
        self.assertIsNotNone(self.adapter.terminal)

    def test_session_probe_rejects_replayed_observation(self):
        self.launch()
        probe = self.session_probe(state="running")
        self.adapter.observe_startup_session(probe)
        with self.assertRaisesRegex(Hold, "stale/reordered"):
            self.adapter.observe_startup_session(probe)

    def test_session_probe_backward_progress_is_held(self):
        self.launch()
        self.adapter.observe_startup_session(self.session_probe(state="running"))
        with self.assertRaisesRegex(Hold, "regressed"):
            self.adapter.observe_startup_session(self.session_probe())

    def test_session_probe_after_full_join_is_held(self):
        self.launch()
        self.adapter.observe(self.frame())
        with self.assertRaisesRegex(Hold, "after join"):
            self.adapter.observe_startup_session(self.session_probe(state="running"))

    def test_session_probe_cannot_extend_original_startup_deadline(self):
        self.launch()
        self.adapter.started_mono -= start.STARTUP_NS
        with self.assertRaisesRegex(Hold, "startup timed out"):
            self.adapter.observe_startup_session(self.session_probe())
        self.assertIsNotNone(self.adapter.terminal)

    def test_unproven_probe_machine_state_is_held(self):
        self.launch()
        probe = self.session_probe()
        record = json.loads(probe["session_raw"])
        record["machine_after"] = 999
        probe["session_raw"] = canonical(record)
        with self.assertRaisesRegex(Hold, "unknown startup state"):
            self.adapter.observe_startup_session(probe)
        self.assertIsNone(self.adapter.joined)

    def test_forward_wait_does_not_join_publish_or_renew_authority(self):
        self.launch()
        lease = dict(self.store.db.execute("SELECT * FROM lease").fetchone())
        started = self.adapter.started_mono
        result = self.adapter.observe(self.waiting_frame())
        self.assertEqual(result["status"], "awaiting-session-identity")
        self.assertFalse(result["guest_ready"])
        self.assertIsNone(self.adapter.joined)
        self.assertFalse((self.root / "frontend.session.receipt.json").exists())
        self.assertEqual(self.adapter.started_mono, started)
        self.assertEqual(
            dict(self.store.db.execute("SELECT * FROM lease").fetchone()), lease
        )
        self.assertEqual(
            self.adapter.observe(self.frame())["status"],
            "runtime-session-bound-not-guest-ready",
        )

    def test_wait_cannot_hide_cross_observation_regression(self):
        self.launch()
        self.adapter.observe(self.waiting_frame())
        with self.assertRaisesRegex(Hold, "regressed"):
            self.adapter.observe(self.waiting_frame())
        self.assertIsNotNone(self.adapter.terminal)

    def test_wait_checks_exact_profile_before_accepting_progress(self):
        self.launch()
        frame = self.waiting_frame()
        frame["machine"] = frame["machine"].replace(
            b'"memory"="1024"', b'"memory"="2048"'
        )
        with self.assertRaises(Hold):
            self.adapter.observe(frame)
        self.assertIsNone(self.adapter.joined)

    def test_wait_is_rejected_after_join(self):
        self.launch()
        self.adapter.observe(self.frame())
        with self.assertRaises(Hold):
            self.adapter.observe(self.waiting_frame())

    def test_retirement_retains_console_bytes_without_accepting_a_stop(self):
        self.launch()
        self.adapter.family.stdout.extend(b"bounded frontend output\n")
        self.adapter.family.stderr.extend(b"bounded frontend warning\n")
        result = self.adapter.close()
        self.assertFalse(result["original_stop_accepted"])
        self.assertFalse(result["VM_poweroff_proven"])
        self.assertEqual(result["errors"], [])
        for stream in ("stdout", "stderr"):
            raw = (self.root / ("frontend." + stream + ".bin")).read_bytes()
            self.assertEqual(raw, getattr(self.adapter.family, stream))
            self.assertEqual(digest(raw), result["cleanup"][stream + "_sha256"])

    def test_output_publication_failure_holds_after_containment_and_fencing(self):
        self.launch()
        (self.root / "frontend.stderr.bin").write_bytes(b"existing evidence")
        result = self.adapter.close()
        self.assertEqual(result["status"], "frontend-retirement-held")
        self.assertIn("output:FileExistsError", result["errors"])
        self.assertIsNotNone(self.adapter.family.terminal)
        self.assertEqual(
            self.store.db.execute("SELECT active FROM authority").fetchone()[0], 0
        )
        self.assertFalse(result["original_stop_accepted"])
        self.assertEqual(
            (self.root / "frontend.stderr.bin").read_bytes(), b"existing evidence"
        )
        self.assertIs(self.adapter.close(), result)

    def test_unarmed_grant_and_missing_owner_ready_never_create_process(self):
        self.grant["approval"]["native_run"] = None
        with self.assertRaises(Hold):
            self.launch()
        self.assertIsNone(self.adapter.family)
        self.adapter.grant = None
        self.grant["approval"]["native_run"] = "test:Python-only"
        (self.root / "owner.ready.json").unlink()
        with self.assertRaises(FileNotFoundError):
            self.launch()
        self.assertIsNone(self.adapter.family)
        self.assertFalse((self.root / "frontend.start.intent.json").exists())

    def test_exact_owner_gate_and_durable_possible_resume_precede_execution(self):
        seen = []
        real = FakeFamily.resume

        def resume(family, gate):
            def wrapped(identity):
                gate(identity)
                row = self.store.db.execute("SELECT * FROM frontend_start").fetchone()
                seen.append((row["state"], row["process"], family.resumed))

            real(family, wrapped)

        with patch.object(FakeFamily, "resume", resume):
            result = self.launch()
        self.assertEqual(
            seen, [("possible-resume", canonical(self.adapter.family.identity), False)]
        )
        self.assertFalse(result["guest_ready"])
        lease = dict(self.store.db.execute("SELECT * FROM lease").fetchone())
        self.assertEqual(lease["expires_ns"], self.packet["lease"]["expires_ns"])

    def test_controller_identity_and_expired_admission_are_denied(self):
        self.identities[os.getpid()] = {
            **self.packet["controller"],
            "created_filetime": 999,
        }
        with self.assertRaises(Hold):
            self.launch()
        self.assertIsNone(self.adapter.family)
        self.adapter.grant = None
        self.identities[os.getpid()] = self.packet["controller"]
        self.grant["boot"]["window"]["expires_mono_ns"] = time.monotonic_ns() - 1
        with self.assertRaises(Hold):
            self.launch()
        self.assertIsNone(self.adapter.family)

    def test_fence_in_final_probe_prevents_resume_and_retains_intent(self):
        calls = []

        def probe():
            calls.append(1)
            if len(calls) == 2:
                self.store.fence("injected final-gate revocation")
            return preconditions.snapshot(self.grant["boot"])

        self.adapter.probe = probe
        with self.assertRaises(Hold):
            self.launch()
        self.assertFalse(self.adapter.family.resumed)
        self.assertIsNotNone(self.adapter.family.terminal)
        self.assertTrue((self.root / "frontend.start.intent.json").exists())
        self.assertFalse((self.root / "frontend.resume.intent.json").exists())

    def test_profile_drift_and_changed_backup_receipt_refuse(self):
        self.receipts[0]["independent"] = False
        with self.assertRaises(Hold):
            self.launch()
        self.assertIsNone(self.adapter.family)

    def test_lost_resume_acknowledgement_retires_and_cannot_replay(self):
        real = FakeFamily.resume

        def resume(family, gate):
            family.lose_ack = True
            real(family, gate)

        with patch.object(FakeFamily, "resume", resume), self.assertRaises(Hold):
            self.launch()
        self.assertTrue(self.adapter.family.resumed)
        self.assertEqual(
            self.store.db.execute("SELECT state FROM frontend_start").fetchone()[0],
            "possible-resume",
        )
        self.assertIsNotNone(self.adapter.family.terminal)
        with self.assertRaises(Hold):
            self.launch()

    def test_filesystem_intent_survives_deleted_journal_and_blocks_new_adapter(self):
        self.launch()
        self.adapter.close()
        self.store.db.execute("DELETE FROM frontend_start")
        # Even an injected re-armed fixture cannot erase a consumed FS intent.
        self.store.db.execute("UPDATE authority SET active=1,generation=1")
        another = start._PreparedStart(self.store, self.adapter.probe)
        self.addCleanup(another.close)
        raw = canonical(self.grant)
        with self.assertRaises(FileExistsError):
            another.start(raw, digest(raw), *map(canonical, self.receipts))
        self.assertIsNone(another.family)

    def test_runtime_join_is_not_guest_readiness_and_window_is_not_renewed(self):
        self.launch()
        result = self.adapter.observe(self.frame())
        self.assertEqual(result["status"], "runtime-session-bound-not-guest-ready")
        self.assertFalse(result["guest_ready"])
        window = self.grant["boot"]["window"]
        with patch.object(
            start.boot, "live_window", side_effect=Hold("admission window expired")
        ):
            self.assertEqual(self.adapter.observe(self.frame()), result)
        self.assertEqual(self.grant["boot"]["window"], window)
        with self.assertRaises(Hold):
            start.boot.owner_live(
                self.store,
                {
                    **self.grant["boot"],
                    "window": {**window, "expires_mono_ns": time.monotonic_ns() - 1},
                },
            )

    def test_foreign_session_pid_and_reordered_observation_retire(self):
        self.launch()
        with self.assertRaises(Hold):
            self.adapter.observe(self.frame(pid=999999))
        self.assertIsNotNone(self.adapter.family.terminal)

    def test_session_unlock_or_stale_frame_never_publishes_ready(self):
        self.launch()
        frame = self.frame()
        frame["session"]["state_after"] = "Unlocking"
        with self.assertRaises(Hold):
            self.adapter.observe(frame)
        self.assertFalse((self.root / "frontend.session.receipt.json").exists())

    def test_repeated_runtime_frame_and_profile_drift_retire(self):
        self.launch()
        frame = self.frame()
        self.adapter.observe(frame)
        with self.assertRaises(Hold):
            self.adapter.observe(frame)
        self.assertIsNotNone(self.adapter.family.terminal)

    def test_delayed_startup_and_missing_runtime_heartbeat_retire(self):
        self.launch()
        self.adapter.started_mono -= start.STARTUP_NS
        self.adapter.started_utc -= start.STARTUP_NS
        self.wait_retired()
        self.assertIn("startup timed out", self.adapter.terminal["reason"])

    def test_runtime_heartbeat_and_session_membership_are_required(self):
        self.launch()
        self.adapter.observe(self.frame())
        self.adapter.last_observation -= 6 * 10**9
        self.wait_retired()
        self.assertIn("heartbeat is stale", self.adapter.terminal["reason"])

    def test_watchdog_retires_on_fence_without_runtime_observer(self):
        self.launch()
        self.store.fence("injected caller revocation")
        self.wait_retired()

    def test_watchdog_retires_on_output_fault_and_preserves_nonzero_exit(self):
        self.launch()
        self.adapter.family.exit = 7
        self.adapter.family.fault.set()
        self.wait_retired()
        self.assertEqual(self.adapter.terminal["cleanup"]["root_exit"], 7)

    def test_watchdog_holds_on_lost_running_journal(self):
        self.launch()
        self.store.db.execute("DELETE FROM frontend_start")
        self.wait_retired()

    def test_cleanup_precedes_failed_fence_and_does_not_accept_stop(self):
        self.launch()
        with patch.object(
            self.store, "fence", side_effect=Hold("injected journal failure")
        ):
            result = self.adapter.retire("test containment")
        self.assertIsNotNone(self.adapter.family.terminal)
        self.assertEqual(result["status"], "frontend-retirement-held")
        self.assertFalse(result["original_stop_accepted"])

    def test_normal_finish_requires_join_and_never_uses_a_stop_command(self):
        self.launch()
        with self.assertRaises(Hold):
            self.adapter.request_owner_stop()
        self.assertIsNotNone(self.adapter.family.terminal)
        self.assertFalse((self.root / "frontend.owner-stop.intent.json").exists())

    def test_normal_finish_waits_for_original_ledger_and_natural_exit(self):
        self.launch()
        self.adapter.observe(self.frame())
        request = self.adapter.request_owner_stop()
        self.assertEqual(self.adapter.family.exit, None)
        self.assertIsNone(self.adapter.family.terminal)
        self.assertTrue((self.root / "frontend.owner-stop.intent.json").exists())
        self.store.db.execute("UPDATE lease SET state='stop-command-returned'")
        self.store.db.execute("UPDATE maintenance_owner SET state='stop-returned'")
        self.adapter.family.exit = 0
        self.wait_retired()
        self.assertIn("original stop returned", self.adapter.terminal["reason"])
        self.assertEqual(request["grant_sha256"], self.adapter.sha)
        self.assertFalse(self.adapter.terminal["original_stop_accepted"])

    def test_normal_finish_acknowledgement_timeout_does_not_extend_lease(self):
        self.launch()
        self.adapter.observe(self.frame())
        before = dict(self.store.db.execute("SELECT * FROM lease").fetchone())
        self.adapter.request_owner_stop()
        self.adapter.owner_stop["issued_utc_ns"] -= 4 * 10**9
        self.adapter.owner_stop["issued_mono_ns"] -= 4 * 10**9
        self.wait_retired()
        self.assertIn("finish window expired", self.adapter.terminal["reason"])
        self.assertEqual(
            dict(self.store.db.execute("SELECT * FROM lease").fetchone()), before
        )

    def test_normal_finish_original_binding_drift_retires_without_acceptance(self):
        self.launch()
        self.adapter.observe(self.frame())
        self.adapter.request_owner_stop()
        self.store.db.execute("UPDATE lease SET expires_mono_ns=expires_mono_ns+1")
        self.wait_retired()
        self.assertIn("lease binding changed", self.adapter.terminal["reason"])

    def test_normal_finish_duplicate_request_cannot_issue_another_command(self):
        self.launch()
        self.adapter.observe(self.frame())
        self.adapter.request_owner_stop()
        with self.assertRaises(Hold):
            self.adapter.request_owner_stop()
        self.assertIsNotNone(self.adapter.family.terminal)


@unittest.skipUnless(
    sys.platform == "win32", "Windows actual original-file share locks"
)
class InputLockTests(unittest.TestCase):
    artifact_root = None
    new_root = backup_tests.BackupTests.new_root
    probe = backup_tests.BackupTests.probe
    capture = backup_tests.BackupTests.capture

    def setUp(self):
        backup_tests.BackupTests.setUp(self)
        if self.artifact_root is not None:
            self.addCleanup(self.preserve)
        result = self.capture()
        self.backup_raw = (self.output / "receipt.json").read_bytes()
        self.inputs = {"boot": {"role": "guard", "backup": result["binding"]}}
        self.paths["configuration"].write_bytes(
            b"synthetic reviewed profile configuration"
        )
        self.profile = {
            "disk_sha256": result["binding"]["disk_sha256"],
            "configuration": start.backup.file_state(self.paths["configuration"]),
            "nvram": {"state": "absent"},
        }
        self.source = start.backup.source_paths("executor")["disk"]
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(self.paths["disk"].read_bytes())
        patch.object(
            start.host, "SOURCE_DISK_SHA", digest(self.source.read_bytes())
        ).start()

    def preserve(self):
        import shutil

        shutil.copytree(self.root, Path(self.artifact_root) / self._testMethodName)

    def locks(self):
        value = start._InputLocks(self.inputs, self.backup_raw, self.profile)
        self.addCleanup(value.close)
        return value

    def test_actual_current_configuration_and_source_disk_are_locked_until_release(
        self,
    ):
        locks = self.locks()
        for path in (self.paths["disk"], self.paths["configuration"], self.source):
            with self.assertRaises(PermissionError):
                path.write_bytes(b"injected writer")
        locks.check()
        locks.close()
        self.paths["configuration"].write_bytes(b"released")

    def test_changed_backup_copy_refuses_before_holding_originals(self):
        (self.output / "disk.vdi").write_bytes(b"changed backup")
        with self.assertRaises(Hold):
            self.locks()
        self.paths["disk"].write_bytes(b"constructor released its handles")

    def test_source_preservation_drift_refuses_and_releases_every_handle(self):
        self.source.write_bytes(b"changed preserved source")
        with self.assertRaises(Hold):
            self.locks()
        self.paths["configuration"].write_bytes(b"released")

    def test_late_firmware_creation_is_seen_before_resume(self):
        locks = self.locks()
        self.paths["nvram"].write_bytes(b"appeared after initial measurement")
        with self.assertRaises(Hold):
            locks.check()


@unittest.skipUnless(
    sys.platform == "win32", "Windows original owner and nested frontend jobs"
)
class NativeStartTests(owner_tests.NativeOwnerFixture, unittest.TestCase):
    artifact_root = None

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.nonce = uuid4().hex
        self.mode = "normal"
        self.controller_job = start.frontend.ControllerJob(
            "Local\\MCLI1Controller-" + self.nonce
        )
        self.controller = SuspendedChild(
            [
                "-I",
                "-B",
                str(Path(__file__).parent / "fixtures/frontend_start_controller.py"),
                str(self.base / "owner"),
            ],
            self.controller_job,
        )
        self.owner = self.owner_identity = None
        self.addCleanup(self.cleanup_processes)

    def prepared(self, mode="normal", owner_mode="success", seconds=40):
        pending = self.pending(mode=owner_mode, seconds=seconds)
        self.seal()
        packet = json.loads((pending.root / "owner.sealed.json").read_bytes())
        b, _ = preconditions.grant_for(pending.root, packet)
        b["caller"] = {"role": "controller", "process": packet["controller"]}
        grant, receipts = bind(b, preconditions.snapshot(b))
        if mode == "recovery-graceful":
            from tests import test_recovery_records as recovery_tests

            context = recovery_tests.context()
            context["sources"] = dict(start.recovery_host.SOURCE_EPOCH)
            b["target"]["disk_uuid"] = start.recovery_host.model.GUARD_DISK
            b["disk_evidence"]["pre_boot_disk_sha256"] = context["files"]["disk"][
                "sha256"
            ]
            frame = preconditions.snapshot(b)
            frame["machine"] = frame["machine"].replace(b'"poweroff"', b'"aborted"')
            frame["medium"] = frame["medium"].replace(b"locked write", b"created")
            for label in ("first_observation", "last_observation"):
                context[label].update(
                    machine_sha256=digest(frame["machine"]),
                    medium_sha256=digest(frame["medium"]),
                )
            backup = recovery_tests.receipt(context)
            backup_sha = digest(canonical(backup))
            b["backup"] = start.backup.records.binding(
                backup, backup_sha, recovery=context
            )
            preboot = {
                **receipts[1],
                "format": "mcli1-recovery-preboot-disk-v1",
                "disk_uuid": b["target"]["disk_uuid"],
                "disk_sha256": b["disk_evidence"]["pre_boot_disk_sha256"],
                "state": "aborted",
                "backup_receipt_sha256": backup_sha,
                "recovery_context_sha256": start.recovery_host.model.context_sha256(
                    context
                ),
            }
            b["disk_evidence"]["pre_boot_receipt_sha256"] = digest(canonical(preboot))
            profile = start.recovery_host.profile(context, backup_sha)
            grant.update(
                format=start.RECOVERY_FORMAT,
                recovery=context,
                profile_receipt_sha256=digest(canonical(profile)),
            )
            receipts = [backup, preboot, receipts[2], profile]
        grant["executable"] = {
            "path": str(Path(sys.executable).resolve()),
            "sha256": digest(Path(sys.executable).read_bytes()),
        }
        (pending.root / "controller.request.json").write_bytes(
            canonical({"mode": mode, "grant": grant, "receipts": receipts})
        )
        self.controller.resume()
        return pending.root

    def wait_file(self, name, timeout=10):
        end = time.monotonic() + timeout
        path, error = self.owner.root / name, self.owner.root / "controller.error.txt"
        while not path.exists() and not error.exists() and time.monotonic() < end:
            time.sleep(0.01)
        self.assertTrue(
            path.exists(),
            error.read_text()
            if error.exists()
            else "controller did not report: " + name,
        )
        return json.loads(path.read_bytes())

    def verify_stop(self):
        terminal = self.terminal()
        calls = (self.owner.root / "surrogate.calls.jsonl").read_text().splitlines()
        self.assertEqual(len(calls), 1)
        self.assertFalse(json.loads(calls[0])["actual_VM_command"])
        return terminal

    def test_actual_controller_owner_and_runtime_family_are_joined_then_fenced(self):
        root = self.prepared()
        ready = self.wait_file("controller.ready.json")
        self.assertFalse(ready["guest_ready"])
        self.assertTrue(ready["query_reaped"])
        self.assertEqual(
            len(
                [
                    p
                    for p in ready["members"]
                    if Path(p["image"]).resolve() == Path(sys.executable).resolve()
                ]
            ),
            3,
        )
        with closing(Store(root / "owner.sqlite")) as store:
            store.fence("test-only native caller revocation")
        result = self.wait_file("controller.terminal.json")
        self.assertFalse(result["original_stop_accepted"])
        self.assertEqual(result["cleanup"]["job_active_processes"], 0)
        self.verify_stop()
        for row in ready["members"]:
            self.assertFalse(self.alive(row))

    def test_original_stop_lost_ack_stays_unknown_after_family_cleanup(self):
        root = self.prepared(owner_mode="lost-ack")
        self.wait_file("controller.ready.json")
        with closing(Store(root / "owner.sqlite")) as store:
            store.fence("test-only lost stop acknowledgement")
        result = self.wait_file("controller.terminal.json")
        self.assertFalse(result["original_stop_accepted"])
        terminal = self.verify_stop()
        self.assertNotEqual(terminal.get("status"), "owner-stop-command-returned")
        with closing(Store(root / "owner.sqlite")) as store:
            self.assertEqual(
                store.db.execute("SELECT state FROM lease").fetchone()[0], "stopping"
            )

    def test_abrupt_controller_loss_reaps_family_and_original_owner_stops_once(self):
        self.prepared(mode="abrupt")
        ready = self.wait_file("controller.ready.json")
        self.verify_stop()
        end = time.monotonic() + 2
        while any(self.alive(p) for p in ready["members"]) and time.monotonic() < end:
            time.sleep(0.01)
        self.assertTrue(all(not self.alive(p) for p in ready["members"]))

    def test_native_resume_ack_loss_has_one_intent_and_no_replay(self):
        root = self.prepared(mode="lost-resume-ack")
        result = self.wait_file("controller.terminal.json")
        self.assertEqual(result["cleanup"]["job_active_processes"], 0)
        self.assertFalse(result["original_stop_accepted"])
        with closing(Store(root / "owner.sqlite")) as store:
            self.assertEqual(
                store.db.execute("SELECT state FROM frontend_start").fetchone()[0],
                "possible-resume",
            )
        self.assertTrue((root / "frontend.resume.intent.json").exists())
        self.verify_stop()

    def test_output_overflow_retires_without_runtime_observer(self):
        root = self.prepared(mode="flood")
        result = self.wait_file("controller.terminal.json")
        self.assertTrue(result["cleanup"]["output_fault"])
        self.assertLessEqual(result["cleanup"]["stdout_bytes"], 65536)
        raw = (root / "frontend.stdout.bin").read_bytes()
        self.assertEqual(len(raw), result["cleanup"]["stdout_bytes"])
        self.assertEqual(digest(raw), result["cleanup"]["stdout_sha256"])
        self.verify_stop()

    def test_unanswered_runtime_join_retires_at_original_stop_reserve(self):
        root = self.prepared(mode="unsettled", seconds=16)
        result = self.wait_file("controller.terminal.json", timeout=12)
        self.assertIn("original stop reserve reached", result["reason"])
        self.assertFalse((root / "frontend.session.receipt.json").exists())
        self.assertEqual(result["cleanup"]["job_active_processes"], 0)
        self.verify_stop()
        packet = json.loads((root / "owner.sealed.json").read_bytes())
        with closing(Store(root / "owner.sqlite")) as store:
            self.assertEqual(
                store.db.execute("SELECT expires_mono_ns FROM lease").fetchone()[0],
                packet["lease"]["expires_mono_ns"],
            )

    def test_original_revocation_inside_final_gate_prevents_python_execution(self):
        root = self.prepared(mode="deny-gate")
        result = self.wait_file("controller.terminal.json")
        self.assertFalse((root / "family-0.json").exists())
        self.assertFalse((root / "frontend.resume.intent.json").exists())
        self.assertEqual(result["cleanup"]["job_active_processes"], 0)
        self.verify_stop()

    def test_normal_finish_allows_original_stop_then_natural_family_exit(self):
        root = self.prepared(mode="graceful")
        ready = self.wait_file("controller.ready.json")
        result = self.wait_file("controller.terminal.json")
        self.assertIn("original stop returned", result["reason"])
        self.assertFalse(result["cleanup"]["terminated"])
        self.assertEqual(result["cleanup"]["root_exit"], 0)
        self.assertFalse(result["original_stop_accepted"])
        self.assertTrue((root / "frontend.owner-stop.intent.json").exists())
        self.verify_stop()
        for row in ready["members"]:
            self.assertFalse(self.alive(row))

    def test_recovery_uses_real_original_owner_and_jobs_with_python_only_frontends(
        self,
    ):
        root = self.prepared(mode="recovery-graceful")
        ready = self.wait_file("controller.ready.json")
        waiting = self.wait_file("recovery.wait.json")
        progress = self.wait_file("controller.probe.json")
        result = self.wait_file("controller.terminal.json")
        self.assertEqual(waiting["status"], "awaiting-session-identity")
        self.assertFalse(waiting["guest_ready"])
        self.assertIn("original stop returned", result["reason"])
        self.assertEqual(result["cleanup"]["root_exit"], 0)
        self.assertFalse(result["cleanup"]["terminated"])
        packet = json.loads((root / "owner.sealed.json").read_bytes())
        self.assertEqual(waiting["original_lease"], packet["lease"])
        self.assertEqual(progress["original_lease"], packet["lease"])
        self.assertTrue(progress["profile_observation_allowed"])
        self.assertFalse(progress["joined"])
        self.assertFalse(result["original_stop_accepted"])
        self.verify_stop()
        for process in ready["members"]:
            self.assertFalse(self.alive(process))

    def test_separate_writer_process_allows_one_join_and_original_stop(self):
        root = self.prepared(mode="graceful-contention")
        self.wait_file("controller.ready.json")
        writer = self.wait_file("controller.journal.writer.json")
        result = self.wait_file("controller.terminal.json")
        self.assertGreater(writer["begin_busy_count"], 0)
        self.assertFalse(self.alive(writer["process"]))
        self.assertEqual(result["cleanup"]["root_exit"], 0)
        self.assertFalse(result["cleanup"]["terminated"])
        self.assertEqual(result["errors"], [])
        trace = json.loads((root / "frontend.journal.trace.json").read_bytes())
        self.assertEqual(
            sum(
                e["phase"] == "session-bind" and e["stage"] == "committed"
                for e in trace["events"]
            ),
            1,
        )
        self.verify_stop()

    def test_normal_finish_lost_original_ack_is_held_after_natural_exit(self):
        root = self.prepared(mode="graceful", owner_mode="lost-ack")
        self.wait_file("controller.ready.json")
        result = self.wait_file("controller.terminal.json")
        self.assertFalse(result["original_stop_accepted"])
        self.assertNotIn("original stop returned", result["reason"])
        self.verify_stop()
        with closing(Store(root / "owner.sqlite")) as store:
            self.assertEqual(
                store.db.execute("SELECT state FROM lease").fetchone()[0], "stopping"
            )


if __name__ == "__main__":
    unittest.main()
