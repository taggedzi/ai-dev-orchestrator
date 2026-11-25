"""Qualification preparation/conformance; native VM/session facts are synthetic."""

import copy
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from research.validation import startup_qualification as qualification
from research.validation.store import Hold
from research.validation.transfer_commands import canonical, digest
from tests import test_boot_preconditions as boot_tests
from tests import test_frontend_start as start_tests
from tests import test_owner_launch as owner_tests
from tests.fixtures.frontend_start_support import bind


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.inputs = {
            "backup": {"path": "synthetic-backup", "sha256": "a" * 64},
            "profile": {"path": "synthetic-profile", "sha256": "b" * 64},
        }
        now, mono = time.time_ns(), time.monotonic_ns()
        self.review = {
            "format": "mcli1-one-guard-startup-review-v1",
            "created_utc_ns": now,
            "policy": dict(qualification.POLICY),
            "sources": dict(qualification.SOURCE_EPOCH),
            "inputs": self.inputs,
            "original_lease": {
                "expires_ns": now + 600 * 10**9,
                "expires_mono_ns": mono + 600 * 10**9,
            },
        }
        self.approval = {
            "format": "mcli1-one-guard-startup-approval-v1",
            "review_sha256": digest(canonical(self.review)),
            "reference": "test:Python-only-surrogates",
            "approved_utc_ns": now,
        }
        self.addCleanup(patch.stopall)
        patch.object(
            qualification,
            "fixed_inputs",
            lambda *, recovery=False, capture_relative=None: copy.deepcopy(self.inputs),
        ).start()

    def checked(self):
        raw = canonical(self.review)
        return qualification.approved_review(raw, digest(raw), canonical(self.approval))

    def test_exact_review_is_required_and_does_not_renew_lease(self):
        before = copy.deepcopy(self.review)
        self.assertEqual(self.checked()[0], before)
        self.assertEqual(self.review, before)
        self.approval["review_sha256"] = "0" * 64
        with self.assertRaises(Hold):
            self.checked()

    def test_recovery_review_binds_its_initial_state_and_context_under_the_same_lease(
        self,
    ):
        self.inputs.update(
            recovery={"path": "synthetic-context", "sha256": "c" * 64},
            preparation={"path": "synthetic-completion", "sha256": "d" * 64},
        )
        self.review.update(
            format=qualification.RECOVERY_REVIEW_FORMAT,
            capture_relative="synthetic-capture",
            policy=qualification.review_policy(True, self.inputs),
        )
        self.approval["review_sha256"] = digest(canonical(self.review))
        lease = copy.deepcopy(self.review["original_lease"])
        self.assertEqual(self.checked()[0]["original_lease"], lease)
        for changed in (
            {"initial_machine_state": "poweroff"},
            {"recovery_context_sha256": "0" * 64},
            {"VM_boots": 2},
        ):
            altered = {**self.review, "policy": {**self.review["policy"], **changed}}
            wire = canonical(altered)
            with self.subTest(changed=changed), self.assertRaises(Hold):
                qualification.approved_review(
                    wire,
                    digest(wire),
                    canonical({**self.approval, "review_sha256": digest(wire)}),
                )

    def test_missing_recovery_capture_never_constructs_owner_or_controller(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(qualification, "new_root", return_value=Path(folder)),
            patch.object(
                qualification,
                "fixed_inputs",
                side_effect=FileNotFoundError("incomplete capture"),
            ),
            patch.object(
                qualification.launch,
                "PendingOwner",
                side_effect=AssertionError("constructed owner"),
            ),
            patch.object(
                qualification.launch,
                "SuspendedChild",
                side_effect=AssertionError("constructed controller"),
            ),
            patch.object(
                qualification.start.frontend,
                "ControllerJob",
                side_effect=AssertionError("created job"),
            ),
            self.assertRaises(FileNotFoundError),
        ):
            qualification.prepare(folder, recovery=True)

    def test_late_or_unanswered_approval_never_admits_activation(self):
        self.review["original_lease"]["expires_mono_ns"] = (
            time.monotonic_ns() + 59 * 10**9
        )
        self.approval["review_sha256"] = digest(canonical(self.review))
        with self.assertRaises(Hold):
            self.checked()
        self.approval["reference"] = None
        with self.assertRaises(Hold):
            self.checked()

    def test_source_input_or_scope_changes_are_not_a_new_approval(self):
        for field, value in (
            ("sources", {}),
            ("inputs", {}),
            ("policy", {**qualification.POLICY, "VM_boots": 2}),
        ):
            changed = {**self.review, field: value}
            raw = canonical(changed)
            approval = {**self.approval, "review_sha256": digest(raw)}
            with self.subTest(field=field), self.assertRaises(Hold):
                qualification.approved_review(raw, digest(raw), canonical(approval))

    def test_approval_clock_or_extra_fields_do_not_admit(self):
        for change in (
            {"approved_utc_ns": True},
            {"approved_utc_ns": time.time_ns() + 60 * 10**9},
            {"extra": "unreviewed"},
        ):
            with self.subTest(change=change), self.assertRaises(Hold):
                qualification.approved_review(
                    canonical(self.review),
                    digest(canonical(self.review)),
                    canonical({**self.approval, **change}),
                )

    def test_readonly_preflight_cli_has_no_owner_or_controller_constructor(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch.object(
                sys,
                "argv",
                ["qualification", "preflight", "--output", folder],
            ),
            patch.object(qualification, "new_root", return_value=Path(folder)),
            patch.object(qualification, "preactivation_probe") as probe,
            patch.object(
                qualification.launch,
                "PendingOwner",
                side_effect=AssertionError("read-only CLI constructed owner"),
            ),
            patch.object(
                qualification.launch,
                "SuspendedChild",
                side_effect=AssertionError("read-only CLI constructed controller"),
            ),
            patch.object(
                qualification.start.frontend,
                "ControllerJob",
                side_effect=AssertionError("read-only CLI created controller job"),
            ),
        ):
            qualification.main()
            probe.assert_called_once()
            record = json.loads((Path(folder) / "preflight.inputs.json").read_bytes())
            self.assertEqual(record["VM_boots"], 0)
            self.assertEqual(record["native_stop_commands"], 0)

    def test_early_abort_closes_both_suspended_processes_without_activation(self):
        with tempfile.TemporaryDirectory() as folder:
            root, calls = Path(folder), []
            (root / "abort").write_text("test-only cancellation")

            class Job:
                def __init__(self, *_args):
                    pass

                def close(self):
                    calls.append("job-close")

            class Child:
                pid = 123

                def __init__(self, *_args):
                    pass

                def close(self):
                    calls.append("controller-close")

                def resume(self, *_args):
                    raise AssertionError("unapproved controller resumed")

            class Pending:
                def __init__(self, directory, *_args):
                    self.root = directory
                    directory.mkdir()
                    self.lease = self_review["original_lease"]
                    self.proposal = {"approval": {"native_stop": None}}
                    self.controller = self.bootstrap = self.owner = {
                        "pid": 123,
                        "created_filetime": 1,
                        "image": "synthetic-python",
                    }

                def close(self):
                    calls.append("owner-close")

            self_review = self.review
            with (
                patch.object(qualification, "new_root", return_value=root),
                patch.object(qualification.start.frontend, "ControllerJob", Job),
                patch.object(qualification.launch, "SuspendedChild", Child),
                patch.object(qualification.launch, "PendingOwner", Pending),
                patch.object(
                    qualification.start.host,
                    "process_identity",
                    return_value={"pid": 123},
                ),
            ):
                result = qualification.prepare("unused-synthetic-root")
            self.assertEqual(result["VM_boots"], 0)
            self.assertEqual(calls, ["job-close", "controller-close", "owner-close"])
            self.assertFalse(
                json.loads((root / "review.json").read_bytes())[
                    "native_boot_authorized"
                ]
            )


class PreactivationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.addCleanup(patch.stopall)
        self.calls, self.fail_role, self.locked_role = [], None, None
        slot = qualification.start.backup.SLOTS["guard"]
        b = qualification.start.boot.draft("guard")
        b["target"].update(
            vm_uuid=slot["vm_uuid"],
            disk_uuid=slot["disk_uuid"],
            dmi_uuid=slot["vm_uuid"],
        )
        b["run_nonce"] = "a" * 32
        b["disk_evidence"]["pre_boot_disk_sha256"] = "a" * 64
        _grant, receipts = bind(b, boot_tests.snapshot(b))
        self.profile = receipts[3]
        config = self.root / "configuration"
        config.write_bytes(b"synthetic reviewed configuration")
        self.profile["configuration"] = qualification.start.backup.file_state(config)
        paths = {"configuration": config, "nvram": self.root / "nvram"}
        patch.object(
            qualification.start.backup, "source_paths", return_value=paths
        ).start()
        patch.object(qualification.start, "image_environment", lambda _: None).start()
        self.inputs = {}
        for name, value in (("backup", receipts[0]), ("profile", self.profile)):
            path = self.root / (name + ".json")
            path.write_bytes(canonical(value))
            self.inputs[name] = {"path": str(path), "sha256": digest(canonical(value))}
        now, mono = time.time_ns(), time.monotonic_ns()
        self.review = {
            "format": "mcli1-one-guard-startup-review-v1",
            "created_utc_ns": now,
            "policy": dict(qualification.POLICY),
            "sources": dict(qualification.SOURCE_EPOCH),
            "inputs": self.inputs,
            "original_lease": {
                "expires_ns": now + 600 * 10**9,
                "expires_mono_ns": mono + 600 * 10**9,
            },
            "native_argv": [
                str(qualification.start.frontend.HEADLESS),
                "--startvm",
                qualification.target_uuid(),
                "--vrde",
                "off",
            ],
            "native_executable_sha256": qualification.start.frontend.HEADLESS_SHA256,
            "environment_sha256": "e" * 64,
        }
        self.raw = canonical(self.review)
        self.sha = digest(self.raw)
        (self.root / "review.json").write_bytes(self.raw)
        self.approval = canonical(
            {
                "format": "mcli1-one-guard-startup-approval-v1",
                "review_sha256": self.sha,
                "reference": "test:surrogate-only",
                "approved_utc_ns": now,
            }
        )
        patch.object(qualification, "fixed_inputs", return_value=self.inputs).start()
        case = self

        class Observer:
            def __init__(self, role):
                self.role, self.last = role, None

            def __call__(self):
                case.calls.append(self.role)
                slot = qualification.start.backup.SLOTS[self.role]
                b = {
                    "role": self.role,
                    "target": {
                        "vm_uuid": slot["vm_uuid"],
                        "disk_uuid": slot["disk_uuid"],
                        "dmi_uuid": slot["vm_uuid"],
                    },
                }
                frame = boot_tests.snapshot(b)
                frame["session"] = {
                    "vm_uuid": slot["vm_uuid"],
                    "state_before": "Unlocked",
                    "state_after": "Unlocked",
                    "pid": 0,
                }
                self.last = {k: frame[k] for k in ("machine", "medium")}
                if case.fail_role == self.role:
                    raise Hold("injected bounded query timeout")
                if case.locked_role == self.role:
                    frame["session"].update(
                        state_before="Locked", state_after="Locked", pid=123
                    )
                return frame

        class Pending:
            def __init__(self):
                self.proposal = {"approval": {"native_stop": None}}

            def seal(self, *_args):
                case.assertTrue((case.root / "preactivation.receipt.json").exists())
                case.assertTrue((case.root / "owner.activation.intent.json").exists())
                case.calls.append("seal")

            def ready(self):
                case.calls.append("ready")

        self.pending = Pending()
        patch.object(qualification.session, "NativeObserver", Observer).start()

    def activate(self):
        return qualification.activate_reviewed_owner(
            self.pending, self.root, self.raw, self.sha, self.approval
        )

    def test_both_readonly_proofs_precede_owner_activation(self):
        self.activate()
        self.assertEqual(self.calls, ["guard", "executor", "seal", "ready"])
        receipt = json.loads((self.root / "preactivation.receipt.json").read_bytes())
        self.assertFalse(receipt["owner_activated"])
        self.assertEqual(receipt["native_stop_commands"], 0)

    def test_guard_timeout_leaves_owner_and_stop_path_unarmed(self):
        self.fail_role = "guard"
        with self.assertRaises(Hold):
            self.activate()
        self.assertEqual(self.calls, ["guard"])
        self.assertFalse((self.root / "owner.activation.intent.json").exists())
        self.assertFalse((self.root / "preactivation.receipt.json").exists())
        self.assertTrue(
            (self.root / "preactivation-observations/guard/machine.stdout").exists()
        )

    def test_source_timeout_after_guard_proof_still_cannot_activate_owner(self):
        self.fail_role = "executor"
        with self.assertRaises(Hold):
            self.activate()
        self.assertEqual(self.calls, ["guard", "executor"])
        self.assertFalse((self.root / "owner.activation.intent.json").exists())

    def test_locked_source_or_guard_session_is_rejected(self):
        self.locked_role = "guard"
        with self.assertRaises(Hold):
            self.activate()
        self.assertNotIn("seal", self.calls)

    def test_current_configuration_drift_is_seen_before_native_queries(self):
        (self.root / "configuration").write_bytes(b"changed")
        with self.assertRaises(Hold):
            self.activate()
        self.assertEqual(self.calls, [])

    def test_image_environment_drift_is_seen_before_native_queries(self):
        with (
            patch.object(
                qualification.start,
                "image_environment",
                side_effect=Hold("changed image/environment"),
            ),
            self.assertRaises(Hold),
        ):
            self.activate()
        self.assertEqual(self.calls, [])

    def test_changed_sources_after_probe_cannot_reach_activation(self):
        with (
            patch.object(
                qualification,
                "current_sources",
                side_effect=[dict(qualification.SOURCE_EPOCH), {}],
            ),
            self.assertRaises(Hold),
        ):
            self.activate()
        self.assertEqual(self.calls, ["guard", "executor"])
        self.assertFalse((self.root / "owner.activation.intent.json").exists())


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "owner"
        self.root.mkdir()
        self.calls, self.fail = [], False
        self.transitions = 0
        self.probe_waits = 0
        self.read_calls = []
        self.startup_contexts = []
        self.payload = {
            "format": "mcli1-qualification-controller-input-v1",
            "review_sha256": "a" * 64,
            "sources": dict(qualification.SOURCE_EPOCH),
            "grant": {},
            "receipts": [{}] * 4,
        }
        self.raw = canonical(self.payload)
        (self.root / "controller.input.json").write_bytes(self.raw)
        (self.root.parent / "review.json").write_bytes(b"{}")
        (self.root.parent / "approval.json").write_bytes(b"{}")
        self.addCleanup(patch.stopall)
        patch.object(
            qualification,
            "approved_review",
            return_value=({"controller": {"pid": 123}}, {}),
        ).start()
        patch.object(
            qualification.start.host, "process_identity", return_value={"pid": 123}
        ).start()
        case = self

        class Observer:
            last = None

            def __init__(self, _role):
                pass

            def __call__(self):
                case.read_calls.append("CLI")
                self.last = {"session_raw": b"synthetic raw session"}
                if case.fail:
                    raise Hold("injected native session inconsistency")
                return {
                    "observed_mono_ns": time.monotonic_ns(),
                    "machine": b"synthetic machine",
                    "medium": b"synthetic disk",
                    "session": {"pid": 5},
                }

            def startup_observation(self, *, recovery=None):
                case.startup_contexts.append(recovery)
                frame = self()
                if case.transitions:
                    case.transitions -= 1
                    frame["startup_transition"] = {"format": "synthetic wait"}
                return frame

            def startup_session(self):
                case.read_calls.append("COM")
                self.last = {"session_raw": b"synthetic COM-only session"}
                return {"session_probe": True}

        class Adapter:
            terminal = None
            joined = None
            family = SimpleNamespace(members=lambda: [{"pid": 5}])

            def __init__(self, *_args):
                pass

            def start(self, *_args):
                case.calls.append("start")

            def observe(self, frame):
                if "startup_transition" in frame:
                    case.calls.append("wait")
                    return {"status": "awaiting-session-identity"}
                self.joined = {"pid": 5}
                case.calls.append("observe")
                return {"status": "runtime-session-bound-not-guest-ready"}

            def observe_startup_session(self, frame):
                case.calls.append("session-probe")
                ready = case.probe_waits == 0
                case.probe_waits = max(0, case.probe_waits - 1)
                return {"profile_observation_allowed": ready, "guest_ready": False}

            def request_owner_stop(self):
                case.calls.append("original-owner-stop-request")
                self.terminal = {"status": "synthetic retirement"}

            def close(self):
                case.calls.append("close")
                return self.terminal or {"status": "synthetic held retirement"}

        patch.object(qualification.session, "NativeObserver", Observer).start()
        patch.object(qualification.start, "_PreparedStart", Adapter).start()

    def test_one_start_two_observations_and_one_original_stop_request(self):
        qualification.controller_main(self.root, digest(self.raw))
        self.assertEqual(
            self.calls,
            [
                "start",
                "session-probe",
                "observe",
                "observe",
                "original-owner-stop-request",
                "close",
            ],
        )
        outcome = json.loads((self.root / "controller.outcome.json").read_bytes())
        self.assertFalse(outcome["guest_ready"])
        self.assertFalse(outcome["native_settlement_qualified"])

    def test_conflicting_observation_is_retained_and_does_not_retry(self):
        self.fail = True
        qualification.controller_main(self.root, digest(self.raw))
        self.assertEqual(self.calls, ["start", "session-probe", "close"])
        self.assertTrue(
            (self.root / "runtime-observations/2/session_raw.stdout").exists()
        )
        self.assertEqual(
            json.loads((self.root / "controller.outcome.json").read_bytes())["status"],
            "held-controller-qualification",
        )

    def test_only_exact_loss_review_reaches_fault_after_two_samples(self):
        with (
            patch.object(
                qualification,
                "approved_review",
                return_value=(
                    {
                        "controller": {"pid": 123},
                        "format": qualification.LOSS_REVIEW_FORMAT,
                    },
                    {},
                ),
            ),
            patch.object(
                qualification,
                "_controller_loss_exit",
                side_effect=SystemExit(qualification.LOSS_EXIT),
            ) as fault,
            self.assertRaises(SystemExit),
        ):
            qualification.controller_main(self.root, digest(self.raw))
        fault.assert_called_once()
        self.assertEqual(len(fault.call_args.args[3]), 2)
        self.assertEqual(self.calls.count("observe"), 2)
        self.assertNotIn("original-owner-stop-request", self.calls)

    def test_failed_observation_never_reaches_reviewed_loss_barrier(self):
        self.fail = True
        with (
            patch.object(
                qualification,
                "approved_review",
                return_value=(
                    {
                        "controller": {"pid": 123},
                        "format": qualification.LOSS_REVIEW_FORMAT,
                    },
                    {},
                ),
            ),
            patch.object(qualification, "_controller_loss_exit") as fault,
        ):
            qualification.controller_main(self.root, digest(self.raw))
        fault.assert_not_called()
        self.assertNotIn("original-owner-stop-request", self.calls)

    def test_forward_wait_does_not_count_as_a_running_sample(self):
        self.transitions = 1
        qualification.controller_main(self.root, digest(self.raw))
        self.assertEqual(
            self.calls,
            [
                "start",
                "session-probe",
                "wait",
                "session-probe",
                "observe",
                "observe",
                "original-owner-stop-request",
                "close",
            ],
        )
        outcome = json.loads((self.root / "controller.outcome.json").read_bytes())
        self.assertEqual(len(outcome["samples"]), 2)

    def test_controller_forwards_recovery_only_until_the_session_is_joined(self):
        from tests import test_recovery_records as recovery_tests

        context = recovery_tests.context()
        self.payload["grant"]["recovery"] = context
        self.raw = canonical(self.payload)
        (self.root / "controller.input.json").write_bytes(self.raw)
        qualification.controller_main(self.root, digest(self.raw))
        self.assertEqual(self.startup_contexts, [context])
        self.assertEqual(
            self.calls,
            [
                "start",
                "session-probe",
                "observe",
                "observe",
                "original-owner-stop-request",
                "close",
            ],
        )

    def test_cli_profile_reads_wait_for_the_session_probe_gate(self):
        self.probe_waits = 2
        qualification.controller_main(self.root, digest(self.raw))
        self.assertEqual(self.read_calls, ["COM", "COM", "COM", "CLI", "CLI"])
        outcome = json.loads((self.root / "controller.outcome.json").read_bytes())
        self.assertEqual(len(outcome["samples"]), 2)

    def test_unsettled_session_never_calls_cli_or_extends_the_sample_window(self):
        self.probe_waits = 999
        with patch.dict(qualification.POLICY, {"runtime_limit_ns": 50 * 10**6}):
            qualification.controller_main(self.root, digest(self.raw))
        self.assertEqual(self.read_calls, ["COM"])
        outcome = json.loads((self.root / "controller.outcome.json").read_bytes())
        self.assertEqual(outcome["samples"], [])
        self.assertIn("sample window ended", outcome["failure"])
        self.assertNotIn("original-owner-stop-request", self.calls)

    def test_changed_activation_digest_never_constructs_an_adapter(self):
        with self.assertRaises(Hold):
            qualification.controller_main(self.root, "0" * 64)
        self.assertEqual(self.calls, [])

    def test_held_controller_outcome_does_not_require_a_normal_stop_intent(self):
        with self.assertRaisesRegex(Hold, "controller qualification held"):
            qualification.stop_proof(
                self.root, {}, {"failure": "injected startup failure"}
            )
        self.assertFalse((self.root / "frontend.owner-stop.intent.json").exists())

    def test_bootstrap_observes_owner_exit_without_claiming_stop_acceptance(self):
        polls = iter((None, 1))
        pending = SimpleNamespace(
            sealed=True,
            child=SimpleNamespace(poll=lambda: next(polls)),
            root=self.root,
            owner={"pid": 123, "created_filetime": 1, "image": "synthetic"},
        )
        qualification.observe_owner_exit(self.root.parent, pending)
        record = json.loads(
            (self.root.parent / "bootstrap.owner-observation.json").read_bytes()
        )
        self.assertEqual(record["exit"], 1)
        self.assertFalse(record["original_stop_accepted"])

    def test_unarmed_owner_is_not_waited_on_or_resumed(self):
        pending = SimpleNamespace(
            sealed=False,
            child=SimpleNamespace(poll=lambda: self.fail("unarmed child was polled")),
        )
        qualification.observe_owner_exit(self.root, pending)
        self.assertFalse((self.root / "bootstrap.owner-observation.json").exists())


@unittest.skipUnless(sys.platform == "win32", "Windows PID creation/retirement proof")
class RetirementTests(unittest.TestCase):
    def test_live_exact_creation_is_not_dead_and_different_creation_is_distinct(self):
        identity = qualification.start.host.process_identity(os.getpid())
        self.assertFalse(qualification.process_retired(identity))
        self.assertTrue(
            qualification.process_retired(
                {**identity, "created_filetime": identity["created_filetime"] - 1}
            )
        )

    def test_reaped_python_query_is_proven_retired(self):
        identity = []
        qualification.session.native._run(
            Path(sys.executable),
            ["-I", "-B", "-c", "print('retirement-surrogate')"],
            time.time_ns() + 4 * 10**9,
            time.monotonic_ns() + 4 * 10**9,
            before_resume=lambda pid: identity.append(
                qualification.start.host.process_identity(pid)
            ),
        )
        self.assertTrue(qualification.process_retired(identity[0]))


@unittest.skipUnless(
    sys.platform == "win32", "Windows actual suspended original-owner job"
)
class UnarmedOwnerTests(owner_tests.NativeOwnerFixture, unittest.TestCase):
    artifact_root = None

    def test_preflight_hold_never_resumes_real_suspended_owner(self):
        pending = self.pending(seconds=40)
        raw = canonical({"test_only": "preactivation failure"})
        (self.base / "review.json").write_bytes(raw)
        with (
            patch.object(qualification, "approved_review", return_value=({}, {})),
            patch.object(
                qualification,
                "preactivation_probe",
                side_effect=Hold("injected read-only timeout"),
            ),
            self.assertRaises(Hold),
        ):
            qualification.activate_reviewed_owner(
                pending, self.base, raw, digest(raw), b"{}"
            )
        self.assertFalse(pending.sealed)
        self.assertIsNotNone(pending.child.primary)
        self.assertFalse((pending.root / "owner.sealed.json").exists())
        self.assertFalse((pending.root / "owner.ready.json").exists())
        self.assertFalse((pending.root / "surrogate.calls.jsonl").exists())
        self.assertFalse((self.base / "owner.activation.intent.json").exists())


@unittest.skipUnless(
    sys.platform == "win32", "Windows actual original-owner surrogate proof"
)
class StopProofTests(owner_tests.NativeOwnerFixture, unittest.TestCase):
    """Actual owner/process proof with explicitly synthetic final VM observations."""

    artifact_root = None
    setUp = start_tests.NativeStartTests.setUp
    prepared = start_tests.NativeStartTests.prepared
    wait_file = start_tests.NativeStartTests.wait_file
    verify_stop = start_tests.NativeStartTests.verify_stop

    def _proof_for_state(self, state, *, failed_frontend=False):
        root = self.prepared(mode="graceful")
        ready = self.wait_file("controller.ready.json")
        result = self.wait_file("controller.terminal.json")
        self.verify_stop()
        packet = json.loads((root / "owner.sealed.json").read_bytes())
        slot = qualification.start.backup.SLOTS["guard"]
        grant = {
            "role": "guard",
            "target": {
                "vm_uuid": slot["vm_uuid"],
                "dmi_uuid": slot["vm_uuid"],
                "disk_uuid": slot["disk_uuid"],
            },
        }

        class Observer:
            def __init__(self, _role):
                self.last = None

            def __call__(self):
                frame = boot_tests.snapshot(grant)
                frame["machine"] = frame["machine"].replace(
                    b'"poweroff"', json.dumps(state).encode()
                )
                frame["session"] = {
                    "vm_uuid": slot["vm_uuid"],
                    "state_before": "Unlocked",
                    "state_after": "Unlocked",
                    "pid": 0,
                }
                self.last = {k: frame[k] for k in ("machine", "medium")}
                return frame

        outcome = {
            "failure": None,
            "retirement": result,
            "samples": [{"members": ready["members"]}] * 2,
        }
        if failed_frontend:
            outcome["retirement"]["cleanup"]["retained_process_exits"][0][
                "exit_code"
            ] = 7
            outcome["retirement"]["cleanup"]["retained_process_exits"][0]["image"] = (
                str(qualification.start.frontend.HEADLESS)
            )
        with (
            patch.object(
                qualification.owner.stop, "STOPS_ROOT", root / "surrogate-stops"
            ),
            patch.object(qualification.session, "NativeObserver", Observer),
        ):
            proof = qualification.stop_proof(root, packet, outcome)
        return proof

    def test_independent_proof_checks_real_original_ledger_and_retirement(self):
        proof = self._proof_for_state("poweroff")
        self.assertFalse(proof["guest_ready"])
        self.assertFalse(proof["late_detached_start_failure_cases_qualified"])
        self.assertLess(proof["stop_elapsed_ns"], 10 * 10**9)

    def test_aborted_is_never_independent_poweroff_acceptance(self):
        with self.assertRaisesRegex(Hold, "not independently powered off"):
            self._proof_for_state("aborted")

    def test_final_nonzero_retained_frontend_exit_cannot_be_accepted(self):
        with self.assertRaisesRegex(Hold, "retained family exit proof"):
            self._proof_for_state("poweroff", failed_frontend=True)


if __name__ == "__main__":
    unittest.main()
