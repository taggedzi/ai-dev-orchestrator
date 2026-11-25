"""Stopped profile admission/failure paths; every native mutation is simulated."""

import copy
import json
import os
import unittest
from unittest.mock import patch

import test_maintenance_host as host_fixture
import test_maintenance_transfer as transfer_fixture
import test_stopped_backup as backup_fixture

from research.validation import boot_preconditions as boot
from research.validation import maintenance_profile as profile
from research.validation import stopped_backup as backup
from research.validation.store import Hold
from research.validation.transfer_commands import canonical, digest


class ProfileTests(unittest.TestCase):
    new_root = backup_fixture.BackupTests.new_root
    portable_locker = backup_fixture.BackupTests.portable_locker
    probe = backup_fixture.BackupTests.probe

    def setUp(self):
        backup_fixture.BackupTests.setUp(self)
        patch.object(profile, "ROOT", self.root).start()
        patch.object(profile, "new_root", self.new_root).start()
        if os.name != "nt":
            patch.object(backup, "locked_source", self.portable_locker).start()
        grant, *_ = transfer_fixture.bound_fixture()
        grant["target"].update(
            disk_uuid=self.slot["disk_uuid"], dmi_uuid=self.slot["vm_uuid"]
        )
        raw, _ = host_fixture.inventory(grant, "poweroff")
        self.machine = profile.host.machine_fields(raw)
        self.machine.update(boot.BOOT_FIELDS)
        self.machine.update(
            CfgFile=str(self.paths["configuration"]),
            NvramFile=str(self.paths["nvram"]),
            uart1="off",
            storagecontrollerportcount0="1",
        )
        self.machine["SATA-0-0"] = str(self.paths["disk"])
        for k in ("SATA-1-0", "SATA-2-0", "SATA-3-0", "uartmode1"):
            self.machine.pop(k, None)
        self.update_machine()
        inventory = self.root / ".local/validation/guard-provision-observe-01"
        (inventory / "guard.stdout").write_bytes(self.raw_machine)
        self.plan = backup.draft("guard")
        self.output = self.root / ".local/validation/stopped-backup-guard-01"
        backup_fixture.BackupTests.capture(self)
        self.plan = profile.draft("guard")
        self.output = self.root / ".local/validation/profile-01"
        self.probes, self.sent = 0, []

    def update_machine(self):
        # Match the native UART printf's unescaped host-pipe value.
        lines = []
        for k, v in self.machine.items():
            if k == "uartmode1":
                lines.append(k + '="' + v + '"')
            else:
                lines.append(json.dumps(k) + "=" + json.dumps(v))
        self.raw_machine = ("\n".join(lines) + "\n").encode()

    def runner(self, args, gate):
        self.assertTrue(
            (self.root / ".local/validation/profile-intents/guard/intent.json").exists()
        )
        gate(111)
        self.sent.append(list(args))
        if args[0] == "storagectl":
            self.machine["storagecontrollerportcount0"] = "4"
            self.machine.update({f"SATA-{n}-0": "none" for n in range(1, 4)})
        else:
            self.machine.update(uart1="0x03f8,4", uartmode1="server," + args[-1])
        self.update_machine()
        self.paths["configuration"].write_bytes(
            b"changed synthetic configuration " + str(len(self.sent)).encode()
        )
        return {
            "stdout": b"",
            "stderr": b"",
            "exit": 0,
            "job_active_processes": 0,
            "pid": 111,
        }

    def apply(self, approval="test:stopped-only", runner=None):
        raw = canonical(self.plan)
        return profile.apply(
            raw, digest(raw), self.output, approval, self.probe, runner or self.runner
        )

    def test_exact_guard_change_reaches_stopped_four_port_uart_profile_without_boot(
        self,
    ):
        result = self.apply()
        self.assertEqual(self.sent, profile.commands("guard"))
        self.assertFalse(result["VM_started"])
        self.assertFalse(result["native_boot_authorized"])
        self.assertEqual(self.machine["VMState"], "poweroff")
        self.assertEqual(self.machine["storagecontrollerportcount0"], "4")
        self.assertEqual(result["nvram"], {"state": "absent"})
        self.assertEqual(
            digest(self.paths["disk"].read_bytes()), self.plan["disk_sha256"]
        )
        self.assertTrue((self.output / "receipt.json").exists())

    def test_missing_approval_expanded_command_or_source_change_refuses_before_probe(
        self,
    ):
        with self.assertRaisesRegex(Hold, "approval is unbound"):
            self.apply(approval=None)
        old = copy.deepcopy(self.plan)
        self.plan["commands"].append(["startvm", self.slot["vm_uuid"]])
        with self.assertRaisesRegex(Hold, "scope expanded"):
            self.apply()
        self.plan = old
        self.plan["sources"]["maintenance_profile.py"] = "0" * 64
        with self.assertRaisesRegex(Hold, "source cohort"):
            self.apply()
        self.assertEqual(self.probes, 0)
        self.assertFalse(self.sent)

    def test_running_or_changed_initial_configuration_cannot_change_settings(self):
        self.machine["VMState"] = "running"
        self.update_machine()
        with self.assertRaisesRegex(Hold, "stopped base disk"):
            self.apply()
        self.assertFalse(self.sent)
        self.assertFalse(self.output.exists())

    def test_missing_or_tampered_backup_cannot_change_settings(self):
        source = profile.receipt_path("guard")
        source.write_bytes(source.read_bytes() + b" ")
        with self.assertRaisesRegex(Hold, "receipt digest"):
            self.apply()
        self.assertFalse(self.sent)
        self.assertEqual(self.probes, 0)

    def test_lost_command_ack_retains_intent_and_denies_replay_with_a_new_output(self):
        def lost(args, gate):
            self.runner(args, gate)
            raise TimeoutError("test:configuration may have changed")

        with self.assertRaises(TimeoutError):
            self.apply(runner=lost)
        self.assertEqual(len(self.sent), 1)
        self.assertFalse((self.output / "receipt.json").exists())
        self.output = self.root / ".local/validation/profile-retry"
        with self.assertRaisesRegex(Hold, "intent exists"):
            self.apply()
        self.assertEqual(len(self.sent), 1)

    def test_nonzero_exit_does_not_execute_the_next_command_or_publish_success(self):
        def failed(args, gate):
            return {**self.runner(args, gate), "exit": 1}

        with self.assertRaisesRegex(Hold, "failed or remains uncertain"):
            self.apply(runner=failed)
        self.assertEqual(len(self.sent), 1)
        self.assertFalse((self.output / "receipt.json").exists())

    def test_changed_command_intent_is_seen_before_resume(self):
        def changed(args, gate):
            (self.output / "step-0.intent.json").write_bytes(b"changed")
            gate(111)
            self.fail("changed command intent reached native execution")

        with self.assertRaisesRegex(Hold, "intent changed"):
            self.apply(runner=changed)
        self.assertFalse(self.sent)

    def test_postcondition_drift_holds_without_starting_or_installing(self):
        def drift(args, gate):
            result = self.runner(args, gate)
            self.machine["nic1"] = "nat"
            self.update_machine()
            return result

        with self.assertRaises(Hold):
            self.apply(runner=drift)
        self.assertEqual(len(self.sent), 1)
        self.assertFalse((self.output / "receipt.json").exists())

    def test_new_nvram_during_setting_change_is_not_silently_accepted(self):
        def drift(args, gate):
            result = self.runner(args, gate)
            self.paths["nvram"].write_bytes(b"unexpected firmware changes")
            return result

        with self.assertRaisesRegex(Hold, "NVRAM changed unexpectedly"):
            self.apply(runner=drift)
        self.assertFalse((self.output / "receipt.json").exists())

    def test_executor_command_reenables_apic_after_x2apic_and_has_no_storage_change(
        self,
    ):
        commands = profile.commands("executor")
        self.assertEqual(len(commands), 1)
        self.assertEqual(
            commands[0][:6],
            [
                "modifyvm",
                backup.SLOTS["executor"]["vm_uuid"],
                "--x86-x2apic",
                "off",
                "--apic",
                "on",
            ],
        )
        self.assertFalse(
            any(
                word in {"startvm", "controlvm", "storageattach"}
                for word in commands[0]
            )
        )


if __name__ == "__main__":
    unittest.main()
