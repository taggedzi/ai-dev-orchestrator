"""Unarmed owner-launch preparation and suspended-process handoff library.

The outside bootstrap must be independent of the controller. There is no CLI
that launches a worker, starts a VM or supplies approval on the operator's behalf.
"""

import argparse
import ctypes
import json
import os
import sqlite3
import sys
import time
from ctypes import wintypes
from pathlib import Path

from . import owner_process as worker
from .maintenance_host import OWNER_KEYS, process_identity
from .maintenance_serial import ExtendedLimits, KillJob
from .offline_repo import description, new_root, write_json
from .store import Store
from .supervisor import LeaseSupervisor
from .transfer_commands import canonical, digest
from .windows_readonly import _create_in_job, require


class OwnerJob(KillJob):
    """Provisional kill-on-close; worker retains and decouples it before ready."""

    def __init__(self, name):
        super().__init__(name)
        limits = ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = 0x2000 | 0x8
        limits.BasicLimitInformation.ActiveProcessLimit = (
            2  # Owner plus one stop child.
        )
        try:
            self.check(
                self.api.SetInformationJobObject(
                    self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
                )
            )
        except Exception:
            self.close()
            raise

    def detached_limits(self):
        limits = ExtendedLimits()
        self.check(
            self.api.QueryInformationJobObject(
                self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits), None
            )
        )
        return (
            limits.BasicLimitInformation.LimitFlags == 0x8
            and limits.BasicLimitInformation.ActiveProcessLimit == 2
        )


class SuspendedChild:
    """Fixed caller-owned argv; only stdin and two null outputs are inherited."""

    def __init__(self, args, job):
        require(sys.platform == "win32", "suspended owner launch requires Windows")
        import _winapi
        import msvcrt

        self.process = self.primary = self.input = None
        self.pid = None
        fds, handles = [], []
        try:
            read_fd, write_fd = os.pipe()
            fds.extend([read_fd, write_fd])
            out_fd = os.open(os.devnull, os.O_WRONLY | os.O_BINARY)
            fds.append(out_fd)
            err_fd = os.open(os.devnull, os.O_WRONLY | os.O_BINARY)
            fds.append(err_fd)
            handles = [msvcrt.get_osfhandle(fd) for fd in (read_fd, out_fd, err_fd)]
            for handle in handles:
                os.set_handle_inheritable(handle, True)
            env = {
                k: v
                for k, v in os.environ.items()
                if k.upper()
                in {
                    "SYSTEMROOT",
                    "WINDIR",
                    "TEMP",
                    "TMP",
                    "USERPROFILE",
                    "APPDATA",
                    "LOCALAPPDATA",
                }
            }
            self.process, self.primary, self.pid, _tid = _create_in_job(
                job.api,
                sys.executable,
                args,
                handles,
                env,
                job.handle,
            )
            for handle in handles:
                os.set_handle_inheritable(handle, False)
            handles.clear()
            self.input = write_fd
            fds.remove(write_fd)
        except Exception:
            if self.process is not None:
                _winapi.TerminateProcess(self.process, 2)
                _winapi.WaitForSingleObject(self.process, 500)
            self.close()
            raise
        finally:
            for handle in handles:
                os.set_handle_inheritable(handle, False)
            for fd in fds:
                os.close(fd)

    def resume(self, activation=b""):
        require(self.primary is not None, "owner primary thread already resumed")
        if self.input is not None:
            require(len(activation) <= 65, "owner activation message exceeds bound")
            if activation:
                require(
                    os.write(self.input, activation) == len(activation),
                    "owner activation write incomplete",
                )
            os.close(self.input)
            self.input = None
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.ResumeThread.argtypes, api.ResumeThread.restype = (
            [wintypes.HANDLE],
            wintypes.DWORD,
        )
        require(
            api.ResumeThread(self.primary) == 1,
            "owner primary thread did not resume once",
        )
        import _winapi

        _winapi.CloseHandle(self.primary)
        self.primary = None

    def poll(self):
        import _winapi

        if _winapi.WaitForSingleObject(self.process, 0) == 0x102:
            return None
        return _winapi.GetExitCodeProcess(self.process)

    def close(self):
        import _winapi

        if self.input is not None:
            os.close(self.input)
            self.input = None
        if self.primary is not None:
            _winapi.CloseHandle(self.primary)
            self.primary = None
        if self.process is not None:
            _winapi.CloseHandle(self.process)
            self.process = None


class PendingOwner:
    def __init__(
        self, root, role, nonce, controller, expiry_utc_ns, provisional_start_reference
    ):
        require(role in worker.stop.VM_IDS, "unknown owner role")
        require(
            isinstance(nonce, str)
            and len(nonce) == 32
            and all(c in "0123456789abcdef" for c in nonce),
            "owner nonce required",
        )
        require(
            isinstance(provisional_start_reference, str)
            and provisional_start_reference,
            "provisional owner process approval required",
        )
        require(
            worker.current_sources() == worker.SOURCE_EPOCH,
            "owner launch source changed",
        )
        self.root = Path(root).absolute()
        worker.root_identity(self.root.parent)
        self.root.mkdir(exist_ok=False)
        self.root = self.root.resolve(strict=True)
        self.role, self.nonce, self.controller = (
            role,
            nonce,
            json.loads(canonical(controller)),
        )
        self.bootstrap = process_identity(os.getpid())
        self.controller_job = "Local\\MCLI1Controller-" + nonce
        worker.outside_controller(self.controller, self.bootstrap, self.controller_job)
        self.job = self.child = None
        self.sealed = False
        profile = {
            "target_vm_uuid": worker.stop.VM_IDS[role],
            "lease_expires_utc_ns": expiry_utc_ns,
            "vboxmanage": str(worker.stop.VBOX),
        }
        store = Store(self.root / "owner.sqlite")
        store.db.execute("PRAGMA busy_timeout=50")
        try:
            LeaseSupervisor(store, profile)
            self.lease = {
                k: store.db.execute("SELECT * FROM lease").fetchone()[k]
                for k in OWNER_KEYS
            }
            self.job = OwnerJob("Local\\MCLI1Owner-" + nonce)
            code = f"import sys;sys.path.insert(0,{str(worker.DIRECTORY.parents[1])!r});from research.validation.owner_process import worker_main;worker_main({str(self.root)!r})"
            self.child = SuspendedChild(["-I", "-B", "-c", code], self.job)
            self.owner = process_identity(self.child.pid)
            self.proposal = worker.stop.draft(role)
            self.proposal.update(
                owner_nonce=nonce, process=self.owner, lease=self.lease
            )
            owner_binding = canonical(
                {
                    "format": "mcli1-original-owner-v1",
                    "owner_nonce": nonce,
                    "lease": self.lease,
                    "process": self.owner,
                }
            )
            self.proposal["owner_binding_sha256"] = digest(owner_binding)
            worker.stop.write_once(
                self.root / "owner.proposal.json",
                canonical(
                    {
                        "status": "suspended-owner-not-armed",
                        "stop_plan": self.proposal,
                        "owner": self.owner,
                        "bootstrap": self.bootstrap,
                        "controller": self.controller,
                        "provisional_start_reference": provisional_start_reference,
                        "sources": worker.SOURCE_EPOCH,
                        "VM_start_authorized": False,
                    }
                ),
            )
        except Exception:
            self.close()
            raise
        finally:
            store.close()

    def seal(self, stop_raw, stop_sha, owner_start_reference):
        require(not self.sealed, "owner launch already sealed")
        require(
            isinstance(owner_start_reference, str)
            and 0 < len(owner_start_reference) <= 256,
            "owner start approval required",
        )
        plan = worker.stop.checked(stop_raw, stop_sha)
        require(
            stop_raw == canonical(plan),
            "reviewed stop plan must use canonical bytes before resume",
        )
        expected = json.loads(canonical(plan))
        expected["approval"] = {"native_stop": None}
        require(
            expected == self.proposal,
            "reviewed stop plan differs from suspended proposal",
        )
        require(
            worker.current_sources() == worker.SOURCE_EPOCH,
            "owner source changed before resume",
        )
        require(
            process_identity(self.child.pid) == self.owner,
            "suspended owner identity changed",
        )
        require(
            time.time_ns() < self.lease["expires_ns"]
            and time.monotonic_ns() < self.lease["expires_mono_ns"],
            "original owner lease expired before resume",
        )
        worker.outside_controller(self.controller, self.bootstrap, self.controller_job)
        packet = {
            "format": "mcli1-independent-owner-v1",
            "role": self.role,
            "owner_nonce": self.nonce,
            "owner_job": "Local\\MCLI1Owner-" + self.nonce,
            "controller_job": self.controller_job,
            "controller": self.controller,
            "bootstrap": self.bootstrap,
            "owner": self.owner,
            "root": worker.root_identity(self.root),
            "lease": self.lease,
            "profile": {
                "target_vm_uuid": plan["target_vm_uuid"],
                "lease_expires_utc_ns": plan["lease"]["expires_ns"],
                "vboxmanage": plan["hypervisor"]["path"],
                "bounded_stop": {"plan": plan, "sha256": stop_sha},
            },
            "approval": {"owner_start": owner_start_reference},
            "sources": worker.SOURCE_EPOCH,
        }
        raw = canonical(packet)
        self.launch_sha = digest(raw)
        worker.stop.write_once(self.root / "owner.sealed.json", raw)
        self.child.resume(self.launch_sha.encode() + b"\n")
        self.sealed = True
        return self.launch_sha

    def ready(self, seconds=3):
        require(
            self.sealed and 0 < seconds <= 5, "bounded sealed owner ready wait required"
        )
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            require(
                self.child.poll() is None, "owner exited before readiness; no VM start"
            )
            path = self.root / "owner.ready.json"
            if path.exists():
                result = worker.object_bytes(worker.read_packet(path))
                require(
                    result["launch_sha256"] == self.launch_sha
                    and result["owner"] == self.owner
                    and result["lease"] == self.lease
                    and result["controller_job_separate"] is True
                    and result["owner_job_retained"] is True
                    and result["VM_start_authorized"] is False
                    and process_identity(self.child.pid) == self.owner
                    and self.job.detached_limits(),
                    "original owner ready proof differs",
                )
                database = (self.root / "owner.sqlite").resolve()
                db = sqlite3.connect(
                    database.as_uri() + "?mode=ro", uri=True, timeout=0.05
                )
                db.row_factory = sqlite3.Row
                try:
                    db.execute("BEGIN")
                    lease = db.execute("SELECT * FROM lease").fetchone()
                    authority = db.execute("SELECT * FROM authority").fetchone()
                    owner = db.execute("SELECT * FROM maintenance_owner").fetchone()
                    require(
                        {k: lease[k] for k in OWNER_KEYS} == self.lease
                        and lease["state"] == "armed"
                        and authority["active"] == 1
                        and authority["generation"] == 1
                        and owner["state"] == "watching"
                        and digest(owner["binding"]) == result["owner_binding_sha256"]
                        and 0
                        <= time.monotonic_ns() - owner["observed_mono_ns"]
                        <= 5 * 10**9,
                        "original owner ready ledger is inactive, stale or changed",
                    )
                finally:
                    db.rollback()
                    db.close()
                require(
                    time.time_ns() < self.lease["expires_ns"]
                    and time.monotonic_ns() < self.lease["expires_mono_ns"],
                    "original owner expired while waiting for ready",
                )
                require(
                    process_identity(self.controller["pid"]) == self.controller,
                    "controller disappeared before owner ready handoff",
                )
                return result
            time.sleep(0.01)
        raise worker.stop.Hold("original owner did not become ready; no VM start")

    def close(self):
        provisional = self.child is not None and self.child.primary is not None
        if self.job is not None:
            self.job.close()
            self.job = None
        if self.child is not None:
            if provisional:
                import _winapi

                require(
                    _winapi.WaitForSingleObject(self.child.process, 500) == 0,
                    "suspended owner cleanup is unknown",
                )
            self.child.close()
            self.child = None


def draft(role):
    return {
        "format": "mcli1-owner-launch-review-v1",
        "role": role,
        "target_vm_uuid": worker.stop.VM_IDS[role],
        "owner_nonce": None,
        "controller_process": None,
        "controller_job": None,
        "provisional_start_approval": None,
        "owner_start_approval": None,
        "native_stop_approval": None,
        "original_expiry_utc_ns": None,
        "suspended_owner_process": None,
        "exact_stop_plan_sha256": None,
        "sources": worker.SOURCE_EPOCH,
        "VM_start_authorized": False,
    }


def prepare(role, output):
    root = new_root(output)
    raw = canonical(draft(role))
    (root / "launch-review.json").write_bytes(raw)
    for name, path in worker.SOURCES.items():
        (root / name).write_bytes(path.read_bytes())
    review = {
        "status": "unarmed-independent-owner-launch-review",
        "role": role,
        "packet": description(root / "launch-review.json"),
        "native_calls": 0,
        "VM_mutations": 0,
        "actual_owner_launched": False,
        "activation_authorized": False,
        "still_required": [
            "Outside-bootstrap/controller job and process bindings",
            "Separate process start and exact native stop approvals",
            "Actual suspended PID/original clocks and sealed plan",
            "Native VM bootstrap and final stop qualification",
        ],
    }
    write_json(root / "review.json", review)
    return review


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=tuple(worker.stop.VM_IDS), default="guard")
    parser.add_argument("--prepare")
    args = parser.parse_args()
    result = (
        prepare(args.role, args.prepare)
        if args.prepare
        else {
            "status": "unarmed-owner-launch-preview",
            "native_calls": 0,
            "launch_available": False,
            "packet": draft(args.role),
        }
    )
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
