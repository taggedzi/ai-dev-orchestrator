"""Preparation checks; never start an executor, provider or VM."""

import http.client
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from uuid import uuid4

from research.validation.bundle import (
    SEED_OID,
    SEED_TREE,
    blind_packets,
    build,
    digest,
    inventory,
    verify,
)
from research.validation.checks import grade, scope
from research.validation.driver import (
    Driver,
    deployment_template,
    qualified_profile,
    report,
)
from research.validation.fixture import canonical
from research.validation.http_tools import (
    LocalServer,
    broker,
    endpoint,
    fault_proxy,
    request,
)
from research.validation.observe import markers, release_gate, seal, wait_marker
from research.validation.store import Hold, Store
from research.validation.supervisor import LeaseSupervisor


class BundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="mcli1-bundle-tests-")
        cls.root = Path(cls.temporary.name)
        cls.bundle = cls.root / "bundle"
        cls.manifest = build(cls.bundle)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_seed_matches_published_objects_and_hashes(self):
        seed = self.manifest["objects"]["S0"]
        self.assertEqual(seed["oid"], SEED_OID)
        self.assertEqual(seed["tree"], SEED_TREE)
        hashes = {
            "package.json": "7b22fdfad7b2ee86575edee3ae4fcf3985c0d08a23c288099225ff023280ba17",
            "src/name-policy.js": "26b4787bdaff26b8759c92e6b2c4805288fff665cebf97a2017553d30576eeb0",
            "test/name-policy.test.js": "67186a1b14e36409fbdf6231ac3330c946f26a861246a86ca72a6155e0d2ff50",
        }
        for path, expected in hashes.items():
            self.assertEqual(
                digest((self.bundle / "sources/S0" / path).read_bytes()), expected
            )

    def test_rebuild_is_byte_identical_and_never_overwrites(self):
        other = self.root / "rebuild"
        build(other)
        self.assertEqual(inventory(other), inventory(self.bundle))
        self.assertEqual(
            (other / "manifest.json").read_bytes(),
            (self.bundle / "manifest.json").read_bytes(),
        )
        with self.assertRaises(FileExistsError):
            build(other)

    @unittest.skipUnless(shutil.which("git"), "Git not installed")
    def test_real_git_reads_and_validates_objects(self):
        environment = dict(
            os.environ,
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_SYSTEM=os.devnull,
            GIT_CONFIG_COUNT="0",
            GIT_NO_REPLACE_OBJECTS="1",
        )
        for key in (
            "GIT_DIR",
            "GIT_WORK_TREE",
            "GIT_OBJECT_DIRECTORY",
            "GIT_ALTERNATE_OBJECT_DIRECTORIES",
            "GIT_COMMON_DIR",
        ):
            environment.pop(key, None)
        args = ["git", "--git-dir=" + str(self.bundle / "git")]
        result = subprocess.run(
            args + ["fsck", "--full", "--strict"],
            capture_output=True,
            env=environment,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run(
            args + ["rev-parse", "refs/heads/milestone"],
            capture_output=True,
            env=environment,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.stdout.strip().decode(), SEED_OID)

    def test_manifest_detects_tamper_extra_and_missing_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            copy = Path(temporary) / "bundle"
            shutil.copytree(self.bundle, copy)
            self.assertEqual(verify(copy)["fixture"], "M-CLI1")
            file = copy / "sources/C1/src/validate.js"
            original = file.read_bytes()
            file.write_bytes(original + b"\n")
            with self.assertRaises(ValueError):
                verify(copy)
            file.write_bytes(original)
            extra = copy / "extra"
            extra.write_bytes(b"extra")
            with self.assertRaises(ValueError):
                verify(copy)
            extra.unlink()
            file.unlink()
            with self.assertRaises(ValueError):
                verify(copy)

    def test_unapproved_deployment_fails_closed(self):
        profile = deployment_template(
            digest((self.bundle / "manifest.json").read_bytes())
        )
        with self.assertRaises(Hold):
            qualified_profile(self.bundle, profile)

    def test_external_freeze_digest_is_required_to_detect_manifest_rewrite(self):
        with self.assertRaises(ValueError):
            verify(self.bundle, expected_digest="0" * 64)

    def test_blind_packets_separate_labels_and_preserve_subjects(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "blind"
            blind_packets(self.bundle, root, 42)
            labels = json.loads((root / "trusted-index.json").read_bytes())
            self.assertEqual(len(labels["mapping"]), 8)
            for packet, row in labels["mapping"].items():
                metadata = json.loads(
                    (root / "packets" / packet / "packet.json").read_bytes()
                )
                self.assertNotIn("expected", metadata)
                self.assertNotIn("original_packet", metadata)
                self.assertEqual(metadata["subject"]["oid"], row["subject"]["oid"])
                self.assertEqual(metadata["subject"]["message"], "Review candidate")

    @unittest.skipUnless(shutil.which("node"), "Node not installed")
    def test_clean_gold_passes_and_scope_preserves_existing_files(self):
        for task, base, name in (("T-01", "S0", "C1"), ("T-02", "C1", "C2")):
            row = grade(
                self.bundle / "sources" / name, task, integrated=True, review=True
            )
            self.assertTrue(row["pass"], row)
            self.assertTrue(
                scope(
                    self.bundle / "sources" / base, self.bundle / "sources" / name, task
                )
            )

    @unittest.skipUnless(shutil.which("node"), "Node not installed")
    def test_rejection_escapes_candidate_checks_but_review_reproduces_it(self):
        source = self.bundle / "sources/B1-rejected"
        self.assertTrue(grade(source, "T-01")["pass"])
        row = grade(source, "T-01", review=True)
        self.assertFalse(row["pass"])
        self.assertIn(
            "review-mixed-blank", [r["check"] for r in row["checks"] if not r["pass"]]
        )

    @unittest.skipUnless(shutil.which("node"), "Node not installed")
    def test_integration_only_regression_and_correction(self):
        self.assertTrue(grade(self.bundle / "sources/C-D", "T-01", review=True)["pass"])
        row = grade(self.bundle / "sources/I-D", "T-01", integrated=True)
        self.assertFalse(row["pass"])
        self.assertIn(
            "repeat-blank-v1", [r["check"] for r in row["checks"] if not r["pass"]]
        )
        self.assertTrue(
            grade(self.bundle / "sources/I-D-corrected", "T-01", integrated=True)[
                "pass"
            ]
        )

    @unittest.skipUnless(shutil.which("node"), "Node not installed")
    def test_review_corpus_expected_cases_and_scope(self):
        labels = json.loads(
            (self.bundle / "review-corpus/adjudication.json").read_bytes()
        )
        for packet, row in labels.items():
            source = self.bundle / "review-corpus" / packet
            base = self.bundle / "sources" / ("S0" if row["task"] == "T-01" else "C1")
            accepted = grade(source, row["task"], review=True)["pass"] and scope(
                base, source, row["task"]
            )
            self.assertEqual(accepted, row["expected"] == "pass", packet)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="mcli1-journal-")
        self.path = Path(self.temporary.name) / "audit.sqlite"
        self.store = Store(self.path)

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def submit(self, permit, role, actual, task="T-01", attempt="A1", bound=None):
        bound = (
            bound
            or {
                "edit": 240000,
                "correction": 160000,
                "finish": 80000,
                "review": 120000,
            }[role]
        )
        request_hash = digest(permit.encode())
        self.store.reserve(permit, task, attempt, role, request_hash, bound)
        self.store.consume(request_hash)
        self.store.settle(permit, actual, "gen-" + permit)

    def test_uncertain_delivery_blocks_old_and_new_mutations_after_restart(self):
        self.store.begin("op1", "hash")
        self.store.close()
        self.store = Store(self.path)
        for operation in ("op1", "op2"):
            with self.assertRaises(Hold):
                self.store.begin(operation, "hash")
        self.store.receipt("op1", 201, b"{}")
        self.store.receipt("op1", 201, b"{}")
        self.store.begin("op2", "other")
        self.assertEqual(
            len([r for r in self.store.audit() if r["kind"] == "operation-receipt"]), 1
        )

    def test_pause_persists_and_stale_authority_is_rejected(self):
        self.store.fence("pause")
        self.store.close()
        self.store = Store(self.path)
        with self.assertRaises(Hold):
            self.store.begin("op", "hash")
        with self.assertRaises(Hold):
            self.store.reserve("p", "T-01", "A1", "edit", "hash", 240000)

    def test_abrupt_process_exit_after_effect_does_not_allow_replay(self):
        marker = self.path.parent / "effect"
        script = """import os, sys
from research.validation.store import Store
store = Store(sys.argv[1])
store.begin('crashed-operation', 'frozen-request')
with open(sys.argv[2], 'xb') as stream:
    stream.write(b'one-effect\\n')
    stream.flush()
    os.fsync(stream.fileno())
os._exit(23)
"""
        result = subprocess.run(
            [sys.executable, "-c", script, str(self.path), str(marker)],
            capture_output=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 23, result.stderr)
        self.assertEqual(marker.read_bytes(), b"one-effect\n")
        with self.assertRaises(Hold):
            self.store.begin("crashed-operation", "frozen-request")
        with self.assertRaises(Hold):
            self.store.begin("replacement", "new-request")
        self.store.receipt("crashed-operation", 200, b"independent-effect-receipt")
        self.store.receipt("crashed-operation", 200, b"independent-effect-receipt")
        self.assertEqual(marker.read_bytes(), b"one-effect\n")

    def test_b0_and_b1_ledgers(self):
        for role, actual in (("edit", 120000), ("finish", 20000), ("review", 40000)):
            self.submit("t1-" + role, role, actual)
        for role, actual in (
            ("correction", 120000),
            ("finish", 20000),
            ("review", 40000),
        ):
            self.submit("correction-" + role, role, actual, attempt="A2")
        for role, actual in (("edit", 120000), ("finish", 20000), ("review", 40000)):
            self.submit("t2-" + role, role, actual, task="T-02", attempt="A3")
        result = self.store.snapshot()
        self.assertEqual(result["settled_micro_usd"], 540000)
        self.assertEqual(result["held_micro_usd"], 0)
        self.assertEqual(len(result["permits"]), 9)
        self.assertEqual(
            sum(r["actual"] for r in result["permits"] if r["attempt"] != "A2"), 360000
        )

    def test_unknown_charge_stays_reserved_and_duplicate_settlement_is_idempotent(self):
        self.store.reserve("p", "T-01", "A1", "edit", "hash", 240000)
        self.store.consume("hash")
        with self.assertRaises(Hold):
            self.store.reserve("p2", "T-01", "A2", "edit", "other", 240000)
        self.assertEqual(self.store.snapshot()["held_micro_usd"], 240000)
        self.store.settle("p", 80000, "gen-p")
        self.store.settle("p", 80000, "gen-p")
        self.assertEqual(self.store.snapshot()["settled_micro_usd"], 80000)
        self.assertEqual(sum(r["kind"] == "settlement" for r in self.store.audit()), 1)

    def test_conflicting_settlement_persists_fence(self):
        self.submit("p", "edit", 120000)
        with self.assertRaises(Hold):
            self.store.settle("p", 130000, "gen-p")
        self.assertFalse(self.store.snapshot()["authority"]["active"])
        self.assertEqual(self.store.snapshot()["held_micro_usd"], 120000)
        self.assertFalse(self.store.snapshot()["exposure_qualified"])
        with self.assertRaises(Hold):
            self.store.reserve("p2", "T-01", "A1", "finish", "next", 80000)

    def test_zero_price_is_explicit_and_invalid_money_rejected(self):
        for bound in (-1, 1.5, True):
            with self.assertRaises(ValueError):
                self.store.reserve("p", "T-01", "A1", "edit", "hash", bound)
        self.submit("zero", "edit", 0)
        self.assertEqual(self.store.snapshot()["permits"][0]["state"], "settled")

    def test_racing_connections_allow_only_one_inflight_reservation(self):
        def reserve(index):
            other = Store(self.path)
            try:
                other.reserve(str(index), "T-01", "A1", "edit", "hash", 240000)
                return True
            except Hold:
                return False
            finally:
                other.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(reserve, range(2))), 1)

    def test_review_protection_and_attempt_limit(self):
        self.submit("first", "edit", 240000)
        with self.assertRaises(Hold):
            self.store.reserve("second", "T-01", "A2", "correction", "other", 160000)
        self.submit("review", "review", 40000)
        self.assertEqual(self.store.snapshot()["settled_micro_usd"], 280000)

    def test_audit_corruption_is_detected(self):
        self.store.event("test", {"safe": True})
        self.store.db.execute("UPDATE audit SET payload=?", (b"{}",))
        with self.assertRaises(Hold):
            self.store.audit()

    def test_report_does_not_invent_task_acceptance_or_real_billing(self):
        result = report(self.store)
        self.assertIsNone(result["accepted_tasks"])
        self.assertIsNone(result["cost_per_accepted_task"])


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="mcli1-http-")
        self.root = Path(self.temporary.name)
        self.store = Store(self.root / "broker.sqlite")
        self.servers = []

    def tearDown(self):
        for server in self.servers:
            server.shutdown()
            server.server_close()
        self.store.close()
        self.temporary.cleanup()

    def start(self, server):
        server.start()
        self.servers.append(server)
        return f"http://127.0.0.1:{server.server_port}"

    def setup_broker(self, mode="json"):
        raw = canonical(
            {
                "model": "fixture/model-v1",
                "messages": [{"role": "user", "content": "synthetic"}],
                "max_completion_tokens": 6000,
            }
        )
        transcript = [
            {
                "request_sha256": digest(raw),
                "generation_id": "gen-test",
                "settled": 120000,
                "mode": mode,
                "admission": {
                    "task": "T-01",
                    "attempt": "A1",
                    "role": "edit",
                    "input_tokens": 100,
                    "response_tokens": 1,
                    "counter_evidence_sha256": "a" * 64,
                },
                "response": {
                    "id": "gen-test",
                    "model": "fixture/model-v1",
                    "choices": [],
                },
            }
        ]
        url = self.start(broker(self.store, transcript))
        self.store.reserve("p", "T-01", "A1", "edit", digest(raw), 240000)
        return url, raw

    def test_broker_success_and_duplicate_request_denial(self):
        url, raw = self.setup_broker()
        headers = {"Authorization": "Bearer fixture-dummy"}
        self.assertEqual(
            request(url, "POST", "/v1/chat/completions", raw, headers)[0], 200
        )
        self.assertEqual(
            request(url, "POST", "/v1/chat/completions", raw, headers)[0], 409
        )
        self.assertEqual(self.store.snapshot()["settled_micro_usd"], 120000)

    def test_forbidden_route_model_fallback_and_changed_request_never_consume_permit(
        self,
    ):
        url, raw = self.setup_broker()
        headers = {"Authorization": "Bearer fixture-dummy"}
        for path, body, status in (
            ("/v1/other", raw, 403),
            ("/v1/chat/completions", canonical({"model": "other"}), 403),
            (
                "/v1/chat/completions",
                canonical({"model": "fixture/model-v1", "provider": {}}),
                403,
            ),
            ("/v1/chat/completions", raw + b" ", 409),
        ):
            self.assertEqual(request(url, "POST", path, body, headers)[0], status)
        self.assertEqual(self.store.snapshot()["permits"][0]["state"], "reserved")
        self.assertFalse(
            any(r["kind"] == "submission-intent" for r in self.store.audit())
        )

    def test_interrupted_script_retains_unknown_spend_and_blocks_replay(self):
        url, raw = self.setup_broker("interrupt")
        with self.assertRaises((http.client.HTTPException, OSError)):
            request(
                url,
                "POST",
                "/v1/chat/completions",
                raw,
                {"Authorization": "Bearer fixture-dummy"},
            )
        self.assertEqual(self.store.snapshot()["held_micro_usd"], 240000)
        self.assertEqual(
            request(
                url,
                "POST",
                "/v1/chat/completions",
                raw,
                {"Authorization": "Bearer fixture-dummy"},
            )[0],
            409,
        )

    def test_sse_script_and_duplicate_json_rejection(self):
        url, raw = self.setup_broker("sse")
        bad = b'{"model":"fixture/model-v1","model":"other"}'
        self.assertEqual(
            request(
                url,
                "POST",
                "/v1/chat/completions",
                bad,
                {"Authorization": "Bearer fixture-dummy"},
            )[0],
            400,
        )
        status, response, content_type = request(
            url,
            "POST",
            "/v1/chat/completions",
            raw,
            {"Authorization": "Bearer fixture-dummy"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/event-stream")
        self.assertTrue(response.endswith(b"data: [DONE]\n\n"))

    def test_nonloopback_or_redirect_style_endpoint_rejected(self):
        for url in (
            "http://example.com",
            "http://192.0.2.1",
            "https://127.0.0.1",
            "http://u:p@127.0.0.1",
            "http://127.0.0.1/path",
        ):
            with self.assertRaises(ValueError):
                endpoint(url)

    def test_lost_create_ack_is_recorded_once_and_never_resent(self):
        effects = []

        class Executor(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                effects.append(self.rfile.read(int(self.headers["Content-Length"])))
                self.send_response(201)
                self.end_headers()
                self.wfile.write(b'{"id":"synthetic"}')

        upstream = self.start(LocalServer(("127.0.0.1", 0), Executor))
        proxy = self.start(
            fault_proxy(self.store, upstream, {"create": "after-response"})
        )
        client_store = Store(self.root / "client.sqlite")
        try:
            client = Driver(client_store, proxy)
            with self.assertRaises((http.client.HTTPException, OSError)):
                client.mutation("create", "/api/conversations", {"id": "synthetic"})
            self.assertEqual(len(effects), 1)
            receipt = self.store.db.execute(
                "SELECT * FROM operations WHERE id='create'"
            ).fetchone()
            self.assertEqual(receipt["status"], 201)
            with self.assertRaises(Hold):
                client.mutation("create", "/api/conversations", {"id": "synthetic"})
            client_store.receipt("create", receipt["status"], receipt["response"])
            self.assertEqual(len(effects), 1)
        finally:
            client_store.close()

    def test_preforward_fault_proves_no_upstream_effect(self):
        proxy = self.start(
            fault_proxy(self.store, "http://127.0.0.1:1", {"create": "before-forward"})
        )
        with self.assertRaises((http.client.HTTPException, OSError)):
            request(
                proxy,
                "POST",
                "/api/conversations",
                b"{}",
                {"X-Fixture-Operation": "create"},
            )
        self.assertTrue(
            any(r["kind"] == "proven-not-forwarded" for r in self.store.audit())
        )
        self.assertFalse(any(r["kind"] == "forward-intent" for r in self.store.audit()))


class ObserverTests(unittest.TestCase):
    def test_exact_marker_bytes_and_gate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            operation = str(uuid4())
            marker = root / "markers.log"
            marker.write_bytes(
                f"{operation} effect\n{operation} child-ready\n".encode()
            )
            self.assertEqual(
                wait_marker(marker, operation, "effect")["phases"],
                ["effect", "child-ready"],
            )
            release_gate(root, operation)
            self.assertEqual(
                (root / "release").read_bytes(), (operation + "\n").encode()
            )
            marker.write_bytes(f"{operation} effect".encode())
            with self.assertRaises(Hold):
                markers(marker, operation)

    def test_intake_requires_stop_and_rejects_git_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "plain").write_bytes(b"synthetic\n")
            with self.assertRaises(Hold):
                seal(source, root / "denied", stop_receipt=None)
            receipt = seal(
                source, root / "sealed", stop_receipt="independent-test-stop"
            )
            self.assertEqual(receipt["files"], inventory(root / "sealed"))
            (source / ".git").write_bytes(b"gitdir: protected\n")
            with self.assertRaises(Hold):
                seal(source, root / "unsafe", stop_receipt="stop")

    def test_symlinks_are_rejected_when_platform_supports_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "target").write_bytes(b"synthetic")
            try:
                (root / "link").symlink_to(root / "target")
            except OSError:
                self.skipTest("symlink creation is unavailable to this process")
            with self.assertRaises(ValueError):
                inventory(root)


class SupervisorTests(unittest.TestCase):
    def test_restart_keeps_original_deadline_and_stops_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            store = Store(Path(temporary) / "supervisor.sqlite")
            profile = {"target_vm_uuid": str(uuid4()), "lease_expires_utc_ns": 200}
            stopped = []
            try:
                lease = LeaseSupervisor(store, profile, now_ns=100, monotonic_ns=10)
                self.assertFalse(lease.poll(now_ns=150, monotonic_ns=60))
                with self.assertRaises(Hold):
                    LeaseSupervisor(
                        store, profile | {"lease_expires_utc_ns": 300}, now_ns=150
                    )
                store.close()
                store = Store(Path(temporary) / "supervisor.sqlite")
                lease = LeaseSupervisor(store, profile, now_ns=150, monotonic_ns=60)
                self.assertTrue(
                    lease.poll(
                        now_ns=200,
                        monotonic_ns=110,
                        stopper=lambda s, p: stopped.append(p["target_vm_uuid"]),
                    )
                )
                self.assertTrue(
                    lease.poll(
                        now_ns=201,
                        monotonic_ns=111,
                        stopper=lambda *_: stopped.append("duplicate"),
                    )
                )
                self.assertEqual(stopped, [profile["target_vm_uuid"]])
            finally:
                store.close()

    def test_fence_or_clock_rollback_triggers_stop_before_expiry(self):
        for fence in (True, False):
            with tempfile.TemporaryDirectory() as temporary:
                store = Store(Path(temporary) / "supervisor.sqlite")
                try:
                    lease = LeaseSupervisor(
                        store,
                        {"target_vm_uuid": str(uuid4()), "lease_expires_utc_ns": 200},
                        now_ns=100,
                        monotonic_ns=10,
                    )
                    if fence:
                        store.fence("pause")
                    stopped = []
                    self.assertTrue(
                        lease.poll(
                            now_ns=150 if fence else 90,
                            monotonic_ns=60,
                            stopper=lambda *_, results=stopped: results.append(True),
                        )
                    )
                    self.assertEqual(stopped, [True])
                finally:
                    store.close()


if __name__ == "__main__":
    unittest.main()
