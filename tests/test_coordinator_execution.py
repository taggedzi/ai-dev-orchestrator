"""Disabled OpenHands boundary and labeled scripted-double evidence."""

import ast
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from coordinator import Coordinator, Principal, Store
from coordinator.store import SCHEMA_VERSION, patched_sqlite
from integrations.openhands import (
    COMMIT,
    LIVE_DISPATCH_REFUSAL,
    PRODUCT,
    VERSION,
    LiveDispatchRefused,
    OpenHandsClient,
    ScriptedResultRefused,
    scripted_result,
)
from tests.test_coordinator import plan, project

REVIEWED_OPERATIONS = (
    "create",
    "send_message",
    "run",
    "pause",
    "interrupt",
    "lookup",
    "attach",
    "resume",
    "stream_events",
    "search_events",
    "fetch_artifacts",
    "close",
    "delete",
    "respond_to_confirmation",
)


@unittest.skipUnless(
    patched_sqlite(), "product persistence requires a patched SQLite runtime"
)
class ExecutionBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "product.sqlite"
        self.store = Store.create(self.path)
        self.addCleanup(lambda: self.store.close() if self.store is not None else None)
        self.app = Coordinator(self.store, Principal("test-developer"))
        self.project_id = self.app.create_project(project())["project_id"]

    def approve_and_claim(self):
        submitted = self.app.submit_plan(
            self.project_id, "M1", plan(), expected_project_version=1
        )
        approved = self.app.approve_plan(
            submitted["plan_id"],
            submitted["digest"],
            expected_project_version=1,
            expected_milestone_version=submitted["milestone_version"],
        )
        return self.app.claim_task(
            self.project_id,
            "M1",
            "T1",
            expected_project_version=approved["project_version"],
            expected_milestone_version=approved["milestone_version"],
        )

    def test_every_live_dispatch_refuses_before_socket_and_retains_no_secret(self):
        self.assertEqual(PRODUCT, "OpenHands Agent Server")
        self.assertEqual(VERSION, "1.62.0")
        self.assertEqual(COMMIT, "504a88cab0fb48ee5226238ad7b8f1d865fa84a8")
        api_key = "fake-openhands-key-m5"
        with patch("socket.socket") as socket_type:
            for operation in (*REVIEWED_OPERATIONS, "unknown-operation"):
                with self.subTest(operation=operation):
                    with self.assertRaises(LiveDispatchRefused) as raised:
                        OpenHandsClient().dispatch(
                            operation,
                            base_url="http://127.0.0.1:9",
                            workspace="ignored-workspace",
                            conversation_id="ignored-conversation",
                            api_key=api_key,
                        )
                    self.assertEqual(str(raised.exception), LIVE_DISPATCH_REFUSAL)
                    refusal = raised.exception.refusal
                    self.assertTrue(refusal["refused"])
                    self.assertFalse(refusal["live_eligible"])
                    self.assertNotIn("capabilities", refusal)
                    if operation in ("attach", "resume"):
                        self.assertIn("automatic resume is disabled", refusal["reason"])
            socket_type.assert_not_called()
        self.assertNotIn(api_key, json.dumps(self.app.status(self.project_id)))
        self.assertNotIn(api_key.encode(), self.path.read_bytes())

    def test_coordinator_refusal_preserves_capabilities_and_attempt_count(self):
        self.approve_and_claim()
        before = self.app.status(self.project_id)
        before_events = self.store.db.execute("SELECT COUNT(*) FROM events").fetchone()[
            0
        ]
        refusal = self.app.refuse_live_dispatch(self.project_id, "create")
        self.assertTrue(refusal["refused"])
        self.assertFalse(refusal["live_eligible"])
        after = self.app.status(self.project_id)
        self.assertFalse(after["live_eligible"])
        self.assertFalse(after["capabilities"]["task_acceptance"])
        self.assertFalse(after["capabilities"]["native_execution"])
        self.assertEqual(len(after["attempts"]), len(before["attempts"]))
        self.assertEqual(after, before)
        after_events = self.store.db.execute("SELECT COUNT(*) FROM events").fetchone()[
            0
        ]
        self.assertEqual(after_events, before_events)

    def test_scripted_double_is_labeled_and_cannot_enable_live_capabilities(self):
        before = self.app.status(self.project_id)
        for outcome in ("candidate", "failed"):
            with self.subTest(outcome=outcome):
                self.assertEqual(
                    scripted_result("scripted", outcome),
                    {
                        "outcome": outcome,
                        "simulated": True,
                        "adapter": "scripted",
                        "label": "scripted-development",
                        "live_eligible": False,
                        "task_acceptance": False,
                        "resolved_model": "scripted/model-v1",
                        "resolved_provider": "scripted-local",
                        "cost_kind": "simulated",
                        "cost": 0,
                    },
                )
        for caller in ("openhands", "live"):
            with self.subTest(caller=caller), self.assertRaises(ScriptedResultRefused):
                scripted_result(caller, "candidate")
        for payload in (
            {"live_eligible": True},
            {"task_acceptance": True},
            {"capabilities": {"task_acceptance": True}},
        ):
            with (
                self.subTest(payload=payload),
                self.assertRaises(ScriptedResultRefused),
            ):
                scripted_result("scripted", "candidate", **payload)
        with self.assertRaises(ScriptedResultRefused):
            scripted_result("scripted", "success")
        after = self.app.status(self.project_id)
        self.assertFalse(after["live_eligible"])
        self.assertFalse(after["capabilities"]["task_acceptance"])
        self.assertEqual(after, before)

    def test_source_boundaries_exclude_research_network_and_process_imports(self):
        root = Path(__file__).resolve().parents[1]
        sources = sorted((root / "coordinator").glob("*.py")) + sorted(
            (root / "integrations").glob("*.py")
        )
        for path in sources:
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("import research", source, path)
            self.assertNotIn("from research", source, path)
        forbidden = {
            "socket",
            "urllib",
            "http.client",
            "httpx",
            "requests",
            "websockets",
            "subprocess",
            "asyncio.open_connection",
        }
        for path in sorted((root / "integrations").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    names = [module]
                    names.extend(f"{module}.{alias.name}" for alias in node.names)
                for name in names:
                    self.assertNotIn(name, forbidden, path)
                    self.assertFalse(name.startswith("urllib."), path)
                if (
                    isinstance(node, ast.Attribute)
                    and node.attr == "open_connection"
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "asyncio"
                ):
                    self.fail(f"forbidden connection call in {path}")

    def test_service_principal_gets_same_refusal_without_store_changes(self):
        before = self.app.status(self.project_id)
        tables = ("attempts", "operations", "observations", "commands", "events")
        before_counts = {
            table: self.store.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in tables
        }
        developer_refusal = self.app.refuse_live_dispatch(self.project_id, "run")
        service = Coordinator(self.store, Principal("execution-service", "service"))
        service_refusal = service.refuse_live_dispatch(self.project_id, "run")
        self.assertEqual(service_refusal, developer_refusal)
        self.assertFalse(service_refusal["live_eligible"])
        self.assertEqual(self.app.status(self.project_id), before)
        for table, count in before_counts.items():
            self.assertEqual(
                self.store.db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],
                count,
            )

    def test_existing_scripted_claim_start_and_result_stay_development_only(self):
        self.assertEqual(SCHEMA_VERSION, 7)
        claim = self.approve_and_claim()
        self.assertEqual(claim["adapter"], "scripted")
        claimed = self.app.status(self.project_id)["attempts"][0]
        self.assertEqual(claimed["assignment"]["profile"], "scripted-development-v1")
        self.assertEqual(
            claimed["assignment"]["reason"],
            "development-only; no live adapter qualified",
        )
        with patch("integrations.openhands.scripted_result") as double:
            started = self.app.start_scripted(claim["attempt_id"], expected_version=1)
            result = self.app.record_scripted_result(claim["operation_id"], "candidate")
        double.assert_not_called()
        self.assertTrue(started["simulated"])
        self.assertTrue(result["simulated"])
        self.assertFalse(result["task_accepted"])
        status = self.app.status(self.project_id)
        attempt = status["attempts"][0]
        self.assertEqual(attempt["adapter"], "scripted")
        self.assertEqual(attempt["result"]["resolved_model"], "scripted/model-v1")
        self.assertEqual(attempt["result"]["resolved_provider"], "scripted-local")
        self.assertEqual(attempt["result"]["cost_kind"], "simulated")
        self.assertEqual(attempt["result"]["cost"], 0)
        self.assertFalse(status["live_eligible"])
        self.assertFalse(status["capabilities"]["task_acceptance"])
        self.assertFalse(status["capabilities"]["native_execution"])


if __name__ == "__main__":
    unittest.main()
