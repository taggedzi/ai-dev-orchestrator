"""Bounded Windows serial worker and unarmed review preparation.

This is an I/O primitive, not VM admission. A trusted caller must bind authority,
persist possible-send before start, signal revocation and independently stop the VM.
"""

import argparse
import base64
import ctypes
import json
import os
import re
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path

from . import maintenance_serial_worker as worker
from .offline_repo import description, new_root, write_json
from .store import Hold


class BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class IOCounters(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", BasicLimits),
        ("IoInfo", IOCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class Accounting(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_int64)
        for name in (
            "TotalUserTime",
            "TotalKernelTime",
            "ThisPeriodTotalUserTime",
            "ThisPeriodTotalKernelTime",
        )
    ] + [
        (name, wintypes.DWORD)
        for name in (
            "TotalPageFaultCount",
            "TotalProcesses",
            "ActiveProcesses",
            "TotalTerminatedProcesses",
        )
    ]


class KillJob:
    """Non-inheritable, kill-on-close Job Object with one active process."""

    def __init__(self, job_name=None):
        worker.require(sys.platform == "win32", "native serial job requires Windows")
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        definitions = {
            "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
            "SetInformationJobObject": (
                [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD],
                wintypes.BOOL,
            ),
            "AssignProcessToJobObject": (
                [wintypes.HANDLE, wintypes.HANDLE],
                wintypes.BOOL,
            ),
            "QueryInformationJobObject": (
                [
                    wintypes.HANDLE,
                    ctypes.c_int,
                    ctypes.c_void_p,
                    wintypes.DWORD,
                    ctypes.c_void_p,
                ],
                wintypes.BOOL,
            ),
            "TerminateJobObject": ([wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        }
        for name, (args, result) in definitions.items():
            function = getattr(self.api, name)
            function.argtypes, function.restype = args, result
        ctypes.set_last_error(0)
        self.handle = self.api.CreateJobObjectW(None, job_name)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        if job_name and ctypes.get_last_error() == 183:
            self.close()
            raise worker.Refuse("serial job name already exists; do not reuse it")
        limits = ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = (
            0x2000 | 0x8
        )  # KILL_ON_JOB_CLOSE | ACTIVE_PROCESS
        limits.BasicLimitInformation.ActiveProcessLimit = 1
        try:
            self.check(
                self.api.SetInformationJobObject(
                    self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
                )
            )
        except Exception:
            self.close()
            raise

    @staticmethod
    def check(result):
        if not result:
            raise ctypes.WinError(ctypes.get_last_error())

    def assign(self, process):
        self.check(self.api.AssignProcessToJobObject(self.handle, int(process._handle)))

    def active(self):
        info = Accounting()
        self.check(
            self.api.QueryInformationJobObject(
                self.handle, 1, ctypes.byref(info), ctypes.sizeof(info), None
            )
        )
        return info.ActiveProcesses

    def terminate(self):
        self.check(self.api.TerminateJobObject(self.handle, 2))

    def close(self):
        if self.handle:
            handle, self.handle = self.handle, None
            self.check(self.api.CloseHandle(handle))


def persist_intent(store, raw, external_sha, generation):
    request = worker.checked(raw, external_sha)
    if not store.db.execute("PRAGMA database_list").fetchone()["file"]:
        raise Hold("serial intent requires a durable journal")
    operation = "serial:" + request["request_id"]
    store.begin(operation, external_sha, generation)
    return {"operation": operation, "request_sha256": external_sha}


def run_request(raw, external_sha, before_start, cancelled=None):
    """Start only after durable intent; never retry a transfer or infer acceptance."""
    request = worker.checked(raw, external_sha)
    worker.require(sys.platform == "win32", "serial transport requires Windows")
    worker.require(callable(before_start), "durable intent callback required")
    worker.live(request)
    worker.require(
        request["expires_utc_ns"] - time.time_ns() <= 90 * 10**9
        and request["expires_mono_ns"] - time.monotonic_ns() <= 90 * 10**9,
        "serial request exceeds bounded window",
    )
    cancelled = cancelled if cancelled is not None else threading.Event()
    worker.require(not cancelled.is_set(), "serial authority revoked")
    proof = before_start()
    worker.require(
        proof
        == {
            "operation": "serial:" + request["request_id"],
            "request_sha256": external_sha,
        },
        "serial durable intent binding changed",
    )
    worker.live(request)
    worker.require(not cancelled.is_set(), "serial authority revoked")
    child, threads, stdout, stderr = None, [], bytearray(), bytearray()
    assigned = False
    fault = threading.Event()
    job = KillJob("Local\\MCLI1Serial-" + request["request_id"])
    try:
        child = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-B",
                str(Path(worker.__file__).resolve()),
                "--worker",
                external_sha,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            close_fds=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
            env={
                k: v
                for k, v in os.environ.items()
                if k.upper() in {"SYSTEMROOT", "TEMP", "TMP"}
            },
        )
        # The trusted worker cannot touch the serial channel until stdin arrives.
        job.assign(child)
        assigned = True

        def read(pipe, output):
            try:
                while chunk := pipe.read(4096):
                    if len(output) + len(chunk) > worker.MAX_CONSOLE:
                        fault.set()
                        return
                    output.extend(chunk)
            except OSError:
                fault.set()

        def write():
            try:
                with child.stdin:
                    child.stdin.write(raw + b"\n")
            except OSError:
                fault.set()

        for function, args in (
            (read, (child.stdout, stdout)),
            (read, (child.stderr, stderr)),
        ):
            thread = threading.Thread(target=function, args=args, daemon=True)
            threads.append(thread)
            thread.start()
        worker.live(request)
        worker.require(not cancelled.is_set(), "serial authority revoked")
        thread = threading.Thread(target=write, daemon=True)
        threads.append(thread)
        thread.start()
        while child.poll() is None:
            worker.live(request)
            worker.require(not cancelled.is_set(), "serial authority revoked")
            worker.require(not fault.is_set(), "serial worker pipe/output fault")
            time.sleep(0.01)
        for thread in threads:
            thread.join(timeout=1)
        worker.require(
            all(not t.is_alive() for t in threads), "serial worker streams not reaped"
        )
        worker.require(
            not fault.is_set() and child.returncode == 0 and not stderr,
            "serial worker held; delivery uncertain",
        )
        worker.live(request)
        worker.require(not cancelled.is_set(), "serial authority revoked")
        result = json.loads(stdout)
        worker.require(
            set(result)
            == {
                "status",
                "request_id",
                "acknowledged_steps",
                "console_bytes",
                "console_sha256",
                "data_base64",
                "data_sha256",
            },
            "serial receipt fields changed",
        )
        worker.require(
            result["request_id"] == request["request_id"]
            and result["status"] == "serial-exchange-reported-not-accepted"
            and result["acknowledged_steps"] == [s["ack"] for s in request["steps"]],
            "serial worker receipt binding changed",
        )
        worker.require(
            type(result["console_bytes"]) is int
            and 0 <= result["console_bytes"] <= worker.MAX_CONSOLE
            and isinstance(result["console_sha256"], str)
            and re.fullmatch(r"[0-9a-f]{64}", result["console_sha256"])
            and isinstance(result["data_base64"], str),
            "serial receipt sizes or digest malformed",
        )
        data = base64.b64decode(result["data_base64"], validate=True)
        worker.require(
            len(data) <= worker.MAX_DATA
            and worker.digest(data) == result["data_sha256"],
            "serial result data digest changed",
        )
        worker.require(job.active() == 0, "serial job has an unreaped process")
        return {
            **result,
            "worker_pid": child.pid,
            "worker_exit": child.returncode,
            "job_active_processes": 0,
            "intent": proof,
        }
    finally:
        try:
            if child is not None:
                if child.poll() is None:
                    if assigned:
                        job.terminate()
                    else:
                        child.kill()  # Assignment failure leaves the stdin gate closed.
                child.wait(timeout=2)
                for thread in threads:
                    thread.join(timeout=1)
                for pipe in (child.stdin, child.stdout, child.stderr):
                    pipe.close()
                worker.require(job.active() == 0, "serial job cleanup incomplete")
        finally:
            job.close()


def run_journaled(store, raw, external_sha, generation, cancelled=None):
    """Retain uncertainty and fence authority after a started/attempted handoff."""
    attempted = False

    def begin():
        nonlocal attempted
        attempted = True
        return persist_intent(store, raw, external_sha, generation)

    try:
        result = run_request(raw, external_sha, begin, cancelled)
        with store.transaction():
            store._event(
                "serial-exchange-reported",
                {
                    "operation": result["intent"]["operation"],
                    "console_sha256": result["console_sha256"],
                    "data_sha256": result["data_sha256"],
                    "job_active_processes": result["job_active_processes"],
                    "possible_send_retained": True,
                },
            )
        return result
    except Exception:
        if attempted:
            store.fence("serial outcome uncertain; stop and reconcile without replay")
        raise


def draft(role):
    target = worker.TARGETS[0 if role == "executor" else 1]
    return {
        "format": "mcli1-serial-exchange-v1",
        "mode": "guest",
        "request_id": None,
        "target_vm_uuid": target,
        "pipe": "\\\\.\\pipe\\mcli1-maint-" + target,
        "steps": [],
        "activation_reference": None,
        "worker_sha256": worker.digest(Path(worker.__file__).read_bytes()),
        "expires_utc_ns": None,
        "expires_mono_ns": None,
    }


def prepare(role, output):
    root = new_root(output)
    request = draft(role)
    raw = worker.encode(request)
    (root / "request.json").write_bytes(raw)
    for source in (Path(__file__), Path(worker.__file__)):
        (root / source.name).write_bytes(source.read_bytes())
    try:
        worker.checked(raw, worker.digest(raw))
    except worker.Refuse as exc:
        refusal = str(exc)
    else:
        raise Hold("unarmed serial request unexpectedly passed")
    review = {
        "status": "unarmed-serial-primitive-review",
        "role": role,
        "request": description(root / "request.json"),
        "refusal": refusal,
        "sources": {
            p.name: description(root / p.name)
            for p in (Path(__file__), Path(worker.__file__))
        },
        "native_calls": 0,
        "guest_commands_generated": False,
        "vm_configuration_available": False,
        "installation_authority": None,
        "still_required": [
            "Exact VM/UART/root-session/backup and immutable supervisor authority admission",
            "Scoped transfer/observation approval and frozen identity-gated command sequence",
            "Trusted revocation signaling and independent VM stop/reap",
            "Independent VM stop/reconciliation after run_journaled fences an uncertain outcome; no replay",
            "Guest control executor, full admission observations and native target qualification",
        ],
    }
    write_json(root / "review.json", review)
    return review


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=("guard", "executor"), default="guard")
    parser.add_argument("--prepare")
    args = parser.parse_args()
    result = (
        prepare(args.role, args.prepare)
        if args.prepare
        else {
            "status": "unarmed-preview",
            "request": draft(args.role),
            "native_calls": 0,
        }
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
