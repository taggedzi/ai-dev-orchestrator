"""Real local file copies/share locks, with synthetic read-only VM inventories."""

import copy
import json
import os
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from research.validation import backup_records as records
from research.validation import boot_preconditions as boot
from research.validation import maintenance_host as host
from research.validation import maintenance_transfer as transfer
from research.validation import stopped_backup as backup
from research.validation.store import Hold
from research.validation.transfer_commands import canonical, digest


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.addCleanup(patch.stopall)
        patch.object(backup, "ROOT", self.root).start()
        self.slot = dict(backup.SLOTS["guard"])
        self.slot["disk_sha256"] = digest(b"synthetic stopped VDI bytes\x00")
        patch.dict(backup.SLOTS, {"guard": self.slot}).start()
        self.folder = self.root / ".local/validation/vms" / self.slot["folder"]
        self.folder.mkdir(parents=True)
        self.paths = backup.source_paths("guard")
        self.paths["disk"].write_bytes(b"synthetic stopped VDI bytes\x00")
        self.paths["configuration"].write_bytes(b"synthetic stopped configuration")
        self.machine = {
            "UUID": self.slot["vm_uuid"],
            "VMState": "poweroff",
            "SATA-ImageUUID-0-0": self.slot["disk_uuid"],
            "CfgFile": str(self.paths["configuration"]),
            "NvramFile": str(self.paths["nvram"]),
            **{f"nic{n}": "none" for n in range(1, 9)},
        }
        self.raw_machine = (
            "\n".join(
                f"{json.dumps(k)}={json.dumps(v)}" for k, v in self.machine.items()
            )
            + "\n"
        ).encode()
        self.raw_medium = (
            "\n".join(
                f"{k}: {v}"
                for k, v in {
                    "UUID": self.slot["disk_uuid"],
                    "Parent UUID": "base",
                    "State": "created",
                    "Type": "normal (base)",
                    "Location": str(self.paths["disk"]),
                }.items()
            )
            + "\n"
        ).encode()
        inventory = self.root / ".local/validation/guard-provision-observe-01"
        inventory.mkdir()
        (inventory / "guard.stdout").write_bytes(self.raw_machine)
        (inventory / "guard-disk.stdout").write_bytes(self.raw_medium)
        self.plan = backup.draft("guard")
        self.probes = 0
        patch.object(backup, "new_root", self.new_root).start()
        self.output = self.root / ".local/validation/backup-01"

    def new_root(self, value):
        value = backup.safe(value)
        self.assertEqual(value.parent, self.root / ".local/validation")
        value.mkdir(exist_ok=False)
        return value

    @staticmethod
    @contextmanager
    def portable_locker(path):
        with path.open("rb") as source:
            yield source

    def probe(self, _):
        self.probes += 1
        return {
            "observed_mono_ns": time.monotonic_ns(),
            "machine": self.raw_machine,
            "medium": self.raw_medium,
            "queries": [],
        }

    def capture(self, probe=None):
        raw = canonical(self.plan)
        locker = backup.locked_source if os.name == "nt" else self.portable_locker
        return backup.capture(
            raw, digest(raw), self.output, probe or self.probe, locker
        )

    def test_absent_nvram_is_explicit_and_copies_are_independent_and_read_back(self):
        result = self.capture()
        self.assertEqual(self.probes, 2)
        self.assertEqual(result["binding"]["nvram"], {"state": "absent"})
        self.assertFalse(result["native_boot_authorized"])
        raw = (self.output / "receipt.json").read_bytes()
        receipt = json.loads(raw)
        self.assertEqual(
            (self.output / "disk.vdi").read_bytes(), self.paths["disk"].read_bytes()
        )
        self.assertTrue(receipt["never_attach"])
        with patch.object(
            backup,
            "locked_source",
            backup.locked_source if os.name == "nt" else self.portable_locker,
        ):
            self.assertEqual(backup.verify_files(raw, digest(raw)), result["binding"])
        for label in ("disk", "configuration"):
            self.assertNotEqual(
                receipt["files"][label]["source_identity"],
                receipt["files"][label]["backup_identity"],
            )
        with self.assertRaises(FileExistsError):
            self.capture()

    def test_existing_nvram_file_is_copied_and_hash_bound(self):
        self.paths["nvram"].write_bytes(b"synthetic firmware bytes")
        self.plan = backup.draft("guard")
        result = self.capture()
        self.assertEqual(
            result["binding"]["nvram"],
            {
                "state": "file",
                "bytes": 24,
                "sha256": digest(b"synthetic firmware bytes"),
            },
        )
        self.assertEqual(
            (self.output / "nvram.bin").read_bytes(), b"synthetic firmware bytes"
        )

    def test_running_or_changed_inventory_refuses_before_output_creation(self):
        self.raw_machine = self.raw_machine.replace(b'"poweroff"', b'"running"')
        with self.assertRaisesRegex(Hold, "inventory changed"):
            self.capture()
        self.assertFalse(self.output.exists())

    def test_wrong_packet_or_source_epoch_refuses_before_native_probe(self):
        raw = canonical(self.plan)
        with self.assertRaisesRegex(Hold, "digest differs"):
            backup.capture(raw, "0" * 64, self.output, self.probe)
        self.plan["sources"]["stopped_backup.py"] = "0" * 64
        with self.assertRaisesRegex(Hold, "source cohort"):
            self.capture()
        self.assertEqual(self.probes, 0)

    def test_changed_disk_bytes_leave_partial_intent_and_no_completed_receipt(self):
        self.paths["disk"].write_bytes(b"changed stopped VDI bytes!!")
        with self.assertRaises(Hold):
            self.capture()
        self.assertTrue((self.output / "intent.json").exists())
        self.assertFalse((self.output / "receipt.json").exists())
        with self.assertRaises(FileExistsError):
            self.capture()

    def test_absent_nvram_appearing_during_second_probe_holds(self):
        def changed(role):
            value = self.probe(role)
            if self.probes == 2:
                self.paths["nvram"].write_bytes(b"unexpected appearance")
            return value

        with self.assertRaisesRegex(Hold, "NVRAM appeared"):
            self.capture(changed)
        self.assertFalse((self.output / "receipt.json").exists())

    def test_partial_destination_and_readback_failure_never_publish_receipt(self):
        original = backup.copy_file

        def failed(source, destination, expected, deadline):
            original(source, destination, expected, deadline)
            raise OSError("test:lost copy acknowledgement")

        with patch.object(backup, "copy_file", failed), self.assertRaises(OSError):
            self.capture()
        self.assertTrue((self.output / "disk.vdi").exists())
        self.assertFalse((self.output / "receipt.json").exists())

    def test_hardlinks_and_source_aliases_cannot_be_accepted(self):
        self.capture()
        raw = (self.output / "receipt.json").read_bytes()
        receipt = json.loads(raw)
        receipt["files"]["disk"]["backup_relative"] = receipt["files"]["disk"][
            "source_relative"
        ]
        changed = canonical(receipt)
        with self.assertRaisesRegex(Hold, "aliases source"):
            backup.verify_files(changed, digest(changed))
        os.link(self.output / "disk.vdi", self.output / "disk-alias.vdi")
        with (
            patch.object(
                backup,
                "locked_source",
                backup.locked_source if os.name == "nt" else self.portable_locker,
            ),
            self.assertRaises(Hold),
        ):
            backup.verify_files(raw, digest(raw))

    def test_absence_cannot_be_replaced_with_an_invented_hash(self):
        for value in (
            {"state": "absent", "sha256": digest(b"")},
            {"state": "absent", "bytes": 0},
            {"state": "file", "bytes": True, "sha256": "a" * 64},
        ):
            with self.subTest(value=value), self.assertRaises(Hold):
                records.nvram_record(value)

    def test_new_receipt_passes_boot_and_transfer_schema_and_pinned_receipt_checks(
        self,
    ):
        import test_maintenance_transfer as fixture

        result = self.capture()
        raw_backup = (self.output / "receipt.json").read_bytes()
        grant, _, *_ = fixture.bound_fixture()
        grant["target"]["disk_uuid"] = self.slot["disk_uuid"]
        grant["backup"] = result["binding"]
        grant["disk_evidence"]["pre_boot_disk_sha256"] = result["binding"][
            "disk_sha256"
        ]
        preboot = canonical(
            {
                "format": "mcli1-preboot-disk-v1",
                "run_nonce": grant["run_nonce"],
                "target_vm_uuid": grant["target"]["vm_uuid"],
                "disk_uuid": self.slot["disk_uuid"],
                "disk_sha256": result["binding"]["disk_sha256"],
                "state": "poweroff",
                "backup_receipt_sha256": digest(raw_backup),
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
        raw = canonical(grant)
        transfer.checked_grant(raw, digest(raw))
        host.receipt_pins(grant, raw_backup, preboot, preservation)
        boot_grant = boot.draft("guard")
        boot_grant.update(
            run_nonce=grant["run_nonce"],
            generation=1,
            target={k: grant["target"][k] for k in boot_grant["target"]},
            backup=grant["backup"],
            disk_evidence=grant["disk_evidence"],
        )
        boot_grant["owner"] = {
            "root": "synthetic",
            "launch_sha256": "a" * 64,
            "ready_sha256": "b" * 64,
            "binding_sha256": "c" * 64,
        }
        boot_grant["caller"] = {"role": "bootstrap", "process": {}}
        boot_grant["approval"] = {k: "test:only" for k in boot_grant["approval"]}
        now, mono = time.time_ns(), time.monotonic_ns()
        boot_grant["window"] = {
            "issued_utc_ns": now,
            "expires_utc_ns": now + 10**9,
            "issued_mono_ns": mono,
            "expires_mono_ns": mono + 10**9,
        }
        raw = canonical(boot_grant)
        boot.checked(raw, digest(raw))
        changed = copy.deepcopy(grant)
        changed["backup"]["nvram"] = {"state": "file", "bytes": 1, "sha256": "d" * 64}
        with self.assertRaises(Hold):
            host.receipt_pins(changed, raw_backup, preboot, preservation)


@unittest.skipUnless(sys.platform == "win32", "Windows backup source share lock")
class NativeLockTests(unittest.TestCase):
    def test_source_handle_denies_write_replace_delete_and_hardlink_alias(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            path = root / "source"
            path.write_bytes(b"protected source")
            replacement = root / "replacement"
            replacement.write_bytes(b"other source")
            with patch.object(backup, "ROOT", root):
                with backup.locked_source(path) as source:
                    with self.assertRaises(OSError):
                        path.write_bytes(b"unexpected write")
                    with self.assertRaises(OSError):
                        path.unlink()
                    with self.assertRaises(OSError):
                        replacement.replace(path)
                    self.assertEqual(source.read(), b"protected source")
                path.write_bytes(b"write succeeds after explicit release")
                os.link(path, root / "alias")
                with (
                    self.assertRaisesRegex(Hold, "identity changed"),
                    backup.locked_source(path),
                ):
                    self.fail("hard-linked source admitted")


if __name__ == "__main__":
    unittest.main()
