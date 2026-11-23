"""Explicit bindings for unattached, byte-for-byte stopped-VM backup files."""

import re

from .store import Hold

BINDING_FORMAT = "mcli1-file-backup-binding-v2"
RECEIPT_FORMAT = "mcli1-stopped-file-backup-v2"


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


def checked_binding(value, target_disk):
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
        and value["format"] == BINDING_FORMAT,
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
    return value


def binding(receipt, receipt_sha):
    files = receipt["files"]
    nvram = {
        k: files["nvram"][k]
        for k in ("state", "bytes", "sha256")
        if k in files["nvram"]
    }
    value = {
        "format": BINDING_FORMAT,
        "backup_id": receipt["backup_id"],
        "source_disk_uuid": receipt["source_disk_uuid"],
        "disk_bytes": files["disk"]["bytes"],
        "disk_sha256": files["disk"]["sha256"],
        "configuration_sha256": files["configuration"]["sha256"],
        "nvram": nvram,
        "receipt_sha256": receipt_sha,
    }
    return checked_binding(value, receipt["source_disk_uuid"])


def checked_receipt(receipt, receipt_sha, grant):
    """Check pinned facts; fresh filesystem verification is a separate operation."""
    value = checked_binding(grant["backup"], grant["target"]["disk_uuid"])
    require(
        receipt.get("format") == RECEIPT_FORMAT
        and receipt.get("status") == "stopped-backup-reported-not-boot-authority"
        and receipt.get("source_poweroff") is True
        and receipt.get("independent") is True
        and receipt.get("never_attach") is True
        and receipt.get("target_vm_uuid") == grant["target"]["vm_uuid"]
        and receipt.get("role") == grant["role"]
        and binding(receipt, receipt_sha) == value,
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
