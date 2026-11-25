"""Prepare/apply exact stopped-only maintenance settings. Never starts a VM."""

import argparse
import json
import os
import time
from pathlib import Path

from . import boot_preconditions as boot
from . import maintenance_host as host
from . import maintenance_transfer as transfer
from . import stopped_backup as backup
from .offline_repo import new_root, write_json
from .transfer_commands import canonical, digest

ROOT = backup.ROOT
require = backup.require
SOURCES = {
    **backup.SOURCES,
    "maintenance_profile.py": Path(__file__),
    "boot_preconditions.py": Path(boot.__file__),
    "maintenance_transfer.py": Path(transfer.__file__),
}
SOURCE_EPOCH = {name: digest(path.read_bytes()) for name, path in SOURCES.items()}


def commands(role):
    slot = backup.SLOTS[role]
    vm = slot["vm_uuid"]
    result = []
    if role == "guard":
        result.append(["storagectl", vm, "--name", "SATA", "--portcount", "4"])
    args = ["modifyvm", vm]
    if role == "executor":
        # The x2APIC setter also changes APIC; restore ordinary APIC last.
        args += ["--x86-x2apic", "off", "--apic", "on"]
    args += [
        "--uart1",
        "0x3F8",
        "4",
        "--uart-mode1",
        "server",
        "\\\\.\\pipe\\mcli1-maint-" + vm,
    ]
    result.append(args)
    return result


def receipt_path(role):
    return backup.safe(
        ROOT / (".local/validation/stopped-backup-" + role + "-01/receipt.json")
    )


def draft(role):
    raw = receipt_path(role).read_bytes()
    receipt = host.object_bytes(raw)
    return {
        "format": "mcli1-stopped-maintenance-profile-v1",
        "role": role,
        "target_vm_uuid": backup.SLOTS[role]["vm_uuid"],
        "source_disk_uuid": backup.SLOTS[role]["disk_uuid"],
        "backup_receipt_sha256": digest(raw),
        "initial_machine_sha256": receipt["last_observation"]["machine_sha256"],
        "initial_medium_sha256": receipt["last_observation"]["medium_sha256"],
        "initial_configuration_sha256": receipt["files"]["configuration"]["sha256"],
        "disk_sha256": receipt["files"]["disk"]["sha256"],
        "commands": commands(role),
        "start_vm": False,
        "install_packages": False,
        "enable_network": False,
        "sources": dict(SOURCE_EPOCH),
    }


def checked(raw, sha):
    require(
        type(raw) is bytes and digest(raw) == sha, "maintenance profile digest differs"
    )
    plan = host.object_bytes(raw)
    require(
        set(plan)
        == {
            "format",
            "role",
            "target_vm_uuid",
            "source_disk_uuid",
            "backup_receipt_sha256",
            "initial_machine_sha256",
            "initial_medium_sha256",
            "initial_configuration_sha256",
            "disk_sha256",
            "commands",
            "start_vm",
            "install_packages",
            "enable_network",
            "sources",
        }
        and plan["format"] == "mcli1-stopped-maintenance-profile-v1"
        and plan["role"] in backup.SLOTS,
        "maintenance profile fields differ",
    )
    slot = backup.SLOTS[plan["role"]]
    require(
        plan["target_vm_uuid"] == slot["vm_uuid"]
        and plan["source_disk_uuid"] == slot["disk_uuid"]
        and plan["disk_sha256"] == slot["disk_sha256"]
        and plan["commands"] == commands(plan["role"])
        and all(
            plan[k] is False for k in ("start_vm", "install_packages", "enable_network")
        ),
        "maintenance profile scope expanded",
    )
    require(
        all(
            backup.records.hash_value(plan[k])
            for k in (
                "backup_receipt_sha256",
                "initial_machine_sha256",
                "initial_medium_sha256",
                "initial_configuration_sha256",
                "disk_sha256",
            )
        ),
        "maintenance profile evidence unbound",
    )
    require(
        plan["sources"]
        == SOURCE_EPOCH
        == {n: digest(p.read_bytes()) for n, p in SOURCES.items()},
        "maintenance profile source cohort changed",
    )
    return plan


def stopped(plan, frame, *, final=False, ports_only=False):
    require(
        0 <= time.monotonic_ns() - frame["observed_mono_ns"] <= 5 * 10**9,
        "maintenance profile observation is stale",
    )
    fields = host.machine_fields(frame["machine"])
    paths = backup.source_paths(plan["role"])
    medium = host.medium_fields(frame["medium"])
    require(
        fields["UUID"] == fields["hardwareuuid"] == plan["target_vm_uuid"]
        and fields["VMState"] == "poweroff"
        and medium["UUID"] == plan["source_disk_uuid"]
        and medium["State"] == "created"
        and medium["Parent UUID"] == "base"
        and digest(frame["medium"]) == plan["initial_medium_sha256"],
        "maintenance target is not the fixed stopped base disk",
    )
    require(
        backup.file_state(paths["disk"])["sha256"] == plan["disk_sha256"],
        "maintenance source disk changed",
    )
    if final or ports_only:
        expected = transfer.expected_host(
            {"role": plan["role"], "target": {"disk_uuid": plan["source_disk_uuid"]}}
        )
        expected["state"] = "poweroff"
        if ports_only:
            expected.update(uart_pipe=None, uart_server=False)
        require(
            host.machine_profile(frame["machine"]) == expected,
            "maintenance stopped profile postconditions differ",
        )
        require(
            all(fields.get(k) == v for k, v in boot.BOOT_FIELDS.items()),
            "maintenance firmware/boot policy differs",
        )
    else:
        require(
            digest(frame["machine"]) == plan["initial_machine_sha256"]
            and backup.file_state(paths["configuration"])["sha256"]
            == plan["initial_configuration_sha256"],
            "maintenance initial configuration changed",
        )
    return fields


def run_command(args, gate):
    require(
        not os.environ.get("VBOX_USER_HOME")
        and digest(backup.native.VBOX.read_bytes()) == backup.owner.stop.EXE_SHA,
        "maintenance hypervisor executable/root changed",
    )
    return backup.native._run(
        backup.native.VBOX,
        args,
        time.time_ns() + 4 * 10**9,
        time.monotonic_ns() + 4 * 10**9,
        before_resume=gate,
    )


def apply(raw, sha, output, approval, probe=backup.observe, runner=run_command):
    plan = checked(raw, sha)
    require(
        isinstance(approval, str) and 0 < len(approval) <= 256,
        "stopped configuration approval is unbound",
    )
    role = plan["role"]
    marker = backup.safe(ROOT / ".local/validation/profile-intents" / role)
    require(not marker.exists(), "profile intent exists; reconcile without replay")
    raw_backup = receipt_path(role).read_bytes()
    binding = backup.verify_files(raw_backup, plan["backup_receipt_sha256"])
    require(
        binding["source_disk_uuid"] == plan["source_disk_uuid"]
        and binding["disk_sha256"] == plan["disk_sha256"],
        "profile backup target differs",
    )
    before = probe(role)
    stopped(plan, before)
    root = new_root(output)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.mkdir(exist_ok=False)
    backup.owner.stop.write_once(
        marker / "intent.json",
        canonical(
            {
                "plan_sha256": sha,
                "approval": approval,
                "commands": plan["commands"],
                "state": "possible-configuration-no-boot-authority",
                "output": str(root),
            }
        ),
    )
    (root / "plan.json").write_bytes(raw)
    results = []
    disk_path = backup.source_paths(role)["disk"]
    with backup.locked_source(disk_path):
        for index, args in enumerate(plan["commands"]):
            prior = probe(role)
            stopped(plan, prior, ports_only=index > 0)
            intent_raw = canonical({"argv": args, "plan_sha256": sha, "index": index})
            backup.owner.stop.write_once(root / f"step-{index}.intent.json", intent_raw)

            def gate(pid, step=index, expected=intent_raw, argv=tuple(args)):
                checked(raw, sha)
                require(
                    (root / f"step-{step}.intent.json").read_bytes() == expected,
                    "profile command intent changed before resume",
                )
                write_json(
                    root / f"step-{step}.process.json", {"pid": pid, "argv": argv}
                )

            result = runner(args, gate)
            for kind in ("stdout", "stderr"):
                (root / f"step-{index}.{kind}").write_bytes(result[kind])
            row = {k: v for k, v in result.items() if k not in {"stdout", "stderr"}}
            write_json(root / f"step-{index}.result.json", row)
            results.append(row)
            require(
                result["exit"] == 0 and result["job_active_processes"] == 0,
                "profile command failed or remains uncertain; no retry",
            )
        after = probe(role)
        stopped(plan, after, final=True)
        checked(raw, sha)
        configuration = backup.file_state(backup.source_paths(role)["configuration"])
        nvram = backup.file_state(backup.source_paths(role)["nvram"])
        require(nvram == binding["nvram"], "maintenance NVRAM changed unexpectedly")
        result = {
            "status": "stopped-maintenance-profile-reported-not-boot-authority",
            "role": role,
            "target_vm_uuid": plan["target_vm_uuid"],
            "source_disk_uuid": plan["source_disk_uuid"],
            "disk_sha256": plan["disk_sha256"],
            "configuration": configuration,
            "nvram": nvram,
            "backup_receipt_sha256": plan["backup_receipt_sha256"],
            "plan_sha256": sha,
            "approval": approval,
            "commands": results,
            "machine_sha256": digest(after["machine"]),
            "medium_sha256": digest(after["medium"]),
            "VM_started": False,
            "network_enabled": False,
            "native_boot_authorized": False,
        }
        for label, frame in (("before", before), ("after", after)):
            for kind in ("machine", "medium"):
                (root / (label + "-" + kind + ".stdout")).write_bytes(frame[kind])
        backup.owner.publish(root / "receipt.json", canonical(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=tuple(backup.SLOTS), default="guard")
    parser.add_argument("--apply", metavar="OUTPUT")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--plan-sha256")
    parser.add_argument("--approval")
    args = parser.parse_args()
    if args.apply:
        require(
            args.plan is not None and args.plan_sha256 is not None,
            "apply requires exact reviewed plan bytes/hash",
        )
        result = apply(
            args.plan.read_bytes(), args.plan_sha256, args.apply, args.approval
        )
    else:
        result = {
            "status": "stopped-maintenance-profile-preview",
            "native_calls": 0,
            "plan": draft(args.role),
        }
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
