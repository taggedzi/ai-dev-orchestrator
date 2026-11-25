"""Controller-loss preparation: VM observations are explicitly synthetic."""

import copy
import json
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from research.validation import startup_qualification as q
from research.validation.store import Hold
from research.validation.transfer_commands import canonical, digest
from tests import test_boot_preconditions as boot_tests
from tests import test_frontend_start as start_tests
from tests import test_owner_launch as owner_tests


def identity(pid):
    return {"pid": pid, "created_filetime": pid, "image": "synthetic-Python-only"}


def samples(process):
    now = time.monotonic_ns()
    return [
        {
            "observed_mono_ns": now - offset,
            "members": [process],
            "session": {
                "vm_uuid": q.target_uuid(),
                "state_before": "Locked",
                "state_after": "Locked",
                "pid": process["pid"],
            },
        }
        for offset in (2_000_000, 1_000_000)
    ]


class LossReviewTests(unittest.TestCase):
    def setUp(self):
        now, mono = time.time_ns(), time.monotonic_ns()
        self.inputs = {"backup": {}, "profile": {}}
        self.review = {
            "format": q.LOSS_REVIEW_FORMAT,
            "created_utc_ns": now,
            "sources": dict(q.SOURCE_EPOCH),
            "inputs": self.inputs,
            "policy": q.review_policy(False, self.inputs, controller_loss=True),
            "original_lease": {
                "expires_ns": now + 600 * 10**9,
                "expires_mono_ns": mono + 600 * 10**9,
            },
        }
        self.approval = {
            "format": "mcli1-one-guard-startup-approval-v1",
            "review_sha256": digest(canonical(self.review)),
            "reference": "test:Python-only-loss-preparation",
            "approved_utc_ns": now,
        }
        self.patch = patch.object(q, "fixed_inputs", return_value=self.inputs)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def checked(self):
        raw = canonical(self.review)
        return q.approved_review(raw, digest(raw), canonical(self.approval))

    def test_loss_requires_exact_fault_policy_and_preserves_original_lease(self):
        original = copy.deepcopy(self.review)
        self.assertEqual(self.checked()[0], original)
        self.review["policy"] = dict(q.POLICY)
        self.approval["review_sha256"] = digest(canonical(self.review))
        with self.assertRaises(Hold):
            self.checked()

    def test_normal_review_cannot_reuse_approval_for_loss_case(self):
        self.approval["review_sha256"] = digest(
            canonical({**self.review, "format": "mcli1-one-guard-startup-review-v1"})
        )
        with self.assertRaises(Hold):
            self.checked()

    def test_recovery_and_loss_cannot_be_combined_or_extend_lease(self):
        with self.assertRaisesRegex(Hold, "poweroff-only"):
            q.review_policy(True, self.inputs, controller_loss=True)
        self.review["original_lease"]["expires_mono_ns"] = (
            time.monotonic_ns() + 59 * 10**9
        )
        self.approval["review_sha256"] = digest(canonical(self.review))
        with self.assertRaisesRegex(Hold, "late"):
            self.checked()


class LossBarrierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.member = identity(5)
        self.frames = samples(self.member)
        self.adapter = SimpleNamespace(
            lock=threading.RLock(),
            _live=Mock(return_value=[self.member]),
            joined=self.member,
            sha="a" * 64,
            packet={"lease": {"expires_ns": 1}},
        )
        self.exit = patch.object(
            q.os, "_exit", side_effect=SystemExit(q.LOSS_EXIT)
        ).start()
        patch.object(q.start.host, "process_identity", return_value=identity(3)).start()
        self.addCleanup(patch.stopall)

    def test_two_joined_samples_publish_original_binding_then_skip_cleanup(self):
        with self.assertRaises(SystemExit) as caught:
            q._controller_loss_exit(self.root, "b" * 64, self.adapter, self.frames)
        self.assertEqual(caught.exception.code, q.LOSS_EXIT)
        value = json.loads((self.root / "controller.loss.intent.json").read_bytes())
        self.assertEqual(value["original_lease"], self.adapter.packet["lease"])
        self.assertEqual(value["samples"], self.frames)
        self.assertFalse(value["normal_stop_requested"])
        self.assertEqual(self.adapter._live.call_count, 2)
        self.exit.assert_called_once_with(q.LOSS_EXIT)
        self.assertFalse((self.root / "frontend.owner-stop.intent.json").exists())

    def test_missing_foreign_or_duplicate_sample_does_not_inject_fault(self):
        for change in (
            self.frames[:1],
            [self.frames[0]] * 2,
            [
                self.frames[0],
                {
                    **self.frames[1],
                    "session": {**self.frames[1]["session"], "pid": 999},
                },
            ],
        ):
            with self.subTest(change=change), self.assertRaises(Hold):
                q._controller_loss_exit(self.root, "b" * 64, self.adapter, change)
        self.exit.assert_not_called()
        self.assertFalse((self.root / "controller.loss.intent.json").exists())

    def test_normal_stop_or_revocation_refuses_fault(self):
        (self.root / "frontend.owner-stop.intent.json").write_bytes(
            b"already requested"
        )
        with self.assertRaises(Hold):
            q._controller_loss_exit(self.root, "b" * 64, self.adapter, self.frames)
        self.exit.assert_not_called()
        (self.root / "frontend.owner-stop.intent.json").unlink()
        self.adapter._live.side_effect = Hold("revoked")
        with self.assertRaisesRegex(Hold, "revoked"):
            q._controller_loss_exit(self.root, "b" * 64, self.adapter, self.frames)
        self.exit.assert_not_called()

    def test_publication_failure_does_not_inject_fault(self):
        with (
            patch.object(q.owner, "publish", side_effect=OSError("lost write")),
            self.assertRaises(OSError),
        ):
            q._controller_loss_exit(self.root, "b" * 64, self.adapter, self.frames)
        self.exit.assert_not_called()

    def test_authority_changed_during_publication_never_exits_at_fault_barrier(self):
        self.adapter._live.side_effect = [[self.member], Hold("lease changed")]
        with self.assertRaisesRegex(Hold, "lease changed"):
            q._controller_loss_exit(self.root, "b" * 64, self.adapter, self.frames)
        self.exit.assert_not_called()
        self.assertTrue((self.root / "controller.loss.intent.json").exists())


class LossProofTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / "owner"
        self.folder.mkdir()
        self.stoproot = self.root / "stops" / ("1" * 32)
        self.stoproot.mkdir(parents=True)
        lease = {
            "armed_ns": time.time_ns() - 10**9,
            "armed_mono_ns": time.monotonic_ns() - 10**9,
            "expires_ns": time.time_ns() + 600 * 10**9,
            "expires_mono_ns": time.monotonic_ns() + 600 * 10**9,
            "target": q.target_uuid(),
        }
        self.review = {
            "format": q.LOSS_REVIEW_FORMAT,
            "inputs": {},
            "sources": dict(q.SOURCE_EPOCH),
            "policy": q.review_policy(False, {}, controller_loss=True),
            "original_lease": lease,
            "controller": identity(3),
            "owner": identity(4),
            "original_stop_proposal": {"owner_nonce": "1" * 32},
        }
        self.write(self.root / "review.json", self.review)
        self.bound = {
            "grant_sha256": "a" * 64,
            "process": identity(5),
            "original_lease": lease,
        }
        self.write(self.folder / "frontend.session.receipt.json", self.bound)
        self.write(
            self.folder / "owner.sealed.json",
            {
                "lease": lease,
                "controller": identity(3),
                "owner": identity(4),
                "owner_nonce": "1" * 32,
                "profile": {"bounded_stop": {"sha256": "c" * 64}},
            },
        )
        self.intent = {
            "format": "mcli1-joined-controller-loss-intent-v1",
            "review_sha256": digest(canonical(self.review)),
            "grant_sha256": "a" * 64,
            "original_lease": lease,
            "controller": identity(3),
            "members": [identity(5)],
            "samples": samples(identity(5)),
            "exit_code": q.LOSS_EXIT,
            "normal_stop_requested": False,
            "issued_utc_ns": time.time_ns(),
            "issued_mono_ns": time.monotonic_ns(),
        }
        self.write(self.folder / "controller.loss.intent.json", self.intent)
        self.db = sqlite3.connect(self.folder / "owner.sqlite")
        self.addCleanup(self.db.close)
        self.db.executescript(
            "CREATE TABLE lease(armed_ns,armed_mono_ns,expires_ns,expires_mono_ns,target);"
            "CREATE TABLE authority(active);CREATE TABLE frontend_start(state,grant_sha,receipt_sha);"
            "CREATE TABLE native_owner_stop(state,child_pid,receipt_sha,plan_sha);"
        )
        self.db.execute("INSERT INTO lease VALUES(?,?,?,?,?)", tuple(lease.values()))
        self.db.execute("INSERT INTO authority VALUES(0)")
        self.db.execute(
            "INSERT INTO frontend_start VALUES(?,?,?)",
            ("session-bound", "a" * 64, digest(canonical(self.bound))),
        )
        self.db.execute(
            "INSERT INTO native_owner_stop VALUES(?,?,?,?)",
            ("possible-send", 8, None, "c" * 64),
        )
        self.db.commit()
        self.write(
            self.stoproot / "process.result.json",
            {"exit": 1, "pid": 8, "job_active_processes": 0},
        )
        self.pending = SimpleNamespace(
            root=self.folder, child=SimpleNamespace(poll=lambda: 1)
        )
        self.controller = SimpleNamespace(poll=lambda: q.LOSS_EXIT)
        self.job = SimpleNamespace(active=lambda: 0)
        self.state = "aborted"
        case = self

        class Observer:
            last = None

            def __init__(self, _role):
                pass

            def __call__(self):
                slot = q.start.backup.SLOTS["guard"]
                frame = boot_tests.snapshot(
                    {
                        "role": "guard",
                        "target": {
                            "vm_uuid": slot["vm_uuid"],
                            "dmi_uuid": slot["vm_uuid"],
                            "disk_uuid": slot["disk_uuid"],
                        },
                    }
                )
                frame["machine"] = frame["machine"].replace(
                    b'"poweroff"', json.dumps(case.state).encode()
                )
                frame["session"] = {
                    "vm_uuid": slot["vm_uuid"],
                    "state_before": "Unlocked",
                    "state_after": "Unlocked",
                    "pid": 0,
                }
                self.last = {k: frame[k] for k in ("machine", "medium")}
                return frame

        self.retired = patch.object(q, "process_retired", return_value=True).start()
        patch.object(q.owner.stop, "STOPS_ROOT", self.root / "stops").start()
        patch.object(q.session, "NativeObserver", Observer).start()
        self.addCleanup(patch.stopall)

    @staticmethod
    def write(path, value):
        path.write_bytes(canonical(value))

    def prove(self):
        return q.controller_loss_proof(
            self.root, self.review, self.pending, self.controller, self.job
        )

    def test_aborted_and_nonzero_original_stop_are_containment_only(self):
        proof = self.prove()
        self.assertTrue(proof["controller_loss_case_measured"])
        self.assertEqual(proof["original_stop_exit"], 1)
        for key in (
            "original_stop_accepted",
            "native_settlement_qualified",
            "normal_start_session_stop_qualified",
            "guest_ready",
        ):
            self.assertFalse(proof[key])
        self.assertFalse((self.stoproot / "command.receipt.json").exists())

    def test_even_poweroff_with_original_command_ack_does_not_accept_normal_stop(self):
        self.state = "poweroff"
        receipt = {
            "exit": 0,
            "child_pid": 8,
            "job_active_processes": 0,
            "target_vm_uuid": q.target_uuid(),
            "owner_nonce": "1" * 32,
            "plan_sha256": "c" * 64,
        }
        self.write(self.stoproot / "command.receipt.json", receipt)
        self.write(
            self.stoproot / "process.result.json",
            {"exit": 0, "pid": 8, "job_active_processes": 0},
        )
        self.db.execute(
            "UPDATE native_owner_stop SET state='command-returned',receipt_sha=?",
            (digest(canonical(receipt)),),
        )
        self.db.commit()
        proof = self.prove()
        self.assertTrue(proof["original_stop_command_acknowledged"])
        self.assertFalse(proof["original_stop_accepted"])

    def test_unfenced_authority_or_wrong_stop_plan_holds(self):
        self.db.execute("UPDATE authority SET active=1")
        self.db.commit()
        with self.assertRaisesRegex(Hold, "durable fence"):
            self.prove()
        self.db.execute("UPDATE authority SET active=0")
        self.db.execute("UPDATE native_owner_stop SET plan_sha=?", ("d" * 64,))
        self.db.commit()
        with self.assertRaisesRegex(Hold, "durable fence"):
            self.prove()

    def test_unknown_retirement_or_wrong_exit_cannot_qualify(self):
        self.retired.return_value = False
        with self.assertRaisesRegex(Hold, "remains live"):
            self.prove()
        self.controller.poll = lambda: 0
        with self.assertRaisesRegex(Hold, "reviewed joined-session barrier"):
            self.prove()

    def test_running_vm_is_not_containment(self):
        self.state = "running"
        with self.assertRaisesRegex(Hold, "still active"):
            self.prove()

    def test_lost_original_stop_result_or_fake_receipt_holds(self):
        (self.stoproot / "process.result.json").unlink()
        with self.assertRaises(FileNotFoundError):
            self.prove()
        self.write(
            self.stoproot / "process.result.json",
            {"exit": 1, "pid": 8, "job_active_processes": 0},
        )
        self.write(self.stoproot / "command.receipt.json", {})
        with self.assertRaisesRegex(Hold, "must remain held"):
            self.prove()

    def test_original_fault_time_is_not_reset_by_observation(self):
        self.intent["issued_mono_ns"] -= 11 * 10**9
        self.write(self.folder / "controller.loss.intent.json", self.intent)
        with self.assertRaisesRegex(Hold, "exceeded ten seconds"):
            self.prove()


@unittest.skipUnless(sys.platform == "win32", "Windows controller job required")
class LossNativeTests(owner_tests.NativeOwnerFixture, unittest.TestCase):
    """Actual Windows jobs, Python frontends and original owner; zero VM calls."""

    artifact_root = None
    setUp = start_tests.NativeStartTests.setUp
    prepared = start_tests.NativeStartTests.prepared
    wait_file = start_tests.NativeStartTests.wait_file
    verify_stop = start_tests.NativeStartTests.verify_stop

    def test_reviewed_fault_exits_controller_once_and_reaps_actual_python_family(self):
        root = self.prepared(mode="qualification-loss")
        intent = self.wait_file("controller.loss.intent.json")
        self.verify_stop()
        end = time.monotonic() + 2
        while (
            self.controller.poll() is None or self.controller_job.active()
        ) and time.monotonic() < end:
            time.sleep(0.01)
        self.assertEqual(self.controller.poll(), q.LOSS_EXIT)
        self.assertEqual(self.controller_job.active(), 0)
        self.assertTrue(all(q.process_retired(row) for row in intent["members"]))
        self.assertEqual(len(intent["samples"]), 2)
        self.assertFalse((root / "frontend.owner-stop.intent.json").exists())
