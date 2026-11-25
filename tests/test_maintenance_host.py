"""Host adapter conformance and native Windows scratch-process checks; no VM control."""

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from test_maintenance_transfer import bound_fixture

from research.validation import maintenance_host as host
from research.validation import maintenance_transfer as transfer
from research.validation import windows_readonly as native
from research.validation.store import Hold, Store
from research.validation.supervisor import LeaseSupervisor
from research.validation.transfer_commands import canonical, digest


def inventory(grant, state="running"):
    target = grant["target"]
    role = grant["role"]
    folder, file = (
        ("mcli1-validation-01", "installation.vdi")
        if role == "executor"
        else ("mcli1-guard-01", "guard-base.vdi")
    )
    disk_path = host.WORKSPACE / ".local/validation/vms" / folder / file
    fields = {
        "UUID": target["vm_uuid"],
        "hardwareuuid": target["dmi_uuid"],
        "VMState": state,
        "cpus": str(transfer.SLOTS[role][1]),
        "memory": str(transfer.SLOTS[role][2]),
        "storagecontrollername0": "SATA",
        "storagecontrollertype0": "IntelAhci",
        "storagecontrollerportcount0": "4",
        "SATA-0-0": str(disk_path),
        "SATA-ImageUUID-0-0": target["disk_uuid"],
        "SATA-1-0": "emptydrive",
        "SATA-2-0": "none",
        "SATA-3-0": "none",
        **{f"nic{n}": "none" for n in range(1, 9)},
        **{
            k: "off"
            for k in (
                "usb",
                "ehci",
                "xhci",
                "vrde",
                "clipboard_file_transfers",
                "uart2",
                "uart3",
                "uart4",
                "lpt1",
                "lpt2",
            )
        },
        "clipboard": "disabled",
        "draganddrop": "disabled",
        "uart1": "0x03f8,4",
    }
    raw = "\n".join(f"{json.dumps(k)}={json.dumps(v)}" for k, v in fields.items())
    # This one upstream printf does not escape Windows backslashes.
    raw += '\nuartmode1="server,' + transfer.expected_host(grant)["uart_pipe"] + '"\n'
    medium = (
        "\n".join(
            f"{k}: {v}"
            for k, v in {
                "UUID": target["disk_uuid"],
                "Parent UUID": "base",
                "State": "locked write",
                "Type": "normal (base)",
                "Location": disk_path,
                "Storage format": "VDI",
                "Format variant": "dynamic default",
                "Capacity": "32768 MBytes",
                "Encryption": "disabled",
                "In use by VMs": f"fixture (UUID: {target['vm_uuid']})",
            }.items()
        )
        + "\n"
    )
    return raw.encode(), medium.encode()


def receipts(grant):
    backup = canonical(
        {
            "format": "mcli1-independent-backup-v1",
            "target_vm_uuid": grant["target"]["vm_uuid"],
            "source_poweroff": True,
            "independent": True,
            **{k: v for k, v in grant["backup"].items() if k != "receipt_sha256"},
        }
    )
    grant["backup"]["receipt_sha256"] = digest(backup)
    preboot = canonical(
        {
            "format": "mcli1-preboot-disk-v1",
            "run_nonce": grant["run_nonce"],
            "target_vm_uuid": grant["target"]["vm_uuid"],
            "disk_uuid": grant["target"]["disk_uuid"],
            "disk_sha256": grant["disk_evidence"]["pre_boot_disk_sha256"],
            "state": "poweroff",
            "backup_receipt_sha256": digest(backup),
        }
    )
    preservation = canonical(
        {
            "format": "mcli1-source-preservation-v1",
            "run_nonce": grant["run_nonce"],
            "target_vm_uuid": grant["target"]["vm_uuid"],
            "source_disk_uuid": transfer.EXECUTOR_DISK,
            "before_sha256": host.SOURCE_DISK_SHA,
            "after_sha256": host.SOURCE_DISK_SHA,
            "state": "poweroff",
        }
    )
    grant["disk_evidence"].update(
        pre_boot_receipt_sha256=digest(preboot),
        source_preservation_receipt_sha256=digest(preservation),
    )
    return backup, preboot, preservation


class InventoryTests(unittest.TestCase):
    def test_live_display_and_double_equals_client_count_are_diagnostic_data(self):
        grant, *_ = bound_fixture()
        raw, _ = inventory(grant)
        runtime = b'SessionName="headless"\nVideoMode="0,0,0"@0,0 1\nVRDEActiveConnection="off"\nVRDEClients==0\n'
        fields = host.machine_fields(raw + runtime)
        self.assertEqual(fields["VideoMode"], '"0,0,0"@0,0 1')
        self.assertEqual(fields["VRDEClients"], "0")
        self.assertEqual(
            host.machine_profile(raw + runtime), transfer.expected_host(grant)
        )
        self.assertEqual(
            host.machine_fields(b'VideoMode="1920,1080,32"@-1920,-1080 1\n')[
                "VideoMode"
            ],
            '"1920,1080,32"@-1920,-1080 1',
        )

    def test_live_diagnostic_exceptions_require_the_exact_bounded_grammar(self):
        for raw in (
            b'VideoMode="0,0,0"\n',
            b'VideoMode="0,0,0"@0,0 1 trailing\n',
            b'VideoMode="0,0,0"@0,$(cmd) 1\n',
            b'VideoMode="4294967296,0,0"@0,0 1\n',
            b'VideoMode="0,0,0"@-2147483649,0 1\n',
            b'VideoMode="0,0,0"@0,0 2147483648\n',
            b"VRDEClients===0\n",
            b"VRDEClients==4294967296\n",
            b"VRDEClients==$(cmd)\n",
            b"memory==1024\n",
        ):
            with self.subTest(raw=raw), self.assertRaises(Hold):
                host.machine_fields(raw)

    def test_live_diagnostics_cannot_hide_duplicate_or_changed_transport_fields(self):
        for raw in (
            b'VRDEClients==0\n"VRDEClients"=0\n',
            b'VideoMode="0,0,0"@0,0 1\n"VideoMode"="0,0,0"@0,0 1\n',
        ):
            with self.subTest(raw=raw), self.assertRaisesRegex(Hold, "duplicate"):
                host.machine_fields(raw)
        grant, *_ = bound_fixture()
        raw, _ = inventory(grant)
        runtime = b'VideoMode="0,0,0"@0,0 1\nVRDEClients==0\n'
        for old, new in (
            (b'"vrde"="off"', b'"vrde"="on"'),
            (b'"nic1"="none"', b'"nic1"="nat"'),
        ):
            with self.subTest(new=new), self.assertRaises(Hold):
                host.machine_profile(raw.replace(old, new) + runtime)

    def test_both_roles_and_raw_uart_backslashes_match_the_frozen_profile(self):
        for role in ("guard", "executor"):
            grant, *_ = bound_fixture(role=role)
            raw, medium = inventory(grant)
            self.assertEqual(host.machine_profile(raw), transfer.expected_host(grant))
            host.check_medium(medium, raw, grant)

    def test_duplicate_malformed_and_shell_text_are_data_or_refusals(self):
        grant, *_ = bound_fixture()
        raw, _ = inventory(grant)
        for extra in (b'UUID="other"\n', b"bad-line\n", b"key=$(cmd)\n"):
            with self.assertRaises((Hold, ValueError)):
                host.machine_fields(raw + extra)
        with self.assertRaisesRegex(Hold, "duplicate"):
            host.object_bytes(b'{"x":1,"x":2}')

    def test_extra_controllers_media_nics_shares_and_transports_cannot_disappear(self):
        grant, *_ = bound_fixture()
        raw, _ = inventory(grant)
        extras = [
            b'storagecontrollername1="IDE"\n',
            b'"IDE-ImageUUID-0-0"="extra"\n',
            b'"SATA-ImageUUID-1-0"="extra"\n',
            b'nic9="none"\n',
            b'SharedFolderNameMachineMapping1="host"\n',
            b'SharedFolderPathTransientMapping1="C:\\\\host"\n',
            b'SharedFolderNameGlobalMapping1="global"\n',
        ]
        for extra in extras:
            with self.subTest(extra=extra), self.assertRaises(Hold):
                host.machine_profile(raw + extra)
        for old, new in (
            (b'"usb"="off"', b'"usb"="on"'),
            (b'"uart2"="off"', b'"uart2"="0x02f8,3"'),
            (b'"SATA-1-0"="emptydrive"', b'"SATA-1-0"="hostdrive"'),
        ):
            with self.assertRaises(Hold):
                host.machine_profile(raw.replace(old, new))

    def test_medium_path_parent_backup_and_cross_attempt_receipt_changes_hold(self):
        grant, *_ = bound_fixture()
        raw, medium = inventory(grant)
        for changed in (
            medium.replace(b"base", b"other"),
            medium.replace(b"guard-base.vdi", b"foreign.vdi"),
            medium + b"UUID: duplicate\n",
        ):
            with self.assertRaises(Hold):
                host.check_medium(changed, raw, grant)
        backup, preboot, preservation = receipts(grant)
        host.receipt_pins(grant, backup, preboot, preservation)
        altered = json.loads(preboot)
        altered["run_nonce"] = "9" * 32
        changed = canonical(altered)
        grant["disk_evidence"]["pre_boot_receipt_sha256"] = digest(changed)
        with self.assertRaisesRegex(Hold, "preboot"):
            host.receipt_pins(grant, backup, changed, preservation)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.db = self.folder / "store.sqlite"
        self.store = Store(self.db)
        self.addCleanup(self.store.close)
        self.grant, self.files, *_ = bound_fixture()
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
        self.process = {
            "pid": 424242,
            "created_filetime": 123,
            "image": r"C:\fixture\python.exe",
        }
        with patch.object(host.os, "getpid", return_value=self.process["pid"]):
            self.owner = host.RegisteredOwner(
                self.supervisor, lease["owner_nonce"], lambda _: dict(self.process)
            )
        self.owner_raw = self.owner.binding
        self.receipts = receipts(self.grant)
        self.state = "running"
        self.queries = []
        self.fail_query = False
        self.adapter = self.make_adapter()

    def make_adapter(self, **changes):
        raw = canonical(self.grant)
        args = {
            "database": self.db,
            "grant_raw": raw,
            "grant_sha": digest(raw),
            "owner_raw": self.owner_raw,
            "owner_sha": digest(self.owner_raw),
            "backup_raw": self.receipts[0],
            "preboot_raw": self.receipts[1],
            "preservation_raw": self.receipts[2],
            "queries": self.query,
            "evidence_root": self.folder / "evidence",
            "identity": lambda _: dict(self.process),
        }
        args.update(changes)
        return host.HostAdapters(**args)

    def query(self, kind, target, wall, mono):
        native.live(wall, mono)
        self.queries.append((kind, target))
        if self.fail_query:
            raise Hold("synthetic query interruption")
        raw, medium = inventory(self.grant, self.state)
        data = (
            native.VERSION.encode() + b"\n"
            if kind == "version"
            else raw
            if kind == "machine"
            else medium
        )
        return {
            "stdout": data,
            "stderr": b"",
            "exit": 0,
            "pid": 111,
            "job_active_processes": 0,
            "started_mono_ns": time.monotonic_ns(),
            "finished_mono_ns": time.monotonic_ns(),
        }

    def stopping(self):
        self.store.db.execute("CREATE TABLE transfer_attempt (nonce TEXT, state TEXT)")
        self.store.db.execute(
            "INSERT INTO transfer_attempt VALUES(?,'stopping')",
            (self.grant["run_nonce"],),
        )
        self.store.fence("synthetic controller finished")

    def test_live_probe_preserves_original_clocks_and_raw_queries_without_mutation(
        self,
    ):
        snapshot = self.adapter.live_probe()
        self.assertEqual(snapshot["host"], transfer.expected_host(self.grant))
        self.assertLessEqual(snapshot["observed_mono_ns"], time.monotonic_ns())
        self.assertEqual(
            snapshot["supervisor"]["expires_mono_ns"],
            self.grant["lease"]["expires_mono_ns"],
        )
        self.assertEqual(
            [q[0] for q in self.queries], ["version", "machine", "disk", "machine"]
        )
        self.assertEqual(len(list(self.adapter.root.glob("*stdout"))), 4)

    def test_reused_pid_stale_pulse_or_changed_lease_prevent_native_queries(self):
        initial = dict(self.process)
        self.process["created_filetime"] += 1
        with self.assertRaisesRegex(Hold, "PID"):
            self.adapter.live_probe()
        self.process = initial
        self.store.db.execute("UPDATE maintenance_owner SET observed_mono_ns=0")
        with self.assertRaises(Hold):
            self.adapter.live_probe()
        self.store.db.execute(
            "UPDATE maintenance_owner SET observed_mono_ns=?", (time.monotonic_ns(),)
        )
        self.store.db.execute("UPDATE lease SET expires_mono_ns=expires_mono_ns+1")
        with self.assertRaisesRegex(Hold, "immutable"):
            self.adapter.live_probe()
        self.assertEqual(self.queries, [])

    def test_owner_registration_and_stop_are_one_shot_without_takeover(self):
        with (
            patch.object(host.os, "getpid", return_value=self.process["pid"]),
            self.assertRaisesRegex(Hold, "already registered"),
        ):
            host.RegisteredOwner(
                self.supervisor, "3" * 32, lambda _: dict(self.process)
            )
        self.assertFalse(self.owner.poll(stopper=lambda *_: self.fail("early stop")))
        self.stopping()
        calls = []
        self.assertTrue(self.owner.poll(stopper=lambda *_: calls.append("stop")))
        with self.assertRaisesRegex(Hold, "terminated"):
            self.owner.poll(stopper=lambda *_: calls.append("duplicate"))
        self.assertEqual(calls, ["stop"])

    def test_changed_owner_profile_refuses_foreign_stop_and_replay(self):
        self.supervisor.profile["target_vm_uuid"] = "foreign"
        with self.assertRaisesRegex(Hold, "profile"):
            self.owner.poll(stopper=lambda *_: self.fail("foreign stop"))
        with self.assertRaisesRegex(Hold, "terminated"):
            self.owner.poll(stopper=lambda *_: self.fail("retry"))

    def test_uncertain_original_stop_stays_stopping_and_cannot_be_reissued(self):
        self.stopping()
        calls = []

        def lost_ack(*_):
            calls.append("possible-send")
            raise Hold("original stop acknowledgement lost")

        with self.assertRaisesRegex(Hold, "acknowledgement lost"):
            self.owner.poll(stopper=lost_ack)
        with self.assertRaisesRegex(Hold, "terminated"):
            self.owner.poll(stopper=lost_ack)
        self.assertEqual(calls, ["possible-send"])
        self.assertEqual(
            self.store.db.execute("SELECT state FROM lease").fetchone()[0], "stopping"
        )

    def test_stop_before_controller_fence_holds_without_queries(self):
        self.store.db.execute("CREATE TABLE transfer_attempt (nonce TEXT, state TEXT)")
        self.store.db.execute(
            "INSERT INTO transfer_attempt VALUES(?,'stopping')",
            (self.grant["run_nonce"],),
        )
        with self.assertRaisesRegex(Hold, "fence/stop intent"):
            self.adapter.stop(self.grant)
        self.assertEqual(self.queries, [])

    def test_standalone_stop_cannot_use_a_different_phase_grant(self):
        self.stopping()
        altered = json.loads(canonical(self.grant))
        altered["purpose"] = "controls"
        with self.assertRaisesRegex(Hold, "outside a session"):
            self.adapter.stop(altered)
        self.assertEqual(self.queries, [])

    def test_stop_acknowledgement_waits_for_poweroff_without_repeating_stop(self):
        self.stopping()
        calls = []
        self.owner.poll(stopper=lambda *_: calls.append("one original stop"))
        original, machines = self.adapter.queries, []

        def delayed_off(kind, target, wall, mono):
            result = original(kind, target, wall, mono)
            if kind == "machine":
                machines.append(kind)
                if len(machines) == 2:
                    self.state = "poweroff"
            return result

        self.adapter.queries = delayed_off
        result = self.adapter.stop(self.grant)
        self.assertEqual(result["state"], "poweroff")
        self.assertEqual(calls, ["one original stop"])
        self.assertEqual(len(machines), 4)

    def test_changed_authority_after_poweroff_observation_prevents_stop_receipt(self):
        self.stopping()
        self.owner.poll(stopper=lambda *_: None)
        self.state = "poweroff"
        original = self.adapter.queries

        def changed_fence(kind, target, wall, mono):
            result = original(kind, target, wall, mono)
            if len(self.queries) == 4:
                self.store.fence("changed during stop observation")
            return result

        self.adapter.queries = changed_fence
        with self.assertRaisesRegex(Hold, "changed during independent"):
            self.adapter.stop(self.grant)

    def test_same_process_owner_binding_cannot_admit_a_live_adapter(self):
        binding = json.loads(self.owner_raw)
        binding["process"]["pid"] = os.getpid()
        raw = canonical(binding)
        with self.assertRaisesRegex(Hold, "separate original owner"):
            self.make_adapter(
                owner_raw=raw,
                owner_sha=digest(raw),
                evidence_root=self.folder / "same-process",
            )

    def test_stop_adapter_waits_for_original_owner_and_then_measures_poweroff(self):
        self.stopping()
        original = []

        def owner_poll():
            time.sleep(0.02)
            self.owner.poll(stopper=lambda *_: original.append("original"))
            self.state = "poweroff"

        thread = threading.Thread(target=owner_poll)
        thread.start()
        try:
            receipt = self.adapter.stop(self.grant)
        finally:
            thread.join(timeout=1)
        self.assertEqual(original, ["original"])
        self.assertEqual(receipt["state"], "poweroff")
        transfer.stop_report(
            self.grant, receipt, receipt["observed_mono_ns"] - receipt["elapsed_ns"]
        )
        with self.assertRaises(FileExistsError):
            self.adapter.stop(self.grant)
        self.assertEqual(original, ["original"])

    def test_poweroff_ledger_claim_without_original_owner_cannot_query(self):
        self.stopping()
        self.store.db.execute("UPDATE lease SET state='stop-command-returned'")
        with self.assertRaisesRegex(Hold, "ledger"):
            self.adapter.stop(self.grant)
        self.assertEqual(self.queries, [])

    def test_interrupted_and_overlapping_capture_retains_intent_and_cannot_reuse_root(
        self,
    ):
        self.fail_query = True
        with self.assertRaisesRegex(Hold, "interruption"):
            self.adapter.live_probe()
        self.assertTrue((self.adapter.root / "capture-000.intent.json").exists())
        self.assertEqual(self.adapter.index, 1)
        self.adapter.capture_lock.acquire()
        try:
            with self.assertRaisesRegex(Hold, "still active"):
                self.adapter._capture(
                    time.time_ns() + 10**9, time.monotonic_ns() + 10**9, "running"
                )
        finally:
            self.adapter.capture_lock.release()
        with self.assertRaises(FileExistsError):
            self.make_adapter()

    def test_controller_uses_the_adapters_and_only_original_owner_stops(self):
        stopped = []
        exit_owner = threading.Event()

        def watch_owner():
            while not exit_owner.is_set():
                if self.owner.poll(stopper=lambda *_: stopped.append("owner")):
                    self.state = "poweroff"
                    break
                exit_owner.wait(0.005)

        owner_thread = threading.Thread(target=watch_owner)
        owner_thread.start()

        def fail_delivery(*_):
            raise Hold("synthetic transport loss")

        controller = transfer.TransferController(
            self.store, self.adapter.live_probe, self.adapter.stop, fail_delivery
        )
        raw = canonical(self.grant)
        try:
            with self.assertRaisesRegex(Hold, "synthetic transport loss"):
                controller.run(raw, digest(raw), self.files)
        finally:
            exit_owner.set()
            owner_thread.join(timeout=1)
        self.assertEqual(stopped, ["owner"])
        self.assertEqual(
            self.store.db.execute("SELECT state FROM transfer_attempt").fetchone()[0],
            "held-stop-reported",
        )


class QueryPolicyTests(unittest.TestCase):
    def test_public_query_policy_cannot_launch_mutations_paths_or_changed_tool_bytes(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "VBoxManage.exe"
            executable.write_bytes(b"synthetic reviewed bytes")
            target = "11111111-1111-4111-8111-111111111111"
            calls = []

            def runner(exe, args, *_):
                calls.append(args)
                return {
                    "exit": 0,
                    "stderr": b"",
                    "stdout": native.VERSION.encode(),
                    "job_active_processes": 0,
                }

            query = native.VBoxQueries(
                digest(executable.read_bytes()), [target], runner
            )
            wall, mono = time.time_ns() + 10**9, time.monotonic_ns() + 10**9
            with (
                patch.object(native, "VBOX", executable),
                patch.dict(os.environ, {"VBOX_USER_HOME": ""}),
            ):
                query("version", None, wall, mono)
                for kind, value in (
                    ("poweroff", target),
                    ("machine", "../../vm"),
                    ("version", target),
                ):
                    with self.assertRaises(Hold):
                        query(kind, value, wall, mono)
                executable.write_bytes(b"changed")
                with self.assertRaisesRegex(Hold, "bytes"):
                    query("machine", target, wall, mono)
            self.assertEqual(calls, [["--version"]])


@unittest.skipUnless(
    sys.platform == "win32", "Windows Job Object/process identity checks"
)
class WindowsQueryTests(unittest.TestCase):
    def run_child(self, source, seconds=2, hook=None):
        return native._run(
            sys.executable,
            ["-I", "-B", "-c", source],
            time.time_ns() + int(seconds * 10**9),
            time.monotonic_ns() + int(seconds * 10**9),
            hook,
        )

    def test_actual_job_membership_precedes_execution_and_output_is_reaped(self):
        seen = []
        r = self.run_child(
            'print("scratch-query")',
            hook=lambda pid: seen.append(host.process_identity(pid)),
        )
        self.assertEqual(r["stdout"].strip(), b"scratch-query")
        self.assertEqual(r["job_active_processes"], 0)
        self.assertEqual(r["exit"], 0)
        self.assertEqual(seen[0]["pid"], r["pid"])

    def test_failed_pre_resume_gate_cannot_execute_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "must-not-exist"

            def deny(_):
                raise Hold("test gate closed")

            with self.assertRaisesRegex(Hold, "gate closed"):
                self.run_child(
                    f'from pathlib import Path;Path({str(path)!r}).write_text("wrong")',
                    hook=deny,
                )
            self.assertFalse(path.exists())

    def test_timeout_flood_and_forbidden_descendant_cannot_leave_a_query_child(self):
        started = time.monotonic()
        for source in (
            "import time;time.sleep(30)",
            'import os;os.write(1,b"x"*200000);import time;time.sleep(30)',
        ):
            with self.assertRaises(Hold):
                self.run_child(source, seconds=0.15)
        self.assertLess(time.monotonic() - started, 3)
        r = self.run_child(
            'import subprocess,sys;subprocess.run([sys.executable,"-c","pass"])'
        )
        self.assertNotEqual(r["exit"], 0)
        self.assertIn(b"OSError", r["stderr"])

    def test_original_process_creation_identity_changes_after_exit(self):
        current = host.process_identity(os.getpid())
        self.assertEqual(current["pid"], os.getpid())
        self.assertGreater(current["created_filetime"], 0)
        r = self.run_child("pass")
        with self.assertRaises(Hold):
            host.process_identity(r["pid"])

    def test_parent_death_reaps_child_even_before_its_primary_thread_resumes(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "child.json"
            sentinel = Path(tmp) / "must-not-exist"
            child_source = (
                f'from pathlib import Path;Path({str(sentinel)!r}).write_text("wrong")'
            )
            source = f"""import sys,time,json
from pathlib import Path
sys.path.insert(0,{str(Path.cwd())!r})
from research.validation.windows_readonly import _run
from research.validation.maintenance_host import process_identity
def hold(pid):
    Path({str(marker)!r}).write_text(json.dumps(process_identity(pid)))
    time.sleep(30)
_run(sys.executable,['-I','-B','-c',{child_source!r}],time.time_ns()+3_000_000_000,time.monotonic_ns()+3_000_000_000,hold)
"""
            parent = subprocess.Popen(
                [sys.executable, "-I", "-B", "-c", source],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            try:
                deadline = time.monotonic() + 3
                while (
                    not marker.exists()
                    and parent.poll() is None
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.01)
                self.assertTrue(
                    marker.exists(),
                    "scratch query parent did not publish the suspended child",
                )
                child = json.loads(marker.read_text())
                parent.kill()
                parent.wait(timeout=1)
                deadline = time.monotonic() + 1
                live_child = True
                while time.monotonic() < deadline:
                    try:
                        live_child = host.process_identity(child["pid"]) == child
                    except Hold:
                        live_child = False
                    if not live_child:
                        break
                    time.sleep(0.01)
                self.assertFalse(live_child)
                self.assertFalse(sentinel.exists())
            finally:
                if parent.poll() is None:
                    parent.kill()
                parent.communicate(timeout=1)


if __name__ == "__main__":
    unittest.main()
