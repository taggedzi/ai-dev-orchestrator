"""Exact evidence bindings and independent roles; all outcomes are scripted."""

import copy
import json
import shutil
import subprocess
import sys
import unittest

from coordinator import Conflict, Coordinator, Invalid, Principal, Store
from coordinator.domain import canonical, digest
from coordinator.source import Snapshot, SourceFile
from coordinator.store import patched_sqlite
from coordinator.verification import DIMENSIONS, Verification
from tests import test_coordinator_intake as intake_fixture


@unittest.skipUnless(
    patched_sqlite() and shutil.which("git"), "needs patched SQLite and Git"
)
class VerificationFixture:
    def setUp(self):
        # Reuse the actual approved-attempt fixture without inheriting its tests.
        intake_fixture.IntakeTests.setUp(self)
        prepared = self.intake.prepare(
            self.attempt_id, self.snapshot, expected_attempt_version=self.version
        )
        self.intake_id = prepared["intake_id"]
        self.sealed = self.intake.run(self.intake_id, expected_version=1)
        self.candidate = self.dev.status(self.project_id)["candidate_intakes"][0]
        self.owner = Verification(self.dev, self.repo, self.artifacts)
        self.scheduler = self.verifier("verification-scheduler")
        self.checker = self.verifier("checker")
        self.reviewer = self.verifier("reviewer")
        self.spec = self.policy()

    def verifier(self, actor):
        return Verification(
            Coordinator(self.store, Principal(actor, "service")),
            self.repo,
            self.artifacts,
        )

    def artifact(self, value):
        return self.artifacts.put(canonical(value).encode())["sha256"]

    def policy(self, *, candidate=None, session="review-session"):
        candidate = candidate or self.candidate
        check = candidate["contract"]["task"]["checks"][0]
        return {
            "classification": "scripted_development",
            "checks": [
                {
                    "check_id": check["id"],
                    "producer": "checker",
                    "definition_digest": self.artifact(
                        {
                            "check": check,
                            "cases": [
                                {
                                    "id": "valid",
                                    "input": "Ada",
                                    "expected": "unchanged",
                                },
                                {"id": "blank", "input": "", "expected": "rejected"},
                            ],
                        }
                    ),
                    "environment_digest": self.artifact(
                        {
                            "classification": "scripted_development",
                            "fixture": "no process runs",
                        }
                    ),
                }
            ],
            "review": {
                "producer": "reviewer",
                "profile_digest": self.artifact(
                    {
                        "classification": "scripted_development",
                        "fixture": "no model runs",
                    }
                ),
                "rubric_digest": self.artifact(
                    {"version": "review-v1", "dimensions": list(DIMENSIONS)}
                ),
                "context_digest": self.artifact(
                    {
                        "session_id": session,
                        "packet_digest": candidate["receipt"]["review_packet"][
                            "sha256"
                        ],
                        "purpose": "independent_review",
                    }
                ),
            },
        }

    def approve(self, spec=None):
        spec = spec or self.spec
        return self.owner.approve_policy(
            self.intake_id,
            spec,
            digest(spec),
            expected_intake_version=self.candidate["version"],
        )

    def row(self, operation_id):
        return next(
            row
            for row in self.dev.status(self.project_id)["verification_operations"]
            if row["id"] == operation_id
        )

    def check_receipt(self, operation_id):
        binding = self.row(operation_id)["binding"]
        observation = self.artifact(
            {
                "classification": "scripted_development",
                "expected": "fixture case passes",
                "observed": "fixture case passes",
            }
        )
        return {
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
                    {"id": key, "status": "pass", "observation_digest": observation}
                    for key in ("valid", "blank")
                ],
            },
        }

    def checks(self):
        self.approve()
        operations = self.scheduler.prepare_checks(self.intake_id)["operations"]
        for operation in operations:
            self.scheduler.begin(operation["operation_id"], expected_version=1)
            self.checker.submit(
                operation["operation_id"], self.check_receipt(operation["operation_id"])
            )
        return operations

    def review_receipt(self, operation_id):
        binding = self.row(operation_id)["binding"]
        return {
            "binding_digest": digest(binding),
            "verdict": "pass",
            "details": {
                "context_digest": binding["profile"]["context_digest"],
                "rubric_digest": binding["profile"]["rubric_digest"],
                "criteria": {"C1": "satisfied"},
                "dimensions": dict.fromkeys(DIMENSIONS, "satisfied"),
                "findings": [],
                "check_evidence": binding["check_evidence"],
            },
        }

    def review(self):
        self.checks()
        operation = self.scheduler.prepare_review(self.intake_id)["operations"][0]
        self.scheduler.begin(operation["operation_id"], expected_version=1)
        return operation


class VerificationTests(VerificationFixture, unittest.TestCase):
    def test_complete_scripted_chain_is_durable_but_cannot_accept_task(self):
        operation = self.review()
        result = self.reviewer.submit(
            operation["operation_id"], self.review_receipt(operation["operation_id"])
        )
        self.assertTrue(result["passed"])
        gate = self.owner.gate(self.intake_id)
        self.assertTrue(gate["development_ready_for_integration"])
        self.assertFalse(gate["live_eligible"])
        self.assertFalse(gate["task_accepted"])
        with Store(self.store.path) as reopened:
            read = Verification(
                Coordinator(reopened, Principal("developer")), self.repo, self.artifacts
            )
            self.assertEqual(read.gate(self.intake_id), gate)
        self.assertEqual(
            self.dev.status(self.project_id)["milestones"][0]["tasks"][1]["state"],
            "blocked_dependencies",
        )

    def test_policy_digest_and_original_checks_cannot_be_substituted(self):
        with self.assertRaises(Conflict):
            self.owner.approve_policy(
                self.intake_id,
                self.spec,
                "0" * 64,
                expected_intake_version=self.candidate["version"],
            )
        changed = copy.deepcopy(self.spec)
        definition = json.loads(
            self.artifacts.read(changed["checks"][0]["definition_digest"])
        )
        definition["check"]["argv"] = ["different-command"]
        changed["checks"][0]["definition_digest"] = self.artifact(definition)
        with self.assertRaises(Invalid):
            self.approve(changed)
        self.assertFalse(
            self.owner.gate(self.intake_id)["development_ready_for_integration"]
        )

    def test_implementer_checker_and_intake_cannot_be_the_reviewer(self):
        for producer in ("developer", "checker", "local-intake"):
            changed = copy.deepcopy(self.spec)
            changed["review"]["producer"] = producer
            with self.subTest(producer=producer), self.assertRaises(Invalid):
                self.approve(changed)
        changed = copy.deepcopy(self.spec)
        changed["checks"][0]["producer"] = "developer"
        with self.assertRaises(Invalid):
            self.approve(changed)

    def test_review_requires_every_check_and_no_result_before_dispatch(self):
        self.approve()
        with self.assertRaises(Conflict):
            self.scheduler.prepare_review(self.intake_id)
        operation = self.scheduler.prepare_checks(self.intake_id)["operations"][0]
        with self.assertRaises(Conflict):
            self.checker.submit(
                operation["operation_id"], self.check_receipt(operation["operation_id"])
            )
        with self.assertRaises(Conflict):
            self.scheduler.prepare_review(self.intake_id)

    def test_wrong_producer_and_actor_payload_cannot_forge_result(self):
        self.approve()
        operation = self.scheduler.prepare_checks(self.intake_id)["operations"][0]
        self.scheduler.begin(operation["operation_id"], expected_version=1)
        receipt = self.check_receipt(operation["operation_id"])
        with self.assertRaises(Conflict):
            self.reviewer.submit(operation["operation_id"], receipt)
        with self.assertRaises(Invalid):
            self.checker.submit(
                operation["operation_id"], {**receipt, "actor": "checker"}
            )
        self.assertEqual(self.row(operation["operation_id"])["state"], "possible_send")

    def test_missing_case_cannot_be_covered_by_pass_verdict(self):
        self.approve()
        operation = self.scheduler.prepare_checks(self.intake_id)["operations"][0]
        self.scheduler.begin(operation["operation_id"], expected_version=1)
        receipt = self.check_receipt(operation["operation_id"])
        receipt["details"]["cases"].pop()
        result = self.checker.submit(operation["operation_id"], receipt)
        self.assertFalse(result["passed"])
        self.assertEqual(result["state"], "held")
        with self.assertRaises(Conflict):
            self.scheduler.prepare_review(self.intake_id)

    def test_wrong_subject_binding_and_environment_are_held(self):
        self.approve()
        operation = self.scheduler.prepare_checks(self.intake_id)["operations"][0]
        self.scheduler.begin(operation["operation_id"], expected_version=1)
        receipt = self.check_receipt(operation["operation_id"])
        receipt["binding_digest"] = "0" * 64
        receipt["details"]["environment_digest"] = "1" * 64
        result = self.checker.submit(operation["operation_id"], receipt)
        self.assertFalse(result["passed"])
        self.assertEqual(result["state"], "held")
        self.assertIsNotNone(self.row(operation["operation_id"])["receipt"])

    def test_rejection_with_reproduction_blocks_green_checks(self):
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
                        "input": " \t ",
                        "expected": "reject",
                        "actual": "accepted",
                        "classification": "scripted_development",
                    }
                ),
                "expected": "Reject blank input",
                "actual": "Accepts mixed whitespace",
                "impact": "Criterion violated",
            }
        ]
        result = self.reviewer.submit(operation["operation_id"], receipt)
        self.assertFalse(result["passed"])
        self.assertFalse(
            self.owner.gate(self.intake_id)["development_ready_for_integration"]
        )

    def test_missing_review_dimension_and_replaced_context_cannot_pass(self):
        operation = self.review()
        receipt = self.review_receipt(operation["operation_id"])
        receipt["details"]["dimensions"].pop("security")
        receipt["details"]["context_digest"] = "0" * 64
        result = self.reviewer.submit(operation["operation_id"], receipt)
        self.assertFalse(result["passed"])
        self.assertFalse(
            self.owner.gate(self.intake_id)["development_ready_for_integration"]
        )

    def test_duplicate_is_deduplicated_and_conflict_fences_every_operation(self):
        operations = self.checks()
        operation_id = operations[0]["operation_id"]
        receipt = self.check_receipt(operation_id)
        first = self.checker.submit(operation_id, receipt)
        self.assertTrue(first["duplicate"])
        self.assertEqual(
            self.store.db.execute(
                "SELECT COUNT(*) FROM verification_observations"
            ).fetchone()[0],
            1,
        )
        receipt["verdict"] = "fail"
        conflict = self.checker.submit(operation_id, receipt)
        self.assertTrue(conflict["conflicting"])
        self.assertTrue(self.dev.status(self.project_id)["project"]["paused"])
        self.assertEqual(self.row(operation_id)["state"], "conflicting")
        self.assertEqual(
            self.store.db.execute(
                "SELECT COUNT(*) FROM verification_observations"
            ).fetchone()[0],
            2,
        )

    def test_late_result_is_retained_and_resume_does_not_revive_authority(self):
        self.approve()
        operation = self.scheduler.prepare_checks(self.intake_id)["operations"][0]
        self.scheduler.begin(operation["operation_id"], expected_version=1)
        receipt = self.check_receipt(operation["operation_id"])
        paused = self.dev.pause(
            self.project_id, expected_version=self.pv, reason="revoke verification"
        )
        result = self.checker.submit(operation["operation_id"], receipt)
        self.assertFalse(result["current"])
        self.dev.resume(self.project_id, expected_version=paused["version"])
        self.assertFalse(
            self.owner.gate(self.intake_id)["development_ready_for_integration"]
        )

    def test_changed_artifact_or_ref_invalidates_green_gate(self):
        operation = self.review()
        self.reviewer.submit(
            operation["operation_id"], self.review_receipt(operation["operation_id"])
        )
        self.assertTrue(
            self.owner.gate(self.intake_id)["development_ready_for_integration"]
        )
        rubric = self.artifacts.root / self.spec["review"]["rubric_digest"]
        original = rubric.read_bytes()
        rubric.write_bytes(b"changed")
        self.assertFalse(
            self.owner.gate(self.intake_id)["development_ready_for_integration"]
        )
        rubric.write_bytes(original)
        receipt = self.candidate["receipt"]["candidate"]
        self.repo._run(
            "update-ref", receipt["ref"], receipt["input_revision"], receipt["revision"]
        )
        self.assertFalse(
            self.owner.gate(self.intake_id)["development_ready_for_integration"]
        )

    def test_reviewer_session_cannot_be_reused_for_correction(self):
        self.approve()
        paused = self.dev.pause(
            self.project_id, expected_version=self.pv, reason="correct source"
        )
        attempt = self.dev.status(self.project_id)["attempts"][0]
        self.dev.abandon_scripted(
            self.attempt_id,
            expected_version=attempt["version"],
            reason="scripted source has no native side effects",
        )
        resumed = self.dev.resume(self.project_id, expected_version=paused["version"])
        new = self.dev.claim_task(
            self.project_id,
            "M1",
            "T1",
            expected_project_version=resumed["version"],
            expected_milestone_version=self.mv,
        )
        self.dev.start_scripted(new["attempt_id"], expected_version=1)
        self.dev.record_scripted_result(new["operation_id"], "candidate")
        version = self.dev.status(self.project_id)["attempts"][-1]["version"]
        prepared = self.intake.prepare(
            new["attempt_id"],
            Snapshot(
                {
                    "src/example.py": SourceFile(b"corrected"),
                    "README.md": SourceFile(b"unchanged"),
                }
            ),
            expected_attempt_version=version,
        )
        self.intake.run(prepared["intake_id"], expected_version=1)
        candidate = self.dev.status(self.project_id)["candidate_intakes"][-1]
        spec = self.policy(candidate=candidate)
        with self.assertRaises(Conflict):
            self.owner.approve_policy(
                candidate["id"],
                spec,
                digest(spec),
                expected_intake_version=candidate["version"],
            )

    def test_process_exit_after_dispatch_does_not_authorize_replay(self):
        self.approve()
        operation = self.scheduler.prepare_checks(self.intake_id)["operations"][0]
        program = """
import os,sys
from coordinator import Coordinator,Principal,Store
from coordinator.evidence import EvidenceStore
from coordinator.source import TrustedRepository
from coordinator.verification import Verification
with Store(sys.argv[1]) as store:
    verifier=Verification(Coordinator(store,Principal("verification-scheduler","service")),TrustedRepository(sys.argv[2]),EvidenceStore(sys.argv[3]))
    verifier.begin(sys.argv[4],expected_version=1)
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
                operation["operation_id"],
            ],
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(child.returncode, 29, child.stderr)
        with self.assertRaises(Conflict):
            self.scheduler.begin(operation["operation_id"], expected_version=1)
        result = self.checker.submit(
            operation["operation_id"], self.check_receipt(operation["operation_id"])
        )
        self.assertTrue(result["passed"])
        self.assertFalse(
            self.owner.gate(self.intake_id)["development_ready_for_integration"]
        )

    def test_unknown_legacy_implementation_identity_does_not_qualify_independence(self):
        context = self.owner._candidate(self.intake_id)
        context["contract"].pop("implementation_actor")
        context["contract"]["format"] = "candidate-contract-v1"
        with self.assertRaises(Conflict):
            self.owner._validate_policy(context, self.spec)

    def test_malformed_enum_and_rubric_values_raise_domain_errors(self):
        changed = copy.deepcopy(self.spec)
        changed["review"]["rubric_digest"] = self.artifact(
            {"version": "bad-rubric", "dimensions": [{}] * len(DIMENSIONS)}
        )
        with self.assertRaises(Invalid):
            self.approve(changed)
        self.approve()
        operation = self.scheduler.prepare_checks(self.intake_id)["operations"][0]
        self.scheduler.begin(operation["operation_id"], expected_version=1)
        receipt = self.check_receipt(operation["operation_id"])
        receipt["verdict"] = []
        with self.assertRaises(Invalid):
            self.checker.submit(operation["operation_id"], receipt)


if __name__ == "__main__":
    unittest.main()
