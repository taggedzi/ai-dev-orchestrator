"""Loopback operator surface for scripted promotion and the schema-7 cost report.

HTTP tests are the acceptance. No provider call and no candidate command runs.
"""

import importlib.util
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from uuid import uuid4

from coordinator import Coordinator, Invalid, Principal, Store
from coordinator.store import patched_sqlite
from tests.test_coordinator import (
    GSD_PLANS,
    GSD_SNAPSHOT,
    GSD_SNAPSHOT_SHA256,
    gsd_project,
    plan,
    project,
)
from tests.test_coordinator_model_policy import policy, requested, usage

WEB_AVAILABLE = importlib.util.find_spec("fastapi") is not None
if WEB_AVAILABLE:
    from fastapi.testclient import TestClient

    from coordinator.cli import main
    from coordinator.web import create_app, init_token, read_token


def blank_usage(quality, units=None):
    observed = usage(quality, units)
    observed["input_tokens"] = None
    observed["output_tokens"] = None
    return observed


@unittest.skipUnless(
    WEB_AVAILABLE and patched_sqlite(),
    "requires approved web environment and patched SQLite",
)
class OperatorHttpTests(unittest.TestCase):
    origin = "http://127.0.0.1:8765"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.database = self.root / "store.sqlite"
        Store.create(self.database).close()
        self.token_file = init_token(self.root / "token")
        self.token = read_token(self.token_file)
        self.app = create_app(self.database, self.token_file, origin=self.origin)
        self.client = self.enterContext(TestClient(self.app, base_url=self.origin))
        self.login()

    def login(self):
        response = self.client.post(
            "/api/session", json={"token": self.token}, headers={"Origin": self.origin}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.csrf = response.json()["csrf"]

    def post(self, path, body):
        return self.client.post(
            path,
            json={"command_id": uuid4().hex, **body},
            headers={"Origin": self.origin, "X-CSRF-Token": self.csrf},
        )

    def status(self, project_id):
        response = self.client.get(f"/api/projects/{project_id}")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def assert_capability_off(self, body):
        self.assertFalse(body["capabilities"]["task_acceptance"])
        self.assertFalse(body["live_eligible"])
        self.assertFalse(body["cost"]["live_eligible"])

    def test_dashboard_reads_cost_decisions_and_acceptance_from_the_api(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn('id="cost-units"', page.text)
        self.assertIn('id="pending-decisions"', page.text)
        self.assertIn('id="scripted-acceptance"', page.text)
        self.assertIn("pending decisions", page.text)
        script = self.client.get("/assets/workspace.js")
        self.assertEqual(script.status_code, 200)
        for field in (
            "data.cost[key]",
            "data.pending_decisions",
            "data.scripted_task_accepted",
            "data.capabilities.task_acceptance",
            "data.live_eligible",
            "data.model_reports",
            "project.spec.context.discovery",
        ):
            self.assertIn(field, script.text)
        self.assertIn('id="discovery-turns"', page.text)
        source = (
            Path(__file__)
            .resolve()
            .parents[1]
            .joinpath("coordinator", "application.py")
        )
        text = source.read_text(encoding="utf-8")
        self.assertNotIn("import research", text)
        self.assertNotIn("from research", text)

    def test_status_splits_units_and_promotion_routes_do_not_execute(self):
        created = self.post("/api/projects", {"spec": project()})
        self.assertEqual(created.status_code, 200, created.text)
        project_id = created.json()["project_id"]
        initial = self.status(project_id)
        self.assertEqual(
            initial["cost"],
            {
                "known_units": 0,
                "estimated_units": 0,
                "pending_units": 0,
                "unknown_units": 0,
                "live_eligible": False,
            },
        )
        self.assertEqual(initial["pending_decisions"], [])
        self.assertFalse(initial["scripted_task_accepted"])
        self.assert_capability_off(initial)

        submitted = self.post(
            f"/api/projects/{project_id}/plans",
            {
                "milestone_key": "M1",
                "spec": plan(),
                "expected_project_version": initial["project"]["version"],
            },
        )
        self.assertEqual(submitted.status_code, 200, submitted.text)
        waiting = self.status(project_id)
        self.assertEqual(
            [item["kind"] for item in waiting["pending_decisions"]],
            ["plan_approval"],
        )
        approved = self.post(
            f"/api/plans/{submitted.json()['plan_id']}/approve",
            {
                "digest": submitted.json()["digest"],
                "expected_project_version": submitted.json()["project_version"],
                "expected_milestone_version": submitted.json()["milestone_version"],
            },
        )
        self.assertEqual(approved.status_code, 200, approved.text)
        self.assertEqual(
            [item["kind"] for item in self.status(project_id)["pending_decisions"]],
            ["model_policy"],
        )
        recorded = self.post(
            f"/api/projects/{project_id}/model-policy",
            {
                "milestone_key": "M1",
                "spec": policy(),
                "expected_project_version": approved.json()["project_version"],
                "expected_milestone_version": approved.json()["milestone_version"],
            },
        )
        self.assertEqual(recorded.status_code, 200, recorded.text)
        self.assertFalse(recorded.json()["live_eligible"])
        self.assertFalse(recorded.json()["task_accepted"])
        self.assertEqual(self.status(project_id)["pending_decisions"], [])

        claimed = self.post(
            f"/api/projects/{project_id}/claims",
            {
                "milestone_key": "M1",
                "task_key": "T1",
                "expected_project_version": approved.json()["project_version"],
                "expected_milestone_version": approved.json()["milestone_version"],
            },
        )
        self.assertEqual(claimed.status_code, 200, claimed.text)
        assigned = self.post(
            f"/api/attempts/{claimed.json()['attempt_id']}/model-assignment",
            {
                "role": "implementation",
                "route_id": "local-scripted",
                "requested": requested(),
                "expected_attempt_version": 1,
                "expected_project_version": approved.json()["project_version"],
            },
        )
        self.assertEqual(assigned.status_code, 200, assigned.text)
        self.assertFalse(assigned.json()["live_eligible"])
        permits = {}
        for name, submission, units in (
            ("known", "submit-known", 10),
            ("estimated", "submit-estimated", 6),
            ("pending", "submit-pending", 2),
            ("unknown", "submit-unknown", 5),
        ):
            begun = self.post(
                f"/api/model-assignments/{assigned.json()['assignment_id']}/permit",
                {
                    "route_id": "local-scripted",
                    "submission_id": submission,
                    "reserved_units": units,
                    "request_digest": "ab" * 32,
                    "expected_project_version": approved.json()["project_version"],
                },
            )
            self.assertEqual(begun.status_code, 200, begun.text)
            self.assertFalse(begun.json()["task_accepted"])
            permits[name] = begun.json()["permit_id"]
        known = self.post(
            f"/api/model-permits/{permits['known']}/usage",
            {
                "expected_version": 1,
                "usage": usage(
                    "known",
                    4,
                    input_tokens=1,
                    output_tokens=1,
                    provider="scripted-provider",
                    resolved_model="scripted-model",
                    response_id="response-1",
                ),
            },
        )
        estimated = self.post(
            f"/api/model-permits/{permits['estimated']}/usage",
            {"expected_version": 1, "usage": blank_usage("estimated", 3)},
        )
        unknown = self.post(
            f"/api/model-permits/{permits['unknown']}/lose-response",
            {"expected_version": 1},
        )
        self.assertEqual(known.status_code, 200, known.text)
        self.assertEqual(estimated.status_code, 200, estimated.text)
        self.assertEqual(unknown.status_code, 200, unknown.text)
        self.assertFalse(known.json()["live_eligible"])
        self.assertFalse(known.json()["task_accepted"])

        report = self.client.get(f"/api/projects/{project_id}/milestones/M1/cost")
        self.assertEqual(report.status_code, 200, report.text)
        body = report.json()
        self.assertEqual(body["known_units"], 4)
        self.assertEqual(body["estimated_units"], 3)
        self.assertEqual(body["pending_units"], 2)
        self.assertEqual(body["unknown_units"], 5)
        self.assertFalse(body["live_eligible"])
        self.assertFalse(body["task_accepted"])
        current = self.status(project_id)
        self.assertEqual(current["cost"]["known_units"], 4)
        self.assertEqual(current["cost"]["estimated_units"], 3)
        self.assertEqual(current["cost"]["pending_units"], 2)
        self.assertEqual(current["cost"]["unknown_units"], 5)
        self.assertFalse(current["scripted_task_accepted"])
        self.assert_capability_off(current)
        self.assertEqual(len(current["model_reports"]), 1)

        output = StringIO()
        with redirect_stdout(output):
            code = main(
                [
                    "--db",
                    str(self.database),
                    "cost-report",
                    project_id,
                    "M1",
                ]
            )
        self.assertEqual(code, 0, output.getvalue())
        cli_report = json.loads(output.getvalue())["result"]
        self.assertEqual(cli_report["known_units"], 4)
        self.assertEqual(cli_report["estimated_units"], 3)
        self.assertEqual(cli_report["pending_units"], 2)
        self.assertEqual(cli_report["unknown_units"], 5)
        self.assertFalse(cli_report["task_accepted"])
        self.assertFalse(cli_report["live_eligible"])

        missing = self.root / "missing-repo"
        artifacts = self.root / "missing-artifacts"
        refused = self.post(
            "/api/integration-proposals/missing/promote",
            {
                "expected_version": 1,
                "repository": str(missing),
                "artifacts": str(artifacts),
            },
        )
        self.assertEqual(refused.status_code, 422, refused.text)
        self.assertIn("managed repository", refused.json()["message"])
        for path, extra in (
            (
                "/api/attempts/missing/diverged-head",
                {
                    "previous_head": "a" * 40,
                    "new_head": "b" * 40,
                    "authority_generation": 1,
                },
            ),
            (
                "/api/integration-proposals/missing/regressions",
                {"spec": policy(), "digest": "cd" * 32, "expected_version": 1},
            ),
            (
                "/api/integration-proposals/missing/evidence",
                {"spec": policy(), "digest": "cd" * 32, "expected_version": 1},
            ),
            (
                "/api/integration-proposals/missing/promotion",
                {"expected_version": 1},
            ),
            ("/api/integration-proposals/missing/promotion-reconcile", {}),
        ):
            response = self.post(
                path,
                {**extra, "repository": str(missing), "artifacts": str(artifacts)},
            )
            self.assertEqual(response.status_code, 422, response.text)
            self.assertIn("managed repository", response.json()["message"])
        self.assert_capability_off(self.status(project_id))
        cli_output = StringIO()
        with redirect_stdout(cli_output):
            cli_code = main(
                [
                    "--db",
                    str(self.database),
                    "promotion-promote",
                    "missing",
                    "--expected-version",
                    "1",
                    "--repository",
                    str(missing),
                    "--artifacts",
                    str(artifacts),
                ]
            )
        self.assertEqual(cli_code, 2, cli_output.getvalue())
        self.assertIn("managed repository", cli_output.getvalue())

    def test_discovery_route_returns_the_stored_turns(self):
        created = self.post("/api/projects", {"spec": project()})
        self.assertEqual(created.status_code, 200, created.text)
        project_id = created.json()["project_id"]
        version = self.status(project_id)["project"]["version"]
        first = self.post(
            f"/api/projects/{project_id}/discovery",
            {
                "expected_version": version,
                "question": "Which outcome is durable?",
                "answer": "The stored answer.",
            },
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertTrue(first.json()["needs_new_plan_approval"])
        second = self.post(
            f"/api/projects/{project_id}/discovery",
            {
                "expected_version": first.json()["version"],
                "question": "What still needs approval?",
                "answer": "The exact plan digest.",
            },
        )
        self.assertEqual(second.status_code, 200, second.text)
        body = self.status(project_id)
        self.assertEqual(
            [
                turn["answer"]
                for turn in body["project"]["spec"]["context"]["discovery"]["turns"]
            ],
            ["The stored answer.", "The exact plan digest."],
        )
        self.assert_capability_off(body)
        stale = self.post(
            f"/api/projects/{project_id}/discovery",
            {
                "expected_version": version,
                "question": "May the old version write?",
                "answer": "No.",
            },
        )
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertEqual(
            len(
                self.status(project_id)["project"]["spec"]["context"]["discovery"][
                    "turns"
                ]
            ),
            2,
        )

    def test_service_principal_cannot_open_the_operator_commands(self):
        database = self.root / "service.sqlite"
        store = Store.create(database)
        self.addCleanup(store.close)
        app = Coordinator(store, Principal("local-intake", "service"))
        with self.assertRaisesRegex(Invalid, "developer authority required"):
            app.cost_report("missing", "M1")
        with self.assertRaisesRegex(Invalid, "developer authority required"):
            app.record_discovery(
                "missing",
                expected_version=1,
                question="Who may record discovery?",
                answer="The developer principal.",
            )
        with self.assertRaisesRegex(Invalid, "developer authority required"):
            app.promote(
                "missing",
                expected_version=1,
                repository=self.root / "missing-repo",
                artifacts=self.root / "missing-artifacts",
            )
        with self.assertRaisesRegex(Invalid, "developer authority required"):
            app.import_gsd(
                "missing",
                "M-CLI1",
                GSD_SNAPSHOT,
                GSD_SNAPSHOT_SHA256,
                GSD_PLANS,
                expected_project_version=1,
                baseline_revision="d" * 40,
                max_attempts=1,
                check_timeout_seconds=1,
            )

    def test_plan_import_gsd_route_submits_an_unapproved_plan(self):
        created = self.post("/api/projects", {"spec": gsd_project()})
        self.assertEqual(created.status_code, 200, created.text)
        project_id = created.json()["project_id"]
        body = {
            "milestone_key": "M-CLI1",
            "snapshot": str(GSD_SNAPSHOT),
            "digest": GSD_SNAPSHOT_SHA256,
            "plans": str(GSD_PLANS),
            "expected_project_version": 1,
            "baseline_revision": "a" * 40,
            "max_attempts": 2,
            "check_timeout_seconds": 30,
        }
        imported = self.post(f"/api/projects/{project_id}/plan-import-gsd", body)
        self.assertEqual(imported.status_code, 200, imported.text)
        self.assertFalse(imported.json()["approved"])
        status = self.status(project_id)
        self.assertEqual(len(status["plans"]), 1)
        self.assertIsNone(status["milestones"][0]["approved_plan_id"])
        self.assertEqual(status["plans"][0]["digest"], imported.json()["digest"])
        self.assert_capability_off(status)
        rejected = self.post(
            f"/api/projects/{project_id}/plan-import-gsd",
            {**body, "digest": "0" * 64},
        )
        self.assertEqual(rejected.status_code, 422, rejected.text)
        extra = self.client.post(
            f"/api/projects/{project_id}/plan-import-gsd",
            json={"command_id": uuid4().hex, **body, "actor": "other"},
            headers={"Origin": self.origin, "X-CSRF-Token": self.csrf},
        )
        self.assertEqual(extra.status_code, 422, extra.text)
        self.assertEqual(len(self.status(project_id)["plans"]), 1)


@unittest.skipUnless(
    WEB_AVAILABLE and patched_sqlite() and shutil.which("git"),
    "requires approved web environment, patched SQLite, and Git",
)
class PromotionHttpTests(unittest.TestCase):
    origin = "http://127.0.0.1:8765"

    def setUp(self):
        from tests.test_coordinator_integration import IntegrationTests

        self.fixture = IntegrationTests(
            "test_same_commit_promotes_without_a_second_review"
        )
        try:
            self.fixture.setUp()
        except Exception:
            self.fixture.doCleanups()
            raise

    def tearDown(self):
        self.fixture.doCleanups()

    def test_http_promote_records_one_scripted_acceptance_without_the_capability(self):
        proposal = self.fixture.stage()
        self.fixture.pass_regressions(proposal)
        token_file = init_token(self.fixture.root / "web-token")
        token = read_token(token_file)
        app = create_app(self.fixture.store.path, token_file, origin=self.origin)
        with TestClient(app, base_url=self.origin) as client:
            login = client.post(
                "/api/session",
                json={"token": token},
                headers={"Origin": self.origin},
            )
            self.assertEqual(login.status_code, 200, login.text)
            csrf = login.json()["csrf"]
            promoted = client.post(
                f"/api/integration-proposals/{proposal['id']}/promote",
                json={
                    "command_id": uuid4().hex,
                    "expected_version": proposal["version"],
                    "repository": str(self.fixture.repo.root),
                    "artifacts": str(self.fixture.artifacts.root),
                },
                headers={"Origin": self.origin, "X-CSRF-Token": csrf},
            )
            self.assertEqual(promoted.status_code, 200, promoted.text)
            self.assertTrue(promoted.json()["task_accepted"])
            self.assertFalse(promoted.json()["live_eligible"])
            status = client.get(f"/api/projects/{self.fixture.project_id}")
            self.assertEqual(status.status_code, 200, status.text)
            body = status.json()
            self.assertTrue(body["scripted_task_accepted"])
            self.assertFalse(body["capabilities"]["task_acceptance"])
            self.assertFalse(body["live_eligible"])
            self.assertEqual(body["milestones"][0]["tasks"][0]["state"], "accepted")
            self.assertNotIn(
                "promotion_reconcile",
                [item["kind"] for item in body["pending_decisions"]],
            )
        output = StringIO()
        with redirect_stdout(output):
            code = main(
                [
                    "--db",
                    str(self.fixture.store.path),
                    "promotion-reconcile",
                    proposal["id"],
                    "--repository",
                    str(self.fixture.repo.root),
                    "--artifacts",
                    str(self.fixture.artifacts.root),
                ]
            )
        self.assertEqual(code, 0, output.getvalue())
        reconciled = json.loads(output.getvalue())["result"]
        self.assertTrue(reconciled["duplicate"])
        self.assertTrue(reconciled["task_accepted"])
        self.assertFalse(reconciled["live_eligible"])
