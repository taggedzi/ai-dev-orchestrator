import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research.validation.bundle import digest
from research.validation.fixture import canonical
from research.validation.http_tools import broker, request
from research.validation.phase_policy import TOKEN_CAPS, admit_request, validate_turn
from research.validation.store import Hold, Store


def turn(role="finish", output=1000):
    raw = canonical(
        {
            "model": "fixture/model-v1",
            "messages": [{"role": "user", "content": "synthetic"}],
            "max_completion_tokens": output,
        }
    )
    row = {
        "request_sha256": digest(raw),
        "generation_id": "synthetic-phase-test",
        "settled": 20000,
        "response": {"id": "synthetic-phase-test", "choices": []},
        # Declared test counts, not native measurement evidence.
        "admission": {
            "task": "T-01",
            "attempt": "A1",
            "role": role,
            "input_tokens": 100,
            "response_tokens": 1,
            "counter_evidence_sha256": "a" * 64,
        },
    }
    return raw, row


class PhasePolicyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.stores = []
        self.servers = []

    def tearDown(self):
        for server, thread in self.servers:
            server.shutdown()
            thread.join(timeout=3)
            server.server_close()
        for store in self.stores:
            store.close()
        self.temporary.cleanup()

    def store(self, name="ledger.sqlite"):
        value = Store(self.root / name)
        self.stores.append(value)
        return value

    def start(self, store, rows):
        server = broker(store, rows)
        self.servers.append((server, server.start()))
        return f"http://127.0.0.1:{server.server_port}"

    def post(self, url, raw):
        return request(
            url,
            "POST",
            "/v1/chat/completions",
            raw,
            {"Authorization": "Bearer fixture-dummy"},
        )[0]

    def test_all_role_caps_keep_the_proposed_money_envelopes(self):
        for role, expected in (
            ("edit", 240000),
            ("correction", 160000),
            ("finish", 80000),
            ("review", 120000),
        ):
            raw, row = turn(role, TOKEN_CAPS[role][1])
            grant = admit_request(raw, digest(raw), row["admission"])
            self.assertEqual(grant["bound"], expected)

    def test_bad_counts_roles_and_evidence_are_not_admitted(self):
        _, row = turn()
        for key, bad in (
            ("role", "auxiliary"),
            ("task", "T-03"),
            ("attempt", ""),
            ("input_tokens", 0),
            ("input_tokens", True),
            ("input_tokens", 6001),
            ("response_tokens", 1001),
            ("counter_evidence_sha256", "missing"),
        ):
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_turn({**row["admission"], key: bad})
        with self.assertRaises(ValueError):
            validate_turn({})

    def test_unbounded_or_conflicting_outputs_and_wrong_hash_hold(self):
        raw, row = turn()
        original = json.loads(raw)
        for change in (
            {"max_completion_tokens": 6000},
            {"max_completion_tokens": True},
            {"max_tokens": 1000},
            {"role": "edit"},
            {"stream_options": {"include_usage": True}},
            {"stream": True, "stream_options": {"include_usage": 1}},
            {"messages": [{"role": "auxiliary", "content": "unapproved"}]},
            {"messages": []},
        ):
            changed = canonical({**original, **change})
            with self.subTest(change=change), self.assertRaises(Hold):
                admit_request(changed, digest(changed), row["admission"])
        with self.assertRaises(Hold):
            admit_request(raw + b" ", digest(raw), row["admission"])
        smaller = canonical({**original, "max_completion_tokens": 100})
        with self.assertRaises(Hold):
            admit_request(
                smaller, digest(smaller), {**row["admission"], "response_tokens": 500}
            )

    def test_oversized_finish_is_denied_without_consuming_its_permit(self):
        store = self.store()
        raw, row = turn(output=6000)
        url = self.start(store, [row])
        store.reserve("P", "T-01", "A1", "finish", digest(raw), 80000)
        self.assertEqual(self.post(url, raw), 409)
        self.assertEqual(store.snapshot()["permits"][0]["state"], "reserved")
        self.assertFalse(
            any(
                r["kind"] in ("phase-admission", "submission-intent")
                for r in store.audit()
            )
        )

    def test_valid_finish_has_one_bound_admission_and_replay_is_denied(self):
        store = self.store()
        raw, row = turn()
        url = self.start(store, [row])
        store.reserve("P", "T-01", "A1", "finish", digest(raw), 80000)
        self.assertEqual(self.post(url, raw), 200)
        self.assertEqual(self.post(url, raw), 409)
        audits = [r for r in store.audit() if r["kind"] == "phase-admission"]
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0]["payload"]["role"], "finish")
        self.assertEqual(audits[0]["payload"]["requested_output_tokens"], 1000)
        self.assertEqual(store.snapshot()["settled_micro_usd"], 20000)

    def test_permit_task_attempt_role_and_bound_must_match_atomically(self):
        raw, row = turn()
        for index, changed in enumerate(
            ({"task": "T-02"}, {"attempt": "A2"}, {"role": "edit"}, {"bound": 79999})
        ):
            store = self.store(f"mismatch-{index}.sqlite")
            fields = {
                "task": "T-01",
                "attempt": "A1",
                "role": "finish",
                "bound": 80000,
                **changed,
            }
            url = self.start(store, [row])
            store.reserve("P", request_hash=digest(raw), **fields)
            self.assertEqual(self.post(url, raw), 409)
            self.assertEqual(store.snapshot()["permits"][0]["state"], "reserved")
            self.assertFalse(any(r["kind"] == "phase-admission" for r in store.audit()))

    def test_admission_and_possible_send_roll_back_together_on_journal_failure(self):
        store = self.store()
        raw, row = turn()
        grant = admit_request(raw, digest(raw), row["admission"])
        store.reserve("P", "T-01", "A1", "finish", digest(raw), 80000)
        original = store._event

        def fail(kind, payload):
            if kind == "submission-intent":
                raise OSError("synthetic journal failure")
            return original(kind, payload)

        with (
            patch.object(store, "_event", side_effect=fail),
            self.assertRaises(OSError),
        ):
            store.consume(digest(raw), grant)
        self.assertEqual(store.snapshot()["permits"][0]["state"], "reserved")
        self.assertFalse(any(r["kind"] == "phase-admission" for r in store.audit()))

    def test_transcript_is_copied_and_binding_survives_new_store_connection(self):
        store = self.store()
        raw, row = turn()
        rows = [copy.deepcopy(row)]
        url = self.start(store, rows)
        rows[0]["admission"]["role"] = "edit"
        rows[0]["response"]["id"] = "mutated"
        store.reserve("P", "T-01", "A1", "finish", digest(raw), 80000)
        self.assertEqual(self.post(url, raw), 200)
        restarted = self.store()
        server = broker(restarted, [row])
        server.server_close()
        with self.assertRaises(Hold):
            broker(restarted, [{**row, "response": {"changed": True}}])
        self.assertEqual(
            sum(r["kind"] == "broker-transcript-bound" for r in store.audit()), 1
        )

    def test_missing_metadata_or_unbound_old_submissions_cannot_start_strict_broker(
        self,
    ):
        store = self.store()
        raw, row = turn()
        incomplete = {key: value for key, value in row.items() if key != "admission"}
        with self.assertRaises(ValueError):
            broker(store, [incomplete])
        store.reserve("P", "T-01", "A1", "finish", digest(raw), 80000)
        store.consume(digest(raw))  # Legacy ledger-only path, not a qualified broker.
        with self.assertRaises(Hold):
            broker(store, [row])


if __name__ == "__main__":
    unittest.main()
