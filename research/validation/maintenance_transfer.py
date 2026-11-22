"""Unarmed transfer controller; native activation still needs approved inputs.

Trusted live-state and stop collectors are injected, not implemented here. No VM
is configured or booted, and no credentials are handled by this module.
"""

import argparse
import base64
import json
import re
import sqlite3
import threading
import time
import zlib
from pathlib import Path

from . import guest_maintenance_control as control
from . import guest_maintenance_probe as probe
from . import guest_transfer_entry as entry
from . import maintenance_serial as transport
from . import maintenance_serial_worker as serial
from . import transfer_commands as commands
from .maintenance_config import PROPOSAL, proposal, render, sources
from .maintenance_control import draft as control_draft
from .maintenance_guest import PRIVATE_PATHS
from .maintenance_guest import draft as inspection_draft
from .offline_repo import description, new_root, write_json
from .store import Hold

FRESH_NS = 5 * 10**9
SLOTS = {
    "executor": (serial.TARGETS[0], 2, 4096),
    "guard": (serial.TARGETS[1], 1, 1024),
}
EXECUTOR_DISK = "e832fc9c-23cc-40a8-8e66-fa0c624b8bd9"
SOURCES = {
    "controller": Path(__file__),
    "compiler": Path(commands.__file__),
    "entry": Path(entry.__file__),
    "worker": Path(serial.__file__),
    "transport": Path(transport.__file__),
    "probe": Path(probe.__file__),
    "controls": Path(control.__file__),
}
SOURCE_EPOCH = {
    key: commands.digest(path.read_bytes()) for key, path in SOURCES.items()
}


def require(value, message):
    if not value:
        raise Hold(message)


def digest(value):
    return commands.digest(commands.canonical(value))


def checked_grant(raw, external_sha):
    require(
        len(raw) <= 64 * 1024 and commands.digest(raw) == external_sha,
        "transfer grant digest changed",
    )
    grant = json.loads(raw)
    require(
        set(grant)
        == {
            "format",
            "purpose",
            "role",
            "run_nonce",
            "generation",
            "target",
            "disk_evidence",
            "backup",
            "approval",
            "lease",
            "phase_window",
            "sources",
            "files",
        },
        "transfer grant fields changed",
    )
    require(
        grant["format"] == "mcli1-transfer-grant-v1"
        and grant["purpose"] in ("inspect", "controls")
        and grant["role"] in SLOTS,
        "transfer purpose/role changed",
    )
    refs = grant["approval"]
    require(
        set(refs)
        == {
            "boot",
            "root_session",
            "transfer",
            "observation",
            "backup",
            "controls",
            "dpkg_configuration_review",
        },
        "transfer approval fields changed",
    )
    required = set(refs) - (
        {"controls", "dpkg_configuration_review"}
        if grant["purpose"] == "inspect"
        else set()
    )
    require(
        all(
            isinstance(refs[k], str)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", refs[k])
            for k in required
        ),
        "transfer approval is unbound",
    )
    require(
        grant["purpose"] != "inspect"
        or refs["controls"] is refs["dpkg_configuration_review"] is None,
        "inspection grant cannot authorize controls",
    )
    require(
        isinstance(grant["run_nonce"], str)
        and re.fullmatch(r"[0-9a-f]{32}", grant["run_nonce"]),
        "transfer nonce is unbound",
    )
    require(
        type(grant["generation"]) is int and grant["generation"] > 0,
        "transfer generation is unbound",
    )
    target = grant["target"]
    require(
        set(target) == {"vm_uuid", "disk_uuid", "dmi_uuid", "root_fs_uuid", "boot_id"}
        and all(probe.uuid(v) for v in target.values()),
        "transfer target is unbound",
    )
    require(
        target["vm_uuid"] == SLOTS[grant["role"]][0],
        "transfer target outside selected slot",
    )
    require(
        (target["disk_uuid"] == EXECUTOR_DISK) == (grant["role"] == "executor"),
        "guard/source disk binding changed",
    )
    require(
        set(grant["disk_evidence"])
        == {
            "pre_boot_disk_sha256",
            "pre_boot_receipt_sha256",
            "source_preservation_receipt_sha256",
        }
        and all(
            isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v)
            for v in grant["disk_evidence"].values()
        ),
        "stopped disk/source preservation evidence unbound",
    )
    backup = grant["backup"]
    require(
        set(backup)
        == {
            "source_disk_uuid",
            "disk_uuid",
            "disk_sha256",
            "configuration_sha256",
            "nvram_sha256",
            "receipt_sha256",
        },
        "transfer backup fields changed",
    )
    require(
        backup["source_disk_uuid"] == target["disk_uuid"]
        and probe.uuid(backup["disk_uuid"])
        and backup["disk_uuid"] not in (target["disk_uuid"], EXECUTOR_DISK),
        "transfer backup is not independent",
    )
    require(
        all(
            isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v)
            for k, v in backup.items()
            if k.endswith("sha256")
        ),
        "transfer backup evidence is unbound",
    )
    lease = grant["lease"]
    require(
        set(lease) == {"owner_nonce", "expires_utc_ns", "expires_mono_ns"}
        and isinstance(lease["owner_nonce"], str)
        and re.fullmatch(r"[0-9a-f]{32}", lease["owner_nonce"]),
        "transfer supervisor is unbound",
    )
    require(
        all(type(lease[k]) is int for k in ("expires_utc_ns", "expires_mono_ns")),
        "transfer lease deadlines are unbound",
    )
    window = grant["phase_window"]
    require(
        set(window)
        == {"issued_utc_ns", "issued_mono_ns", "expires_utc_ns", "expires_mono_ns"}
        and all(type(v) is int for v in window.values()),
        "transfer phase window is unbound",
    )
    for clock in ("utc", "mono"):
        require(
            0
            < window["expires_" + clock + "_ns"] - window["issued_" + clock + "_ns"]
            <= 90 * 10**9
            and window["expires_" + clock + "_ns"]
            <= lease["expires_" + clock + "_ns"] - 10 * 10**9,
            "transfer phase extends original authority/stop reserve",
        )
    require(
        grant["sources"]
        == SOURCE_EPOCH
        == {k: commands.digest(p.read_bytes()) for k, p in SOURCES.items()},
        "transfer source cohort changed",
    )
    return grant


def payloads(grant, files):
    expected = {"guest_maintenance_probe.py", "inspection-spec.json"}
    if grant["purpose"] == "controls":
        expected |= {"guest_maintenance_control.py", "request.json", "observation.json"}
    require(
        set(files) == expected and set(grant["files"]) == expected,
        "transfer payload cohort changed",
    )
    for name, raw in files.items():
        require(
            isinstance(raw, bytes)
            and len(raw) <= commands.MAX_MEMBER
            and grant["files"][name]
            == {"bytes": len(raw), "sha256": commands.digest(raw)},
            "transfer payload bytes changed",
        )
    require(
        commands.digest(files["guest_maintenance_probe.py"]) == entry.PROBE_SHA,
        "transfer probe changed",
    )
    spec = probe.checked_spec(
        files["inspection-spec.json"], grant["files"]["inspection-spec.json"]["sha256"]
    )
    planned = proposal(PROPOSAL.read_bytes())
    require(
        spec["masks"]
        == planned["common_admin_masks_proposal"]
        + planned["roles"][grant["role"]]["additional_admin_masks"]
        and spec["private_paths"] == PRIVATE_PATHS,
        "transfer control inventory differs from frozen procedure",
    )
    require(
        spec["config_files"]
        == {
            "/run/mcli1-maintenance/apt.config": render(planned),
            "/run/mcli1-maintenance/apt/sources.list": sources(),
            "/run/mcli1-maintenance/apt/apt.conf": "",
            "/run/mcli1-maintenance/apt/preferences": "",
        },
        "transfer APT configuration differs from frozen preview",
    )
    require(
        spec["role"] == grant["role"]
        and spec["run_nonce"] == grant["run_nonce"]
        and spec["target"]
        == {k: grant["target"][k] for k in ("dmi_uuid", "root_fs_uuid", "boot_id")},
        "transfer inspection binding changed",
    )
    require(
        spec["approval"]["boot"] == grant["approval"]["boot"]
        and spec["approval"]["observation"] == grant["approval"]["observation"],
        "transfer inspection approvals differ",
    )
    if grant["purpose"] == "controls":
        require(
            commands.digest(files["guest_maintenance_control.py"]) == entry.CONTROL_SHA,
            "transfer controls changed",
        )
        request = control.checked_request(
            files["request.json"], grant["files"]["request.json"]["sha256"]
        )
        require(
            request["run_nonce"] == grant["run_nonce"]
            and request["role"] == grant["role"]
            and request["spec_sha256"]
            == grant["files"]["inspection-spec.json"]["sha256"],
            "control packet belongs to another transfer",
        )
        for key, ref in (
            ("boot", "boot"),
            ("transfer", "transfer"),
            ("observation", "observation"),
            ("backup", "backup"),
            ("control_changes", "controls"),
            ("dpkg_configuration_review", "dpkg_configuration_review"),
        ):
            require(
                request["approval"][key] == grant["approval"][ref],
                "control approval cohort differs",
            )
        before = json.loads(files["observation.json"])
        control.validate_observations(
            request, spec, files["observation.json"], before, probe
        )
    return spec


def expected_host(grant):
    vm, cpu, memory = SLOTS[grant["role"]]
    return {
        "vm_uuid": vm,
        "state": "running",
        "cpus": cpu,
        "memory_mb": memory,
        "disks": [grant["target"]["disk_uuid"]],
        "dvd_uuid": None,
        "nics": ["none"] * 8,
        "shares": [],
        "clipboard": "disabled",
        "dragdrop": "disabled",
        "usb": "disabled",
        "vrde": False,
        "uart_pipe": "\\\\.\\pipe\\mcli1-maint-" + vm,
        "uart_server": True,
    }


def fresh(stamp, mono):
    require(
        type(stamp) is int and 0 <= mono - stamp <= FRESH_NS,
        "transfer authority evidence is stale",
    )


def check_lease(db, grant, wall_ns=time.time_ns, mono_ns=time.monotonic_ns):
    now, mono = wall_ns(), mono_ns()
    row = db.execute("SELECT * FROM lease WHERE singleton=1").fetchone()
    authority = db.execute("SELECT * FROM authority").fetchone()
    require(
        row is not None
        and authority["active"]
        and authority["generation"] == grant["generation"]
        and row["state"] == "armed",
        "transfer authority is fenced or unarmed",
    )
    require(
        row["target"] == grant["target"]["vm_uuid"]
        and row["expires_ns"] == grant["lease"]["expires_utc_ns"]
        and row["expires_mono_ns"] == grant["lease"]["expires_mono_ns"],
        "original transfer lease changed",
    )
    require(
        row["armed_ns"] <= now < row["expires_ns"]
        and row["armed_mono_ns"] <= mono < row["expires_mono_ns"]
        and row["expires_ns"] - row["armed_ns"] <= 600 * 10**9
        and row["expires_mono_ns"] - row["armed_mono_ns"] <= 600 * 10**9,
        "original VM authority expired, moved or exceeds ten minutes",
    )
    window = grant["phase_window"]
    require(
        window["issued_utc_ns"] <= now < window["expires_utc_ns"]
        and window["issued_mono_ns"] <= mono < window["expires_mono_ns"],
        "transfer phase expired or clock moved",
    )
    return row, mono


def check_authority(
    db, grant, snapshot, wall_ns=time.time_ns, mono_ns=time.monotonic_ns
):
    row, mono = check_lease(db, grant, wall_ns, mono_ns)
    fresh(snapshot["observed_mono_ns"], mono)
    host = snapshot["host"]
    require(
        type(host["cpus"]) is type(host["memory_mb"]) is int
        and host == expected_host(grant),
        "transfer VM/storage/UART/isolation profile changed",
    )
    require(
        snapshot["backup_receipt_sha256"] == grant["backup"]["receipt_sha256"],
        "transfer backup receipt changed",
    )
    require(
        snapshot["disk_evidence"] == grant["disk_evidence"],
        "transfer stopped-disk/source evidence changed",
    )
    pulse = snapshot["supervisor"]
    fresh(pulse["observed_mono_ns"], mono)
    require(
        pulse["live"] is True
        and pulse["target_vm_uuid"] == row["target"]
        and pulse["owner_nonce"] == grant["lease"]["owner_nonce"]
        and pulse["expires_utc_ns"] == row["expires_ns"]
        and pulse["expires_mono_ns"] == row["expires_mono_ns"],
        "original live supervisor binding changed",
    )


class AuthorityWatch:
    """Separate sampler and watchdog; a stuck collector cannot refresh evidence."""

    def __init__(self, database, grant, live_probe):
        self.stop, self.cancelled, self.ready = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )
        self.latest, self.error = None, None

        def sample():
            while not self.stop.is_set():
                try:
                    value = live_probe()
                    require(
                        len(commands.canonical(value)) <= 64 * 1024,
                        "live transfer snapshot exceeds bound",
                    )
                    self.latest = json.loads(commands.canonical(value))
                except Exception:  # noqa: BLE001 - Any collector failure revokes dispatch.
                    self.error = "live transfer collector failed"
                    self.cancelled.set()
                self.ready.set()
                self.stop.wait(0.05)

        def watch():
            db = None
            try:
                db = sqlite3.connect(str(database), timeout=0.05)
                db.row_factory = sqlite3.Row
                while not self.stop.is_set():
                    try:
                        if self.latest is not None:
                            db.execute("BEGIN")
                            try:
                                check_authority(db, grant, self.latest)
                            finally:
                                db.rollback()
                    except Exception:  # noqa: BLE001 - Query/shape failures revoke dispatch.
                        self.error = "transfer authority changed or became stale"
                        self.cancelled.set()
                    self.stop.wait(0.01)
            except Exception:  # noqa: BLE001 - Failed monitor startup must fail closed.
                self.error = "transfer authority monitor unavailable"
                self.cancelled.set()
            finally:
                if db is not None:
                    db.close()

        self.threads = [
            threading.Thread(target=sample, daemon=True),
            threading.Thread(target=watch, daemon=True),
        ]
        for thread in self.threads:
            thread.start()

    def close(self):
        self.stop.set()
        for thread in self.threads:
            thread.join(timeout=0.2)


def decode_report(receipt, request):
    require(
        receipt["request_id"] == request["request_id"]
        and receipt["acknowledged_steps"] == [s["ack"] for s in request["steps"]]
        and receipt["worker_exit"] == 0
        and receipt["job_active_processes"] == 0,
        "transfer transport receipt changed",
    )
    raw = base64.b64decode(receipt["data_base64"], validate=True)
    require(
        len(raw) <= entry.MAX_REPORT and commands.digest(raw) == receipt["data_sha256"],
        "transfer report digest/size changed",
    )
    return json.loads(raw), raw


def identity_window(grant, envelope, grant_sha, after_wall, after_mono):
    require(
        set(envelope) == {"format", "run_nonce", "grant_sha256", "identity"}
        and envelope["format"] == "mcli1-transfer-identity-v1"
        and envelope["run_nonce"] == grant["run_nonce"]
        and envelope["grant_sha256"] == grant_sha,
        "read-only identity report changed",
    )
    identity = envelope["identity"]
    require(
        set(identity)
        == {
            "dmi_uuid",
            "root_fs_uuid",
            "boot_id",
            "root_dev",
            "root_ino",
            "mnt_ino",
            "guest_utc_ns",
            "guest_mono_ns",
        }
        and all(
            identity[k] == grant["target"][k]
            for k in ("dmi_uuid", "root_fs_uuid", "boot_id")
        ),
        "read-only guest identity differs",
    )
    require(
        all(
            type(identity[k]) is int and identity[k] > 0
            for k in (
                "root_dev",
                "root_ino",
                "mnt_ino",
                "guest_utc_ns",
                "guest_mono_ns",
            )
        )
        and identity["root_ino"] == 2,
        "guest clock/root namespace fields malformed",
    )
    remaining = min(
        grant["phase_window"]["expires_utc_ns"] - after_wall,
        grant["phase_window"]["expires_mono_ns"] - after_mono,
        60 * 10**9,
    )
    require(remaining > 0, "identity exchange exhausted original phase")
    return identity, {
        "issued_utc_ns": identity["guest_utc_ns"],
        "issued_mono_ns": identity["guest_mono_ns"],
        "expires_utc_ns": identity["guest_utc_ns"] + remaining,
        "expires_mono_ns": identity["guest_mono_ns"] + remaining,
    }


def stop_report(grant, receipt, not_before):
    require(
        set(receipt)
        == {
            "vm_uuid",
            "run_nonce",
            "state",
            "disks",
            "nics",
            "shares",
            "receipt_sha256",
            "observed_mono_ns",
            "elapsed_ns",
        }
        and len(commands.canonical(receipt)) <= 64 * 1024,
        "independent transfer stop fields/size changed",
    )
    require(
        receipt["vm_uuid"] == grant["target"]["vm_uuid"]
        and receipt["run_nonce"] == grant["run_nonce"]
        and receipt["state"] == "poweroff"
        and receipt["disks"] == [grant["target"]["disk_uuid"]]
        and receipt["nics"] == ["none"] * 8
        and receipt["shares"] == [],
        "independent transfer stop profile differs",
    )
    require(
        isinstance(receipt["receipt_sha256"], str)
        and re.fullmatch(r"[0-9a-f]{64}", receipt["receipt_sha256"]),
        "independent transfer stop receipt missing",
    )
    fresh(receipt["observed_mono_ns"], time.monotonic_ns())
    require(
        type(receipt["elapsed_ns"]) is int
        and 0 <= receipt["elapsed_ns"] <= 10 * 10**9
        and receipt["observed_mono_ns"] - receipt["elapsed_ns"] >= not_before
        and receipt["observed_mono_ns"]
        <= grant["lease"]["expires_mono_ns"] + 10 * 10**9,
        "independent transfer stop exceeded original bound",
    )


class TransferController:
    def __init__(self, store, live_probe, stopper, sender=transport.run_journaled):
        self.store, self.live_probe, self.stopper, self.sender = (
            store,
            live_probe,
            stopper,
            sender,
        )
        path = store.db.execute("PRAGMA database_list").fetchone()["file"]
        require(
            path and callable(live_probe) and callable(stopper) and callable(sender),
            "durable controller and trusted collectors required",
        )
        self.database = Path(path)
        store.db.execute(
            "CREATE TABLE IF NOT EXISTS transfer_attempt (singleton INTEGER PRIMARY KEY CHECK(singleton=1), grant_sha TEXT, nonce TEXT, state TEXT)"
        )

    def run(self, raw, external_sha, files):
        grant = checked_grant(raw, external_sha)
        files = dict(
            files
        )  # Bytes are immutable; do not retain a caller's mutable map.
        payloads(grant, files)
        watch = None
        validated = False
        started, outcome, upload_request, _result_raw, stopped = (
            False,
            None,
            None,
            None,
            None,
        )
        try:
            with self.store.transaction():
                check_lease(self.store.db, grant)
                require(
                    self.store.db.execute("SELECT 1 FROM transfer_attempt").fetchone()
                    is None,
                    "transfer attempt exists; reconcile without replay",
                )
                self.store.db.execute(
                    "INSERT INTO transfer_attempt VALUES(1,?,?,'intent')",
                    (external_sha, grant["run_nonce"]),
                )
                self.store._event(
                    "transfer-controller-intent",
                    {"grant_sha256": external_sha, "nonce": grant["run_nonce"]},
                )
            started = True
            watch = AuthorityWatch(self.database, grant, self.live_probe)
            require(
                watch.ready.wait(1) and not watch.cancelled.is_set(),
                "live authority snapshot unavailable",
            )
            check_authority(self.store.db, grant, watch.latest)
            checked_grant(raw, external_sha)
            identity_request = commands.identity_request(grant, external_sha)
            before = time.monotonic_ns()
            wire = commands.canonical(identity_request)
            receipt = self.sender(
                self.store,
                wire,
                commands.digest(wire),
                grant["generation"],
                watch.cancelled,
            )
            envelope, identity_raw = decode_report(receipt, identity_request)
            require(
                not watch.cancelled.is_set()
                and 0 <= time.monotonic_ns() - before <= FRESH_NS,
                "identity response became stale",
            )
            identity, window = identity_window(
                grant, envelope, external_sha, time.time_ns(), time.monotonic_ns()
            )
            check_authority(self.store.db, grant, watch.latest)
            self.store.receipt(
                "serial:" + identity_request["request_id"], 200, identity_raw
            )  # Read-only gate only.
            if grant["purpose"] == "controls":
                control_request = json.loads(files["request.json"])
                require(
                    control_request["window"]["expires_mono_ns"]
                    <= window["expires_mono_ns"]
                    and control_request["window"]["expires_utc_ns"]
                    <= window["expires_utc_ns"],
                    "control request extends original guest window",
                )
            compiled = commands.compile_upload(
                grant, external_sha, identity, window, files
            )
            checked_grant(raw, external_sha)
            upload_request = compiled["request"]
            wire = commands.canonical(upload_request)
            receipt = self.sender(
                self.store,
                wire,
                commands.digest(wire),
                grant["generation"],
                watch.cancelled,
            )
            outcome, _result_raw = decode_report(receipt, upload_request)
            require(
                not watch.cancelled.is_set(),
                "transfer authority changed before reporting",
            )
            check_authority(self.store.db, grant, watch.latest)
            require(
                set(outcome)
                == {
                    "format",
                    "purpose",
                    "run_nonce",
                    "grant_sha256",
                    "capsule_sha256",
                    "result",
                }
                and outcome["format"] == "mcli1-transfer-result-v1"
                and outcome["purpose"] == grant["purpose"]
                and outcome["run_nonce"] == grant["run_nonce"]
                and outcome["grant_sha256"] == external_sha
                and outcome["capsule_sha256"] == compiled["capsule_sha256"],
                "transfer result envelope differs",
            )
            result = outcome["result"]
            require(
                result["run_nonce"] == grant["run_nonce"],
                "transfer result nonce differs",
            )
            if grant["purpose"] == "inspect":
                require(
                    result["status"] == "observed-not-admitted"
                    and result["role"] == grant["role"]
                    and result["target"]
                    == {
                        k: grant["target"][k]
                        for k in ("dmi_uuid", "root_fs_uuid", "boot_id")
                    }
                    and result["baseline_status_sha256"] == probe.STATUS,
                    "inspection report binding differs",
                )
                require(
                    type(result["guest_finished_mono_ns"]) is int
                    and compiled["capsule"]["guest_window"]["issued_mono_ns"]
                    <= result["guest_finished_mono_ns"]
                    < compiled["capsule"]["guest_window"]["expires_mono_ns"]
                    and result["mutations"] == 0
                    and result["host_timestamp_or_authority"] is False,
                    "inspection result clock/scope changed",
                )
            else:
                planned = probe.control_plan(
                    payloads(grant, files), json.loads(files["observation.json"])
                )
                require(
                    result["status"] == "controls-reported-not-installation-acceptance"
                    and result["installation_performed"] is False
                    and result["state_directory"] == control.STATE
                    and result["independent_stop_still_required"] is True
                    and type(result["actions_completed"]) is int
                    and result["actions_completed"] == len(planned["actions"])
                    and isinstance(result["journal_last_sha256"], str)
                    and re.fullmatch(r"[0-9a-f]{64}", result["journal_last_sha256"]),
                    "control report is not the expected controls-only result",
                )
            validated = True
        finally:
            if watch is not None:
                watch.close()
            if started:
                self.store.fence(
                    "transfer finished or uncertain; independent stop/reconciliation required"
                )
                with self.store.transaction():
                    self.store.db.execute(
                        "UPDATE transfer_attempt SET state='stopping'"
                    )
                    self.store._event(
                        "transfer-stop-intent",
                        {"target_vm_uuid": grant["target"]["vm_uuid"]},
                    )
                box, done = {}, threading.Event()
                stop_started = time.monotonic_ns()

                def stop():
                    try:
                        box["receipt"] = self.stopper(grant)
                    except Exception:  # noqa: BLE001 - Stop errors retain uncertain state.
                        box["failed"] = True
                    finally:
                        done.set()

                threading.Thread(target=stop, daemon=True).start()
                require(
                    done.wait(10) and "receipt" in box,
                    "independent transfer stop unknown; no retry",
                )
                stopped = box["receipt"]
                stop_report(grant, stopped, stop_started)
                lease = self.store.db.execute(
                    "SELECT * FROM lease WHERE singleton=1"
                ).fetchone()
                require(
                    lease["state"] == "stop-command-returned"
                    and lease["target"] == grant["target"]["vm_uuid"]
                    and lease["expires_ns"] == grant["lease"]["expires_utc_ns"]
                    and lease["expires_mono_ns"] == grant["lease"]["expires_mono_ns"],
                    "original supervisor stop ledger is incomplete or changed",
                )
                with self.store.transaction():
                    if not validated:
                        self.store.db.execute(
                            "UPDATE transfer_attempt SET state='held-stop-reported'"
                        )
                    self.store._event(
                        "transfer-stop-reported",
                        {"receipt_sha256": stopped["receipt_sha256"]},
                    )
        combined = commands.canonical({"outcome": outcome, "stop": stopped})
        self.store.receipt("serial:" + upload_request["request_id"], 200, combined)
        with self.store.transaction():
            self.store.db.execute(
                "UPDATE transfer_attempt SET state='reported-and-stop-reported'"
            )
            self.store._event(
                "transfer-postconditions-reported",
                {
                    "result_sha256": commands.digest(combined),
                    "native_qualification_still_required": True,
                },
            )
        return {
            "status": "transfer-and-stop-reported-not-accepted",
            "outcome": outcome,
            "stop": stopped,
        }


def draft(role, purpose, files):
    return {
        "format": "mcli1-transfer-grant-v1",
        "purpose": purpose,
        "role": role,
        "run_nonce": None,
        "generation": None,
        "target": {
            "vm_uuid": SLOTS[role][0],
            "disk_uuid": None,
            "dmi_uuid": None,
            "root_fs_uuid": None,
            "boot_id": None,
        },
        "backup": {
            "source_disk_uuid": None,
            "disk_uuid": None,
            "disk_sha256": None,
            "configuration_sha256": None,
            "nvram_sha256": None,
            "receipt_sha256": None,
        },
        "disk_evidence": {
            key: None
            for key in (
                "pre_boot_disk_sha256",
                "pre_boot_receipt_sha256",
                "source_preservation_receipt_sha256",
            )
        },
        "approval": {
            k: None
            for k in (
                "boot",
                "root_session",
                "transfer",
                "observation",
                "backup",
                "controls",
                "dpkg_configuration_review",
            )
        },
        "lease": {"owner_nonce": None, "expires_utc_ns": None, "expires_mono_ns": None},
        "phase_window": {
            k: None
            for k in (
                "issued_utc_ns",
                "issued_mono_ns",
                "expires_utc_ns",
                "expires_mono_ns",
            )
        },
        "sources": dict(SOURCE_EPOCH),
        "files": {
            name: {"bytes": len(data), "sha256": commands.digest(data)}
            for name, data in files.items()
        },
    }


def prepare(role, purpose, output):
    spec = commands.canonical(inspection_draft(role))
    files = {
        "guest_maintenance_probe.py": Path(probe.__file__).read_bytes(),
        "inspection-spec.json": spec,
    }
    if purpose == "controls":
        files["guest_maintenance_control.py"] = Path(control.__file__).read_bytes()
        files["request.json"] = commands.canonical(
            control_draft(role, commands.digest(spec))
        )
        # A real observation is still required; never fabricate one in the packet.
    grant = draft(role, purpose, files)
    root = new_root(output)
    raw = commands.canonical(grant)
    (root / "grant.json").write_bytes(raw)
    for name, data in files.items():
        (root / name).write_bytes(data)
    for source in (
        Path(__file__),
        Path(commands.__file__),
        Path(entry.__file__),
        Path(serial.__file__),
    ):
        (root / source.name).write_bytes(source.read_bytes())
    try:
        checked_grant(raw, commands.digest(raw))
    except Hold as exc:
        refusal = str(exc)
    else:
        raise Hold("unarmed transfer grant unexpectedly passed")
    review = {
        "status": "unarmed-transfer-controller-review",
        "role": role,
        "purpose": purpose,
        "grant": description(root / "grant.json"),
        "refusal": refusal,
        "native_calls": 0,
        "mutations": 0,
        "actual_observation_present": False,
        "collectors_implemented": False,
        "VM_activation_authorized": False,
        "static_payload_layout": [
            {
                "name": name,
                "bytes": len(data),
                "sha256": commands.digest(data),
                "compressed_bytes": len(zlib.compress(data, 9)),
            }
            for name, data in sorted(files.items())
        ],
        "still_required": [
            "Actual VM/disk/backup/root-session and immutable lease bindings",
            "Qualified live-state, approval and independent stop collectors",
            "Scoped native creation/boot/UART/transfer/observation/control approvals",
            "Real observation and exact control packet for controls purpose",
            "Native target and complete installation/runtime qualification",
        ],
    }
    write_json(root / "review.json", review)
    return review


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=tuple(SLOTS), default="guard")
    parser.add_argument("--purpose", choices=("inspect", "controls"), default="inspect")
    parser.add_argument("--prepare")
    args = parser.parse_args()
    result = (
        prepare(args.role, args.purpose, args.prepare)
        if args.prepare
        else {
            "status": "unarmed-preview",
            "grant": draft(args.role, args.purpose, {}),
            "native_calls": 0,
        }
    )
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
