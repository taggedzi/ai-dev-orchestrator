import base64
import copy
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research.validation import guest_maintenance_control as control
from research.validation import guest_maintenance_probe as probe
from research.validation import maintenance_control


def fixture():
    spec = {
        "role": "guard",
        "run_nonce": "1" * 32,
        "target": {"boot_id": "10000000-0000-0000-0000-000000000001"},
        "masks": ["apt-daily.timer"],
        "policy": {
            "path": "/usr/sbin/policy-rc.d",
            "mode": 0o755,
            "content": "#!/bin/sh\nexit 101\n",
        },
        "private_paths": ["/run/mcli1-maintenance"],
        "config_files": {"/run/mcli1-maintenance/apt.config": "synthetic config"},
    }
    observed = {
        "format": probe.FORMAT,
        "role": "guard",
        "run_nonce": spec["run_nonce"],
        "target": spec["target"],
        "baseline_status_sha256": probe.STATUS,
        "audit_stdout": "",
        "package_processes": [],
        "runtime_processes": [],
        "units": {
            "apt-daily.timer": {
                "properties": {
                    "Id": "apt-daily.timer",
                    "Names": "apt-daily.timer",
                    "LoadState": "loaded",
                    "ActiveState": "active",
                    "FragmentPath": "/usr/lib/systemd/system/apt-daily.timer",
                    "DropInPaths": "",
                },
                "admin": {"kind": "absent"},
                "helper": {"kind": "absent"},
            }
        },
        "policy": {"kind": "absent"},
        "dpkg_configurations": {},
        "private_paths": {
            p: {"kind": "absent"}
            for p in spec["private_paths"] + list(spec["config_files"])
        },
        "apt_sandbox_user": {"name": "_apt", "uid": 42, "gid": 65534},
        "guest_finished_mono_ns": 100,
    }
    plan = probe.control_plan(spec, observed)
    request = maintenance_control.draft("guard", "a" * 64)
    request.update(
        run_nonce=spec["run_nonce"],
        observation_sha256=control.sha(control.canonical(observed)),
        stable_observation_sha256=control.sha(
            control.canonical(control.stable(observed))
        ),
        plan_sha256=control.sha(control.canonical(plan)),
        dpkg_configuration_sha256=control.sha(
            control.canonical(observed["dpkg_configurations"])
        ),
        host_intent_receipt_sha256="b" * 64,
    )
    request["approval"] = {k: "test:" + k for k in request["approval"]}
    request["window"] = {
        "issued_utc_ns": 100,
        "issued_mono_ns": 200,
        "expires_utc_ns": 100 + 60 * 10**9,
        "expires_mono_ns": 200 + 60 * 10**9,
    }
    return request, spec, observed, plan


class Records:
    def __init__(self):
        self.rows = []

    def append(self, row):
        self.rows.append(copy.deepcopy(row))


class FakeTree:
    def __init__(self):
        self.changes = []

    def create_file(self, path, raw, mode):
        self.changes.append((path, raw, mode))
        return {"sha256": control.sha(raw)}

    def mkdir(self, *args):
        self.changes.append(args)
        return {"created": True}

    def symlink(self, *args):
        self.changes.append(args)
        return {"created": True}


class ControlGateTests(unittest.TestCase):
    def setUp(self):
        self.request, self.spec, self.observed, self.plan = fixture()

    def test_request_binds_raw_bytes_programs_scopes_and_fixed_window(self):
        raw = control.canonical(self.request)
        self.assertEqual(control.checked_request(raw, control.sha(raw)), self.request)
        for key, value in [
            ("program_sha256", "0" * 64),
            ("probe_sha256", "0" * 64),
            ("host_intent_receipt_sha256", None),
        ]:
            changed = copy.deepcopy(self.request)
            changed[key] = value
            raw = control.canonical(changed)
            with self.subTest(key=key), self.assertRaises(control.Refuse):
                control.checked_request(raw, control.sha(raw))
        raw = control.canonical(maintenance_control.draft("guard", None))
        with self.assertRaisesRegex(control.Refuse, "approval"):
            control.checked_request(raw, control.sha(raw))

    def test_platform_refusals_precede_any_filesystem_mutation(self):
        for system, uid, release in [
            ("win32", 0, "6.8"),
            ("linux", 1000, "6.8"),
            ("linux", 0, "6.8-microsoft-WSL2"),
        ]:
            with (
                self.subTest(system=system, uid=uid),
                patch.object(control, "OwnedTree") as tree,
                self.assertRaises(control.Refuse),
            ):
                control.platform_guard(system, uid, release)
            tree.assert_not_called()

    def test_clock_rollback_expiry_and_extension_refuse(self):
        control.check_window(self.request, lambda: 100, lambda: 200)
        for wall, mono in [(99, 200), (100, 199), (100 + 60 * 10**9, 200)]:
            with self.subTest(wall=wall, mono=mono), self.assertRaises(control.Refuse):
                control.check_window(
                    self.request, lambda value=wall: value, lambda value=mono: value
                )
        self.request["window"]["expires_mono_ns"] += 1
        raw = control.canonical(self.request)
        with self.assertRaises(control.Refuse):
            control.checked_request(raw, control.sha(raw))

    def test_fresh_review_comparison_ignores_only_guest_timestamp(self):
        fresh = copy.deepcopy(self.observed)
        fresh["guest_finished_mono_ns"] += 999
        result = control.validate_observations(
            self.request, self.spec, control.canonical(self.observed), fresh, probe
        )
        self.assertEqual(result, self.plan)
        fresh["units"]["apt-daily.timer"]["properties"]["ActiveState"] = "inactive"
        with self.assertRaisesRegex(control.Refuse, "differs from review"):
            control.validate_observations(
                self.request, self.spec, control.canonical(self.observed), fresh, probe
            )

    def test_approved_plan_digest_cannot_substitute_a_changed_action(self):
        self.request["plan_sha256"] = "0" * 64
        with self.assertRaisesRegex(control.Refuse, "regenerated"):
            control.validate_observations(
                self.request,
                self.spec,
                control.canonical(self.observed),
                self.observed,
                probe,
            )

    def test_action_intent_is_recorded_before_io_and_reported_before_next(self):
        records, tree = Records(), FakeTree()
        actions = [
            {
                "action": "create-exclusive-file",
                "path": "/safe/new",
                "content": "hello",
                "mode": 0o600,
            }
        ]

        def create(*args):
            self.assertEqual(records.rows[-1]["phase"], "action-intent")
            return {"created": True}

        tree.create_file = create
        self.assertEqual(
            control.execute_actions(actions, tree, None, records, lambda: None), 1
        )
        self.assertEqual(
            [r["phase"] for r in records.rows], ["action-intent", "action-reported"]
        )

    def test_journal_failure_before_io_prevents_mutation_and_after_io_retains_it(self):
        actions = [
            {
                "action": "create-exclusive-file",
                "path": "/safe/new",
                "content": "x",
                "mode": 0o600,
            }
        ]
        tree, records = FakeTree(), Records()
        with (
            patch.object(records, "append", side_effect=OSError("synthetic disk full")),
            self.assertRaises(OSError),
        ):
            control.execute_actions(actions, tree, None, records, lambda: None)
        self.assertEqual(tree.changes, [])

        def append(row):
            if row["phase"] == "action-reported":
                raise OSError("synthetic lost report")
            records.rows.append(row)

        records.append = append
        with self.assertRaises(OSError):
            control.execute_actions(actions, tree, None, records, lambda: None)
        self.assertEqual(len(tree.changes), 1)
        self.assertEqual(records.rows[-1]["phase"], "action-intent")

    def test_journal_latency_counts_before_mutation(self):
        tree, records, calls = FakeTree(), Records(), []

        def check():
            calls.append(1)
            if len(calls) == 2:
                raise control.Refuse("expired during fsync")

        with self.assertRaises(control.Refuse):
            control.execute_actions(self.plan["actions"], tree, None, records, check)
        self.assertEqual(tree.changes, [])
        self.assertEqual(records.rows[-1]["phase"], "action-intent")

    def test_failed_or_warned_control_command_is_not_success(self):
        for result in [
            {"exit": 1},
            {
                "exit": 0,
                "timed_out": False,
                "output_exceeded": False,
                "stdout_base64": "",
                "stderr_base64": "d2FybmluZw==",
            },
        ]:
            records = Records()
            with self.subTest(result=result), self.assertRaises(control.Refuse):
                control.execute_actions(
                    [
                        {
                            "action": "reviewed-command",
                            "argv": ["/usr/bin/systemctl", "daemon-reload"],
                        }
                    ],
                    None,
                    lambda _, value=result: value,
                    records,
                    lambda: None,
                )
            self.assertEqual(records.rows[-1]["phase"], "action-reported")

    def test_only_daemon_reload_and_reviewed_stops_can_launch(self):
        commands = control.ControlCommands(self.spec["masks"], lambda: None)
        for argv in [
            ["/usr/bin/apt-get", "install", "anything"],
            ["/usr/bin/systemctl", "poweroff"],
            ["/usr/bin/systemctl", "--no-ask-password", "stop", "unreviewed.service"],
        ]:
            with (
                self.subTest(argv=argv),
                patch.object(control.subprocess, "Popen") as popen,
                self.assertRaises(control.Refuse),
            ):
                commands(argv)
            popen.assert_not_called()

    def test_postconditions_require_effective_masks_and_unchanged_dpkg(self):
        post = copy.deepcopy(self.observed)
        post["policy"] = {
            "kind": "file",
            "uid": 0,
            "mode": 0o755,
            "sha256": control.sha(self.spec["policy"]["content"].encode()),
        }
        row = post["units"]["apt-daily.timer"]
        row["admin"] = {"kind": "symlink", "uid": 0, "target": "/dev/null"}
        row["properties"].update(
            LoadState="masked", FragmentPath="/dev/null", ActiveState="inactive"
        )
        actions = {a["path"]: a for a in self.plan["actions"] if "path" in a}

        class PostTree:
            def metadata(self, path):
                action = actions[path]
                if action["action"] == "create-exclusive-directory":
                    return {
                        "kind": "directory",
                        **{k: action[k] for k in ("uid", "gid", "mode")},
                    }
                return {
                    "kind": "file",
                    "uid": 0,
                    "mode": action["mode"],
                    "links": 1,
                    "sha256": control.sha(action["content"].encode()),
                }

        control.verify_post(self.spec, post, self.plan, PostTree(), probe)
        changed = copy.deepcopy(post)
        changed["dpkg_configurations"] = {"changed": True}
        with self.assertRaisesRegex(control.Refuse, "dpkg configuration"):
            control.verify_post(self.spec, changed, self.plan, PostTree(), probe)
        changed = copy.deepcopy(post)
        changed["units"]["apt-daily.timer"]["properties"]["LoadState"] = "loaded"
        with self.assertRaisesRegex(control.Refuse, "effective"):
            control.verify_post(self.spec, changed, self.plan, PostTree(), probe)

    def test_standalone_default_is_unarmed_without_mutations(self):
        result = subprocess.run(
            [sys.executable, "-B", str(Path(control.__file__))],
            capture_output=True,
            check=True,
            timeout=5,
        )
        self.assertEqual(
            json.loads(result.stdout),
            {
                "status": "unarmed-preview",
                "mutations": 0,
                "installation_available": False,
            },
        )


@unittest.skipUnless(sys.platform == "linux", "POSIX exclusive filesystem/child checks")
class NativeControlPrimitiveTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="mcli1-control-test-")
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        (self.root / "safe").mkdir(mode=0o700)
        (self.root / "var").mkdir(mode=0o755)
        (self.root / "var/lib").mkdir(mode=0o755)
        self.tree = control.OwnedTree(self.root, owner=os.getuid())
        self.addCleanup(self.tree.close)

    def test_exclusive_file_and_mask_never_overwrite_existing_bytes(self):
        self.tree.create_file("/safe/policy", b"retained", 0o600)
        with self.assertRaises(FileExistsError):
            self.tree.create_file("/safe/policy", b"replacement", 0o755)
        self.assertEqual((self.root / "safe/policy").read_bytes(), b"retained")
        self.assertEqual(
            stat.S_IMODE((self.root / "safe/policy").stat().st_mode), 0o600
        )
        self.tree.symlink("/safe/mask.service", "/dev/null")
        with self.assertRaises(FileExistsError):
            self.tree.symlink("/safe/mask.service", "/dev/null")
        self.assertEqual(os.readlink(self.root / "safe/mask.service"), "/dev/null")

    def test_symlink_ancestors_writable_parents_and_path_escapes_refuse(self):
        outside = self.root / "outside"
        outside.mkdir(mode=0o700)
        os.symlink(outside, self.root / "safe/link")
        with self.assertRaises(OSError):
            self.tree.create_file("/safe/link/escape", b"bad")
        self.assertFalse((outside / "escape").exists())
        os.chmod(self.root / "safe", 0o777)
        with self.assertRaises(control.Refuse):
            self.tree.create_file("/safe/unsafe", b"bad")
        for path in ["/safe/../outside/file", "//safe/file", "/safe/./file"]:
            with self.subTest(path=path), self.assertRaises(control.Refuse):
                self.tree.create_file(path, b"bad")

    def test_hardlinked_or_foreign_owned_inputs_are_not_approved(self):
        self.tree.create_file("/safe/original", b"private")
        os.link(self.root / "safe/original", self.root / "safe/alias")
        with self.assertRaises(control.Refuse):
            self.tree.read("/safe/original")
        with self.assertRaises(control.Refuse):
            control.OwnedTree(self.root, owner=os.getuid() + 1)

    def test_partial_file_write_remains_and_refuses_replay(self):
        original, calls = os.write, []

        def interrupted(fd, data):
            calls.append(1)
            if len(calls) > 1:
                raise OSError("synthetic write interrupted")
            return original(fd, data[:3])

        with (
            patch.object(control.os, "write", side_effect=interrupted),
            self.assertRaises(OSError),
        ):
            self.tree.create_file("/safe/partial", b"abcdef")
        self.assertEqual((self.root / "safe/partial").read_bytes(), b"abc")
        with self.assertRaises(FileExistsError):
            self.tree.create_file("/safe/partial", b"abcdef")

    def test_global_journal_survives_close_and_rejects_a_fresh_attempt(self):
        journal = control.Journal(self.tree, {"request.json": b"{}"})
        journal.append({"phase": "action-intent", "index": 0})
        journal.append({"phase": "action-reported", "index": 0})
        last = journal.last
        journal.close()
        raw = self.tree.read(control.STATE + "/events.jsonl")
        rows = [json.loads(line) for line in raw.splitlines()]
        self.assertEqual(
            rows[1]["previous_sha256"], control.sha(control.canonical(rows[0]))
        )
        self.assertEqual(last, control.sha(control.canonical(rows[1])))
        with self.assertRaises(FileExistsError):
            control.Journal(self.tree, {"request.json": b"new attempt"})
        self.assertEqual(self.tree.read(control.STATE + "/events.jsonl"), raw)

    def test_real_child_capture_timeout_output_bound_and_reaping(self):
        original = subprocess.Popen
        cases = [
            ("print('captured')", False, False),
            ("import time; time.sleep(10)", True, False),
            (
                "import sys; sys.stdout.buffer.write(b'x'*(128*1024)); sys.stdout.buffer.flush()",
                False,
                True,
            ),
        ]
        for code, timed_out, exceeded in cases:
            children = []

            def launch(_argv, _code=code, _children=children, **kwargs):
                child = original([sys.executable, "-B", "-c", _code], **kwargs)
                _children.append(child)
                return child

            with (
                self.subTest(code=code),
                patch.object(control.subprocess, "Popen", side_effect=launch),
            ):
                result = control.ControlCommands([], lambda: None, seconds=0.2)(
                    ["/usr/bin/systemctl", "daemon-reload"]
                )
            self.assertEqual(result["timed_out"], timed_out)
            self.assertEqual(result["output_exceeded"], exceeded)
            self.assertIsNotNone(children[0].poll())
            if not timed_out and not exceeded:
                self.assertEqual(result["exit"], 0)
                self.assertEqual(
                    base64.b64decode(result["stdout_base64"]), b"captured\n"
                )


if __name__ == "__main__":
    unittest.main()
