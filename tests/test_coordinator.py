"""Product-domain evidence with real scratch SQLite stores; no live adapters."""

import copy
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from coordinator import Conflict, Coordinator, Invalid, Principal, Store
from coordinator import store as store_module
from coordinator.domain import plan_spec
from coordinator.store import patched_sqlite


def copy_store(source, target):
    shutil.copyfile(source, target)
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(source) + suffix)
        if sidecar.exists():
            shutil.copyfile(sidecar, Path(str(target) + suffix))


def project():
    return {
        "name": "Example",
        "repository": "fixture-only",
        "requirements": [{"id": "R1", "text": "Validate then use the input"}],
        "context": {"goal": "A two-task milestone"},
    }


GSD_SNAPSHOT = Path(__file__).resolve().parent / "fixtures" / "gsd-schema-1.json"
GSD_PLANS = Path(__file__).resolve().parent / "fixtures" / "gsd-schema-1-plans"
GSD_SNAPSHOT_SHA256 = "3568a79095dd2868053f389295e11b57c45f18af79f5c74ace509f5ec9f9aa92"
GSD_PLAN_SHA256 = {
    "01-01-PLAN.md": "87c0d15f905df82fa8d607c3215cd8b9830e78e622a53fe6687084051bccff2c",
    "01-02-PLAN.md": "82329e3c3146d52285e7b1215d41e447bd6670bffa64694fa63bf277fa5653ed",
}


def gsd_project():
    spec = project()
    spec["requirements"] = [
        {"id": "CLI-01", "text": "Preserve nonblank names."},
        {"id": "CLI-02", "text": "Provide the CLI."},
    ]
    return spec


def plan():
    tasks = []
    for key, deps in (("T1", []), ("T2", ["T1"])):
        tasks.append(
            {
                "id": key,
                "title": key,
                "instructions": "Implement the approved criterion",
                "depends_on": deps,
                "allowed_paths": ["src/example.py"],
                "criteria": [
                    {
                        "id": "C1",
                        "description": "Expected behavior",
                        "requirement_id": "R1",
                        "checks": ["unit"],
                    }
                ],
                "checks": [
                    {
                        "id": "unit",
                        "argv": ["python", "-m", "unittest"],
                        "timeout_seconds": 30,
                    }
                ],
                "max_attempts": 2,
            }
        )
    return {
        "title": "Example milestone",
        "baseline_revision": "a" * 40,
        "requirements_revision": 1,
        "tasks": tasks,
    }


class ValidationTests(unittest.TestCase):
    def test_plan_rejects_cycle_unresolved_dependencies_and_unsafe_paths(self):
        for mutate in (
            lambda p: p["tasks"][0]["depends_on"].append("T2"),
            lambda p: p["tasks"][1]["depends_on"].append("missing"),
            lambda p: p["tasks"][0]["allowed_paths"].append("../outside"),
            lambda p: p["tasks"][0]["allowed_paths"].append(".Git/config"),
            lambda p: p["tasks"][0]["criteria"][0].update(checks=["unknown"]),
            lambda p: p["tasks"][0]["criteria"][0].update(requirement_id=[]),
            lambda p: p["tasks"][0].update(max_attempts=True),
        ):
            value = plan()
            mutate(value)
            with self.subTest(value=value), self.assertRaises(Invalid):
                plan_spec(value, {"R1"})

    def test_unpatched_runtime_refuses_before_creating_a_store(self):
        with (
            tempfile.TemporaryDirectory() as folder,
            patch("coordinator.store.patched_sqlite", return_value=False),
        ):
            target = Path(folder) / "never.sqlite"
            with self.assertRaisesRegex(Invalid, "WAL-reset"):
                Store.create(target)
            self.assertFalse(target.exists())


@unittest.skipUnless(
    patched_sqlite(), "product persistence requires a patched SQLite runtime"
)
class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "product.sqlite"
        self.store = Store.create(self.path)
        self.addCleanup(lambda: self.store.close() if self.store is not None else None)
        self.app = Coordinator(self.store, Principal("test-developer"))
        self.project_id = self.app.create_project(project())["project_id"]

    def approve(self):
        submitted = self.app.submit_plan(
            self.project_id, "M1", plan(), expected_project_version=1
        )
        approved = self.app.approve_plan(
            submitted["plan_id"],
            submitted["digest"],
            expected_project_version=1,
            expected_milestone_version=submitted["milestone_version"],
        )
        self.pv, self.mv = approved["project_version"], approved["milestone_version"]
        return submitted

    def claim(self, task="T1", **extra):
        return self.app.claim_task(
            self.project_id,
            "M1",
            task,
            expected_project_version=self.pv,
            expected_milestone_version=self.mv,
            **extra,
        )

    def test_exact_approval_and_dependency_gates_survive_reopen(self):
        submitted = self.app.submit_plan(
            self.project_id, "M1", plan(), expected_project_version=1
        )
        with self.assertRaisesRegex(Conflict, "no approved"):
            self.app.claim_task(
                self.project_id,
                "M1",
                "T1",
                expected_project_version=1,
                expected_milestone_version=1,
            )
        with self.assertRaisesRegex(Conflict, "digest"):
            self.app.approve_plan(
                submitted["plan_id"],
                "wrong",
                expected_project_version=1,
                expected_milestone_version=1,
            )
        approved = self.app.approve_plan(
            submitted["plan_id"],
            submitted["digest"],
            expected_project_version=1,
            expected_milestone_version=1,
        )
        self.pv, self.mv = approved["project_version"], approved["milestone_version"]
        self.store.close()
        self.store = Store(self.path)
        self.app = Coordinator(self.store, Principal("test-developer"))
        with self.assertRaisesRegex(Conflict, "dependencies"):
            self.claim("T2")
        attempt = self.claim()
        operation = self.app.start_scripted(attempt["attempt_id"], expected_version=1)
        result = self.app.record_scripted_result(operation["operation_id"], "candidate")
        self.assertFalse(result["task_accepted"])
        status = self.app.status(self.project_id)
        self.assertEqual(
            [t["state"] for t in status["milestones"][0]["tasks"]],
            ["awaiting_verification", "blocked_dependencies"],
        )
        self.assertFalse(status["capabilities"]["native_execution"])

    def test_local_command_ack_loss_deduplicates_but_changed_intent_refuses(self):
        original = self.app.create_project(project(), command_id="create-once")
        self.assertEqual(
            self.app.create_project(project(), command_id="create-once"), original
        )
        altered = project()
        altered["name"] = "Changed"
        with self.assertRaisesRegex(Conflict, "command id"):
            self.app.create_project(altered, command_id="create-once")
        self.assertEqual(len(self.app.events()), 2)

    def test_competing_connections_admit_one_attempt(self):
        self.approve()
        barrier = threading.Barrier(2)

        def compete(index):
            with Store(self.path) as store:
                app = Coordinator(store, Principal(f"worker-{index}", "service"))
                barrier.wait(timeout=5)
                try:
                    return app.claim_task(
                        self.project_id,
                        "M1",
                        "T1",
                        expected_project_version=self.pv,
                        expected_milestone_version=self.mv,
                    )["attempt_id"]
                except Conflict:
                    return None

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(compete, (1, 2)))
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(len(self.app.status(self.project_id)["attempts"]), 1)

    def test_restart_recovery_holds_delivery_and_rejects_stale_completion(self):
        self.approve()
        attempt = self.claim()
        self.app.start_scripted(attempt["attempt_id"], expected_version=1)
        self.store.close()
        self.store = Store(self.path)
        self.app = Coordinator(self.store, Principal("test-developer"))
        self.app.recover(
            self.project_id, expected_version=self.pv, reason="sender disappeared"
        )
        held = self.app.status(self.project_id)["attempts"][0]
        self.assertEqual((held["state"], held["operation_state"]), ("held", "unknown"))
        with self.assertRaises(Conflict):
            self.app.start_scripted(
                attempt["attempt_id"], expected_version=held["version"]
            )
        late = self.app.record_scripted_result(attempt["operation_id"], "candidate")
        self.assertFalse(late["accepted"])
        self.assertTrue(late["late_observation_retained"])
        self.app.abandon_scripted(
            attempt["attempt_id"],
            expected_version=held["version"],
            reason="pure scripted computation has no external side effects",
        )
        resumed = self.app.resume(self.project_id, expected_version=self.pv + 1)
        self.pv = resumed["version"]
        replacement = self.claim()
        self.assertNotEqual(replacement["attempt_id"], attempt["attempt_id"])

    def test_sender_process_crash_retains_delivery_intent_and_requires_recovery(self):
        self.approve()
        attempt = self.claim()
        script = (
            "import os,sys; from coordinator import Store,Coordinator,Principal; "
            "s=Store(sys.argv[1]); a=Coordinator(s,Principal('crashing-sender','service')); "
            "a.start_scripted(sys.argv[2],expected_version=1); os._exit(29)"
        )
        process = subprocess.run(
            [sys.executable, "-c", script, str(self.path), attempt["attempt_id"]],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(process.returncode, 29, process.stderr)
        self.assertEqual(
            self.app.status(self.project_id)["attempts"][0]["operation_state"],
            "possible_send",
        )
        self.app.recover(
            self.project_id,
            expected_version=self.pv,
            reason="confirmed sender exit with an unsettled intent",
        )
        status = self.app.status(self.project_id)
        self.assertEqual(status["attempts"][0]["state"], "held")
        with self.assertRaises(Conflict):
            self.app.start_scripted(
                attempt["attempt_id"], expected_version=status["attempts"][0]["version"]
            )

    def test_duplicate_receipt_after_pause_does_not_reactivate_authority(self):
        self.approve()
        attempt = self.claim()
        self.app.start_scripted(attempt["attempt_id"], expected_version=1)
        self.app.record_scripted_result(attempt["operation_id"], "candidate")
        self.app.pause(
            self.project_id, expected_version=self.pv, reason="developer pause"
        )
        result = self.app.record_scripted_result(attempt["operation_id"], "candidate")
        self.assertFalse(result["accepted"])
        self.assertTrue(result["duplicate"])

    def test_pause_cancels_unsent_work_and_revision_requires_new_approval(self):
        self.approve()
        self.claim()
        changed = copy.deepcopy(project())
        changed["context"]["goal"] = "A revised goal"
        self.app.revise_project(self.project_id, changed, expected_version=self.pv)
        status = self.app.status(self.project_id)
        self.assertTrue(status["project"]["paused"])
        self.assertEqual(status["attempts"][0]["state"], "cancelled")
        with self.assertRaisesRegex(Conflict, "current approved"):
            self.app.resume(self.project_id, expected_version=self.pv + 1)
        with self.assertRaisesRegex(Conflict, "version"):
            self.app.pause(
                self.project_id, expected_version=self.pv, reason="stale view"
            )

    def test_attempt_limits_carry_across_corrections(self):
        self.approve()
        for _ in range(2):
            attempt = self.claim()
            self.app.start_scripted(attempt["attempt_id"], expected_version=1)
            self.app.record_scripted_result(attempt["operation_id"], "failed")
        with self.assertRaisesRegex(Conflict, "exhausted"):
            self.claim()

    def test_conflicting_receipts_are_preserved_and_fence_authority(self):
        self.approve()
        attempt = self.claim()
        self.app.start_scripted(attempt["attempt_id"], expected_version=1)
        self.app.record_scripted_result(attempt["operation_id"], "candidate")
        result = self.app.record_scripted_result(attempt["operation_id"], "failed")
        self.assertTrue(result["conflicting_receipts"])
        status = self.app.status(self.project_id)
        self.assertTrue(status["project"]["paused"])
        self.assertEqual(status["attempts"][0]["state"], "held")
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0], 2
        )

    def test_service_identity_cannot_approve_or_pause(self):
        service = Coordinator(self.store, Principal("scripted-service", "service"))
        with self.assertRaisesRegex(Invalid, "developer"):
            service.pause(self.project_id, expected_version=1, reason="not a developer")

    def test_backup_readback_is_an_archive_not_new_execution_authority(self):
        self.approve()
        target = Path(self.temp.name) / "backup.sqlite"
        self.store.backup(target)
        with Store(target) as backup:
            app = Coordinator(backup, Principal("test-developer"))
            self.assertEqual(app.status(self.project_id)["project"]["spec"], project())
            with self.assertRaisesRegex(Invalid, "archive"):
                app.pause(
                    self.project_id,
                    expected_version=self.pv,
                    reason="must not activate a backup",
                )
        with self.assertRaises(FileExistsError):
            self.store.backup(target)
        self.assertEqual(
            self.store.db.execute("PRAGMA integrity_check").fetchall()[0][0], "ok"
        )

    def test_copy_interrupted_before_archive_mark_cannot_create_authority(self):
        target = Path(self.temp.name) / "interrupted-copy.sqlite"
        destination = sqlite3.connect(target, autocommit=True)
        try:
            # A crash after backup() but before marking the archive must not
            # expose an independently writable copy of the old authority.
            self.store.db.backup(destination)
        finally:
            destination.close()
        with Store(target) as copied:
            app = Coordinator(copied, Principal("test-developer"))
            self.assertEqual(app.status(self.project_id)["project"]["spec"], project())
            with self.assertRaisesRegex(Invalid, "restore/recovery"):
                app.pause(
                    self.project_id, expected_version=1, reason="copied authority"
                )
        self.assertEqual(self.app.status(self.project_id)["project"]["version"], 1)

    def test_restore_rebinds_a_new_primary_and_refuses_archive_and_copy(self):
        archive = Path(self.temp.name) / "backup.sqlite"
        archived = self.store.backup(archive)
        copied = Path(self.temp.name) / "copied.sqlite"
        copy_store(self.path, copied)
        restored = Path(self.temp.name) / "restored.sqlite"
        outcome = Store.restore(archive, restored, archived["digest"])
        self.assertEqual(outcome["mode"], "primary")
        self.assertEqual(outcome["schema"], 7)
        with Store(restored) as store:
            app = Coordinator(store, Principal("test-developer"))
            paused = app.pause(
                self.project_id, expected_version=1, reason="restored primary"
            )
            self.assertEqual(paused["version"], 2)
        with Store(archive) as store:
            app = Coordinator(store, Principal("test-developer"))
            with self.assertRaisesRegex(Invalid, "archive"):
                app.pause(
                    self.project_id,
                    expected_version=1,
                    reason="archive stays read-only",
                )
        with Store(copied) as store:
            app = Coordinator(store, Principal("test-developer"))
            with self.assertRaisesRegex(Invalid, "restore/recovery"):
                app.pause(
                    self.project_id,
                    expected_version=1,
                    reason="copy keeps its old path",
                )
        self.assertEqual(
            self.app.pause(
                self.project_id, expected_version=1, reason="original primary remains"
            )["version"],
            2,
        )

    def test_tampered_or_drifted_archive_leaves_no_destination(self):
        archive = Path(self.temp.name) / "backup.sqlite"
        archived = self.store.backup(archive)
        missing = Path(self.temp.name) / "missing-digest.sqlite"
        with self.assertRaisesRegex(Conflict, "digest"):
            Store.restore(archive, missing, "0" * 64)
        self.assertFalse(missing.exists())
        occupied = Path(self.temp.name) / "occupied.sqlite"
        occupied.write_bytes(b"keep")
        with self.assertRaisesRegex(Invalid, "exists"):
            Store.restore(archive, occupied, archived["digest"])
        self.assertEqual(occupied.read_bytes(), b"keep")
        raw = bytearray(archive.read_bytes())
        raw[100] ^= 0x01
        archive.write_bytes(raw)
        corrupt = hashlib.sha256(raw).hexdigest()
        rejected = Path(self.temp.name) / "corrupt.sqlite"
        with self.assertRaisesRegex(Invalid, "integrity"):
            Store.restore(archive, rejected, corrupt)
        self.assertFalse(rejected.exists())

    def test_archive_drift_and_failed_rebind_leave_no_destination(self):
        archive = Path(self.temp.name) / "backup.sqlite"
        archived = self.store.backup(archive)
        destination = Path(self.temp.name) / "drift.sqlite"
        real = store_module.load_archive_bytes

        def drift(path):
            payload = real(path)
            if Path(path) == archive and drift.calls == 1:
                drift.calls += 1
                return payload + b"x"
            drift.calls += 1
            return payload

        drift.calls = 0
        with (
            patch("coordinator.store.load_archive_bytes", side_effect=drift),
            self.assertRaisesRegex(Conflict, "drifted"),
        ):
            Store.restore(archive, destination, archived["digest"])
        self.assertFalse(destination.exists())
        failed = Path(self.temp.name) / "failed.sqlite"
        with (
            patch(
                "coordinator.store.rebind_restored",
                side_effect=Invalid("rebind failed"),
            ),
            self.assertRaisesRegex(Invalid, "rebind failed"),
        ):
            Store.restore(archive, failed, archived["digest"])
        self.assertFalse(failed.exists())
        self.assertFalse(Path(str(failed) + "-wal").exists())

    def test_plain_copy_and_old_schema_are_not_archives(self):
        archive = Path(self.temp.name) / "backup.sqlite"
        self.store.backup(archive)
        db = sqlite3.connect(archive, autocommit=True)
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE meta SET value='0' WHERE key='archive'")
            db.execute("COMMIT")
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            db.close()
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        unmarked = Path(self.temp.name) / "unmarked.sqlite"
        with self.assertRaisesRegex(Invalid, "must be an archive"):
            Store.restore(archive, unmarked, digest)
        self.assertFalse(unmarked.exists())
        db = sqlite3.connect(archive, autocommit=True)
        try:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE meta SET value='1' WHERE key='archive'")
            db.execute("PRAGMA user_version=6")
            db.execute("COMMIT")
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            db.close()
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        outdated = Path(self.temp.name) / "outdated.sqlite"
        with self.assertRaisesRegex(Invalid, "migration required"):
            Store.restore(archive, outdated, digest)
        self.assertFalse(outdated.exists())

    def test_cli_restore_uses_the_archive_digest(self):
        archive = Path(self.temp.name) / "cli-archive.sqlite"
        destination = Path(self.temp.name) / "cli-restored.sqlite"
        argv = [sys.executable, "-m", "coordinator", "--db", str(self.path)]
        backed = subprocess.run(
            [*argv, "backup", str(archive)],
            capture_output=True,
            text=True,
            check=True,
        )
        digest = json.loads(backed.stdout)["result"]["digest"]
        restored = subprocess.run(
            [
                sys.executable,
                "-m",
                "coordinator",
                "restore",
                str(archive),
                str(destination),
                "--digest",
                digest,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(json.loads(restored.stdout)["result"]["mode"], "primary")
        refused = subprocess.run(
            [
                *argv[:-2],
                "--db",
                str(archive),
                "pause",
                self.project_id,
                "--expected-version",
                "1",
                "--reason",
                "archive",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(refused.returncode, 2)
        self.assertIn("archive", refused.stdout)

    def test_cli_round_trip_and_structured_failure(self):
        value = Path(self.temp.name) / "project.json"
        value.write_text(json.dumps(project()), encoding="utf-8")
        argv = [sys.executable, "-m", "coordinator", "--db", str(self.path)]
        created = subprocess.run(
            [*argv, "project-create", str(value)],
            capture_output=True,
            text=True,
            check=True,
        )
        project_id = json.loads(created.stdout)["result"]["project_id"]
        status = subprocess.run(
            [*argv, "status", project_id], capture_output=True, text=True, check=True
        )
        self.assertEqual(
            json.loads(status.stdout)["result"]["project"]["spec"], project()
        )
        refused = subprocess.run(
            [
                *argv,
                "pause",
                project_id,
                "--expected-version",
                "100",
                "--reason",
                "stale",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(refused.returncode, 2)
        self.assertEqual(json.loads(refused.stdout)["error"], "Conflict")

    def test_discovery_records_two_revisions_and_keeps_exact_plan_approval(self):
        with self.assertRaisesRegex(Invalid, "discovery question"):
            self.app.record_discovery(
                self.project_id, expected_version=1, question="", answer="Blank"
            )
        self.assertEqual(self.app.status(self.project_id)["project"]["revision"], 1)

        def record(version, question, answer, command_id=None, requirements=None):
            return self.app.record_discovery(
                self.project_id,
                expected_version=version,
                question=question,
                answer=answer,
                requirements=requirements,
                command_id=command_id,
            )

        with (
            patch("socket.socket", side_effect=AssertionError("provider socket")),
            patch("subprocess.Popen", side_effect=AssertionError("candidate command")),
        ):
            first = record(1, "What must persist?", "The stored answer.", "turn-1")
            self.assertEqual(
                record(1, "What must persist?", "The stored answer.", "turn-1"), first
            )
            with self.assertRaisesRegex(Conflict, "command id"):
                record(1, "What must persist?", "A different answer.", "turn-1")
            second = record(
                first["version"], "What still needs approval?", "The exact plan digest."
            )
        self.assertEqual(first["requirements_revision"], 2)
        self.assertTrue(first["paused"])
        self.assertTrue(first["needs_new_plan_approval"])
        self.assertEqual(second["requirements_revision"], 3)
        with Store(self.path) as reopened:
            again = Coordinator(reopened, Principal("reopened-developer"))
            spec = again.status(self.project_id)["project"]["spec"]
        turns = spec["context"]["discovery"]["turns"]
        self.assertEqual(
            [(turn["n"], turn["question"], turn["answer"]) for turn in turns],
            [
                (2, "What must persist?", "The stored answer."),
                (3, "What still needs approval?", "The exact plan digest."),
            ],
        )
        self.assertEqual(spec["context"]["goal"], project()["context"]["goal"])
        self.assertEqual(spec["requirements"], project()["requirements"])
        with self.assertRaisesRegex(Conflict, "record version changed"):
            record(first["version"] - 1, "Stale?", "No new turn.")
        with self.assertRaisesRegex(Conflict, "record version changed"):
            self.app.revise_project(
                self.project_id, project(), expected_version=first["version"] - 1
            )
        held = self.app.status(self.project_id)
        self.assertEqual(held["project"]["revision"], 3)
        self.assertEqual(
            len(held["project"]["spec"]["context"]["discovery"]["turns"]), 2
        )
        before_pause = held["project"]["version"]
        self.app.pause(
            self.project_id, expected_version=before_pause, reason="hold discovery"
        )
        with self.assertRaisesRegex(Conflict, "record version changed"):
            record(before_pause, "After pause?", "Still no new turn.")
        paused = self.app.status(self.project_id)
        self.assertEqual(paused["project"]["revision"], 3)
        self.assertEqual(
            len(paused["project"]["spec"]["context"]["discovery"]["turns"]), 2
        )
        spec = plan()
        spec["requirements_revision"] = paused["project"]["revision"]
        current = paused["project"]
        submitted = self.app.submit_plan(
            self.project_id,
            "M1",
            spec,
            expected_project_version=current["version"],
        )
        self.assertFalse(submitted["approved"])
        waiting = self.app.status(self.project_id)
        self.assertIsNone(waiting["milestones"][0]["approved_plan_id"])
        approvals = [
            item
            for item in waiting["pending_decisions"]
            if item["kind"] == "plan_approval"
        ]
        self.assertEqual(approvals[0]["digest"], submitted["digest"])
        self.assertFalse(waiting["capabilities"]["task_acceptance"])
        self.assertFalse(waiting["live_eligible"])
        with self.assertRaisesRegex(Conflict, "digest"):
            self.app.approve_plan(
                submitted["plan_id"],
                "f" * 64,
                expected_project_version=submitted["project_version"],
                expected_milestone_version=submitted["milestone_version"],
            )
        self.assertIsNone(
            self.app.status(self.project_id)["milestones"][0]["approved_plan_id"]
        )
        approved = self.app.approve_plan(
            submitted["plan_id"],
            submitted["digest"],
            expected_project_version=submitted["project_version"],
            expected_milestone_version=submitted["milestone_version"],
        )
        self.assertTrue(approved["approved"])
        self.assertEqual(
            self.app.status(self.project_id)["milestones"][0]["approved_plan_id"],
            submitted["plan_id"],
        )
        continued = record(
            approved["project_version"],
            "May discovery continue on the new version?",
            "Yes. The new version is current.",
        )
        self.assertEqual(continued["requirements_revision"], 4)
        self.assertEqual(
            self.app.status(self.project_id)["project"]["spec"]["context"]["discovery"][
                "turns"
            ][-1]["answer"],
            "Yes. The new version is current.",
        )

    def test_cli_discovery_record_reopens_the_same_answers(self):
        self.store.close()
        self.store = None
        requirements = Path(self.temp.name) / "requirements.json"
        requirements.write_text(
            json.dumps([{"id": "R9", "text": "Keep this answer"}]),
            encoding="utf-8",
        )
        argv = [sys.executable, "-m", "coordinator", "--db", str(self.path)]
        first = subprocess.run(
            [
                *argv,
                "discovery-record",
                self.project_id,
                "--expected-version",
                "1",
                "--question",
                "What is stored?",
                "--answer",
                "The first answer.",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        recorded = json.loads(first.stdout)["result"]
        self.assertEqual(recorded["requirements_revision"], 2)
        self.assertTrue(recorded["needs_new_plan_approval"])
        stale = subprocess.run(
            [
                *argv,
                "discovery-record",
                self.project_id,
                "--expected-version",
                "1",
                "--question",
                "Again?",
                "--answer",
                "No.",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(stale.returncode, 2)
        self.assertEqual(json.loads(stale.stdout)["error"], "Conflict")
        replaced = subprocess.run(
            [
                *argv,
                "discovery-record",
                self.project_id,
                "--expected-version",
                str(recorded["version"]),
                "--question",
                "Which requirement replaced the list?",
                "--answer",
                "R9.",
                "--requirements",
                str(requirements),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(replaced.returncode, 0, replaced.stdout + replaced.stderr)
        status = subprocess.run(
            [*argv, "status", self.project_id],
            capture_output=True,
            text=True,
            check=True,
        )
        spec = json.loads(status.stdout)["result"]["project"]["spec"]
        self.assertEqual(
            [
                (turn["n"], turn["answer"])
                for turn in spec["context"]["discovery"]["turns"]
            ],
            [(2, "The first answer."), (3, "R9.")],
        )
        self.assertEqual(
            spec["requirements"], [{"id": "R9", "text": "Keep this answer"}]
        )
        self.assertEqual(spec["context"]["goal"], project()["context"]["goal"])
        self.assertFalse(
            json.loads(status.stdout)["result"]["capabilities"]["task_acceptance"]
        )
        self.assertFalse(json.loads(status.stdout)["result"]["live_eligible"])

    def _plan_count(self):
        return self.store.db.execute("SELECT COUNT(*) FROM plans").fetchone()[0]

    def _import_gsd(self, project_id, **overrides):
        arguments = {
            "snapshot": GSD_SNAPSHOT,
            "snapshot_digest": GSD_SNAPSHOT_SHA256,
            "plans": GSD_PLANS,
            "expected_project_version": 1,
            "baseline_revision": "a" * 40,
            "max_attempts": 2,
            "check_timeout_seconds": 30,
        }
        arguments.update(overrides)
        return self.app.import_gsd(project_id, "M-CLI1", **arguments)

    def _copy_gsd(self, name):
        root = Path(self.temp.name) / name
        plans = root / "plans"
        plans.mkdir(parents=True)
        snapshot = root / "snapshot.json"
        snapshot.write_bytes(GSD_SNAPSHOT.read_bytes())
        for filename in GSD_PLAN_SHA256:
            (plans / filename).write_bytes((GSD_PLANS / filename).read_bytes())
        return snapshot, plans

    def test_gsd_import_submits_one_unapproved_plan(self):
        raw = GSD_SNAPSHOT.read_bytes()
        self.assertEqual(len(raw), 5270)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), GSD_SNAPSHOT_SHA256)
        for filename, digest in GSD_PLAN_SHA256.items():
            body = (GSD_PLANS / filename).read_bytes()
            self.assertEqual(hashlib.sha256(body).hexdigest(), digest)
        project_id = self.app.create_project(gsd_project())["project_id"]
        with (
            patch("socket.socket", side_effect=AssertionError("network")),
            patch("subprocess.Popen", side_effect=AssertionError("candidate command")),
        ):
            submitted = self._import_gsd(project_id, command_id="import-once")
            self.assertEqual(
                self._import_gsd(project_id, command_id="import-once"), submitted
            )
        self.assertFalse(submitted["approved"])
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM approvals").fetchone()[0], 0
        )
        changed = json.loads(raw)
        changed["diagnostics"][0]["detail"] += "x"
        mutated = Path(self.temp.name) / "mutated-snapshot.json"
        mutated_bytes = json.dumps(changed).encode()
        mutated.write_bytes(mutated_bytes)
        with self.assertRaisesRegex(Conflict, "command id"):
            self._import_gsd(
                project_id,
                snapshot=mutated,
                snapshot_digest=hashlib.sha256(mutated_bytes).hexdigest(),
                command_id="import-once",
            )
        self.assertEqual(self._plan_count(), 1)
        status = self.app.status(project_id)
        self.assertEqual(len(status["plans"]), 1)
        self.assertIsNone(status["milestones"][0]["approved_plan_id"])
        approvals = [
            item
            for item in status["pending_decisions"]
            if item["kind"] == "plan_approval"
        ]
        self.assertEqual(
            approvals,
            [
                {
                    "kind": "plan_approval",
                    "milestone_key": "M-CLI1",
                    "plan_id": submitted["plan_id"],
                    "digest": submitted["digest"],
                    "summary": "Approve the exact plan for M-CLI1",
                }
            ],
        )
        spec = status["plans"][0]["spec"]
        tasks = spec["tasks"]
        self.assertEqual([task["id"] for task in tasks], ["T-01", "T-02"])
        self.assertEqual(tasks[0]["depends_on"], [])
        self.assertEqual(tasks[1]["depends_on"], ["T-01"])
        self.assertEqual(
            [task["checks"][0]["argv"] for task in tasks],
            [
                ["node", "--test", "test/validate.test.js"],
                ["node", "--test", "test/cli.test.js"],
            ],
        )
        self.assertEqual(
            [task["allowed_paths"] for task in tasks],
            [
                ["src/validate.js", "test/validate.test.js"],
                ["src/cli.js", "test/cli.test.js"],
            ],
        )
        self.assertEqual(
            [
                criterion["requirement_id"]
                for task in tasks
                for criterion in task["criteria"]
            ],
            ["CLI-01", "CLI-01", "CLI-02", "CLI-02", "CLI-02"],
        )
        self.assertIn("Hello, <name>!", tasks[1]["instructions"])
        self.assertEqual(spec["title"], "Validate names and provide a CLI.")
        self.assertEqual(spec["baseline_revision"], "a" * 40)
        self.assertEqual(spec["requirements_revision"], 1)
        self.assertEqual(
            [task["max_attempts"] for task in tasks],
            [2, 2],
        )
        self.assertTrue(
            all(task["checks"][0]["timeout_seconds"] == 30 for task in tasks)
        )
        done = "All frozen candidate checks and independent review pass on the exact revision."
        self.assertNotIn(
            done,
            [
                criterion["description"]
                for task in tasks
                for criterion in task["criteria"]
            ],
        )
        self.assertEqual(
            status["project"]["spec"]["requirements"], gsd_project()["requirements"]
        )
        self.assertFalse(status["capabilities"]["task_acceptance"])
        self.assertFalse(status["live_eligible"])
        kinds = [row[0] for row in self.store.db.execute("SELECT kind FROM events")]
        self.assertIn("plan.submit", kinds)
        self.assertNotIn("project.revise", kinds)
        self.assertNotIn("discovery.record", kinds)
        self.assertNotIn("plan.approve", kinds)
        self.store.close()
        self.store = Store(self.path)
        self.app = Coordinator(self.store, Principal("reopened-developer"))
        reopened = self.app.status(project_id)
        self.assertEqual(reopened["plans"][0]["digest"], submitted["digest"])
        self.assertIsNone(reopened["milestones"][0]["approved_plan_id"])
        with self.assertRaisesRegex(Conflict, "digest"):
            self.app.approve_plan(
                submitted["plan_id"],
                "f" * 64,
                expected_project_version=submitted["project_version"],
                expected_milestone_version=submitted["milestone_version"],
            )
        self.assertIsNone(
            self.app.status(project_id)["milestones"][0]["approved_plan_id"]
        )
        approved = self.app.approve_plan(
            submitted["plan_id"],
            submitted["digest"],
            expected_project_version=submitted["project_version"],
            expected_milestone_version=submitted["milestone_version"],
        )
        self.assertTrue(approved["approved"])
        final = self.app.status(project_id)
        self.assertEqual(
            final["milestones"][0]["approved_plan_id"], submitted["plan_id"]
        )
        self.assertFalse(final["capabilities"]["task_acceptance"])
        self.assertFalse(final["live_eligible"])

    def test_gsd_import_refuses_before_a_plan_write(self):
        self.assertEqual(self._plan_count(), 0)
        mutated, _plans = self._copy_gsd("digest")
        flipped = bytearray(mutated.read_bytes())
        flipped[0] ^= 0x01
        mutated.write_bytes(flipped)
        with self.assertRaisesRegex(Invalid, "snapshot digest"):
            self._import_gsd(self.project_id, snapshot=mutated)
        snapshot, plans = self._copy_gsd("plan-byte")
        plan_path = plans / "01-01-PLAN.md"
        plan_path.write_bytes(
            plan_path.read_bytes().replace(b"Implement T-01", b"Jmplement T-01", 1)
        )
        with self.assertRaisesRegex(Invalid, "objective"):
            self._import_gsd(self.project_id, snapshot=snapshot, plans=plans)
        for version in (2, "1", True):
            snapshot, _plans = self._copy_gsd(f"schema-{version}")
            document = json.loads(snapshot.read_bytes())
            document["schema_version"] = version
            encoded = json.dumps(document).encode()
            snapshot.write_bytes(encoded)
            with self.assertRaisesRegex(Invalid, "schema"):
                self._import_gsd(
                    self.project_id,
                    snapshot=snapshot,
                    snapshot_digest=hashlib.sha256(encoded).hexdigest(),
                )
        snapshot, plans = self._copy_gsd("cycle")
        document = json.loads(snapshot.read_bytes())
        document["phases"][0]["plans"][0]["dependsOn"] = ["01-02"]
        document["phases"][0]["plans"][1]["dependsOn"] = ["01-01"]
        encoded = json.dumps(document).encode()
        snapshot.write_bytes(encoded)
        first = plans / "01-01-PLAN.md"
        first.write_bytes(
            first.read_bytes().replace(b"depends_on: []", b'depends_on: ["01-02"]', 1)
        )
        with self.assertRaisesRegex(Invalid, "cycle"):
            self._import_gsd(
                self.project_id,
                snapshot=snapshot,
                plans=plans,
                snapshot_digest=hashlib.sha256(encoded).hexdigest(),
            )
        with self.assertRaisesRegex(Invalid, "snapshot requirement"):
            self._import_gsd(self.project_id)
        snapshot, plans = self._copy_gsd("missing-target")
        document = json.loads(snapshot.read_bytes())
        document["phases"][0]["plans"][1]["dependsOn"] = ["99-99"]
        encoded = json.dumps(document).encode()
        snapshot.write_bytes(encoded)
        second = plans / "01-02-PLAN.md"
        second.write_bytes(
            second.read_bytes().replace(
                b'depends_on: ["01-01"]', b'depends_on: ["99-99"]', 1
            )
        )
        with self.assertRaisesRegex(Invalid, "missing dependency"):
            self._import_gsd(
                self.project_id,
                snapshot=snapshot,
                plans=plans,
                snapshot_digest=hashlib.sha256(encoded).hexdigest(),
            )
        snapshot, plans = self._copy_gsd("duplicate-task")
        document = json.loads(snapshot.read_bytes())
        document["phases"][0]["plans"][1]["tasks"][0]["name"] = "T-01"
        encoded = json.dumps(document).encode()
        snapshot.write_bytes(encoded)
        renamed = plans / "01-02-PLAN.md"
        renamed.write_bytes(
            renamed.read_bytes().replace(b"<name>T-02</name>", b"<name>T-01</name>", 1)
        )
        with self.assertRaisesRegex(Invalid, "duplicate task id"):
            self._import_gsd(
                self.project_id,
                snapshot=snapshot,
                plans=plans,
                snapshot_digest=hashlib.sha256(encoded).hexdigest(),
            )
        snapshot, plans = self._copy_gsd("missing-file")
        (plans / "01-02-PLAN.md").unlink()
        with self.assertRaisesRegex(Invalid, "plan files"):
            self._import_gsd(self.project_id, snapshot=snapshot, plans=plans)
        snapshot, plans = self._copy_gsd("extra-file")
        (plans / "EXTRA.md").write_bytes(b"extra\n")
        with self.assertRaisesRegex(Invalid, "plan files"):
            self._import_gsd(self.project_id, snapshot=snapshot, plans=plans)
        snapshot, plans = self._copy_gsd("oversized")
        (plans / "01-01-PLAN.md").write_bytes(b"x" * (128 * 1024 + 1))
        with self.assertRaisesRegex(Invalid, "128 KiB"):
            self._import_gsd(self.project_id, snapshot=snapshot, plans=plans)
        huge = Path(self.temp.name) / "huge.json"
        huge.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
        with self.assertRaisesRegex(Invalid, "import bound"):
            self._import_gsd(self.project_id, snapshot=huge)
        project_id = self.app.create_project(gsd_project())["project_id"]
        snapshot, plans = self._copy_gsd("unsafe")
        document = json.loads(snapshot.read_bytes())
        for plan_row in document["phases"][0]["plans"][0:1]:
            plan_row["plannedFiles"] = ["../secret"]
            plan_row["tasks"][0]["plannedFiles"] = ["../secret"]
        encoded = json.dumps(document).encode()
        snapshot.write_bytes(encoded)
        unsafe = plans / "01-01-PLAN.md"
        unsafe.write_bytes(
            unsafe.read_bytes()
            .replace(
                b'["src/validate.js", "test/validate.test.js"]',
                b'["../secret"]',
                1,
            )
            .replace(
                b"<files>src/validate.js, test/validate.test.js</files>",
                b"<files>../secret</files>",
                1,
            )
        )
        with self.assertRaisesRegex(Invalid, "allowed paths"):
            self._import_gsd(
                project_id,
                snapshot=snapshot,
                plans=plans,
                snapshot_digest=hashlib.sha256(encoded).hexdigest(),
            )
        self.assertEqual(self._plan_count(), 0)

    def test_service_principal_cannot_import_gsd(self):
        service = Coordinator(self.store, Principal("scripted-service", "service"))
        with self.assertRaisesRegex(Invalid, "developer"):
            service.import_gsd(
                self.project_id,
                "M-CLI1",
                GSD_SNAPSHOT,
                GSD_SNAPSHOT_SHA256,
                GSD_PLANS,
                expected_project_version=1,
                baseline_revision="b" * 40,
                max_attempts=1,
                check_timeout_seconds=1,
            )
        self.assertEqual(self._plan_count(), 0)

    def test_cli_plan_import_gsd_prints_the_submit_result(self):
        database = Path(self.temp.name) / "cli.sqlite"
        Store.create(database).close()
        spec_path = Path(self.temp.name) / "gsd-project.json"
        spec_path.write_text(json.dumps(gsd_project()), encoding="utf-8")
        argv = [sys.executable, "-m", "coordinator", "--db", str(database)]
        created = subprocess.run(
            [*argv, "project-create", str(spec_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
        project_id = json.loads(created.stdout)["result"]["project_id"]
        imported = subprocess.run(
            [
                *argv,
                "plan-import-gsd",
                project_id,
                "M-CLI1",
                str(GSD_SNAPSHOT),
                "--digest",
                GSD_SNAPSHOT_SHA256,
                "--plans",
                str(GSD_PLANS),
                "--expected-project-version",
                "1",
                "--baseline",
                "c" * 40,
                "--max-attempts",
                "2",
                "--check-timeout",
                "30",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(imported.returncode, 0, imported.stdout + imported.stderr)
        result = json.loads(imported.stdout)["result"]
        self.assertFalse(result["approved"])
        refused = subprocess.run(
            [
                *argv,
                "plan-import-gsd",
                project_id,
                "M-CLI1",
                str(GSD_SNAPSHOT),
                "--digest",
                "0" * 64,
                "--plans",
                str(GSD_PLANS),
                "--expected-project-version",
                "1",
                "--baseline",
                "c" * 40,
                "--max-attempts",
                "2",
                "--check-timeout",
                "30",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(refused.returncode, 2)
        self.assertEqual(json.loads(refused.stdout)["error"], "Invalid")
        status = subprocess.run(
            [*argv, "status", project_id],
            capture_output=True,
            text=True,
            check=True,
        )
        body = json.loads(status.stdout)["result"]
        self.assertEqual(len(body["plans"]), 1)
        self.assertEqual(body["plans"][0]["digest"], result["digest"])
        self.assertFalse(body["capabilities"]["task_acceptance"])
        self.assertFalse(body["live_eligible"])


if __name__ == "__main__":
    unittest.main()
