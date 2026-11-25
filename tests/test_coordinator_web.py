"""Product HTTP boundaries and command behavior; no listening socket or live adapter."""

import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from coordinator import Store
from coordinator.store import patched_sqlite
from tests.test_coordinator import plan, project

WEB_AVAILABLE = importlib.util.find_spec("fastapi") is not None
if WEB_AVAILABLE:
    from fastapi.testclient import TestClient

    from coordinator.web import create_app, init_token, read_token
    from coordinator.web_security import BODY_LIMIT, COOKIE, Sessions


@unittest.skipUnless(
    WEB_AVAILABLE and patched_sqlite(),
    "requires approved web environment and patched SQLite",
)
class WebTests(unittest.TestCase):
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
        self.csrf = None

    def login(self):
        response = self.client.post(
            "/api/session", json={"token": self.token}, headers={"Origin": self.origin}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.csrf = response.json()["csrf"]
        return response

    def post(self, path, body, *, method="POST", csrf=True):
        headers = {"Origin": self.origin}
        if csrf:
            headers["X-CSRF-Token"] = self.csrf or ""
        return self.client.request(
            method, path, json={"command_id": uuid4().hex, **body}, headers=headers
        )

    def test_login_cookie_protection_expiry_and_logout(self):
        self.assertEqual(self.client.get("/api/projects").status_code, 401)
        login = self.login()
        cookie = login.headers["set-cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=strict", cookie)
        self.assertNotIn(self.token, login.text + cookie)
        self.assertEqual(self.client.get("/api/session").json()["csrf"], self.csrf)
        self.assertEqual(
            self.client.post(
                "/api/logout",
                json={},
                headers={"Origin": self.origin, "X-CSRF-Token": self.csrf},
            ).status_code,
            200,
        )
        self.assertEqual(self.client.get("/api/projects").status_code, 401)

    def test_origin_host_and_fetch_boundaries_precede_mutation(self):
        self.login()
        payload = {"command_id": uuid4().hex, "spec": project()}
        for headers, expected in (
            ({"Origin": "https://example.invalid", "X-CSRF-Token": self.csrf}, 403),
            ({"X-CSRF-Token": self.csrf}, 403),
            (
                {
                    "Origin": self.origin,
                    "Host": "attacker.invalid",
                    "X-CSRF-Token": self.csrf,
                },
                400,
            ),
            (
                {
                    "Origin": self.origin,
                    "Sec-Fetch-Site": "cross-site",
                    "X-CSRF-Token": self.csrf,
                },
                403,
            ),
        ):
            response = self.client.post("/api/projects", json=payload, headers=headers)
            self.assertEqual(response.status_code, expected, response.text)
        self.assertEqual(self.client.get("/api/projects").json()["projects"], [])

    def test_csrf_missing_or_wrong_cannot_create_project(self):
        self.login()
        self.assertEqual(
            self.post("/api/projects", {"spec": project()}, csrf=False).status_code, 403
        )
        self.csrf = "wrong"
        self.assertEqual(
            self.post("/api/projects", {"spec": project()}).status_code, 403
        )
        self.assertEqual(self.client.get("/api/projects").json()["projects"], [])

    def test_request_limits_types_and_duplicate_json_refuse(self):
        self.login()
        headers = {"Origin": self.origin, "X-CSRF-Token": self.csrf}
        self.assertEqual(
            self.client.post(
                "/api/projects",
                content=b"x" * (BODY_LIMIT + 1),
                headers={**headers, "Content-Type": "application/json"},
            ).status_code,
            413,
        )
        self.assertEqual(
            self.client.post(
                "/api/projects",
                content="{}",
                headers={**headers, "Content-Type": "text/plain"},
            ).status_code,
            415,
        )
        for body in ('{"spec":{},"spec":{}}', '{"spec":NaN}', "[]"):
            response = self.client.post(
                "/api/projects",
                content=body,
                headers={**headers, "Content-Type": "application/json"},
            )
            self.assertEqual(response.status_code, 422, response.text)

    def test_exact_plan_approval_and_dependency_blocking_through_api(self):
        self.login()
        created = self.post("/api/projects", {"spec": project()}).json()
        pid = created["project_id"]
        self.assertEqual(
            self.client.get("/api/projects").json()["projects"][0]["id"], pid
        )
        submitted = self.post(
            f"/api/projects/{pid}/plans",
            {"milestone_key": "M1", "spec": plan(), "expected_project_version": 1},
        ).json()
        approval = {
            "digest": "wrong",
            "expected_project_version": 1,
            "expected_milestone_version": 1,
        }
        self.assertEqual(
            self.post(
                f"/api/plans/{submitted['plan_id']}/approve", approval
            ).status_code,
            409,
        )
        approval["digest"] = submitted["digest"]
        approved = self.post(
            f"/api/plans/{submitted['plan_id']}/approve", approval
        ).json()
        claim = {
            "milestone_key": "M1",
            "task_key": "T2",
            "expected_project_version": approved["project_version"],
            "expected_milestone_version": approved["milestone_version"],
        }
        self.assertEqual(
            self.post(f"/api/projects/{pid}/claims", claim).status_code, 409
        )
        claim["task_key"] = "T1"
        attempt = self.post(f"/api/projects/{pid}/claims", claim).json()
        self.assertEqual(
            self.post(
                f"/api/attempts/{attempt['attempt_id']}/scripted-start",
                {"expected_version": 1},
            ).status_code,
            200,
        )
        candidate = self.post(
            f"/api/operations/{attempt['operation_id']}/scripted-result",
            {"outcome": "candidate"},
        ).json()
        self.assertFalse(candidate["task_accepted"])
        status = self.client.get(f"/api/projects/{pid}").json()
        self.assertEqual(
            [t["state"] for t in status["milestones"][0]["tasks"]],
            ["awaiting_verification", "blocked_dependencies"],
        )

    def test_actor_spoof_and_stale_revision_are_refused(self):
        self.login()
        response = self.post(
            "/api/projects", {"spec": project(), "actor": "another-user"}
        )
        self.assertEqual(response.status_code, 422)
        created = self.post("/api/projects", {"spec": project()}).json()
        self.assertEqual(
            self.post(
                f"/api/projects/{created['project_id']}/pause",
                {"expected_version": True, "reason": "invalid boolean"},
            ).status_code,
            422,
        )
        self.assertEqual(
            self.post(
                f"/api/projects/{created['project_id']}/pause",
                {"expected_version": 100, "reason": "stale"},
            ).status_code,
            409,
        )
        events = self.client.get("/api/events?limit=1").json()
        self.assertEqual(events["items"][0]["actor"], "local-web-developer")
        self.assertNotIn(self.token, json.dumps(events))

    def test_login_errors_do_not_echo_credentials_or_validation_inputs(self):
        response = self.client.post(
            "/api/session",
            json={"token": self.token, "unexpected": self.token},
            headers={"Origin": self.origin},
        )
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(self.token, response.text)
        response = self.client.post(
            "/api/session", json={"token": 123}, headers={"Origin": self.origin}
        )
        self.assertEqual(response.status_code, 401)

    def test_headers_assets_and_branded_404_are_local(self):
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn("noindex", home.text)
        self.assertIn("Skip to workspace", home.text)
        self.assertNotIn(self.token, home.text)
        self.assertEqual(home.headers["cache-control"], "no-store")
        self.assertIn("frame-ancestors 'none'", home.headers["content-security-policy"])
        self.assertEqual(self.client.get("/assets/workspace.js").status_code, 200)
        missing = self.client.get("/missing")
        self.assertEqual(missing.status_code, 404)
        self.assertIn("Return to workspace", missing.text)
        self.assertEqual(self.client.get("/api/missing").status_code, 404)

    def test_store_busy_is_structured_without_hidden_retry(self):
        self.login()
        with patch.object(
            self.app.state.coordinator.store,
            "command",
            side_effect=sqlite3.OperationalError("database is locked"),
        ) as command:
            response = self.post("/api/projects", {"spec": project()})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(command.call_count, 1)
        self.assertEqual(response.json()["error"], "StoreUnavailable")

    def test_session_restart_and_expiration_require_new_login(self):
        clock = [0]
        sessions = Sessions(self.token, clock=lambda: clock[0], ttl=10)
        app = create_app(
            self.database, self.token_file, origin=self.origin, sessions=sessions
        )
        with TestClient(app, base_url=self.origin) as client:
            self.assertEqual(
                client.post(
                    "/api/session",
                    json={"token": self.token},
                    headers={"Origin": self.origin},
                ).status_code,
                200,
            )
            old_cookie = client.cookies.get(COOKIE)
            clock[0] = 11
            self.assertEqual(client.get("/api/projects").status_code, 401)
        with TestClient(
            create_app(self.database, self.token_file, origin=self.origin),
            base_url=self.origin,
        ) as client:
            client.cookies.set(COOKIE, old_cookie)
            self.assertEqual(client.get("/api/projects").status_code, 401)

    def test_token_file_creation_is_exclusive(self):
        with self.assertRaises(FileExistsError):
            init_token(self.token_file)


if __name__ == "__main__":
    unittest.main()
