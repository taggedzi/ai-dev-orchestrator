import copy
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from research.validation.guard_packages import WORKSPACE
from research.validation.maintenance_config import PROPOSAL, proposal, settings
from research.validation.maintenance_runner import (
    ISO_SHA256,
    LOCAL,
    MEDIA_SHA256,
    STATUS_SHA256,
    MaintenanceAdmission,
    digest,
    draft,
    missing,
)
from research.validation.store import Hold, Store
from research.validation.supervisor import LeaseSupervisor


class MaintenanceRunnerTests(unittest.TestCase):
    def setUp(self):
        LOCAL.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(
            prefix="maintenance-test-", dir=LOCAL
        )
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.now, self.mono = 1000 * 10**9, 2000 * 10**9
        self.planned = proposal(PROPOSAL.read_bytes())
        catalog = json.loads(
            (WORKSPACE / "research/validation/os-update-inputs.json").read_bytes()
        )
        baseline = {
            r["name"]: r["old_version"]
            for r in catalog["archives"]
            if r["old_version"] is not None
        }
        for i in range(480 - len(baseline)):
            baseline[f"baseline-filler-{i}"] = "1"
        self.policy = {
            "proposal": self.planned,
            "settings": settings(self.planned),
            "baseline": baseline,
        }
        patched = patch(
            "research.validation.maintenance_runner.load_policy",
            return_value=self.policy,
        )
        patched.start()
        self.addCleanup(patched.stop)
        self.path = self.root / "maintenance.sqlite"
        self.store = Store(self.path)
        self.addCleanup(self.store.close)
        self.packet = draft("guard", self.path.relative_to(WORKSPACE).as_posix())
        target = self.packet["target"]
        for key in ("disk_uuid", "dmi_uuid", "root_fs_uuid", "boot_id", "dvd_uuid"):
            target[key] = {
                "disk_uuid": "11111111-1111-4111-8111-111111111111",
                "dmi_uuid": "22222222-2222-4222-8222-222222222222",
                "root_fs_uuid": "33333333-3333-4333-8333-333333333333",
                "boot_id": "44444444-4444-4444-8444-444444444444",
                "dvd_uuid": "55555555-5555-4555-8555-555555555555",
            }[key]
        target.update(
            pre_boot_disk_sha256="a" * 64,
            pre_boot_receipt_sha256="b" * 64,
            media_device="/dev/sr0",
        )
        self.packet.update(run_nonce="1" * 32, generation=1)
        self.packet["inputs"].update(
            guest_preflight_program_sha256="c" * 64,
            source_preservation_receipt_sha256="d" * 64,
        )
        self.packet["approval"] = {
            k: "synthetic-test-approval" for k in self.packet["approval"]
        }
        self.packet["backup"] = {
            "source_disk_uuid": target["disk_uuid"],
            "disk_uuid": "66666666-6666-4666-8666-666666666666",
            "disk_sha256": "e" * 64,
            "configuration_sha256": "f" * 64,
            "nvram_sha256": "a" * 64,
            "receipt_sha256": "b" * 64,
        }
        self.packet["lease"] = {
            "owner_nonce": "2" * 32,
            "expires_utc_ns": self.now + 600 * 10**9,
            "expires_mono_ns": self.mono + 600 * 10**9,
        }
        LeaseSupervisor(
            self.store,
            {
                "target_vm_uuid": target["vm_uuid"],
                "lease_expires_utc_ns": self.packet["lease"]["expires_utc_ns"],
            },
            now_ns=self.now,
            monotonic_ns=self.mono,
        )
        self.probes = 0
        self.gate = self.gate_for(self.store)
        machine = {
            "UUID": target["vm_uuid"],
            "VMState": "running",
            "cpus": "1",
            "memory": "1024",
            "SATA-ImageUUID-0-0": target["disk_uuid"],
            **{f"nic{i}": "none" for i in range(1, 9)},
        }
        expected = self.policy["settings"]
        dumped = (
            "\n".join(
                f'{k} "{v}";' for k, v in expected.items() if k != "Acquire::Languages"
            )
            + '\nAcquire::Languages "";\nAcquire::Languages:: "none";\nAPT::Architectures:: "amd64";'
        )
        self.observed = {
            "run_nonce": self.packet["run_nonce"],
            "observed_mono_ns": self.mono,
            "host": {
                "machine": machine,
                "hard_disk_uuids": [target["disk_uuid"]],
                "dvd_uuid": target["dvd_uuid"],
                "iso_sha256": ISO_SHA256,
                "pre_boot_disk_sha256": target["pre_boot_disk_sha256"],
                "pre_boot_receipt_sha256": target["pre_boot_receipt_sha256"],
                "backup_receipt_sha256": self.packet["backup"]["receipt_sha256"],
                "source_preservation_receipt_sha256": self.packet["inputs"][
                    "source_preservation_receipt_sha256"
                ],
            },
            "guest": {
                "platform": "linux",
                "uid": 0,
                "kernel_release": "6.8.0-test",
                "dmi_uuid": target["dmi_uuid"],
                "root_fs_uuid": target["root_fs_uuid"],
                "boot_id": target["boot_id"],
                "root_fs_type": "ext4",
                "interfaces": ["lo"],
                "media_mount": {
                    "target": "/media/mcli1-maintenance",
                    "source": "/dev/sr0",
                    "fstype": "iso9660",
                    "options": ["ro", "nosuid", "nodev", "noexec"],
                },
                "media_manifest_sha256": MEDIA_SHA256,
                "verified_media_files": 142,
                "status_sha256": STATUS_SHA256,
                "audit_stdout": "",
                "audit_stderr": "",
                "preflight_program_sha256": self.packet["inputs"][
                    "guest_preflight_program_sha256"
                ],
                "apt_dump": dumped,
                "maintenance_unit_exists": False,
                "log_directory": {
                    "path": "/var/log/mcli1-maintenance",
                    "uid": 0,
                    "mode": 0o700,
                    "symlink": False,
                },
                "root_free_bytes": 5 * 1024**3,
                "boot_free_bytes": 1024**3,
                "efi_free_bytes": 128 * 1024**2,
                **self.control_facts(),
            },
        }

    def control_facts(self):
        return {
            "masks": {
                name: {
                    "target": "/dev/null",
                    "uid": 0,
                    "active": "inactive",
                    "helper_mask_state": False,
                }
                for name in self.planned["common_admin_masks_proposal"]
                + self.planned["roles"]["guard"]["additional_admin_masks"]
            },
            "policy": {
                "sha256": self.planned["policy_rc_d_proposal"]["sha256"],
                "uid": 0,
                "mode": 0o755,
            },
            "active_package_processes": [],
            "snap_apps": [],
            "docker_socket_present": False,
            "protected_runtime_processes": [],
            "operator_in_docker_group": False,
        }

    def pulse(self):
        self.probes += 1
        return {
            "target_vm_uuid": self.packet["target"]["vm_uuid"],
            "owner_nonce": self.packet["lease"]["owner_nonce"],
            "live": True,
            "observed_mono_ns": self.mono,
            "expires_utc_ns": self.packet["lease"]["expires_utc_ns"],
            "expires_mono_ns": self.packet["lease"]["expires_mono_ns"],
        }

    def gate_for(self, store):
        return MaintenanceAdmission(
            store, self.pulse, wall_ns=lambda: self.now, mono_ns=lambda: self.mono
        )

    def admit(self, packet=None, observed=None):
        packet = self.packet if packet is None else packet
        return self.gate.admit(
            packet, digest(packet), self.observed if observed is None else observed
        )

    def result(self):
        finished = self.mono
        self.now += 10**9
        self.mono += 10**9
        versions = dict(self.policy["baseline"])
        for pin in self.planned["roles"]["guard"]["pins"]:
            name, version = pin.split("=", 1)
            versions[name] = version
        self.assertEqual(len(versions), 489)
        return {
            "vm_uuid": self.packet["target"]["vm_uuid"],
            "run_nonce": self.packet["run_nonce"],
            "boot_id": self.packet["target"]["boot_id"],
            "unit_exit": 0,
            "audit_stdout": "",
            "audit_stderr": "",
            "unconfigured_packages": [],
            "installed_versions": versions,
            "installed_status_sha256": "c" * 64,
            "observed_mono_ns": self.mono,
            "unit_finished_host_mono_ns": finished,
            "independent_stop": {
                "vm_uuid": self.packet["target"]["vm_uuid"],
                "state": "poweroff",
                "receipt_sha256": "d" * 64,
                "observed_mono_ns": self.mono,
                "elapsed_ns": 10**9,
                "nics": ["none"] * 8,
                "shared_folders": [],
                "hard_disk_uuids": [self.packet["target"]["disk_uuid"]],
                "dvd_uuid": self.packet["target"]["dvd_uuid"],
            },
            **self.control_facts(),
        }

    def test_draft_has_no_authority_and_cannot_probe_or_dispatch(self):
        packet = draft("guard", self.packet["journal_path"])
        self.assertIn("inputs.guest_preflight_program_sha256", missing(packet))
        with self.assertRaises(Hold):
            self.admit(packet)
        self.assertEqual(self.probes, 0)
        self.assertFalse((self.root / "dispatch.intent.json").exists())

    def test_valid_admission_persists_before_any_external_send_and_never_replays(self):
        result = self.admit()
        self.assertEqual(result["state"], "possible-send")
        self.assertFalse(result["native_dispatch_performed"])
        self.assertTrue((self.root / "dispatch.intent.json").is_file())
        second = Store(self.path)
        self.addCleanup(second.close)
        self.assertEqual(
            second.db.execute("SELECT state FROM operations").fetchone()["state"],
            "possible-send",
        )
        packet = copy.deepcopy(self.packet)
        packet["run_nonce"] = "3" * 32
        observed = copy.deepcopy(self.observed)
        observed["run_nonce"] = packet["run_nonce"]
        with self.assertRaises(Hold):
            self.gate_for(second).admit(packet, digest(packet), observed)

    def test_deleted_database_rows_do_not_erase_the_one_use_marker(self):
        self.admit()
        with self.store.transaction():
            self.store.db.execute("DELETE FROM operations")
            self.store.db.execute("DELETE FROM maintenance_dispatch")
        with self.assertRaisesRegex(Hold, "marker"):
            self.admit()

    def test_target_media_mount_and_backup_mismatches_hold_before_intent(self):
        mutations = [
            ("host", "iso_sha256", "0" * 64),
            ("host", "hard_disk_uuids", []),
            ("host", "backup_receipt_sha256", "0" * 64),
            ("guest", "kernel_release", "6.1-microsoft-WSL2"),
            ("guest", "uid", 1000),
            ("guest", "interfaces", ["lo", "eth0"]),
            ("guest", "status_sha256", "0" * 64),
            ("guest", "root_free_bytes", True),
        ]
        for section, key, value in mutations:
            observed = copy.deepcopy(self.observed)
            observed[section][key] = value
            with self.subTest(key=key), self.assertRaises(Hold):
                self.admit(observed=observed)
        observed = copy.deepcopy(self.observed)
        observed["guest"]["media_mount"]["options"].append("exec")
        with self.assertRaises(Hold):
            self.admit(observed=observed)
        self.assertFalse((self.root / "dispatch.intent.json").exists())

    def test_clock_deadline_and_live_owner_cannot_be_renewed_by_packet(self):
        self.now += 351 * 10**9
        self.mono += 351 * 10**9
        self.observed["observed_mono_ns"] = self.mono
        with self.assertRaisesRegex(Hold, "budget"):
            self.admit()
        packet = copy.deepcopy(self.packet)
        packet["lease"]["expires_utc_ns"] += 100 * 10**9
        with self.assertRaisesRegex(Hold, "deadline"):
            self.admit(packet)
        self.now -= 352 * 10**9
        self.observed["observed_mono_ns"] = self.mono
        with self.assertRaisesRegex(Hold, "clock"):
            self.admit()
        self.assertFalse((self.root / "dispatch.intent.json").exists())

    def test_stale_observation_dead_supervisor_and_memory_journal_hold(self):
        observed = copy.deepcopy(self.observed)
        observed["observed_mono_ns"] -= 6 * 10**9
        with self.assertRaisesRegex(Hold, "stale"):
            self.admit(observed=observed)
        self.gate.live_probe = lambda: {**self.pulse(), "live": False}
        with self.assertRaisesRegex(Hold, "live"):
            self.admit()
        memory = Store(":memory:")
        self.addCleanup(memory.close)
        with self.assertRaisesRegex(Hold, "ephemeral"):
            self.gate_for(memory)

    def test_zero_unit_exit_without_full_postconditions_is_not_acceptance(self):
        self.admit()
        result = self.result()
        result["installed_versions"].pop(next(iter(result["installed_versions"])))
        with self.assertRaises(Hold):
            self.gate.record_result(self.packet, result)
        self.assertEqual(
            self.store.db.execute("SELECT state FROM operations").fetchone()["state"],
            "possible-send",
        )
        self.assertEqual(
            self.store.db.execute("SELECT active FROM authority").fetchone()["active"],
            0,
        )

    def test_independent_stop_is_required_and_full_result_fences_further_authority(
        self,
    ):
        self.admit()
        result = self.result()
        self.gate.record_result(self.packet, result)
        self.assertEqual(
            self.store.db.execute("SELECT state FROM maintenance_dispatch").fetchone()[
                "state"
            ],
            "postconditions-and-stop-reported",
        )
        self.assertEqual(
            self.store.db.execute("SELECT active FROM authority").fetchone()["active"],
            0,
        )
        with self.assertRaises(Hold):
            self.gate.record_result(self.packet, result)

    def test_two_connections_cannot_both_admit_the_same_maintenance(self):
        second = Store(self.path)
        self.addCleanup(second.close)
        other = self.gate_for(second)

        def attempt(gate):
            try:
                gate.admit(self.packet, digest(self.packet), self.observed)
                return True
            except Hold:
                return False

        with ThreadPoolExecutor(max_workers=2) as pool:
            values = list(pool.map(attempt, [self.gate, other]))
        self.assertEqual(sorted(values), [False, True])

    def test_handoff_is_durable_before_callback_and_lost_ack_never_replays(self):
        ticket = self.admit()
        calls = []

        def sender(request):
            calls.append(request)
            self.assertEqual(
                self.store.db.execute(
                    "SELECT state FROM maintenance_dispatch"
                ).fetchone()["state"],
                "transport-entered",
            )
            raise TimeoutError("synthetic lost acknowledgement")

        with self.assertRaises(Hold):
            self.gate.invoke(ticket, sender)
        with self.assertRaises(Hold):
            self.gate.invoke(ticket, sender)
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            self.store.db.execute("SELECT state FROM operations").fetchone()["state"],
            "possible-send",
        )
        self.assertEqual(
            self.store.db.execute("SELECT active FROM authority").fetchone()["active"],
            0,
        )

    def test_stale_ticket_and_changed_command_never_reach_sender(self):
        ticket = self.admit()
        calls = []
        changed = copy.deepcopy(ticket)
        changed["argv"].append("--force-yes")
        with self.assertRaises(Hold):
            self.gate.invoke(changed, lambda request: calls.append(request) or b"ack")
        self.now += 6 * 10**9
        self.mono += 6 * 10**9
        with self.assertRaises(Hold):
            self.gate.invoke(ticket, lambda request: calls.append(request) or b"ack")
        self.assertEqual(calls, [])

    def test_transport_ack_alone_keeps_operation_uncertain(self):
        ticket = self.admit()
        self.assertEqual(
            self.gate.invoke(ticket, lambda request: b"synthetic ack"), b"synthetic ack"
        )
        self.assertEqual(
            self.store.db.execute("SELECT state FROM operations").fetchone()["state"],
            "possible-send",
        )
        self.assertEqual(
            self.store.db.execute("SELECT state FROM maintenance_dispatch").fetchone()[
                "state"
            ],
            "transport-returned",
        )
        self.gate.record_result(self.packet, self.result())
        self.assertEqual(
            self.store.db.execute("SELECT state FROM operations").fetchone()["state"],
            "received",
        )

    def test_missing_independent_stop_and_late_completion_cannot_complete(self):
        self.admit()
        result = self.result()
        result["independent_stop"]["state"] = "running"
        with self.assertRaises(Hold):
            self.gate.record_result(self.packet, result)
        self.assertEqual(
            self.store.db.execute("SELECT state FROM operations").fetchone()["state"],
            "possible-send",
        )
        late = self.result()
        late["unit_finished_host_mono_ns"] = self.packet["lease"]["expires_mono_ns"] + 1
        with self.assertRaises(Hold):
            self.gate.record_result(self.packet, late)
