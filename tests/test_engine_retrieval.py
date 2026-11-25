import copy
import json
import unittest

from research.validation.fetch_os_updates import (
    check_resolution_binding,
    checked_catalog,
    source_lines,
)
from research.validation.guard_packages import sha


class EngineRetrievalTests(unittest.TestCase):
    def setUp(self):
        packages = [
            {
                "name": name,
                "version": "1",
                "architecture": "amd64",
                "bytes": 123,
                "sha256": "a" * 64,
                "archive_path": f"pool/{'universe' if name == 'docker.io' else 'main'}/x/source/{name}_1_amd64.deb",
                "filename": f"{name}_1_amd64.deb",
            }
            for name in ("docker.io", "containerd", "runc")
        ]
        self.catalog = {
            "schema_version": 1,
            "installation_approval": None,
            "status": "resolved-not-downloaded-not-installed",
            "role": "executor container engine candidate",
            "archives": packages,
            "unique_archives": 3,
            "archive_bytes": 369,
            "counts": {"upgrades": 0, "additions": 3, "removals": 0, "held_back": 0},
            "planning_baseline": {
                "package_rows": 485,
                "projected_status_sha256": "b" * 64,
            },
            "proposed_final_package_rows": 488,
            "security_and_runtime_qualified": False,
        }
        self.metadata = {
            "packages": copy.deepcopy(packages),
            "counts": self.catalog["counts"].copy(),
            "baseline_versions": {f"base-{i}": "1" for i in range(485)},
            "projected_status_sha256": "b" * 64,
        }

    def checked(self, value=None, kind="engine"):
        raw = json.dumps(self.catalog if value is None else value).encode()
        return checked_catalog(raw, sha(raw), kind=kind)

    def test_engine_mode_is_explicit_and_does_not_change_default_sources(self):
        self.assertEqual(self.checked()["unique_archives"], 3)
        with self.assertRaises(ValueError):
            self.checked(kind="os-update")
        default = source_lines("/private/keyring", "os-update")
        engine = source_lines("/private/keyring", "engine")
        self.assertEqual(len(default), 3)
        self.assertTrue(all(line.endswith(" main") for line in default))
        self.assertEqual(engine, [line + " universe" for line in default])
        with self.assertRaises(ValueError):
            source_lines("/private/keyring", "other")

    def test_role_baseline_effects_and_qualification_scope_cannot_change(self):
        for key, value in (
            ("role", "guard"),
            ("status", "installed"),
            ("planning_baseline", {"package_rows": 480}),
            ("proposed_final_package_rows", 489),
            ("security_and_runtime_qualified", True),
            ("counts", {"upgrades": 1, "additions": 2, "removals": 0, "held_back": 0}),
        ):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.checked({**self.catalog, key: value})

    def test_archive_paths_and_integer_sizes_remain_bounded(self):
        for key, value in (
            ("archive_path", "pool/multiverse/x/source/docker.io_1_amd64.deb"),
            ("archive_path", "pool/universe/../docker.io_1_amd64.deb"),
            ("filename", "different.deb"),
            ("bytes", True),
        ):
            catalog = copy.deepcopy(self.catalog)
            catalog["archives"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.checked(catalog)

    def test_native_resolution_binding_includes_exact_archive_and_projected_status(
        self,
    ):
        self.assertEqual(
            check_resolution_binding(self.catalog, self.metadata, "engine"), "b" * 64
        )
        for key, value in (
            ("projected_status_sha256", "c" * 64),
            ("baseline_versions", {}),
            ("counts", {"upgrades": 0, "additions": 2, "removals": 0, "held_back": 0}),
        ):
            with self.subTest(key=key), self.assertRaises(ValueError):
                check_resolution_binding(
                    self.catalog, {**self.metadata, key: value}, "engine"
                )
        altered = copy.deepcopy(self.metadata)
        altered["packages"][0]["sha256"] = "c" * 64
        with self.assertRaises(ValueError):
            check_resolution_binding(self.catalog, altered, "engine")
        altered = copy.deepcopy(self.metadata)
        altered["packages"].append(altered["packages"][0].copy())
        with self.assertRaises(ValueError):
            check_resolution_binding(self.catalog, altered, "engine")


if __name__ == "__main__":
    unittest.main()
