"""Unarmed maintenance command preview and durable host admission checks.

No native transport is provided. Runtime callers must supply trusted observations
and a qualified live-supervisor probe; hashes bind evidence, not its truth.
"""

import argparse
import hashlib
import json
import os
import re
import time
from pathlib import Path
from uuid import UUID

from .fixture import canonical
from .guard_packages import WORKSPACE, paragraphs
from .maintenance_config import (
    PROPOSAL,
    PROPOSAL_SHA256,
    checked_profile,
    proposal,
    validate_dump,
)
from .offline_repo import description, file_digest, new_root, no_links, write_json
from .store import Hold

LOCAL = WORKSPACE / ".local/validation"
ISO_SHA256 = "e09f95fb365b3b87be9f6e7b8f7d1529ee596f09c4ea2fee1cf36ea239dd48d4"
MEDIA_SHA256 = "de9916a00044717b9b5d588cf71bd5d88f565fc675a668a6b9351394dec943b6"
PROFILE_SHA256 = "fef1a95fd7f80e5e4bf89aed1b29135508d7ce0035daa4c5df6a76171efbbf92"
STATUS_SHA256 = "b9f366f301a3ae82652a1bb983c905c53e325d78e44b831ed8da16a4176190b4"
TARGETS = {
    "executor": ("74129e9c-5a65-44fa-9d35-79d458dc4704", 2, 4096),
    "guard": ("0eceb37e-f216-45ed-817c-7cf2fca3a32a", 1, 1024),
}
EXECUTOR_DISK = "e832fc9c-23cc-40a8-8e66-fa0c624b8bd9"
FRESH_NS = 5 * 10**9
REQUEST_FIELDS = (
    "packet_sha256",
    "observations_sha256",
    "argv",
    "target_vm_uuid",
    "run_nonce",
    "generation",
    "owner_nonce",
    "expires_utc_ns",
    "expires_mono_ns",
    "admitted_mono_ns",
    "dispatch_until_utc_ns",
    "dispatch_until_mono_ns",
)


def require(condition, message):
    if not condition:
        raise Hold(message)


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def is_digest(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def is_uuid(value):
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except ValueError:
        return False


def load_policy():
    planned = proposal(PROPOSAL.read_bytes())
    profile = checked_profile(LOCAL / "maintenance-config-01", PROFILE_SHA256)
    raw = (LOCAL / "offline-repository-01/baseline/status").read_bytes()
    require(hashlib.sha256(raw).hexdigest() == STATUS_SHA256, "baseline status changed")
    versions = {
        r["Package"]: r["Version"]
        for r in paragraphs(raw.decode())
        if r.get("Status") == "install ok installed"
    }
    require(len(versions) == 480, "baseline inventory changed")
    return {"proposal": planned, "settings": profile["settings"], "baseline": versions}


def draft(role, journal_path=None):
    require(role in TARGETS, "unsupported maintenance role")
    return {
        "format": "mcli1-maintenance-dispatch-v1",
        "role": role,
        "run_nonce": None,
        "generation": None,
        "journal_path": journal_path
        or f".local/validation/maintenance-control-{role}-01/maintenance.sqlite",
        "target": {
            "vm_uuid": TARGETS[role][0],
            "disk_uuid": EXECUTOR_DISK if role == "executor" else None,
            "pre_boot_disk_sha256": None,
            "pre_boot_receipt_sha256": None,
            "dmi_uuid": None,
            "root_fs_uuid": None,
            "boot_id": None,
            "dvd_uuid": None,
            "media_device": None,
        },
        "inputs": {
            "proposal_sha256": PROPOSAL_SHA256,
            "iso_sha256": ISO_SHA256,
            "media_manifest_sha256": MEDIA_SHA256,
            "config_profile_sha256": PROFILE_SHA256,
            "admission_program_sha256": file_digest(Path(__file__)),
            "guest_preflight_program_sha256": None,
            "source_preservation_receipt_sha256": None,
        },
        "approval": dict.fromkeys(
            (
                "boot",
                "media_attachment",
                "installation",
                "target_binding",
                "backup",
                "source_preservation",
            )
        ),
        "backup": dict.fromkeys(
            (
                "source_disk_uuid",
                "disk_uuid",
                "disk_sha256",
                "configuration_sha256",
                "nvram_sha256",
                "receipt_sha256",
            )
        ),
        "lease": dict.fromkeys(("owner_nonce", "expires_utc_ns", "expires_mono_ns")),
    }


def missing(value, prefix=""):
    result = []
    for key, item in value.items():
        name = f"{prefix}.{key}" if prefix else key
        if isinstance(item, dict):
            result.extend(missing(item, name))
        elif item is None:
            result.append(name)
    return result


def journal(packet):
    name = packet["journal_path"]
    require(
        isinstance(name, str)
        and re.fullmatch(
            r"\.local/validation/[A-Za-z0-9_-]+/maintenance\.sqlite", name
        ),
        "journal must be a fixed maintenance file in a workspace run directory",
    )
    path = WORKSPACE / name
    no_links(path)
    return path.resolve()


def checked_packet(packet, external_sha):
    require(
        is_digest(external_sha) and digest(packet) == external_sha,
        "packet differs from external approval digest",
    )
    require(packet.get("role") in TARGETS, "unsupported maintenance role")
    expected = draft(packet["role"], packet.get("journal_path"))
    require(set(packet) == set(expected), "packet fields changed")
    for key in ("target", "inputs", "approval", "backup", "lease"):
        require(
            isinstance(packet[key], dict) and set(packet[key]) == set(expected[key]),
            "packet section changed",
        )
    require(
        packet["format"] == expected["format"] and not missing(packet),
        "maintenance packet remains unbound",
    )
    for key, value in expected["inputs"].items():
        require(is_digest(packet["inputs"][key]), "missing input or program digest")
        if value is not None:
            require(packet["inputs"][key] == value, "maintenance input cohort changed")
    target = packet["target"]
    require(
        target["vm_uuid"] == TARGETS[packet["role"]][0],
        "target is outside the selected fixture slot",
    )
    for key in (
        "vm_uuid",
        "disk_uuid",
        "dmi_uuid",
        "root_fs_uuid",
        "boot_id",
        "dvd_uuid",
    ):
        require(is_uuid(target[key]), "target UUID is unbound")
    require(
        is_digest(target["pre_boot_disk_sha256"])
        and is_digest(target["pre_boot_receipt_sha256"]),
        "stopped disk evidence is missing",
    )
    require(
        re.fullmatch(r"/dev/sr[0-9]", target["media_device"]) is not None,
        "unsupported optical device",
    )
    if packet["role"] == "executor":
        require(target["disk_uuid"] == EXECUTOR_DISK, "executor disk changed")
    else:
        require(target["disk_uuid"] != EXECUTOR_DISK, "guard aliases the source disk")
    for value in packet["approval"].values():
        require(
            isinstance(value, str)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", value),
            "missing scoped approval reference",
        )
    backup = packet["backup"]
    require(
        backup["source_disk_uuid"] == target["disk_uuid"]
        and is_uuid(backup["disk_uuid"]),
        "backup source or identity changed",
    )
    require(
        backup["disk_uuid"] not in (target["disk_uuid"], EXECUTOR_DISK),
        "backup must be an independent full disk",
    )
    require(
        all(is_digest(v) for k, v in backup.items() if k.endswith("sha256")),
        "backup disk/configuration/firmware evidence missing",
    )
    require(
        type(packet["generation"]) is int and packet["generation"] > 0,
        "invalid authority generation",
    )
    for nonce in (packet["run_nonce"], packet["lease"]["owner_nonce"]):
        require(
            isinstance(nonce, str) and re.fullmatch(r"[0-9a-f]{32}", nonce),
            "invalid run or supervisor nonce",
        )
    for key in ("expires_utc_ns", "expires_mono_ns"):
        require(type(packet["lease"][key]) is int, "invalid lease deadline")
    journal(packet)
    return packet


def fresh(observed, now):
    require(
        type(observed) is int and 0 <= now - observed <= FRESH_NS,
        "observation is stale or future-dated",
    )


def controls(observed, role, planned):
    require(
        type(observed["policy"].get("uid")) is int
        and type(observed["policy"].get("mode")) is int,
        "malformed policy ownership/mode",
    )
    units = set(
        planned["common_admin_masks_proposal"]
        + planned["roles"][role]["additional_admin_masks"]
    )
    require(set(observed["masks"]) == units, "persistent mask inventory changed")
    for row in observed["masks"].values():
        require(type(row.get("uid")) is int, "malformed mask owner")
        require(
            row
            == {
                "target": "/dev/null",
                "uid": 0,
                "active": "inactive",
                "helper_mask_state": False,
            },
            "mask or helper state failed",
        )
    require(
        observed["policy"]
        == {
            "sha256": planned["policy_rc_d_proposal"]["sha256"],
            "uid": 0,
            "mode": 0o755,
        },
        "policy-rc.d differs from the reviewed create-only policy",
    )
    require(
        observed["active_package_processes"] == [] and observed["snap_apps"] == [],
        "background package or snap activity remains",
    )
    require(
        observed["docker_socket_present"] is False
        and observed["protected_runtime_processes"] == [],
        "protected runtime or socket is active",
    )
    require(
        observed["operator_in_docker_group"] is False,
        "operator received Docker socket authority",
    )


def unit_command(packet, planned):
    nonce = packet["run_nonce"]
    args = [
        "/usr/bin/systemd-run",
        f"--unit=mcli1-maint-{nonce}.service",
        "--wait",
        "--no-ask-password",
        "--expand-environment=no",
    ]
    args.extend(
        f"--property={k}={v}" for k, v in planned["transaction_unit_properties"].items()
    )
    args += [
        f"--property=StandardOutput=append:/var/log/mcli1-maintenance/{nonce}.log",
        "--property=StandardError=inherit",
        "--property=StandardInput=null",
        "--property=UnsetEnvironment=" + " ".join(planned["forbidden_environment"]),
    ]
    args.extend(f"--setenv={k}={v}" for k, v in planned["environment"].items())
    return args + planned["roles"][packet["role"]]["proposed_install_argv"]


class MaintenanceAdmission:
    """Persist one conservative dispatch intent before a future transport sends."""

    def __init__(
        self, store, live_probe, wall_ns=time.time_ns, mono_ns=time.monotonic_ns
    ):
        self.store, self.live_probe = store, live_probe
        self.wall_ns, self.mono_ns = wall_ns, mono_ns
        database = store.db.execute("PRAGMA database_list").fetchone()["file"]
        require(bool(database), "maintenance journal cannot be ephemeral")
        require(callable(live_probe), "a qualified live-supervisor probe is required")
        require(
            store.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='lease'"
            ).fetchone()
            is not None,
            "outside-VM lease has not been prepared",
        )
        self.policy = load_policy()
        self.database = Path(database).resolve()
        store.db.execute(
            "CREATE TABLE IF NOT EXISTS maintenance_dispatch (singleton INTEGER PRIMARY KEY CHECK(singleton=1), operation TEXT, packet_sha TEXT, request_sha TEXT, state TEXT)"
        )

    def _lease(self, packet, pulse, now, mono):
        self.store.active(packet["generation"])
        row = self.store.db.execute("SELECT * FROM lease WHERE singleton=1").fetchone()
        require(
            row is not None and row["state"] == "armed", "outside-VM lease is not armed"
        )
        require(
            row["target"] == packet["target"]["vm_uuid"] == pulse["target_vm_uuid"],
            "supervisor targets differ",
        )
        require(
            pulse["owner_nonce"] == packet["lease"]["owner_nonce"]
            and pulse["live"] is True,
            "supervisor owner is not live",
        )
        fresh(pulse["observed_mono_ns"], mono)
        for key, column in (
            ("expires_utc_ns", "expires_ns"),
            ("expires_mono_ns", "expires_mono_ns"),
        ):
            require(
                packet["lease"][key] == row[column] == pulse[key],
                "original supervisor deadline changed",
            )
        require(
            row["armed_ns"] <= now and row["armed_mono_ns"] <= mono,
            "clock moved before lease arm",
        )
        require(
            row["expires_ns"] - row["armed_ns"] <= 600 * 10**9,
            "VM authority exceeds ten minutes",
        )
        require(
            row["expires_mono_ns"] - row["armed_mono_ns"] <= 600 * 10**9,
            "monotonic VM authority exceeds ten minutes",
        )
        minimum = (
            self.policy["proposal"]["time_bounds_proposal"][
                "minimum_host_remaining_before_transaction_seconds"
            ]
            * 10**9
        )
        require(
            min(row["expires_ns"] - now, row["expires_mono_ns"] - mono) >= minimum,
            "insufficient original lease budget",
        )

    def admit(self, packet, external_sha, observed):
        try:
            return self._admit(packet, external_sha, observed)
        except Hold:
            raise
        except (KeyError, TypeError, AttributeError, ValueError) as exc:
            raise Hold("malformed maintenance packet or observation") from exc

    def _admit(self, packet, external_sha, observed):
        checked_packet(packet, external_sha)
        require(self.database == journal(packet), "journal path was rebound")
        require(
            len(canonical(observed)) <= 2 * 1024**2, "observation frame is too large"
        )
        role, target = packet["role"], packet["target"]
        planned = self.policy["proposal"]
        host, guest = observed["host"], observed["guest"]
        require(
            observed["run_nonce"] == packet["run_nonce"],
            "observation belongs to another attempt",
        )
        machine = host["machine"]
        require(
            machine.get("UUID") == target["vm_uuid"]
            and machine.get("VMState") == "running",
            "active VM identity/state changed",
        )
        require(
            (machine.get("cpus"), machine.get("memory"))
            == tuple(str(v) for v in TARGETS[role][1:]),
            "VM CPU/memory profile changed",
        )
        require(
            all(machine.get(f"nic{i}") == "none" for i in range(1, 9)),
            "a VM NIC is enabled",
        )
        require(
            not any(k.startswith("SharedFolderName") for k in machine),
            "host shared folder present",
        )
        require(
            host["hard_disk_uuids"] == [target["disk_uuid"]]
            and machine.get("SATA-ImageUUID-0-0") == target["disk_uuid"],
            "disk binding or disk count changed",
        )
        require(
            host["dvd_uuid"] == target["dvd_uuid"] and host["iso_sha256"] == ISO_SHA256,
            "DVD identity changed",
        )
        for key in ("pre_boot_disk_sha256", "pre_boot_receipt_sha256"):
            require(host[key] == target[key], "stopped-image evidence changed")
        require(
            host["backup_receipt_sha256"] == packet["backup"]["receipt_sha256"],
            "backup receipt changed",
        )
        require(
            host["source_preservation_receipt_sha256"]
            == packet["inputs"]["source_preservation_receipt_sha256"],
            "source-preservation evidence changed",
        )
        require(
            guest["platform"] == "linux"
            and type(guest["uid"]) is int
            and guest["uid"] == 0,
            "maintenance must target guest root",
        )
        require(
            not any(t in guest["kernel_release"].lower() for t in ("microsoft", "wsl")),
            "WSL is not an installation target",
        )
        require(
            all(guest[k] == target[k] for k in ("dmi_uuid", "root_fs_uuid", "boot_id")),
            "guest boot/root identity changed",
        )
        require(
            guest["root_fs_type"] == "ext4" and guest["interfaces"] == ["lo"],
            "guest root or interface profile changed",
        )
        mount = guest["media_mount"]
        require(
            mount["target"] == "/media/mcli1-maintenance"
            and mount["source"] == target["media_device"]
            and mount["fstype"] == "iso9660",
            "media mount changed",
        )
        require(
            {"ro", "nosuid", "nodev", "noexec"} <= set(mount["options"])
            and not {"rw", "suid", "dev", "exec"} & set(mount["options"]),
            "media mount flags changed",
        )
        require(
            guest["media_manifest_sha256"] == MEDIA_SHA256
            and guest["verified_media_files"] == 142,
            "complete mounted media verification missing",
        )
        require(
            guest["status_sha256"] == STATUS_SHA256
            and guest["audit_stdout"] == guest["audit_stderr"] == "",
            "guest baseline/audit changed",
        )
        require(
            guest["preflight_program_sha256"]
            == packet["inputs"]["guest_preflight_program_sha256"],
            "guest preparer program changed",
        )
        validate_dump(guest["apt_dump"], self.policy["settings"])
        require(
            guest["maintenance_unit_exists"] is False,
            "maintenance unit name already exists",
        )
        require(
            guest["log_directory"]
            == {
                "path": "/var/log/mcli1-maintenance",
                "uid": 0,
                "mode": 0o700,
                "symlink": False,
            },
            "protected log directory missing",
        )
        require(
            type(guest["log_directory"]["uid"]) is int, "malformed log directory owner"
        )
        for name, minimum in planned["resource_preflight_proposal"].items():
            if name == "disk_resize_allowed":
                continue
            field = name.removeprefix("minimum_")
            require(
                type(guest[field]) is int and guest[field] >= minimum,
                "insufficient measured guest free space",
            )
        controls(guest, role, planned)
        command = unit_command(packet, planned)
        pulse = self.live_probe()
        marker = self.database.with_name("dispatch.intent.json")
        request = {
            "packet_sha256": external_sha,
            "observations_sha256": digest(observed),
            "argv": command,
            "target_vm_uuid": target["vm_uuid"],
            "run_nonce": packet["run_nonce"],
            "generation": packet["generation"],
            **packet["lease"],
        }
        operation = "maintenance:" + packet["run_nonce"]
        with self.store.transaction():
            now, mono = self.wall_ns(), self.mono_ns()
            self._lease(packet, pulse, now, mono)
            fresh(observed["observed_mono_ns"], mono)
            margin = (
                planned["time_bounds_proposal"][
                    "minimum_host_remaining_before_transaction_seconds"
                ]
                * 10**9
            )
            request.update(
                admitted_mono_ns=mono,
                dispatch_until_utc_ns=packet["lease"]["expires_utc_ns"] - margin,
                dispatch_until_mono_ns=min(
                    packet["lease"]["expires_mono_ns"] - margin,
                    observed["observed_mono_ns"] + FRESH_NS,
                    pulse["observed_mono_ns"] + FRESH_NS,
                ),
            )
            require(not marker.exists(), "dispatch marker exists; reconcile read-only")
            require(
                self.store.db.execute("SELECT 1 FROM maintenance_dispatch").fetchone()
                is None,
                "maintenance already admitted; reconcile read-only",
            )
            require(
                self.store.db.execute(
                    "SELECT 1 FROM operations WHERE state='possible-send' OR id=?",
                    (operation,),
                ).fetchone()
                is None,
                "earlier mutation is unresolved or already issued",
            )
            no_links(marker)
            with marker.open("xb") as output:
                output.write(
                    canonical(
                        {**request, "operation": operation, "created_utc_ns": now}
                    )
                )
                output.flush()
                os.fsync(output.fileno())
            self._lease(packet, pulse, self.wall_ns(), self.mono_ns())
            fresh(observed["observed_mono_ns"], self.mono_ns())
            # A marker survives an interrupted transaction conservatively; never remove it.
            self.store.db.execute(
                "INSERT INTO operations VALUES(?,?,?,'possible-send',NULL,NULL)",
                (operation, digest(request), packet["generation"]),
            )
            self.store.db.execute(
                "INSERT INTO maintenance_dispatch VALUES(1,?,?,?,'possible-send')",
                (operation, external_sha, digest(request)),
            )
            self.store._event(
                "maintenance-dispatch-intent",
                {
                    "operation": operation,
                    "packet_sha256": external_sha,
                    "request_sha256": digest(request),
                    "observations_sha256": digest(observed),
                },
            )
        return {
            **request,
            "operation": operation,
            "state": "possible-send",
            "native_dispatch_performed": False,
        }

    def invoke(self, ticket, sender):
        """One bounded handoff point; a concrete native adapter is still required."""
        require(
            set(ticket)
            == set(REQUEST_FIELDS)
            | {"operation", "state", "native_dispatch_performed"},
            "dispatch ticket fields changed",
        )
        request = {k: ticket[k] for k in REQUEST_FIELDS}
        frozen = json.loads(canonical(request))
        require(callable(sender), "a reviewed bounded transport is required")
        pulse = self.live_probe()
        with self.store.transaction():
            row = self.store.db.execute("SELECT * FROM maintenance_dispatch").fetchone()
            require(
                row is not None
                and row["operation"] == ticket["operation"]
                and row["request_sha"] == digest(frozen),
                "dispatch ticket differs from durable intent",
            )
            require(
                row["state"] == "possible-send",
                "transport already entered; reconcile read-only",
            )
            operation = self.store.db.execute(
                "SELECT * FROM operations WHERE id=?", (row["operation"],)
            ).fetchone()
            require(
                operation is not None
                and operation["state"] == "possible-send"
                and operation["request_hash"] == row["request_sha"]
                and operation["generation"] == frozen["generation"],
                "operation intent changed before transport",
            )
            self.store.active(frozen["generation"])
            lease = self.store.db.execute(
                "SELECT * FROM lease WHERE singleton=1"
            ).fetchone()
            require(
                lease["state"] == "armed"
                and lease["target"] == frozen["target_vm_uuid"],
                "supervisor no longer owns target",
            )
            require(
                lease["expires_ns"] == frozen["expires_utc_ns"]
                and lease["expires_mono_ns"] == frozen["expires_mono_ns"],
                "supervisor deadline changed",
            )
            require(
                pulse["live"] is True
                and pulse["owner_nonce"] == frozen["owner_nonce"]
                and pulse["target_vm_uuid"] == frozen["target_vm_uuid"],
                "supervisor owner lost before transport",
            )
            require(
                pulse["expires_utc_ns"] == frozen["expires_utc_ns"]
                and pulse["expires_mono_ns"] == frozen["expires_mono_ns"],
                "live supervisor deadline changed",
            )
            now, mono = self.wall_ns(), self.mono_ns()
            fresh(pulse["observed_mono_ns"], mono)
            require(
                lease["armed_ns"] <= now <= frozen["dispatch_until_utc_ns"]
                and frozen["admitted_mono_ns"]
                <= mono
                <= frozen["dispatch_until_mono_ns"],
                "dispatch ticket is stale or clock moved",
            )
            self.store.db.execute(
                "UPDATE maintenance_dispatch SET state='transport-entered'"
            )
            self.store._event(
                "maintenance-transport-intent",
                {"operation": ticket["operation"], "request_sha256": digest(frozen)},
            )
        try:
            # Commit/fsync time also counts; never refresh the original ticket.
            require(
                self.wall_ns() <= frozen["dispatch_until_utc_ns"]
                and self.mono_ns() <= frozen["dispatch_until_mono_ns"],
                "ticket expired while committing transport intent",
            )
            response = sender(frozen)
            require(
                isinstance(response, bytes) and len(response) <= 1024**2,
                "transport acknowledgement is malformed or oversized",
            )
            with self.store.transaction():
                self.store.db.execute(
                    "UPDATE maintenance_dispatch SET state='transport-returned'"
                )
                self.store._event(
                    "maintenance-transport-returned",
                    {
                        "operation": ticket["operation"],
                        "response_sha256": hashlib.sha256(response).hexdigest(),
                        "postconditions_still_required": True,
                    },
                )
            return response
        except Exception as exc:
            self.store.fence(
                "maintenance handoff is uncertain; stop and reconcile without replay"
            )
            raise Hold(
                "maintenance transport acknowledgement unknown; stop/reconcile"
            ) from exc

    def record_result(self, packet, result):
        """Validate reported postconditions and independent stop, not an exit-code shortcut."""
        row = self.store.db.execute("SELECT * FROM maintenance_dispatch").fetchone()
        require(
            row is not None and row["packet_sha"] == digest(packet),
            "result has no matching original intent",
        )
        require(
            row["state"]
            in ("possible-send", "transport-entered", "transport-returned"),
            "result already recorded; reconcile read-only",
        )
        try:
            marker = json.loads(
                self.database.with_name("dispatch.intent.json").read_bytes()
            )
            original = {k: marker[k] for k in REQUEST_FIELDS}
            require(digest(original) == row["request_sha"], "dispatch marker changed")
            target = packet["target"]
            require(
                result["vm_uuid"] == target["vm_uuid"]
                and result["run_nonce"] == packet["run_nonce"]
                and result["boot_id"] == target["boot_id"],
                "result target/nonce/boot changed",
            )
            require(
                type(result["unit_exit"]) is int and result["unit_exit"] == 0,
                "maintenance unit failed",
            )
            require(
                result["audit_stdout"] == result["audit_stderr"] == ""
                and result["unconfigured_packages"] == [],
                "package audit/state is incomplete",
            )
            wanted = dict(self.policy["baseline"])
            for pin in self.policy["proposal"]["roles"][packet["role"]]["pins"]:
                name, version = pin.split("=", 1)
                wanted[name] = version
            require(
                result["installed_versions"] == wanted
                and is_digest(result["installed_status_sha256"]),
                "installed inventory is not the exact role result",
            )
            controls(result, packet["role"], self.policy["proposal"])
            fresh(result["observed_mono_ns"], self.mono_ns())
            require(
                type(result["unit_finished_host_mono_ns"]) is int
                and original["admitted_mono_ns"]
                <= result["unit_finished_host_mono_ns"]
                <= min(self.mono_ns(), packet["lease"]["expires_mono_ns"]),
                "unit completion exceeded original authority",
            )
            stop = result["independent_stop"]
            require(
                stop["vm_uuid"] == target["vm_uuid"]
                and stop["state"] == "poweroff"
                and is_digest(stop["receipt_sha256"]),
                "independent VM stop is unproven",
            )
            require(
                stop["nics"] == ["none"] * 8
                and stop["shared_folders"] == []
                and stop["hard_disk_uuids"] == [target["disk_uuid"]]
                and stop["dvd_uuid"] == target["dvd_uuid"],
                "stopped target isolation/storage changed",
            )
            fresh(stop["observed_mono_ns"], self.mono_ns())
            require(
                stop["observed_mono_ns"]
                <= packet["lease"]["expires_mono_ns"] + 10 * 10**9,
                "VM stop was later than the original deadline and stop bound",
            )
            require(
                type(stop["elapsed_ns"]) is int
                and 0 <= stop["elapsed_ns"] <= 10 * 10**9,
                "external stop exceeded its bound",
            )
            require(
                stop["observed_mono_ns"] - stop["elapsed_ns"]
                >= result["unit_finished_host_mono_ns"],
                "stop receipt precedes unit completion",
            )
            self.store.receipt(row["operation"], 200, canonical(result))
            self.store.fence("maintenance stop and postconditions recorded")
            with self.store.transaction():
                self.store.db.execute(
                    "UPDATE maintenance_dispatch SET state='postconditions-and-stop-reported'"
                )
                self.store._event(
                    "maintenance-postconditions-reported",
                    {
                        "operation": row["operation"],
                        "result_sha256": digest(result),
                        "native_qualification_required": True,
                    },
                )
        except (ValueError, KeyError, TypeError, OSError) as exc:
            self.store.fence(
                "maintenance result incomplete or conflicting; retain possible-send"
            )
            raise Hold(
                "maintenance result incomplete or conflicting; stop/reconciliation required"
            ) from exc


def prepare(role, output):
    planned = load_policy()["proposal"]
    require(
        description(LOCAL / "maintenance-media-01/maintenance.iso")
        == {"bytes": 599830528, "sha256": ISO_SHA256},
        "maintenance ISO changed",
    )
    root = new_root(output)
    packet = draft(
        role, (root / "maintenance.sqlite").relative_to(WORKSPACE).as_posix()
    )
    try:
        checked_packet(packet, digest(packet))
    except Hold as exc:
        refusal = str(exc)
    else:
        raise Hold("an unarmed preview unexpectedly passed admission")
    write_json(root / "packet.json", packet)
    (root / "maintenance_runner.py").write_bytes(Path(__file__).read_bytes())
    result = {
        "status": "unarmed-preview",
        "role": role,
        "packet_sha256": digest(packet),
        "packet_file": description(root / "packet.json"),
        "missing_bindings": missing(packet),
        "native_calls": 0,
        "journal_created": False,
        "transport_available": False,
        "admission_refusal": refusal,
        "unit_properties": {
            **planned["transaction_unit_properties"],
            "StandardOutput": "append:/var/log/mcli1-maintenance/{run_nonce}.log",
            "StandardError": "inherit",
            "StandardInput": "null",
            "UnsetEnvironment": " ".join(planned["forbidden_environment"]),
        },
        "environment": planned["environment"],
        "install_argv": planned["roles"][role]["proposed_install_argv"],
    }
    write_json(root / "preview.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=tuple(TARGETS), default="guard")
    parser.add_argument("--prepare")
    args = parser.parse_args()
    if args.prepare:
        result = prepare(args.role, args.prepare)
    else:
        packet = draft(args.role)
        result = {
            "status": "unarmed-preview",
            "packet": packet,
            "missing_bindings": missing(packet),
            "transport_available": False,
        }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
