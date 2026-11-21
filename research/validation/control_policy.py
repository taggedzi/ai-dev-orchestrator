"""Frozen M-CLI1 control admission; separate from the fault-injection proxy."""

import copy
import hmac
import http.client
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from urllib.parse import parse_qsl, urlencode
from uuid import UUID

from .bundle import digest, load_json
from .fixture import canonical
from .http_tools import Handler, LocalServer, endpoint, request
from .store import Hold

IMAGE = "f242d7a2b69742fde04385231647c54c57396b251ddfd7a5f34095073970e868"
MAX_READS = 128


def conversation_request(conversation, broker_url="http://127.0.0.1:18080/v1"):
    """Proposed native request; SDK serialization/initialization need measurement."""
    if broker_url != "http://127.0.0.1:18080/v1":
        raise Hold("non-loopback broker requires a separately frozen deployment")
    conversation = str(UUID(str(conversation)))
    return {
        "conversation_id": conversation,
        "workspace": {"kind": "LocalWorkspace", "working_dir": "/workspace/project"},
        "conversation_runtime": "local",
        "worktree": False,
        "worktree_options": None,
        "parent_conversation_id": None,
        "agent_settings": None,
        "agent_profile_id": None,
        "agent": {
            "kind": "Agent",
            "llm": {
                "model": "openai/fixture/model-v1",
                "base_url": broker_url,
                "api_key": "fixture-dummy",
                "auth_type": "api_key",
                "provider_connection_id": None,
                "num_retries": 0,
                "timeout": 30,
                "stream_idle_timeout": 30,
                "max_input_tokens": 32768,
                "max_output_tokens": 6000,
                "api_mode": "chat",
                "capability_overrides": {
                    "supports_vision": False,
                    "supports_prompt_cache": False,
                    "supports_responses_api": False,
                },
                "native_tool_calling": True,
                "disable_vision": True,
                "caching_prompt": False,
                "log_completions": False,
                "stream": False,
                "litellm_extra_body": {},
                "fallback_strategy": None,
            },
            "tools": [
                {
                    "name": "terminal",
                    "params": {
                        "terminal_type": "subprocess",
                        "shell_path": "/bin/bash",
                        "no_change_timeout_seconds": 30,
                    },
                },
                {"name": "file_editor", "params": {}},
            ],
            "include_default_tools": [],
            "mcp_config": {},
            "filter_tools_regex": "^(terminal|file_editor)$",
            "condenser": None,
            "critic": None,
            "tool_concurrency_limit": 1,
            "agent_context": {
                "skills": [],
                "load_user_skills": False,
                "load_public_skills": False,
                "load_project_skills": False,
                "load_memory": False,
                "registered_marketplaces": [],
                "secrets": None,
            },
        },
        "confirmation_policy": {"kind": "NeverConfirm"},
        "security_analyzer": None,
        "initial_message": None,
        "max_iterations": 2,
        "stuck_detection": True,
        "secrets": {},
        "secrets_encrypted": False,
        "tool_module_qualnames": {},
        "client_tools": [],
        "agent_launch_additions": None,
        "agent_definitions": [],
        "plugins": [],
        "hook_config": None,
        "autotitle": False,
        "title_llm_profile": None,
        "max_budget_per_run": None,
        "container": None,
        "tags": {},
        "user_id": None,
        "observability_metadata": {},
        "observability_tags": [],
    }


def checked_create(raw, expected):
    """No normalization or ignored extra field may widen a frozen request."""
    try:
        value = load_json(raw)
    except ValueError as exc:
        raise Hold("invalid create JSON") from exc
    if value != expected or raw != canonical(expected):
        raise Hold("create differs from its exact frozen two-tool request")
    return value


def route(method, target, conversation):
    if len(target) > 2048 or not re.fullmatch(r"[\x21-\x7e]+", target):
        raise Hold("control target bounds")
    base = "/api/conversations/" + conversation
    if method == "POST":
        if target == "/api/conversations":
            return "create"
        if target in {base + "/events", base + "/run"}:
            return "work"
        if target in {base + "/interrupt", base + "/pause"}:
            return "stop"
    if method == "GET":
        path, separator, query = target.partition("?")
        if path in {base, base + "/runtime"} and not separator:
            return "read"
        if path == base + "/events/search":
            if not separator:
                return "read"
            pairs = parse_qsl(query, keep_blank_values=True, strict_parsing=True)
            if (
                len(pairs) == 1
                and pairs[0][0] == "page_id"
                and 0 < len(pairs[0][1]) <= 256
                and re.fullmatch(r"[\x21-\x7e]+", pairs[0][1])
                and urlencode(pairs) == query
            ):
                return "read"
    raise Hold("control method, conversation, route or query denied")


class ControlGate:
    """One fixture conversation, durable intents, no mutation replay or retries."""

    def __init__(self, database, policy, expected_digest, clock=time.time_ns):
        if digest(canonical(policy)) != expected_digest:
            raise Hold("control policy differs from external freeze digest")
        self.policy = copy.deepcopy(policy)
        self.lock = threading.RLock()
        self.clock = clock
        self.conversation = str(UUID(policy["conversation_id"]))
        if self.conversation != policy["conversation_id"]:
            raise Hold("noncanonical conversation identity")
        if (
            type(policy.get("schema_version")) is not int
            or policy["schema_version"] != 1
            or policy.get("image_id") != "sha256:" + IMAGE
            or policy.get("create") != conversation_request(self.conversation)
        ):
            raise Hold("control policy is not the pinned two-tool fixture profile")
        self.grants = policy["mutations"]
        if not 0 < len(self.grants) <= 128:
            raise Hold("control mutation count bound")
        for operation, row in self.grants.items():
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", operation):
                raise Hold("invalid control operation identity")
            kind = route("POST", row["path"], self.conversation)
            if kind != row["kind"] or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]):
                raise Hold("control grant mismatch")
        if type(policy["expires_utc_ns"]) is not int or not re.fullmatch(
            r"[0-9a-f]{64}", policy["control_credential_sha256"]
        ):
            raise Hold("control authority not frozen")
        self.db = sqlite3.connect(
            database, check_same_thread=False, isolation_level=None
        )
        if self.db.execute("PRAGMA journal_mode=WAL").fetchone()[0] != "wal":
            self.db.close()
            raise Hold("control journal requires persistent WAL storage")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript(
            "CREATE TABLE IF NOT EXISTS policy(id INTEGER PRIMARY KEY CHECK(id=1), hash TEXT, fenced INTEGER, reads INTEGER);"
            "CREATE TABLE IF NOT EXISTS mutations(id TEXT PRIMARY KEY, kind TEXT, binding TEXT, state TEXT, status INTEGER, response_sha256 TEXT);"
        )
        try:
            with self.transaction():
                previous = self.db.execute("SELECT hash FROM policy").fetchall()
                if previous and previous != [(expected_digest,)]:
                    raise Hold("control journal belongs to another frozen policy")
                self.db.execute(
                    "INSERT OR IGNORE INTO policy VALUES(1,?,0,0)", (expected_digest,)
                )
        except (OSError, ValueError, sqlite3.Error):
            self.db.close()
            raise

    @contextmanager
    def transaction(self):
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self.db.rollback()
                raise
            else:
                try:
                    self.db.commit()
                except sqlite3.Error:
                    self.db.rollback()
                    raise

    def close(self):
        with self.lock:
            self.db.close()

    def fence(self):
        with self.transaction():
            self.db.execute("UPDATE policy SET fenced=1")

    def admit(self, credential, method, target, raw, operation=""):
        if not hmac.compare_digest(
            digest(credential.encode()), self.policy["control_credential_sha256"]
        ):
            raise Hold("control authentication denied")
        kind = route(method, target, self.conversation)
        binding = digest(canonical([method, target, digest(raw)]))
        if kind == "create":
            checked_create(raw, self.policy["create"])
        if kind == "read":
            if raw or operation:
                raise Hold("read lookup has an unexpected body/operation")
            with self.transaction():
                changed = self.db.execute(
                    "UPDATE policy SET reads=reads+1 WHERE reads<?", (MAX_READS,)
                ).rowcount
            if not changed:
                raise Hold("control lookup count exhausted")
            return kind
        row = self.grants.get(operation)
        if row != {"kind": kind, "path": target, "sha256": digest(raw)}:
            raise Hold("control operation/body grant denied")
        with self.transaction():
            fenced = self.db.execute("SELECT fenced FROM policy").fetchone()[0]
            if kind != "stop" and (
                fenced or self.clock() >= self.policy["expires_utc_ns"]
            ):
                raise Hold("control authority fenced or expired")
            if self.db.execute(
                "SELECT 1 FROM mutations WHERE id=?", (operation,)
            ).fetchone():
                raise Hold("control operation already issued; reconcile read-only")
            if (
                kind != "stop"
                and self.db.execute(
                    "SELECT 1 FROM mutations WHERE state='possible-send'"
                ).fetchone()
            ):
                raise Hold("unresolved control mutation; reconcile read-only")
            if kind == "stop":
                self.db.execute("UPDATE policy SET fenced=1")
            self.db.execute(
                "INSERT INTO mutations VALUES(?,?,?,'possible-send',NULL,NULL)",
                (operation, kind, binding),
            )
        return kind

    def receipt(self, operation, status, raw):
        with self.transaction():
            if (
                self.db.execute(
                    "UPDATE mutations SET state='received',status=?,response_sha256=? WHERE id=? AND state='possible-send'",
                    (status, digest(raw), operation),
                ).rowcount
                != 1
            ):
                raise Hold("control receipt has no matching pending intent")


def control_gate(gate, upstream, backend_key="fixture-dummy", address=("127.0.0.1", 0)):
    """Local conformance transport. Final non-loopback placement is unqualified."""
    endpoint(upstream)
    if backend_key != "fixture-dummy" or hmac.compare_digest(
        digest(backend_key.encode()), gate.policy["control_credential_sha256"]
    ):
        raise Hold("fixture control and disposable backend credentials must differ")

    class Control(Handler):
        def dispatch(self):
            try:
                allowed = {
                    "host",
                    "authorization",
                    "x-fixture-operation",
                    "content-length",
                    "content-type",
                    "accept",
                    "accept-encoding",
                    "user-agent",
                }
                if any(name.lower() not in allowed for name in self.headers):
                    raise Hold("control header denied")
                for name in allowed:
                    if len(self.headers.get_all(name, [])) > 1:
                        raise Hold("duplicate control header")
                auth = self.headers.get("Authorization", "")
                if not auth.startswith("Bearer "):
                    raise Hold("control authentication denied")
                raw = self.body() if self.command == "POST" else b""
                if self.command == "GET" and (
                    self.headers.get("Transfer-Encoding")
                    or self.headers.get("Content-Length", "0") != "0"
                ):
                    raise Hold("read request framing denied")
                operation = self.headers.get("X-Fixture-Operation", "")
                kind = gate.admit(
                    auth.removeprefix("Bearer "),
                    self.command,
                    self.path,
                    raw,
                    operation,
                )
                headers = {
                    "Content-Type": "application/json",
                    "X-Session-API-Key": backend_key,
                }
                if kind != "read":
                    headers["X-Fixture-Operation"] = operation
                status, response, content_type = request(
                    upstream,
                    self.command,
                    self.path,
                    raw,
                    headers,
                )
                if kind != "read":
                    gate.receipt(operation, status, response)
                self.reply(status, response, content_type)
            except Hold as exc:
                self.reject(403, str(exc))
            except (ValueError, TypeError) as exc:
                self.reject(400, str(exc))
            except sqlite3.Error:
                self.reject(503, "control journal unavailable; mutation is not retried")
            except (OSError, http.client.HTTPException):
                self.reject(502, "control delivery uncertain; mutation is not retried")

        do_GET = dispatch
        do_POST = dispatch

    return LocalServer(address, Control)
