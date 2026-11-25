"""Prepared Windows frontend process-family containment; no VM activation CLI.

This private primitive is not a boot admission adapter. A future admitted starter
must bind the original owner, target, backup, clocks and executable before using it.
"""

import ctypes
import hashlib
import json
import os
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

from .maintenance_host import process_identity
from .maintenance_serial import ExtendedLimits, KillJob
from .windows_readonly import Hold, _create_in_job, require

FRONTEND_LIMIT = 3
FAMILY_LIMIT = 6
CONTROLLER_LIMIT = 12
OUTPUT_LIMIT = 65536
CONHOST = Path(r"C:\Windows\System32\conhost.exe")
CONHOST_SHA256 = "0afce92d925a7ef2ae27c088e9416c52c762979c9ceb8dfca46371afa8c6bd83"
HEADLESS = Path(r"C:\Program Files\Oracle\VirtualBox\VBoxHeadless.exe")
HEADLESS_SHA256 = "e862a58b74c085306c5e8103529ddea1159e48862712cb5d4a68305c886fd51d"


def set_limits(job, count):
    limits = ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = 0x2000 | 0x8
    limits.BasicLimitInformation.ActiveProcessLimit = count
    job.check(
        job.api.SetInformationJobObject(
            job.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        )
    )


class ControllerJob(KillJob):
    """Bounded outer job: controller, frontend family and isolated query workers."""

    def __init__(self, name):
        super().__init__(name)
        try:
            set_limits(self, CONTROLLER_LIMIT)
        except BaseException:
            self.close()
            raise


class FamilyJob(KillJob):
    def __init__(self, name=None):
        super().__init__(name)
        try:
            set_limits(self, FAMILY_LIMIT)
        except BaseException:
            self.close()
            raise

    def pids(self):
        class Pids(ctypes.Structure):
            _fields_ = [
                ("assigned", wintypes.DWORD),
                ("count", wintypes.DWORD),
                ("pids", ctypes.c_size_t * (FAMILY_LIMIT + 1)),
            ]

        value = Pids()
        length = wintypes.DWORD()
        ok = self.api.QueryInformationJobObject(
            self.handle,
            3,
            ctypes.byref(value),
            ctypes.sizeof(value),
            ctypes.byref(length),
        )
        require(
            ok,
            f"frontend PID query incomplete: assigned={value.assigned}, listed={value.count}, bytes={length.value}, error={ctypes.get_last_error()}",
        )
        require(
            value.assigned == value.count <= FAMILY_LIMIT
            and len(set(value.pids[: value.count])) == value.count,
            "frontend job PID inventory is incomplete or exceeds bound",
        )
        return list(value.pids[: value.count])


def frontend_environment():
    """The complete inherited environment, also pinned by the start adapter."""
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
    env.update(LANG="C", LC_ALL="C")
    return env


class _HeldProcess:
    """Retain one validated creation identity until family cleanup."""

    def __init__(self, identity, handle=None):
        self.identity, self.owned = dict(identity), handle is None
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        definitions = {
            "OpenProcess": (
                [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD],
                wintypes.HANDLE,
            ),
            "GetProcessTimes": (
                [wintypes.HANDLE, *([ctypes.c_void_p] * 4)],
                wintypes.BOOL,
            ),
            "WaitForSingleObject": ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
            "GetExitCodeProcess": ([wintypes.HANDLE, ctypes.c_void_p], wintypes.BOOL),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        }
        for name, (args, result) in definitions.items():
            function = getattr(self.api, name)
            function.argtypes, function.restype = args, result
        self.handle = (
            handle
            if handle is not None
            else self.api.OpenProcess(0x1000 | 0x100000, False, identity["pid"])
        )
        require(self.handle, "validated frontend process handle unavailable")
        try:
            stamps = [ctypes.c_uint64() for _ in range(4)]
            require(
                self.api.GetProcessTimes(
                    self.handle, *[ctypes.byref(s) for s in stamps]
                )
                and stamps[0].value == identity["created_filetime"],
                "retained frontend creation identity differs",
            )
        except BaseException:
            self.close()
            raise

    def exit_code(self):
        require(self.handle is not None, "retained frontend handle is closed")
        status = self.api.WaitForSingleObject(self.handle, 0)
        require(status in {0, 0x102}, "retained frontend wait result is unknown")
        if status == 0x102:
            return None
        code = wintypes.DWORD()
        require(
            self.api.GetExitCodeProcess(self.handle, ctypes.byref(code)),
            "retained frontend exit code unavailable",
        )
        return code.value

    def close(self):
        if self.handle is not None:
            handle, self.handle = self.handle, None
            if self.owned:
                require(
                    self.api.CloseHandle(handle),
                    "retained frontend handle did not close",
                )


class _FrontendProcess:
    """Create already-jobbed/suspended; retain bounded pipes and entire family.

    Executable/argv are supplied by a trusted caller, like the private native
    query primitive. This class deliberately supplies no native VM permissions.
    """

    def __init__(self, executable, args, name=None):
        require(sys.platform == "win32", "frontend containment requires Windows")
        import _winapi
        import msvcrt

        self.executable = Path(executable).resolve(strict=True)
        self.process = self.primary = None
        self.pid, self.identity, self.resumed = None, None, False
        self._pins = {}
        self.stdout, self.stderr, self.threads = bytearray(), bytearray(), []
        self.fault, self.terminal = threading.Event(), None
        self.job = FamilyJob(name)
        fds, inherited = [], []
        try:
            null = os.open(os.devnull, os.O_RDONLY | os.O_BINARY)
            fds.append(null)
            out_read, out_write = os.pipe()
            fds.extend((out_read, out_write))
            err_read, err_write = os.pipe()
            fds.extend((err_read, err_write))
            inherited = [
                msvcrt.get_osfhandle(fd) for fd in (null, out_write, err_write)
            ]
            for handle in inherited:
                os.set_handle_inheritable(handle, True)
            env = frontend_environment()
            self.process, self.primary, self.pid, _tid = _create_in_job(
                self.job.api,
                self.executable,
                list(args),
                inherited,
                env,
                self.job.handle,
            )
            for handle in inherited:
                os.set_handle_inheritable(handle, False)
            inherited.clear()
            for fd in (null, out_write, err_write):
                os.close(fd)
                fds.remove(fd)
            require(
                self.job.pids() == [self.pid], "frontend initial job membership differs"
            )
            self.identity = process_identity(self.pid)
            require(
                Path(self.identity["image"]).resolve() == self.executable,
                "frontend image identity differs",
            )
            self._pins[self.pid] = _HeldProcess(self.identity, self.process)

            def read(fd, target):
                try:
                    with os.fdopen(fd, "rb", buffering=0) as stream:
                        while data := stream.read(4096):
                            if len(target) + len(data) > OUTPUT_LIMIT:
                                self.fault.set()
                                return
                            target.extend(data)
                except OSError:
                    self.fault.set()

            for fd, target in ((out_read, self.stdout), (err_read, self.stderr)):
                thread = threading.Thread(target=read, args=(fd, target), daemon=True)
                thread.start()
                self.threads.append(thread)
                fds.remove(fd)
        except BaseException:
            try:
                if self.process is not None:
                    self.job.terminate()
                    _winapi.WaitForSingleObject(self.process, 500)
            finally:
                for thread in self.threads:
                    thread.join(timeout=0.5)
                self.close_handles()
            raise
        finally:
            for handle in inherited:
                try:
                    os.set_handle_inheritable(handle, False)
                except OSError:
                    pass
            for fd in fds:
                os.close(fd)

    def resume(self, gate):
        require(
            self.primary is not None and not self.resumed,
            "frontend cannot resume twice",
        )
        require(callable(gate), "frontend needs a durable admission gate")
        require(
            self.job.pids() == [self.pid]
            and process_identity(self.pid) == self.identity,
            "suspended frontend identity changed",
        )
        gate(dict(self.identity))
        require(
            not self.fault.is_set() and self.job.pids() == [self.pid],
            "frontend gate lost containment",
        )
        api = self.job.api
        api.ResumeThread.argtypes, api.ResumeThread.restype = (
            [wintypes.HANDLE],
            wintypes.DWORD,
        )
        require(
            api.ResumeThread(self.primary) == 1, "frontend primary did not resume once"
        )
        import _winapi

        _winapi.CloseHandle(self.primary)
        self.primary = None
        self.resumed = True

    def members(self, *, allow_retired=False):
        require(self.job.handle is not None, "frontend family already closed")
        exits = {}
        if allow_retired:
            for pid, pin in self._pins.items():
                exits[pid] = pin.exit_code()
                require(
                    Path(pin.identity["image"]).resolve() != self.executable
                    or exits[pid] in {None, 0},
                    "frontend exited nonzero during normal finish",
                )
        members = []
        for pid in self.job.pids():
            if allow_retired and pid in self._pins:
                if exits[pid] is None:
                    members.append(dict(self._pins[pid].identity))
                continue
            try:
                members.append(process_identity(pid))
            except (Hold, OSError) as error:
                raise Hold(
                    f"frontend family PID {pid} identity unavailable: {error}"
                ) from error
        frontends, helpers = [], []
        for row in members:
            if Path(row["image"]).resolve() == self.executable:
                frontends.append(row)
            else:
                require(
                    Path(row["image"]).resolve() == CONHOST
                    and hashlib.sha256(CONHOST.read_bytes()).hexdigest()
                    == CONHOST_SHA256,
                    "frontend family contains an unpinned helper",
                )
                helpers.append(row)
        require(
            len(frontends) <= FRONTEND_LIMIT and len(helpers) <= FRONTEND_LIMIT,
            "frontend/helper process count exceeds bound",
        )
        known = {pid: pin.identity for pid, pin in self._pins.items()}
        for row in members:
            require(
                row["pid"] not in known or known[row["pid"]] == row,
                "frontend creation identity changed",
            )
            known[row["pid"]] = row
        require(
            sum(
                Path(row["image"]).resolve() == self.executable
                for row in known.values()
            )
            <= FRONTEND_LIMIT
            and sum(
                Path(row["image"]).resolve() != self.executable
                for row in known.values()
            )
            <= FRONTEND_LIMIT,
            "cumulative frontend/helper process count exceeds bound",
        )
        for row in members:
            if row["pid"] not in self._pins:
                pin = _HeldProcess(row)
                self._pins[row["pid"]] = pin
                require(
                    pin.exit_code() is None, "new frontend retired before validation"
                )
        return members

    def poll(self):
        import _winapi

        require(self.process is not None, "frontend process handle is closed")
        status = _winapi.WaitForSingleObject(self.process, 0)
        require(status in {0, 0x102}, "frontend root wait result is unknown")
        return None if status == 0x102 else _winapi.GetExitCodeProcess(self.process)

    def retire(self):
        """Terminate any remaining family and prove local process/pipe cleanup only."""
        if self.terminal is not None:
            return self.terminal
        import _winapi

        try:
            terminated = bool(self.job.active())
            if terminated:
                self.job.terminate()
            require(
                _winapi.WaitForSingleObject(self.process, 500) == 0,
                "frontend root cleanup is unknown",
            )
            for thread in self.threads:
                thread.join(timeout=0.5)
            end = time.monotonic() + 0.5
            while self.job.active() and time.monotonic() < end:
                time.sleep(0.005)
            require(
                self.job.active() == 0
                and not self.job.pids()
                and all(not t.is_alive() for t in self.threads),
                "frontend family or pipes remain live",
            )
            self.terminal = {
                "status": "frontend-family-reaped-not-VM-poweroff-proof",
                "root_pid": self.pid,
                "root_exit": self.poll(),
                "retained_process_exits": [
                    {**pin.identity, "exit_code": pin.exit_code()}
                    for pin in self._pins.values()
                ],
                "terminated": terminated,
                "job_active_processes": 0,
                "output_fault": self.fault.is_set(),
                "stdout_bytes": len(self.stdout),
                "stderr_bytes": len(self.stderr),
                "stdout_sha256": hashlib.sha256(self.stdout).hexdigest(),
                "stderr_sha256": hashlib.sha256(self.stderr).hexdigest(),
                "native_boot_authorized": False,
            }
            return self.terminal
        finally:
            self.close_handles()

    def close_handles(self):
        import _winapi

        errors = []
        for pin in self._pins.values():
            try:
                pin.close()
            except (Hold, OSError) as error:
                errors.append(error)
        self._pins.clear()
        for name in ("primary", "process"):
            handle = getattr(self, name)
            if handle is not None:
                setattr(self, name, None)
                try:
                    _winapi.CloseHandle(handle)
                except (Hold, OSError) as error:
                    errors.append(error)
        if self.job.handle:
            try:
                self.job.close()
            except (Hold, OSError) as error:
                errors.append(error)
        if errors:
            raise Hold("frontend handle cleanup incomplete") from errors[0]


if __name__ == "__main__":
    print(
        json.dumps(
            {
                "status": "frontend-process-preparation-preview",
                "native_calls": 0,
                "native_boot_authorized": False,
                "frontend_family_limit": FAMILY_LIMIT,
                "controller_process_limit": CONTROLLER_LIMIT,
                "still_required": "original-owner boot admission and native hardening/runtime qualification",
            },
            indent=2,
        )
    )
