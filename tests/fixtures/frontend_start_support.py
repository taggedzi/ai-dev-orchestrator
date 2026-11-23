"""Synthetic input facts shared by startup tests; never native VM evidence."""

from uuid import uuid4

from research.validation import frontend_start as start
from research.validation.transfer_commands import canonical, digest


def bind(b, frame):
    b["caller"] = {"role": "controller", "process": b["caller"]["process"]}
    disk_sha = b["disk_evidence"]["pre_boot_disk_sha256"]
    files = {}
    for n, name in enumerate(("disk", "configuration"), 1):
        files[name] = {
            "state": "file",
            "bytes": 17,
            "sha256": disk_sha if name == "disk" else "b" * 64,
            "source_relative": "source/" + name,
            "backup_relative": "copy/" + name,
            "source_identity": {"device": 1, "inode": n},
            "backup_identity": {"device": 1, "inode": n + 10},
        }
    files["nvram"] = {
        "state": "absent",
        "source_relative": "source/nvram",
        "backup_relative": None,
    }
    backup = {
        "format": start.backup.records.RECEIPT_FORMAT,
        "status": "stopped-backup-reported-not-boot-authority",
        "backup_id": uuid4().hex,
        "role": b["role"],
        "target_vm_uuid": b["target"]["vm_uuid"],
        "source_disk_uuid": b["target"]["disk_uuid"],
        "source_poweroff": True,
        "independent": True,
        "never_attach": True,
        "files": files,
    }
    backup_raw = canonical(backup)
    b["backup"] = start.backup.records.binding(backup, digest(backup_raw))
    preboot = {
        "format": "mcli1-preboot-disk-v1",
        "run_nonce": b["run_nonce"],
        "target_vm_uuid": b["target"]["vm_uuid"],
        "disk_uuid": b["target"]["disk_uuid"],
        "disk_sha256": disk_sha,
        "state": "poweroff",
        "backup_receipt_sha256": digest(backup_raw),
    }
    preservation = {
        "format": "mcli1-source-preservation-v1",
        "run_nonce": b["run_nonce"],
        "target_vm_uuid": b["target"]["vm_uuid"],
        "source_disk_uuid": start.boot.transfer.EXECUTOR_DISK,
        "before_sha256": start.host.SOURCE_DISK_SHA,
        "after_sha256": start.host.SOURCE_DISK_SHA,
        "state": "poweroff",
    }
    b["disk_evidence"].update(
        pre_boot_receipt_sha256=digest(canonical(preboot)),
        source_preservation_receipt_sha256=digest(canonical(preservation)),
    )
    profile = {
        "status": "stopped-maintenance-profile-reported-not-boot-authority",
        "role": b["role"],
        "target_vm_uuid": b["target"]["vm_uuid"],
        "source_disk_uuid": b["target"]["disk_uuid"],
        "backup_receipt_sha256": digest(backup_raw),
        "disk_sha256": disk_sha,
        "nvram": {"state": "absent"},
        "configuration": {"state": "file", "bytes": 23, "sha256": "c" * 64},
        "machine_sha256": digest(frame["machine"]),
        "medium_sha256": digest(frame["medium"]),
        "VM_started": False,
        "native_boot_authorized": False,
        "network_enabled": False,
    }
    grant = start.draft(b["role"])
    grant.update(
        boot=b,
        environment_sha256=digest(canonical(start.frontend.frontend_environment())),
        profile_receipt_sha256=digest(canonical(profile)),
        approval={"native_run": "test:Python-surrogates-only-no-native-VM"},
    )
    return grant, [backup, preboot, preservation, profile]


class NoInputLocks:
    """Explicit fake filesystem boundary. Original-file locking is tested separately."""

    def __init__(self, *_args):
        pass

    def check(self):
        pass

    def close(self):
        pass
