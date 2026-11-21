"""Control admission, durable uncertainty and byte-boundary conformance."""

import copy
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from research.validation.bundle import digest
from research.validation.control_policy import (
    IMAGE,
    ControlGate,
    control_gate,
    conversation_request,
    route,
)
from research.validation.fixture import canonical
from research.validation.http_tools import Handler, LocalServer, fault_proxy, request
from research.validation.store import Hold, Store

CONVERSATION = "12345678-1234-4234-8234-123456789abc"
BASE = "/api/conversations/" + CONVERSATION
CREDENTIAL = "synthetic-control-credential-not-a-provider-key"


@contextmanager
def serving(server):
    server.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def policy():
    body = conversation_request(CONVERSATION)
    return {
        "schema_version": 1,
        "image_id": "sha256:" + IMAGE,
        "conversation_id": CONVERSATION,
        "create": body,
        "expires_utc_ns": 100,
        "control_credential_sha256": digest(CREDENTIAL.encode()),
        "mutations": {
            "create": {
                "kind": "create",
                "path": "/api/conversations",
                "sha256": digest(canonical(body)),
            },
            "run": {"kind": "work", "path": BASE + "/run", "sha256": digest(b"{}")},
            "run-other": {
                "kind": "work",
                "path": BASE + "/run",
                "sha256": digest(b"{}"),
            },
            "stop": {
                "kind": "stop",
                "path": BASE + "/interrupt",
                "sha256": digest(b"{}"),
            },
        },
    }


class ControlPolicyTests(unittest.TestCase):
    def gate(self, database, value=None):
        value = value or policy()
        return ControlGate(database, value, digest(canonical(value)), clock=lambda: 1)

    def test_journal_cannot_be_ephemeral_or_rebound_to_another_policy(self):
        with self.assertRaises(Hold):
            self.gate(":memory:")
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "journal.db"
            self.gate(path).close()
            changed = policy()
            changed["expires_utc_ns"] = 101
            with self.assertRaises(Hold):
                self.gate(path, changed)

    def test_disposable_backend_key_cannot_authenticate_control_ingress(self):
        value = policy()
        value["control_credential_sha256"] = digest(b"fixture-dummy")
        with tempfile.TemporaryDirectory() as temp:
            gate = self.gate(Path(temp) / "journal.db", value)
            try:
                with self.assertRaises(Hold):
                    control_gate(gate, "http://127.0.0.1:1")
            finally:
                gate.close()

    def test_expanded_create_profiles_cannot_be_frozen_or_sent(self):
        value = policy()
        for path, replacement in [
            (("client_tools",), [{"name": "unsafe"}]),
            (("tool_module_qualnames",), {"unsafe": "os"}),
            (("plugins",), [{"source": "unapproved"}]),
            (("hook_config",), {"hooks": {"Stop": ["command"]}}),
            (("agent", "include_default_tools"), ["FinishTool"]),
            (("agent", "tools"), [{"name": "task", "params": {}}]),
            (("agent", "llm", "num_retries"), 1),
            (("agent", "llm", "base_url"), "http://unapproved.invalid"),
            (("agent", "agent_context", "load_public_skills"), True),
            (("autotitle",), True),
            (("agent_settings",), {"agent_kind": "ACPAgent"}),
        ]:
            changed = copy.deepcopy(value)
            parent = changed["create"]
            for field in path[:-1]:
                parent = parent[field]
            parent[path[-1]] = replacement
            with (
                self.subTest(path=path),
                tempfile.TemporaryDirectory() as temp,
                self.assertRaises(Hold),
            ):
                self.gate(Path(temp) / "journal.db", changed)
        with tempfile.TemporaryDirectory() as temp:
            gate = self.gate(Path(temp) / "journal.db")
            try:
                raw = canonical(value["create"])
                with self.assertRaises(Hold):
                    gate.admit(
                        CREDENTIAL, "POST", "/api/conversations", raw + b" ", "create"
                    )
                with self.assertRaises(Hold):
                    gate.admit(
                        CREDENTIAL,
                        "POST",
                        "/api/conversations",
                        b'{"conversation_id":"x","conversation_id":"y"}',
                        "create",
                    )
            finally:
                gate.close()

    def test_methods_cross_conversation_encoding_queries_and_upgrade_routes_are_denied(
        self,
    ):
        for method, path in [
            ("GET", BASE + "/run"),
            ("POST", BASE),
            ("POST", BASE + "/children"),
            ("POST", BASE + "/load_plugin"),
            ("POST", "/api/mcp/test"),
            ("POST", "/api/conversations"),
            ("GET", "/api/settings"),
            ("GET", BASE + "/events/search?page_id=one&page_id=two"),
            ("GET", BASE + "/events/search?unknown=value"),
            ("GET", BASE + "/events/search?page_id=%2f"),
            ("GET", BASE + "/events/search?page_id=one#frag"),
            ("GET", BASE.replace("abc", "abd")),
            ("GET", BASE + "/events/search\r\nX-Test: injected"),
        ]:
            if (method, path) == ("POST", "/api/conversations"):
                continue
            with (
                self.subTest(method=method, path=path),
                self.assertRaises((Hold, ValueError)),
            ):
                route(method, path, CONVERSATION)
        self.assertEqual(
            route("GET", BASE + "/events/search?page_id=opaque%2Fcursor", CONVERSATION),
            "read",
        )

    def test_pending_mutation_and_replay_survive_restart_but_stop_remains_possible(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "journal.db"
            gate = self.gate(path)
            gate.admit(CREDENTIAL, "POST", BASE + "/run", b"{}", "run")
            gate.close()
            gate = self.gate(path)
            try:
                with self.assertRaises(Hold):
                    gate.admit(CREDENTIAL, "POST", BASE + "/run", b"{}", "run")
                with self.assertRaises(Hold):
                    gate.admit(CREDENTIAL, "POST", BASE + "/run", b"{}", "run-other")
                gate.fence()
                self.assertEqual(
                    gate.admit(CREDENTIAL, "POST", BASE + "/interrupt", b"{}", "stop"),
                    "stop",
                )
                gate.receipt("stop", 200, b"{}")
                self.assertEqual(gate.admit(CREDENTIAL, "GET", BASE, b""), "read")
                with self.assertRaises(Hold):
                    gate.admit(CREDENTIAL, "POST", BASE + "/run", b"{}", "run-other")
            finally:
                gate.close()

    def test_two_journal_connections_cannot_admit_two_inflight_mutations(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "journal.db"
            first = self.gate(path)
            second = self.gate(path)
            barrier = threading.Barrier(2)

            def admit(gate, operation):
                barrier.wait()
                try:
                    gate.admit(CREDENTIAL, "POST", BASE + "/run", b"{}", operation)
                    return "admitted"
                except Hold:
                    return "held"

            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    a = pool.submit(admit, first, "run")
                    b = pool.submit(admit, second, "run-other")
                    self.assertEqual(
                        sorted([a.result(), b.result()]), ["admitted", "held"]
                    )
            finally:
                first.close()
                second.close()

    def test_auth_expiry_fencing_and_read_budget_are_independent(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "journal.db"
            gate = self.gate(path)
            try:
                with self.assertRaises(Hold):
                    gate.admit("fixture-dummy", "POST", BASE + "/run", b"{}", "run")
                gate.clock = lambda: 100
                with self.assertRaises(Hold):
                    gate.admit(CREDENTIAL, "POST", BASE + "/run", b"{}", "run")
                with patch("research.validation.control_policy.MAX_READS", 1):
                    gate.admit(CREDENTIAL, "GET", BASE, b"")
                    with self.assertRaises(Hold):
                        gate.admit(CREDENTIAL, "GET", BASE, b"")
                gate.admit(CREDENTIAL, "POST", BASE + "/interrupt", b"{}", "stop")
            finally:
                gate.close()

    def test_http_gate_blocks_unapproved_sends_and_replaces_private_auth(self):
        seen = []

        class Backend(Handler):
            def do_POST(self):
                seen.append(
                    (
                        self.path,
                        self.headers.get("Authorization"),
                        self.headers.get("X-Session-API-Key"),
                        self.body(),
                    )
                )
                self.reply(200, b"{}")

        with tempfile.TemporaryDirectory() as temp:
            gate = self.gate(Path(temp) / "journal.db")
            try:
                with (
                    serving(LocalServer(("127.0.0.1", 0), Backend)) as backend,
                    serving(control_gate(gate, backend)) as server,
                ):
                    headers = {
                        "Authorization": "Bearer " + CREDENTIAL,
                        "X-Fixture-Operation": "create",
                    }
                    raw = canonical(policy()["create"])
                    self.assertEqual(
                        request(server, "POST", "/api/conversations", raw, headers)[0],
                        200,
                    )
                    self.assertEqual(
                        request(server, "POST", "/api/conversations", raw, headers)[0],
                        403,
                    )
                    self.assertEqual(
                        request(server, "POST", "/api/settings", b"{}", headers)[0],
                        403,
                    )
                    headers["Upgrade"] = "websocket"
                    self.assertEqual(
                        request(server, "POST", BASE + "/run", b"{}", headers)[0],
                        403,
                    )
                    headers.pop("Upgrade")
                    headers["authorization"] = headers["Authorization"]
                    self.assertEqual(
                        request(server, "POST", BASE + "/run", b"{}", headers)[0],
                        403,
                    )
                self.assertEqual(len(seen), 1)
                self.assertIsNone(seen[0][1])
                self.assertEqual(seen[0][2], "fixture-dummy")
            finally:
                gate.close()

    def test_lost_backend_ack_is_journaled_and_never_automatically_reissued(self):
        seen = []

        class DisconnectingBackend(Handler):
            def do_POST(self):
                seen.append((self.path, self.body()))
                self.close_connection = True

        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "journal.db"
            gate = self.gate(database)
            try:
                with (
                    serving(
                        LocalServer(("127.0.0.1", 0), DisconnectingBackend)
                    ) as backend,
                    serving(control_gate(gate, backend)) as server,
                ):
                    headers = {
                        "Authorization": "Bearer " + CREDENTIAL,
                        "X-Fixture-Operation": "run",
                    }
                    self.assertEqual(
                        request(server, "POST", BASE + "/run", b"{}", headers)[0], 502
                    )
                    self.assertEqual(
                        request(server, "POST", BASE + "/run", b"{}", headers)[0], 403
                    )
                    headers["X-Fixture-Operation"] = "run-other"
                    self.assertEqual(
                        request(server, "POST", BASE + "/run", b"{}", headers)[0], 403
                    )
                self.assertEqual(seen, [(BASE + "/run", b"{}")])
                self.assertEqual(
                    gate.db.execute(
                        "SELECT state FROM mutations WHERE id='run'"
                    ).fetchone()[0],
                    "possible-send",
                )
            finally:
                gate.close()
            resumed = self.gate(database)
            try:
                with self.assertRaises(Hold):
                    resumed.admit(CREDENTIAL, "POST", BASE + "/run", b"{}", "run-other")
            finally:
                resumed.close()

    def test_receipt_storage_failure_preserves_possible_send_after_backend_effect(self):
        seen = []

        class Backend(Handler):
            def do_POST(self):
                seen.append(self.body())
                self.reply(200, b"{}")

        with tempfile.TemporaryDirectory() as temp:
            gate = self.gate(Path(temp) / "journal.db")
            try:
                with (
                    serving(LocalServer(("127.0.0.1", 0), Backend)) as backend,
                    serving(control_gate(gate, backend)) as server,
                    patch.object(
                        gate,
                        "receipt",
                        side_effect=sqlite3.OperationalError(
                            "synthetic storage failure"
                        ),
                    ),
                ):
                    headers = {
                        "Authorization": "Bearer " + CREDENTIAL,
                        "X-Fixture-Operation": "run",
                    }
                    self.assertEqual(
                        request(server, "POST", BASE + "/run", b"{}", headers)[0], 503
                    )
                    self.assertEqual(
                        request(server, "POST", BASE + "/run", b"{}", headers)[0], 403
                    )
                self.assertEqual(seen, [b"{}"])
                self.assertEqual(
                    gate.db.execute(
                        "SELECT state FROM mutations WHERE id='run'"
                    ).fetchone()[0],
                    "possible-send",
                )
            finally:
                gate.close()

    def test_fault_proxy_retains_independent_receipt_when_gate_ack_is_lost(self):
        seen = []

        class Backend(Handler):
            def do_POST(self):
                seen.append(
                    (
                        self.headers.get("Authorization"),
                        self.headers.get("X-Session-API-Key"),
                        self.body(),
                    )
                )
                self.reply(200, b"{}")

        with tempfile.TemporaryDirectory() as temp:
            gate = self.gate(Path(temp) / "gate.db")
            observer = Store(Path(temp) / "observer.db")
            try:
                with (
                    serving(LocalServer(("127.0.0.1", 0), Backend)) as backend,
                    serving(
                        fault_proxy(observer, backend, {"create": "after-response"})
                    ) as proxy,
                    serving(control_gate(gate, proxy)) as server,
                ):
                    raw = canonical(policy()["create"])
                    headers = {
                        "Authorization": "Bearer " + CREDENTIAL,
                        "X-Fixture-Operation": "create",
                    }
                    self.assertEqual(
                        request(server, "POST", "/api/conversations", raw, headers)[0],
                        502,
                    )
                    self.assertEqual(
                        request(server, "POST", "/api/conversations", raw, headers)[0],
                        403,
                    )
                self.assertEqual(len(seen), 1)
                self.assertIsNone(seen[0][0])
                self.assertEqual(seen[0][1], "fixture-dummy")
                receipt = observer.db.execute(
                    "SELECT state,status FROM operations WHERE id='create'"
                ).fetchone()
                self.assertNotEqual(receipt[0], "possible-send")
                self.assertEqual(receipt[1], 200)
                self.assertEqual(
                    gate.db.execute(
                        "SELECT state FROM mutations WHERE id='create'"
                    ).fetchone()[0],
                    "possible-send",
                )
            finally:
                gate.close()
                observer.close()


if __name__ == "__main__":
    unittest.main()
