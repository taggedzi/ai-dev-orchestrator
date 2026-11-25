"""Prepared independent owner worker; no VM startup and no activation CLI.

A trusted outside launcher supplies an exact approved stop plan after obtaining
the suspended worker's real PID/creation identity. Ready is never VM acceptance.
"""

import ctypes
import os
import re
import sys
import time
from ctypes import wintypes
from pathlib import Path

from . import maintenance_stop as stop
from .maintenance_host import (
    OWNER_KEYS,
    RegisteredOwner,
    object_bytes,
    process_identity,
)
from .maintenance_serial import ExtendedLimits, KillJob
from .store import Store
from .supervisor import LeaseSupervisor
from .transfer_commands import canonical, digest
from .windows_readonly import require

DIRECTORY = Path(__file__).parent
SOURCES = {
    **stop.SOURCES,
    **{name: DIRECTORY / name for name in ("owner_process.py", "owner_launch.py")},
}
SOURCE_EPOCH = {name: digest(p.read_bytes()) for name, p in SOURCES.items()}


def current_sources():
    return {name: digest(p.read_bytes()) for name, p in SOURCES.items()}


def job_api():
    require(sys.platform == "win32", "independent owner requires Windows")
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    declarations = {
        "OpenJobObjectW": (
            [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR],
            wintypes.HANDLE,
        ),
        "OpenProcess": (
            [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD],
            wintypes.HANDLE,
        ),
        "IsProcessInJob": (
            [wintypes.HANDLE, wintypes.HANDLE, ctypes.c_void_p],
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
        "SetInformationJobObject": (
            [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD],
            wintypes.BOOL,
        ),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
    }
    for name, (args, result) in declarations.items():
        fn = getattr(api, name)
        fn.argtypes, fn.restype = args, result
    return api


def member(api, pid, job):
    handle = api.OpenProcess(0x1000, False, pid)
    require(handle, "job process identity unavailable")
    try:
        result = wintypes.BOOL()
        KillJob.check(api.IsProcessInJob(handle, job, ctypes.byref(result)))
        return bool(result.value)
    finally:
        KillJob.check(api.CloseHandle(handle))


def outside_controller(controller, bootstrap, job_name, identity=process_identity):
    require(
        identity(controller["pid"]) == controller
        and identity(bootstrap["pid"]) == bootstrap
        and os.getpid() != controller["pid"],
        "original controller/bootstrap process binding changed",
    )
    api = job_api()
    handle = api.OpenJobObjectW(0x4, False, job_name)  # QUERY only; never inherit it.
    require(handle, "named controller job is unavailable")
    try:
        require(
            member(api, controller["pid"], handle)
            and not member(api, os.getpid(), handle)
            and not member(api, bootstrap["pid"], handle),
            "owner/bootstrap must be outside the controller kill job",
        )
    finally:
        # Holding even a query handle could delay kill-on-last-close.
        KillJob.check(api.CloseHandle(handle))


def retain_owner_job(name):
    """Retain our own non-inheritable job handle before removing parent coupling."""
    api = job_api()
    handle = api.OpenJobObjectW(0x2 | 0x4, False, name)  # SET_ATTRIBUTES | QUERY
    require(handle, "original owner job is unavailable")
    try:
        require(
            member(api, os.getpid(), handle), "worker is outside its original owner job"
        )
        limits = ExtendedLimits()
        KillJob.check(
            api.QueryInformationJobObject(
                handle, 9, ctypes.byref(limits), ctypes.sizeof(limits), None
            )
        )
        require(
            limits.BasicLimitInformation.LimitFlags == 0x2000 | 0x8
            and limits.BasicLimitInformation.ActiveProcessLimit == 2,
            "provisional owner job limits differ",
        )
        limits.BasicLimitInformation.LimitFlags = 0x8
        KillJob.check(
            api.SetInformationJobObject(
                handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
            )
        )
        return api, handle
    except Exception:
        api.CloseHandle(handle)
        raise


def root_identity(root):
    for path in (root, *root.parents):
        state = path.lstat()
        require(
            not path.is_symlink()
            and not (getattr(state, "st_file_attributes", 0) & 0x400),
            "owner root has a link/reparse ancestor",
        )
    state = root.stat()
    return {"path": str(root), "device": state.st_dev, "inode": state.st_ino}


def read_packet(path):
    state = path.lstat()
    require(
        not path.is_symlink() and not (getattr(state, "st_file_attributes", 0) & 0x400),
        "owner packet is a link/reparse point",
    )
    with path.open("rb") as source:
        raw = source.read(65537)
    require(len(raw) <= 65536, "owner packet exceeds bound")
    return raw


def publish(path, raw):
    # Publish only completely flushed bytes; retain the exclusive staging name.
    staged = path.with_name(path.name + ".staged")
    stop.write_once(staged, raw)
    os.link(staged, path)


def checked(raw, external_sha, root, identity=process_identity):
    require(
        type(raw) is bytes and digest(raw) == external_sha,
        "owner launch digest differs",
    )
    packet = object_bytes(raw)
    require(
        set(packet)
        == {
            "format",
            "role",
            "owner_nonce",
            "owner_job",
            "controller_job",
            "controller",
            "bootstrap",
            "owner",
            "root",
            "lease",
            "profile",
            "approval",
            "sources",
        }
        and packet["format"] == "mcli1-independent-owner-v1"
        and packet["role"] in stop.VM_IDS,
        "owner launch format differs",
    )
    require(
        packet["sources"] == SOURCE_EPOCH == current_sources(),
        "owner launch source cohort changed",
    )
    require(
        isinstance(packet["owner_nonce"], str)
        and re.fullmatch(r"[0-9a-f]{32}", packet["owner_nonce"])
        and packet["owner_job"] == "Local\\MCLI1Owner-" + packet["owner_nonce"]
        and packet["controller_job"]
        == "Local\\MCLI1Controller-" + packet["owner_nonce"]
        and packet["root"] == root_identity(root)
        and packet["approval"].keys() == {"owner_start"}
        and isinstance(packet["approval"]["owner_start"], str)
        and 0 < len(packet["approval"]["owner_start"]) <= 256,
        "owner launch root/jobs/start approval differs",
    )
    require(
        identity(os.getpid()) == packet["owner"], "worker PID creation identity differs"
    )
    require(
        len({packet[k]["pid"] for k in ("owner", "controller", "bootstrap")}) == 3,
        "owner/controller/bootstrap processes must be distinct",
    )
    profile = packet["profile"]
    binding = profile["bounded_stop"]
    plan = stop.checked(canonical(binding["plan"]), binding["sha256"])
    require(
        plan["role"] == packet["role"]
        and plan["owner_nonce"] == packet["owner_nonce"]
        and plan["process"] == packet["owner"]
        and plan["lease"] == packet["lease"]
        and profile["target_vm_uuid"] == plan["target_vm_uuid"]
        and profile["lease_expires_utc_ns"] == plan["lease"]["expires_ns"]
        and profile["vboxmanage"] == plan["hypervisor"]["path"],
        "owner launch and exact original stop plan differ",
    )
    return packet


def serve(
    root,
    external_sha,
    identity=process_identity,
    independence=outside_controller,
    retain=retain_owner_job,
):
    """Run only the existing original lease/stop path; never start a VM or renew."""
    root = Path(root).resolve(strict=True)
    raw = read_packet(root / "owner.sealed.json")
    packet = checked(raw, external_sha, root, identity)
    independence(packet["controller"], packet["bootstrap"], packet["controller_job"])
    store = Store(root / "owner.sqlite")
    store.db.execute("PRAGMA busy_timeout=50")
    owner, job, failure = None, None, None
    try:
        lease = store.db.execute("SELECT * FROM lease WHERE singleton=1").fetchone()
        require(
            lease is not None
            and {k: lease[k] for k in OWNER_KEYS} == packet["lease"]
            and lease["state"] == "armed"
            and store.db.execute("SELECT active FROM authority").fetchone()[0] == 1,
            "provisional original lease changed or became inactive",
        )
        job = retain(packet["owner_job"])
        supervisor = LeaseSupervisor(store, packet["profile"])
        owner = RegisteredOwner(supervisor, packet["owner_nonce"], identity)
        expected = packet["profile"]["bounded_stop"]["plan"]["owner_binding_sha256"]
        require(
            digest(owner.binding) == expected,
            "registered owner binding differs from approved plan",
        )
        publish(
            root / "owner.ready.json",
            canonical(
                {
                    "format": "mcli1-owner-ready-v1",
                    "launch_sha256": external_sha,
                    "owner": packet["owner"],
                    "owner_binding_sha256": expected,
                    "lease": packet["lease"],
                    "stop_plan_sha256": packet["profile"]["bounded_stop"]["sha256"],
                    "controller_job_separate": True,
                    "owner_job_retained": True,
                    "observed_mono_ns": time.monotonic_ns(),
                    "VM_start_authorized": False,
                }
            ),
        )
        while True:
            try:
                require(
                    identity(packet["controller"]["pid"]) == packet["controller"],
                    "controller creation identity changed",
                )
                require(current_sources() == SOURCE_EPOCH, "owner source files changed")
            except Exception:  # noqa: BLE001 - Lost identity or source evidence revokes run authority.
                store.fence("controller unavailable or owner source changed")
            if owner.poll():
                break
            time.sleep(0.05)
        terminal = {
            "status": "original-owner-stop-command-returned-not-poweroff-acceptance",
            "launch_sha256": external_sha,
            "owner_binding_sha256": expected,
            "independent_poweroff_still_required": True,
            "finished_mono_ns": time.monotonic_ns(),
        }
        publish(root / "owner.terminal.json", canonical(terminal))
        return terminal
    except Exception as exc:
        failure = type(exc).__name__
        fence_error = None
        try:
            store.fence("original owner held; independent reconciliation required")
        except Exception as fence_exc:  # noqa: BLE001 -- a busy journal must not suppress the independent terminal record
            fence_error = type(fence_exc).__name__ + ": " + str(fence_exc)[:256]
        if not (root / "owner.terminal.json").exists():
            publish(
                root / "owner.terminal.json",
                canonical(
                    {
                        "status": "held-owner-state-not-accepted",
                        "error_type": failure,
                        "error": str(exc)[:256],
                        "fence_error": fence_error,
                        "launch_sha256": external_sha,
                    }
                ),
            )
        raise
    finally:
        store.close()
        if job is not None:
            api, handle = job
            api.CloseHandle(handle)


def worker_main(root):
    # The exact reviewed packet hash is supplied before the suspended process resumes.
    raw = sys.stdin.buffer.readline(66)
    require(re.fullmatch(rb"[0-9a-f]{64}\n", raw), "owner activation hash missing")
    serve(root, raw.strip().decode("ascii"))
