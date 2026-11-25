"""Scripted model eligibility, permits, and cost reports. No provider calls."""

import tempfile
import unittest
from pathlib import Path

from coordinator import Conflict, Coordinator, Invalid, Principal, Store
from coordinator.model_policy import ModelPolicy
from coordinator.store import patched_sqlite
from tests.test_coordinator import plan, project


def policy():
    return {
        "classification": "scripted_development",
        "limits": {
            "max_reserved_units": 1000,
            "max_submissions": 4,
            "protected_review_units": 200,
        },
        "routes": [
            {
                "id": "local-scripted",
                "kind": "local",
                "requested_model": "scripted-model",
                "available": True,
            },
            {
                "id": "paid-gateway",
                "kind": "gateway",
                "requested_model": "gateway-model",
                "available": False,
            },
        ],
    }


def requested():
    return {
        "model": "scripted-model",
        "max_output_tokens": 1000,
        "reasoning_effort": "low",
    }


def usage(quality, units=None, **identity):
    body = {
        "quality": quality,
        "units": units,
        "input_tokens": None,
        "output_tokens": None,
        "provider": None,
        "resolved_model": None,
        "response_id": None,
    }
    body.update(identity)
    return body


@unittest.skipUnless(
    patched_sqlite(), "product persistence requires a patched SQLite runtime"
)
class ModelPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "product.sqlite"
        self.store = Store.create(self.path)
        self.addCleanup(lambda: self.store.close() if self.store is not None else None)
        self.app = Coordinator(self.store, Principal("test-developer"))
        self.models = ModelPolicy(self.app)
        self.project_id = self.app.create_project(project())["project_id"]
        submitted = self.app.submit_plan(
            self.project_id, "M1", plan(), expected_project_version=1
        )
        approved = self.app.approve_plan(
            submitted["plan_id"],
            submitted["digest"],
            expected_project_version=1,
            expected_milestone_version=submitted["milestone_version"],
        )
        self.pv = approved["project_version"]
        self.mv = approved["milestone_version"]
        self.attempt = self.app.claim_task(
            self.project_id,
            "M1",
            "T1",
            expected_project_version=self.pv,
            expected_milestone_version=self.mv,
        )

    def approve(self, spec=None):
        return self.models.approve_policy(
            self.project_id,
            "M1",
            policy() if spec is None else spec,
            expected_project_version=self.pv,
            expected_milestone_version=self.mv,
        )

    def assign(self, role="implementation", route="local-scripted"):
        return self.models.assign(
            self.attempt["attempt_id"],
            role,
            route,
            requested(),
            expected_attempt_version=1,
            expected_project_version=self.pv,
        )

    def permit(self, assignment_id, submission, units, route="local-scripted"):
        return self.models.begin_permit(
            assignment_id,
            route,
            submission,
            units,
            "ab" * 32,
            expected_project_version=self.pv,
        )

    def test_unavailable_route_fallback_and_replay_are_denied(self):
        self.approve()
        with self.assertRaisesRegex(Conflict, "route unavailable"):
            self.assign(route="paid-gateway")
        granted = self.assign()
        self.assertEqual(
            granted["missing_observed"], ["provider", "resolved_model", "response_id"]
        )
        self.assertFalse(granted["live_eligible"])
        with self.assertRaisesRegex(Conflict, "fallback route denied"):
            self.permit(granted["assignment_id"], "submit-1", 10, route="paid-gateway")
        begun = self.models.begin_permit(
            granted["assignment_id"],
            "local-scripted",
            "submit-1",
            10,
            "ab" * 32,
            expected_project_version=self.pv,
            command_id="permit-a",
        )
        again = self.models.begin_permit(
            granted["assignment_id"],
            "local-scripted",
            "submit-1",
            10,
            "ab" * 32,
            expected_project_version=self.pv,
            command_id="permit-a",
        )
        self.assertEqual(again, begun)
        with self.assertRaisesRegex(Conflict, "submission replay denied"):
            self.permit(granted["assignment_id"], "submit-1", 10)
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM model_permits").fetchone()[0],
            1,
        )
        self.assertEqual(
            self.store.db.execute("SELECT COUNT(*) FROM acceptances").fetchone()[0], 0
        )

    def test_protected_review_allowance_survives_implementation_exhaustion(self):
        self.approve()
        implementation = self.assign()
        review = self.assign(role="review")
        self.permit(implementation["assignment_id"], "impl-1", 800)
        with self.assertRaisesRegex(Conflict, "cumulative limit exhausted"):
            self.permit(implementation["assignment_id"], "impl-2", 1)
        review_permit = self.permit(review["assignment_id"], "review-1", 200)
        self.assertEqual(review_permit["allowance"], "review")
        with self.assertRaisesRegex(Conflict, "cumulative limit exhausted"):
            self.permit(review["assignment_id"], "review-2", 1)
        report = self.models.report(self.project_id, "M1")
        self.assertEqual(report["pending_units"], 1000)
        self.assertEqual(report["implementation_units"], 800)
        self.assertEqual(report["review_units"], 200)
        self.assertEqual(report["protected_review_remaining"], 0)
        self.assertFalse(report["live_eligible"])

    def test_response_loss_keeps_reservation_across_restart(self):
        self.approve()
        granted = self.assign()
        begun = self.permit(granted["assignment_id"], "submit-lost", 125)
        lost = self.models.lose_response(begun["permit_id"], expected_version=1)
        self.assertEqual(lost["quality"], "unknown")
        self.assertEqual(lost["reserved_units"], 125)
        self.assertFalse(lost["duplicate"])
        duplicate = self.models.lose_response(begun["permit_id"], expected_version=2)
        self.assertTrue(duplicate["duplicate"])
        self.store.close()
        self.store = Store(self.path)
        self.app = Coordinator(self.store, Principal("test-developer"))
        self.models = ModelPolicy(self.app)
        report = self.models.report(self.project_id, "M1")
        self.assertEqual(report["unknown_units"], 125)
        self.assertEqual(report["pending_units"], 0)
        self.assertEqual(report["known_units"], 0)
        self.assertEqual(report["reserved_units"], 125)
        with self.assertRaisesRegex(Conflict, "submission replay denied"):
            self.permit(granted["assignment_id"], "submit-lost", 125)

    def test_known_reconcile_releases_unused_reservation_for_a_new_submission(self):
        self.approve()
        granted = self.assign()
        begun = self.permit(granted["assignment_id"], "submit-a", 500)
        observed = self.models.observe_usage(
            begun["permit_id"],
            usage(
                "known",
                320,
                input_tokens=20,
                output_tokens=5,
                provider="scripted-provider",
                resolved_model="scripted-model",
                response_id="response-1",
            ),
            expected_version=1,
        )
        self.assertEqual(observed["state"], "reconciled")
        self.assertEqual(observed["settled_units"], 320)
        self.assertEqual(observed["missing_observed"], [])
        retry = self.permit(granted["assignment_id"], "submit-b", 480)
        self.assertNotEqual(retry["submission_id"], begun["submission_id"])
        with self.assertRaisesRegex(Conflict, "cumulative limit exhausted"):
            self.permit(granted["assignment_id"], "submit-c", 1)
        review = self.assign(role="review")
        self.permit(review["assignment_id"], "review-after-ceiling", 200)
        report = self.models.report(self.project_id, "M1")
        self.assertEqual(report["known_units"], 320)
        self.assertEqual(report["pending_units"], 680)
        self.assertEqual(report["implementation_units"], 800)
        self.assertEqual(report["review_units"], 200)
        self.assertEqual(report["reserved_units"], 1000)
        identity = next(
            item for item in report["assignments"] if item["role"] == "implementation"
        )
        self.assertEqual(identity["missing_observed"], [])
        self.assertEqual(identity["requested"]["model"], "scripted-model")

    def test_estimate_stays_reserved_and_pause_does_not_release_uncertainty(self):
        self.approve()
        granted = self.assign()
        estimated = self.permit(granted["assignment_id"], "submit-est", 100)
        self.models.observe_usage(
            estimated["permit_id"], usage("estimated", 40), expected_version=1
        )
        self.permit(granted["assignment_id"], "submit-open", 50)
        self.app.pause(self.project_id, expected_version=self.pv, reason="inspect cost")
        status = self.app.status(self.project_id)
        states = {
            item["submission_id"]: item["state"] for item in status["model_permits"]
        }
        self.assertEqual(states["submit-est"], "reserved")
        self.assertEqual(states["submit-open"], "held")
        self.assertFalse(status["capabilities"]["task_acceptance"])
        report = status["model_reports"][0]
        self.assertEqual(report["estimated_units"], 40)
        self.assertEqual(report["unknown_units"], 50)
        self.assertEqual(report["reserved_units"], 150)
        self.assertEqual(report["interventions"], 1)
        self.assertFalse(report["live_eligible"])

    def test_conflicting_usage_fences_without_releasing_the_reservation(self):
        self.approve()
        granted = self.assign()
        begun = self.permit(granted["assignment_id"], "submit-conflict", 80)
        self.models.observe_usage(
            begun["permit_id"], usage("known", 80), expected_version=1
        )
        conflict = self.models.observe_usage(
            begun["permit_id"], usage("known", 70), expected_version=2
        )
        self.assertTrue(conflict["conflicting"])
        report = self.models.report(self.project_id, "M1")
        self.assertEqual(report["known_units"], 0)
        self.assertEqual(report["unknown_units"], 80)
        self.assertEqual(report["interventions"], 1)
        self.assertTrue(self.app.status(self.project_id)["project"]["paused"])

    def test_service_principal_cannot_approve_a_policy(self):
        service = ModelPolicy(
            Coordinator(self.store, Principal("broker", role="service"))
        )
        with self.assertRaisesRegex(Invalid, "developer authority required"):
            service.approve_policy(
                self.project_id,
                "M1",
                policy(),
                expected_project_version=self.pv,
                expected_milestone_version=self.mv,
            )

    def test_module_does_not_import_a_provider_client(self):
        source = Path("coordinator/model_policy.py").read_text(encoding="utf-8")
        imports = "\n".join(
            line
            for line in source.splitlines()
            if line.startswith(("import ", "from "))
        )
        for banned in ("socket", "httpx", "urllib", "requests", "openai", "litellm"):
            self.assertNotIn(banned, imports)


if __name__ == "__main__":
    unittest.main()
