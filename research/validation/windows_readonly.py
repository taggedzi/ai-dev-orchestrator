"""Bounded Windows query processes, started suspended inside a one-process job.

The public VBoxQueries boundary permits only three fixed read-only command shapes.
There is no VM-control or generic command-line entry point.
"""

import ctypes
import hashlib
import os
import re
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path
from uuid import UUID

from .maintenance_serial import KillJob
from .store import Hold

MAX_OUTPUT = 64 * 1024
VBOX = Path(r"C:\Program Files\Oracle\VirtualBox\VBoxManage.exe")
VERSION = "7.2.22r175245"


class StartupInfo(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        *[
            (name, wintypes.DWORD)
            for name in (
                "dwX",
                "dwY",
                "dwXSize",
                "dwYSize",
                "dwXCountChars",
                "dwYCountChars",
                "dwFillAttribute",
                "dwFlags",
            )
        ],
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class ExtendedStartup(ctypes.Structure):
    _fields_ = [("startup", StartupInfo), ("attributes", ctypes.c_void_p)]


class ProcessInfo(ctypes.Structure):
    _fields_ = [
        ("process", wintypes.HANDLE),
        ("thread", wintypes.HANDLE),
        ("pid", wintypes.DWORD),
        ("tid", wintypes.DWORD),
    ]


def _create_in_job(api, executable, args, handles, env, job_handle):
    """Assign at creation, removing the parent-death gap before job assignment."""
    definitions = {
        "InitializeProcThreadAttributeList": (
            [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p],
            wintypes.BOOL,
        ),
        "UpdateProcThreadAttribute": (
            [
                ctypes.c_void_p,
                wintypes.DWORD,
                ctypes.c_size_t,
                ctypes.c_void_p,
                ctypes.c_size_t,
                ctypes.c_void_p,
                ctypes.c_void_p,
            ],
            wintypes.BOOL,
        ),
        "DeleteProcThreadAttributeList": ([ctypes.c_void_p], None),
        "CreateProcessW": (
            [
                wintypes.LPCWSTR,
                wintypes.LPWSTR,
                ctypes.c_void_p,
                ctypes.c_void_p,
                wintypes.BOOL,
                wintypes.DWORD,
                ctypes.c_void_p,
                wintypes.LPCWSTR,
                ctypes.c_void_p,
                ctypes.c_void_p,
            ],
            wintypes.BOOL,
        ),
    }
    for name, (argtypes, restype) in definitions.items():
        function = getattr(api, name)
        function.argtypes, function.restype = argtypes, restype
    size = ctypes.c_size_t()
    api.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(size))
    require(size.value > 0, "native process attribute size unavailable")
    attributes = ctypes.create_string_buffer(size.value)
    KillJob.check(
        api.InitializeProcThreadAttributeList(attributes, 2, 0, ctypes.byref(size))
    )
    try:
        inherited = (wintypes.HANDLE * len(handles))(*handles)
        jobs = (wintypes.HANDLE * 1)(job_handle)
        for key, value in ((0x20002, inherited), (0x2000D, jobs)):
            KillJob.check(
                api.UpdateProcThreadAttribute(
                    attributes,
                    0,
                    key,
                    value,
                    ctypes.sizeof(value),
                    None,
                    None,
                )
            )
        startup = ExtendedStartup()
        startup.startup.cb = ctypes.sizeof(startup)
        startup.startup.dwFlags = subprocess.STARTF_USESTDHANDLES
        (
            startup.startup.hStdInput,
            startup.startup.hStdOutput,
            startup.startup.hStdError,
        ) = handles
        startup.attributes = ctypes.addressof(attributes)
        command = ctypes.create_unicode_buffer(
            subprocess.list2cmdline([str(executable), *args])
        )
        environment = ctypes.create_unicode_buffer(
            "\0".join(
                f"{k}={v}" for k, v in sorted(env.items(), key=lambda kv: kv[0].upper())
            )
            + "\0\0"
        )
        info = ProcessInfo()
        KillJob.check(
            api.CreateProcessW(
                str(executable),
                command,
                None,
                None,
                True,
                0x4 | 0x400 | 0x80000 | subprocess.CREATE_NO_WINDOW,
                environment,
                str(Path(executable).parent),
                ctypes.byref(startup),
                ctypes.byref(info),
            )
        )
        return info.process, info.thread, info.pid, info.tid
    finally:
        api.DeleteProcThreadAttributeList(attributes)


def require(condition, message):
    if not condition:
        raise Hold(message)


def live(wall_deadline, mono_deadline):
    require(
        time.time_ns() < wall_deadline and time.monotonic_ns() < mono_deadline,
        "native query deadline expired",
    )


def _run(executable, args, wall_deadline, mono_deadline, before_resume=None):
    """Private process primitive. Callers must supply their own fixed argv policy."""
    require(sys.platform == "win32", "bounded native queries require Windows")
    import _winapi
    import msvcrt

    live(wall_deadline, mono_deadline)
    require(
        0 < mono_deadline - time.monotonic_ns() <= 4 * 10**9
        and 0 < wall_deadline - time.time_ns() <= 4 * 10**9,
        "native query budget exceeds four seconds",
    )
    job = KillJob()
    handles, fds, threads = [], [], []
    process = primary = None
    stdout, stderr = bytearray(), bytearray()
    fault = threading.Event()
    started = time.monotonic_ns()
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.ResumeThread.argtypes, api.ResumeThread.restype = (
        [wintypes.HANDLE],
        wintypes.DWORD,
    )

    def read(fd, target):
        try:
            with os.fdopen(fd, "rb", buffering=0) as pipe:
                while data := pipe.read(4096):
                    if len(target) + len(data) > MAX_OUTPUT:
                        fault.set()
                        return
                    target.extend(data)
        except OSError:
            fault.set()

    try:
        null = os.open(os.devnull, os.O_RDONLY | os.O_BINARY)
        out_read, out_write = os.pipe()
        err_read, err_write = os.pipe()
        fds.extend([null, out_read, out_write, err_read, err_write])
        handles = [msvcrt.get_osfhandle(fd) for fd in (null, out_write, err_write)]
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
        env.update(LANG="C", LC_ALL="C")
        live(wall_deadline, mono_deadline)
        process, primary, pid, _tid = _create_in_job(
            api,
            executable,
            args,
            handles,
            env,
            job.handle,
        )
        for handle in handles:
            os.set_handle_inheritable(handle, False)
        for fd in (null, out_write, err_write):
            os.close(fd)
            fds.remove(fd)
        handles.clear()  # Closed handle values can be reused by another host thread.
        require(job.active() == 1, "query job membership differs before resume")
        if before_resume is not None:
            before_resume(pid)  # Test hook, never supplied by VBoxQueries.
        live(wall_deadline, mono_deadline)
        for fd, target in ((out_read, stdout), (err_read, stderr)):
            thread = threading.Thread(target=read, args=(fd, target), daemon=True)
            thread.start()
            threads.append(thread)
            fds.remove(fd)
        require(
            api.ResumeThread(primary) == 1, "query primary thread did not resume once"
        )
        _winapi.CloseHandle(primary)
        primary = None
        while _winapi.WaitForSingleObject(process, 0) == 0x102:
            live(wall_deadline, mono_deadline)
            require(
                not fault.is_set(), "native query output exceeds bound or pipe failed"
            )
            time.sleep(0.005)
        for thread in threads:
            thread.join(timeout=0.25)
        live(wall_deadline, mono_deadline)
        require(
            not fault.is_set() and all(not t.is_alive() for t in threads),
            "native query streams not reaped",
        )
        code = _winapi.GetExitCodeProcess(process)
        while job.active():
            live(wall_deadline, mono_deadline)
            time.sleep(0.005)
        require(job.active() == 0, "native query process remains in job")
        return {
            "stdout": bytes(stdout),
            "stderr": bytes(stderr),
            "exit": code,
            "pid": pid,
            "started_mono_ns": started,
            "finished_mono_ns": time.monotonic_ns(),
            "job_active_processes": 0,
        }
    finally:
        try:
            if process is not None:
                if _winapi.WaitForSingleObject(process, 0) == 0x102:
                    # Also covers assignment failure while the primary remains suspended.
                    _winapi.TerminateProcess(process, 2)
                    job.terminate()
                require(
                    _winapi.WaitForSingleObject(process, 500) == 0,
                    "native query process cleanup unknown",
                )
            for thread in threads:
                thread.join(timeout=0.25)
            cleanup_deadline = time.monotonic() + 0.5
            while job.active() and time.monotonic() < cleanup_deadline:
                time.sleep(0.005)
            require(
                all(not t.is_alive() for t in threads) and job.active() == 0,
                "native query cleanup incomplete",
            )
        finally:
            for handle in handles:
                try:
                    os.set_handle_inheritable(handle, False)
                except OSError:
                    pass  # Child-side handles were already closed in the normal path.
            for fd in fds:
                os.close(fd)
            if primary is not None:
                _winapi.CloseHandle(primary)
            if process is not None:
                _winapi.CloseHandle(process)
            job.close()


class VBoxQueries:
    def __init__(self, executable_sha256, targets, runner=_run):
        require(
            isinstance(executable_sha256, str)
            and re.fullmatch(r"[0-9a-f]{64}", executable_sha256),
            "reviewed VBoxManage digest required",
        )
        self.digest = executable_sha256
        self.targets = frozenset(str(UUID(t)) for t in targets)
        self.runner = runner

    def __call__(self, kind, target, wall_deadline, mono_deadline):
        if kind == "version":
            require(target is None, "version query has no target")
            args = ["--version"]
        else:
            require(target in self.targets, "unreviewed query target")
            if kind == "machine":
                args = ["showvminfo", target, "--machinereadable"]
            elif kind == "disk":
                args = ["showmediuminfo", "disk", target]
            else:
                raise Hold("query command shape is not read-only")
        live(wall_deadline, mono_deadline)
        require(
            not os.environ.get("VBOX_USER_HOME")
            and hashlib.sha256(VBOX.read_bytes()).hexdigest() == self.digest,
            "VBoxManage bytes or configuration root changed",
        )
        result = self.runner(VBOX, args, wall_deadline, mono_deadline)
        require(
            result["exit"] == 0
            and not result["stderr"]
            and result["job_active_processes"] == 0
            and len(result["stdout"]) <= MAX_OUTPUT,
            "read-only VBox query failed or was not reaped",
        )
        if kind == "version":
            require(
                result["stdout"].strip() == VERSION.encode(), "VBox version changed"
            )
        return result
