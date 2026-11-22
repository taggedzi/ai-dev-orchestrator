"""Prepared host observations and original-owner stop handoff for maintenance.

No boot, configuration, installation, transfer or native-owner activation CLI.
Receipt consistency does not authenticate an approval or its issuing observer.
"""

import ctypes
import json
import os
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from ctypes import wintypes
from pathlib import Path, PureWindowsPath
from uuid import UUID

from . import maintenance_transfer as transfer
from .os_install import WORKSPACE
from .supervisor import LeaseSupervisor
from .transfer_commands import canonical, digest
from .windows_readonly import VERSION, live, require

SOURCE_DISK_SHA = "2eb1d9cd009ecfe83381d855137f5cee8c1317739f6209beddd6da8a10955a09"
OWNER_KEYS = ("target", "armed_ns", "expires_ns", "armed_mono_ns", "expires_mono_ns")
MAX_RECEIPT = 64 * 1024


def object_bytes(raw):
    require(
        type(raw) is bytes and len(raw) <= MAX_RECEIPT, "host receipt size/type differs"
    )

    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate host receipt key")
            result[key] = value
        return result

    value = json.loads(raw, object_pairs_hook=unique)
    require(type(value) is dict, "host receipt is not an object")
    return value


def machine_fields(raw):
    require(
        type(raw) is bytes and len(raw) <= MAX_RECEIPT, "VM inventory exceeds bound"
    )
    fields = {}
    for line in raw.decode("utf-8", errors="strict").splitlines():
        if not line.strip():
            continue
        if re.fullmatch(r" rec_screen\d+", line):
            continue  # Installed CLI emits this recording section marker without '='.
        require("=" in line, "unrecognized VM inventory line")
        key, value = line.split("=", 1)
        if key.startswith('"'):
            key = json.loads(key)
        require(
            type(key) is str
            and key not in fields
            and re.fullmatch(r"[A-Za-z0-9_-]+", key),
            "duplicate or malformed VM inventory key",
        )
        if value.startswith('"'):
            if re.fullmatch(r"uartmode\d+", key):
                # VBoxManageInfo.cpp uses raw printf here, not its escaped-string helper.
                require(value.endswith('"') and '"' not in value[1:-1], "bad UART mode")
                value = value[1:-1]
            else:
                value = json.loads(value)
        else:
            require(re.fullmatch(r"[0-9]+", value), "unquoted VM value is not numeric")
        require(
            type(value) is str and "\x00" not in value, "invalid VM inventory value"
        )
        fields[key] = value
    return fields


def machine_profile(raw):
    """Narrow SATA-only observation. Unsupported inventories hold, never disappear."""
    fields = machine_fields(raw)
    require(
        {
            k: v
            for k, v in fields.items()
            if re.fullmatch(r"storagecontrollername\d+", k)
        }
        == {"storagecontrollername0": "SATA"}
        and fields["storagecontrollertype0"] == "IntelAhci"
        and fields["storagecontrollerportcount0"] == "4",
        "unreviewed storage controller or port inventory",
    )
    slots = {k: v for k, v in fields.items() if re.fullmatch(r"SATA-\d+-\d+", k)}
    require(
        set(slots) == {f"SATA-{n}-0" for n in range(4)}
        and slots["SATA-0-0"] not in {"none", "emptydrive"}
        and all(slots[f"SATA-{n}-0"] in {"none", "emptydrive"} for n in range(1, 4))
        and {k for k in fields if "-ImageUUID-" in k} == {"SATA-ImageUUID-0-0"},
        "extra or missing disk/optical/floppy attachment",
    )
    require(
        all(
            re.fullmatch(
                r"SATA-(?:[0-3]-0|ImageUUID-0-0|(?:hot-pluggable|nonrotational|discard|IsEjected|tempeject)-[0-3]-0)",
                k,
            )
            for k in fields
            if k.startswith("SATA-")
        )
        and not any(k.startswith("SharedFolder") for k in fields),
        "unknown storage field or configured/transient shared folder",
    )
    require(
        all(fields[k] == "off" for k in ("usb", "ehci", "xhci", "vrde"))
        and fields["clipboard"] == fields["draganddrop"] == "disabled"
        and fields["clipboard_file_transfers"] == "off"
        and all(fields[f"uart{n}"] == "off" for n in range(2, 5))
        and all(fields[f"lpt{n}"] == "off" for n in (1, 2)),
        "unreviewed USB/display/clipboard/UART/parallel transport",
    )
    nics = {k: v for k, v in fields.items() if re.fullmatch(r"nic\d+", k)}
    require(
        nics == {f"nic{n}": "none" for n in range(1, 9)}, "VM NIC inventory differs"
    )
    if fields["uart1"] == "off":
        uart_pipe, uart_server = None, False
    else:
        require(fields["uart1"] == "0x03f8,4", "UART address/IRQ differs")
        mode, separator, uart_pipe = fields["uartmode1"].partition(",")
        require(separator and mode == "server", "UART is not a host-pipe server")
        uart_server = True
    return {
        "vm_uuid": str(UUID(fields["UUID"])),
        "state": fields["VMState"],
        "cpus": int(fields["cpus"]),
        "memory_mb": int(fields["memory"]),
        "disks": [str(UUID(fields["SATA-ImageUUID-0-0"]))],
        "dvd_uuid": None,
        "nics": [nics[f"nic{n}"] for n in range(1, 9)],
        "shares": [],
        "clipboard": fields["clipboard"],
        "dragdrop": fields["draganddrop"],
        "usb": "disabled",
        "vrde": False,
        "uart_pipe": uart_pipe,
        "uart_server": uart_server,
    }


def medium_fields(raw):
    require(
        type(raw) is bytes and len(raw) <= MAX_RECEIPT, "medium inventory exceeds bound"
    )
    fields = {}
    for line in raw.decode("utf-8", errors="strict").splitlines():
        require(":" in line, "unrecognized disk inventory line")
        key, value = line.split(":", 1)
        require(key not in fields, "duplicate disk inventory key")
        fields[key] = value.strip()
    return fields


def check_medium(raw, machine_raw, grant):
    medium, machine = medium_fields(raw), machine_fields(machine_raw)
    role = grant["role"]
    folder, filename = (
        ("mcli1-validation-01", "installation.vdi")
        if role == "executor"
        else ("mcli1-guard-01", "guard-base.vdi")
    )
    expected = PureWindowsPath(WORKSPACE / ".local/validation/vms" / folder / filename)
    require(
        medium["UUID"] == grant["target"]["disk_uuid"]
        and medium["Parent UUID"] == "base"
        and medium["Type"] == "normal (base)"
        and medium["Storage format"] == "VDI"
        and medium["Capacity"] == "32768 MBytes"
        and medium["Encryption"] == "disabled"
        and medium["State"] in {"created", "locked write"}
        and PureWindowsPath(medium["Location"]) == expected
        and PureWindowsPath(machine["SATA-0-0"]) == expected
        and re.fullmatch(
            r"[^()\r\n]+ \(UUID: " + re.escape(grant["target"]["vm_uuid"]) + r"\)",
            medium["In use by VMs"],
        ),
        "target disk type/path/parent/attachment identity changed",
    )


def process_identity(pid):
    """Read PID creation identity through a non-inheritable Windows process handle."""
    require(os.name == "nt" and type(pid) is int and pid > 0, "Windows PID required")
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    definitions = {
        "OpenProcess": (
            [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD],
            wintypes.HANDLE,
        ),
        "GetProcessTimes": ([wintypes.HANDLE, *([ctypes.c_void_p] * 4)], wintypes.BOOL),
        "QueryFullProcessImageNameW": (
            [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.c_void_p],
            wintypes.BOOL,
        ),
        "WaitForSingleObject": ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
    }
    for name, (args, result) in definitions.items():
        function = getattr(api, name)
        function.argtypes, function.restype = args, result
    handle = api.OpenProcess(
        0x1000 | 0x100000, False, pid
    )  # QUERY_LIMITED | SYNCHRONIZE
    require(handle, "original supervisor process unavailable")
    try:
        require(
            api.WaitForSingleObject(handle, 0) == 0x102, "original owner is not live"
        )
        stamps = [ctypes.c_uint64() for _ in range(4)]
        require(
            api.GetProcessTimes(handle, *[ctypes.byref(s) for s in stamps]),
            "PID times unavailable",
        )
        image, size = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
        require(
            api.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size)),
            "PID image unavailable",
        )
        return {"pid": pid, "created_filetime": stamps[0].value, "image": image.value}
    finally:
        require(api.CloseHandle(handle), "process observation handle did not close")


class RegisteredOwner:
    """Wrap the existing one-shot owner; never take ownership after a restart."""

    def __init__(self, supervisor, owner_nonce, identity=process_identity):
        require(
            isinstance(supervisor, LeaseSupervisor),
            "original lease supervisor required",
        )
        require(
            re.fullmatch(r"[0-9a-f]{32}", owner_nonce or ""), "owner nonce required"
        )
        self.supervisor, self.store = supervisor, supervisor.store
        self.profile = canonical(supervisor.profile)
        path = self.store.db.execute("PRAGMA database_list").fetchone()["file"]
        require(path, "owner requires a durable store")
        row = self.store.db.execute("SELECT * FROM lease WHERE singleton=1").fetchone()
        require(row is not None and row["state"] == "armed", "owner lease is not armed")
        require(
            supervisor.profile["target_vm_uuid"] == row["target"]
            and supervisor.profile["lease_expires_utc_ns"] == row["expires_ns"],
            "owner profile differs from original lease",
        )
        require(
            row["armed_ns"] <= time.time_ns() < row["expires_ns"]
            and row["armed_mono_ns"] <= time.monotonic_ns() < row["expires_mono_ns"],
            "owner cannot revive an expired lease",
        )
        require(
            0 < row["expires_ns"] - row["armed_ns"] <= 600 * 10**9
            and 0 < row["expires_mono_ns"] - row["armed_mono_ns"] <= 600 * 10**9
            and self.store.db.execute("SELECT active FROM authority").fetchone()[0]
            == 1,
            "owner cannot register extended or fenced authority",
        )
        process = identity(os.getpid())
        require(
            set(process) == {"pid", "created_filetime", "image"}
            and type(process["pid"]) is int
            and process["pid"] == os.getpid()
            and type(process["created_filetime"]) is int
            and process["created_filetime"] > 0
            and isinstance(process["image"], str)
            and PureWindowsPath(process["image"]).is_absolute(),
            "original owner must register its own process identity",
        )
        self.binding = canonical(
            {
                "format": "mcli1-original-owner-v1",
                "owner_nonce": owner_nonce,
                "lease": {k: row[k] for k in OWNER_KEYS},
                "process": process,
            }
        )
        with self.store.transaction():
            self.store.db.execute(
                "CREATE TABLE IF NOT EXISTS maintenance_owner (singleton INTEGER PRIMARY KEY CHECK(singleton=1), binding BLOB, observed_mono_ns INTEGER, sequence INTEGER, state TEXT)"
            )
            require(
                self.store.db.execute("SELECT 1 FROM maintenance_owner").fetchone()
                is None,
                "original owner already registered; reconcile without takeover",
            )
            self.store.db.execute(
                "INSERT INTO maintenance_owner VALUES(1,?,?,0,'watching')",
                (self.binding, time.monotonic_ns()),
            )
            self.store._event(
                "maintenance-owner-registered", {"binding_sha256": digest(self.binding)}
            )

    def poll(self, stopper=None):
        require(self.binding is not None, "owner loop already terminated")
        try:
            require(
                canonical(self.supervisor.profile) == self.profile,
                "original owner profile changed",
            )
            with self.store.transaction():
                row = self.store.db.execute(
                    "SELECT * FROM maintenance_owner"
                ).fetchone()
                require(
                    row["binding"] == self.binding and row["state"] == "watching",
                    "owner binding changed",
                )
                self.store.db.execute(
                    "UPDATE maintenance_owner SET observed_mono_ns=?, sequence=sequence+1",
                    (time.monotonic_ns(),),
                )
            stopped = self.supervisor.poll(stopper=stopper)
        except Exception:
            self.binding = None  # Never retry a possibly sent native stop.
            raise
        if stopped:
            with self.store.transaction():
                self.store.db.execute(
                    "UPDATE maintenance_owner SET state='stop-returned'"
                )
            self.binding = None
        return stopped


def receipt_pins(grant, backup, preboot, preservation):
    """Validate proposed trusted receipts; these are not fresh disk measurements."""
    b, p, s = [object_bytes(raw) for raw in (backup, preboot, preservation)]
    require(
        b.get("independent") is True
        and b.get("source_poweroff") is True
        and digest(backup) == grant["backup"]["receipt_sha256"]
        and b
        == {
            "format": "mcli1-independent-backup-v1",
            "target_vm_uuid": grant["target"]["vm_uuid"],
            "source_poweroff": True,
            "independent": True,
            **{k: v for k, v in grant["backup"].items() if k != "receipt_sha256"},
        },
        "backup receipt bytes or facts differ",
    )
    require(
        digest(preboot) == grant["disk_evidence"]["pre_boot_receipt_sha256"]
        and p
        == {
            "format": "mcli1-preboot-disk-v1",
            "run_nonce": grant["run_nonce"],
            "target_vm_uuid": grant["target"]["vm_uuid"],
            "disk_uuid": grant["target"]["disk_uuid"],
            "disk_sha256": grant["disk_evidence"]["pre_boot_disk_sha256"],
            "state": "poweroff",
            "backup_receipt_sha256": digest(backup),
        },
        "preboot receipt bytes or facts differ",
    )
    require(
        digest(preservation)
        == grant["disk_evidence"]["source_preservation_receipt_sha256"]
        and s
        == {
            "format": "mcli1-source-preservation-v1",
            "run_nonce": grant["run_nonce"],
            "target_vm_uuid": grant["target"]["vm_uuid"],
            "source_disk_uuid": transfer.EXECUTOR_DISK,
            "before_sha256": SOURCE_DISK_SHA,
            "after_sha256": SOURCE_DISK_SHA,
            "state": "poweroff",
        },
        "source-preservation receipt bytes or facts differ",
    )


class HostAdapters:
    def __init__(
        self,
        database,
        grant_raw,
        grant_sha,
        owner_raw,
        owner_sha,
        backup_raw,
        preboot_raw,
        preservation_raw,
        queries,
        evidence_root,
        identity=process_identity,
    ):
        self.grant = transfer.checked_grant(grant_raw, grant_sha)
        require(digest(owner_raw) == owner_sha, "owner receipt digest changed")
        self.owner, self.owner_raw = object_bytes(owner_raw), owner_raw
        require(
            set(self.owner) == {"format", "owner_nonce", "lease", "process"}
            and self.owner["format"] == "mcli1-original-owner-v1"
            and self.owner["owner_nonce"] == self.grant["lease"]["owner_nonce"]
            and self.owner["lease"]["target"] == self.grant["target"]["vm_uuid"]
            and self.owner["lease"]["expires_ns"]
            == self.grant["lease"]["expires_utc_ns"]
            and self.owner["lease"]["expires_mono_ns"]
            == self.grant["lease"]["expires_mono_ns"]
            and self.owner["process"]["pid"] != os.getpid(),
            "separate original owner receipt differs",
        )
        receipt_pins(self.grant, backup_raw, preboot_raw, preservation_raw)
        self.database = Path(database).resolve(strict=True)
        self.queries, self.identity = queries, identity
        self.root = Path(evidence_root)
        self.root.mkdir(
            exist_ok=False
        )  # One attempt; retained snapshots never overwritten.
        self.index = 0
        self.capture_lock = threading.Lock()

    @contextmanager
    def _db(self):
        db = sqlite3.connect(
            self.database.as_uri() + "?mode=ro", uri=True, timeout=0.05
        )
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN")
            yield db
        finally:
            db.rollback()
            db.close()

    def _owner(self, db, require_live):
        row = db.execute("SELECT * FROM maintenance_owner WHERE singleton=1").fetchone()
        lease = db.execute("SELECT * FROM lease WHERE singleton=1").fetchone()
        require(
            row is not None
            and row["binding"] == self.owner_raw
            and {k: lease[k] for k in OWNER_KEYS} == self.owner["lease"],
            "original owner or immutable lease record changed",
        )
        if require_live:
            transfer.fresh(row["observed_mono_ns"], time.monotonic_ns())
            require(
                row["state"] == "watching"
                and self.identity(self.owner["process"]["pid"])
                == self.owner["process"],
                "original owner PID identity/liveness changed",
            )
        return row, lease

    def _capture(self, wall_deadline, mono_deadline, expected_state):
        require(
            self.capture_lock.acquire(blocking=False),
            "prior host capture is still active",
        )
        try:
            return self._capture_one(wall_deadline, mono_deadline, expected_state)
        finally:
            self.capture_lock.release()

    def _capture_one(self, wall_deadline, mono_deadline, expected_state):
        require(self.index < 256, "host evidence capture count exhausted")
        start = time.monotonic_ns()
        index, self.index = self.index, self.index + 1
        with (self.root / f"capture-{index:03}.intent.json").open("xb") as output:
            output.write(
                canonical({"started_mono_ns": start, "expected_state": expected_state})
            )
            output.flush()
            os.fsync(output.fileno())
        vm, disk = self.grant["target"]["vm_uuid"], self.grant["target"]["disk_uuid"]
        results = []
        for number, (kind, target) in enumerate(
            (("version", None), ("machine", vm), ("disk", disk), ("machine", vm))
        ):
            result = self.queries(kind, target, wall_deadline, mono_deadline)
            require(
                result["exit"] == 0
                and not result["stderr"]
                and result["job_active_processes"] == 0
                and type(result["stdout"]) is bytes
                and len(result["stdout"]) <= MAX_RECEIPT,
                "native observation query failed/overflowed or was not reaped",
            )
            results.append(result)
            with (self.root / f"capture-{index:03}-query-{number}.stdout").open(
                "xb"
            ) as output:
                output.write(result["stdout"])
                output.flush()
                os.fsync(output.fileno())
        live(wall_deadline, mono_deadline)
        require(results[0]["stdout"].strip() == VERSION.encode(), "hypervisor changed")
        before, after = (
            machine_profile(results[1]["stdout"]),
            machine_profile(results[3]["stdout"]),
        )
        if expected_state == "await-poweroff":
            require(
                before["state"] in {"running", "poweroff"}
                and after["state"] in {"running", "poweroff"}
                and not (before["state"] == "poweroff" and after["state"] == "running")
                and {**before, "state": after["state"]} == after,
                "stop observation changed hardware or restarted the VM",
            )
        else:
            require(before == after, "VM profile changed during observation")
        expected = transfer.expected_host(self.grant)
        expected["state"] = (
            after["state"] if expected_state == "await-poweroff" else expected_state
        )
        require(after == expected, "observed VM profile differs from transfer grant")
        require(
            machine_fields(results[3]["stdout"])["hardwareuuid"]
            == self.grant["target"]["dmi_uuid"],
            "host DMI identity differs",
        )
        check_medium(results[2]["stdout"], results[3]["stdout"], self.grant)
        check_medium(results[2]["stdout"], results[1]["stdout"], self.grant)
        require(
            machine_fields(results[1]["stdout"])["hardwareuuid"]
            == self.grant["target"]["dmi_uuid"],
            "initial host DMI identity differs",
        )
        record = canonical(
            {
                "format": "mcli1-host-capture-v1",
                "run_nonce": self.grant["run_nonce"],
                "started_mono_ns": start,
                "finished_mono_ns": time.monotonic_ns(),
                "queries": [
                    {
                        **{k: v for k, v in r.items() if k not in {"stdout", "stderr"}},
                        "stdout_utf8": r["stdout"].decode("utf-8"),
                        "stderr_utf8": r["stderr"].decode("utf-8"),
                    }
                    for r in results
                ],
                "host": after,
            }
        )
        filename = self.root / f"capture-{index:03}.json"
        with filename.open("xb") as output:
            output.write(record)
            output.flush()
            os.fsync(output.fileno())
        return after, start, digest(record)

    def live_probe(self):
        started = time.monotonic_ns()
        with self._db() as db:
            self._owner(db, True)
            transfer.check_lease(db, self.grant)
        wall = min(
            time.time_ns() + 4 * 10**9, self.grant["phase_window"]["expires_utc_ns"]
        )
        mono = min(started + 4 * 10**9, self.grant["phase_window"]["expires_mono_ns"])
        host, observed, _receipt = self._capture(wall, mono, "running")
        with self._db() as db:
            row, lease = self._owner(db, True)
            snapshot = {
                "observed_mono_ns": observed,
                "host": host,
                "backup_receipt_sha256": self.grant["backup"]["receipt_sha256"],
                "disk_evidence": dict(self.grant["disk_evidence"]),
                "supervisor": {
                    "observed_mono_ns": row["observed_mono_ns"],
                    "live": True,
                    "target_vm_uuid": lease["target"],
                    "owner_nonce": self.owner["owner_nonce"],
                    "expires_utc_ns": lease["expires_ns"],
                    "expires_mono_ns": lease["expires_mono_ns"],
                },
            }
            transfer.check_authority(db, self.grant, snapshot)
        return snapshot

    def stop(self, grant):
        """Fencing is the durable signal. Only the registered original owner stops."""
        require(grant == self.grant, "stop adapter grant changed")
        start, wall_start = time.monotonic_ns(), time.time_ns()
        with (self.root / "stop-wait.intent.json").open("xb") as output:
            output.write(
                canonical({"run_nonce": grant["run_nonce"], "started_mono_ns": start})
            )
            output.flush()
            os.fsync(output.fileno())
        deadline = min(
            start + 9 * 10**9, grant["lease"]["expires_mono_ns"] + 10 * 10**9
        )
        wall = min(
            wall_start + 9 * 10**9, grant["lease"]["expires_utc_ns"] + 10 * 10**9
        )
        while True:
            live(wall, deadline)
            with self._db() as db:
                row, lease = self._owner(db, False)
                authority = db.execute("SELECT * FROM authority").fetchone()
                attempt = db.execute("SELECT * FROM transfer_attempt").fetchone()
                require(
                    not authority["active"]
                    and attempt["nonce"] == grant["run_nonce"]
                    and attempt["state"] == "stopping",
                    "controller fence/stop intent is absent",
                )
                if (
                    lease["state"] == "stop-command-returned"
                    and row["state"] == "stop-returned"
                ):
                    generation = authority["generation"]
                    break
                require(
                    lease["state"] in {"armed", "stopping"},
                    "original stop ledger changed",
                )
                if lease["state"] == "armed":
                    self._owner(db, True)
            time.sleep(0.01)
        while True:
            now = time.monotonic_ns()
            host, observed, receipt = self._capture(
                min(wall, time.time_ns() + 4 * 10**9),
                min(deadline, now + 4 * 10**9),
                "await-poweroff",
            )
            with self._db() as db:
                owner, lease = self._owner(db, False)
                authority = db.execute("SELECT * FROM authority").fetchone()
                attempt = db.execute("SELECT * FROM transfer_attempt").fetchone()
                require(
                    lease["state"] == "stop-command-returned"
                    and owner["state"] == "stop-returned"
                    and not authority["active"]
                    and authority["generation"] == generation
                    and attempt["nonce"] == grant["run_nonce"]
                    and attempt["state"] == "stopping",
                    "stop authority/owner changed during independent observation",
                )
            if host["state"] == "poweroff":
                break
            live(wall, deadline)
            time.sleep(0.01)  # Read-only polling; the original stop is never repeated.
        finished = time.monotonic_ns()
        result = {
            "vm_uuid": host["vm_uuid"],
            "run_nonce": grant["run_nonce"],
            "state": host["state"],
            "disks": host["disks"],
            "nics": host["nics"],
            "shares": host["shares"],
            "receipt_sha256": receipt,
            "observed_mono_ns": finished,
            "elapsed_ns": finished - start,
        }
        require(observed >= start, "poweroff observation predates stop request")
        transfer.stop_report(grant, result, start)
        return result


def main():
    print(
        json.dumps(
            {
                "status": "unarmed-host-adapter-preview",
                "native_calls": 0,
                "VM_control_commands_available": False,
                "owner_activation_available": False,
                "still_required": [
                    "Actual backup/preboot/source receipts and externally reviewed owner binding",
                    "Authenticated approvals, host ACLs and qualified independent owner startup",
                    "Native running/UART/stop and controller-death qualification after scoped approval",
                    "Same-boot inspection and controls approval handoff",
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
