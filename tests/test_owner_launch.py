"""Owner preparation; all VM state/approval is synthetic, all stops are surrogates."""

import contextlib
import copy
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from research.validation import owner_launch as launch
from research.validation import owner_process as worker
from research.validation.maintenance_host import process_identity
from research.validation.maintenance_serial import KillJob
from research.validation.store import Hold, Store
from research.validation.transfer_commands import canonical, digest

FIXTURES = Path(__file__).parent / "fixtures"


class PacketTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        nonce = "5" * 32
        owner = {
            "pid": os.getpid(),
            "created_filetime": 1,
            "image": r"C:\fixture\python.exe",
        }
        lease = {
            "target": worker.stop.VM_IDS["guard"],
            "armed_ns": time.time_ns(),
            "expires_ns": time.time_ns() + 500 * 10**9,
            "armed_mono_ns": time.monotonic_ns(),
            "expires_mono_ns": time.monotonic_ns() + 500 * 10**9,
        }
        plan = worker.stop.draft("guard")
        plan.update(
            owner_nonce=nonce,
            process=owner,
            lease=lease,
            approval={"native_stop": "test:synthetic"},
        )
        binding = {
            "format": "mcli1-original-owner-v1",
            "owner_nonce": nonce,
            "lease": lease,
            "process": owner,
        }
        plan["owner_binding_sha256"] = digest(canonical(binding))
        self.packet = {
            "format": "mcli1-independent-owner-v1",
            "role": "guard",
            "owner_nonce": nonce,
            "owner_job": "Local\\MCLI1Owner-" + nonce,
            "controller_job": "Local\\MCLI1Controller-" + nonce,
            "owner": owner,
            "controller": {**owner, "pid": owner["pid"] + 1},
            "bootstrap": {**owner, "pid": owner["pid"] + 2},
            "root": worker.root_identity(self.root),
            "lease": lease,
            "approval": {"owner_start": "test:synthetic"},
            "profile": {
                "target_vm_uuid": lease["target"],
                "lease_expires_utc_ns": lease["expires_ns"],
                "vboxmanage": str(worker.stop.VBOX),
                "bounded_stop": {"plan": plan, "sha256": digest(canonical(plan))},
            },
            "sources": dict(worker.SOURCE_EPOCH),
        }

    def check(self, packet=None):
        packet = self.packet if packet is None else packet
        raw = canonical(packet)
        return worker.checked(
            raw, digest(raw), self.root, identity=lambda _pid: dict(packet["owner"])
        )

    def test_sealed_packet_requires_current_source_and_exact_original_plan(self):
        self.assertEqual(self.check(), self.packet)
        changed = copy.deepcopy(self.packet)
        changed["sources"]["owner_launch.py"] = "0" * 64
        with self.assertRaisesRegex(Hold, "source cohort"):
            self.check(changed)
        changed = copy.deepcopy(self.packet)
        changed["lease"] = {
            **changed["lease"],
            "expires_ns": changed["lease"]["expires_ns"] + 1,
        }
        with self.assertRaisesRegex(Hold, "stop plan differ"):
            self.check(changed)

    def test_missing_approval_shared_process_or_changed_root_refuses_before_registration(
        self,
    ):
        for field in ("approval", "bootstrap", "root"):
            changed = copy.deepcopy(self.packet)
            if field == "approval":
                changed[field]["owner_start"] = None
            elif field == "bootstrap":
                changed[field] = changed["owner"]
            else:
                changed[field]["inode"] += 1
            with self.subTest(field=field), self.assertRaises(Hold):
                self.check(changed)

    def test_stop_approval_and_packet_bytes_cannot_change_after_seal(self):
        changed = copy.deepcopy(self.packet)
        p = changed["profile"]["bounded_stop"]
        p["plan"]["approval"]["native_stop"] = None
        p["sha256"] = digest(canonical(p["plan"]))
        with self.assertRaisesRegex(Hold, "approval is unbound"):
            self.check(changed)
        with self.assertRaisesRegex(Hold, "digest differs"):
            worker.checked(canonical(self.packet), "0" * 64, self.root)

    def test_ready_publication_is_complete_exclusive_and_retains_staging(self):
        path = self.root / "ready.json"
        raw = canonical({"proof": "ready"})
        worker.publish(path, raw)
        self.assertEqual(worker.read_packet(path), raw)
        self.assertEqual(path.with_name(path.name + ".staged").read_bytes(), raw)
        with self.assertRaises(FileExistsError):
            worker.publish(path, raw)

    def test_packet_size_and_default_CLI_never_launch_an_owner(self):
        path = self.root / "oversized"
        path.write_bytes(b"x" * 65537)
        with self.assertRaisesRegex(Hold, "exceeds bound"):
            worker.read_packet(path)
        out = io.StringIO()
        with (
            patch.object(sys, "argv", ["owner_launch"]),
            contextlib.redirect_stdout(out),
            patch.object(
                launch, "PendingOwner", side_effect=AssertionError("unexpected launch")
            ),
        ):
            launch.main()
        preview = json.loads(out.getvalue())
        self.assertEqual(preview["native_calls"], 0)
        self.assertFalse(preview["launch_available"])


class NativeOwnerFixture:
    """Shared native fixture; every owner stop uses an isolated Python surrogate."""

    artifact_root = None

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.nonce = uuid4().hex
        self.controller_job = KillJob("Local\\MCLI1Controller-" + self.nonce)
        self.controller = launch.SuspendedChild(
            ["-I", "-B", "-c", "import time;time.sleep(30)"], self.controller_job
        )
        self.controller.resume()
        self.owner = None
        self.owner_identity = None
        self.addCleanup(self.cleanup_processes)

    def cleanup_processes(self):
        if self.owner is not None:
            database = self.owner.root / "owner.sqlite"
            if database.exists():
                s = Store(database)
                try:
                    s.fence("test-only cleanup of surrogate owner")
                finally:
                    s.close()
            if self.owner.sealed and self.owner_identity is not None:
                end = time.monotonic() + 4
                while self.alive(self.owner_identity) and time.monotonic() < end:
                    time.sleep(0.01)
            self.owner.close()
            if self.owner_identity is not None:
                end = time.monotonic() + 1
                while self.alive(self.owner_identity) and time.monotonic() < end:
                    time.sleep(0.01)
                self.assertFalse(
                    self.alive(self.owner_identity),
                    "surrogate owner did not exit during cleanup",
                )
        if self.controller_job.handle:
            self.controller_job.close()
        self.controller.close()
        if self.artifact_root is not None:
            destination = Path(self.artifact_root) / self._testMethodName
            shutil.copytree(self.base, destination)

    @staticmethod
    def alive(record):
        try:
            return process_identity(record["pid"]) == record
        except Hold:
            return False

    def pending(self, mode="success", seconds=15):
        root = self.base / "owner"
        original = launch.SuspendedChild

        def factory(args, job):
            self.assertEqual(args[:3], ["-I", "-B", "-c"])
            prelude = f"import runpy;runpy.run_path({str(FIXTURES / 'owner_surrogate_child.py')!r})['install_surrogate']({str(root)!r},{mode!r})\n"
            return original([*args[:3], prelude + args[3]], job)

        with patch.object(launch, "SuspendedChild", factory):
            self.owner = launch.PendingOwner(
                root,
                "guard",
                self.nonce,
                process_identity(self.controller.pid),
                time.time_ns() + seconds * 10**9,
                "test:provisional-process-only",
            )
        self.owner_identity = dict(self.owner.owner)
        return self.owner

    def seal(self):
        plan = copy.deepcopy(self.owner.proposal)
        plan["approval"]["native_stop"] = "test:surrogate-only"
        self.owner.seal(
            canonical(plan), digest(canonical(plan)), "test:owner-process-only"
        )
        return self.owner.ready()

    def terminal(self):
        end = time.monotonic() + 5
        path = self.owner.root / "owner.terminal.json"
        while not path.exists() and time.monotonic() < end:
            time.sleep(0.01)
        self.assertTrue(path.exists(), "surrogate owner did not report terminal state")
        result = json.loads(path.read_bytes())
        while self.alive(self.owner_identity) and time.monotonic() < end:
            time.sleep(0.01)
        self.assertFalse(self.alive(self.owner_identity))
        return result


@unittest.skipUnless(sys.platform == "win32", "Windows independent-job process checks")
class NativeOwnerTests(NativeOwnerFixture, unittest.TestCase):
    def test_owner_survives_controller_job_close_and_bootstrap_handle_release(self):
        self.pending()
        ready = self.seal()
        self.assertTrue(ready["controller_job_separate"])
        self.owner.close()
        self.assertTrue(self.alive(self.owner_identity))
        self.controller_job.close()
        result = self.terminal()
        self.assertEqual(
            result["status"],
            "original-owner-stop-command-returned-not-poweroff-acceptance",
        )
        calls = [
            json.loads(line)
            for line in (self.owner.root / "surrogate.calls.jsonl")
            .read_text()
            .splitlines()
        ]
        self.assertEqual(len(calls), 1)
        self.assertFalse(calls[0]["controller_live"])
        self.assertFalse(calls[0]["actual_VM_command"])

    def test_owner_expiry_is_original_and_does_not_depend_on_controller_failure(self):
        self.pending(seconds=2)
        original = dict(self.owner.lease)
        self.seal()
        result = self.terminal()
        self.assertIsNotNone(process_identity(self.controller.pid))
        self.assertEqual(
            result["status"],
            "original-owner-stop-command-returned-not-poweroff-acceptance",
        )
        s = Store(self.owner.root / "owner.sqlite")
        try:
            row = s.db.execute("SELECT * FROM lease").fetchone()
            self.assertEqual({k: row[k] for k in original}, original)
        finally:
            s.close()

    def test_unapproved_or_altered_plan_cannot_resume_suspended_owner(self):
        self.pending()
        raw = canonical(self.owner.proposal)
        with self.assertRaisesRegex(Hold, "approval is unbound"):
            self.owner.seal(raw, digest(raw), "test:start")
        changed = copy.deepcopy(self.owner.proposal)
        changed["approval"]["native_stop"] = "test:surrogate-only"
        changed["lease"]["expires_ns"] += 1
        with self.assertRaisesRegex(Hold, "proposal"):
            self.owner.seal(
                canonical(changed), digest(canonical(changed)), "test:start"
            )
        self.assertFalse((self.owner.root / "owner.ready.json").exists())
        self.assertFalse((self.owner.root / "surrogate.calls.jsonl").exists())
        exact = copy.deepcopy(self.owner.proposal)
        exact["approval"]["native_stop"] = "test:surrogate-only"
        pretty = json.dumps(exact, indent=2).encode()
        with self.assertRaisesRegex(Hold, "canonical bytes"):
            self.owner.seal(pretty, digest(pretty), "test:start")

    def test_lost_surrogate_ack_is_held_without_restart_or_replay(self):
        self.pending(mode="lost-ack")
        self.seal()
        self.controller_job.close()
        result = self.terminal()
        self.assertEqual(result["status"], "held-owner-state-not-accepted")
        self.assertTrue((self.owner.root / "surrogate.effect").exists())
        self.assertEqual(
            len((self.owner.root / "surrogate.calls.jsonl").read_text().splitlines()), 1
        )

    def test_same_controller_job_or_fenced_ready_ledger_cannot_authorize_start(self):
        self.pending()
        self.seal()
        with self.assertRaisesRegex(Hold, "outside the controller kill job"):
            worker.outside_controller(
                process_identity(self.controller.pid),
                process_identity(self.controller.pid),
                "Local\\MCLI1Controller-" + self.nonce,
            )
        s = Store(self.owner.root / "owner.sqlite")
        try:
            s.fence("test reject stale ready")
        finally:
            s.close()
        with self.assertRaises(Hold):
            self.owner.ready()
        self.terminal()

    def test_outside_bootstrap_death_does_not_kill_ready_owner(self):
        root = self.base / "detached-owner"
        nonce = uuid4().hex
        p = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-B",
                str(FIXTURES / "owner_bootstrap_exit.py"),
                str(root),
                nonce,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            stdout, stderr = p.communicate(timeout=8)
            self.assertEqual(p.returncode, 0, (stdout, stderr))
            observed = json.loads((root / "bootstrap.observed.json").read_bytes())
            end = time.monotonic() + 5
            while (
                not (root / "owner.terminal.json").exists() and time.monotonic() < end
            ):
                time.sleep(0.01)
            self.assertTrue((root / "owner.terminal.json").exists())
            calls = [
                json.loads(line)
                for line in (root / "surrogate.calls.jsonl").read_text().splitlines()
            ]
            self.assertEqual(len(calls), 1)
            self.assertFalse(calls[0]["bootstrap_live"])
            self.assertFalse(calls[0]["controller_live"])
            self.assertEqual(calls[0]["owner_pid"], observed["owner"]["pid"])
            while self.alive(observed["owner"]) and time.monotonic() < end:
                time.sleep(0.01)
            self.assertFalse(self.alive(observed["owner"]))
        finally:
            if p.poll() is None:
                p.kill()
                p.communicate(timeout=1)


if __name__ == "__main__":
    unittest.main()
