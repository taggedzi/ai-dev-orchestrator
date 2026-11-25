"""Prepared boot admission checks. No native-start command or dispatch permit.

Live original-owner proof, stopped configuration and backup bindings must agree.
Provider start-task settlement remains a separate prerequisite for activation.
"""

import argparse
import ctypes
import json
import os
import re
import sqlite3
import time
from pathlib import Path
from uuid import UUID

from . import backup_records
from . import maintenance_host as host
from . import maintenance_transfer as transfer
from . import owner_process as owner
from .maintenance_serial import ExtendedLimits, KillJob
from .offline_repo import description, new_root, write_json
from .transfer_commands import canonical, digest
from .windows_readonly import require

SOURCES = {
    **owner.SOURCES,
    "boot_preconditions.py": Path(__file__),
    "maintenance_transfer.py": Path(transfer.__file__),
    "offline_repo.py": Path(new_root.__code__.co_filename),
}
SOURCE_EPOCH = {name: digest(path.read_bytes()) for name, path in SOURCES.items()}
BOOT_FIELDS = {
    "firmware": "EFI",
    "apic": "on",
    "x2apic": "off",
    "boot1": "disk",
    "boot2": "none",
    "boot3": "none",
    "boot4": "none",
    "autostart-enabled": "off",
    "teleporterenabled": "off",
    "nested-hw-virt": "off",
    "recording_enabled": "off",
    "recording_started": "off",
}


def draft(role):
    return {
        "format": "mcli1-boot-preconditions-v1",
        "role": role,
        "run_nonce": None,
        "generation": None,
        "owner": {
            "root": None,
            "launch_sha256": None,
            "ready_sha256": None,
            "binding_sha256": None,
        },
        "caller": {"role": None, "process": None},
        "target": {
            "vm_uuid": transfer.SLOTS[role][0],
            "disk_uuid": None,
            "dmi_uuid": None,
        },
        "backup": {
            k: None
            for k in (
                "source_disk_uuid",
                "disk_uuid",
                "disk_sha256",
                "configuration_sha256",
                "nvram_sha256",
                "receipt_sha256",
            )
        },
        "disk_evidence": {
            k: None
            for k in (
                "pre_boot_disk_sha256",
                "pre_boot_receipt_sha256",
                "source_preservation_receipt_sha256",
            )
        },
        "approval": {"boot_scope_review": None, "backup": None, "configuration": None},
        "window": {
            k: None
            for k in (
                "issued_utc_ns",
                "issued_mono_ns",
                "expires_utc_ns",
                "expires_mono_ns",
            )
        },
        "sources": dict(SOURCE_EPOCH),
    }


def checked(raw, sha, *, recovery=None):
    require(
        type(raw) is bytes and digest(raw) == sha, "boot preconditions digest differs"
    )
    grant = host.object_bytes(raw)
    require(
        set(grant) == set(draft("guard"))
        and grant["format"] == "mcli1-boot-preconditions-v1"
        and grant["role"] in transfer.SLOTS,
        "boot preconditions format differs",
    )
    require(
        set(grant["approval"]) == {"boot_scope_review", "backup", "configuration"}
        and all(
            isinstance(v, str) and 0 < len(v) <= 256 for v in grant["approval"].values()
        ),
        "boot scope/backup/configuration review is unbound",
    )
    require(
        isinstance(grant["run_nonce"], str)
        and re.fullmatch(r"[0-9a-f]{32}", grant["run_nonce"])
        and type(grant["generation"]) is int
        and grant["generation"] == 1,
        "boot nonce/generation is unbound",
    )
    require(
        set(grant["target"]) == {"vm_uuid", "disk_uuid", "dmi_uuid"}
        and grant["target"]["vm_uuid"] == transfer.SLOTS[grant["role"]][0],
        "boot target differs",
    )
    for key in ("disk_uuid", "dmi_uuid"):
        require(
            str(UUID(grant["target"][key])) == grant["target"][key],
            "boot disk/DMI identity differs",
        )
    require(
        grant["target"]["disk_uuid"] == transfer.EXECUTOR_DISK
        if grant["role"] == "executor"
        else grant["target"]["disk_uuid"] != transfer.EXECUTOR_DISK,
        "boot role aliases source disk",
    )
    require(
        set(grant["disk_evidence"]) == set(draft("guard")["disk_evidence"])
        and all(
            isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v)
            for v in grant["disk_evidence"].values()
        ),
        "boot disk/source preservation evidence is unbound",
    )
    backup = grant["backup"]
    if recovery is not None:
        context = backup_records.recovery_model.checked(recovery)
        require(
            grant["role"] == "guard"
            and grant["target"]["vm_uuid"] == context["target_vm_uuid"],
            "recovery boot scope differs",
        )
        backup_records.checked_binding(
            backup, grant["target"]["disk_uuid"], recovery=context
        )
    elif backup.get("format") == backup_records.BINDING_FORMAT:
        backup_records.checked_binding(backup, grant["target"]["disk_uuid"])
    else:
        legacy_backup(backup, grant)
    require(
        set(grant["owner"])
        == {"root", "launch_sha256", "ready_sha256", "binding_sha256"}
        and isinstance(grant["owner"]["root"], str),
        "boot owner root is unbound",
    )
    for key in ("launch_sha256", "ready_sha256", "binding_sha256"):
        require(
            isinstance(grant["owner"][key], str)
            and re.fullmatch(r"[0-9a-f]{64}", grant["owner"][key]),
            "boot owner receipt is unbound",
        )
    require(
        set(grant["caller"]) == {"role", "process"}
        and grant["caller"]["role"] in {"controller", "bootstrap"},
        "boot caller scope differs",
    )
    window = grant["window"]
    require(
        set(window)
        == {"issued_utc_ns", "issued_mono_ns", "expires_utc_ns", "expires_mono_ns"}
        and all(type(v) is int and v > 0 for v in window.values()),
        "boot window is unbound",
    )
    for clock in ("utc_ns", "mono_ns"):
        require(
            0 < window["expires_" + clock] - window["issued_" + clock] <= 15 * 10**9,
            "boot check window exceeds bound",
        )
    require(
        grant["sources"]
        == SOURCE_EPOCH
        == {n: digest(p.read_bytes()) for n, p in SOURCES.items()},
        "boot source cohort changed",
    )
    return grant


def legacy_backup(backup, grant):
    require(
        set(backup) == set(draft("guard")["backup"])
        and backup["source_disk_uuid"] == grant["target"]["disk_uuid"]
        and isinstance(backup["disk_uuid"], str)
        and str(UUID(backup["disk_uuid"])) == backup["disk_uuid"]
        and backup["disk_uuid"]
        not in (grant["target"]["disk_uuid"], transfer.EXECUTOR_DISK),
        "boot backup is not independent",
    )
    require(
        all(
            isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v)
            for k, v in backup.items()
            if k.endswith("sha256")
        ),
        "boot backup evidence is unbound",
    )


def live_window(grant):
    w = grant["window"]
    require(
        w["issued_utc_ns"] <= time.time_ns() < w["expires_utc_ns"]
        and w["issued_mono_ns"] <= time.monotonic_ns() < w["expires_mono_ns"],
        "boot check window expired or clock moved",
    )


def kernel_jobs(packet):
    api = owner.job_api()
    for label, expected in (("controller_job", False), ("owner_job", True)):
        job = api.OpenJobObjectW(0x4, False, packet[label])
        require(job, "boot owner/controller job is unavailable")
        try:
            require(
                owner.member(api, packet["owner"]["pid"], job) is expected,
                "boot owner job membership changed",
            )
            require(
                owner.member(api, packet["controller"]["pid"], job) is not expected,
                "boot controller job membership changed",
            )
            if label == "owner_job":
                limits = ExtendedLimits()
                KillJob.check(
                    api.QueryInformationJobObject(
                        job, 9, ctypes.byref(limits), ctypes.sizeof(limits), None
                    )
                )
                require(
                    limits.BasicLimitInformation.LimitFlags == 0x8
                    and limits.BasicLimitInformation.ActiveProcessLimit == 2,
                    "boot owner independent job limits changed",
                )
        finally:
            KillJob.check(api.CloseHandle(job))


def owner_live(store, grant, identity=host.process_identity, jobs=kernel_jobs):
    live_window(grant)
    return watch_owner(store, grant, identity, jobs)


def watch_owner(store, grant, identity=host.process_identity, jobs=kernel_jobs):
    """Monitor the same original authority after the admission window closes.

    This never extends a window or lease and supplies no start permission.
    Admission must still use owner_live, including immediately before resume.
    """
    root = Path(grant["owner"]["root"])
    require(
        not (root / "owner.terminal.json").exists(),
        "original owner terminal receipt forbids further admission",
    )
    root_record = owner.root_identity(root)
    dbpath = store.db.execute("PRAGMA database_list").fetchone()["file"]
    require(
        dbpath and Path(dbpath).resolve() == (root / "owner.sqlite").resolve(),
        "boot checks require the original owner Store",
    )
    launch_raw = owner.read_packet(root / "owner.sealed.json")
    ready_raw = owner.read_packet(root / "owner.ready.json")
    require(
        digest(launch_raw) == grant["owner"]["launch_sha256"]
        and digest(ready_raw) == grant["owner"]["ready_sha256"],
        "boot owner launch/ready bytes differ",
    )
    packet, ready = host.object_bytes(launch_raw), host.object_bytes(ready_raw)
    require(
        packet["format"] == "mcli1-independent-owner-v1"
        and packet["role"] == grant["role"]
        and packet["sources"] == owner.SOURCE_EPOCH == owner.current_sources()
        and packet["root"] == root_record,
        "boot sealed owner source/root differs",
    )
    require(
        ready["format"] == "mcli1-owner-ready-v1"
        and ready["launch_sha256"] == digest(launch_raw)
        and ready["owner"] == packet["owner"]
        and ready["lease"] == packet["lease"]
        and ready["owner_binding_sha256"] == grant["owner"]["binding_sha256"]
        and ready["controller_job_separate"] is True
        and ready["owner_job_retained"] is True
        and ready["VM_start_authorized"] is False,
        "boot owner ready binding differs",
    )
    binding = packet["profile"]["bounded_stop"]
    plan = owner.stop.checked(canonical(binding["plan"]), binding["sha256"])
    expected = canonical(
        {
            "format": "mcli1-original-owner-v1",
            "owner_nonce": packet["owner_nonce"],
            "lease": packet["lease"],
            "process": packet["owner"],
        }
    )
    require(
        plan["target_vm_uuid"] == grant["target"]["vm_uuid"]
        and plan["process"] == packet["owner"]
        and plan["lease"] == packet["lease"]
        and plan["owner_nonce"] == packet["owner_nonce"]
        and plan["owner_binding_sha256"]
        == digest(expected)
        == grant["owner"]["binding_sha256"]
        and ready["stop_plan_sha256"] == binding["sha256"],
        "boot original stop plan/owner binding differs",
    )
    role = grant["caller"]["role"]
    require(
        grant["caller"]["process"] == packet[role]
        and identity(os.getpid()) == packet[role]
        and identity(packet["owner"]["pid"]) == packet["owner"]
        and identity(packet["controller"]["pid"]) == packet["controller"],
        "boot caller/controller/original owner PID identity is not live",
    )
    jobs(packet)
    db = sqlite3.connect(
        Path(dbpath).resolve().as_uri() + "?mode=ro", uri=True, timeout=0.05
    )
    db.row_factory = sqlite3.Row
    try:
        db.execute("BEGIN")
        ledger_live(db, grant, packet, ready["observed_mono_ns"])
    finally:
        db.rollback()
        db.close()
    return packet, ready["observed_mono_ns"]


def ledger_live(db, grant, packet, ready_mono_ns):
    """Check a single SQLite snapshot; no callbacks or native I/O under a write lock."""
    lease = db.execute("SELECT * FROM lease").fetchone()
    row = db.execute("SELECT * FROM maintenance_owner").fetchone()
    authority = db.execute("SELECT * FROM authority").fetchone()
    expected = canonical(
        {
            "format": "mcli1-original-owner-v1",
            "owner_nonce": packet["owner_nonce"],
            "lease": packet["lease"],
            "process": packet["owner"],
        }
    )
    require(
        lease is not None
        and row is not None
        and authority is not None
        and {k: lease[k] for k in host.OWNER_KEYS} == packet["lease"]
        and lease["state"] == "armed"
        and row["state"] == "watching"
        and row["binding"] == expected
        and authority["active"] == 1
        and authority["generation"] == grant["generation"],
        "boot owner ledger is fenced, replaced or stopping",
    )
    now, mono = time.time_ns(), time.monotonic_ns()
    require(
        lease["armed_ns"] <= now < lease["expires_ns"]
        and lease["armed_mono_ns"] <= mono < lease["expires_mono_ns"]
        and 0 <= mono - row["observed_mono_ns"] <= 5 * 10**9
        and lease["armed_mono_ns"] <= ready_mono_ns <= row["observed_mono_ns"],
        "boot owner pulse/lease is stale or clock moved",
    )
    require(
        grant["window"]["expires_utc_ns"] <= lease["expires_ns"] - 10 * 10**9
        and grant["window"]["expires_mono_ns"] <= lease["expires_mono_ns"] - 10 * 10**9,
        "boot check window consumes original stop reserve",
    )


def stopped_snapshot(grant, snapshot, *, recovery=None):
    require(
        set(snapshot) == {"observed_mono_ns", "machine", "medium"}
        and type(snapshot["observed_mono_ns"]) is int
        and 0 <= time.monotonic_ns() - snapshot["observed_mono_ns"] <= 5 * 10**9,
        "boot stopped observation is stale",
    )
    require(
        type(snapshot["machine"]) is bytes and type(snapshot["medium"]) is bytes,
        "boot raw observation bytes missing",
    )
    fields = host.machine_fields(snapshot["machine"])
    expected = transfer.expected_host(grant)
    expected["state"] = "poweroff"
    if recovery is not None:
        context = backup_records.recovery_model.checked(recovery)
        require(
            grant["role"] == "guard"
            and grant["target"]["vm_uuid"] == context["target_vm_uuid"],
            "recovery stopped scope differs",
        )
        backup_records.checked_binding(
            grant["backup"], grant["target"]["disk_uuid"], recovery=context
        )
        expected["state"] = "aborted"
    require(
        host.machine_profile(snapshot["machine"]) == expected
        and fields["hardwareuuid"] == grant["target"]["dmi_uuid"],
        "boot stopped VM/storage/UART/profile changed",
    )
    require(
        all(fields.get(k) == v for k, v in BOOT_FIELDS.items()),
        "boot firmware/order/autostart policy changed",
    )
    host.check_medium(snapshot["medium"], snapshot["machine"], grant)
    if recovery is not None:
        require(
            host.medium_fields(snapshot["medium"])["State"] == "created",
            "recovery admission medium is still locked",
        )
    return {
        "observed_mono_ns": snapshot["observed_mono_ns"],
        "machine_sha256": digest(snapshot["machine"]),
        "medium_sha256": digest(snapshot["medium"]),
    }


class BootPreconditions:
    def __init__(self, store, probe, identity=host.process_identity, jobs=kernel_jobs):
        require(callable(probe), "trusted stopped-state probe required")
        self.store, self.probe, self.identity, self.jobs = store, probe, identity, jobs

    def record(self, raw, sha, backup, preboot, preservation):
        grant = checked(raw, sha)
        host.receipt_pins(grant, backup, preboot, preservation)
        packet, ready_mono_ns = owner_live(self.store, grant, self.identity, self.jobs)
        root = Path(grant["owner"]["root"])
        try:
            first = stopped_snapshot(grant, self.probe())
            live_window(grant)
            intent = canonical(
                {
                    "grant_sha256": sha,
                    "run_nonce": grant["run_nonce"],
                    "launch_sha256": grant["owner"]["launch_sha256"],
                    "first_observation": first,
                    "native_dispatch_permit": False,
                }
            )
            owner.stop.write_once(root / "boot.preconditions.intent.json", intent)
            with self.store.transaction():
                self.store.db.execute(
                    "CREATE TABLE IF NOT EXISTS boot_preconditions (singleton INTEGER PRIMARY KEY CHECK(singleton=1), grant_sha TEXT, state TEXT, receipt_sha TEXT)"
                )
                require(
                    self.store.db.execute("SELECT 1 FROM boot_preconditions").fetchone()
                    is None,
                    "boot preconditions attempt already exists; no replay",
                )
                self.store.db.execute(
                    "INSERT INTO boot_preconditions VALUES(1,?,'intent',NULL)", (sha,)
                )
                self.store._event(
                    "boot-preconditions-intent",
                    {"grant_sha256": sha, "native_dispatch_permit": False},
                )
            final = stopped_snapshot(grant, self.probe())
            checked(raw, sha)
            owner_live(self.store, grant, self.identity, self.jobs)
            require(
                final["machine_sha256"] == first["machine_sha256"]
                and final["medium_sha256"] == first["medium_sha256"],
                "boot stopped configuration changed between observations",
            )
            result = {
                "status": "boot-preconditions-reported-not-native-start-authority",
                "grant_sha256": sha,
                "run_nonce": grant["run_nonce"],
                "owner_binding_sha256": grant["owner"]["binding_sha256"],
                "original_lease": packet["lease"],
                "last_observation": final,
                "native_dispatch_permit": False,
                "VM_started": False,
                "provider_start_task_settlement": "unqualified",
            }
            receipt = canonical(result)
            owner.publish(root / "boot.preconditions.receipt.json", receipt)
            with self.store.transaction():
                row = self.store.db.execute(
                    "SELECT * FROM boot_preconditions"
                ).fetchone()
                authority = self.store.db.execute("SELECT * FROM authority").fetchone()
                require(
                    row["state"] == "intent"
                    and row["grant_sha"] == sha
                    and authority["active"] == 1
                    and authority["generation"] == grant["generation"],
                    "boot preconditions journal/authority changed before receipt",
                )
                live_window(grant)
                ledger_live(self.store.db, grant, packet, ready_mono_ns)
                self.store.db.execute(
                    "UPDATE boot_preconditions SET state='preconditions-reported',receipt_sha=?",
                    (digest(receipt),),
                )
                self.store._event(
                    "boot-preconditions-reported",
                    {
                        "receipt_sha256": digest(receipt),
                        "native_dispatch_permit": False,
                    },
                )
            return result
        except Exception:
            self.store.fence("boot preconditions incomplete; no native start authority")
            raise


def prepare(role, output):
    root = new_root(output)
    raw = canonical(draft(role))
    (root / "boot-review.json").write_bytes(raw)
    for name, path in SOURCES.items():
        (root / name).write_bytes(path.read_bytes())
    try:
        checked(raw, digest(raw))
    except owner.stop.Hold as exc:
        refusal = str(exc)
    else:
        raise owner.stop.Hold("unarmed boot preconditions unexpectedly passed")
    review = {
        "status": "unarmed-boot-preconditions-review",
        "role": role,
        "packet": description(root / "boot-review.json"),
        "refusal": refusal,
        "native_calls": 0,
        "VM_mutations": 0,
        "native_dispatch_permit": False,
        "provider_start_task_settlement": "unqualified",
    }
    write_json(root / "review.json", review)
    return review


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=tuple(transfer.SLOTS), default="guard")
    parser.add_argument("--prepare")
    args = parser.parse_args()
    result = (
        prepare(args.role, args.prepare)
        if args.prepare
        else {
            "status": "unarmed-boot-preconditions-preview",
            "native_calls": 0,
            "native_dispatch_permit": False,
            "packet": draft(args.role),
        }
    )
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
