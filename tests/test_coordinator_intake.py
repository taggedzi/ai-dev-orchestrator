"""Durable source intake and explicit migration with real SQLite/Git effects."""

import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from coordinator import Conflict, Coordinator, Invalid, Principal, Store
from coordinator.evidence import EvidenceStore
from coordinator.intake import CandidateIntake
from coordinator.source import Snapshot, SourceFile, TrustedRepository
from coordinator.store import (
    APPLICATION_ID,
    SCHEMA_V1,
    SCHEMA_V2,
    SCHEMA_V3,
    SCHEMA_V4,
    SCHEMA_V5,
    SCHEMA_V6,
    archive_connection,
    patched_sqlite,
)
from tests.test_coordinator import plan, project


@unittest.skipUnless(
    patched_sqlite() and shutil.which("git"), "needs patched SQLite and installed Git"
)
class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store.create(self.root / "state.sqlite")
        self.addCleanup(self.store.close)
        self.dev = Coordinator(self.store, Principal("developer"))
        self.service = Coordinator(self.store, Principal("local-intake", "service"))
        self.repo = TrustedRepository.create(self.root / "managed")
        self.artifacts = EvidenceStore.create(self.root / "artifacts")
        baseline = self.repo.baseline(
            Snapshot(
                {
                    "src/example.py": SourceFile(b"baseline\r\n"),
                    "README.md": SourceFile(b"unchanged"),
                }
            )
        )
        self.project_id = self.dev.create_project(project())["project_id"]
        spec = plan()
        spec["baseline_revision"] = baseline["revision"]
        submitted = self.dev.submit_plan(
            self.project_id, "M1", spec, expected_project_version=1
        )
        approved = self.dev.approve_plan(
            submitted["plan_id"],
            submitted["digest"],
            expected_project_version=1,
            expected_milestone_version=1,
        )
        self.pv, self.mv = approved["project_version"], approved["milestone_version"]
        attempt = self.dev.claim_task(
            self.project_id,
            "M1",
            "T1",
            expected_project_version=self.pv,
            expected_milestone_version=self.mv,
        )
        self.attempt_id = attempt["attempt_id"]
        self.dev.start_scripted(self.attempt_id, expected_version=1)
        self.dev.record_scripted_result(
            attempt["operation_id"],
            "candidate",
            detail="Implementer conclusions must not appear in the review packet",
        )
        self.version = self.dev.status(self.project_id)["attempts"][0]["version"]
        self.snapshot = Snapshot(
            {
                "src/example.py": SourceFile(b"candidate\r\n\0binary"),
                "README.md": SourceFile(b"unchanged"),
            }
        )
        self.intake = CandidateIntake(self.service, self.repo, self.artifacts)

    def prepare(self, **kwargs):
        return self.intake.prepare(
            self.attempt_id,
            self.snapshot,
            expected_attempt_version=self.version,
            **kwargs,
        )

    def test_packet_is_exact_durable_and_never_accepts_scripted_task(self):
        prepared = self.prepare()
        outcome = self.intake.run(prepared["intake_id"], expected_version=1)
        self.assertTrue(outcome["current"])
        self.assertFalse(outcome["task_accepted"])
        packet = json.loads(self.artifacts.read(outcome["review_packet"]["sha256"]))
        self.assertEqual(packet["contract"]["task"]["id"], "T1")
        self.assertEqual(packet["contract"]["attempt_id"], self.attempt_id)
        self.assertEqual(packet["source_manifest"], self.snapshot.manifest)
        self.assertEqual(packet["candidate"]["revision"], outcome["revision"])
        self.assertNotIn("Implementer conclusions", json.dumps(packet))
        self.assertIsNone(packet["contract"]["native_stop_proof"])
        with Store(self.store.path) as reopened:
            status = Coordinator(reopened, Principal("reader")).status(self.project_id)
        self.assertEqual(
            status["candidate_intakes"][0]["receipt"]["candidate"]["revision"],
            outcome["revision"],
        )
        self.assertEqual(
            [t["state"] for t in status["milestones"][0]["tasks"]],
            ["awaiting_verification", "blocked_dependencies"],
        )
        replay = self.intake.reconcile(prepared["intake_id"])
        self.assertTrue(replay["duplicate"])
        self.assertEqual(
            self.store.db.execute(
                "SELECT COUNT(*) FROM intake_observations"
            ).fetchone()[0],
            1,
        )

    def test_ack_loss_dedupe_and_pause_prevent_late_dispatch(self):
        prepared = self.prepare(command_id="prepare-once")
        self.dev.pause(
            self.project_id, expected_version=self.pv, reason="pause before Git"
        )
        self.assertEqual(self.prepare(command_id="prepare-once"), prepared)
        with (
            patch.object(
                self.repo, "seal", side_effect=AssertionError("must not dispatch")
            ),
            self.assertRaises(Conflict),
        ):
            self.intake.run(prepared["intake_id"], expected_version=1)
        row = self.store.db.execute("SELECT * FROM candidate_intakes").fetchone()
        self.assertIsNone(row["sent_ns"])
        with self.assertRaises(Conflict):
            self.intake.reconcile(prepared["intake_id"])

    def test_missing_ref_after_possible_send_is_held_without_replay(self):
        prepared = self.prepare()
        self.intake.begin(prepared["intake_id"], expected_version=1)
        with (
            patch.object(self.repo, "seal", side_effect=AssertionError("no retry")),
            self.assertRaises(Conflict),
        ):
            self.intake.reconcile(prepared["intake_id"])
        self.assertEqual(
            self.dev.status(self.project_id)["candidate_intakes"][0]["state"], "held"
        )
        self.assertEqual(
            len(
                self.repo._run(
                    "for-each-ref", "--format=%(refname)"
                ).stdout.splitlines()
            ),
            1,
        )

    def test_real_child_exit_after_ref_write(self):
        prepared = self.prepare()
        program = """
import os,sys
from coordinator import Coordinator,Principal,Store
from coordinator.evidence import EvidenceStore
from coordinator.source import TrustedRepository
from coordinator.intake import CandidateIntake
with Store(sys.argv[1]) as store:
    intake=CandidateIntake(Coordinator(store,Principal("local-intake","service")),TrustedRepository(sys.argv[2]),EvidenceStore(sys.argv[3]))
    intake.begin(sys.argv[4],expected_version=1)
    row,contract,snapshot=intake._load(sys.argv[4])
    intake.repo.seal(contract["input_revision"],snapshot,allowed_paths=contract["task"]["allowed_paths"],binding=intake._binding(contract))
    os._exit(29)
"""
        child = subprocess.run(
            [
                sys.executable,
                "-c",
                program,
                str(self.store.path),
                str(self.repo.root),
                str(self.artifacts.root),
                prepared["intake_id"],
            ],
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(child.returncode, 29, child.stderr)
        self.assertEqual(
            self.dev.status(self.project_id)["candidate_intakes"][0]["state"],
            "possible_send",
        )
        with patch.object(
            self.repo, "seal", side_effect=AssertionError("read only reconciliation")
        ):
            recovered = self.intake.reconcile(prepared["intake_id"])
        self.assertTrue(recovered["current"])
        self.assertEqual(recovered["state"], "sealed")

    def test_pause_after_effect_retains_fenced_observation(self):
        prepared = self.prepare()
        self.intake.begin(prepared["intake_id"], expected_version=1)
        _, contract, snapshot = self.intake._load(prepared["intake_id"])
        self.repo.seal(
            contract["input_revision"],
            snapshot,
            allowed_paths=contract["task"]["allowed_paths"],
            binding=self.intake._binding(contract),
        )
        paused = self.dev.pause(
            self.project_id,
            expected_version=self.pv,
            reason="revoke before observation",
        )
        result = self.intake.reconcile(prepared["intake_id"])
        self.assertFalse(result["current"])
        self.assertEqual(result["state"], "held")
        self.dev.resume(self.project_id, expected_version=paused["version"])
        self.assertFalse(self.intake.reconcile(prepared["intake_id"])["current"])

    def test_real_child_exit_before_git_never_replays_missing_effect(self):
        prepared = self.prepare()
        program = """
import os,sys
from coordinator import Coordinator,Principal,Store
from coordinator.evidence import EvidenceStore
from coordinator.source import TrustedRepository
from coordinator.intake import CandidateIntake
with Store(sys.argv[1]) as store:
    intake=CandidateIntake(Coordinator(store,Principal("local-intake","service")),TrustedRepository(sys.argv[2]),EvidenceStore(sys.argv[3]))
    intake.begin(sys.argv[4],expected_version=1)
    os._exit(29)
"""
        child = subprocess.run(
            [
                sys.executable,
                "-c",
                program,
                str(self.store.path),
                str(self.repo.root),
                str(self.artifacts.root),
                prepared["intake_id"],
            ],
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(child.returncode, 29, child.stderr)
        with (
            patch.object(
                self.repo, "seal", side_effect=AssertionError("no blind replay")
            ),
            self.assertRaises(Conflict),
        ):
            self.intake.reconcile(prepared["intake_id"])
        self.assertEqual(
            self.dev.status(self.project_id)["candidate_intakes"][0]["state"], "held"
        )

    def test_changed_ref_holds_the_previously_sealed_candidate(self):
        prepared = self.prepare()
        sealed = self.intake.run(prepared["intake_id"], expected_version=1)
        receipt = self.dev.status(self.project_id)["candidate_intakes"][0]["receipt"]
        self.repo._run(
            "update-ref",
            receipt["candidate"]["ref"],
            receipt["candidate"]["input_revision"],
            sealed["revision"],
        )
        with self.assertRaises(Conflict):
            self.intake.reconcile(prepared["intake_id"])
        status = self.dev.status(self.project_id)
        self.assertFalse(status["candidate_intakes"][0]["current"])
        self.assertEqual(
            status["candidate_intakes"][0]["receipt"]["candidate"]["revision"],
            sealed["revision"],
        )
        self.assertEqual(
            status["milestones"][0]["tasks"][1]["state"], "blocked_dependencies"
        )

    def test_requirements_revision_invalidates_the_review_packet(self):
        prepared = self.prepare()
        sealed = self.intake.run(prepared["intake_id"], expected_version=1)
        changed = project()
        changed["requirements"][0]["text"] = "Revised behavior"
        self.dev.revise_project(self.project_id, changed, expected_version=self.pv)
        result = self.intake.reconcile(prepared["intake_id"])
        self.assertFalse(result["current"])
        packet = json.loads(self.artifacts.read(sealed["review_packet"]["sha256"]))
        self.assertEqual(packet["contract"]["project_revision"], 1)
        self.assertEqual(self.dev.status(self.project_id)["project"]["revision"], 2)

    def test_source_or_controller_substitution_refuses(self):
        prepared = self.prepare()
        changed = self.snapshot.files()
        changed["src/example.py"] = SourceFile(b"other")
        with self.assertRaises(Conflict):
            self.intake.prepare(
                self.attempt_id,
                Snapshot(changed),
                expected_attempt_version=self.version,
            )
        other = CandidateIntake(
            Coordinator(self.store, Principal("other-controller", "service")),
            self.repo,
            self.artifacts,
        )
        with self.assertRaises(Conflict):
            other.begin(prepared["intake_id"], expected_version=1)
        with self.assertRaises(Invalid):
            CandidateIntake(self.dev, self.repo, self.artifacts)
        blob = self.snapshot.manifest[0]["sha256"]
        (self.artifacts.root / blob).write_bytes(b"tampered")
        with self.assertRaises(Conflict):
            self.intake.run(prepared["intake_id"], expected_version=1)
        self.assertEqual(
            self.dev.status(self.project_id)["candidate_intakes"][0]["state"], "held"
        )

    def test_competing_connections_admit_one_dispatch(self):
        prepared = self.prepare()
        barrier = threading.Barrier(2)

        def begin():
            with Store(self.store.path) as store:
                controller = CandidateIntake(
                    Coordinator(store, Principal("local-intake", "service")),
                    self.repo,
                    self.artifacts,
                )
                barrier.wait(timeout=5)
                try:
                    controller.begin(prepared["intake_id"], expected_version=1)
                    return "admitted"
                except Conflict:
                    return "refused"

        with ThreadPoolExecutor(max_workers=2) as workers:
            self.assertCountEqual(
                list(workers.map(lambda _: begin(), range(2))), ["admitted", "refused"]
            )

    def test_slow_preflight_does_not_hold_sqlite_writer_and_rechecks_authority(self):
        original = self.repo.candidate_intent

        def preflight(*args, **kwargs):
            with Store(self.store.path) as store:
                Coordinator(store, Principal("developer")).pause(
                    self.project_id,
                    expected_version=self.pv,
                    reason="changed during preflight",
                )
            return original(*args, **kwargs)

        with (
            patch.object(self.repo, "candidate_intent", side_effect=preflight),
            self.assertRaises(Conflict),
        ):
            self.prepare()
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM candidate_intakes").fetchone()[
                0
            ],
            0,
        )


@unittest.skipUnless(patched_sqlite(), "requires patched SQLite")
class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "v1.sqlite"
        with closing(sqlite3.connect(self.path, autocommit=True)) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("BEGIN IMMEDIATE")
            for statement in SCHEMA_V1:
                db.execute(statement)
            db.execute("INSERT INTO meta VALUES('archive','0')")
            db.execute(
                "INSERT INTO meta VALUES('primary_path',?)", (str(self.path.resolve()),)
            )
            db.execute("INSERT INTO projects VALUES('historical',3,1,2,1)")
            db.execute(f"PRAGMA application_id={APPLICATION_ID}")
            db.execute("PRAGMA user_version=1")
            db.execute("COMMIT")

    def test_explicit_migration_preserves_state_and_archives_before_change(self):
        with self.assertRaisesRegex(Invalid, "migration"):
            Store(self.path)
        outcome = Store.migrate(self.path, self.root / "archive.sqlite")
        self.assertEqual(outcome["schema"], 7)
        with Store(self.path) as store:
            self.assertEqual(
                tuple(
                    store.db.execute(
                        "SELECT version,generation,paused FROM projects"
                    ).fetchone()
                ),
                (3, 2, 1),
            )
            self.assertEqual(
                store.db.execute("SELECT COUNT(*) FROM candidate_intakes").fetchone()[
                    0
                ],
                0,
            )
            self.assertEqual(
                store.db.execute(
                    "SELECT COUNT(*) FROM integration_head_mappings"
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                store.db.execute(
                    "SELECT COUNT(*) FROM integration_promotions"
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                store.db.execute("SELECT COUNT(*) FROM model_policies").fetchone()[0],
                0,
            )
        with closing(sqlite3.connect(self.root / "archive.sqlite")) as archive:
            self.assertEqual(archive.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(
                archive.execute(
                    "SELECT value FROM meta WHERE key='archive'"
                ).fetchone()[0],
                "1",
            )
        with self.assertRaises(Invalid):
            Store.migrate(self.root / "archive.sqlite", self.root / "forbidden.sqlite")

    def test_copy_cannot_migrate_or_replace_existing_backup(self):
        copied = self.root / "copy.sqlite"
        shutil.copyfile(self.path, copied)
        with self.assertRaises(Invalid):
            Store.migrate(copied, self.root / "copied-backup.sqlite")
        backup = self.root / "existing"
        backup.write_bytes(b"preserve me")
        with self.assertRaises(FileExistsError):
            Store.migrate(self.path, backup)
        self.assertEqual(backup.read_bytes(), b"preserve me")

    def test_concurrent_write_during_backup_refuses_schema_change(self):
        def capture(source, output):
            result = archive_connection(source, output)
            with closing(sqlite3.connect(self.path, autocommit=True)) as writer:
                writer.execute("UPDATE projects SET version=4")
            return result

        with (
            patch("coordinator.store.archive_connection", side_effect=capture),
            self.assertRaises(Conflict),
        ):
            Store.migrate(self.path, self.root / "captured.sqlite")
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(
                db.execute("SELECT version FROM projects").fetchone()[0], 4
            )

    def test_ddl_failure_rolls_back_schema_with_backup_retained(self):
        with (
            patch.dict(
                "coordinator.store.MIGRATIONS",
                {1: ("CREATE TABLE migration_probe(id)", "INVALID SQL")},
            ),
            self.assertRaises(sqlite3.Error),
        ):
            Store.migrate(self.path, self.root / "archive.sqlite")
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertIsNone(
                db.execute(
                    "SELECT 1 FROM sqlite_master WHERE name='migration_probe'"
                ).fetchone()
            )
        self.assertTrue((self.root / "archive.sqlite").exists())

    def test_v2_upgrade_preserves_unsettled_candidate_and_missing_identity(self):
        path = self.root / "v2.sqlite"
        with closing(sqlite3.connect(path, autocommit=True)) as db:
            db.execute("PRAGMA journal_mode=WAL")
            for statement in SCHEMA_V2:
                db.execute(statement)
            db.execute("INSERT INTO meta VALUES('archive','0')")
            db.execute(
                "INSERT INTO meta VALUES('primary_path',?)", (str(path.resolve()),)
            )
            db.execute("INSERT INTO projects VALUES('p',3,1,2,1)")
            db.execute(
                "INSERT INTO milestones VALUES('m','p','M1',2,'plan',?)", ("a" * 40,)
            )
            db.execute("INSERT INTO plans VALUES('plan','m',1,'{}',?)", ("b" * 64,))
            db.execute(
                "INSERT INTO attempts VALUES('a','m','plan','T1',2,4,'held','scripted',?,'{}')",
                ("a" * 40,),
            )
            db.execute(
                "INSERT INTO candidate_intakes VALUES('i','a','p','old-controller',3,'held','{}',?,NULL,NULL,1,1)",
                ("c" * 64,),
            )
            db.execute(f"PRAGMA application_id={APPLICATION_ID}")
            db.execute("PRAGMA user_version=2")
        Store.migrate(path, self.root / "v2-archive.sqlite")
        with Store(path) as migrated:
            self.assertEqual(
                tuple(
                    migrated.db.execute(
                        "SELECT state,contract FROM candidate_intakes"
                    ).fetchone()
                ),
                ("held", "{}"),
            )
            self.assertEqual(
                migrated.db.execute("SELECT assignment FROM attempts").fetchone()[0],
                "{}",
            )
            self.assertEqual(
                migrated.db.execute(
                    "SELECT COUNT(*) FROM verification_policies"
                ).fetchone()[0],
                0,
            )

    def test_v3_upgrade_preserves_pending_verification_without_stage_authority(self):
        path = self.root / "v3.sqlite"
        with closing(sqlite3.connect(path, autocommit=True)) as db:
            db.execute("PRAGMA journal_mode=WAL")
            for statement in SCHEMA_V3:
                db.execute(statement)
            db.execute("INSERT INTO meta VALUES('archive','0')")
            db.execute(
                "INSERT INTO meta VALUES('primary_path',?)", (str(path.resolve()),)
            )
            db.execute("INSERT INTO projects VALUES('p',3,1,2,1)")
            db.execute(
                "INSERT INTO milestones VALUES('m','p','M1',2,'plan',?)", ("a" * 40,)
            )
            db.execute("INSERT INTO plans VALUES('plan','m',1,'{}',?)", ("b" * 64,))
            db.execute(
                "INSERT INTO attempts VALUES('a','m','plan','T1',2,4,'held','scripted',?,'{}')",
                ("a" * 40,),
            )
            db.execute(
                "INSERT INTO candidate_intakes VALUES('i','a','p','old-controller',3,'held','{}',?,NULL,NULL,1,1)",
                ("c" * 64,),
            )
            db.execute(
                "INSERT INTO verification_policies VALUES('vp','i',?,'{}','owner','old-review-session',1)",
                ("d" * 64,),
            )
            db.execute(
                "INSERT INTO verification_operations(id,intake_id,policy_id,kind,key,scheduler,producer,version,state,binding,sent_ns,created_ns) VALUES('vo','i','vp','check','unit','scheduler','checker',2,'possible_send','{}',1,1)"
            )
            db.execute(f"PRAGMA application_id={APPLICATION_ID}")
            db.execute("PRAGMA user_version=3")
        Store.migrate(path, self.root / "v3-archive.sqlite")
        with Store(path) as migrated:
            self.assertEqual(
                tuple(
                    migrated.db.execute(
                        "SELECT state,sent_ns FROM verification_operations"
                    ).fetchone()
                ),
                ("possible_send", 1),
            )
            self.assertEqual(
                migrated.db.execute(
                    "SELECT COUNT(*) FROM integration_proposals"
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                migrated.db.execute(
                    "SELECT COUNT(*) FROM integration_head_mappings"
                ).fetchone()[0],
                0,
            )

    def test_v4_upgrade_preserves_proposal_without_head_authority(self):
        path = self.root / "v4.sqlite"
        with closing(sqlite3.connect(path, autocommit=True)) as db:
            db.execute("PRAGMA journal_mode=WAL")
            for statement in SCHEMA_V4:
                db.execute(statement)
            db.execute("INSERT INTO meta VALUES('archive','0')")
            db.execute(
                "INSERT INTO meta VALUES('primary_path',?)", (str(path.resolve()),)
            )
            db.execute("INSERT INTO projects VALUES('p',3,1,2,1)")
            db.execute(
                "INSERT INTO milestones VALUES('m','p','M1',2,'plan',?)", ("a" * 40,)
            )
            db.execute("INSERT INTO plans VALUES('plan','m',1,'{}',?)", ("b" * 64,))
            db.execute(
                "INSERT INTO attempts VALUES('a','m','plan','T1',2,4,'held','scripted',?,'{}')",
                ("a" * 40,),
            )
            db.execute(
                "INSERT INTO candidate_intakes VALUES('i','a','p','old-controller',3,'held','{}',?,NULL,NULL,1,1)",
                ("c" * 64,),
            )
            db.execute(
                "INSERT INTO integration_proposals(id,intake_id,project_id,producer,version,state,intent,created_ns) VALUES('ip','i','p','old-controller',1,'prepared','{}',1)"
            )
            db.execute(f"PRAGMA application_id={APPLICATION_ID}")
            db.execute("PRAGMA user_version=4")
        Store.migrate(path, self.root / "v4-archive.sqlite")
        with Store(path) as migrated:
            self.assertEqual(
                tuple(
                    migrated.db.execute(
                        "SELECT state,intent FROM integration_proposals"
                    ).fetchone()
                ),
                ("prepared", "{}"),
            )
            self.assertEqual(
                migrated.db.execute(
                    "SELECT COUNT(*) FROM integration_head_mappings"
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                migrated.db.execute("SELECT settled FROM attempts").fetchone()[0], 0
            )

    def test_v5_upgrade_preserves_mapping_without_promotion(self):
        path = self.root / "v5.sqlite"
        with closing(sqlite3.connect(path, autocommit=True)) as db:
            db.execute("PRAGMA journal_mode=WAL")
            for statement in SCHEMA_V5:
                db.execute(statement)
            db.execute("INSERT INTO meta VALUES('archive','0')")
            db.execute(
                "INSERT INTO meta VALUES('primary_path',?)", (str(path.resolve()),)
            )
            db.execute("INSERT INTO projects VALUES('p',3,1,2,1)")
            db.execute(
                "INSERT INTO milestones VALUES('m','p','M1',2,'plan',?)", ("a" * 40,)
            )
            db.execute("INSERT INTO plans VALUES('plan','m',1,'{}',?)", ("b" * 64,))
            db.execute(
                "INSERT INTO attempts VALUES('a','m','plan','T1',2,4,'held','scripted',?,'{}')",
                ("a" * 40,),
            )
            db.execute(
                "INSERT INTO candidate_intakes VALUES('i','a','p','old-controller',3,'held','{}',?,NULL,NULL,1,1)",
                ("c" * 64,),
            )
            db.execute(
                "INSERT INTO integration_proposals(id,intake_id,project_id,producer,version,state,intent,created_ns) VALUES('ip','i','p','old-controller',1,'prepared','{}',1)"
            )
            db.execute(
                "INSERT INTO integration_head_mappings(id,attempt_id,project_id,previous_head,new_head,authority_generation,authorization_digest,actor,state,created_ns) VALUES('map','a','p',?,?,1,?,'owner','authorized',1)",
                ("a" * 40, "b" * 40, "d" * 64),
            )
            db.execute(f"PRAGMA application_id={APPLICATION_ID}")
            db.execute("PRAGMA user_version=5")
        Store.migrate(path, self.root / "v5-archive.sqlite")
        with Store(path) as migrated:
            self.assertEqual(
                tuple(
                    migrated.db.execute(
                        "SELECT state,intent FROM integration_proposals"
                    ).fetchone()
                ),
                ("prepared", "{}"),
            )
            self.assertEqual(
                tuple(
                    migrated.db.execute(
                        "SELECT m.state,m.consumed_by,a.settled FROM integration_head_mappings m JOIN attempts a ON a.id=m.attempt_id"
                    ).fetchone()
                ),
                ("authorized", None, 0),
            )
            self.assertEqual(
                migrated.db.execute(
                    "SELECT COUNT(*) FROM integration_promotions"
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                migrated.db.execute("SELECT COUNT(*) FROM model_policies").fetchone()[
                    0
                ],
                0,
            )

    def test_v6_upgrade_preserves_promotion_without_model_policy(self):
        path = self.root / "v6.sqlite"
        with closing(sqlite3.connect(path, autocommit=True)) as db:
            db.execute("PRAGMA journal_mode=WAL")
            for statement in SCHEMA_V6:
                db.execute(statement)
            db.execute("INSERT INTO meta VALUES('archive','0')")
            db.execute(
                "INSERT INTO meta VALUES('primary_path',?)", (str(path.resolve()),)
            )
            db.execute("INSERT INTO projects VALUES('p',3,1,2,1)")
            db.execute(
                "INSERT INTO milestones VALUES('m','p','M1',2,'plan',?)", ("a" * 40,)
            )
            db.execute("INSERT INTO plans VALUES('plan','m',1,'{}',?)", ("b" * 64,))
            db.execute(
                "INSERT INTO attempts VALUES('a','m','plan','T1',2,4,'awaiting_verification','scripted',?,?,1)",
                ("a" * 40, "{}"),
            )
            db.execute(
                "INSERT INTO candidate_intakes VALUES('i','a','p','old-controller',3,'held','{}',?,NULL,NULL,1,1)",
                ("c" * 64,),
            )
            db.execute(
                "INSERT INTO integration_proposals(id,intake_id,project_id,producer,version,state,intent,created_ns) VALUES('ip','i','p','old-controller',1,'staged','{}',1)"
            )
            db.execute(
                "INSERT INTO integration_promotions(id,proposal_id,project_id,milestone_id,attempt_id,plan_id,task_key,expected_head,integrated_revision,expected_milestone_version,evidence_digest,evidence,version,state,created_ns) VALUES('promo','ip','p','m','a','plan','T1',?,?,1,?,'{}',1,'promoted',1)",
                ("a" * 40, "b" * 40, "d" * 64),
            )
            db.execute(f"PRAGMA application_id={APPLICATION_ID}")
            db.execute("PRAGMA user_version=6")
        Store.migrate(path, self.root / "v6-archive.sqlite")
        with Store(path) as migrated:
            self.assertEqual(
                tuple(
                    migrated.db.execute(
                        "SELECT state,integrated_revision,attempt_id FROM integration_promotions"
                    ).fetchone()
                ),
                ("promoted", "b" * 40, "a"),
            )
            self.assertEqual(
                migrated.db.execute("SELECT settled FROM attempts").fetchone()[0], 1
            )
            self.assertEqual(
                migrated.db.execute("SELECT COUNT(*) FROM model_policies").fetchone()[
                    0
                ],
                0,
            )
            self.assertEqual(
                migrated.db.execute("SELECT COUNT(*) FROM model_permits").fetchone()[0],
                0,
            )


if __name__ == "__main__":
    unittest.main()
