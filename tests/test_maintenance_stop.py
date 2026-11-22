"""Original-owner stop conformance. All VM states/approvals are synthetic.

Native cases replace the VBox command with an isolated scratch Python process.
This suite never executes VBoxManage controlvm.
"""

import copy
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from research.validation import maintenance_host as host
from research.validation import maintenance_stop as stop
from research.validation import windows_readonly as native
from research.validation.driver import stop_vm
from research.validation.store import Hold, Store
from research.validation.supervisor import LeaseSupervisor
from research.validation.transfer_commands import canonical, digest


class StopFixture:
    native_identity = False

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.store = Store(self.folder / "owner.sqlite")
        self.addCleanup(self.store.close)
        self.profile = {
            "target_vm_uuid": stop.VM_IDS["guard"],
            "lease_expires_utc_ns": time.time_ns() + 600 * 10**9,
            "vboxmanage": str(stop.VBOX),
        }
        self.supervisor = LeaseSupervisor(self.store, self.profile)
        if self.native_identity:
            self.process = host.process_identity(os.getpid())
            self.identity = host.process_identity
        else:
            self.process = {
                "pid": os.getpid(),
                "created_filetime": 123,
                "image": r"C:\fixture\python.exe",
            }
            self.identity = lambda _pid: dict(self.process)
            self.enterContext(patch.object(stop, "process_identity", self.identity))
        self.plan = stop.draft("guard")
        self.plan.update(
            owner_nonce="7" * 32,
            process=dict(self.process),
            lease={
                k: self.store.db.execute("SELECT * FROM lease").fetchone()[k]
                for k in host.OWNER_KEYS
            },
            approval={"native_stop": "test:surrogate-only-no-native-VM-approval"},
        )
        owner_raw = canonical(
            {
                "format": "mcli1-original-owner-v1",
                "owner_nonce": self.plan["owner_nonce"],
                "lease": self.plan["lease"],
                "process": self.process,
            }
        )
        self.plan["owner_binding_sha256"] = digest(owner_raw)
        self.profile["bounded_stop"] = {
            "plan": self.plan,
            "sha256": digest(canonical(self.plan)),
        }
        self.owner = host.RegisteredOwner(
            self.supervisor, self.plan["owner_nonce"], self.identity
        )
        self.assertEqual(self.owner.binding, owner_raw)
        self.root = self.folder / "stops"
        self.enterContext(patch.object(stop, "STOPS_ROOT", self.root))
        self.check_executable = stop.executable
        self.enterContext(patch.object(stop, "executable", lambda plan: None))
        self.calls = []

    def intent_root(self):
        return self.root / self.plan["owner_nonce"]

    def row_state(self):
        return self.store.db.execute("SELECT state FROM lease").fetchone()[0]

    def result(self, pid, exit=0):
        return {
            "pid": pid,
            "exit": exit,
            "stdout": b"bounded surrogate\n",
            "stderr": b"0%...100%\n",
            "job_active_processes": 0,
            "started_mono_ns": time.monotonic_ns(),
            "finished_mono_ns": time.monotonic_ns(),
        }

    def fake_runner(self, exe, args, wall, mono, before_resume):
        self.assertEqual(str(exe), str(stop.VBOX))
        self.assertEqual(args, ["controlvm", self.plan["target_vm_uuid"], "poweroff"])
        self.assertTrue((self.intent_root() / "poweroff.intent.json").exists())
        self.assertEqual(
            self.store.db.execute("SELECT state FROM native_owner_stop").fetchone()[0],
            "possible-send",
        )
        self.assertEqual(self.row_state(), "stopping")
        native.live(wall, mono)
        before_resume(123456)
        self.calls.append(args)
        return self.result(123456)

    def poll(self, runner=None):
        with patch.object(stop, "_run", runner or self.fake_runner):
            return self.owner.poll()


class StopTests(StopFixture, unittest.TestCase):
    def test_default_preview_and_both_unarmed_plans_have_no_native_stop(self):
        for role in stop.VM_IDS:
            raw = canonical(stop.draft(role))
            with self.assertRaisesRegex(Hold, "approval is unbound"):
                stop.checked(raw, digest(raw))
        self.profile["bounded_stop"] = None
        self.store.fence("test unavailable binding")
        with (
            patch.object(
                stop, "_run", side_effect=AssertionError("native stop forbidden")
            ),
            self.assertRaisesRegex(Hold, "plan is unbound"),
        ):
            stop_vm(self.store, self.profile)
        self.assertFalse(self.root.exists())

    def test_original_lease_owner_uses_fixed_command_and_retains_independent_stop_gate(
        self,
    ):
        self.store.fence("test finished")
        self.assertTrue(self.poll())
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.row_state(), "stop-command-returned")
        r = json.loads((self.intent_root() / "command.receipt.json").read_bytes())
        self.assertTrue(r["independent_poweroff_still_required"])
        self.assertEqual(
            r["status"], "original-stop-command-returned-not-poweroff-acceptance"
        )
        self.assertEqual(
            self.store.db.execute("SELECT state FROM native_owner_stop").fetchone()[0],
            "command-returned",
        )
        with self.assertRaisesRegex(Hold, "terminated"):
            self.poll()
        self.assertEqual(len(self.calls), 1)

    def test_expired_original_lease_retains_emergency_stop_without_renewal(self):
        lease = self.plan["lease"]
        with (
            patch.object(stop.time, "time_ns", return_value=lease["expires_ns"] + 1),
            patch.object(
                stop.time, "monotonic_ns", return_value=lease["expires_mono_ns"] + 1
            ),
        ):
            self.assertTrue(self.poll())
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(
            self.store.db.execute("SELECT expires_ns FROM lease").fetchone()[0],
            lease["expires_ns"],
        )
        r = json.loads((self.intent_root() / "command.receipt.json").read_bytes())
        self.assertTrue(r["original_lease_expired_before_command"])

    def test_clock_rollback_triggers_original_stop_without_rewriting_lease(self):
        lease = dict(self.plan["lease"])
        with (
            patch.object(stop.time, "time_ns", return_value=lease["armed_ns"] - 1),
            patch.object(
                stop.time, "monotonic_ns", return_value=lease["armed_mono_ns"] - 1
            ),
        ):
            self.assertTrue(self.poll())
        self.assertEqual(len(self.calls), 1)
        row = self.store.db.execute("SELECT * FROM lease").fetchone()
        self.assertEqual({k: row[k] for k in host.OWNER_KEYS}, lease)

    def test_executable_bytes_and_configuration_root_are_rechecked(self):
        file = self.folder / "VBoxManage.exe"
        file.write_bytes(b"synthetic native program bytes")
        plan = {"hypervisor": {"sha256": digest(file.read_bytes())}}
        with (
            patch.object(stop, "VBOX", file),
            patch.dict(os.environ, {"VBOX_USER_HOME": ""}),
        ):
            self.check_executable(plan)
            file.write_bytes(b"changed executable")
            with self.assertRaisesRegex(Hold, "executable bytes"):
                self.check_executable(plan)
            plan["hypervisor"]["sha256"] = digest(file.read_bytes())
            with (
                patch.dict(os.environ, {"VBOX_USER_HOME": "foreign-config"}),
                self.assertRaisesRegex(Hold, "configuration root"),
            ):
                self.check_executable(plan)

    def test_foreign_target_process_and_extended_lease_refuse_before_intent(self):
        for key, value in (
            ("target_vm_uuid", stop.VM_IDS["executor"]),
            ("process", {**self.process, "pid": self.process["pid"] + 1}),
            (
                "lease",
                {
                    **self.plan["lease"],
                    "expires_ns": self.plan["lease"]["expires_ns"] + 1,
                },
            ),
        ):
            altered = copy.deepcopy(self.plan)
            altered[key] = value
            profile = {
                **self.profile,
                "bounded_stop": {"plan": altered, "sha256": digest(canonical(altered))},
            }
            self.store.db.execute("UPDATE lease SET state='stopping'")
            with self.assertRaises(Hold):
                stop.execute(self.store, profile, runner=self.fake_runner)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.root.exists())

    def test_missing_fence_owner_stop_intent_or_slow_SQL_connection_prevents_dispatch(
        self,
    ):
        with self.assertRaisesRegex(Hold, "intent or fence"):
            stop.execute(self.store, self.profile, runner=self.fake_runner)
        self.store.db.execute("PRAGMA busy_timeout=1000")
        with self.assertRaisesRegex(Hold, "owner connection"):
            stop.execute(self.store, self.profile, runner=self.fake_runner)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.root.exists())

    def test_changed_source_or_missing_approval_refuses_even_with_rehashed_plan(self):
        altered = copy.deepcopy(self.plan)
        altered["approval"]["native_stop"] = None
        with self.assertRaisesRegex(Hold, "approval"):
            stop.checked(canonical(altered), digest(canonical(altered)))
        file = self.folder / "changed-driver.py"
        file.write_bytes(b"unreviewed")
        with (
            patch.dict(stop.SOURCES, {"driver.py": file}),
            self.assertRaisesRegex(Hold, "source cohort"),
        ):
            stop.checked(canonical(self.plan), digest(canonical(self.plan)))
        self.assertFalse(self.root.exists())

    def test_uncertain_command_retains_possible_send_and_filesystem_hold_after_row_deletion(
        self,
    ):
        self.store.fence("test failed delivery")

        def lost(exe, args, wall, mono, gate):
            gate(123456)
            self.calls.append(args)
            raise Hold("lost command acknowledgement")

        with self.assertRaisesRegex(Hold, "lost command"):
            self.poll(lost)
        self.assertEqual(self.row_state(), "stopping")
        self.assertEqual(
            self.store.db.execute("SELECT state FROM native_owner_stop").fetchone()[0],
            "possible-send",
        )
        self.store.db.execute("DELETE FROM native_owner_stop")
        with self.assertRaises(FileExistsError):
            stop.execute(self.store, self.profile, runner=self.fake_runner)
        self.assertEqual(len(self.calls), 1)

    def test_failed_commit_before_process_leaves_fs_intent_and_performs_no_command(
        self,
    ):
        self.store.fence("test journal failure")
        original = self.store._event

        def failed(kind, payload):
            if kind == "original-native-stop-intent":
                raise Hold("synthetic commit failure")
            return original(kind, payload)

        with (
            patch.object(self.store, "_event", failed),
            self.assertRaisesRegex(Hold, "commit failure"),
        ):
            self.poll()
        self.assertTrue((self.intent_root() / "poweroff.intent.json").exists())
        self.assertEqual(self.calls, [])
        self.assertEqual(self.row_state(), "stopping")

    def test_source_change_before_resume_never_dispatches(self):
        self.store.fence("test source race")
        file = self.folder / "changed-source"
        file.write_bytes(b"changed")

        def changed(exe, args, wall, mono, gate):
            with patch.dict(stop.SOURCES, {"driver.py": file}):
                gate(123456)
            self.fail("unreviewed command")

        with self.assertRaisesRegex(Hold, "source cohort"):
            self.poll(changed)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.row_state(), "stopping")

    def test_caller_profile_changes_after_admission_cannot_retarget_frozen_command(
        self,
    ):
        self.store.fence("test caller race")
        original_target = self.plan["target_vm_uuid"]

        def changed(exe, args, wall, mono, gate):
            self.profile["target_vm_uuid"] = stop.VM_IDS["executor"]
            self.assertEqual(args[1], original_target)
            return self.fake_runner(exe, args, wall, mono, gate)

        self.assertTrue(self.poll(changed))
        self.assertEqual(self.calls[0][1], original_target)

    def test_nonzero_exit_keeps_bounded_diagnostics_and_never_completes_lease(self):
        self.store.fence("test native refusal")

        def nonzero(exe, args, wall, mono, gate):
            gate(123456)
            return self.result(123456, 1)

        with self.assertRaisesRegex(Hold, "command failed"):
            self.poll(nonzero)
        self.assertEqual(self.row_state(), "stopping")
        self.assertEqual(
            (self.intent_root() / "stderr.bin").read_bytes(), b"0%...100%\n"
        )
        self.assertTrue((self.intent_root() / "process.result.json").exists())
        self.assertFalse((self.intent_root() / "command.receipt.json").exists())

    def test_missing_gate_or_unreaped_result_cannot_become_a_command_receipt(self):
        self.store.fence("test bad worker")
        with self.assertRaisesRegex(Hold, "not reaped"):
            self.poll(lambda *_: self.result(123456))
        self.assertFalse((self.intent_root() / "command.receipt.json").exists())

    def test_failed_receipt_commit_keeps_uncertainty_after_surrogate_effect(self):
        self.store.fence("test receipt failure")
        original = self.store._event

        def failed(kind, payload):
            if kind == "original-native-stop-command-returned":
                raise Hold("receipt commit failed")
            return original(kind, payload)

        with (
            patch.object(self.store, "_event", failed),
            self.assertRaisesRegex(Hold, "receipt commit failed"),
        ):
            self.poll()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.row_state(), "stopping")
        self.assertEqual(
            self.store.db.execute("SELECT state FROM native_owner_stop").fetchone()[0],
            "possible-send",
        )
        self.assertTrue((self.intent_root() / "command.receipt.json").exists())


@unittest.skipUnless(sys.platform == "win32", "native Windows surrogate process checks")
class NativeStopTests(StopFixture, unittest.TestCase):
    native_identity = True

    def surrogate(self, source, alter_gate=None):
        def run(exe, args, wall, mono, before_resume):
            self.assertEqual(str(exe), str(stop.VBOX))
            self.assertEqual(
                args, ["controlvm", self.plan["target_vm_uuid"], "poweroff"]
            )

            def gate(pid):
                before_resume(pid)
                if alter_gate is not None:
                    alter_gate(pid)

            self.calls.append(args)
            return native._run(
                sys.executable, ["-I", "-B", "-c", source], wall, mono, gate
            )

        return run

    def test_default_original_owner_path_runs_only_the_explicit_native_surrogate(self):
        self.store.fence("test native surrogate")
        self.assertTrue(self.poll(self.surrogate('print("surrogate-poweroff-only")')))
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.row_state(), "stop-command-returned")
        self.assertEqual(
            (self.intent_root() / "stdout.bin").read_bytes().strip(),
            b"surrogate-poweroff-only",
        )

    def test_parent_gate_failure_prevents_native_surrogate_side_effect(self):
        self.store.fence("test suspended gate failure")
        sentinel = self.folder / "must-not-exist"

        def deny(_):
            raise Hold("gate closed before resume")

        source = f'from pathlib import Path;Path({str(sentinel)!r}).write_text("wrong")'
        with self.assertRaisesRegex(Hold, "gate closed"):
            self.poll(self.surrogate(source, deny))
        self.assertFalse(sentinel.exists())
        self.assertEqual(self.row_state(), "stopping")

    def test_native_surrogate_timeout_and_output_flood_are_held_without_replay(self):
        self.store.fence("test native timeout")

        def short(exe, args, wall, mono, before_resume):
            return self.surrogate(
                'import os,time;os.write(1,b"x"*200000);time.sleep(30)'
            )(
                exe,
                args,
                min(wall, time.time_ns() + 150_000_000),
                min(mono, time.monotonic_ns() + 150_000_000),
                before_resume,
            )

        start = time.monotonic()
        with self.assertRaises(Hold):
            self.poll(short)
        self.assertLess(time.monotonic() - start, 2)
        self.assertEqual(self.row_state(), "stopping")
        self.assertFalse((self.intent_root() / "command.receipt.json").exists())

    def test_partial_pipe_allocation_failure_closes_every_created_descriptor(self):
        original = native.os.pipe
        allocated = []
        opened = []
        original_open = native.os.open

        def keep_open(*args, **kwargs):
            fd = original_open(*args, **kwargs)
            opened.append(fd)
            return fd

        def fail_second():
            if allocated:
                raise OSError("synthetic second pipe allocation failure")
            pair = original()
            allocated.extend(pair)
            return pair

        with (
            patch.object(native.os, "pipe", side_effect=fail_second),
            patch.object(native.os, "open", side_effect=keep_open),
            self.assertRaisesRegex(OSError, "second pipe"),
        ):
            native._run(
                sys.executable,
                ["-I", "-B", "-c", "pass"],
                time.time_ns() + 10**9,
                time.monotonic_ns() + 10**9,
            )
        self.assertEqual(len(allocated) + len(opened), 3)
        for fd in allocated + opened:
            with self.assertRaises(OSError):
                os.fstat(fd)


if __name__ == "__main__":
    unittest.main()
