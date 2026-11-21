"""Bounded offline boot verification over a temporary Windows named pipe."""

import argparse
import base64
import ctypes
import io
import re
import shlex
import subprocess
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from .bundle import digest, load_json
from .fixture import canonical
from .os_install import (
    VM,
    VM_ROOT,
    WORKSPACE,
    Installer,
    file_hash,
    rooted,
    validate_machine,
    validate_storage,
)
from .store import Hold, Store

MAX_CAPTURE = 10 * 1024**2


def validate_checkpoint(path, original_hash):
    path = rooted(path)
    data = load_json(path.read_bytes())
    if (
        data.get("kind") != "stopped-boot-reconciliation-v1"
        or data.get("vm_uuid") != VM
    ):
        raise Hold("invalid stopped-boot checkpoint")
    if data.get("original_installed_vdi_sha256") != original_hash or data.get(
        "retry_index"
    ) not in (1, 2, 3):
        raise Hold("checkpoint is outside the bounded reviewed boot trials")
    if file_hash(path.parent / "serial-sanitized.log") != data.get("serial_sha256"):
        raise Hold("prior console evidence changed")
    previous = Store(path.parent / "control.sqlite")
    try:
        audit = previous.audit()
    finally:
        previous.close()
    approvals = [
        row["payload"] for row in audit if row["kind"] == "first-boot-approval"
    ]
    if len(approvals) != 1:
        raise Hold("prior boot intent is ambiguous")
    if data["retry_index"] == 1:
        if (
            approvals[0].get("input_vdi_sha256") != original_hash
            or approvals[0].get("prior_attempt") is not None
        ):
            raise Hold("prior boot intent does not match the original installation")
    elif data["retry_index"] == 2:
        parent = approvals[0].get("prior_attempt") or {}
        if (
            data.get("profile_change") != {"cpus": 1}
            or parent.get("retry_index") != 1
            or parent.get("original_installed_vdi_sha256") != original_hash
            or approvals[0].get("input_vdi_sha256") != parent.get("stopped_vdi_sha256")
            or data.get("parent_checkpoint_sha256") != parent.get("checkpoint_sha256")
        ):
            raise Hold("diagnostic CPU trial lacks a valid stopped-image chain")
    else:
        parent = approvals[0].get("prior_attempt") or {}
        if (
            data.get("profile_change") != {"cpus": 1}
            or parent.get("retry_index") != 2
            or parent.get("original_installed_vdi_sha256") != original_hash
            or approvals[0].get("input_vdi_sha256") != parent.get("stopped_vdi_sha256")
            or data.get("parent_checkpoint_sha256") != parent.get("checkpoint_sha256")
            or not any(
                row["kind"] == "serial-phase"
                and row["payload"].get("phase") == "collecting-boot-receipt"
                for row in audit
            )
        ):
            raise Hold("protocol retry lacks the completed login/transfer chain")
    if (
        not audit
        or audit[-1]["kind"] != "emergency-stop-observation"
        or audit[-1]["payload"].get("state") != "poweroff"
        or audit[-1]["payload"].get("vm_uuid") != VM
    ):
        raise Hold("prior attempt lacks confirmed stop evidence")
    return data | {"checkpoint_sha256": file_hash(path)}


def clean_text(raw):
    text = raw.decode("utf-8", errors="replace").replace("\r", "")
    return re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)


def parse_receipt(raw, token):
    prefix = "MCLI1_BOOT_RESULT " + token + " "
    rows = re.findall(
        "^" + re.escape(prefix) + r"([A-Za-z0-9+/=]+)\n", clean_text(raw), re.MULTILINE
    )
    if len(rows) != 1:
        raise Hold("exactly one token-bound boot receipt required")
    result = load_json(base64.b64decode(rows[0], validate=True))
    if result.get("schema_version") != 1 or result.get("token") != token:
        raise Hold("boot receipt identity mismatch")
    return result


def check_receipt(result, installed):
    checks = {
        "ubuntu_release": result.get("os_release", {}).get("ID") == "ubuntu"
        and result["os_release"].get("VERSION_ID") == "24.04",
        "installed_kernel": "vmlinuz-" + result.get("running_kernel", "")
        in installed["kernel_files"],
        "non_root_operator": result.get("uid")
        == result.get("fixture_uid")
        == installed["operator_uid"]
        and result["uid"] > 0,
        "loopback_only": result.get("interfaces") == ["lo"],
        "disk_root": len(result.get("root_mount", [])) == 4
        and result["root_mount"][2] == "ext4"
        and "rw" in result["root_mount"][3].split(","),
        "no_installer_arguments": not any(
            word in result.get("command_line", "")
            for word in ("autoinstall", "/casper/", "boot=casper")
        ),
        "package_inventory_unchanged": result.get("package_inventory_sha256")
        == installed["package_inventory_sha256"],
        "package_audit_clean": result.get("package_audit")
        == {"exit": 0, "stdout": "", "stderr": ""},
        "cloud_init_done": result.get("cloud_init", {}).get("exit") == 0
        and (result["cloud_init"].get("report") or {}).get("status") == "done",
        "ssh_absent": result.get("ssh_server_installed") is False,
    }
    return {"pass": all(checks.values()), "checks": checks}


def removable_media(path):
    tree = ET.parse(rooted(path))
    media = []
    for controller in tree.iter():
        if not controller.tag.endswith("}StorageController"):
            continue
        for device in controller:
            if device.get("type") == "Floppy":
                raise Hold("unexpected floppy medium")
            if device.get("type") == "DVD" and list(device):
                media.append(
                    (controller.get("name"), device.get("port"), device.get("device"))
                )
    return media


def probe_commands(source, token):
    """Keep each tty input line well below the Linux canonical-input limit."""
    path = "/tmp/mcli1-boot-" + token + ".b64"
    payload = base64.b64encode(source).decode("ascii")
    statements = [
        (
            "from pathlib import Path; Path(" + repr(path) + ").touch(exist_ok=False)",
            "create",
        )
    ]
    for number, offset in enumerate(range(0, len(payload), 600)):
        statements.append(
            (
                "from pathlib import Path; p=Path("
                + repr(path)
                + "); p.open('ab').write("
                + repr(payload[offset : offset + 600].encode())
                + ")",
                str(number),
            )
        )
    commands = []
    for statement, label in statements:
        ack = "MCLI1_ACK_" + token + "_" + label
        commands.append(
            (
                "python3 -c "
                + shlex.quote(statement + "; print(" + repr(ack) + ", flush=True)"),
                ack,
            )
        )
    execute = (
        "from pathlib import Path; import base64,sys; p=Path("
        + repr(path)
        + "); data=base64.b64decode(p.read_bytes()); p.unlink(); sys.argv=['mcli1-boot',"
        + repr(token)
        + "]; exec(compile(data,'<mcli1-boot>','exec'),{'__name__':'__main__'})"
    )
    return commands, "python3 -c " + shlex.quote(execute)


class PipeConsole:
    def __init__(self, name, password):
        self.name, self.password = name, password
        self.file = None
        self.raw = bytearray()

    def connect(self, deadline):
        while time.monotonic() < deadline:
            try:
                self.file = io.FileIO(self.name, "r+")
                return
            except OSError as error:
                if getattr(error, "winerror", None) not in (None, 2, 231):
                    raise
                time.sleep(0.1)
        raise Hold("serial pipe connection deadline")

    def read_available(self):
        import msvcrt

        api = ctypes.WinDLL("kernel32", use_last_error=True).PeekNamedPipe
        api.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.c_void_p,
        ]
        api.restype = ctypes.c_int
        available = ctypes.c_ulong()
        if not api(
            msvcrt.get_osfhandle(self.file.fileno()),
            None,
            0,
            None,
            ctypes.byref(available),
            None,
        ):
            raise Hold("serial pipe closed before expected receipt")
        if available.value:
            data = self.file.read(min(available.value, 4096))
            if len(self.raw) + len(data) > MAX_CAPTURE:
                raise Hold("serial capture limit")
            self.raw.extend(data)

    def wait(self, pattern, deadline, heartbeat, wake=False):
        last_wake = time.monotonic()
        while time.monotonic() < deadline:
            self.read_available()
            if re.search(pattern, clean_text(self.raw), re.MULTILINE):
                return
            heartbeat()
            if wake and time.monotonic() - last_wake >= 20:
                self.send(
                    ""
                )  # Re-display a getty prompt; never send credentials early.
                last_wake = time.monotonic()
            time.sleep(0.05)
        raise Hold("serial protocol deadline")

    def send(self, text):
        data = (text + "\r").encode("utf-8")
        if len(data) > 2048:
            raise Hold("tty command exceeds input limit")
        if self.file.write(data) != len(data):
            raise Hold("partial serial write")

    def sanitized(self):
        return bytes(self.raw).replace(self.password.encode(), b"[credential omitted]")

    def close(self):
        if self.file is not None:
            self.file.close()


class BootCheck(Installer):
    def run(self, approval, checkpoint=None, single_cpu=False):
        if not approval:
            raise Hold("boot approval reference required")
        expected = load_json(
            (WORKSPACE / "research/validation/os-install-evidence.json").read_bytes()
        )["result"]
        version = self.native("version", ["--version"], mutation=False).decode().strip()
        if version != "7.2.22r175245":
            raise Hold("hypervisor version changed")
        validate_storage(VM_ROOT / "mcli1-validation-01.vbox")
        disk = rooted(VM_ROOT / "installation.vdi")
        input_hash = expected["installed_vdi_sha256"]
        prior_attempt = None
        if checkpoint is not None:
            prior_attempt = validate_checkpoint(
                checkpoint, expected["installed_vdi_sha256"]
            )
            input_hash = prior_attempt["stopped_vdi_sha256"]
        validate_machine(
            self.configuration(),
            expected_cpus=1
            if prior_attempt and prior_attempt["retry_index"] == 3
            else 2,
        )
        expected_cpus = 1 if single_cpu else 2
        if single_cpu and (
            not prior_attempt or prior_attempt.get("profile_change") != {"cpus": 1}
        ):
            raise Hold("one-CPU diagnostic requires its stopped-image checkpoint")
        if prior_attempt and prior_attempt.get("profile_change") and not single_cpu:
            raise Hold("checkpoint requires the explicit one-CPU option")
        if file_hash(disk) != input_hash:
            raise Hold("installed image changed since its recorded receipt")
        password = (
            rooted(WORKSPACE / ".local/validation/os-install-01/operator-password.txt")
            .read_text()
            .strip()
        )
        token = str(uuid4())
        pipe = "\\\\.\\pipe\\mcli1-firstboot-" + token
        console = PipeConsole(pipe, password)
        self.store.event(
            "first-boot-approval",
            {
                "approval": approval,
                "token": token,
                "max_seconds": 600,
                "input_vdi_sha256": input_hash,
                "prior_attempt": prior_attempt,
            },
        )
        if single_cpu:
            self.native("one-cpu-nem-diagnostic", ["modifyvm", VM, "--cpus", "1"])
        for number, (controller, port, device) in enumerate(
            removable_media(VM_ROOT / "mcli1-validation-01.vbox")
        ):
            self.native(
                f"detach-installer-{number}",
                [
                    "storageattach",
                    VM,
                    "--storagectl",
                    controller,
                    "--port",
                    port,
                    "--device",
                    device,
                    "--type",
                    "dvddrive",
                    "--medium",
                    "none",
                ],
            )
        self.native(
            "disk-boot-and-pipe",
            [
                "modifyvm",
                VM,
                "--boot1",
                "disk",
                "--boot2",
                "none",
                "--boot3",
                "none",
                "--boot4",
                "none",
                "--uart1",
                "0x3F8",
                "4",
                "--uart-mode1",
                "server",
                pipe,
            ],
        )
        validate_machine(self.configuration(), expected_cpus=expected_cpus)
        if removable_media(VM_ROOT / "mcli1-validation-01.vbox"):
            raise Hold("installer media still attached")
        started = time.monotonic()
        deadline = started + 600
        last_check, last_progress = [0], [0]

        def heartbeat():
            now = time.monotonic()
            if now - last_check[0] >= 10:
                status = self.configuration()
                if status.get("VMState") != "running" or any(
                    status.get(f"nic{n}") != "none" for n in range(1, 9)
                ):
                    raise Hold("running/offline VM binding lost")
                last_check[0] = now
            if now - last_progress[0] >= 30:
                print(
                    canonical(
                        {
                            "phase": "first-boot",
                            "elapsed_seconds": int(now - started),
                            "serial_bytes": len(console.raw),
                        }
                    ).decode(),
                    flush=True,
                )
                last_progress[0] = now

        try:
            self.started = True
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    self.native,
                    "start-first-boot",
                    ["startvm", VM, "--type", "headless"],
                )
                console.connect(min(deadline, time.monotonic() + 60))
                future.result(timeout=60)
            self.store.event("serial-phase", {"phase": "waiting-login"})
            console.wait(
                r"^.* login: *$",
                min(deadline, time.monotonic() + 360),
                heartbeat,
                wake=True,
            )
            console.send("fixture")
            self.store.event("serial-phase", {"phase": "waiting-password-prompt"})
            console.wait(
                r"^Password: *$", min(deadline, time.monotonic() + 30), heartbeat
            )
            console.send(password)
            self.store.event("serial-phase", {"phase": "waiting-user-shell"})
            console.wait(
                r"^.*fixture@.*\$ *$", min(deadline, time.monotonic() + 45), heartbeat
            )
            ready = "MCLI1_READY_" + token
            console.send("stty -echo && printf '\\n" + ready + "\\n'")
            console.wait(
                "^" + re.escape(ready) + "$",
                min(deadline, time.monotonic() + 15),
                heartbeat,
            )
            source = (Path(__file__).parent / "boot_receipt.py").read_bytes()
            self.store.event("serial-phase", {"phase": "transferring-probe"})
            commands, execute = probe_commands(source, token)
            for command, ack in commands:
                console.send(command)
                console.wait(
                    "^" + re.escape(ack) + "$",
                    min(deadline, time.monotonic() + 15),
                    heartbeat,
                )
            console.send(execute)
            self.store.event("serial-phase", {"phase": "collecting-boot-receipt"})
            console.wait(
                "^MCLI1_BOOT_RESULT " + re.escape(token) + r" [A-Za-z0-9+/=]+\n",
                min(deadline, time.monotonic() + 210),
                heartbeat,
            )
            receipt = parse_receipt(console.raw, token)
            verdict = check_receipt(receipt, expected["image"])
            # Preserve observations even when the subsequent shutdown fails.
            (self.root / "boot-receipt.json").write_bytes(canonical(receipt) + b"\n")
            (self.root / "boot-verdict.json").write_bytes(canonical(verdict) + b"\n")
            self.store.event(
                "base-os-boot-observation", {"receipt": receipt, "verdict": verdict}
            )
            self.native("acpi-shutdown", ["controlvm", VM, "acpipowerbutton"])
            shutdown_deadline = min(deadline, time.monotonic() + 60)
            while time.monotonic() < shutdown_deadline:
                status = self.configuration()
                if status.get("VMState") == "poweroff":
                    self.started = False
                    break
                time.sleep(2)
            if self.started:
                raise Hold("ACPI shutdown not confirmed by deadline")
            self.native(
                "disconnect-preparation-console",
                ["modifyvm", VM, "--uart1", "off", "--uart-mode1", "disconnected"],
            )
            validate_machine(self.configuration(), expected_cpus=expected_cpus)
            result = {
                "classification": "measured offline base OS boot; runtime isolation and executor remain unqualified",
                "pass": verdict["pass"],
                "checks": verdict["checks"],
                "vm_uuid": VM,
                "hypervisor_version": version,
                "guest_cpus": expected_cpus,
                "state": "poweroff",
                "network": "eight NICs disabled",
                "shutdown": "ACPI",
                "temporary_uart": "disabled after shutdown",
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "image": receipt,
                "input_vdi_sha256": input_hash,
                "prior_attempt": prior_attempt,
                "output_vdi_sha256": file_hash(disk),
                "probe_sha256": digest(source),
                "serial_sha256": digest(console.sanitized()),
            }
            (self.root / "result.json").write_bytes(canonical(result) + b"\n")
            self.store.event("base-os-boot-result", result)
            return result
        finally:
            (self.root / "serial-sanitized.log").write_bytes(console.sanitized())
            console.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approval")
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--single-cpu-diagnostic", action="store_true")
    parser.add_argument(
        "--output", type=Path, default=WORKSPACE / ".local/validation/first-boot-01"
    )
    args = parser.parse_args()
    if not args.apply:
        print(
            canonical(
                {
                    "mode": "plan-only",
                    "target": VM,
                    "boot": "installed disk only",
                    "network": "eight NICs disabled",
                    "probe_user": "fixture, no sudo",
                    "max_seconds": 600,
                    "transport": "temporary named pipe, no network or guest additions",
                    "shutdown": "ACPI followed by UART disable",
                }
            ).decode()
        )
        return
    if not args.approval:
        parser.error("--approval is required")
    runner = BootCheck(args.output)
    try:
        result = runner.run(
            args.approval,
            checkpoint=args.checkpoint,
            single_cpu=args.single_cpu_diagnostic,
        )
        print(canonical(result).decode(), flush=True)
        if not result["pass"]:
            raise Hold("base OS observations contain a failed check")
    except BaseException:
        if runner.started:
            try:
                runner.native(
                    "failure-display",
                    [
                        "controlvm",
                        VM,
                        "screenshotpng",
                        str(runner.root / "failure-display.png"),
                    ],
                    mutation=False,
                )
            except (Hold, OSError, subprocess.SubprocessError) as error:
                runner.store.event(
                    "failure-display-unavailable", {"error_type": type(error).__name__}
                )
        raise
    finally:
        runner.close()


if __name__ == "__main__":
    main()
