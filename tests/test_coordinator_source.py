"""Actual scratch Git objects and artifact files; no candidate code runs."""

import dataclasses
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from coordinator.domain import Conflict, Invalid
from coordinator.evidence import EvidenceStore
from coordinator.source import CandidateBinding, Snapshot, SourceFile, TrustedRepository


class SnapshotTests(unittest.TestCase):
    def test_paths_modes_and_cross_platform_aliases_are_rejected(self):
        for path in (
            "../secret",
            "/root",
            "a//b",
            "a/./b",
            "a/../b",
            ".git/config",
            "src/.GIT/config",
            "git~1/config",
            "C:/file",
            "a\\b",
            "a:b",
            "con.txt",
            "a/LPT¹.log",
            "a.",
            "a ",
            "a\nb",
            "e\u0301.py",
        ):
            with self.subTest(path=path), self.assertRaises(Invalid):
                Snapshot({path: SourceFile(b"x")})
        for files in (
            {"src": SourceFile(b"x"), "src/a": SourceFile(b"y")},
            {"Src/a": SourceFile(b"x"), "src/b": SourceFile(b"y")},
            {"a": SourceFile(b"x"), "A": SourceFile(b"y")},
        ):
            with self.assertRaises(Invalid):
                Snapshot(files)
        for mode in ("120000", "160000", "040000"):
            with self.assertRaises(Invalid):
                SourceFile(b"not a regular file", mode)

    def test_snapshot_does_not_retain_mutable_input_or_manifest(self):
        files = {"é.py": SourceFile(b"a\r\n\0b", "100755")}
        snapshot = Snapshot(files)
        files.clear()
        snapshot.manifest[0]["sha256"] = "forged"
        copy = snapshot.files()
        copy.clear()
        self.assertEqual(snapshot.files()["é.py"].data, b"a\r\n\0b")
        self.assertEqual(
            snapshot.manifest[0]["sha256"], hashlib.sha256(b"a\r\n\0b").hexdigest()
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            snapshot.digest = "forged"

    def test_snapshot_limits_are_checked_before_git_writes(self):
        with (
            patch("coordinator.source.MAX_SNAPSHOT_BYTES", 3),
            self.assertRaises(Invalid),
        ):
            Snapshot({"a": SourceFile(b"12"), "b": SourceFile(b"34")})
        with patch("coordinator.source.MAX_FILES", 1), self.assertRaises(Invalid):
            Snapshot({"a": SourceFile(b""), "b": SourceFile(b"")})


class ArtifactTests(unittest.TestCase):
    def test_atomic_deduplication_corruption_and_unfinished_temp(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "evidence"
            store = EvidenceStore.create(root)
            (root / "pending-crashed-writer").write_bytes(b"unfinished")
            first = store.put(b"trusted observed output")
            self.assertEqual(store.put(b"trusted observed output"), first)
            self.assertEqual(store.read(first["sha256"]), b"trusted observed output")
            target = root / first["sha256"]
            target.write_bytes(b"changed")
            with self.assertRaises(Conflict):
                store.put(b"trusted observed output")
            self.assertEqual(target.read_bytes(), b"changed")
            self.assertEqual(
                (root / "pending-crashed-writer").read_bytes(), b"unfinished"
            )
            with self.assertRaises(Invalid):
                store.read("../secret")

    def test_linked_evidence_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            store = EvidenceStore.create(Path(temp) / "evidence")
            item = store.put(b"content")
            os.link(store.root / item["sha256"], Path(temp) / "alias")
            with self.assertRaises(Conflict):
                store.read(item["sha256"])


@unittest.skipUnless(shutil.which("git"), "requires installed Git")
class GitIntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = TrustedRepository.create(self.root / "managed")
        self.initial = Snapshot(
            {
                "src/a.txt": SourceFile(b"original\r\n"),
                "README.md": SourceFile(b"baseline"),
            }
        )
        self.base = self.repo.baseline(self.initial)
        self.binding = CandidateBinding("attempt-01", "a" * 64, "b" * 64, 1)

    def test_scope_parent_exact_bytes_private_ref_and_reopen(self):
        files = self.initial.files()
        files["src/a.txt"] = SourceFile(b"candidate\r\n\0raw", "100755")
        changed = Snapshot(files)
        receipt = self.repo.seal(
            self.base["revision"],
            changed,
            allowed_paths=["src/a.txt"],
            binding=self.binding,
        )
        self.assertEqual(receipt["parents"], [self.base["revision"]])
        commit = self.repo._run("cat-file", "commit", receipt["revision"]).stdout
        self.assertIn(f"parent {self.base['revision']}\n".encode(), commit)
        self.assertEqual(commit.count(b"\nparent "), 1)
        self.assertEqual(
            self.repo.snapshot(receipt["revision"]).files(), changed.files()
        )
        self.assertFalse(receipt["task_accepted"])
        self.assertTrue(receipt["ref"].startswith("refs/orchestrator/candidates/"))
        reopened = TrustedRepository(self.repo.root)
        duplicate = reopened.seal(
            self.base["revision"],
            changed,
            allowed_paths=["src/a.txt"],
            binding=self.binding,
        )
        self.assertEqual(duplicate["revision"], receipt["revision"])
        self.assertTrue(duplicate["reconciled_existing"])
        refs = (
            self.repo._run("for-each-ref", "--format=%(refname)")
            .stdout.decode()
            .splitlines()
        )
        self.assertEqual(set(refs), {self.base["ref"], receipt["ref"]})

    def test_deletion_addition_mode_and_out_of_scope_refusal(self):
        for path, file in (
            ("README.md", SourceFile(b"changed")),
            ("outside.txt", SourceFile(b"new")),
            ("README.md", SourceFile(b"baseline", "100755")),
            ("README.md", None),
        ):
            files = self.initial.files()
            if file is None:
                del files[path]
            else:
                files[path] = file
            with self.subTest(path=path, file=file), self.assertRaises(Conflict):
                self.repo.seal(
                    self.base["revision"],
                    Snapshot(files),
                    allowed_paths=["src/a.txt"],
                    binding=self.binding,
                )
        files = self.initial.files()
        del files["src/a.txt"]
        files["src/new.txt"] = SourceFile(b"new")
        receipt = self.repo.seal(
            self.base["revision"],
            Snapshot(files),
            allowed_paths=["src/a.txt", "src/new.txt"],
            binding=self.binding,
        )
        self.assertEqual(receipt["changed_paths"], ["src/a.txt", "src/new.txt"])

    def test_hostile_environment_and_attributes_do_not_transform_source(self):
        files = self.initial.files()
        files[".gitattributes"] = SourceFile(b"*.txt filter=malicious text eol=lf\n")
        files["src/a.txt"] = SourceFile(b"unchanged\r\n\xff")
        with patch.dict(
            os.environ,
            {
                "GIT_DIR": str(self.root / "forbidden"),
                "GIT_OBJECT_DIRECTORY": str(self.root / "outside"),
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "core.hooksPath",
                "GIT_CONFIG_VALUE_0": str(self.root / "evil-hooks"),
            },
        ):
            receipt = self.repo.seal(
                self.base["revision"],
                Snapshot(files),
                allowed_paths=[".gitattributes", "src/a.txt"],
                binding=self.binding,
            )
        self.assertEqual(self.repo.snapshot(receipt["revision"]).files(), files)
        self.assertFalse((self.root / "outside").exists())

    def test_private_ref_collision_and_symbolic_ref_are_held(self):
        first = self.repo.seal(
            self.base["revision"],
            self.initial,
            allowed_paths=["src/a.txt"],
            binding=self.binding,
        )
        self.repo._run(
            "update-ref", first["ref"], self.base["revision"], first["revision"]
        )
        with self.assertRaises(Conflict):
            self.repo.seal(
                self.base["revision"],
                self.initial,
                allowed_paths=["src/a.txt"],
                binding=self.binding,
            )
        self.repo._run("symbolic-ref", first["ref"], self.base["ref"])
        with self.assertRaises(Conflict):
            self.repo.seal(
                self.base["revision"],
                self.initial,
                allowed_paths=["src/a.txt"],
                binding=self.binding,
            )

    def test_config_and_external_object_tampering_refused_before_git(self):
        config = self.repo.repository / "config"
        original = config.read_bytes()
        config.write_bytes(original + b"\n[include]\npath = /unknown\n")
        with self.assertRaises(Conflict):
            self.repo.snapshot(self.base["revision"])
        config.write_bytes(original)
        alternates = self.repo.repository / "objects/info/alternates"
        alternates.write_text(str(self.root / "outside"), encoding="utf-8")
        with self.assertRaises(Conflict):
            self.repo.snapshot(self.base["revision"])

    def test_changed_candidate_requires_fresh_attempt_and_changes_revision(self):
        first = self.repo.seal(
            self.base["revision"],
            self.initial,
            allowed_paths=["src/a.txt"],
            binding=self.binding,
        )
        files = self.initial.files()
        files["src/a.txt"] = SourceFile(b"corrected")
        with self.assertRaises(Conflict):
            self.repo.seal(
                self.base["revision"],
                Snapshot(files),
                allowed_paths=["src/a.txt"],
                binding=self.binding,
            )
        corrected = self.repo.seal(
            self.base["revision"],
            Snapshot(files),
            allowed_paths=["src/a.txt"],
            binding=CandidateBinding("attempt-02", "a" * 64, "b" * 64, 1),
        )
        self.assertNotEqual(corrected["revision"], first["revision"])

    def test_actual_process_exit_after_ref_update_reconciles_without_replacement(self):
        program = """
import os, sys
from coordinator.source import CandidateBinding, Snapshot, SourceFile, TrustedRepository
repo = TrustedRepository(sys.argv[1])
repo.seal(sys.argv[2], Snapshot({"src/a.txt": SourceFile(b"original\\r\\n"), "README.md": SourceFile(b"baseline")}), allowed_paths=["src/a.txt"], binding=CandidateBinding("attempt-01", "a"*64, "b"*64, 1))
os._exit(29)
"""
        process = subprocess.run(
            [sys.executable, "-c", program, str(self.repo.root), self.base["revision"]],
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(process.returncode, 29, process.stderr)
        reopened = TrustedRepository(self.repo.root)
        recovered = reopened.seal(
            self.base["revision"],
            self.initial,
            allowed_paths=["src/a.txt"],
            binding=self.binding,
        )
        self.assertTrue(recovered["reconciled_existing"])
        refs = (
            reopened._run("for-each-ref", "--format=%(refname)")
            .stdout.decode()
            .splitlines()
        )
        self.assertEqual(len(refs), 2)


if __name__ == "__main__":
    unittest.main()
