import copy
import hashlib
import json
import unittest

from research.validation.resolved_tool_probe import REQUEST_SHA256, validate_observation


class ResolvedToolObservationTests(unittest.TestCase):
    def setUp(self):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": "native description",
                    "parameters": {"properties": {"summary": {}, "security_risk": {}}},
                },
            }
            for name in ("terminal", "file_editor")
        ]
        raw = json.dumps(tools)
        self.value = {
            "format": "mcli1-resolved-tool-probe-v1",
            "request_sha256": REQUEST_SHA256,
            "working_dir": "/workspace/project",
            "resolved_names": ["terminal", "file_editor"],
            "inference_attempts": 0,
            "action_attempts": 0,
            "event_types": ["SystemPromptEvent"],
            "children_after_cleanup": [],
            "executors_closed": ["terminal", "file_editor"],
            "native_tool_json": raw,
            "native_tool_json_sha256": hashlib.sha256(raw.encode()).hexdigest(),
        }

    def test_exact_native_observation_passes(self):
        self.assertEqual(len(validate_observation(self.value)), 2)

    def test_actions_inference_extra_tools_or_incomplete_cleanup_hold(self):
        for field, bad in (
            ("inference_attempts", 1),
            ("request_sha256", "0" * 64),
            ("working_dir", "/other"),
            ("action_attempts", 1),
            ("resolved_names", ["terminal", "file_editor", "finish"]),
            ("event_types", ["SystemPromptEvent", "ActionEvent"]),
            ("children_after_cleanup", [123]),
            ("executors_closed", ["file_editor"]),
            ("native_tool_json_sha256", "0" * 64),
        ):
            changed = {**self.value, field: bad}
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_observation(changed)

    def test_wire_fields_and_tool_identity_are_preserved(self):
        for field in ("summary", "security_risk", "name"):
            changed = copy.deepcopy(self.value)
            tools = json.loads(changed["native_tool_json"])
            if field == "name":
                tools[0]["function"]["name"] = "other"
            else:
                tools[0]["function"]["parameters"]["properties"].pop(field)
            changed["native_tool_json"] = json.dumps(tools)
            changed["native_tool_json_sha256"] = hashlib.sha256(
                changed["native_tool_json"].encode()
            ).hexdigest()
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_observation(changed)


if __name__ == "__main__":
    unittest.main()
