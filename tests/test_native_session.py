"""Fixed read-only observer conformance; no COM or VirtualBox process in tests."""

import copy
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from research.validation import native_session as session
from research.validation.store import Hold
from research.validation.transfer_commands import canonical
from tests import test_boot_preconditions as inputs
from tests import test_recovery_records as recovery_tests


def sample(role="guard", state="poweroff", pid=0):
    slot = session.backup.SLOTS[role]
    return {
        "format": "mcli1-native-session-read-v1",
        "version": session.VERSION,
        "revision": session.REVISION,
        "vm_uuid": slot["vm_uuid"],
        "state_before": 1 if not pid else 2,
        "state_after": 1 if not pid else 2,
        "machine_before": session.MACHINE_STATES[state],
        "machine_after": session.MACHINE_STATES[state],
        "pid": pid,
    }


class ObserverTests(unittest.TestCase):
    def setUp(self):
        self.slot = session.backup.SLOTS["guard"]
        self.grant = {
            "role": "guard",
            "target": {
                "vm_uuid": self.slot["vm_uuid"],
                "disk_uuid": self.slot["disk_uuid"],
                "dmi_uuid": self.slot["vm_uuid"],
            },
        }
        self.frame = inputs.snapshot(self.grant)
        self.session = sample()
        self.calls = []
        self.result_changes = {}
        self.observer = session.NativeObserver(
            "guard", runner=self.native_run, queries=self.query
        )
        self.addCleanup(patch.stopall)
        self.pins_patch = patch.object(self.observer, "pins", lambda: None)
        self.pins_patch.start()

    def result(self, raw):
        return {
            "stdout": raw,
            "stderr": b"",
            "exit": 0,
            "pid": 11,
            "started_mono_ns": time.monotonic_ns(),
            "finished_mono_ns": time.monotonic_ns(),
            "job_active_processes": 0,
            **self.result_changes,
        }

    def query(self, kind, target, wall, mono):
        self.calls.append((kind, target, wall, mono))
        return self.result(self.frame["machine" if kind == "machine" else "medium"])

    def native_run(self, exe, args, wall, mono, before_resume):
        self.calls.append(("session", exe, wall, mono, args))
        before_resume(123)
        return self.result(canonical(self.session))

    def test_fixed_queries_share_one_deadline_and_use_oldest_timestamp(self):
        before = time.monotonic_ns()
        frame = self.observer()
        self.assertEqual(
            [c[0] for c in self.calls], ["machine", "disk", "session", "machine"]
        )
        self.assertEqual(len({(c[2], c[3]) for c in self.calls}), 1)
        self.assertLessEqual(self.calls[0][3] - before, 4 * 10**9 + 10**6)
        self.assertLessEqual(before, frame["observed_mono_ns"])
        self.assertLessEqual(
            frame["observed_mono_ns"], self.observer.last["finished_mono_ns"]
        )
        self.assertEqual(
            frame["session"],
            {
                "vm_uuid": self.slot["vm_uuid"],
                "state_before": "Unlocked",
                "state_after": "Unlocked",
                "pid": 0,
            },
        )
        self.assertEqual(
            self.calls[2][4],
            [
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                session.script("guard"),
            ],
        )

    def test_locked_running_session_requires_consistent_positive_pid(self):
        self.frame["machine"] = self.frame["machine"].replace(
            b'"poweroff"', b'"running"'
        )
        self.session = sample(state="running", pid=123)
        self.assertEqual(self.observer()["session"]["pid"], 123)

    def test_startup_session_probe_never_calls_cli_or_claims_profile(self):
        self.observer.queries = lambda *_args: self.fail("CLI acquired a startup lock")
        before = time.monotonic_ns()
        probe = self.observer.startup_session()
        self.assertEqual([c[0] for c in self.calls], ["session"])
        self.assertEqual(
            set(probe),
            {"format", "observed_mono_ns", "finished_mono_ns", "session_raw"},
        )
        self.assertEqual(probe["session_raw"], canonical(self.session))
        self.assertLessEqual(before, probe["observed_mono_ns"])
        self.assertLessEqual(probe["observed_mono_ns"], probe["finished_mono_ns"])
        self.assertLessEqual(self.calls[0][3] - before, 4 * 10**9 + 10**6)
        with tempfile.TemporaryDirectory() as folder:
            session.retain(Path(folder), self.observer)
            self.assertEqual(
                (Path(folder) / "session_raw.stdout").read_bytes(),
                canonical(self.session),
            )

    def test_startup_session_probe_preserves_failure_and_process_bounds(self):
        for change in (
            {"exit": 1},
            {"stderr": b"uncertain"},
            {"job_active_processes": 1},
            {"stdout": b"x" * 65537},
        ):
            self.result_changes = change
            with self.subTest(change=change), self.assertRaises(Hold):
                self.observer.startup_session()
        self.assertTrue(all(call[0] == "session" for call in self.calls))

    def test_wrong_target_version_types_or_unstable_state_are_rejected(self):
        cases = (
            {"vm_uuid": session.backup.SLOTS["executor"]["vm_uuid"]},
            {"revision": True},
            {"version": "7.2.23"},
            {"state_after": 2},
            {"machine_after": 6},
            {"pid": -1},
            {"pid": True},
            {"state_before": 2, "state_after": 2},
            {"pid": 123},
        )
        for change in cases:
            with self.subTest(change=change), self.assertRaises(Hold):
                session.session_record(canonical({**sample(), **change}), "guard")

    def test_native_failure_stderr_unreaped_or_excess_output_holds(self):
        for change in (
            {"exit": 1},
            {"stderr": b"failure"},
            {"job_active_processes": 1},
            {"stdout": b"x" * 65537},
        ):
            self.result_changes = change
            with self.subTest(change=list(change)), self.assertRaises(Hold):
                self.observer()

    def test_machine_state_mismatch_and_mid_observation_drift_hold(self):
        self.session = sample(state="running", pid=123)
        with self.assertRaises(Hold):
            self.observer()
        self.session = sample()
        original = self.query

        def drift(kind, *args):
            if len(self.calls) == 3:
                self.frame["machine"] = self.frame["machine"].replace(
                    b'"poweroff"', b'"running"'
                )
            return original(kind, *args)

        self.calls.clear()
        self.observer.queries = drift
        with self.assertRaises(Hold):
            self.observer()

    def test_timeout_has_no_retry_and_keeps_prior_raw_results(self):
        def fail(*_args, **_kwargs):
            raise Hold("injected bounded COM timeout")

        self.observer.runner = fail
        with self.assertRaises(Hold):
            self.observer()
        self.assertEqual([c[0] for c in self.calls], ["machine", "disk"])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            session.retain(root, self.observer)
            self.assertEqual(
                (root / "machine_first.stdout").read_bytes(), self.frame["machine"]
            )

    def test_forward_machine_and_session_reads_produce_only_a_wait_marker(self):
        self.session.update(
            state_before=3, state_after=2, machine_before=11, machine_after=6
        )
        original = self.query

        def progress(kind, *args):
            if len(self.calls) == 3:
                self.frame["machine"] = self.frame["machine"].replace(
                    b'"poweroff"', b'"running"'
                )
            return original(kind, *args)

        self.observer.queries = progress
        frame = self.observer.startup_observation()
        self.assertEqual(
            frame["startup_transition"]["machine_states"],
            ["poweroff", "starting", "running", "running"],
        )
        self.assertEqual(frame["session"]["pid"], 0)

    def test_stable_spawning_can_wait_but_default_observer_stays_strict(self):
        self.session.update(state_before=3, state_after=3)
        self.assertIn("startup_transition", self.observer.startup_observation())
        self.session["state_after"] = 2
        with self.assertRaises(Hold):
            self.observer()

    def test_spawning_wait_accepts_installed_cli_display_and_client_diagnostics(self):
        self.session.update(state_before=3, state_after=3)
        original = self.query

        def runtime(kind, *args):
            if len(self.calls) == 3:
                self.frame["machine"] += (
                    b'SessionName="headless"\nVideoMode="0,0,0"@0,0 1\nVRDEActiveConnection="off"\nVRDEClients==0\n'
                )
            return original(kind, *args)

        self.observer.queries = runtime
        frame = self.observer.startup_observation()
        self.assertIn("startup_transition", frame)
        self.assertEqual(frame["session"]["pid"], 0)
        self.assertEqual(frame["session"]["state_before"], "Spawning")

    def test_aborted_is_observable_data_but_not_ordinary_startup_admission(self):
        self.frame["machine"] = self.frame["machine"].replace(
            b'"poweroff"', b'"aborted"'
        )
        self.session = sample(state="aborted")
        observed = self.observer()
        self.assertEqual(
            session.host.machine_fields(observed["machine"])["VMState"], "aborted"
        )
        with self.assertRaises(Hold):
            self.observer.startup_observation()
        self.session.update(state_before=3, state_after=3)
        frame = self.observer.startup_observation(recovery=recovery_tests.context())
        self.assertEqual(frame["startup_transition"]["machine_states"], ["aborted"] * 4)

    def test_recovery_progress_has_one_explicit_initial_state_and_no_backward_edge(
        self,
    ):
        context = recovery_tests.context()
        self.assertEqual(
            session.startup_progress(
                ["aborted", "starting", "running", "running"],
                "Spawning",
                "Locked",
                recovery=context,
            ),
            ((0, 1), (2, 2)),
        )
        for states in (
            ["poweroff"] * 4,
            ["running", "aborted", "aborted", "aborted"],
            ["aborted", "saved", "starting", "running"],
        ):
            with self.subTest(states=states), self.assertRaises(Hold):
                session.startup_progress(states, "Spawning", "Locked", recovery=context)
        self.observer.role = "executor"
        self.calls.clear()
        with self.assertRaises(Hold):
            self.observer.startup_observation(recovery=context)
        self.assertEqual(self.calls, [])

    def test_startup_still_rejects_backward_unknown_profile_and_pid_drift(self):
        for change in (
            {"state_before": 3, "state_after": 1},
            {"state_before": 4, "state_after": 4},
            {"machine_before": 6, "machine_after": 11},
            {"machine_after": 999},
            {"state_before": 3, "state_after": 2, "pid": 123},
            {"version": "7.2.23"},
        ):
            self.session = {**sample(), **change}
            with self.subTest(change=change), self.assertRaises(Hold):
                self.observer.startup_observation()
        self.session = sample()
        original = self.query

        def drift(kind, *args):
            if len(self.calls) == 3:
                self.frame["machine"] = self.frame["machine"].replace(
                    b'"memory"="1024"', b'"memory"="2048"'
                )
            return original(kind, *args)

        self.calls.clear()
        self.observer.queries = drift
        with self.assertRaises(Hold):
            self.observer.startup_observation()

    def test_script_reads_session_pid_only_under_locked_state_and_has_no_mutator(self):
        source = session.script("guard")
        self.assertIn("if($before -eq 2)", source)
        self.assertIn(self.slot["vm_uuid"], source)
        for method in (
            "LaunchVMProcess",
            "LockMachine",
            "PowerUp",
            "PowerDown",
            "SaveSettings",
            "CreateMachine",
        ):
            self.assertNotIn(method.lower(), source.lower())
        with self.assertRaises(Hold):
            session.script("guard';anything")

    def test_changed_source_binary_or_configuration_refuses_before_native_calls(self):
        self.pins_patch.stop()
        with (
            patch.dict(session.os.environ, {"VBOX_USER_HOME": "unreviewed"}),
            self.assertRaises(Hold),
        ):
            self.observer()
        self.assertEqual(self.calls, [])

    def test_static_source_and_target_inputs_are_not_mutated_by_capture(self):
        before = copy.deepcopy(session.SOURCE_EPOCH)
        self.observer()
        self.assertEqual(before, session.SOURCE_EPOCH)


if __name__ == "__main__":
    unittest.main()
