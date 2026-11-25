"""Real Git staging/CAS and durable scripted integration regression gates."""

import json
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from coordinator import Conflict, Coordinator, Invalid, Principal, Store
from coordinator.domain import canonical, digest
from coordinator.integration import Integration
from coordinator.source import CandidateBinding, Snapshot, SourceFile, TrustedRepository
from coordinator.store import patched_sqlite
from coordinator.verification import DIMENSIONS
from tests import test_coordinator_verification as verification_fixture


@unittest.skipUnless(shutil.which("git"), "requires installed Git")
class SourceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = TrustedRepository.create(self.root / "managed")
        self.files = {
            "src/a.txt": SourceFile(b"base\n"),
            "head.txt": SourceFile(b"head base\n"),
        }
        self.base = self.repo.baseline(Snapshot(self.files))["revision"]
        files = {**self.files, "src/a.txt": SourceFile(b"candidate\n")}
        self.candidate = self.repo.seal(
            self.base,
            Snapshot(files),
            allowed_paths=["src/a.txt"],
            binding=CandidateBinding("candidate", "a" * 64, "b" * 64, 1),
        )["revision"]

    def head(self, *, conflict=False):
        files = {**self.files}
        path = "src/a.txt" if conflict else "head.txt"
        files[path] = SourceFile(b"head advance\n")
        return self.repo.seal(
            self.base,
            Snapshot(files),
            allowed_paths=[path],
            binding=CandidateBinding("head", "a" * 64, "c" * 64, 1),
        )["revision"]

    def stage(self, head=None, **kwargs):
        return self.repo.stage_integration(
            self.candidate,
            head or self.base,
            proposal_id="proposal",
            authorization_digest="d" * 64,
            allowed_paths=["src/a.txt"],
            **kwargs,
        )

    def test_direct_stage_keeps_candidate_and_binds_authorization(self):
        staged = self.stage()
        self.assertEqual(staged["revision"], self.candidate)
        self.assertEqual(staged["parents"], [self.base])
        self.assertFalse(staged["task_accepted"])
        self.assertEqual(
            self.repo.observe_integration(
                self.candidate,
                self.base,
                proposal_id="proposal",
                authorization_digest="d" * 64,
                allowed_paths=["src/a.txt"],
            ),
            staged,
        )
        with self.assertRaises(Conflict):
            self.repo.stage_integration(
                self.candidate,
                self.base,
                proposal_id="proposal",
                authorization_digest="e" * 64,
                allowed_paths=["src/a.txt"],
            )

    def test_clean_merge_has_ordered_parents_and_scoped_effective_diff(self):
        head = self.head()
        staged = self.stage(head)
        self.assertNotEqual(staged["revision"], self.candidate)
        self.assertEqual(staged["parents"], [head, self.candidate])
        self.assertEqual(staged["changed_paths"], ["src/a.txt"])
        files = self.repo.snapshot(staged["revision"]).files()
        self.assertEqual(files["head.txt"].data, b"head advance\n")
        self.assertEqual(files["src/a.txt"].data, b"candidate\n")

    def test_conflicting_merge_never_retains_conflict_tree_as_proposal(self):
        with self.assertRaises(Conflict):
            self.stage(self.head(conflict=True))
        refs = self.repo._run("for-each-ref", "--format=%(refname)").stdout.decode()
        self.assertNotIn("/integrations/", refs)
        self.assertNotIn("/integration-intents/", refs)

    def test_scope_violation_refuses_before_private_proposal_is_retained(self):
        with self.assertRaises(Conflict):
            self.repo.stage_integration(
                self.candidate,
                self.base,
                proposal_id="outside",
                authorization_digest="d" * 64,
                allowed_paths=["head.txt"],
            )
        self.assertNotIn(
            b"/integrations/",
            self.repo._run("for-each-ref", "--format=%(refname)").stdout,
        )

    def test_expected_head_guard_rejects_race_and_never_claims_duplicate_write(self):
        self.assertTrue(
            self.repo.update_validation_ref("fixture", None, self.base)[
                "guard_accepted"
            ]
        )
        head = self.head()
        self.assertTrue(
            self.repo.update_validation_ref("fixture", self.base, head)[
                "guard_accepted"
            ]
        )
        stale = self.repo.update_validation_ref("fixture", self.base, self.candidate)
        self.assertFalse(stale["guard_accepted"])
        self.assertEqual(stale["observed_revision"], head)
        self.assertTrue(
            self.repo.update_validation_ref("fixture", head, self.candidate)[
                "guard_accepted"
            ]
        )
        duplicate = self.repo.update_validation_ref("fixture", head, self.candidate)
        self.assertFalse(duplicate["guard_accepted"])
        self.assertFalse(duplicate["task_accepted"])

    def test_milestone_ref_is_created_once_and_is_not_a_validation_ref(self):
        created = self.repo.advance_milestone_ref("milestone", None, self.candidate)
        self.assertTrue(created["guard_accepted"])
        self.assertTrue(created["created"])
        self.assertFalse(created["task_accepted"])
        again = self.repo.advance_milestone_ref("milestone", self.base, self.candidate)
        self.assertFalse(again["guard_accepted"])
        self.assertEqual(again["observed_revision"], self.candidate)
        self.assertEqual(
            self.repo.observe_milestone_ref("milestone", self.candidate)[
                "observed_revision"
            ],
            self.candidate,
        )
        with self.assertRaises(Conflict):
            self.repo.advance_milestone_ref("milestone", self.base, self.head())
        with self.assertRaises(Conflict):
            self.repo.observe_milestone_ref("missing", self.candidate)
        refs = self.repo._run("for-each-ref", "--format=%(refname)").stdout.decode()
        self.assertIn("refs/orchestrator/milestones/milestone", refs)
        self.assertNotIn("refs/orchestrator/validation/", refs)
        self.assertNotIn("refs/heads/", refs)

    def test_process_exit_after_validation_ref_write_does_not_replay_guard(self):
        self.repo.update_validation_ref("fault", None, self.base)
        program = """
import os,sys
from coordinator.source import TrustedRepository
repo=TrustedRepository(sys.argv[1])
result=repo.update_validation_ref("fault",sys.argv[2],sys.argv[3])
assert result["guard_accepted"]
os._exit(29)
"""
        child = subprocess.run(
            [
                sys.executable,
                "-c",
                program,
                str(self.repo.root),
                self.base,
                self.candidate,
            ],
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(child.returncode, 29, child.stderr)
        inspected = self.repo.update_validation_ref("fault", self.base, self.candidate)
        self.assertFalse(inspected["guard_accepted"])
        self.assertEqual(inspected["observed_revision"], self.candidate)


@unittest.skipUnless(
    patched_sqlite() and shutil.which("git"), "requires patched SQLite and Git"
)
class IntegrationTests(verification_fixture.VerificationFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        review = self.review()
        self.reviewer.submit(
            review["operation_id"], self.review_receipt(review["operation_id"])
        )
        self.controller = Integration(
            Coordinator(self.store, Principal("integration-controller", "service")),
            self.repo,
            self.artifacts,
        )
        self.integration_owner = Integration(self.dev, self.repo, self.artifacts)
        self.regression = Integration(
            Coordinator(self.store, Principal("regression-controller", "service")),
            self.repo,
            self.artifacts,
        )

    def stage(self):
        proposal = self.controller.prepare(self.intake_id)
        self.controller.run(proposal["proposal_id"], expected_version=1)
        return next(
            row
            for row in self.dev.status(self.project_id)["integration_proposals"]
            if row["id"] == proposal["proposal_id"]
        )

    def diverged_head(self):
        previous = self.dev.status(self.project_id)["milestones"][0]["head_revision"]
        revision = self.repo.seal(
            previous,
            Snapshot(
                {
                    "src/example.py": SourceFile(b"baseline\r\n"),
                    "README.md": SourceFile(b"head advance\n"),
                }
            ),
            allowed_paths=["README.md"],
            binding=CandidateBinding("headadvance", "a" * 64, "c" * 64, 1),
        )["revision"]
        return previous, revision

    def authorize_head(self, previous, new_head):
        generation = self.dev.status(self.project_id)["project"]["generation"]
        return self.integration_owner.authorize_diverged_head(
            self.attempt_id, previous, new_head, generation
        )

    def regression_job(self, proposal):
        profile = {
            "classification": "scripted_development",
            "checks": [
                {
                    "check_id": "regression",
                    "producer": "regression-controller",
                    "definition_digest": self.artifact(
                        {
                            "check": {
                                "id": "regression",
                                "argv": ["fixture-only-regression"],
                                "timeout_seconds": 30,
                            },
                            "cases": [
                                {
                                    "id": "repeated-input",
                                    "input": ["\t", "\t"],
                                    "expected": ["reject", "reject"],
                                }
                            ],
                        }
                    ),
                    "environment_digest": self.artifact(
                        {
                            "classification": "scripted_development",
                            "profile": "no process runs",
                        }
                    ),
                }
            ],
        }
        self.integration_owner.approve_regressions(
            proposal["id"],
            profile,
            digest(profile),
            expected_version=proposal["version"],
        )
        operation = self.controller.prepare_regressions(proposal["id"])["operations"][0]
        self.controller.begin_regression(operation["operation_id"], expected_version=1)
        return operation

    def regression_receipt(self, operation_id):
        row = next(
            row
            for row in self.dev.status(self.project_id)["integration_regressions"]
            if row["id"] == operation_id
        )
        binding = row["binding"]
        return {
            "binding_digest": digest(binding),
            "verdict": "pass",
            "details": {
                "source_digest": binding["source_digest"],
                "environment_digest": binding["profile"]["environment_digest"],
                "log_digest": self.artifact(
                    {"classification": "scripted_development", "log": "not executed"}
                ),
                "cases": [
                    {
                        "id": "repeated-input",
                        "status": "pass",
                        "observation_digest": self.artifact(
                            {
                                "classification": "scripted_development",
                                "observed": ["reject", "reject"],
                            }
                        ),
                    }
                ],
            },
        }

    def test_staged_subject_and_regressions_survive_restart_without_acceptance(self):
        proposal = self.stage()
        operation = self.regression_job(proposal)
        result = self.regression.submit_regression(
            operation["operation_id"],
            self.regression_receipt(operation["operation_id"]),
        )
        self.assertTrue(result["passed"])
        gate = self.controller.gate(proposal["id"])
        self.assertTrue(gate["development_ready_for_promotion"])
        self.assertFalse(gate["live_eligible"])
        self.assertFalse(gate["task_accepted"])
        with Store(self.store.path) as reopened:
            reader = Integration(
                Coordinator(reopened, Principal("developer")), self.repo, self.artifacts
            )
            self.assertEqual(reader.gate(proposal["id"]), gate)
        status = self.dev.status(self.project_id)
        self.assertEqual(
            status["milestones"][0]["tasks"][1]["state"], "blocked_dependencies"
        )
        self.assertEqual(
            status["milestones"][0]["head_revision"],
            proposal["intent"]["expected_head"],
        )

    def test_failed_regression_blocks_green_candidate(self):
        proposal = self.stage()
        operation = self.regression_job(proposal)
        receipt = self.regression_receipt(operation["operation_id"])
        receipt["verdict"] = "fail"
        receipt["details"]["cases"][0]["status"] = "fail"
        self.regression.submit_regression(operation["operation_id"], receipt)
        self.assertTrue(
            self.owner.gate(self.intake_id)["development_ready_for_integration"]
        )
        self.assertFalse(
            self.controller.gate(proposal["id"])["development_ready_for_promotion"]
        )

    def test_wrong_regression_binding_is_held(self):
        proposal = self.stage()
        operation = self.regression_job(proposal)
        receipt = self.regression_receipt(operation["operation_id"])
        receipt["binding_digest"] = "0" * 64
        result = self.regression.submit_regression(operation["operation_id"], receipt)
        self.assertFalse(result["passed"])
        self.assertEqual(result["state"], "held")

    def test_pause_retains_late_regression_without_reviving_proposal(self):
        proposal = self.stage()
        operation = self.regression_job(proposal)
        receipt = self.regression_receipt(operation["operation_id"])
        self.dev.pause(
            self.project_id, expected_version=self.pv, reason="pause integration"
        )
        self.assertFalse(
            self.regression.submit_regression(operation["operation_id"], receipt)[
                "current"
            ]
        )
        self.assertFalse(
            self.controller.gate(proposal["id"])["development_ready_for_promotion"]
        )

    def test_missing_stage_after_committed_send_is_held_without_replay(self):
        proposal = self.controller.prepare(self.intake_id)
        self.controller.begin(proposal["proposal_id"], expected_version=1)
        with (
            patch.object(
                self.repo,
                "stage_integration",
                side_effect=AssertionError("must not retry"),
            ),
            self.assertRaises(Conflict),
        ):
            self.controller.reconcile(proposal["proposal_id"])
        self.assertEqual(
            self.dev.status(self.project_id)["integration_proposals"][0]["state"],
            "held",
        )

    def test_actual_process_exit_after_stage_reconciles_read_only(self):
        proposal = self.controller.prepare(self.intake_id)
        program = """
import os,sys
from coordinator import Coordinator,Principal,Store
from coordinator.evidence import EvidenceStore
from coordinator.source import TrustedRepository
from coordinator.integration import Integration
with Store(sys.argv[1]) as store:
    controller=Integration(Coordinator(store,Principal("integration-controller","service")),TrustedRepository(sys.argv[2]),EvidenceStore(sys.argv[3]))
    controller.begin(sys.argv[4],expected_version=1)
    row=controller._proposal(sys.argv[4],owned=True)
    intent,args=controller._arguments(row)
    controller.repo.stage_integration(**args)
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
                proposal["proposal_id"],
            ],
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(child.returncode, 29, child.stderr)
        with patch.object(
            self.repo,
            "stage_integration",
            side_effect=AssertionError("read-only recovery"),
        ):
            recovered = self.controller.reconcile(proposal["proposal_id"])
        self.assertTrue(recovered["current"])
        self.assertFalse(recovered["task_accepted"])
        self.assertTrue(self.controller.reconcile(proposal["proposal_id"])["duplicate"])

    def test_competing_connections_admit_one_stage(self):
        proposal = self.controller.prepare(self.intake_id)
        barrier = threading.Barrier(2)

        def begin(_):
            with Store(self.store.path) as store:
                controller = Integration(
                    Coordinator(store, Principal("integration-controller", "service")),
                    self.repo,
                    self.artifacts,
                )
                barrier.wait(timeout=5)
                try:
                    controller.begin(proposal["proposal_id"], expected_version=1)
                    return "admitted"
                except Conflict:
                    return "refused"

        with ThreadPoolExecutor(max_workers=2) as workers:
            self.assertCountEqual(
                list(workers.map(begin, range(2))), ["admitted", "refused"]
            )

    def test_missing_original_source_artifact_invalidates_candidate_evidence(self):
        packet = json.loads(
            self.artifacts.read(self.candidate["receipt"]["review_packet"]["sha256"])
        )
        source = next(
            item
            for item in packet["input_source_manifest"]
            if item["path"] == "src/example.py"
        )
        (self.artifacts.root / source["sha256"]).write_bytes(b"changed")
        self.assertFalse(
            self.owner.gate(self.intake_id)["development_ready_for_integration"]
        )
        with self.assertRaises(Conflict):
            self.controller.prepare(self.intake_id)

    def test_conflicting_regression_fences_proposal_and_retains_both_observations(self):
        proposal = self.stage()
        operation = self.regression_job(proposal)
        receipt = self.regression_receipt(operation["operation_id"])
        self.regression.submit_regression(operation["operation_id"], receipt)
        self.assertTrue(
            self.regression.submit_regression(operation["operation_id"], receipt)[
                "duplicate"
            ]
        )
        receipt["verdict"] = "fail"
        conflict = self.regression.submit_regression(operation["operation_id"], receipt)
        self.assertTrue(conflict["conflicting"])
        status = self.dev.status(self.project_id)
        self.assertTrue(status["project"]["paused"])
        self.assertEqual(status["integration_proposals"][0]["state"], "held")
        self.assertEqual(
            self.store.db.execute(
                "SELECT COUNT(*) FROM integration_regression_observations"
            ).fetchone()[0],
            2,
        )

    def test_lost_prepare_ack_replays_record_but_cannot_dispatch_after_pause(self):
        prepared = self.controller.prepare(self.intake_id, command_id="prepare-once")
        self.dev.pause(
            self.project_id,
            expected_version=self.pv,
            reason="after committed preparation",
        )
        self.assertEqual(
            self.controller.prepare(self.intake_id, command_id="prepare-once"), prepared
        )
        with (
            patch.object(
                self.repo,
                "stage_integration",
                side_effect=AssertionError("no dispatch"),
            ),
            self.assertRaises(Conflict),
        ):
            self.controller.run(prepared["proposal_id"], expected_version=1)

    def test_missing_diverged_head_mapping_refuses_stage(self):
        previous, new_head = self.diverged_head()
        with self.assertRaisesRegex(Conflict, "diverged-head mapping missing"):
            self.controller.prepare(self.intake_id, expected_head=new_head)
        status = self.dev.status(self.project_id)
        self.assertEqual(status["integration_proposals"], [])
        self.assertEqual(status["integration_head_mappings"], [])
        self.assertEqual(status["milestones"][0]["head_revision"], previous)
        self.assertEqual(
            status["milestones"][0]["tasks"][1]["state"], "blocked_dependencies"
        )
        self.assertFalse(status["capabilities"]["task_acceptance"])

    def test_different_diverged_head_mapping_refuses_stage(self):
        previous, new_head = self.diverged_head()
        generation = self.dev.status(self.project_id)["project"]["generation"]
        with self.assertRaisesRegex(Conflict, "diverged-head mapping differs"):
            self.integration_owner.authorize_diverged_head(
                self.attempt_id, "b" * 40, new_head, generation
            )
        self.assertEqual(
            self.dev.status(self.project_id)["integration_head_mappings"], []
        )
        granted = self.authorize_head(previous, new_head)
        self.assertFalse(granted["consumed"])
        self.assertFalse(granted["task_accepted"])
        with self.assertRaisesRegex(Conflict, "diverged-head mapping differs"):
            self.controller.prepare(self.intake_id, expected_head="d" * 40)
        status = self.dev.status(self.project_id)
        self.assertEqual(status["integration_proposals"], [])
        self.assertEqual(status["integration_head_mappings"][0]["state"], "authorized")
        self.assertIsNone(status["integration_head_mappings"][0]["consumed_by"])
        self.assertEqual(status["milestones"][0]["head_revision"], previous)

    def test_stale_diverged_head_mapping_refuses_stage(self):
        previous, new_head = self.diverged_head()
        self.authorize_head(previous, new_head)
        self.dev.pause(
            self.project_id, expected_version=self.pv, reason="stale mapping"
        )
        with self.assertRaisesRegex(Conflict, "diverged-head mapping is stale"):
            self.controller.prepare(self.intake_id, expected_head=new_head)
        status = self.dev.status(self.project_id)
        self.assertEqual(status["integration_proposals"], [])
        self.assertEqual(status["integration_head_mappings"][0]["state"], "authorized")
        self.assertIsNone(status["integration_head_mappings"][0]["consumed_by"])
        self.assertEqual(status["milestones"][0]["head_revision"], previous)
        self.assertNotEqual(
            status["integration_head_mappings"][0]["authority_generation"],
            status["project"]["generation"],
        )

    def test_authorized_head_is_consumed_once_and_used_as_stage_base(self):
        previous, new_head = self.diverged_head()
        granted = self.authorize_head(previous, new_head)
        repeated = self.authorize_head(previous, new_head)
        self.assertEqual(repeated["mapping_id"], granted["mapping_id"])
        self.assertEqual(
            len(self.dev.status(self.project_id)["integration_head_mappings"]), 1
        )
        proposal = self.controller.prepare(self.intake_id, expected_head=new_head)
        staged = self.controller.run(proposal["proposal_id"], expected_version=1)
        self.assertTrue(staged["current"])
        self.assertEqual(staged["state"], "staged")
        self.assertFalse(staged["task_accepted"])
        status = self.dev.status(self.project_id)
        stored = status["integration_proposals"][0]
        stage = stored["receipt"]["stage"]
        self.assertEqual(
            stage["parents"], [new_head, stored["intent"]["candidate_revision"]]
        )
        self.assertEqual(stage["expected_head"], new_head)
        self.assertNotEqual(stage["revision"], stored["intent"]["candidate_revision"])
        self.assertEqual(stage["changed_paths"], ["src/example.py"])
        self.assertFalse(stage["task_accepted"])
        files = self.repo.snapshot(stage["revision"]).files()
        self.assertEqual(files["README.md"].data, b"head advance\n")
        self.assertEqual(files["src/example.py"].data, b"candidate\r\n\0binary")
        self.assertEqual(status["milestones"][0]["head_revision"], previous)
        self.assertEqual(
            status["milestones"][0]["tasks"][1]["state"], "blocked_dependencies"
        )
        self.assertFalse(status["capabilities"]["task_acceptance"])
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM acceptances").fetchone()[0], 0
        )
        mapping = status["integration_head_mappings"][0]
        self.assertEqual(mapping["state"], "consumed")
        self.assertEqual(mapping["consumed_by"], proposal["proposal_id"])
        self.assertEqual(mapping["previous_head"], previous)
        self.assertEqual(mapping["new_head"], new_head)
        refs = self.repo._run("for-each-ref", "--format=%(refname)").stdout.decode()
        self.assertIn(f"refs/orchestrator/integrations/{proposal['proposal_id']}", refs)
        self.assertNotIn("refs/heads/", refs)
        self.assertNotIn("refs/orchestrator/validation/", refs)
        with self.assertRaisesRegex(Conflict, "diverged-head mapping already consumed"):
            self.authorize_head(previous, new_head)
        current = self.dev.status(self.project_id)["integration_proposals"][0][
            "version"
        ]
        with self.assertRaisesRegex(Conflict, "stage may already be sent"):
            self.controller.run(proposal["proposal_id"], expected_version=current)
        operation = self.regression_job(stored)
        self.regression.submit_regression(
            operation["operation_id"],
            self.regression_receipt(operation["operation_id"]),
        )
        gate = self.controller.gate(proposal["proposal_id"])
        self.assertFalse(gate["development_ready_for_promotion"])
        self.assertTrue(gate["needs_fresh_integrated_checks_review"])
        self.assertFalse(gate["live_eligible"])
        self.assertFalse(gate["task_accepted"])
        self.assertEqual(
            self.dev.status(self.project_id)["milestones"][0]["head_revision"], previous
        )

    def integrated_row(self, operation_id):
        return next(
            row
            for row in self.dev.status(self.project_id)["integration_verifications"]
            if row["id"] == operation_id
        )

    def integrated_spec(self, proposal, *, session="integrated-review-session"):
        return {
            "classification": "scripted_development",
            "phase": "integrated",
            "checks": self.spec["checks"],
            "review": {
                "producer": "reviewer",
                "profile_digest": self.artifact(
                    {
                        "classification": "scripted_development",
                        "fixture": "integrated review",
                    }
                ),
                "rubric_digest": self.artifact(
                    {"version": "review-v1", "dimensions": list(DIMENSIONS)}
                ),
                "context_digest": self.artifact(
                    {
                        "session_id": session,
                        "packet_digest": proposal["receipt"]["packet"]["sha256"],
                        "purpose": "independent_review",
                    }
                ),
            },
        }

    def pass_regressions(self, proposal):
        operation = self.regression_job(proposal)
        result = self.regression.submit_regression(
            operation["operation_id"],
            self.regression_receipt(operation["operation_id"]),
        )
        self.assertTrue(result["passed"])
        return operation

    def pass_integrated(self, proposal, *, review_verdict="pass"):
        spec = self.integrated_spec(proposal)
        self.integration_owner.approve_evidence(
            proposal["id"],
            spec,
            digest(spec),
            expected_version=proposal["version"],
        )
        prepared = self.controller.prepare_integrated_checks(proposal["id"])
        checker = Integration(
            Coordinator(self.store, Principal("checker", "service")),
            self.repo,
            self.artifacts,
        )
        reviewer = Integration(
            Coordinator(self.store, Principal("reviewer", "service")),
            self.repo,
            self.artifacts,
        )
        for operation in prepared["operations"]:
            self.controller.begin_integrated(
                operation["operation_id"], expected_version=1
            )
            binding = self.integrated_row(operation["operation_id"])["binding"]
            observation = self.artifact(
                {
                    "classification": "scripted_development",
                    "expected": "fixture case passes",
                    "observed": "fixture case passes",
                }
            )
            checker.submit_integrated(
                operation["operation_id"],
                {
                    "binding_digest": digest(binding),
                    "verdict": "pass",
                    "details": {
                        "source_digest": binding["source_digest"],
                        "environment_digest": binding["profile"]["environment_digest"],
                        "log_digest": self.artifact(
                            {
                                "classification": "scripted_development",
                                "log": "no check execution",
                            }
                        ),
                        "cases": [
                            {
                                "id": key,
                                "status": "pass",
                                "observation_digest": observation,
                            }
                            for key in ("valid", "blank")
                        ],
                    },
                },
            )
        review = self.controller.prepare_integrated_review(proposal["id"])[
            "operations"
        ][0]
        self.controller.begin_integrated(review["operation_id"], expected_version=1)
        binding = self.integrated_row(review["operation_id"])["binding"]
        review_receipt = {
            "binding_digest": digest(binding),
            "verdict": review_verdict,
            "details": {
                "context_digest": binding["profile"]["context_digest"],
                "rubric_digest": binding["profile"]["rubric_digest"],
                "criteria": {"C1": "satisfied"},
                "dimensions": dict.fromkeys(DIMENSIONS, "satisfied"),
                "findings": [],
                "check_evidence": binding["check_evidence"],
            },
        }
        if review_verdict == "reject":
            review_receipt["details"]["criteria"]["C1"] = "violated"
            review_receipt["details"]["findings"] = [
                {
                    "id": "F1",
                    "criterion_id": "C1",
                    "severity": "major",
                    "location": "src/example.py:1",
                    "reproduction_digest": self.artifact(
                        {
                            "classification": "scripted_development",
                            "actual": "rejected integrated commit",
                        }
                    ),
                    "expected": "Fresh integrated review passes",
                    "actual": "Integrated review rejects the commit",
                    "impact": "Promotion stays held",
                }
            ]
        result = reviewer.submit_integrated(review["operation_id"], review_receipt)
        return result

    def staged_diverged(self):
        previous, new_head = self.diverged_head()
        self.authorize_head(previous, new_head)
        proposal = self.controller.prepare(self.intake_id, expected_head=new_head)
        self.controller.run(proposal["proposal_id"], expected_version=1)
        stored = next(
            row
            for row in self.dev.status(self.project_id)["integration_proposals"]
            if row["id"] == proposal["proposal_id"]
        )
        self.pass_regressions(stored)
        return previous, stored

    def claim_task_two(self):
        status = self.dev.status(self.project_id)
        milestone = status["milestones"][0]
        return self.dev.claim_task(
            self.project_id,
            "M1",
            "T2",
            expected_project_version=status["project"]["version"],
            expected_milestone_version=milestone["version"],
        )

    def test_same_commit_promotes_without_a_second_review(self):
        proposal = self.stage()
        self.pass_regressions(proposal)
        gate = self.controller.gate(proposal["id"])
        self.assertTrue(gate["development_ready_for_promotion"])
        self.assertIsNone(gate["integrated_evidence"])
        self.assertFalse(gate["needs_fresh_integrated_checks_review"])
        spec = {
            "classification": "scripted_development",
            "phase": "integrated",
            "checks": self.spec["checks"],
            "review": {},
        }
        with self.assertRaisesRegex(Conflict, "already binds this integrated commit"):
            self.integration_owner.approve_evidence(
                proposal["id"], spec, digest(spec), expected_version=proposal["version"]
            )
        with self.assertRaisesRegex(Conflict, "dependencies are not accepted"):
            self.claim_task_two()
        before = self.dev.status(self.project_id)
        promoted = self.integration_owner.promote(
            proposal["id"], expected_version=proposal["version"]
        )
        self.assertTrue(promoted["task_accepted"])
        self.assertFalse(promoted["live_eligible"])
        self.assertFalse(promoted["duplicate"])
        status = self.dev.status(self.project_id)
        milestone = status["milestones"][0]
        self.assertEqual(milestone["head_revision"], gate["integrated_revision"])
        self.assertEqual(milestone["tasks"][0]["state"], "accepted")
        self.assertEqual(milestone["tasks"][1]["state"], "ready")
        self.assertEqual(
            status["project"]["generation"], before["project"]["generation"]
        )
        self.assertFalse(status["capabilities"]["task_acceptance"])
        claimed = self.claim_task_two()
        self.assertEqual(claimed["input_revision"], gate["integrated_revision"])
        repeated = self.integration_owner.reconcile_promotion(proposal["id"])
        self.assertTrue(repeated["duplicate"])
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM acceptances").fetchone()[0], 1
        )
        refs = self.repo._run("for-each-ref", "--format=%(refname)").stdout.decode()
        self.assertIn(f"refs/orchestrator/milestones/{milestone['id']}", refs)
        self.assertNotIn("refs/heads/", refs)
        self.assertNotIn("refs/orchestrator/validation/", refs)

    def test_missing_milestone_ref_after_send_is_held_without_replay(self):
        proposal = self.stage()
        self.pass_regressions(proposal)
        begun = self.integration_owner.begin_promotion(
            proposal["id"], expected_version=proposal["version"]
        )
        with (
            patch.object(
                self.repo,
                "advance_milestone_ref",
                side_effect=AssertionError("must not create the ref"),
            ),
            self.assertRaises(Conflict),
        ):
            self.integration_owner.reconcile_promotion(proposal["id"])
        status = self.dev.status(self.project_id)
        self.assertEqual(status["integration_promotions"][0]["state"], "held")
        self.assertEqual(
            status["integration_promotions"][0]["id"], begun["promotion_id"]
        )
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM acceptances").fetchone()[0], 0
        )
        self.assertEqual(
            status["milestones"][0]["tasks"][1]["state"], "blocked_dependencies"
        )
        refs = self.repo._run("for-each-ref", "--format=%(refname)").stdout.decode()
        self.assertNotIn("refs/orchestrator/milestones/", refs)

    def test_rejected_integrated_review_cannot_promote(self):
        _previous, proposal = self.staged_diverged()
        result = self.pass_integrated(proposal, review_verdict="reject")
        self.assertFalse(result["passed"])
        gate = self.controller.gate(proposal["id"])
        self.assertFalse(gate["development_ready_for_promotion"])
        self.assertTrue(gate["needs_fresh_integrated_checks_review"])
        with self.assertRaisesRegex(Conflict, "not ready for promotion"):
            self.integration_owner.begin_promotion(
                proposal["id"], expected_version=proposal["version"]
            )
        status = self.dev.status(self.project_id)
        self.assertEqual(status["integration_promotions"], [])
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM acceptances").fetchone()[0], 0
        )
        self.assertEqual(
            status["milestones"][0]["tasks"][1]["state"], "blocked_dependencies"
        )
        self.assertNotIn(
            "refs/orchestrator/milestones/",
            self.repo._run("for-each-ref", "--format=%(refname)").stdout.decode(),
        )

    def test_changed_sha_invalidates_integrated_review(self):
        previous, proposal = self.staged_diverged()
        self.pass_integrated(proposal)
        stage = proposal["receipt"]["stage"]["revision"]
        review = next(
            row
            for row in self.dev.status(self.project_id)["integration_verifications"]
            if row["kind"] == "review"
        )
        binding = dict(review["binding"])
        self.assertEqual(binding["subject_revision"], stage)
        binding["subject_revision"] = proposal["intent"]["candidate_revision"]
        self.store.db.execute(
            "UPDATE integration_verifications SET binding=? WHERE id=?",
            (canonical(binding), review["id"]),
        )
        reference, intent, receipt = self.controller._validated(proposal["id"])
        with self.assertRaisesRegex(Conflict, "bound to another commit"):
            self.controller._fresh_evidence(reference, intent, receipt)
        self.assertFalse(
            self.controller.gate(proposal["id"])["development_ready_for_promotion"]
        )
        with self.assertRaisesRegex(Conflict, "not ready for promotion"):
            self.integration_owner.begin_promotion(
                proposal["id"], expected_version=proposal["version"]
            )
        status = self.dev.status(self.project_id)
        self.assertEqual(status["milestones"][0]["head_revision"], previous)
        self.assertEqual(status["integration_promotions"], [])
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM acceptances").fetchone()[0], 0
        )

    def test_distinct_commit_promotion_reconciles_once_and_releases_task_two(self):
        previous, proposal = self.staged_diverged()
        self.assertFalse(
            self.controller.gate(proposal["id"])["development_ready_for_promotion"]
        )
        reused = self.integrated_spec(proposal, session="review-session")
        with self.assertRaisesRegex(Conflict, "candidate review session"):
            self.integration_owner.approve_evidence(
                proposal["id"],
                reused,
                digest(reused),
                expected_version=proposal["version"],
            )
        fresh = self.pass_integrated(proposal)
        self.assertTrue(fresh["passed"])
        gate = self.controller.gate(proposal["id"])
        stage = proposal["receipt"]["stage"]["revision"]
        self.assertTrue(gate["development_ready_for_promotion"])
        self.assertFalse(gate["needs_fresh_integrated_checks_review"])
        self.assertFalse(gate["live_eligible"])
        self.assertFalse(gate["task_accepted"])
        self.assertEqual(gate["integrated_evidence"]["subject_revision"], stage)
        self.assertNotEqual(stage, proposal["intent"]["candidate_revision"])
        check = next(
            row
            for row in self.dev.status(self.project_id)["integration_verifications"]
            if row["kind"] == "check"
        )
        self.assertEqual(check["binding"]["subject_revision"], stage)
        self.assertEqual(
            check["binding"]["source_digest"],
            gate["integrated_evidence"]["source_digest"],
        )
        with self.assertRaisesRegex(Invalid, "developer authority required"):
            self.controller.begin_promotion(
                proposal["id"], expected_version=proposal["version"]
            )
        with self.assertRaisesRegex(Conflict, "dependencies are not accepted"):
            self.claim_task_two()
        before = self.dev.status(self.project_id)
        program = """
import os,sys
from coordinator import Coordinator,Principal,Store
from coordinator.evidence import EvidenceStore
from coordinator.source import TrustedRepository
from coordinator.integration import Integration
with Store(sys.argv[1]) as store:
    owner=Integration(Coordinator(store,Principal("developer")),TrustedRepository(sys.argv[2]),EvidenceStore(sys.argv[3]))
    begun=owner.begin_promotion(sys.argv[4], expected_version=int(sys.argv[5]))
    owner.repo.advance_milestone_ref(begun["milestone_id"], begun["expected_head"], begun["integrated_revision"])
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
                proposal["id"],
                str(proposal["version"]),
            ],
            capture_output=True,
            timeout=60,
            check=False,
        )
        self.assertEqual(child.returncode, 29, child.stderr)
        with patch.object(
            self.repo,
            "advance_milestone_ref",
            side_effect=AssertionError("reconcile must not write the ref"),
        ):
            recovered = self.integration_owner.reconcile_promotion(proposal["id"])
            repeated = self.integration_owner.reconcile_promotion(proposal["id"])
        self.assertTrue(recovered["task_accepted"])
        self.assertFalse(recovered["live_eligible"])
        self.assertFalse(recovered["duplicate"])
        self.assertTrue(repeated["duplicate"])
        self.assertEqual(recovered["integrated_revision"], stage)
        status = self.dev.status(self.project_id)
        milestone = status["milestones"][0]
        self.assertEqual(milestone["head_revision"], stage)
        self.assertNotEqual(milestone["head_revision"], previous)
        self.assertEqual(milestone["tasks"][0]["state"], "accepted")
        self.assertEqual(milestone["tasks"][1]["state"], "ready")
        self.assertEqual(
            status["project"]["generation"], before["project"]["generation"]
        )
        self.assertEqual(status["project"]["version"], before["project"]["version"])
        self.assertFalse(status["capabilities"]["task_acceptance"])
        self.assertEqual(
            status["integration_promotions"][0]["evidence"]["integrated_revision"],
            stage,
        )
        self.assertEqual(
            status["integration_promotions"][0]["evidence"]["classification"],
            "scripted_development",
        )
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM acceptances").fetchone()[0], 1
        )
        self.assertEqual(
            self.store.db.execute(
                "SELECT integrated_revision FROM acceptances"
            ).fetchone()[0],
            stage,
        )
        claimed = self.claim_task_two()
        self.assertEqual(claimed["input_revision"], stage)
        self.assertEqual(claimed["state"], "reserved")
        refs = self.repo._run("for-each-ref", "--format=%(refname)").stdout.decode()
        self.assertIn(f"refs/orchestrator/milestones/{milestone['id']}", refs)
        self.assertIn(f"refs/orchestrator/integrations/{proposal['id']}", refs)
        self.assertNotIn("refs/heads/", refs)
        self.assertNotIn("refs/orchestrator/validation/", refs)


class RejectedCandidateTests(
    verification_fixture.VerificationFixture, unittest.TestCase
):
    def test_rejected_candidate_cannot_promote(self):
        operation = self.review()
        receipt = self.review_receipt(operation["operation_id"])
        receipt["verdict"] = "reject"
        receipt["details"]["criteria"]["C1"] = "violated"
        receipt["details"]["findings"] = [
            {
                "id": "F1",
                "criterion_id": "C1",
                "severity": "major",
                "location": "src/example.py:1",
                "reproduction_digest": self.artifact(
                    {
                        "classification": "scripted_development",
                        "actual": "candidate rejected",
                    }
                ),
                "expected": "Reject the candidate",
                "actual": "Candidate remains unintegrated",
                "impact": "No promotion",
            }
        ]
        result = self.reviewer.submit(operation["operation_id"], receipt)
        self.assertFalse(result["passed"])
        self.assertFalse(
            self.owner.gate(self.intake_id)["development_ready_for_integration"]
        )
        controller = Integration(
            Coordinator(self.store, Principal("integration-controller", "service")),
            self.repo,
            self.artifacts,
        )
        with self.assertRaises(Conflict):
            controller.prepare(self.intake_id)
        status = self.dev.status(self.project_id)
        self.assertEqual(status["integration_proposals"], [])
        self.assertEqual(
            status["milestones"][0]["tasks"][1]["state"], "blocked_dependencies"
        )
        self.assertFalse(status["capabilities"]["task_acceptance"])
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM acceptances").fetchone()[0], 0
        )
        self.assertNotIn(
            "refs/orchestrator/milestones/",
            self.repo._run("for-each-ref", "--format=%(refname)").stdout.decode(),
        )


if __name__ == "__main__":
    unittest.main()
