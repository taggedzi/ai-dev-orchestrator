"""Explicit bindings for unattached, byte-for-byte stopped-VM backup files."""

import re

from . import recovery_records as recovery_model
from .store import Hold

BINDING_FORMAT = "mcli1-file-backup-binding-v2"
RECEIPT_FORMAT = "mcli1-stopped-file-backup-v2"
RECOVERY_BINDING_FORMAT = "mcli1-file-backup-binding-v3"
RECOVERY_RECEIPT_FORMAT = "mcli1-aborted-file-backup-v3"


def require(value, message):
    if not value:
        raise Hold(message)


def hash_value(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)


def nvram_record(value):
    require(isinstance(value, dict), "backup NVRAM state is unbound")
    if value.get("state") == "absent":
        require(set(value) == {"state"}, "absent NVRAM cannot contain file facts")
    else:
        require(
            set(value) == {"state", "bytes", "sha256"}
            and value["state"] == "file"
            and type(value["bytes"]) is int
            and 0 < value["bytes"] <= 16 * 1024**2
            and hash_value(value["sha256"]),
            "backup NVRAM file is unbound",
        )


def checked_binding(value, target_disk, *, recovery=None):
    context = recovery_model.checked(recovery) if recovery is not None else None
    extra = {"source_machine_state", "recovery_context_sha256"} if context else set()
    require(
        isinstance(value, dict)
        and set(value)
        == {
            "format",
            "backup_id",
            "source_disk_uuid",
            "disk_bytes",
            "disk_sha256",
            "configuration_sha256",
            "nvram",
            "receipt_sha256",
        }
        | extra
        and value["format"] == (RECOVERY_BINDING_FORMAT if context else BINDING_FORMAT),
        "file backup binding fields differ",
    )
    require(
        isinstance(value["backup_id"], str)
        and re.fullmatch(r"[0-9a-f]{32}", value["backup_id"])
        and value["source_disk_uuid"] == target_disk,
        "file backup target/identity differs",
    )
    require(
        type(value["disk_bytes"]) is int
        and 0 < value["disk_bytes"] <= 36 * 1024**3
        and all(
            hash_value(value[k])
            for k in ("disk_sha256", "configuration_sha256", "receipt_sha256")
        ),
        "file backup byte/hash evidence is unbound",
    )
    nvram_record(value["nvram"])
    if context:
        require(
            target_disk == recovery_model.GUARD_DISK
            and value["source_machine_state"] == "aborted"
            and value["recovery_context_sha256"]
            == recovery_model.context_sha256(context)
            and value["disk_bytes"] == context["files"]["disk"]["bytes"]
            and value["disk_sha256"] == context["files"]["disk"]["sha256"]
            and value["configuration_sha256"]
            == context["files"]["configuration"]["sha256"]
            and value["nvram"] == context["files"]["nvram"],
            "recovery backup and exact guard context differ",
        )
    return value


def binding(receipt, receipt_sha, *, recovery=None):
    require(
        receipt["format"]
        == (RECOVERY_RECEIPT_FORMAT if recovery is not None else RECEIPT_FORMAT),
        "backup receipt provenance format differs",
    )
    files = receipt["files"]
    nvram = {
        k: files["nvram"][k]
        for k in ("state", "bytes", "sha256")
        if k in files["nvram"]
    }
    value = {
        "format": RECOVERY_BINDING_FORMAT if recovery is not None else BINDING_FORMAT,
        "backup_id": receipt["backup_id"],
        "source_disk_uuid": receipt["source_disk_uuid"],
        "disk_bytes": files["disk"]["bytes"],
        "disk_sha256": files["disk"]["sha256"],
        "configuration_sha256": files["configuration"]["sha256"],
        "nvram": nvram,
        "receipt_sha256": receipt_sha,
    }
    if recovery is not None:
        value.update(
            source_machine_state="aborted",
            recovery_context_sha256=recovery_model.context_sha256(recovery),
        )
    return checked_binding(value, receipt["source_disk_uuid"], recovery=recovery)


def checked_receipt(receipt, receipt_sha, grant, *, recovery=None):
    """Check pinned facts; fresh filesystem verification is a separate operation."""
    value = checked_binding(
        grant["backup"], grant["target"]["disk_uuid"], recovery=recovery
    )
    if recovery is None:
        source_valid = (
            receipt.get("format") == RECEIPT_FORMAT
            and receipt.get("source_poweroff") is True
            and receipt.get("status") == "stopped-backup-reported-not-boot-authority"
        )
    else:
        source_valid = (
            receipt.get("format") == RECOVERY_RECEIPT_FORMAT
            and receipt.get("status") == "aborted-backup-reported-not-boot-authority"
            and "source_poweroff" not in receipt
            and receipt.get("source_machine_state") == "aborted"
            and receipt.get("source_session_state") == "Unlocked"
            and type(receipt.get("source_session_pid")) is int
            and receipt["source_session_pid"] == 0
            and receipt.get("recovery_context_sha256")
            == recovery_model.context_sha256(recovery)
            and receipt.get("role") == "guard"
            and grant["role"] == "guard"
            and receipt.get("target_vm_uuid") == recovery_model.GUARD_VM
        )
    require(
        source_valid
        and receipt.get("independent") is True
        and receipt.get("never_attach") is True
        and receipt.get("target_vm_uuid") == grant["target"]["vm_uuid"]
        and receipt.get("role") == grant["role"]
        and binding(receipt, receipt_sha, recovery=recovery) == value,
        "stopped file backup receipt differs",
    )
    require(
        value["disk_sha256"] == grant["disk_evidence"]["pre_boot_disk_sha256"],
        "file backup and preboot image differ",
    )
    for label in ("disk", "configuration", "nvram"):
        row = receipt["files"][label]
        if row["state"] == "file":
            require(
                row["source_identity"] != row["backup_identity"]
                and row["source_relative"] != row["backup_relative"],
                "backup file aliases its source",
            )
