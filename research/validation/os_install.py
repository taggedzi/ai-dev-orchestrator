"""Prepare or apply one offline Ubuntu installation to the new fixture VM."""

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from uuid import uuid4

from .bundle import digest, load_json
from .fixture import canonical
from .store import Hold, Store

WORKSPACE = Path(__file__).resolve().parents[2]
VBOX = Path("C:/Program Files/Oracle/VirtualBox/VBoxManage.exe")
VM = "74129e9c-5a65-44fa-9d35-79d458dc4704"
VM_ROOT = WORKSPACE / ".local/validation/vms/mcli1-validation-01"
ISO = WORKSPACE / ".local/validation/installers/ubuntu-24.04.5-live-server-amd64.iso"
ISO_HASH = "97f3d7ffb032c3eb3b23d2c8be9cc76e60c2c1f2c0146ba5ba9fe01cafae0fd8"


def rooted(path):
    path = Path(path).absolute()
    path.relative_to(WORKSPACE)
    for part in (path, *path.parents):
        if part.exists() and (
            part.is_symlink() or getattr(part.lstat(), "st_file_attributes", 0) & 0x400
        ):
            raise Hold("linked/reparse provisioning path")
        if part == WORKSPACE:
            break
    return path


def file_hash(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024**2), b""):
            result.update(chunk)
    return result.hexdigest()


def render_template(token):
    program = (Path(__file__).parent / "image_receipt.py").read_text(encoding="utf-8")
    # Use the installed VirtualBox template engine for just the synthetic identity.
    header = """#cloud-config
autoinstall:
  version: 1
  refresh-installer:
    update: false
  apt:
    geoip: false
    fallback: offline-install
  source:
    id: ubuntu-server-minimal
    search_drivers: false
  locale: en_US.UTF-8
  keyboard:
    layout: us
  timezone: Etc/UTC
  shutdown: poweroff
  network:
    version: 2
    ethernets: {}
  storage:
    layout:
      name: direct
      match:
        path: /dev/sda
    swap:
      size: 0
  identity:
    hostname: mcli1-validation-01
    username: fixture
    realname: Fixture Operator
    password: '@@VBOX_INSERT_USER_PASSWORD_SHACRYPT512@@'
  ssh:
    install-server: false
    allow-pw: false
    authorized-keys: []
  drivers:
    install: false
  codecs:
    install: false
  oem:
    install: false
  user-data:
    timezone: Etc/UTC
    ntp:
      enabled: false
  late-commands:
    - - /usr/bin/python3
      - -c
      - |
"""
    template = (
        header
        + "".join("        " + line + "\n" for line in program.splitlines())
        + f"      - /target\n      - {token}\n"
    )
    failure = [
        "/bin/sh",
        "-c",
        "printf '\\nMCLI1_OS_INSTALL_FAILED " + token + "\\n' > /dev/ttyS0",
    ]
    return (
        template
        + "  error-commands:\n    - "
        + json.dumps(failure)
        + "\n    - [systemctl, poweroff]\n"
    )


def parse_marker(raw, token):
    if len(raw) > 10 * 1024**2:
        raise Hold("serial evidence exceeds limit")
    prefix = "MCLI1_OS_INSTALLED " + token + " "
    candidates = [
        line[len(prefix) :]
        for line in raw.decode("utf-8", errors="replace").splitlines()
        if line.startswith(prefix)
    ]
    if len(candidates) != 1:
        raise Hold("exactly one matching install receipt required")
    result = load_json(base64.b64decode(candidates[0], validate=True))
    if (
        result.get("schema_version") != 1
        or result.get("token") != token
        or result.get("architecture") != "amd64"
    ):
        raise Hold("invalid install receipt binding")
    if (
        result.get("os_release", {}).get("ID") != "ubuntu"
        or result["os_release"].get("VERSION_ID") != "24.04"
    ):
        raise Hold("wrong installed release")
    if (
        not result.get("kernel_files")
        or type(result.get("operator_uid")) is not int
        or result["operator_uid"] <= 0
    ):
        raise Hold("incomplete installed target evidence")
    if not re.fullmatch("[0-9a-f]{64}", result.get("package_inventory_sha256", "")):
        raise Hold("missing package inventory hash")
    return result


def validate_machine(configuration, expected_cpus=2):
    if configuration.get("UUID") != VM or configuration.get("VMState") != "poweroff":
        raise Hold("target identity/state does not match the powered-off fixture VM")
    if expected_cpus not in (1, 2):
        raise Hold("unsupported preparation CPU profile")
    if configuration.get("memory") != "4096" or configuration.get("cpus") != str(
        expected_cpus
    ):
        raise Hold("target resource profile changed")
    if any(configuration.get(f"nic{n}") != "none" for n in range(1, 9)):
        raise Hold("all eight NICs must be disabled")
    if any(key.startswith("SharedFolderName") for key in configuration):
        raise Hold("host shared folders must be absent")
    if (
        configuration.get("SATA-ImageUUID-0-0")
        != "e832fc9c-23cc-40a8-8e66-fa0c624b8bd9"
    ):
        raise Hold("installation disk identity changed")


def validate_storage(config_path):
    tree = ET.parse(rooted(config_path))
    disks = [
        node
        for node in tree.iter()
        if node.tag.endswith("}AttachedDevice") and node.get("type") == "HardDisk"
    ]
    if len(disks) != 1:
        raise Hold("exactly one virtual installation disk is required")
    images = list(disks[0])
    if (
        len(images) != 1
        or images[0].get("uuid", "").strip("{}")
        != "e832fc9c-23cc-40a8-8e66-fa0c624b8bd9"
    ):
        raise Hold("unexpected attached hard disk")


def machine_fields(raw):
    fields = {}
    for line in raw.decode("utf-8", errors="strict").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            fields[key.strip('"')] = value.strip('"')
    return fields


def medium_fields(raw):
    return {
        key.strip(): value.strip()
        for line in raw.decode("utf-8").splitlines()
        if ":" in line
        for key, value in [line.split(":", 1)]
    }


class Installer:
    def __init__(self, destination):
        self.root = rooted(destination)
        self.root.mkdir(parents=True, exist_ok=False)
        self.store = Store(self.root / "control.sqlite")
        self.serial = self.root / "serial.log"
        self.started = False

    def native(self, label, arguments, mutation=True):
        if mutation:
            self.store.begin(label, digest(canonical(arguments)))
        result = subprocess.run(
            [str(VBOX), *arguments], capture_output=True, timeout=60, check=False
        )
        text = (result.stdout + result.stderr).decode("utf-8", errors="replace")
        sanitized = "\n".join(
            "[password field omitted]" if "password" in line.lower() else line
            for line in text.splitlines()
        ).encode()
        if len(sanitized) > 1024**2:
            raise Hold("native output limit")
        (self.root / (label + ".log")).write_bytes(sanitized)
        if mutation:
            self.store.receipt(label, result.returncode, sanitized)
        if result.returncode:
            raise Hold(f"VBoxManage failed at {label}; see sanitized local log")
        return result.stdout

    def configuration(self):
        return machine_fields(
            self.native(
                "configuration", ["showvminfo", VM, "--machinereadable"], mutation=False
            )
        )

    def apply(self, approval, validate_only=False):
        token = str(uuid4())
        template = self.root / "user-data.template"
        password = self.root / "operator-password.txt"
        template.write_bytes(render_template(token).encode())
        # This is a new disposable VM credential, never a host/provider credential.
        descriptor = os.open(password, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            output.write(secrets.token_urlsafe(32) + "\n")
        if not approval:
            raise Hold("explicit installation approval reference required")
        self.store.event(
            "installation-approval",
            {
                "reference": approval,
                "token": token,
                "template_sha256": file_hash(template),
                "limit_seconds": 1200,
            },
        )
        if (
            self.native("version", ["--version"], mutation=False).decode().strip()
            != "7.2.22r175245"
        ):
            raise Hold("hypervisor version changed")
        configuration = self.configuration()
        validate_machine(configuration)
        validate_storage(VM_ROOT / "mcli1-validation-01.vbox")
        # The single SATA HDD must still be the newly created installation disk.
        disk_info = medium_fields(
            self.native(
                "disk",
                [
                    "showmediuminfo",
                    "disk",
                    str(VM_ROOT / "installation.vdi"),
                ],
                mutation=False,
            )
        )
        if disk_info.get("UUID") != "e832fc9c-23cc-40a8-8e66-fa0c624b8bd9":
            raise Hold("wrong installation medium")
        if (
            disk_info.get("Capacity") != "32768 MBytes"
            or disk_info.get("Parent UUID") != "base"
        ):
            raise Hold("unexpected installation disk shape")
        disk = rooted(VM_ROOT / "installation.vdi")
        if disk.stat().st_size > 4 * 1024**2:
            raise Hold("installation disk is no longer the empty preparation disk")
        disk_before_hash = file_hash(disk)
        if file_hash(ISO) != ISO_HASH:
            raise Hold("installer ISO changed")
        arguments = [
            "unattended",
            "install",
            VM,
            "--iso=" + str(ISO),
            "--user=fixture",
            "--user-password-file=" + str(password),
            "--full-user-name=Fixture Operator",
            "--hostname=mcli1-validation-01.invalid",
            "--no-install-additions",
            "--no-install-txs",
            "--locale=en_US",
            "--country=US",
            "--time-zone=Etc/UTC",
            "--start-vm=none",
            "--script-template=" + str(template),
            "--auxiliary-base-path=" + str(self.root / "aux-"),
            r"--extra-install-kernel-parameters=autoinstall ds=nocloud\;s=/cdrom/ console=ttyS0,115200n8 console=tty0",
        ]
        if validate_only:
            self.native("custom-dry-run", [*arguments, "--dry-run"])
            validate_machine(self.configuration())
            result = {
                "classification": "custom native dry-run; no installation",
                "pass": True,
                "token": token,
                "template_sha256": file_hash(template),
            }
            (self.root / "result.json").write_bytes(canonical(result) + b"\n")
            return result
        self.native("prepare-media", arguments)
        self.native(
            "serial-configuration",
            [
                "modifyvm",
                VM,
                "--uart1",
                "0x3F8",
                "4",
                "--uart-mode1",
                "file",
                str(self.serial),
            ],
        )
        validate_machine(self.configuration())
        validate_storage(VM_ROOT / "mcli1-validation-01.vbox")
        intent = {
            "token": token,
            "approval": approval,
            "vm_uuid": VM,
            "iso_sha256": ISO_HASH,
            "template_sha256": file_hash(template),
            "deadline_seconds": 1200,
            "disk_before_sha256": disk_before_hash,
        }
        (self.root / "install-intent.json").write_bytes(canonical(intent) + b"\n")
        if file_hash(disk) != disk_before_hash:
            raise Hold("installation disk changed before boot")
        self.started = (
            True  # A lost start acknowledgement still requires stop/reconciliation.
        )
        start = time.monotonic()
        self.native("start-install", ["startvm", VM, "--type", "headless"])
        last_progress = 0
        while time.monotonic() - start < 1200:
            configuration = self.configuration()
            if any(configuration.get(f"nic{n}") != "none" for n in range(1, 9)):
                raise Hold("network profile changed while installing")
            if self.serial.exists() and self.serial.stat().st_size > 10 * 1024**2:
                raise Hold("serial evidence limit")
            if (
                self.serial.exists()
                and ("MCLI1_OS_INSTALL_FAILED " + token).encode()
                in self.serial.read_bytes()
            ):
                raise Hold(
                    "installer reported failure; retained serial diagnostics require review"
                )
            if configuration.get("VMState") == "poweroff":
                self.started = False
                receipt = parse_marker(self.serial.read_bytes(), token)
                result = {
                    "classification": "measured offline OS installation; first boot and runtime boundary unqualified",
                    "vm_uuid": VM,
                    "elapsed_seconds": round(time.monotonic() - start, 3),
                    "state": "poweroff",
                    "network": "eight NICs disabled",
                    "image": receipt,
                    "serial_sha256": file_hash(self.serial),
                    "installed_vdi_sha256": file_hash(disk),
                    "intent": intent,
                }
                (self.root / "result.json").write_bytes(canonical(result) + b"\n")
                self.store.event("installed-target-receipt", result)
                return result
            elapsed = int(time.monotonic() - start)
            if elapsed - last_progress >= 30:
                print(
                    canonical(
                        {
                            "phase": "installing",
                            "elapsed_seconds": elapsed,
                            "vm_state": configuration.get("VMState"),
                        }
                    ).decode(),
                    flush=True,
                )
                last_progress = elapsed
            time.sleep(3)
        raise Hold("installation deadline exceeded")

    def close(self):
        try:
            if self.started:
                self.store.fence("installation failed or timed out")
                # Revocation must never prevent this target's emergency stop.
                # The ordinary mutation path intentionally rejects fenced or
                # uncertain operations, including an unanswered start request.
                self.store.event("emergency-stop-intent", {"vm_uuid": VM})
                result = subprocess.run(
                    [str(VBOX), "controlvm", VM, "poweroff"],
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
                state = self.configuration().get("VMState")
                self.store.event(
                    "emergency-stop-observation",
                    {
                        "vm_uuid": VM,
                        "command_exit": result.returncode,
                        "stdout_sha256": digest(result.stdout),
                        "stderr_sha256": digest(result.stderr),
                        "state": state,
                    },
                )
                if state != "poweroff":
                    raise Hold(
                        "emergency stop is unconfirmed; runtime requires operator reconciliation"
                    )
                self.started = False
        finally:
            self.store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--approval")
    parser.add_argument(
        "--output", type=Path, default=WORKSPACE / ".local/validation/os-install"
    )
    args = parser.parse_args()
    if not args.apply and not args.validate_only:
        print(
            canonical(
                {
                    "mode": "plan-only",
                    "target": VM,
                    "source": "ubuntu-server-minimal from verified ISO",
                    "network": "all NICs disabled",
                    "installs": "Ubuntu base OS only",
                    "ssh": False,
                    "guest_additions": False,
                    "max_seconds": 1200,
                    "completion": "installed target receipt plus VM poweroff; first boot unqualified",
                    "writes": "new installation disk, VM auxiliary media, serial log and local disposable credential",
                }
            ).decode()
        )
        return
    if not args.approval:
        parser.error("--approval is required for native dry-run or installation")
    installer = Installer(args.output)
    try:
        print(
            canonical(
                installer.apply(args.approval, validate_only=args.validate_only)
            ).decode(),
            flush=True,
        )
    finally:
        installer.close()


if __name__ == "__main__":
    main()
