import copy
import unittest

from research.validation.token_fit_probe import (
    INPUT_HASHES,
    ROLE_CAPS,
    validate_inputs,
    validate_observation,
)


class TokenFitObservationTests(unittest.TestCase):
    def setUp(self):
        self.value = {
            "format": "mcli1-token-fit-probe-v1",
            "input_sha256": INPUT_HASHES.copy(),
            "inference_attempts": 0,
            "native_tool_calling": True,
            "mock_tool_calls": False,
            "token_counter_disabled": False,
            "error": None,
            "counts": {
                "sdk_messages_only": 4000,
                "litellm_messages_only": 4000,
                "litellm_with_tools": 6500,
            },
            "role_prefix_headroom": {
                role: cap - 6500 for role, cap in ROLE_CAPS.items()
            },
        }

    def test_valid_measurement_can_exceed_a_role_cap(self):
        validate_observation(self.value)
        self.assertEqual(self.value["role_prefix_headroom"]["finish"], -500)

    def test_counter_failure_mismatch_and_changed_path_are_rejected(self):
        for field, bad in (
            ("inference_attempts", 1),
            ("mock_tool_calls", True),
            ("token_counter_disabled", True),
            ("native_tool_calling", False),
            ("error", "count failed"),
            ("input_sha256", {}),
            ("role_prefix_headroom", {}),
        ):
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_observation({**self.value, field: bad})
        for name, bad in (
            ("sdk_messages_only", 0),
            ("sdk_messages_only", 3999),
            ("litellm_with_tools", 4000),
            ("litellm_with_tools", True),
        ):
            value = copy.deepcopy(self.value)
            value["counts"][name] = bad
            with self.subTest(name=name, bad=bad), self.assertRaises(ValueError):
                validate_observation(value)

    def test_changed_or_extra_retained_inputs_are_rejected(self):
        for value in ({}, dict.fromkeys(INPUT_HASHES, "changed"), {"extra": ""}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_inputs(value)


if __name__ == "__main__":
    unittest.main()
