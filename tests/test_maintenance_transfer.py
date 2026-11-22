import ast
import base64
import copy
import hashlib
import json
import os
import random
import shlex
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

from research.validation import guest_maintenance_control as control
from research.validation import guest_maintenance_probe as probe
from research.validation import guest_transfer_entry as entry
from research.validation import maintenance_serial as transport
from research.validation import maintenance_serial_worker as serial
from research.validation import maintenance_transfer as transfer
from research.validation import transfer_commands as commands
from research.validation.maintenance_config import PROPOSAL, proposal, render, sources
from research.validation.maintenance_control import draft as control_draft
from research.validation.maintenance_guest import PRIVATE_PATHS
from research.validation.store import Hold, Store
from research.validation.supervisor import LeaseSupervisor


def unpack(step):
    args = shlex.split(step["send"])
    if args[:4] != ["/usr/bin/python3", "-I", "-B", "-c"]:
        raise AssertionError("unexpected guest invocation")
    tree = ast.parse(args[4])
    call = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "b64decode"
    )
    return zlib.decompress(base64.b64decode(ast.literal_eval(call.args[0]))).decode()


def bound_fixture(purpose="inspect", role="guard"):
    planned = proposal(PROPOSAL.read_bytes())
    target = {
        "dmi_uuid": "11111111-1111-4111-8111-111111111111",
        "root_fs_uuid": "22222222-2222-4222-8222-222222222222",
        "boot_id": "33333333-3333-4333-8333-333333333333",
    }
    nonce = "1" * 32
    spec = {
        "format": probe.FORMAT,
        "role": role,
        "run_nonce": nonce,
        "target": target,
        "approval": {"boot": "test:boot", "observation": "test:observation"},
        "program_sha256": entry.PROBE_SHA,
        "proposal_sha256": probe.PROPOSAL,
        "masks": planned["common_admin_masks_proposal"]
        + planned["roles"][role]["additional_admin_masks"],
        "policy": {
            "path": "/usr/sbin/policy-rc.d",
            "content": "#!/bin/sh\nexit 101\n",
            "mode": 0o755,
        },
        "private_paths": PRIVATE_PATHS,
        "config_files": {
            "/run/mcli1-maintenance/apt.config": render(planned),
            "/run/mcli1-maintenance/apt/sources.list": sources(),
            "/run/mcli1-maintenance/apt/apt.conf": "",
            "/run/mcli1-maintenance/apt/preferences": "",
        },
    }
    observed = {
        "format": probe.FORMAT,
        "status": "observed-not-admitted",
        "role": role,
        "run_nonce": nonce,
        "target": target,
        "kernel_release": "6.8-test",
        "baseline_status_sha256": probe.STATUS,
        "audit_stdout": "",
        "units": {
            name: {
                "properties": {
                    "Id": name,
                    "Names": name,
                    "LoadState": "loaded",
                    "ActiveState": "inactive",
                    "FragmentPath": "/usr/lib/systemd/system/" + name,
                    "DropInPaths": "",
                },
                "admin": {"kind": "absent"},
                "helper": {"kind": "absent"},
            }
            for name in spec["masks"]
        },
        "policy": {"kind": "absent"},
        "private_paths": {
            name: {"kind": "absent"}
            for name in PRIVATE_PATHS + list(spec["config_files"])
        },
        "dpkg_configurations": {},
        "apt_sandbox_user": {"name": "_apt", "uid": 42, "gid": 65534},
        "package_processes": [],
        "runtime_processes": [],
        "guest_finished_mono_ns": 900 * 10**9 + 1,
        "mutations": 0,
        "host_timestamp_or_authority": False,
    }
    files = {
        "guest_maintenance_probe.py": Path(probe.__file__).read_bytes(),
        "inspection-spec.json": commands.canonical(spec),
    }
    plan = probe.control_plan(spec, observed)
    if purpose == "controls":
        request = control_draft(role, commands.digest(files["inspection-spec.json"]))
        request.update(
            run_nonce=nonce,
            observation_sha256=commands.digest(commands.canonical(observed)),
            stable_observation_sha256=transfer.digest(control.stable(observed)),
            plan_sha256=transfer.digest(plan),
            dpkg_configuration_sha256=transfer.digest({}),
            host_intent_receipt_sha256="a" * 64,
        )
        request["approval"] = {
            k: "test:" + ("controls" if k == "control_changes" else k)
            for k in request["approval"]
        }
        request["window"] = {
            "issued_utc_ns": 2 * 10**18,
            "issued_mono_ns": 900 * 10**9,
            "expires_utc_ns": 2 * 10**18 + 30 * 10**9,
            "expires_mono_ns": 930 * 10**9,
        }
        files.update(
            {
                "guest_maintenance_control.py": Path(control.__file__).read_bytes(),
                "request.json": commands.canonical(request),
                "observation.json": commands.canonical(observed),
            }
        )
    grant = transfer.draft(role, purpose, files)
    wall, mono = time.time_ns(), time.monotonic_ns()
    disk = (
        transfer.EXECUTOR_DISK
        if role == "executor"
        else "44444444-4444-4444-8444-444444444444"
    )
    grant.update(run_nonce=nonce, generation=1)
    grant["target"].update(disk_uuid=disk, **target)
    grant["disk_evidence"] = {key: "b" * 64 for key in grant["disk_evidence"]}
    grant["backup"] = {
        "source_disk_uuid": disk,
        "disk_uuid": "55555555-5555-4555-8555-555555555555",
        "disk_sha256": "c" * 64,
        "configuration_sha256": "d" * 64,
        "nvram_sha256": "e" * 64,
        "receipt_sha256": "f" * 64,
    }
    grant["approval"] = {k: "test:" + k for k in grant["approval"]}
    if purpose == "inspect":
        grant["approval"].update(controls=None, dpkg_configuration_review=None)
    grant["lease"] = {
        "owner_nonce": "2" * 32,
        "expires_utc_ns": wall + 600 * 10**9,
        "expires_mono_ns": mono + 600 * 10**9,
    }
    grant["phase_window"] = {
        "issued_utc_ns": wall,
        "issued_mono_ns": mono,
        "expires_utc_ns": wall + 90 * 10**9,
        "expires_mono_ns": mono + 90 * 10**9,
    }
    identity = {
        **target,
        "root_dev": 2049,
        "root_ino": 2,
        "mnt_ino": 4026531841,
        "guest_utc_ns": 2 * 10**18,
        "guest_mono_ns": 900 * 10**9,
    }
    return grant, files, observed, identity, plan


class TransferCompilerTests(unittest.TestCase):
    def test_control_plan_is_stable_across_sorted_json_roundtrip(self):
        grant, files, observed, _, plan = bound_fixture("controls")
        spec = json.loads(files["inspection-spec.json"])
        restored = json.loads(commands.canonical(observed))
        self.assertEqual(probe.control_plan(spec, restored), plan)
        transfer.payloads(grant, files)

    def test_fixed_cohort_and_both_purpose_role_compilations_fit_native_limits(self):
        for purpose in ("inspect", "controls"):
            for role in ("guard", "executor"):
                grant, files, _, identity, _ = bound_fixture(purpose, role)
                raw = commands.canonical(grant)
                sha = commands.digest(raw)
                self.assertEqual(transfer.checked_grant(raw, sha), grant)
                transfer.payloads(grant, files)
                envelope = {
                    "format": "mcli1-transfer-identity-v1",
                    "run_nonce": grant["run_nonce"],
                    "grant_sha256": sha,
                    "identity": identity,
                }
                _, window = transfer.identity_window(
                    grant, envelope, sha, time.time_ns(), time.monotonic_ns()
                )
                gate = commands.identity_request(grant, sha)
                compiled = commands.compile_upload(grant, sha, identity, window, files)
                for request in (gate, compiled["request"]):
                    wire = commands.canonical(request)
                    serial.checked(wire, commands.digest(wire))
                    self.assertLessEqual(len(request["steps"]), 128)
                    for step in request["steps"]:
                        self.assertLessEqual(len(step["send"]), 2047)
                        compile(unpack(step), "<test-compiled>", "exec")
                self.assertEqual(
                    compiled["request"]["expires_mono_ns"],
                    grant["phase_window"]["expires_mono_ns"],
                )

    def test_unarmed_and_changed_source_grants_refuse_before_dispatch(self):
        raw = commands.canonical(transfer.draft("guard", "inspect", {}))
        with self.assertRaisesRegex(Hold, "approval"):
            transfer.checked_grant(raw, commands.digest(raw))
        grant, _, _, _, _ = bound_fixture()
        grant["sources"]["entry"] = "0" * 64
        raw = commands.canonical(grant)
        with self.assertRaisesRegex(Hold, "source cohort"):
            transfer.checked_grant(raw, commands.digest(raw))

    def test_partial_or_weakened_control_inventory_cannot_hide_in_payload_hash(self):
        grant, files, _, _, _ = bound_fixture()
        spec = json.loads(files["inspection-spec.json"])
        spec["masks"] = spec["masks"][:1]
        files["inspection-spec.json"] = commands.canonical(spec)
        grant["files"]["inspection-spec.json"] = {
            "bytes": len(files["inspection-spec.json"]),
            "sha256": commands.digest(files["inspection-spec.json"]),
        }
        with self.assertRaisesRegex(Hold, "inventory"):
            transfer.payloads(grant, files)

    def test_guest_clock_budget_uses_remaining_host_time_without_copying_clock(self):
        grant, _, _, identity, _ = bound_fixture()
        sha = transfer.digest(grant)
        envelope = {
            "format": "mcli1-transfer-identity-v1",
            "run_nonce": grant["run_nonce"],
            "grant_sha256": sha,
            "identity": identity,
        }
        _, window = transfer.identity_window(
            grant,
            envelope,
            sha,
            grant["phase_window"]["expires_utc_ns"] - 7 * 10**9,
            grant["phase_window"]["expires_mono_ns"] - 8 * 10**9,
        )
        self.assertEqual(
            window["expires_mono_ns"], identity["guest_mono_ns"] + 7 * 10**9
        )
        self.assertNotEqual(
            window["expires_mono_ns"], grant["phase_window"]["expires_mono_ns"]
        )

    def test_changed_identity_and_extended_phase_or_source_disk_alias_refuse(self):
        for changed in ("phase", "disk", "backup"):
            grant, _, _, _, _ = bound_fixture()
            if changed == "phase":
                grant["phase_window"]["expires_mono_ns"] += 1
            if changed == "disk":
                grant["target"]["disk_uuid"] = transfer.EXECUTOR_DISK
            if changed == "backup":
                grant["backup"]["disk_uuid"] = grant["target"]["disk_uuid"]
            raw = commands.canonical(grant)
            with self.subTest(changed=changed), self.assertRaises(Hold):
                transfer.checked_grant(raw, commands.digest(raw))

    def test_payload_size_or_step_overflow_refuses_in_compiler(self):
        grant, _, _, identity, _ = bound_fixture()
        window = {
            "issued_utc_ns": identity["guest_utc_ns"],
            "issued_mono_ns": identity["guest_mono_ns"],
            "expires_utc_ns": identity["guest_utc_ns"] + 60 * 10**9,
            "expires_mono_ns": identity["guest_mono_ns"] + 60 * 10**9,
        }
        raw = random.Random(1).randbytes(100000)
        with self.assertRaisesRegex(serial.Refuse, "too many"):
            commands.compile_upload(
                grant,
                transfer.digest(grant),
                identity,
                window,
                {"inspection-spec.json": raw},
            )

    def test_entry_defaults_to_preview_without_guest_queries(self):
        result = subprocess.run(
            [sys.executable, "-B", str(Path(entry.__file__))],
            capture_output=True,
            check=True,
            timeout=5,
        )
        self.assertEqual(
            json.loads(result.stdout), {"status": "unarmed-preview", "mutations": 0}
        )


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = Store(Path(self.folder.name) / "transfer.sqlite")
        self.addCleanup(self.store.close)
        self.grant, self.files, self.observed, self.identity, self.plan = (
            bound_fixture()
        )
        lease = self.grant["lease"]
        self.supervisor = LeaseSupervisor(
            self.store,
            {
                "target_vm_uuid": self.grant["target"]["vm_uuid"],
                "lease_expires_utc_ns": lease["expires_utc_ns"],
            },
            now_ns=lease["expires_utc_ns"] - 600 * 10**9,
            monotonic_ns=lease["expires_mono_ns"] - 600 * 10**9,
        )
        self.sent, self.stops, self.fail_at = [], [], None
        self.native_stop_requests = []
        self.bad_host = False

    def snapshot(self):
        now = time.monotonic_ns()
        host = transfer.expected_host(self.grant)
        if self.bad_host:
            host["nics"][0] = "nat"
        return {
            "observed_mono_ns": now,
            "host": host,
            "backup_receipt_sha256": self.grant["backup"]["receipt_sha256"],
            "disk_evidence": copy.deepcopy(self.grant["disk_evidence"]),
            "supervisor": {
                "observed_mono_ns": now,
                "live": True,
                "target_vm_uuid": self.grant["target"]["vm_uuid"],
                **self.grant["lease"],
            },
        }

    def stop(self, grant):
        self.stops.append(grant["run_nonce"])
        self.assertEqual(
            self.store.db.execute("SELECT active FROM authority").fetchone()["active"],
            0,
        )
        self.supervisor.poll(
            stopper=lambda *_: self.native_stop_requests.append(
                grant["target"]["vm_uuid"]
            )
        )
        return {
            "vm_uuid": grant["target"]["vm_uuid"],
            "run_nonce": grant["run_nonce"],
            "state": "poweroff",
            "disks": [grant["target"]["disk_uuid"]],
            "nics": ["none"] * 8,
            "shares": [],
            "receipt_sha256": "a" * 64,
            "observed_mono_ns": time.monotonic_ns(),
            "elapsed_ns": 0,
        }

    def sender(self, store, raw, sha, generation, cancelled):
        request = serial.checked(raw, sha)
        transport.persist_intent(store, raw, sha, generation)
        self.sent.append(request)
        if self.fail_at == len(self.sent):
            raise TimeoutError("synthetic lost acknowledgement")
        grant_sha = transfer.digest(self.grant)
        if len(self.sent) == 1:
            result = {
                "format": "mcli1-transfer-identity-v1",
                "run_nonce": self.grant["run_nonce"],
                "grant_sha256": grant_sha,
                "identity": self.identity,
            }
        else:
            tree = ast.parse(unpack(request["steps"][-1]))
            assignment = next(
                n
                for n in ast.walk(tree)
                if isinstance(n, ast.Assign)
                and any(
                    isinstance(t, ast.Attribute) and t.attr == "argv" for t in n.targets
                )
            )
            capsule_sha = ast.literal_eval(assignment.value)[1]
            report = (
                self.observed
                if self.grant["purpose"] == "inspect"
                else {
                    "status": "controls-reported-not-installation-acceptance",
                    "run_nonce": self.grant["run_nonce"],
                    "actions_completed": len(self.plan["actions"]),
                    "journal_last_sha256": "a" * 64,
                    "state_directory": control.STATE,
                    "installation_performed": False,
                    "independent_stop_still_required": True,
                }
            )
            result = {
                "format": "mcli1-transfer-result-v1",
                "purpose": self.grant["purpose"],
                "run_nonce": self.grant["run_nonce"],
                "grant_sha256": grant_sha,
                "capsule_sha256": capsule_sha,
                "result": report,
            }
        data = commands.canonical(result)
        return {
            "request_id": request["request_id"],
            "acknowledged_steps": [s["ack"] for s in request["steps"]],
            "data_base64": base64.b64encode(data).decode(),
            "data_sha256": commands.digest(data),
            "worker_exit": 0,
            "job_active_processes": 0,
        }

    def run_controller(self, live_probe=None, stopper=None, sender=None):
        controller = transfer.TransferController(
            self.store,
            live_probe or self.snapshot,
            stopper or self.stop,
            sender or self.sender,
        )
        raw = commands.canonical(self.grant)
        return controller.run(raw, commands.digest(raw), self.files)

    def test_complete_inspection_requires_stop_before_receipt_and_fences_authority(
        self,
    ):
        result = self.run_controller()
        self.assertEqual(result["status"], "transfer-and-stop-reported-not-accepted")
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(len(self.stops), 1)
        self.assertEqual(len(self.native_stop_requests), 1)
        self.assertEqual(
            [r["state"] for r in self.store.db.execute("SELECT state FROM operations")],
            ["received", "received"],
        )
        self.assertEqual(
            self.store.db.execute("SELECT state FROM transfer_attempt").fetchone()[
                "state"
            ],
            "reported-and-stop-reported",
        )

    def test_complete_control_report_stays_controls_only(self):
        lease = self.grant["lease"]
        self.grant, self.files, self.observed, self.identity, self.plan = bound_fixture(
            "controls"
        )
        self.grant["lease"] = lease
        result = self.run_controller()
        self.assertFalse(result["outcome"]["result"]["installation_performed"])
        self.assertEqual(len(self.stops), 1)

    def test_caller_cannot_swap_payload_bytes_after_identity(self):
        original = self.grant["files"]["inspection-spec.json"]["sha256"]

        def sender(*args):
            result = self.sender(*args)
            if len(self.sent) == 1:
                self.files["inspection-spec.json"] = b"changed after approval"
            return result

        self.run_controller(sender=sender)
        script = "\n".join(unpack(step) for step in self.sent[-1]["steps"])
        self.assertIn(original, script)
        self.assertNotIn(commands.digest(b"changed after approval"), script)

    def test_changed_entry_source_after_identity_cannot_be_uploaded(self):
        altered = Path(self.folder.name) / "changed-entry.py"
        altered.write_bytes(b"not the granted program")

        def sender(*args):
            result = self.sender(*args)
            if len(self.sent) == 1:
                entry.__file__ = str(altered)
            return result

        with (
            patch.object(entry, "__file__", entry.__file__),
            self.assertRaisesRegex(serial.Refuse, "entry source"),
        ):
            self.run_controller(sender=sender)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(len(self.stops), 1)

    def test_lost_ack_retains_possible_send_and_stops_without_resend(self):
        self.fail_at = 2
        with self.assertRaises(TimeoutError):
            self.run_controller()
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(len(self.stops), 1)
        self.assertEqual(
            [r["state"] for r in self.store.db.execute("SELECT state FROM operations")],
            ["received", "possible-send"],
        )
        with self.assertRaises(Hold):
            self.run_controller()
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(len(self.stops), 1)

    def test_wrong_guest_identity_prevents_upload_and_still_stops(self):
        self.identity["boot_id"] = "66666666-6666-4666-8666-666666666666"
        with self.assertRaises(Hold):
            self.run_controller()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(len(self.stops), 1)

    def test_changed_host_profile_prevents_gate_and_stops_owned_vm(self):
        self.bad_host = True
        with self.assertRaises(Hold):
            self.run_controller()
        self.assertEqual(self.sent, [])
        self.assertEqual(len(self.stops), 1)

    def test_missing_stop_report_retains_uncertain_upload(self):
        def fail_stop(_):
            raise OSError("synthetic missing stop receipt")

        with self.assertRaisesRegex(Hold, "stop unknown"):
            self.run_controller(stopper=fail_stop)
        self.assertEqual(
            [r["state"] for r in self.store.db.execute("SELECT state FROM operations")],
            ["received", "possible-send"],
        )
        self.assertEqual(
            self.store.db.execute("SELECT state FROM transfer_attempt").fetchone()[
                "state"
            ],
            "stopping",
        )

    def test_poweroff_claim_without_original_stop_ledger_cannot_complete(self):
        def claimed(grant):
            return {
                "vm_uuid": grant["target"]["vm_uuid"],
                "run_nonce": grant["run_nonce"],
                "state": "poweroff",
                "disks": [grant["target"]["disk_uuid"]],
                "nics": ["none"] * 8,
                "shares": [],
                "receipt_sha256": "a" * 64,
                "observed_mono_ns": time.monotonic_ns(),
                "elapsed_ns": 0,
            }

        with self.assertRaisesRegex(Hold, "supervisor stop ledger"):
            self.run_controller(stopper=claimed)
        self.assertEqual(
            self.store.db.execute(
                "SELECT state FROM operations ORDER BY rowid DESC"
            ).fetchone()["state"],
            "possible-send",
        )
        self.assertEqual(self.native_stop_requests, [])

    def test_stale_stop_from_another_attempt_cannot_complete(self):
        def wrong(grant):
            receipt = self.stop(grant)
            receipt["run_nonce"] = "9" * 32
            return receipt

        with self.assertRaisesRegex(Hold, "stop profile"):
            self.run_controller(stopper=wrong)
        self.assertEqual(
            self.store.db.execute(
                "SELECT state FROM operations ORDER BY rowid DESC"
            ).fetchone()["state"],
            "possible-send",
        )

    def test_blocked_collector_cannot_refresh_old_authority(self):
        release = threading.Event()
        calls = []
        self.addCleanup(release.set)

        def collector():
            calls.append(1)
            if len(calls) > 1:
                release.wait(2)
            return self.snapshot()

        def sender(store, raw, sha, generation, cancelled):
            if self.sent:
                transport.persist_intent(store, raw, sha, generation)
                self.assertTrue(cancelled.wait(1))
                raise Hold("revoked after stale sample")
            return self.sender(store, raw, sha, generation, cancelled)

        with patch.object(transfer, "FRESH_NS", 150 * 10**6), self.assertRaises(Hold):
            self.run_controller(live_probe=collector, sender=sender)
        release.set()
        self.assertEqual(len(self.stops), 1)

    def test_store_fence_revokes_inflight_phase_without_deadline_renewal(self):
        original = self.grant["phase_window"].copy()

        def sender(store, raw, sha, generation, cancelled):
            if self.sent:
                transport.persist_intent(store, raw, sha, generation)
                store.fence("synthetic revocation")
                self.assertTrue(cancelled.wait(1))
                raise Hold("revoked")
            return self.sender(store, raw, sha, generation, cancelled)

        with self.assertRaises(Hold):
            self.run_controller(sender=sender)
        self.assertEqual(self.grant["phase_window"], original)
        self.assertEqual(len(self.stops), 1)


@unittest.skipUnless(sys.platform == "linux", "POSIX transfer-body fixture checks")
class NativeTransferBodyTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="mcli1-transfer-test-")
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name)
        self.fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY)
        self.addCleanup(os.close, self.fd)

    def execute(self, code):
        context = {
            "os": os,
            "stat": stat,
            "zlib": zlib,
            "base64": base64,
            "hashlib": hashlib,
            "d": self.fd,
            "u": os.getuid(),
        }
        exec(compile(code, "<fixture-transfer-body>", "exec"), context)  # noqa: S102 - Generated body in an owned temporary directory only.

    def stage(self, raw):
        compressed = zlib.compress(raw, 9)
        for offset in range(0, len(compressed), 64):
            self.execute(
                commands.chunk_body(
                    "data.json", offset, compressed[offset : offset + 64]
                )
            )
        return compressed

    def test_real_chunk_and_decode_bytes_roundtrip_and_duplicate_offset_hold(self):
        raw = bytes(range(256)) * 8
        compressed = self.stage(raw)
        before = (self.path / "data.json.part").read_bytes()
        with self.assertRaises(AssertionError):
            self.execute(commands.chunk_body("data.json", 64, compressed[64:128]))
        self.assertEqual((self.path / "data.json.part").read_bytes(), before)
        self.execute(commands.finish_body("data.json", raw, compressed))
        self.assertEqual((self.path / "data.json").read_bytes(), raw)

    def test_tampered_compression_and_existing_final_file_never_execute_or_overwrite(
        self,
    ):
        raw = b"trusted data"
        compressed = self.stage(raw)
        (self.path / "data.json.part").write_bytes(b"x" * len(compressed))
        with self.assertRaises(AssertionError):
            self.execute(commands.finish_body("data.json", raw, compressed))
        self.assertFalse((self.path / "data.json").exists())
        (self.path / "data.json.part").write_bytes(compressed)
        (self.path / "data.json").write_bytes(b"keep")
        with self.assertRaises(FileExistsError):
            self.execute(commands.finish_body("data.json", raw, compressed))
        self.assertEqual((self.path / "data.json").read_bytes(), b"keep")

    def test_bounded_decode_refuses_expansion_before_creating_final(self):
        raw = b"x" * 100000
        compressed = self.stage(raw)
        with self.assertRaises(AssertionError):
            self.execute(commands.finish_body("data.json", b"x", compressed))
        self.assertFalse((self.path / "data.json").exists())

    def test_isolated_packed_rejection_does_not_expose_error_or_honor_optimize_env(
        self,
    ):
        step = commands.packed_step(
            'raise RuntimeError("private sentinel")', "1" * 32, 0
        )
        result = subprocess.run(
            shlex.split(step["send"]),
            env={**os.environ, "PYTHONOPTIMIZE": "1"},
            capture_output=True,
            timeout=5,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, b"MCLI1_NACK_" + b"1" * 32 + b"_0\n")
        self.assertNotIn(b"private sentinel", result.stderr)

    def test_actual_non_guest_identity_fails_before_any_stage_write(self):
        grant, _, _, _, _ = bound_fixture()
        job = commands.identity_request(grant, transfer.digest(grant))
        result = subprocess.run(
            shlex.split(job["steps"][0]["send"]),
            capture_output=True,
            timeout=7,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"MCLI1_NACK_", result.stdout)
        self.assertNotIn(b"MCLI1_ACK_", result.stdout)


if __name__ == "__main__":
    unittest.main()
