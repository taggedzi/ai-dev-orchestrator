import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from research.validation import guest_maintenance_probe as probe
from research.validation import maintenance_guest


def spec():
    return {
        "format": probe.FORMAT,
        "role": "guard",
        "run_nonce": "1" * 32,
        "target": {
            "dmi_uuid": "10000000-0000-0000-0000-000000000001",
            "root_fs_uuid": "20000000-0000-0000-0000-000000000002",
            "boot_id": "30000000-0000-0000-0000-000000000003",
        },
        "approval": {"boot": "test:boot", "observation": "test:observation"},
        "program_sha256": probe.sha(Path(probe.__file__).read_bytes()),
        "proposal_sha256": probe.PROPOSAL,
        "masks": ["apt-daily.timer", "apt-daily.service"],
        "policy": {
            "path": "/usr/sbin/policy-rc.d",
            "content": "#!/bin/sh\nexit 101\n",
            "mode": 0o755,
        },
        "private_paths": maintenance_guest.PRIVATE_PATHS.copy(),
        "config_files": {
            "/run/mcli1-maintenance/apt.config": "test config",
            "/run/mcli1-maintenance/apt/sources.list": "test sources",
            "/run/mcli1-maintenance/apt/apt.conf": "",
            "/run/mcli1-maintenance/apt/preferences": "",
        },
    }


def properties(unit, active="inactive"):
    return {
        "Id": unit,
        "Names": unit,
        "LoadState": "loaded",
        "ActiveState": active,
        "SubState": "dead",
        "UnitFileState": "disabled",
        "FragmentPath": "/usr/lib/systemd/system/" + unit,
        "DropInPaths": "",
    }


def observation(value):
    return {
        "format": probe.FORMAT,
        "role": value["role"],
        "run_nonce": value["run_nonce"],
        "target": copy.deepcopy(value["target"]),
        "baseline_status_sha256": probe.STATUS,
        "audit_stdout": "",
        "units": {
            unit: {
                "properties": properties(unit),
                "admin": {"kind": "absent"},
                "helper": {"kind": "absent"},
            }
            for unit in value["masks"]
        },
        "policy": {"kind": "absent"},
        "private_paths": {
            p: {"kind": "absent"}
            for p in value["private_paths"] + list(value["config_files"])
        },
        "dpkg_configurations": {
            "/etc/dpkg/dpkg.cfg": {
                "metadata": {"kind": "file", "sha256": "a" * 64},
                "content": "# retained review bytes\n",
            }
        },
        "package_processes": [],
        "runtime_processes": [],
        "apt_sandbox_user": {"name": "_apt", "uid": 42, "gid": 65534},
    }


class Reader:
    def __init__(self, value):
        self.value = value
        self.calls = []
        self.status = b"synthetic original package status\n"
        self.late_status = self.status
        self.status_reads = 0
        self.interfaces_value = ["lo"]

    def read(self, path, limit=probe.MAX_BYTES):
        self.calls.append(path)
        if path == "/var/lib/dpkg/status":
            self.status_reads += 1
            return self.status if self.status_reads == 1 else self.late_status
        return {
            "/proc/1/comm": b"systemd\n",
            "/sys/class/dmi/id/product_uuid": self.value["target"]["dmi_uuid"].encode(),
            "/proc/sys/kernel/random/boot_id": self.value["target"]["boot_id"].encode(),
        }[path]

    def mount(self, path):
        self.calls.append(("mount", path))
        return {"uuid": self.value["target"]["root_fs_uuid"], "fstype": "ext4"}

    def interfaces(self):
        return self.interfaces_value

    def metadata(self, path):
        self.calls.append(("metadata", path))
        return {"kind": "absent"}

    def command(self, argv):
        self.calls.append(argv)
        if argv == ["/usr/bin/dpkg", "--audit"]:
            return ""
        return "\n".join(k + "=" + v for k, v in properties(argv[-1]).items())

    def processes(self):
        return [], []

    def configurations(self):
        return {}

    def apt_identity(self):
        return {"name": "_apt", "uid": 42, "gid": 65534}


class GuestMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.spec = spec()
        self.observed = observation(self.spec)

    def test_exact_spec_binds_external_bytes_program_and_target(self):
        raw = json.dumps(self.spec).encode()
        self.assertEqual(probe.checked_spec(raw, probe.sha(raw)), self.spec)
        with self.assertRaises(probe.Refuse):
            probe.checked_spec(raw + b" ", probe.sha(raw))
        changed = copy.deepcopy(self.spec)
        changed["program_sha256"] = "0" * 64
        raw = json.dumps(changed).encode()
        with self.assertRaisesRegex(probe.Refuse, "probe changed"):
            probe.checked_spec(raw, probe.sha(raw))

    def test_unarmed_binding_and_escaped_paths_refuse(self):
        for section, key, value in [
            ("target", "boot_id", None),
            ("approval", "observation", None),
            (None, "run_nonce", None),
            (None, "private_paths", ["/etc/shadow"]),
            (None, "private_paths", ["/run/mcli1-maintenance/../outside"]),
            (None, "masks", ["--help.service"]),
        ]:
            changed = copy.deepcopy(self.spec)
            (changed[section] if section else changed)[key] = value
            raw = json.dumps(changed).encode()
            with self.subTest(key=key), self.assertRaises(probe.Refuse):
                probe.checked_spec(raw, probe.sha(raw))

    def test_non_guest_wsl_and_nonroot_refuse_before_native_reads(self):
        for system, uid, kernel in [
            ("win32", 0, "6.8"),
            ("linux", 1000, "6.8"),
            ("linux", 0, "6.8-microsoft-WSL2"),
        ]:
            reader = Reader(self.spec)
            with (
                self.subTest(system=system, uid=uid, kernel=kernel),
                self.assertRaises(probe.Refuse),
            ):
                probe.inspect(self.spec, reader, system, uid, kernel)
            self.assertEqual(reader.calls, [])

    def test_wrong_boot_or_interface_refuses_without_package_or_service_changes(self):
        reader = Reader(self.spec)
        other = copy.deepcopy(self.spec)
        other["target"]["boot_id"] = "40000000-0000-0000-0000-000000000004"
        with self.assertRaisesRegex(probe.Refuse, "identity"):
            probe.inspect(other, reader, "linux", 0, "6.8")
        reader.interfaces_value = ["lo", "enp0s3"]
        with self.assertRaisesRegex(probe.Refuse, "disconnected"):
            probe.inspect(self.spec, reader, "linux", 0, "6.8")
        self.assertFalse(any(isinstance(c, list) for c in reader.calls))

    def test_inspection_retains_raw_unit_facts_and_never_claims_host_authority(self):
        reader = Reader(self.spec)
        with patch.object(probe, "STATUS", probe.sha(reader.status)):
            result = probe.inspect(self.spec, reader, "linux", 0, "6.8")
        self.assertEqual(result["status"], "observed-not-admitted")
        self.assertEqual(result["mutations"], 0)
        self.assertFalse(result["host_timestamp_or_authority"])
        self.assertEqual(set(result["units"]), set(self.spec["masks"]))
        commands = [c for c in reader.calls if isinstance(c, list)]
        self.assertTrue(
            all(
                c[0] == "/usr/bin/systemctl"
                and "show" in c
                or c == ["/usr/bin/dpkg", "--audit"]
                for c in commands
            )
        )

    def test_status_change_during_inspection_refuses(self):
        reader = Reader(self.spec)
        reader.late_status = b"changed during query"
        with (
            patch.object(probe, "STATUS", probe.sha(reader.status)),
            self.assertRaisesRegex(probe.Refuse, "changed during"),
        ):
            probe.inspect(self.spec, reader, "linux", 0, "6.8")

    def test_mask_plan_is_create_only_and_masks_before_stopping(self):
        for row in self.observed["units"].values():
            row["properties"]["ActiveState"] = "active"
        result = probe.control_plan(self.spec, self.observed)
        self.assertFalse(result["executor_available"])
        self.assertIsNone(result["installation_authority"])
        actions = result["actions"]
        mask_indexes = [
            i
            for i, a in enumerate(actions)
            if a["action"] == "create-exclusive-symlink"
        ]
        stop_indexes = [i for i, a in enumerate(actions) if "stop" in a.get("argv", [])]
        self.assertLess(max(mask_indexes), min(stop_indexes))
        self.assertTrue(actions[stop_indexes[0]]["argv"][-1].endswith(".timer"))
        self.assertEqual(
            result["dpkg_configuration_review_required"],
            self.observed["dpkg_configurations"],
        )

    def test_conflicting_admin_policy_helper_alias_and_dropins_refuse(self):
        cases = [
            ("admin", {"kind": "file", "uid": 0, "sha256": "a" * 64}),
            ("helper", {"kind": "file", "uid": 0}),
            (
                "properties",
                {
                    **properties("apt-daily.service"),
                    "Names": "apt-daily.service unknown.service",
                },
            ),
            (
                "properties",
                {
                    **properties("apt-daily.service"),
                    "DropInPaths": "/etc/systemd/system/apt-daily.service.d/custom.conf",
                },
            ),
        ]
        for key, value in cases:
            observed = copy.deepcopy(self.observed)
            observed["units"]["apt-daily.service"][key] = value
            with self.subTest(key=key), self.assertRaises(probe.Refuse):
                probe.control_plan(self.spec, observed)
        self.observed["policy"] = {
            "kind": "file",
            "uid": 0,
            "mode": 0o755,
            "sha256": "0" * 64,
        }
        with self.assertRaises(probe.Refuse):
            probe.control_plan(self.spec, self.observed)

    def test_matching_mask_is_preserved_only_when_effective(self):
        row = self.observed["units"]["apt-daily.service"]
        row["admin"] = {
            "kind": "symlink",
            "uid": 0,
            "mode": 0o777,
            "target": "/dev/null",
        }
        with self.assertRaisesRegex(probe.Refuse, "not effective"):
            probe.control_plan(self.spec, self.observed)
        row["properties"].update(LoadState="masked", FragmentPath="/dev/null")
        actions = probe.control_plan(self.spec, self.observed)["actions"]
        self.assertFalse(
            any(
                a.get("path") == "/etc/systemd/system/apt-daily.service"
                for a in actions
            )
        )

    def test_apt_staging_ownership_and_parent_traversal_preserve_sandbox(self):
        actions = probe.control_plan(self.spec, self.observed)["actions"]
        dirs = {
            a["path"]: a for a in actions if a["action"] == "create-exclusive-directory"
        }
        for path in self.spec["private_paths"]:
            if path.startswith(("/var/lib/", "/var/cache/")):
                if path.endswith("/partial"):
                    self.assertEqual(
                        (dirs[path]["uid"], dirs[path]["gid"], dirs[path]["mode"]),
                        (42, 65534, 0o700),
                    )
                else:
                    self.assertEqual(
                        (dirs[path]["uid"], dirs[path]["mode"]), (0, 0o755)
                    )
            else:
                self.assertEqual((dirs[path]["uid"], dirs[path]["mode"]), (0, 0o700))
        for uid in (0, True, 1000):
            observed = copy.deepcopy(self.observed)
            observed["apt_sandbox_user"]["uid"] = uid
            with (
                self.subTest(uid=uid),
                self.assertRaisesRegex(probe.Refuse, "sandbox account"),
            ):
                probe.control_plan(self.spec, observed)

    def test_existing_private_state_and_background_actors_refuse_replay(self):
        for key in ["package_processes", "runtime_processes"]:
            observed = copy.deepcopy(self.observed)
            observed[key] = [{"pid": 123, "comm": "synthetic actor"}]
            with self.subTest(key=key), self.assertRaises(probe.Refuse):
                probe.control_plan(self.spec, observed)
        self.observed["private_paths"]["/run/mcli1-maintenance"] = {
            "kind": "directory",
            "uid": 0,
        }
        with self.assertRaisesRegex(probe.Refuse, "no overwrite/replay"):
            probe.control_plan(self.spec, self.observed)

    def test_ambiguous_mount_and_duplicate_or_wrong_unit_properties_hold(self):
        row = {
            "target": "/",
            "source": "/dev/sda2",
            "fstype": "ext4",
            "uuid": self.spec["target"]["root_fs_uuid"],
            "options": "rw",
            "maj:min": "8:2",
        }
        self.assertEqual(probe.one_mount(json.dumps({"filesystems": [row]}), "/"), row)
        with self.assertRaises(probe.Refuse):
            probe.one_mount(json.dumps({"filesystems": [row, row]}), "/")
        raw = "\n".join(k + "=" + v for k, v in properties("apt-daily.service").items())
        with self.assertRaises(probe.Refuse):
            probe.unit_properties(raw + "\nId=other.service", "apt-daily.service")
        with self.assertRaises(probe.Refuse):
            probe.unit_properties(raw, "other.service")

    def test_default_standalone_cli_is_a_preview_without_guest_queries(self):
        result = subprocess.run(
            [sys.executable, "-B", str(Path(probe.__file__))],
            capture_output=True,
            check=True,
            timeout=5,
        )
        self.assertEqual(
            json.loads(result.stdout),
            {
                "status": "preview",
                "native_queries": 0,
                "mutations": 0,
                "apply_available": False,
            },
        )

    def test_expired_native_query_budget_never_launches_a_process(self):
        reader = probe.NativeReader()
        reader.deadline = -1
        with (
            patch.object(probe.subprocess, "Popen") as popen,
            self.assertRaisesRegex(probe.Refuse, "deadline"),
        ):
            reader.command(["/usr/bin/dpkg", "--audit"])
        popen.assert_not_called()

    def test_native_query_vectors_cannot_be_changed_to_mutations(self):
        reader = probe.NativeReader()
        for argv in [
            ["/usr/bin/systemctl", "poweroff"],
            ["/usr/bin/dpkg", "--configure", "--pending"],
            ["/usr/bin/findmnt", "--poll"],
        ]:
            with (
                self.subTest(argv=argv),
                patch.object(probe.subprocess, "Popen") as popen,
                self.assertRaisesRegex(probe.Refuse, "allowlist"),
            ):
                reader.command(argv)
            popen.assert_not_called()

    @unittest.skipUnless(sys.platform == "linux", "POSIX pipe/process-group check")
    def test_native_pipe_deadline_output_bound_and_child_reaping(self):
        # Exercise the real Linux pipe/kill/reap path with synthetic children,
        # while passing an allowed read-only vector into the admission helper.
        original = subprocess.Popen
        cases = [
            ("import time; time.sleep(30)", "deadline"),
            (
                "import sys; sys.stdout.write('x'*8192); sys.stdout.flush()",
                "output limit",
            ),
            (
                "import sys; sys.stderr.write('x'*8192); sys.stderr.flush()",
                "output limit",
            ),
        ]
        for code, message in cases:
            children = []

            def child(_argv, _code=code, _children=children, **kwargs):
                process = original([sys.executable, "-B", "-c", _code], **kwargs)
                _children.append(process)
                return process

            with (
                self.subTest(message=message),
                patch.object(probe, "MAX_BYTES", 1024),
                patch.object(probe.subprocess, "Popen", side_effect=child),
                self.assertRaisesRegex(probe.Refuse, message),
            ):
                probe.NativeReader(seconds=0.2).command(["/usr/bin/dpkg", "--audit"])
            self.assertEqual(len(children), 1)
            self.assertIsNotNone(children[0].poll())


if __name__ == "__main__":
    unittest.main()
