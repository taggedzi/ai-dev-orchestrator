"""Conformance controls using a sample derived from the real pinned GSD export."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from research.validation.bundle import build, digest, inventory, verify, write
from research.validation.driver import deployment_template
from research.validation.fixture import PROMPTS, planning_files
from research.validation.gsd_import import eligible_tasks, normalize
from research.validation.store import Hold

PLAN1 = ".planning/phases/01-validate-cli/01-01-PLAN.md"
PLAN2 = ".planning/phases/01-validate-cli/01-02-PLAN.md"


def inputs():
    snapshot = json.loads(
        (Path(__file__).parent / "fixtures/gsd-schema-1.json").read_text()
    )
    raw = {name: value.encode() for name, value in planning_files().items()}
    return snapshot, raw


def encode(snapshot):
    return json.dumps(snapshot).encode()


class GsdImportTests(unittest.TestCase):
    def test_bundle_attachment_binds_snapshot_and_raw_plans_without_run_approval(self):
        snapshot, raw = inputs()
        encoded = encode(snapshot)
        frozen_hash = digest(encoded)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            export_root = root / "export"
            project = export_root / "planning-input"
            for name, value in raw.items():
                write(project, name, value)
            before = inventory(project)
            write(export_root, "planning-before.json", json.dumps(before))
            write(export_root, "planning-after.json", json.dumps(before))
            observations = []
            for name in ["identity", "context", "inspect", "index", "inspect-repeat"]:
                value = encoded if name in ["inspect", "inspect-repeat"] else b"{}\n"
                write(export_root, name + ".stdout", value)
                write(export_root, name + ".stderr", b"")
                observations.append(
                    {
                        "name": name,
                        "exit": 0,
                        "stdout_sha256": digest(value),
                        "stderr_sha256": digest(b""),
                    }
                )
            receipt = {
                "gsd_version": "1.21.0",
                "gsd_commit": "357508df233ccca0dcf4332b385d6bee9b113da9",
                "snapshot_sha256": frozen_hash,
                "planning_files_unchanged": True,
                "git_metadata_unchanged": True,
                "tool_package_unchanged": True,
                "repeat_bytes_equal": True,
                "queries": observations,
                "bundle_sha256": "a" * 64,
                "planning_commit": {"oid": "b" * 40},
            }
            write(export_root, "result.json", json.dumps(receipt))
            destination = root / "bundle"
            manifest = build(destination, export_root, frozen_hash)
            self.assertEqual(
                verify(destination)["planning_export"]["snapshot_sha256"], frozen_hash
            )
            self.assertEqual(
                (destination / "planning/native-snapshot.json").read_bytes(), encoded
            )
            self.assertIn("planning/import-probe.json", manifest["files"])
            profile = deployment_template(
                digest((destination / "manifest.json").read_bytes()), frozen_hash
            )
            self.assertEqual(profile["gsd_export_sha256"], frozen_hash)
            self.assertEqual(profile["status"], "not-approved")
            self.assertIsNone(profile["approval"])
            with self.assertRaisesRegex(ValueError, "external freeze digest"):
                build(root / "wrong-hash", export_root, "0" * 64)
            roadmap = project / ".planning/ROADMAP.md"
            roadmap.write_bytes(roadmap.read_bytes() + b"\nChanged after export\n")
            changed = inventory(project)
            write(export_root, "planning-before.json", json.dumps(changed))
            write(export_root, "planning-after.json", json.dumps(changed))
            with self.assertRaisesRegex(ValueError, "different raw planning inputs"):
                build(root / "wrong-planning-input", export_root, frozen_hash)

    def test_native_fields_and_raw_actions_checks_done_survive_translation(self):
        snapshot, raw = inputs()
        result = normalize(encode(snapshot), raw)
        self.assertEqual([task["id"] for task in result["tasks"]], ["T-01", "T-02"])
        self.assertEqual(result["tasks"][1]["depends_on"], ["T-01"])
        for task in result["tasks"]:
            self.assertEqual(
                task["action"], PROMPTS[task["id"]].split("\n", 1)[1].strip()
            )
            self.assertTrue(task["verification"].startswith("node --test "))
            self.assertIn("independent review", task["done"])
        self.assertIn("Hello, <name>!", result["tasks"][1]["action"])
        self.assertEqual(eligible_tasks(result, []), ["T-01"])
        self.assertEqual(eligible_tasks(result, ["T-01"]), ["T-02"])
        self.assertEqual(eligible_tasks(result, ["T-01", "T-02"]), [])

    def test_unknown_duplicate_and_noninteger_schema_are_rejected(self):
        snapshot, raw = inputs()
        for version in [2, "1", True, None]:
            with self.assertRaises(Hold):
                normalize(encode(snapshot | {"schema_version": version}), raw)
        with self.assertRaises(Hold):
            normalize(b'{"schema_version":1,"schema_version":1}', raw)

    def test_missing_cycle_and_dropped_dependency_cannot_release_second_task(self):
        snapshot, raw = inputs()
        for dependencies, expected_error in [
            (["99-99"], "missing dependency target"),
            ([], "approved fixture dependency changed"),
        ]:
            changed = copy.deepcopy(snapshot)
            changed["phases"][0]["plans"][1]["dependsOn"] = dependencies
            changed_raw = raw | {
                PLAN2: raw[PLAN2].replace(
                    b'depends_on: ["01-01"]',
                    ("depends_on: " + json.dumps(dependencies)).encode(),
                )
            }
            with self.assertRaisesRegex(Hold, expected_error):
                normalize(encode(changed), changed_raw)
        changed = copy.deepcopy(snapshot)
        changed["phases"][0]["plans"][0]["dependsOn"] = ["01-02"]
        with self.assertRaisesRegex(Hold, "dependency cycle"):
            normalize(
                encode(changed),
                raw
                | {
                    PLAN1: raw[PLAN1].replace(
                        b"depends_on: []", b'depends_on: ["01-02"]'
                    )
                },
            )

    def test_omitted_native_action_and_verification_are_bound_to_raw_plan(self):
        snapshot, raw = inputs()
        for old, new in [
            (b"Leave Git, dependencies", b"Modify Git, dependencies"),
            (b"node --test test/cli.test.js", b"echo pretend-pass"),
            (b"All frozen candidate checks", b"Skip candidate checks"),
        ]:
            with self.subTest(old=old), self.assertRaises(Hold):
                normalize(encode(snapshot), raw | {PLAN2: raw[PLAN2].replace(old, new)})

    def test_malformed_missing_or_ambiguous_raw_fields_hold(self):
        snapshot, raw = inputs()
        for old, new in [
            (b"</task>", b""),
            (b"depends_on:", b"missing_field:"),
            (b"depends_on: []", b"depends_on: []\ndepends_on: []"),
            (b"<name>T-01</name>", b"<name>T-01</name><name>extra</name>"),
        ]:
            with self.subTest(old=old), self.assertRaises(Hold):
                normalize(encode(snapshot), raw | {PLAN1: raw[PLAN1].replace(old, new)})

    def test_unknown_goal_requirement_mapping_and_file_scope_hold(self):
        snapshot, raw = inputs()
        changed = copy.deepcopy(snapshot)
        changed["phases"][0]["goal"]["value"] = None
        variants = [changed]
        changed = copy.deepcopy(snapshot)
        changed["requirements"][0]["mappedPhases"] = []
        variants.append(changed)
        changed = copy.deepcopy(snapshot)
        changed["phases"][0]["plans"][1]["plannedFiles"].append("unexpected.txt")
        variants.append(changed)
        for changed in variants:
            with self.assertRaises(Hold):
                normalize(encode(changed), raw)

    def test_native_finished_status_and_checkbox_do_not_supply_acceptance(self):
        snapshot, raw = inputs()
        phase = snapshot["phases"][0]
        phase["complete"] = True
        phase["roadmap_acceptance"]["checkbox"] = True
        for plan in phase["plans"]:
            plan["tasks"][0]["status"] = "finished"
        result = normalize(encode(snapshot), raw)
        self.assertEqual(eligible_tasks(result, []), ["T-01"])
        self.assertEqual(result["tasks"][1]["native_status_observation"], "finished")

    def test_unknown_percentages_remain_unknown_and_acceptance_ids_are_checked(self):
        snapshot, raw = inputs()
        result = normalize(encode(snapshot), raw)
        self.assertIsNone(
            result["native_progress_observation"]["accepted_phases"]["percent"]
        )
        with self.assertRaises(Hold):
            eligible_tasks(result, ["T-99"])


if __name__ == "__main__":
    unittest.main()
