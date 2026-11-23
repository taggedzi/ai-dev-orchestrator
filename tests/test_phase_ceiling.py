"""Explicit scripted-broker ceiling; all token counts and billing are synthetic."""

import copy
import hashlib
import http.client
import json
import unittest
from unittest.mock import patch

import test_phase_policy as fixture

from research.validation.fixture import POLICY, canonical
from research.validation.http_tools import broker
from research.validation.phase_policy import TOKEN_CAPS, admit_with_ceiling
from research.validation.store import Hold


def turn(role="finish", output=6000):
    raw, row = fixture.turn(role, output)
    payload = json.loads(raw)
    payload["max_completion_tokens"] = min(output, TOKEN_CAPS[role][1])
    effective = (
        raw
        if payload["max_completion_tokens"] == output
        else json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    )
    row["normalization"] = {
        "effective_request_sha256": hashlib.sha256(effective).hexdigest(),
        "incoming_counter_evidence_sha256": "b" * 64,
    }
    return raw, row, effective


class CeilingTests(unittest.TestCase):
    setUp = fixture.PhasePolicyTests.setUp
    tearDown = fixture.PhasePolicyTests.tearDown
    store = fixture.PhasePolicyTests.store
    post = fixture.PhasePolicyTests.post

    def start(self, store, rows, **options):
        server = broker(
            store,
            rows,
            output_policy="phase-ceiling-v1",
            ceiling_approval="test:broker-ceiling-preparation",
            **options,
        )
        self.servers.append((server, server.start()))
        return f"http://127.0.0.1:{server.server_port}"

    def reserve(self, store, raw, role="finish"):
        store.reserve(
            "P",
            "T-01",
            "A1",
            role,
            hashlib.sha256(raw).hexdigest(),
            POLICY["limits"][role],
        )

    def test_explicit_mode_serves_exact_script_and_journals_both_bodies_and_limits(
        self,
    ):
        raw, row, effective = turn()
        store = self.store()
        self.reserve(store, raw)
        url = self.start(store, [row])
        self.assertEqual(self.post(url, raw), 200)
        event = next(
            r["payload"] for r in store.audit() if r["kind"] == "phase-admission"
        )
        self.assertEqual(
            event["incoming_request_sha256"], hashlib.sha256(raw).hexdigest()
        )
        self.assertEqual(
            event["effective_request_sha256"], hashlib.sha256(effective).hexdigest()
        )
        self.assertEqual(event["requested_output_tokens"], 6000)
        self.assertEqual(event["effective_output_tokens"], 1000)
        self.assertEqual(event["bound"], 80000)
        self.assertEqual(event["counter_evidence_sha256"], "a" * 64)
        self.assertEqual(event["incoming_counter_evidence_sha256"], "b" * 64)
        self.assertEqual(event["ceiling_approval"], "test:broker-ceiling-preparation")
        self.assertEqual(self.post(url, raw), 409)
        self.assertEqual(store.snapshot()["settled_micro_usd"], 20000)

    def test_all_roles_and_smaller_requests_keep_caps_and_full_reservations(self):
        for role in TOKEN_CAPS:
            for limit in (500, 6000):
                raw, row, effective = turn(role, limit)
                result = admit_with_ceiling(
                    raw, row["request_sha256"], row["admission"], row["normalization"]
                )
                self.assertEqual(
                    result["effective_output_tokens"], min(limit, TOKEN_CAPS[role][1])
                )
                self.assertEqual(result["bound"], POLICY["limits"][role])
                if limit == 500:
                    self.assertEqual(raw, effective)

    def test_policy_and_normalization_are_required_before_binding_a_store(self):
        _, row, _ = turn()
        cases = (
            ({"output_policy": "phase-ceiling-v1"}, [row]),
            ({"output_policy": "unknown"}, [row]),
            ({}, [row]),
            (
                {
                    "output_policy": "phase-ceiling-v1",
                    "ceiling_approval": "test:approved",
                },
                [{k: v for k, v in row.items() if k != "normalization"}],
            ),
        )
        for index, (options, rows) in enumerate(cases):
            store = self.store(f"invalid-{index}.sqlite")
            with self.subTest(options=options), self.assertRaises(ValueError):
                broker(store, rows, **options)
            self.assertFalse(
                any(r["kind"] == "broker-transcript-bound" for r in store.audit())
            )

    def test_effective_hash_drift_raw_alias_or_permit_mismatch_cannot_consume(self):
        raw, original, _ = turn()
        for index, change in enumerate(
            ("effective", "alias", "permit", "count", "response")
        ):
            row = copy.deepcopy(original)
            store = self.store(f"drift-{index}.sqlite")
            self.reserve(store, raw)
            if change == "effective":
                row["normalization"]["effective_request_sha256"] = "0" * 64
            elif change == "permit":
                row["admission"]["attempt"] = "A2"
            elif change == "count":
                row["admission"]["role"] = "edit"
            elif change == "response":
                # The frozen response must also fit an executor's smaller request.
                payload = json.loads(raw)
                payload["max_completion_tokens"] = 1
                changed = canonical(payload)
                row["request_sha256"] = hashlib.sha256(changed).hexdigest()
                row["normalization"]["effective_request_sha256"] = row["request_sha256"]
                row["admission"]["response_tokens"] = 2
            url = self.start(store, [row])
            request = (
                raw + b" "
                if change == "alias"
                else changed
                if change == "response"
                else raw
            )
            with self.subTest(change=change):
                self.assertEqual(self.post(url, request), 409)
                self.assertEqual(store.snapshot()["permits"][0]["state"], "reserved")
                self.assertFalse(
                    any(r["kind"] == "phase-admission" for r in store.audit())
                )

    def test_restart_binds_policy_approval_counts_and_effective_bytes(self):
        _, row, _ = turn()
        store = self.store()
        self.start(store, [row])
        restarted = self.store()
        server = broker(
            restarted,
            [row],
            output_policy="phase-ceiling-v1",
            ceiling_approval="test:broker-ceiling-preparation",
        )
        server.server_close()
        for name in ("approval", "effective", "count"):
            changed = copy.deepcopy(row)
            approval = "test:broker-ceiling-preparation"
            if name == "approval":
                approval = "test:other-approval"
            elif name == "effective":
                changed["normalization"]["effective_request_sha256"] = "0" * 64
            else:
                changed["normalization"]["incoming_counter_evidence_sha256"] = "0" * 64
            with self.subTest(name=name), self.assertRaises(Hold):
                broker(
                    restarted,
                    [changed],
                    output_policy="phase-ceiling-v1",
                    ceiling_approval=approval,
                )
        strict = {k: v for k, v in row.items() if k != "normalization"}
        with self.assertRaises(Hold):
            broker(restarted, [strict])

    def test_interrupted_ceiling_reply_keeps_unknown_spend_and_denies_replay_after_restart(
        self,
    ):
        raw, row, _ = turn()
        row["mode"] = "interrupt"
        store = self.store()
        self.reserve(store, raw)
        url = self.start(store, [row])
        with self.assertRaises((http.client.HTTPException, OSError)):
            self.post(url, raw)
        self.assertEqual(store.snapshot()["permits"][0]["state"], "possible-send")
        restarted = self.store()
        other = self.start(restarted, [row])
        self.assertEqual(self.post(other, raw), 409)
        admissions = [r for r in restarted.audit() if r["kind"] == "phase-admission"]
        self.assertEqual(len(admissions), 1)
        self.assertEqual(admissions[0]["payload"]["effective_output_tokens"], 1000)
        self.assertEqual(restarted.snapshot()["settled_micro_usd"], 0)

    def test_journal_failure_rolls_back_normalization_and_possible_send_together(self):
        raw, row, _ = turn()
        store = self.store()
        self.reserve(store, raw)
        admission = admit_with_ceiling(
            raw, row["request_sha256"], row["admission"], row["normalization"]
        )
        original = store._event

        def fail(kind, payload):
            if kind == "submission-intent":
                raise OSError("test:journal failure before scripted response")
            return original(kind, payload)

        with patch.object(store, "_event", fail), self.assertRaises(OSError):
            store.consume(row["request_sha256"], admission)
        self.assertEqual(store.snapshot()["permits"][0]["state"], "reserved")
        self.assertFalse(any(r["kind"] == "phase-admission" for r in store.audit()))

    def test_default_strict_transcript_keeps_its_original_binding_digest(self):
        _, row = fixture.turn()
        store = self.store()
        server = broker(store, [row])
        server.server_close()
        from research.validation.phase_policy import (
            INPUT_MICRO_USD_PER_TOKEN,
            OUTPUT_MICRO_USD_PER_TOKEN,
        )

        old = {
            "format": "mcli1-phase-broker-v1",
            "token_caps": TOKEN_CAPS,
            "money_limits": POLICY["limits"],
            "micro_usd_per_token": [
                INPUT_MICRO_USD_PER_TOKEN,
                OUTPUT_MICRO_USD_PER_TOKEN,
            ],
            "transcript": [row],
        }
        store.bind_broker_transcript(hashlib.sha256(canonical(old)).hexdigest())


if __name__ == "__main__":
    unittest.main()
