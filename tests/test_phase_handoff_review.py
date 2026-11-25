import hashlib
import json
import unittest

from research.validation.phase_handoff_review import preview_output_ceiling
from research.validation.store import Hold


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class PhaseHandoffReviewTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "messages": [{"role": "user", "content": "Exact text: \t ☃\n"}],
            "model": "fixture/model-v1",
            "max_completion_tokens": 6000,
            "tools": [
                {
                    "type": "function",
                    "function": {"name": "terminal", "parameters": {"z": 1, "a": 2}},
                }
            ],
        }

    def test_only_the_output_limit_changes_and_content_order_is_preserved(self):
        raw = json.dumps(
            self.payload, ensure_ascii=False, separators=(",", ":")
        ).encode()
        for role, cap in (
            ("edit", 6000),
            ("correction", 2000),
            ("finish", 1000),
            ("review", 3000),
        ):
            target = json.dumps(
                {**self.payload, "max_completion_tokens": cap},
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
            result = preview_output_ceiling(raw, role, sha(raw), sha(target))
            self.assertEqual(result, target)
            parsed = json.loads(result)
            self.assertEqual(parsed["messages"], self.payload["messages"])
            self.assertEqual(
                list(parsed["tools"][0]["function"]["parameters"]), ["z", "a"]
            )

    def test_a_smaller_requested_limit_and_original_serialization_are_preserved(self):
        raw = json.dumps(
            {**self.payload, "max_completion_tokens": 500}, indent=2
        ).encode()
        self.assertEqual(preview_output_ceiling(raw, "finish", sha(raw), sha(raw)), raw)

    def test_unfrozen_unbounded_or_changed_requests_hold(self):
        raw = json.dumps(self.payload).encode()
        with self.assertRaises(Hold):
            preview_output_ceiling(raw, "finish", "0" * 64, "0" * 64)
        with self.assertRaises(Hold):
            preview_output_ceiling(raw, "finish", sha(raw), "0" * 64)
        with self.assertRaises(Hold):
            preview_output_ceiling(raw, "auxiliary", sha(raw), "0" * 64)
        for changes in (
            {"max_completion_tokens": 0},
            {"max_completion_tokens": True},
            {"max_completion_tokens": 6001},
            {"max_tokens": 1000},
            {"role": "edit"},
            {"provider": {}},
            {"model": "other"},
        ):
            changed = json.dumps({**self.payload, **changes}).encode()
            with self.subTest(changes=changes), self.assertRaises(Hold):
                preview_output_ceiling(changed, "finish", sha(changed), sha(changed))
        missing = json.dumps(
            {k: v for k, v in self.payload.items() if k != "max_completion_tokens"}
        ).encode()
        with self.assertRaises(Hold):
            preview_output_ceiling(missing, "finish", sha(missing), sha(missing))


if __name__ == "__main__":
    unittest.main()
