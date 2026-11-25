"""Native Windows scratch processes only; no VirtualBox executable is launched."""

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from research.validation.frontend_process import ControllerJob, _FrontendProcess
from research.validation.maintenance_host import process_identity
from research.validation.owner_launch import SuspendedChild
from research.validation.store import Hold

FIXTURES = Path(__file__).parent / "fixtures"


@unittest.skipUnless(sys.platform == "win32", "Windows nested frontend-family jobs")
class FrontendTests(unittest.TestCase):
    artifact_root = None

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        if self.artifact_root is not None:
            self.addCleanup(self.preserve)

    def preserve(self):
        import shutil

        shutil.copytree(self.root, Path(self.artifact_root) / self._testMethodName)

    @staticmethod
    def alive(row):
        try:
            return process_identity(row["pid"]) == row
        except Hold:
            return False

    def wait_file(self, path):
        end = time.monotonic() + 6
        error = self.root / "controller.error.txt"
        while not path.exists() and not error.exists() and time.monotonic() < end:
            time.sleep(0.01)
        self.assertTrue(
            path.exists(),
            error.read_text()
            if error.exists()
            else "scratch controller did not report",
        )
        return json.loads(path.read_bytes())

    def process(self, source):
        value = _FrontendProcess(sys.executable, ["-I", "-B", "-c", source])
        self.addCleanup(value.retire)
        return value

    def controller(self, mode="normal"):
        job = ControllerJob("Local\\MCLI1Controller-" + uuid4().hex)
        self.addCleanup(job.close)
        child = SuspendedChild(
            [
                "-I",
                "-B",
                str(FIXTURES / "frontend_controller.py"),
                str(self.root),
                mode,
            ],
            job,
        )
        self.addCleanup(child.close)
        child.resume()
        return child, job

    def wait_dead(self, members):
        end = time.monotonic() + 3
        while any(self.alive(row) for row in members) and time.monotonic() < end:
            time.sleep(0.01)
        self.assertFalse(any(self.alive(row) for row in members))

    def test_suspended_gate_failure_never_runs_code_and_family_is_reaped(self):
        marker = self.root / "unexpected"
        process = self.process(
            f"from pathlib import Path;Path({str(marker)!r}).write_text('effect')"
        )
        self.assertFalse(marker.exists())

        def denied(_):
            raise Hold("test:original owner was not ready")

        with self.assertRaisesRegex(Hold, "owner was not ready"):
            process.resume(denied)
        result = process.retire()
        self.assertFalse(marker.exists())
        self.assertEqual(result["job_active_processes"], 0)

    def test_actual_controller_allows_three_member_family_and_separate_bounded_query(
        self,
    ):
        child, _ = self.controller()
        ready = self.wait_file(self.root / "controller.ready.json")
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
        self.assertLessEqual(len(ready["members"]), 6)
        self.assertTrue(ready["query_job_reaped"])
        (self.root / "controller.finish").write_text("finish")
        result = self.wait_file(self.root / "controller.terminal.json")
        self.assertEqual(result["job_active_processes"], 0)
        self.assertFalse(result["native_boot_authorized"])
        self.wait_dead(ready["members"])
        end = time.monotonic() + 2
        while child.poll() is None and time.monotonic() < end:
            time.sleep(0.01)
        self.assertEqual(child.poll(), 0)

    def test_abrupt_controller_exit_reaps_all_frontend_descendants(self):
        _, _job = self.controller("abrupt")
        ready = self.wait_file(self.root / "controller.ready.json")
        self.wait_dead(ready["members"])
        self.assertFalse((self.root / "controller.terminal.json").exists())

    def test_outer_controller_job_termination_reaps_the_entire_family(self):
        _, job = self.controller()
        ready = self.wait_file(self.root / "controller.ready.json")
        job.close()
        self.wait_dead(ready["members"])

    def test_output_flood_is_bounded_and_retirement_cleans_up(self):
        process = self.process("import os,time;os.write(1,b'x'*1000000);time.sleep(8)")
        process.resume(lambda _: None)
        self.assertTrue(process.fault.wait(3))
        result = process.retire()
        self.assertTrue(result["output_fault"])
        self.assertLessEqual(result["stdout_bytes"], 65536)
        self.assertEqual(result["job_active_processes"], 0)

    def test_only_the_retained_root_zero_exit_can_skip_a_final_image_lookup(self):
        import research.validation.frontend_process as module

        process = self.process("pass")
        process.resume(lambda _: None)
        end = time.monotonic() + 3
        while process.poll() is None and time.monotonic() < end:
            time.sleep(0.01)
        self.assertEqual(process.poll(), 0)
        with (
            patch.object(process.job, "pids", return_value=[process.pid]),
            patch.object(
                module, "process_identity", side_effect=Hold("PID image unavailable")
            ),
        ):
            with self.assertRaises(Hold):
                process.members()
            self.assertEqual(process.members(allow_retired=True), [])

    def test_final_root_exit_does_not_hide_unknown_family_members(self):
        import research.validation.frontend_process as module

        process = self.process("pass")
        process.resume(lambda _: None)
        end = time.monotonic() + 3
        while process.poll() is None and time.monotonic() < end:
            time.sleep(0.01)
        self.assertEqual(process.poll(), 0)
        with (
            patch.object(process.job, "pids", return_value=[process.pid, 999999]),
            patch.object(module, "process_identity", side_effect=Hold("unknown image")),
            self.assertRaises(Hold),
        ):
            process.members(allow_retired=True)

    def test_retained_live_root_is_known_but_nonzero_exit_still_holds(self):
        import research.validation.frontend_process as module

        for code in ("import time;time.sleep(8)", "raise SystemExit(7)"):
            process = self.process(code)
            process.resume(lambda _: None)
            if "SystemExit" in code:
                end = time.monotonic() + 3
                while process.poll() is None and time.monotonic() < end:
                    time.sleep(0.01)
                self.assertEqual(process.poll(), 7)
            with (
                patch.object(process.job, "pids", return_value=[process.pid]),
                patch.object(
                    module, "process_identity", side_effect=Hold("unreadable image")
                ),
            ):
                with self.assertRaises(Hold):
                    process.members()
                if "SystemExit" in code:
                    with self.assertRaisesRegex(Hold, "nonzero"):
                        process.members(allow_retired=True)
                else:
                    self.assertEqual(
                        process.members(allow_retired=True), [process.identity]
                    )

    def test_unknown_wait_result_cannot_prove_a_root_exit(self):
        import _winapi

        process = self.process("pass")
        with (
            patch.object(_winapi, "WaitForSingleObject", return_value=0xFFFFFFFF),
            self.assertRaisesRegex(Hold, "wait result is unknown"),
        ):
            process.poll()

    def test_retained_family_handles_prove_natural_exit_without_image_requery(self):
        import research.validation.frontend_process as module

        process = _FrontendProcess(
            sys.executable,
            ["-I", "-B", str(FIXTURES / "frontend_family.py"), str(self.root), "0"],
        )
        self.addCleanup(process.retire)
        process.resume(lambda _: None)
        self.wait_file(self.root / "family-2.json")
        members = process.members()
        self.assertEqual(
            sum(
                Path(row["image"]).resolve() == Path(sys.executable).resolve()
                for row in members
            ),
            3,
        )
        self.assertLessEqual(len(members), 6)
        pins = list(process._pins.values())
        (self.root / "family.finish").write_text("finish")
        end = time.monotonic() + 3
        while process.job.active() and time.monotonic() < end:
            time.sleep(0.01)
        self.assertEqual(process.poll(), 0)
        with (
            patch.object(
                process.job, "pids", return_value=[row["pid"] for row in members]
            ),
            patch.object(
                module, "process_identity", side_effect=Hold("image unavailable")
            ),
        ):
            self.assertEqual(process.members(allow_retired=True), [])
        terminal = process.retire()
        self.assertFalse(terminal["terminated"])
        self.assertEqual(len(terminal["retained_process_exits"]), len(members))
        self.assertTrue(
            all(row["exit_code"] == 0 for row in terminal["retained_process_exits"])
        )
        self.assertTrue(all(pin.handle is None for pin in pins))
        self.assertEqual(process._pins, {})

    def test_unknown_retained_wait_result_holds_normal_finish(self):
        process = self.process("import time;time.sleep(8)")
        pin = process._pins[process.pid]
        with (
            patch.object(pin.api, "WaitForSingleObject", return_value=0xFFFFFFFF),
            self.assertRaisesRegex(Hold, "retained frontend wait result is unknown"),
        ):
            process.members(allow_retired=True)

    def test_resume_is_one_shot_and_delayed_frontend_can_be_retired(self):
        marker = self.root / "late"
        process = self.process(
            f"import time;from pathlib import Path;time.sleep(2);Path({str(marker)!r}).write_text('late')"
        )
        process.resume(lambda _: None)
        with self.assertRaisesRegex(Hold, "resume twice"):
            process.resume(lambda _: None)
        process.retire()
        self.assertFalse(marker.exists())
        self.assertFalse(self.alive(process.identity))

    def test_unexpected_family_image_or_too_many_frontends_is_a_hold(self):
        process = self.process("import time;time.sleep(8)")
        import research.validation.frontend_process as module

        with (
            patch.object(
                module,
                "process_identity",
                return_value={**process.identity, "image": r"C:\unexpected.exe"},
            ),
            self.assertRaisesRegex(Hold, "unpinned helper"),
        ):
            process.members()
        with (
            patch.object(process.job, "pids", return_value=[1, 2, 3, 4]),
            patch.object(
                module,
                "process_identity",
                side_effect=lambda pid: {**process.identity, "pid": pid},
            ),
            self.assertRaisesRegex(Hold, "count exceeds bound"),
        ):
            process.members()

    def test_nonzero_frontend_exit_is_retained_without_claiming_vm_poweroff(self):
        process = self.process("import sys;sys.exit(7)")
        process.resume(lambda _: None)
        end = time.monotonic() + 3
        while process.job.active() and time.monotonic() < end:
            time.sleep(0.01)
        result = process.retire()
        self.assertEqual(result["root_exit"], 7)
        self.assertFalse(result["native_boot_authorized"])
        self.assertIn("not-VM-poweroff-proof", result["status"])


if __name__ == "__main__":
    unittest.main()
