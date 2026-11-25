"""Offline installation guard and receipt tests; no VM boot or native writes."""

import base64
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research.validation.os_install import (
    VM,
    WORKSPACE,
    machine_fields,
    medium_fields,
    parse_marker,
    render_template,
    rooted,
    validate_machine,
    validate_storage,
)
from research.validation.store import Hold


def config():
    return {
        "UUID": VM,
        "VMState": "poweroff",
        "memory": "4096",
        "cpus": "2",
        "SATA-ImageUUID-0-0": "e832fc9c-23cc-40a8-8e66-fa0c624b8bd9",
        **{f"nic{number}": "none" for number in range(1, 9)},
    }


def receipt():
    return {
        "schema_version": 1,
        "token": "test-token",
        "architecture": "amd64",
        "os_release": {"ID": "ubuntu", "VERSION_ID": "24.04"},
        "kernel_files": ["vmlinuz-example"],
        "operator_uid": 1000,
        "package_inventory_sha256": "a" * 64,
    }


def line(row):
    return (
        b"MCLI1_OS_INSTALLED test-token "
        + base64.b64encode(json.dumps(row).encode())
        + b"\r\n"
    )


class InstallTests(unittest.TestCase):
    def test_native_medium_output_preserves_windows_path_and_capacity(self):
        raw = b"UUID: example\r\nLocation: E:\\fixture\\disk.vdi\r\nCapacity: 32768 MBytes\r\n"
        self.assertEqual(
            medium_fields(raw),
            {
                "UUID": "example",
                "Location": "E:\\fixture\\disk.vdi",
                "Capacity": "32768 MBytes",
            },
        )

    def test_machine_rejects_running_networked_or_wrong_disk_target(self):
        validate_machine(config())
        for change in (
            {"VMState": "running"},
            {"UUID": "other"},
            {"nic1": "nat"},
            {"nic8": "bridged"},
            {"memory": "8192"},
            {"SharedFolderName1": "host"},
            {"SATA-ImageUUID-0-0": "other"},
        ):
            with self.assertRaises(Hold):
                validate_machine(config() | change)

    def test_receipt_requires_exact_token_unique_marker_and_installed_target(self):
        self.assertEqual(
            parse_marker(b"kernel log\n" + line(receipt()), "test-token"), receipt()
        )
        for raw in (
            b"",
            line(receipt()) * 2,
            line(receipt() | {"architecture": "arm64"}),
            line(receipt() | {"kernel_files": []}),
            line(receipt() | {"operator_uid": 0}),
            line(receipt() | {"os_release": {"ID": "other"}}),
        ):
            with self.assertRaises(Hold):
                parse_marker(raw, "test-token")
        with self.assertRaises(Hold):
            parse_marker(line(receipt()), "wrong-token")

    def test_host_paths_cannot_escape_workspace(self):
        self.assertEqual(
            rooted(WORKSPACE / ".local/validation/os-install-test"),
            WORKSPACE / ".local/validation/os-install-test",
        )
        with self.assertRaises(ValueError):
            rooted(WORKSPACE.parent / "outside")

    def test_xml_storage_guard_rejects_extra_disks(self):
        disk = '<AttachedDevice type="HardDisk"><Image uuid="{e832fc9c-23cc-40a8-8e66-fa0c624b8bd9}"/></AttachedDevice>'
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "test.vbox"
            with patch(
                "research.validation.os_install.rooted", side_effect=lambda p: p
            ):
                path.write_text(
                    '<VirtualBox xmlns="urn:test">' + disk + "</VirtualBox>"
                )
                validate_storage(path)
                path.write_text(
                    '<VirtualBox xmlns="urn:test">' + disk * 2 + "</VirtualBox>"
                )
                with self.assertRaises(Hold):
                    validate_storage(path)

    def test_machine_readable_values_are_parsed_without_shell_evaluation(self):
        self.assertEqual(
            machine_fields(b'UUID="example"\nmemory=4096\n"SATA-0-0"="C:\\path"\n'),
            {"UUID": "example", "memory": "4096", "SATA-0-0": "C:\\path"},
        )

    @unittest.skipUnless(
        importlib.util.find_spec("yaml"),
        "optional installed PyYAML validator unavailable",
    )
    def test_rendered_template_is_valid_yaml_and_late_program_compiles(self):
        import yaml

        raw = render_template("test-token")
        parsed = yaml.safe_load(raw)["autoinstall"]
        self.assertEqual(parsed["source"]["id"], "ubuntu-server-minimal")
        self.assertEqual(parsed["shutdown"], "poweroff")
        self.assertFalse(parsed["refresh-installer"]["update"])
        self.assertFalse(parsed["ssh"]["install-server"])
        self.assertEqual(parsed["network"]["ethernets"], {})
        self.assertEqual(parsed["storage"]["layout"]["match"]["path"], "/dev/sda")
        command = parsed["late-commands"][0]
        self.assertEqual(command[:2], ["/usr/bin/python3", "-c"])
        self.assertEqual(command[-2:], ["/target", "test-token"])
        compile(command[2], "inline-receipt", "exec")
        self.assertNotIn("packages", parsed)


if __name__ == "__main__":
    unittest.main()
