"""Boot protocol and stop checks with no live VM or pipe operations."""

import base64
import json
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research.validation.first_boot import (
    TRIAL_SOURCES,
    PipeConsole,
    check_receipt,
    clean_text,
    parse_receipt,
    probe_commands,
    removable_media,
    validate_apic,
    validate_checkpoint,
)
from research.validation.os_install import VBOX, VM, Installer
from research.validation.store import Hold, Store


def installed():
    return {
        "kernel_files": ["vmlinuz-test-kernel"],
        "operator_uid": 1000,
        "package_inventory_sha256": "a" * 64,
    }


def receipt():
    return {
        "schema_version": 1,
        "token": "test",
        "os_release": {"ID": "ubuntu", "VERSION_ID": "24.04"},
        "running_kernel": "test-kernel",
        "uid": 1000,
        "fixture_uid": 1000,
        "interfaces": ["lo"],
        "root_mount": ["/dev/sda2", "/", "ext4", "rw,relatime"],
        "command_line": "root=UUID=example ro console=ttyS0",
        "package_inventory_sha256": "a" * 64,
        "package_audit": {"exit": 0, "stdout": "", "stderr": ""},
        "cloud_init": {"exit": 0, "report": {"status": "done"}},
        "ssh_server_installed": False,
    }


class BootTests(unittest.TestCase):
    def test_x2apic_off_keeps_ordinary_apic_and_firmware_profile(self):
        profile = {"apic": "on", "ioapic": "on", "biosapic": "apic", "x2apic": "off"}
        validate_apic(profile, "off")
        for key in profile:
            with self.assertRaises(Hold):
                validate_apic(profile | {key: "unexpected"}, "off")
        with self.assertRaises(Hold):
            validate_apic(profile | {"apic": "off"}, "off")

    def test_failed_native_start_is_reported_before_pipe_connection(self):
        import time
        from concurrent.futures import Future

        failed = Future()
        failed.set_exception(Hold("native start failed"))
        with self.assertRaisesRegex(Hold, "native start failed"):
            PipeConsole("unused", "disposable").connect(time.monotonic() + 60, failed)

    def test_x2apic_trial_binds_stopped_disk_audit_and_offline_evidence(self):
        import hashlib

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = root / "research/validation/offline-inspection-evidence.json"
            evidence.parent.mkdir(parents=True)
            evidence.write_bytes(b"offline evidence")
            pins = {}
            for name in TRIAL_SOURCES:
                (evidence.parent / name).write_bytes(b"frozen source")
                pins[name] = hashlib.sha256(b"frozen source").hexdigest()
            capture = b"completed receipt and failed shutdown\n"
            (root / "serial-sanitized.log").write_bytes(capture)
            (root / "post-trial-state.json").write_text(
                json.dumps({"stopped_vdi_sha256": "stopped"})
            )
            parent = {
                "retry_index": 3,
                "original_installed_vdi_sha256": "original",
                "stopped_vdi_sha256": "input",
                "checkpoint_sha256": "parent",
            }
            store = Store(root / "control.sqlite")
            store.event(
                "first-boot-approval",
                {"input_vdi_sha256": "input", "prior_attempt": parent},
            )
            store.event(
                "emergency-stop-observation", {"vm_uuid": VM, "state": "poweroff"}
            )
            tail = store.audit()[-1]["digest"]
            store.close()
            data = {
                "kind": "stopped-boot-reconciliation-v1",
                "vm_uuid": VM,
                "retry_index": 4,
                "original_installed_vdi_sha256": "original",
                "stopped_vdi_sha256": "stopped",
                "serial_sha256": hashlib.sha256(capture).hexdigest(),
                "profile_change": {"x2apic": "off"},
                "parent_checkpoint_sha256": "parent",
                "prior_audit_tail_digest": tail,
                "offline_inspection_sha256": hashlib.sha256(
                    evidence.read_bytes()
                ).hexdigest(),
                "trial_source_sha256": pins,
            }
            path = root / "checkpoint.json"
            with (
                patch("research.validation.first_boot.rooted", side_effect=lambda p: p),
                patch("research.validation.first_boot.WORKSPACE", root),
            ):
                path.write_text(json.dumps(data))
                self.assertEqual(
                    validate_checkpoint(path, "original")["retry_index"], 4
                )
                for change in [
                    {"prior_audit_tail_digest": "wrong"},
                    {"stopped_vdi_sha256": "wrong"},
                    {"offline_inspection_sha256": "wrong"},
                    {"profile_change": {"cpus": 3}},
                    {"trial_source_sha256": pins | {"first_boot.py": "changed"}},
                ]:
                    path.write_text(json.dumps(data | change))
                    with self.assertRaises(Hold):
                        validate_checkpoint(path, "original")
                path.write_text(json.dumps(data))
                evidence.write_bytes(b"changed evidence")
                with self.assertRaises(Hold):
                    validate_checkpoint(path, "original")

    def test_reconciled_retry_requires_matching_capture_original_intent_and_stop(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "serial-sanitized.log").write_bytes(b"partial boot\n")
            store = Store(root / "control.sqlite")
            store.event("first-boot-approval", {"input_vdi_sha256": "original"})
            store.event(
                "emergency-stop-observation", {"vm_uuid": VM, "state": "poweroff"}
            )
            store.close()
            import hashlib

            data = {
                "kind": "stopped-boot-reconciliation-v1",
                "vm_uuid": VM,
                "retry_index": 1,
                "original_installed_vdi_sha256": "original",
                "stopped_vdi_sha256": "changed-by-boot",
                "serial_sha256": hashlib.sha256(b"partial boot\n").hexdigest(),
            }
            path = root / "checkpoint.json"
            path.write_text(json.dumps(data))
            with patch(
                "research.validation.first_boot.rooted", side_effect=lambda p: p
            ):
                self.assertEqual(
                    validate_checkpoint(path, "original")["stopped_vdi_sha256"],
                    "changed-by-boot",
                )
                with self.assertRaises(Hold):
                    validate_checkpoint(path, "different-image")
                (root / "serial-sanitized.log").write_bytes(b"changed capture")
                with self.assertRaises(Hold):
                    validate_checkpoint(path, "original")

    def test_receipt_accepts_only_one_matching_complete_frame(self):
        line = (
            b"MCLI1_BOOT_RESULT test "
            + base64.b64encode(json.dumps(receipt()).encode())
            + b"\r\n"
        )
        self.assertEqual(parse_receipt(b"kernel log\r\n" + line, "test"), receipt())
        for raw, token in ((line * 2, "test"), (line, "wrong"), (line[:-2], "test")):
            with self.assertRaises(Hold):
                parse_receipt(raw, token)
        # A serial read may stop anywhere, including inside an apparently valid base64 word.
        for end in range(len(b"MCLI1_BOOT_RESULT test ") + 1, len(line) - 1):
            with self.assertRaises(Hold):
                parse_receipt(line[:end], "test")

    def test_protocol_retry_requires_bound_parent_and_completed_transfer(self):
        import hashlib

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capture = b"probe transferred\n"
            (root / "serial-sanitized.log").write_bytes(capture)
            parent = {
                "retry_index": 2,
                "original_installed_vdi_sha256": "original",
                "stopped_vdi_sha256": "before-protocol-failure",
                "checkpoint_sha256": "parent-checkpoint",
            }
            store = Store(root / "control.sqlite")
            store.event(
                "first-boot-approval",
                {
                    "input_vdi_sha256": "before-protocol-failure",
                    "prior_attempt": parent,
                },
            )
            store.event("serial-phase", {"phase": "collecting-boot-receipt"})
            store.event(
                "emergency-stop-observation", {"vm_uuid": VM, "state": "poweroff"}
            )
            audit = store.audit()
            store.close()
            data = {
                "kind": "stopped-boot-reconciliation-v1",
                "vm_uuid": VM,
                "retry_index": 3,
                "original_installed_vdi_sha256": "original",
                "stopped_vdi_sha256": "after-protocol-failure",
                "serial_sha256": hashlib.sha256(capture).hexdigest(),
                "profile_change": {"cpus": 1},
                "parent_checkpoint_sha256": "parent-checkpoint",
            }
            path = root / "checkpoint.json"
            with patch(
                "research.validation.first_boot.rooted", side_effect=lambda p: p
            ):
                path.write_text(json.dumps(data))
                self.assertEqual(
                    validate_checkpoint(path, "original")["retry_index"], 3
                )
                for change in (
                    {"parent_checkpoint_sha256": "wrong-parent"},
                    {"profile_change": {"cpus": 2}},
                    {"retry_index": 5},
                ):
                    path.write_text(json.dumps(data | change))
                    with self.assertRaises(Hold):
                        validate_checkpoint(path, "original")
                path.write_text(json.dumps(data))
                with (
                    patch.object(
                        Store,
                        "audit",
                        return_value=[r for r in audit if r["kind"] != "serial-phase"],
                    ),
                    self.assertRaises(Hold),
                ):
                    validate_checkpoint(path, "original")

    def test_live_installer_root_wrong_kernel_root_login_and_network_fail(self):
        self.assertTrue(check_receipt(receipt(), installed())["pass"])
        changes = [
            {"root_mount": ["overlay", "/", "overlay", "rw"]},
            {"running_kernel": "unexpected"},
            {"uid": 0},
            {"interfaces": ["lo", "enp0s3"]},
            {"command_line": "autoinstall boot=casper"},
            {"package_inventory_sha256": "b" * 64},
            {"ssh_server_installed": True},
            {"cloud_init": {"exit": 1, "report": {"status": "error"}}},
        ]
        for change in changes:
            self.assertFalse(
                check_receipt(receipt() | change, installed())["pass"], change
            )

    def test_console_credentials_are_redacted_across_capture_chunks(self):
        console = PipeConsole("unused", "disposable-test-password")
        console.raw.extend(b"log disposable-test-")
        console.raw.extend(b"password tail")
        self.assertNotIn(b"disposable-test-password", console.sanitized())
        self.assertEqual(console.sanitized(), b"log [credential omitted] tail")

    def test_console_normalization_removes_ansi_and_carriage_returns(self):
        self.assertEqual(
            clean_text(b"\x1b[32mfixture@host:~$\x1b[0m \r\n"), "fixture@host:~$ \n"
        )

    def test_probe_transfer_uses_small_compilable_lines(self):
        source = (
            Path(__file__).parents[1] / "research/validation/boot_receipt.py"
        ).read_bytes()
        commands, execute = probe_commands(source, "test")
        self.assertGreater(len(commands), 2)
        for command, _ in commands:
            self.assertLess(len(command.encode()), 2048)
            compile(shlex.split(command)[2], "<transfer>", "exec")
        compile(shlex.split(execute)[2], "<execute>", "exec")

    def test_only_nonempty_dvd_media_are_selected_for_detachment(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "test.vbox"
            path.write_text(
                '<VirtualBox xmlns="urn:test"><StorageController name="SATA"><AttachedDevice type="DVD" port="1" device="0"><Image uuid="test"/></AttachedDevice><AttachedDevice type="DVD" port="2" device="0"/></StorageController></VirtualBox>'
            )
            with patch(
                "research.validation.first_boot.rooted", side_effect=lambda p: p
            ):
                self.assertEqual(removable_media(path), [("SATA", "1", "0")])

    def test_emergency_stop_is_not_blocked_by_fence_or_unanswered_start(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "run"
            with patch(
                "research.validation.os_install.rooted", side_effect=lambda p: p
            ):
                runner = Installer(root)
            runner.store.begin("unanswered-start", "request-hash")
            runner.started = True
            with patch(
                "research.validation.os_install.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0, b"stopped", b""),
            ) as native:
                with patch.object(
                    runner, "configuration", return_value={"VMState": "poweroff"}
                ):
                    runner.close()
                self.assertEqual(
                    native.call_args.args[0], [str(VBOX), "controlvm", VM, "poweroff"]
                )
            store = Store(root / "control.sqlite")
            try:
                events = [row["kind"] for row in store.audit()]
                self.assertIn("emergency-stop-intent", events)
                self.assertIn("emergency-stop-observation", events)
                self.assertFalse(store.snapshot()["authority"]["active"])
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
