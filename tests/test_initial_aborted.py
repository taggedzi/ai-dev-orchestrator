"""Recovery capture uses real scratch copies with synthetic VM/process facts."""

import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from research.validation import initial_aborted as recovery
from research.validation import recovery_records as model
from research.validation.fixture import canonical
from research.validation.store import Hold
from research.validation.transfer_commands import digest
from tests import test_boot_preconditions as boot_tests
from tests import test_native_session as session_tests
from tests import test_recovery_records as records_tests


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.addCleanup(patch.stopall)
        patch.object(recovery, "ROOT", self.root).start()
        patch.object(recovery.backup, "ROOT", self.root).start()
        patch.object(recovery.host, "WORKSPACE", self.root).start()

        def new_root(path):
            path.mkdir(parents=True, exist_ok=False)
            return path

        patch.object(recovery, "new_root", new_root).start()
        self.locker = lambda path: path.open("rb")
        patch.object(recovery.backup, "locked_source", self.locker).start()
        guard_cfg = b'<VirtualBox xmlns="http://www.virtualbox.org/"><Machine aborted="true"/></VirtualBox>'
        self.payloads = {
            "guard": {
                "disk": b"synthetic-guard-disk" * 1000,
                "configuration": guard_cfg,
            },
            "executor": {
                "disk": b"synthetic-source-disk" * 1000,
                "configuration": b"source-configuration",
                "nvram": b"source-firmware",
            },
        }
        facts = {}
        for role, payloads in self.payloads.items():
            facts[role] = {}
            paths = recovery.backup.source_paths(role)
            for name in ("disk", "configuration", "nvram"):
                path = paths[name]
                path.parent.mkdir(parents=True, exist_ok=True)
                if name in payloads:
                    path.write_bytes(payloads[name])
                    facts[role][name] = {
                        "state": "file",
                        "bytes": len(payloads[name]),
                        "sha256": digest(payloads[name]),
                    }
                else:
                    facts[role][name] = {"state": "absent"}
        patch.object(model, "FILES", facts["guard"]).start()
        patch.object(recovery, "EXECUTOR_FILES", facts["executor"]).start()
        self.prior = records_tests.context()["prior"]
        self.intervening = records_tests.intervening()
        self.latest = records_tests.latest()
        patch.object(
            recovery, "latest_snapshot", lambda: copy.deepcopy(self.latest)
        ).start()
        patch.object(
            recovery, "intervening_snapshot", lambda: copy.deepcopy(self.intervening)
        ).start()
        self.calls, self.guard_calls = [], 0
        self.drift = self.appear_nvram = False
        case = self

        class Observer:
            last = None

            def __init__(self, role):
                self.role = role

            def __call__(self):
                role = self.role
                case.calls.append(role)
                state = "aborted" if role == "guard" else "poweroff"
                if role == "guard":
                    case.guard_calls += 1
                    if case.guard_calls == 2:
                        if case.drift:
                            state = "running"
                        if case.appear_nvram:
                            recovery.backup.source_paths("guard")["nvram"].write_bytes(
                                b"unexpected"
                            )
                slot = recovery.backup.SLOTS[role]
                grant = {
                    "role": role,
                    "target": {
                        "vm_uuid": slot["vm_uuid"],
                        "dmi_uuid": slot["vm_uuid"],
                        "disk_uuid": slot["disk_uuid"],
                    },
                }
                frame = boot_tests.snapshot(grant)
                frame["machine"] = frame["machine"].replace(
                    b'"poweroff"', json.dumps(state).encode()
                )
                frame["medium"] = frame["medium"].replace(b"locked write", b"created")
                frame["session"] = {
                    "vm_uuid": slot["vm_uuid"],
                    "state_before": "Unlocked",
                    "state_after": "Unlocked",
                    "pid": 0,
                }
                session_raw = canonical(session_tests.sample(role=role, state=state))
                self.last = {
                    **frame,
                    "machine_first": frame["machine"],
                    "session_raw": session_raw,
                    "queries": [],
                    "finished_mono_ns": time.monotonic_ns(),
                }
                return frame

        self.observer = Observer

    def capture(self, prior_check=None):
        return recovery.capture(
            "capture",
            observer_factory=self.observer,
            prior_check=prior_check or (lambda: copy.deepcopy(self.prior)),
            locker=self.locker,
        )

    def test_real_scratch_copy_has_explicit_aborted_provenance_and_no_boot_authority(
        self,
    ):
        result = self.capture()
        self.assertFalse(result["native_boot_authorized"])
        self.assertEqual(result["VM_mutations"], 0)
        self.assertEqual(self.calls, ["guard", "executor", "guard", "executor"])
        folder = self.root / "capture"
        context = recovery.host.object_bytes((folder / "recovery.json").read_bytes())
        receipt_raw = (folder / "backup/receipt.json").read_bytes()
        receipt = recovery.host.object_bytes(receipt_raw)
        self.assertNotIn("source_poweroff", receipt)
        self.assertEqual(receipt["source_machine_state"], "aborted")
        binding = recovery.backup.verify_files(
            receipt_raw, digest(receipt_raw), recovery=context
        )
        self.assertEqual(
            binding["recovery_context_sha256"], model.context_sha256(context)
        )
        self.assertTrue((folder / "preparation.receipt.json").exists())
        self.assertEqual(
            (folder / "backup/disk.vdi").read_bytes(), self.payloads["guard"]["disk"]
        )
        self.assertEqual(
            recovery.backup.source_paths("executor")["disk"].read_bytes(),
            self.payloads["executor"]["disk"],
        )
        with self.assertRaises(Hold):
            recovery.backup.verify_files(receipt_raw, digest(receipt_raw))

    def test_changed_current_bytes_refuse_without_completed_capture(self):
        recovery.backup.source_paths("guard")["configuration"].write_bytes(b"changed")
        with self.assertRaises(Hold):
            self.capture()
        self.assertFalse((self.root / "capture/preparation.receipt.json").exists())
        self.assertFalse((self.root / "capture/backup/receipt.json").exists())

    def test_changed_observation_or_late_nvram_never_completes_capture(self):
        self.drift = True
        with self.assertRaises(Hold):
            self.capture()
        self.assertFalse((self.root / "capture/preparation.receipt.json").exists())

    def test_late_absent_firmware_creation_is_not_hidden_by_disk_copy(self):
        self.appear_nvram = True
        with self.assertRaisesRegex(Hold, "NVRAM appeared"):
            self.capture()
        self.assertFalse((self.root / "capture/recovery.json").exists())

    def test_changed_prior_after_copy_preserves_partial_output_and_holds(self):
        calls = []

        def prior():
            calls.append(1)
            return (
                copy.deepcopy(self.prior)
                if len(calls) == 1
                else {**self.prior, "owner_nonce": "0" * 32}
            )

        with self.assertRaisesRegex(Hold, "prior provenance changed"):
            self.capture(prior)
        self.assertTrue((self.root / "capture/backup/disk.vdi").exists())
        self.assertFalse((self.root / "capture/preparation.receipt.json").exists())

    def test_backup_verification_failure_cannot_publish_completion_marker(self):
        with (
            patch.object(
                recovery.backup,
                "verify_files",
                side_effect=Hold("injected readback failure"),
            ),
            self.assertRaises(Hold),
        ):
            self.capture()
        self.assertFalse((self.root / "capture/preparation.receipt.json").exists())

    def test_existing_partial_directory_is_never_reused(self):
        (self.root / "capture").mkdir()
        with self.assertRaises(FileExistsError):
            self.capture()
        self.assertEqual(self.calls, [])

    def test_loader_requires_completion_marker_and_exact_captured_metadata(self):
        self.capture()
        with (
            patch.object(recovery, "CAPTURE_RELATIVE", "capture"),
            patch.object(
                recovery, "prior_snapshot", return_value=copy.deepcopy(self.prior)
            ),
        ):
            context, inputs = recovery.load_capture("capture")
            self.assertEqual(context["initial_state"], "aborted")
            self.assertEqual(
                set(inputs), {"recovery", "backup", "profile", "preparation"}
            )
            marker = self.root / "capture/preparation.receipt.json"
            marker.write_bytes(b"{}")
            with self.assertRaisesRegex(Hold, "incomplete or changed"):
                recovery.load_capture()

    def test_capture_selection_cannot_escape_the_workspace(self):
        with (
            patch.object(
                recovery,
                "prior_snapshot",
                side_effect=AssertionError("escaped path reached prior checks"),
            ),
            self.assertRaises(ValueError),
        ):
            recovery.load_capture(str(self.root.parent / "outside-recovery-workspace"))

    def test_source_change_after_inventory_is_caught_by_reacquired_file_hashes(self):
        original = self.observer
        path = recovery.backup.source_paths("guard")["disk"]

        class Changed(original):
            def __call__(instance):
                frame = super().__call__()
                if self.guard_calls == 2:
                    path.write_bytes(b"changed-disk-with-unchanged-profile")
                return frame

        self.observer = Changed
        with self.assertRaises(Hold):
            self.capture()
        self.assertFalse((self.root / "capture/preparation.receipt.json").exists())

    def test_changed_backup_source_provenance_does_not_pass_file_verification(self):
        self.capture()
        folder = self.root / "capture"
        context = json.loads((folder / "recovery.json").read_bytes())
        receipt = json.loads((folder / "backup/receipt.json").read_bytes())
        receipt["files"]["disk"]["source_relative"] = "unrelated-source"
        raw = canonical(receipt)
        with self.assertRaisesRegex(Hold, "source path differs"):
            recovery.backup.verify_files(raw, digest(raw), recovery=context)

    def test_recovery_preflight_uses_capture_and_fresh_observations_without_owner(self):
        from research.validation import startup_qualification as qualification

        self.capture()
        root = self.root / "preflight"
        root.mkdir()
        with (
            patch.object(recovery, "CAPTURE_RELATIVE", "capture"),
            patch.object(
                recovery, "prior_snapshot", return_value=copy.deepcopy(self.prior)
            ),
            patch.object(qualification.start, "image_environment", lambda _: None),
            patch.object(qualification.session, "NativeObserver", self.observer),
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
        ):
            _, inputs = recovery.load_capture()
            review = {
                "format": qualification.RECOVERY_REVIEW_FORMAT,
                "inputs": inputs,
                "native_argv": [
                    str(qualification.start.frontend.HEADLESS),
                    "--startvm",
                    model.GUARD_VM,
                    "--vrde",
                    "off",
                ],
                "native_executable_sha256": qualification.start.frontend.HEADLESS_SHA256,
                "environment_sha256": "a" * 64,
            }
            qualification.preactivation_probe(root, review)
            report = json.loads((root / "preactivation.receipt.json").read_bytes())
            self.assertFalse(report["owner_activated"])
            self.assertEqual(report["VM_boots"], 0)
            self.assertEqual(report["native_stop_commands"], 0)
            ordinary = self.root / "ordinary-preflight"
            ordinary.mkdir()
            with self.assertRaises(Hold):
                qualification.preactivation_probe(
                    ordinary, {**review, "format": "mcli1-one-guard-startup-review-v1"}
                )


class PriorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.addCleanup(patch.stopall)
        patch.object(recovery, "ROOT", self.root).start()
        patch.object(recovery.backup, "ROOT", self.root).start()
        patch.object(recovery.owner.stop, "STOPS_ROOT", self.root / "stops").start()
        data = records_tests.context()["prior"]
        processes, nonce = data["processes"], data["owner_nonce"]
        review = {
            **{k: processes[k] for k in ("bootstrap", "controller", "owner")},
            "original_stop_proposal": {"owner_nonce": nonce},
            "original_lease": {"synthetic": True},
        }
        review_sha = digest(canonical(review))
        patch.object(model, "PRIOR_REVIEW", review_sha).start()
        cleanup = {
            "job_active_processes": 0,
            "terminated": True,
            "root_pid": processes["frontend"]["pid"],
        }
        terminal = {
            "cleanup": cleanup,
            "grant_sha256": "a" * 64,
            "original_stop_accepted": False,
            "VM_poweroff_proven": False,
        }
        cmd_sha = digest(
            canonical(
                [str(recovery.owner.stop.VBOX), "controlvm", model.GUARD_VM, "poweroff"]
            )
        )
        values = {
            "review.json": review,
            "approval.json": {
                "format": "mcli1-one-guard-startup-approval-v1",
                "review_sha256": review_sha,
                "reference": "test:prior-approved",
            },
            "qualification.terminal.json": {
                "status": "held-startup-qualification-no-replay"
            },
            "owner/frontend.start.intent.json": {"grant_sha256": "a" * 64},
            "owner/frontend.resume.intent.json": {
                "grant_sha256": "a" * 64,
                "process": processes["frontend"],
            },
            "owner/frontend.terminal.json": terminal,
            "owner/controller.outcome.json": {
                "status": "held-controller-qualification",
                "review_sha256": review_sha,
                "retirement": terminal,
                "failure": "synthetic failure",
                "samples": [],
                "guest_ready": False,
                "native_settlement_qualified": False,
            },
            "owner/owner.sealed.json": {
                **{k: processes[k] for k in ("bootstrap", "controller", "owner")},
                "owner_nonce": nonce,
                "lease": review["original_lease"],
                "profile": {
                    "bounded_stop": {
                        "plan": {"approval": {"native_stop": "test:prior-approved"}}
                    }
                },
            },
            "owner/owner.terminal.json": {"status": "held-owner-state-not-accepted"},
            "independent-startup-inspection.json": {
                "journal": {
                    "native_owner_stop": [
                        {
                            "state": "possible-send",
                            "receipt_sha": None,
                            "child_pid": data["stop_child_pid"],
                        }
                    ]
                }
            },
            "postfiles/receipt.json": {"synthetic": True},
            "stop/poweroff.intent.json": {"command_sha256": cmd_sha},
            "stop/process.result.json": {
                "pid": data["stop_child_pid"],
                "exit": 1,
                "job_active_processes": 0,
                "command_sha256": cmd_sha,
                "stderr_sha256": digest(b"not currently running"),
                "stdout_sha256": digest(b""),
            },
        }
        self.prior_root = self.root / model.PRIOR_ROOT
        self.stoproot = recovery.owner.stop.STOPS_ROOT / nonce
        for name in model.PRIOR_ARTIFACTS:
            path = (
                self.stoproot / name.removeprefix("stop/")
                if name.startswith("stop/")
                else self.prior_root / name
            )
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = (
                b"not currently running"
                if name == "stop/stderr.bin"
                else b""
                if name == "stop/stdout.bin"
                else canonical(values[name])
            )
            path.write_bytes(raw)

    def test_prior_is_bound_to_one_consumed_attempt_and_four_retired_creations(self):
        seen = []
        value = recovery.prior_snapshot(retired=lambda p: seen.append(p) or True)
        self.assertEqual(len(seen), 4)
        self.assertEqual(value["stop_exit"], 1)
        self.assertEqual(set(value["artifacts"]), model.PRIOR_ARTIFACTS)

    def test_live_or_inaccessible_old_process_prevents_recovery(self):
        with self.assertRaisesRegex(Hold, "remains live"):
            recovery.prior_snapshot(retired=lambda _: False)
        with self.assertRaises(PermissionError):
            recovery.prior_snapshot(
                retired=lambda _: (_ for _ in ()).throw(
                    PermissionError("unreadable old process")
                )
            )

    def test_changed_prior_review_is_rejected_before_retirement_checks(self):
        (self.prior_root / "review.json").write_bytes(b"{}")
        with self.assertRaisesRegex(Hold, "review differs"):
            recovery.prior_snapshot(
                retired=lambda _: self.fail("changed review checked process")
            )

    def test_prior_cannot_be_reclassified_as_a_successful_stop(self):
        path = self.stoproot / "process.result.json"
        value = json.loads(path.read_bytes())
        value["exit"] = 0
        path.write_bytes(canonical(value))
        with self.assertRaisesRegex(Hold, "nonzero"):
            recovery.prior_snapshot(retired=lambda _: True)


class InterveningTests(unittest.TestCase):
    def setUp(self):
        self.case = PriorTests(
            "test_prior_is_bound_to_one_consumed_attempt_and_four_retired_creations"
        )
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.root, self.stoproot = self.case.prior_root, self.case.stoproot
        patch.object(model, "INTERVENING_ROOT", model.PRIOR_ROOT).start()
        parent = self.case.root / model.PARENT_CONTEXT
        parent.parent.mkdir(parents=True, exist_ok=True)
        parent.write_bytes(b"synthetic immutable historical context")
        patch.object(
            model, "PARENT_CONTEXT_SHA256", digest(parent.read_bytes())
        ).start()
        self.parent = parent
        review = self.read("review.json")
        review["inputs"] = {"recovery": {"sha256": model.PARENT_CONTEXT_SHA256}}
        self.write("review.json", review)
        review_sha = digest(canonical(review))
        patch.object(model, "INTERVENING_REVIEW", review_sha).start()
        approval = self.read("approval.json")
        approval["review_sha256"] = review_sha
        self.write("approval.json", approval)
        self.family = [
            {
                **self.read("owner/frontend.resume.intent.json")["process"],
                "exit_code": 1,
            }
        ]
        terminal = self.read("owner/frontend.terminal.json")
        terminal["cleanup"].update(
            terminated=False, root_exit=1, retained_process_exits=self.family
        )
        terminal["cleanup"].update(
            stderr_bytes=len(b"already locked for a session"),
            stderr_sha256=digest(b"already locked for a session"),
        )
        self.write("owner/frontend.terminal.json", terminal)
        outcome = self.read("owner/controller.outcome.json")
        outcome.update(review_sha256=review_sha, retirement=terminal)
        self.write("owner/controller.outcome.json", outcome)
        self.write(
            "postfiles/receipt.json",
            {
                "files": {
                    "guard": model.HISTORICAL_FILES,
                    "executor": recovery.EXECUTOR_FILES,
                }
            },
        )
        (self.root / "owner/frontend.stderr.bin").write_bytes(
            b"already locked for a session"
        )

    def read(self, name):
        return json.loads((self.root / name).read_bytes())

    def write(self, name, value):
        (self.root / name).write_bytes(canonical(value))

    def test_new_consumed_review_parent_and_every_creation_are_bound(self):
        seen = []
        value = recovery.intervening_snapshot(retired=lambda p: seen.append(p) or True)
        self.assertEqual(len(seen), 5)
        self.assertEqual(value["parent_context_sha256"], model.PARENT_CONTEXT_SHA256)
        self.assertEqual(value["review_sha256"], model.INTERVENING_REVIEW)
        self.assertEqual(value["family"], self.family)
        self.assertEqual(value["stop_exit"], 1)

    def test_new_consumed_attempt_cannot_hide_a_live_descendant(self):
        extra = {
            "pid": 9000,
            "created_filetime": 9001,
            "image": "C:/synthetic/helper.exe",
            "exit_code": 0,
        }
        terminal = self.read("owner/frontend.terminal.json")
        terminal["cleanup"]["retained_process_exits"].append(extra)
        self.write("owner/frontend.terminal.json", terminal)
        outcome = self.read("owner/controller.outcome.json")
        outcome["retirement"] = terminal
        self.write("owner/controller.outcome.json", outcome)
        with self.assertRaisesRegex(Hold, "family remains live"):
            recovery.intervening_snapshot(retired=lambda p: p["pid"] != 9000)

    def test_intervening_file_drift_is_rejected(self):
        post = self.read("postfiles/receipt.json")
        post["files"]["guard"]["disk"]["sha256"] = "0" * 64
        self.write("postfiles/receipt.json", post)
        with self.assertRaisesRegex(Hold, "backing files differ"):
            recovery.intervening_snapshot(retired=lambda _: True)

    def test_parent_bytes_are_not_replaceable_by_a_matching_path(self):
        self.parent.write_bytes(b"changed historical context")
        with self.assertRaisesRegex(Hold, "parent differs"):
            recovery.intervening_snapshot(retired=lambda _: True)


class LatestTests(unittest.TestCase):
    def setUp(self):
        self.case = InterveningTests(
            "test_new_consumed_review_parent_and_every_creation_are_bound"
        )
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.root = self.case.root
        patch.object(model, "LATEST_ROOT", model.INTERVENING_ROOT).start()
        patch.object(model, "LATEST_PARENT_CONTEXT", model.PARENT_CONTEXT).start()
        patch.object(model, "LATEST_PARENT_SHA256", model.PARENT_CONTEXT_SHA256).start()
        review = self.case.read("review.json")
        patch.object(model, "LATEST_REVIEW", digest(canonical(review))).start()
        self.leaf = {
            "pid": 9000,
            "created_filetime": 9001,
            "image": self.case.family[0]["image"],
        }
        terminal = self.case.read("owner/frontend.terminal.json")
        terminal["cleanup"].update(
            terminated=True,
            root_exit=2,
            retained_process_exits=[
                {**self.case.family[0], "exit_code": 2},
                {**self.leaf, "exit_code": None},
            ],
            stderr_bytes=len(b"Starting virtual machine: 100%"),
            stderr_sha256=digest(b"Starting virtual machine: 100%"),
        )
        self.case.write("owner/frontend.terminal.json", terminal)
        outcome = self.case.read("owner/controller.outcome.json")
        outcome.update(
            failure="OperationalError: database is locked", retirement=terminal
        )
        self.case.write("owner/controller.outcome.json", outcome)
        self.case.write(
            "owner/frontend.session.receipt.json",
            {
                "process": self.leaf,
                "grant_sha256": terminal["grant_sha256"],
                "original_lease": review["original_lease"],
            },
        )
        (self.root / "owner/frontend.stderr.bin").write_bytes(
            b"Starting virtual machine: 100%"
        )
        inspection = self.case.read("independent-startup-inspection.json")
        inspection["journal"]["frontend_start"] = [
            {
                "state": "resumed",
                "receipt_sha": None,
                "grant_sha": terminal["grant_sha256"],
            }
        ]
        self.case.write("independent-startup-inspection.json", inspection)
        self.case.write(
            "postfiles/receipt.json",
            {"files": {"guard": model.FILES, "executor": recovery.EXECUTOR_FILES}},
        )
        self.running = self.root / "owner/runtime-observations/12"
        self.running.mkdir(parents=True)
        grant = {
            "role": "guard",
            "target": {
                "vm_uuid": model.GUARD_VM,
                "dmi_uuid": model.GUARD_VM,
                "disk_uuid": model.GUARD_DISK,
            },
        }
        frame = boot_tests.snapshot(grant)
        machine = frame["machine"].replace(b'"poweroff"', b'"running"')
        for name in ("machine_first.stdout", "machine.stdout"):
            (self.running / name).write_bytes(machine)
        (self.running / "medium.stdout").write_bytes(frame["medium"])
        (self.running / "session_raw.stdout").write_bytes(
            canonical(session_tests.sample(state="running", pid=self.leaf["pid"]))
        )

    def test_latest_orphan_and_unknown_exit_remain_failure_provenance(self):
        seen = []
        value = recovery.latest_snapshot(retired=lambda p: seen.append(p) or True)
        self.assertEqual(len(seen), 6)
        self.assertEqual(value["joined_process"], self.leaf)
        self.assertEqual(value["frontend_ledger_state"], "resumed")
        self.assertIsNone(value["frontend_ledger_receipt_sha"])
        self.assertIsNone(value["family"][-1]["exit_code"])

    def test_unknown_exit_never_substitutes_for_fresh_retirement_proof(self):
        with self.assertRaisesRegex(Hold, "family remains live"):
            recovery.latest_snapshot(retired=lambda p: p["pid"] != self.leaf["pid"])

    def test_latest_receipt_cannot_be_reclassified_as_committed(self):
        inspection = self.case.read("independent-startup-inspection.json")
        inspection["journal"]["frontend_start"][0]["state"] = "session-bound"
        self.case.write("independent-startup-inspection.json", inspection)
        with self.assertRaisesRegex(Hold, "orphan journal facts"):
            recovery.latest_snapshot(retired=lambda _: True)

    def test_latest_running_pid_must_match_its_receipt(self):
        (self.running / "session_raw.stdout").write_bytes(
            canonical(session_tests.sample(state="running", pid=9999))
        )
        with self.assertRaisesRegex(Hold, "orphan journal facts"):
            recovery.latest_snapshot(retired=lambda _: True)

    def test_latest_configuration_drift_cannot_enter_recovery(self):
        post = self.case.read("postfiles/receipt.json")
        post["files"]["guard"]["configuration"]["sha256"] = "0" * 64
        self.case.write("postfiles/receipt.json", post)
        with self.assertRaisesRegex(Hold, "backing files differ"):
            recovery.latest_snapshot(retired=lambda _: True)
