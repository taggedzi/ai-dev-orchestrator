"""Same-boot session integration with synthetic guest/owner facts and no VM calls."""

import copy
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import test_maintenance_host as host_fixture
import test_maintenance_transfer as fixture
import test_owner_launch as native_fixture

from research.validation import maintenance_host as host
from research.validation import maintenance_session as session
from research.validation import owner_process as owner
from research.validation.store import Hold, Store
from research.validation.supervisor import LeaseSupervisor
from research.validation.transfer_commands import canonical, digest


class SessionTests(unittest.TestCase):
    snapshot = fixture.ControllerTests.snapshot

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = Store(Path(self.folder.name) / "owner.sqlite")
        self.addCleanup(self.store.close)
        self.grant, self.files, self.observed, self.identity, self.plan = (
            fixture.bound_fixture()
        )
        lease = self.grant["lease"]
        self.supervisor = LeaseSupervisor(
            self.store,
            {
                "target_vm_uuid": self.grant["target"]["vm_uuid"],
                "lease_expires_utc_ns": lease["expires_utc_ns"],
            },
            now_ns=lease["expires_utc_ns"] - 600 * 10**9,
            monotonic_ns=lease["expires_mono_ns"] - 600 * 10**9,
        )
        self.sent, self.stops, self.fail_at = [], [], None
        self.native_stop_requests, self.bad_host = [], False
        self.identities = {
            os.getpid(): {
                "pid": os.getpid(),
                "created_filetime": 1,
                "image": r"C:\synthetic\controller.exe",
            },
            9999991: {
                "pid": 9999991,
                "created_filetime": 2,
                "image": r"C:\synthetic\owner.exe",
            },
        }
        with patch.object(host.os, "getpid", return_value=9999991):
            self.original = host.RegisteredOwner(
                self.supervisor,
                self.grant["lease"]["owner_nonce"],
                identity=self.identities.__getitem__,
            )
        self.root = self.store.db.execute("PRAGMA database_list").fetchone()["file"]
        self.root = Path(self.root).parent
        lease = json.loads(self.original.binding)["lease"]
        launch = {
            "format": "mcli1-independent-owner-v1",
            "owner": self.identities[9999991],
            "controller": self.identities[os.getpid()],
            "lease": lease,
            "sources": dict(owner.SOURCE_EPOCH),
            "root": owner.root_identity(self.root),
            "profile": self.supervisor.profile,
        }
        self.launch_raw = canonical(launch)
        (self.root / "owner.sealed.json").write_bytes(self.launch_raw)
        self.all_sent = []
        self.phase_sent = []

    def sender(self, *args):
        # Reuse the existing wire/capsule simulator independently for each phase.
        self.sent = self.phase_sent
        value = fixture.ControllerTests.sender(self, *args)
        self.all_sent.append(self.sent[-1]["request_id"])
        return value

    def stop(self, grant):
        self.stops.append(grant["run_nonce"])
        self.original.poll(
            stopper=lambda *_: self.native_stop_requests.append(
                grant["target"]["vm_uuid"]
            )
        )
        return {
            "vm_uuid": grant["target"]["vm_uuid"],
            "run_nonce": grant["run_nonce"],
            "state": "poweroff",
            "disks": [grant["target"]["disk_uuid"]],
            "nics": ["none"] * 8,
            "shares": [],
            "receipt_sha256": "a" * 64,
            "observed_mono_ns": time.monotonic_ns(),
            "elapsed_ns": 0,
        }

    def prepare(self, seconds=None):
        if seconds is not None:
            now, mono = time.time_ns(), time.monotonic_ns()
            self.grant["phase_window"].update(
                issued_utc_ns=now,
                issued_mono_ns=mono,
                expires_utc_ns=now + int(seconds * 10**9),
                expires_mono_ns=mono + int(seconds * 10**9),
            )
        raw = canonical(self.grant)
        review = session.draft()
        review.update(
            inspection_grant_sha256=digest(raw),
            owner_binding_sha256=digest(self.original.binding),
            owner_launch_sha256=digest(self.launch_raw),
            controller=self.identities[os.getpid()],
            approval="test:session-preparation-only",
            review_expires_utc_ns=(
                self.grant["phase_window"]["expires_utc_ns"]
                if seconds is not None
                else self.grant["lease"]["expires_utc_ns"] - 10 * 10**9
            ),
            review_expires_mono_ns=(
                self.grant["phase_window"]["expires_mono_ns"]
                if seconds is not None
                else self.grant["lease"]["expires_mono_ns"] - 10 * 10**9
            ),
        )
        controller = session.transfer.TransferController(
            self.store,
            getattr(self, "live_probe", self.snapshot),
            getattr(self, "stop_observer", self.stop),
            self.sender,
        )
        wire = canonical(review)
        self.subject = session.MaintenanceSession(
            controller,
            wire,
            digest(wire),
            raw,
            digest(raw),
            self.identities.__getitem__,
        )
        self.addCleanup(self.subject.close)
        self.review, self.review_raw, self.inspect_raw = review, wire, raw
        self.inspection_grant = copy.deepcopy(self.grant)
        self.inspection_files = dict(self.files)
        return self.subject

    def controls(self):
        lease = self.grant["lease"]
        target = self.grant["target"]
        original = self.grant
        grant, files, observed, identity, plan = fixture.bound_fixture("controls")
        grant.update(
            lease=lease,
            target=target,
            backup=original["backup"],
            disk_evidence=original["disk_evidence"],
        )
        # Retain the actual inspection observation, including its timestamp.
        files["observation.json"] = self.store.db.execute(
            "SELECT report FROM maintenance_session"
        ).fetchone()[0]
        request = json.loads(files["request.json"])
        request["observation_sha256"] = digest(files["observation.json"])
        files["request.json"] = canonical(request)
        grant["files"] = {
            name: {"bytes": len(raw), "sha256": digest(raw)}
            for name, raw in files.items()
        }
        self.grant, self.files, self.observed, self.identity, self.plan = (
            grant,
            files,
            observed,
            identity,
            plan,
        )
        self.phase_sent = []
        raw = canonical(grant)
        approval = self.subject.approval_template(digest(raw))
        approval["approval_reference"] = "test:exact-inspection-and-actions"
        return raw, files, approval

    def run_controls(self, raw, files, approval):
        approved = canonical(approval)
        return self.subject.controls(
            raw, digest(raw), files, approved, digest(approved)
        )

    def wait_fenced(self):
        end = time.monotonic() + 3
        while time.monotonic() < end:
            if not self.store.db.execute("SELECT active FROM authority").fetchone()[0]:
                return
            time.sleep(0.01)
        self.fail("session did not fence without another conversation turn")

    def test_full_same_boot_handoff_two_unique_phases_and_original_stop(self):
        subject = self.prepare()
        original_lease = dict(subject.lease)
        report = subject.inspect(self.files)
        self.assertEqual(report["status"], "awaiting-review")
        self.assertEqual(len(self.all_sent), 2)
        self.assertFalse(self.stops)
        self.assertFalse(self.native_stop_requests)
        self.assertEqual(
            self.store.db.execute("SELECT active FROM authority").fetchone()[0], 1
        )
        raw, files, approval = self.controls()
        result = self.run_controls(raw, files, approval)
        self.assertEqual(result["status"], "transfer-and-stop-reported-not-accepted")
        self.assertEqual(len(self.all_sent), 4)
        self.assertEqual(len(set(self.all_sent)), 4)
        self.assertEqual(len(self.native_stop_requests), 1)
        self.assertEqual(
            self.store.db.execute("SELECT state FROM maintenance_session").fetchone()[
                0
            ],
            "reported-and-stop-reported",
        )
        self.assertEqual(
            [r[0] for r in self.store.db.execute("SELECT state FROM operations")],
            ["received"] * 4,
        )
        lease = self.store.db.execute("SELECT * FROM lease").fetchone()
        self.assertEqual({k: lease[k] for k in original_lease}, original_lease)
        self.assertEqual(
            self.store.db.execute(
                "SELECT count(*) FROM maintenance_session_phase"
            ).fetchone()[0],
            2,
        )
        self.store.audit()

    def test_no_serial_intent_or_standalone_controller_during_review(self):
        subject = self.prepare()
        subject.inspect(self.files)
        with self.assertRaisesRegex(Hold, "no guest dispatch authority"):
            self.store.begin("serial:" + "a" * 32, "b" * 64)
        controller = session.transfer.TransferController(
            self.store, self.snapshot, self.stop, self.sender
        )
        with self.assertRaisesRegex(Hold, "original session controller"):
            controller.run(self.inspect_raw, digest(self.inspect_raw), self.files)
        self.assertEqual(len(self.all_sent), 2)

    def test_real_host_adapters_support_review_then_stop_with_the_control_grant(self):
        receipts = host_fixture.receipts(self.grant)
        state = ["running"]

        def query(kind, target, wall, mono):
            host.live(wall, mono)
            machine, medium = host_fixture.inventory(self.grant, state[0])
            raw = (
                host.VERSION.encode() + b"\n"
                if kind == "version"
                else machine
                if kind == "machine"
                else medium
            )
            return {
                "stdout": raw,
                "stderr": b"",
                "exit": 0,
                "pid": 11,
                "job_active_processes": 0,
                "started_mono_ns": time.monotonic_ns(),
                "finished_mono_ns": time.monotonic_ns(),
            }

        raw = canonical(self.grant)
        adapter = host.HostAdapters(
            self.root / "owner.sqlite",
            raw,
            digest(raw),
            self.original.binding,
            digest(self.original.binding),
            *receipts,
            query,
            self.root / "host-evidence",
            identity=self.identities.__getitem__,
        )

        def stopped(grant):
            self.original.poll(
                stopper=lambda *_: self.native_stop_requests.append("surrogate")
            )
            state[0] = "poweroff"
            return adapter.stop(grant)

        self.live_probe, self.stop_observer = adapter.live_probe, stopped
        subject = self.prepare()
        subject.inspect(self.files)
        # Inspection's dispatch window can expire while read-only review remains
        # bounded by its separately approved original session deadline.
        observed_grant = host.session_observation_grant(self.store.db, adapter.grant)
        self.assertEqual(
            observed_grant["phase_window"]["expires_mono_ns"],
            self.review["review_expires_mono_ns"],
        )
        raw, files, approval = self.controls()
        result = self.run_controls(raw, files, approval)
        self.assertEqual(result["stop"]["state"], "poweroff")
        self.assertEqual(len(self.native_stop_requests), 1)
        self.assertTrue((adapter.root / "stop-wait.intent.json").exists())

    def test_changed_lease_or_source_during_review_fences_without_controls(self):
        subject = self.prepare()
        subject.inspect(self.files)
        self.store.db.execute("UPDATE lease SET expires_ns=expires_ns+1")
        self.wait_fenced()
        self.assertEqual(len(self.all_sent), 2)

    def test_second_approval_and_control_attempt_cannot_replay(self):
        subject = self.prepare()
        subject.inspect(self.files)
        raw, files, approval = self.controls()
        self.run_controls(raw, files, approval)
        with self.assertRaisesRegex(Hold, "closed"):
            self.run_controls(raw, files, approval)
        self.assertEqual(len(self.all_sent), 4)
        self.assertEqual(len(self.native_stop_requests), 1)

    def test_no_answer_expires_and_original_owner_stops_without_renewal(self):
        subject = self.prepare(seconds=0.7)
        subject.inspect(self.files)
        self.wait_fenced()
        self.assertTrue(
            self.original.poll(
                stopper=lambda *_: self.native_stop_requests.append("surrogate")
            )
        )
        self.assertEqual(len(self.native_stop_requests), 1)
        self.assertEqual(
            self.store.db.execute("SELECT state FROM maintenance_session").fetchone()[
                0
            ],
            "stopping",
        )
        self.assertEqual(len(self.all_sent), 2)

    def test_rejected_or_changed_approval_fences_without_control_dispatch(self):
        subject = self.prepare()
        subject.inspect(self.files)
        raw, files, approval = self.controls()
        approval["observation_sha256"] = "0" * 64
        with self.assertRaisesRegex(Hold, "scope differs"):
            self.run_controls(raw, files, approval)
        self.assertTrue(subject.closed)
        self.assertEqual(len(self.all_sent), 2)
        self.assertEqual(
            self.store.db.execute("SELECT active FROM authority").fetchone()[0], 0
        )

    def test_delayed_approval_after_revocation_cannot_start_controls(self):
        subject = self.prepare()
        subject.inspect(self.files)
        raw, files, approval = self.controls()
        subject.revoke("test:operator rejected review")
        with self.assertRaisesRegex(Hold, "closed"):
            self.run_controls(raw, files, approval)
        self.assertEqual(len(self.all_sent), 2)

    def test_recreated_session_cannot_resume_or_create_another_lease(self):
        subject = self.prepare()
        subject.inspect(self.files)
        with self.assertRaisesRegex(Hold, "restart cannot resume"):
            session.MaintenanceSession(
                subject.controller,
                self.review_raw,
                digest(self.review_raw),
                self.inspect_raw,
                digest(self.inspect_raw),
                self.identities.__getitem__,
            )
        self.assertEqual(
            self.store.db.execute("SELECT count(*) FROM lease").fetchone()[0], 1
        )
        self.assertEqual(len(self.all_sent), 2)

    def test_reused_controller_pid_or_lost_owner_fences_review(self):
        subject = self.prepare()
        subject.inspect(self.files)
        self.identities[os.getpid()] = {
            **self.identities[os.getpid()],
            "created_filetime": 77,
        }
        self.wait_fenced()
        self.assertEqual(len(self.all_sent), 2)

    def test_old_boot_id_cannot_be_approved_for_controls(self):
        subject = self.prepare()
        subject.inspect(self.files)
        raw, files, approval = self.controls()
        grant = json.loads(raw)
        grant["target"]["boot_id"] = "66666666-6666-4666-8666-666666666666"
        raw = canonical(grant)
        approval["controls_grant_sha256"] = digest(raw)
        with self.assertRaises(Hold):
            self.run_controls(raw, files, approval)
        self.assertEqual(len(self.all_sent), 2)

    def test_lost_inspection_ack_stops_once_without_review_or_replay(self):
        subject = self.prepare()
        self.fail_at = 2
        with self.assertRaises(TimeoutError):
            subject.inspect(self.files)
        self.assertEqual(len(self.native_stop_requests), 1)
        self.assertIsNone(
            self.store.db.execute("SELECT report FROM maintenance_session").fetchone()[
                0
            ]
        )
        with self.assertRaises(Hold):
            subject.inspect(self.files)
        self.assertEqual(len(self.native_stop_requests), 1)

    def test_interrupted_approval_journal_cannot_dispatch_or_resume(self):
        subject = self.prepare()
        subject.inspect(self.files)
        raw, files, approval = self.controls()
        original = self.store._event

        def fail(kind, payload):
            if kind == "maintenance-session-controls-approved":
                raise OSError("test:approval journal interrupted")
            return original(kind, payload)

        with patch.object(self.store, "_event", fail), self.assertRaises(OSError):
            self.run_controls(raw, files, approval)
        self.assertEqual(len(self.all_sent), 2)
        self.assertIsNone(
            self.store.db.execute(
                "SELECT approval FROM maintenance_session"
            ).fetchone()[0]
        )
        self.assertEqual(
            self.store.db.execute("SELECT active FROM authority").fetchone()[0], 0
        )

    def test_approval_and_revoke_race_cannot_send_when_revoke_wins(self):
        subject = self.prepare()
        subject.inspect(self.files)
        raw, files, approval = self.controls()
        original = self.store._event

        def revoke_after_approval(kind, payload):
            value = original(kind, payload)
            if kind == "maintenance-session-controls-approved":
                # Another revoker waits for the atomic approval transaction.
                threading.Thread(
                    target=lambda: subject.revoke("test:approval race"), daemon=True
                ).start()
            return value

        original_run = subject.controller.run

        def wait_for_revocation(*args, **kwargs):
            self.wait_fenced()
            return original_run(*args, **kwargs)

        with (
            patch.object(self.store, "_event", revoke_after_approval),
            patch.object(subject.controller, "run", wait_for_revocation),
            self.assertRaises(Hold),
        ):
            self.run_controls(raw, files, approval)
        self.assertEqual(len(self.all_sent), 2)


@unittest.skipUnless(sys.platform == "win32", "Windows independent original owner")
class NativeReviewTests(native_fixture.NativeOwnerFixture, unittest.TestCase):
    prepare = SessionTests.prepare
    sender = SessionTests.sender
    snapshot = SessionTests.snapshot
    wait_fenced = SessionTests.wait_fenced

    def test_unanswered_review_fences_and_real_original_owner_stops_surrogate(self):
        self.pending(seconds=25)
        self.seal()
        self.root = self.owner.root
        self.store = Store(self.root / "owner.sqlite")
        self.addCleanup(self.store.close)
        self.launch_raw = (self.root / "owner.sealed.json").read_bytes()
        packet = json.loads(self.launch_raw)
        binding = self.store.db.execute(
            "SELECT binding FROM maintenance_owner"
        ).fetchone()[0]
        self.original = SimpleNamespace(binding=binding)
        self.grant, self.files, self.observed, self.identity, self.plan = (
            fixture.bound_fixture()
        )
        self.grant["lease"] = {
            "owner_nonce": packet["owner_nonce"],
            "expires_utc_ns": packet["lease"]["expires_ns"],
            "expires_mono_ns": packet["lease"]["expires_mono_ns"],
        }
        # Guest reports, native queries and this caller-to-controller mapping are
        # synthetic. Only the original owner/process/stop loop is native here.
        self.identities = {
            os.getpid(): packet["controller"],
            packet["owner"]["pid"]: packet["owner"],
        }
        self.sent, self.phase_sent, self.all_sent = [], [], []
        self.stops, self.native_stop_requests, self.fail_at, self.bad_host = (
            [],
            [],
            None,
            False,
        )
        self.stop = lambda _: self.fail(
            "review expiry must not ask the controller to issue a stop"
        )
        subject = self.prepare(seconds=0.7)
        subject.inspect(self.files)
        self.wait_fenced()
        result = self.terminal()
        self.assertEqual(
            result["status"],
            "original-owner-stop-command-returned-not-poweroff-acceptance",
        )
        calls = (self.root / "surrogate.calls.jsonl").read_text().splitlines()
        self.assertEqual(len(calls), 1)
        self.assertFalse(json.loads(calls[0])["actual_VM_command"])
        self.assertEqual(len(self.all_sent), 2)
        row = self.store.db.execute("SELECT * FROM lease").fetchone()
        self.assertEqual({k: row[k] for k in subject.lease}, subject.lease)


if __name__ == "__main__":
    unittest.main()
