import tempfile
import unittest
from pathlib import Path

from research.validation.engine_plan import (
    candidate_version,
    check_engine_command,
    project_status,
    verify_signed_indexes,
)
from research.validation.guard_packages import package_record, paragraphs, sha


def record(name, version):
    return {
        "Package": name,
        "Version": version,
        "Architecture": "amd64",
        "Maintainer": "Fixture <fixture@example.invalid>",
        "Description": "Synthetic metadata\n continuation",
        "Provides": "synthetic-virtual",
        "SHA256": "a" * 64,
    }


class EnginePlanTests(unittest.TestCase):
    def test_universe_archives_require_an_explicit_component_allowance(self):
        raw = (
            "Package: docker.io\nVersion: 1\nArchitecture: amd64\nFilename: pool/universe/d/docker/docker.io_1_amd64.deb\nSize: 42\nSHA256: "
            + "a" * 64
            + "\n"
        )
        with self.assertRaises(ValueError):
            package_record(raw, "docker.io", "1")
        row = package_record(raw, "docker.io", "1", components=("main", "universe"))
        self.assertTrue(row["archive_path"].startswith("pool/universe/"))
        for bad in (
            raw.replace("pool/universe/", "pool/multiverse/"),
            raw.replace("pool/universe/", "pool/universe/../"),
        ):
            with self.assertRaises(ValueError):
                package_record(bad, "docker.io", "1", components=("main", "universe"))

    def setUp(self):
        self.status = b"Package: alpha\nVersion: 1\nStatus: install ok installed\n\n"
        self.updates = [
            {"name": "alpha", "old_version": "1", "version": "2"},
            {"name": "beta", "old_version": None, "version": "1"},
        ]
        self.metadata = [record("alpha", "2"), record("beta", "1")]

    def test_projected_status_preserves_dependency_control_and_declared_versions(self):
        raw, versions = project_status(self.status, self.updates, self.metadata)
        self.assertEqual(versions, {"alpha": "2", "beta": "1"})
        rows = paragraphs(raw.decode())
        self.assertEqual([r["Status"] for r in rows], ["install ok installed"] * 2)
        self.assertEqual(rows[0]["Provides"], "synthetic-virtual")
        self.assertEqual(rows[0]["Description"], "Synthetic metadata\n continuation")
        self.assertNotIn("SHA256", rows[0])

    def test_wrong_starting_versions_missing_metadata_or_conflicting_rows_hold(self):
        with self.assertRaises(ValueError):
            project_status(
                self.status, [{**self.updates[0], "old_version": "0"}], self.metadata
            )
        with self.assertRaises(ValueError):
            project_status(self.status, self.updates + self.updates, self.metadata)
        with self.assertRaises(ValueError):
            project_status(self.status, self.updates, self.metadata[:1])
        with self.assertRaises(ValueError):
            project_status(
                self.status,
                self.updates,
                self.metadata + [{**self.metadata[0], "Depends": "changed"}],
            )

    def test_only_pinned_simulated_install_commands_are_permitted(self):
        good = [
            "apt-get",
            "--simulate",
            "--no-install-recommends",
            "--no-remove",
            "install",
            "docker.io=29.1.3-0ubuntu3~24.04.2",
        ]
        check_engine_command(good)
        for bad in (
            [x for x in good if x != "--simulate"],
            [*good[:-1], "docker.io"],
            ["apt-get", "download", "docker.io"],
            ["apt-get", "update"],
            ["apt-get", "--simulate", "--no-remove", "upgrade"],
            [*good, "--allow-unauthenticated"],
        ):
            with self.subTest(command=bad), self.assertRaises(ValueError):
                check_engine_command(bad)

    def test_candidate_is_scoped_to_its_own_package_block(self):
        self.assertEqual(
            candidate_version(
                "docker.io:\n  Candidate: 29.1.3\ncontainerd:\n  Candidate: 2.2.1\n",
                "docker.io",
            ),
            "29.1.3",
        )
        for raw in (
            "docker.io:\n  Installed: (none)\ncontainerd:\n  Candidate: 2.2.1\n",
            "docker.io:\n  Candidate: (none)\n",
            "docker.io:\n  Candidate: 29\n  Candidate: 30\n",
        ):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                candidate_version(raw, "docker.io")

    def test_both_private_component_indexes_must_match_the_signed_release(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lists = root / "state/lists"
            lists.mkdir(parents=True)
            body = b"synthetic index\n"
            paths = [
                lists
                / f"archive.ubuntu.com_ubuntu_dists_noble_{component}_binary-amd64_Packages"
                for component in ("main", "universe")
            ]
            for path in paths:
                path.write_bytes(body)
            release = {
                "Suite": "noble",
                "SHA256": "\n".join(
                    f"{sha(body)} {len(body)} {component}/binary-amd64/Packages"
                    for component in ("main", "universe")
                ),
            }
            self.assertEqual(
                set(verify_signed_indexes(root, release)), {"main", "universe"}
            )
            paths[1].write_bytes(b"changed")
            with self.assertRaises(ValueError):
                verify_signed_indexes(root, release)


if __name__ == "__main__":
    unittest.main()
