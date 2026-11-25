import copy
import hashlib
import json
import unittest

from research.validation.phase_policy import TOKEN_CAPS
from research.validation.wire_input_probe import (
    ROLE_LIMITS,
    assess_request,
    validate_observation,
)


def request(phase, output=6000):
    roles = ["system", "user"] + (
        ["assistant", "tool"] if phase == "finish_projection" else []
    )
    return json.dumps(
        {
            "model": "fixture/model-v1",
            "tools": [
                {"function": {"name": name}} for name in ("terminal", "file_editor")
            ],
            "messages": [{"role": role} for role in roles],
            "max_tokens": output,
        }
    )


class WireInputTests(unittest.TestCase):
    def test_sdk_probe_phase_options_match_the_broker_policy(self):
        self.assertEqual(ROLE_LIMITS["initial_edit"], TOKEN_CAPS["edit"])
        self.assertEqual(ROLE_LIMITS["finish_projection"], TOKEN_CAPS["finish"])

    def test_observed_output_mismatch_remains_a_valid_but_unapproved_measurement(self):
        initial = assess_request(request("initial_edit"), "initial_edit", 5300)
        finish = assess_request(request("finish_projection"), "finish_projection", 5400)
        self.assertTrue(initial["output_within_cap"])
        self.assertFalse(finish["output_within_cap"])
        self.assertTrue(finish["input_within_cap"])
        self.assertFalse(finish["dispatch_approved"])
        self.assertFalse(
            assess_request(
                request("finish_projection", 1000), "finish_projection", 6001
            )["input_within_cap"]
        )

    def test_unbounded_or_ambiguous_output_and_changed_route_roles_hold(self):
        baseline = json.loads(request("initial_edit"))
        for key, value in (
            ("model", "other"),
            ("max_tokens", 0),
            ("max_tokens", True),
            ("messages", []),
            ("max_completion_tokens", 1000),
        ):
            changed = {**baseline, key: value}
            with self.subTest(key=key), self.assertRaises(ValueError):
                assess_request(json.dumps(changed), "initial_edit", 5300)
        for count in (0, -1, True):
            with self.subTest(count=count), self.assertRaises(ValueError):
                assess_request(request("initial_edit"), "initial_edit", count)

    def test_capture_requires_one_denied_http_attempt_per_case_and_no_sockets(self):
        value = {
            "format": "mcli1-wire-input-probe-v1",
            "unexpected_transport_attempts": 0,
            "socket_connect_attempts": 0,
            "executor_instances": 0,
            "cases": [],
        }
        for task in ("T-01", "T-02"):
            for phase in ROLE_LIMITS:
                raw = request(phase)
                value["cases"].append(
                    {
                        "task": task,
                        "phase": phase,
                        "wire_utf8": raw,
                        "wire_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                        "http_attempts": 1,
                        "sdk_response_returned": False,
                        "sdk_error_type": "PermissionDeniedError",
                        "sdk_input_tokens": 5300,
                        "wire_input_tokens": 5300,
                        "assessment": assess_request(raw, phase, 5300),
                    }
                )
        validate_observation(value)
        with self.assertRaises(ValueError):
            validate_observation({**value, "explicit_phase_options": True})
        for field, bad in (
            ("http_attempts", 2),
            ("sdk_response_returned", True),
            ("wire_sha256", "0" * 64),
            ("sdk_input_tokens", 0),
        ):
            changed = copy.deepcopy(value)
            changed["cases"][0][field] = bad
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_observation(changed)
        for field in (
            "unexpected_transport_attempts",
            "socket_connect_attempts",
            "executor_instances",
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_observation({**value, field: 1})


if __name__ == "__main__":
    unittest.main()
