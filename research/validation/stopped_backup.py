"""Copy stopped preparation VM files into a new unattached local backup.

Default CLI is a review only. Capture runs fixed read-only VBox queries and file
copies; it has no VM mutation, disk registration, mount or restore operation.
"""

import argparse
import ctypes
import hashlib
import json
import os
import stat
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path, PureWindowsPath
from uuid import uuid4

from . import backup_records as records
from . import maintenance_host as host
from . import owner_process as owner
from . import windows_readonly as native
from .offline_repo import description, new_root, write_json
from .os_install import WORKSPACE
from .transfer_commands import canonical, digest

require = records.require
ROOT = WORKSPACE
SLOTS = {
    "guard": {
        "vm_uuid": "0eceb37e-f216-45ed-817c-7cf2fca3a32a",
        "disk_uuid": "a8f47315-d330-4b28-bbb0-6a721b4c6251",
        "disk_sha256": "a8a6024499644999738f089546096e93174a336c003f2d1ae841214c2fe22c43",
        "folder": "mcli1-guard-01",
        "disk": "guard-base.vdi",
        "inventory": "guard",
        "medium": "guard-disk",
    },
    "executor": {
        "vm_uuid": "74129e9c-5a65-44fa-9d35-79d458dc4704",
        "disk_uuid": "e832fc9c-23cc-40a8-8e66-fa0c624b8bd9",
        "disk_sha256": "2eb1d9cd009ecfe83381d855137f5cee8c1317739f6209beddd6da8a10955a09",
        "folder": "mcli1-validation-01",
        "disk": "installation.vdi",
        "inventory": "source",
        "medium": "source-disk",
    },
}
SOURCES = {
    **owner.SOURCES,
    "stopped_backup.py": Path(__file__),
    "backup_records.py": Path(records.__file__),
    "offline_repo.py": Path(new_root.__code__.co_filename),
}
SOURCE_EPOCH = {n: digest(p.read_bytes()) for n, p in SOURCES.items()}


def safe(path):
    path = Path(os.path.abspath(path))
    path.relative_to(ROOT)
    for part in (path, *path.parents):
        if part.exists() or part.is_symlink():
            info = part.lstat()
            require(
                not stat.S_ISLNK(info.st_mode)
                and not (getattr(info, "st_file_attributes", 0) & 0x400),
                "linked/reparse backup path",
            )
        if part == ROOT:
            break
    return path


def source_paths(role):
    slot = SLOTS[role]
    folder = ROOT / ".local/validation/vms" / slot["folder"]
    return {
        "disk": safe(folder / slot["disk"]),
        "configuration": safe(folder / (slot["folder"] + ".vbox")),
        "nvram": safe(folder / (slot["folder"] + ".nvram")),
    }


def file_identity(info):
    return {"device": info.st_dev, "inode": info.st_ino}


def file_state(path):
    if not path.exists():
        return {"state": "absent"}
    info = path.lstat()
    require(
        stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
        "backup source is not a single-link regular file",
    )
    with path.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"state": "file", "bytes": info.st_size, "sha256": sha}


def draft(role):
    slot = SLOTS[role]
    paths = source_paths(role)
    observed = ROOT / ".local/validation/guard-provision-observe-01"
    files = {
        "disk": {
            "state": "file",
            "bytes": paths["disk"].stat().st_size,
            "sha256": slot["disk_sha256"],
        },
        "configuration": file_state(paths["configuration"]),
        "nvram": file_state(paths["nvram"]),
    }
    return {
        "format": "mcli1-stopped-backup-plan-v2",
        "role": role,
        "target_vm_uuid": slot["vm_uuid"],
        "source_disk_uuid": slot["disk_uuid"],
        "expected_files": files,
        "machine_sha256": digest(
            (observed / (slot["inventory"] + ".stdout")).read_bytes()
        ),
        "medium_sha256": digest((observed / (slot["medium"] + ".stdout")).read_bytes()),
        "never_attach": True,
        "VM_mutations": 0,
        "sources": dict(SOURCE_EPOCH),
    }


def checked(raw, sha):
    require(type(raw) is bytes and digest(raw) == sha, "backup plan digest differs")
    plan = host.object_bytes(raw)
    require(
        set(plan)
        == {
            "format",
            "role",
            "target_vm_uuid",
            "source_disk_uuid",
            "expected_files",
            "machine_sha256",
            "medium_sha256",
            "never_attach",
            "VM_mutations",
            "sources",
        }
        and plan["format"] == "mcli1-stopped-backup-plan-v2"
        and plan["role"] in SLOTS,
        "backup plan fields differ",
    )
    slot = SLOTS[plan["role"]]
    require(
        plan["target_vm_uuid"] == slot["vm_uuid"]
        and plan["source_disk_uuid"] == slot["disk_uuid"]
        and plan["never_attach"] is True
        and type(plan["VM_mutations"]) is int
        and plan["VM_mutations"] == 0,
        "backup scope differs",
    )
    require(
        plan["sources"]
        == SOURCE_EPOCH
        == {n: digest(p.read_bytes()) for n, p in SOURCES.items()},
        "backup source cohort changed",
    )
    require(
        records.hash_value(plan["machine_sha256"])
        and records.hash_value(plan["medium_sha256"]),
        "backup stopped inventory is unbound",
    )
    files = plan["expected_files"]
    require(
        set(files) == {"disk", "configuration", "nvram"}, "backup file cohort differs"
    )
    for label, value in files.items():
        if label == "nvram":
            records.nvram_record(value)
        else:
            maximum = 36 * 1024**3 if label == "disk" else 1024**2
            require(
                set(value) == {"state", "bytes", "sha256"}
                and value["state"] == "file"
                and type(value["bytes"]) is int
                and 0 < value["bytes"] <= maximum
                and records.hash_value(value["sha256"]),
                "backup source file is unbound",
            )
    require(
        files["disk"]["sha256"] == slot["disk_sha256"], "backup source image changed"
    )
    return plan


def observe(role):
    slot = SLOTS[role]
    queries = native.VBoxQueries(
        owner.stop.EXE_SHA, (slot["vm_uuid"], slot["disk_uuid"])
    )
    outputs, metadata = {}, []
    started = time.monotonic_ns()
    for label, kind, target in (
        ("version", "version", None),
        ("before", "machine", slot["vm_uuid"]),
        ("medium", "disk", slot["disk_uuid"]),
        ("after", "machine", slot["vm_uuid"]),
    ):
        result = queries(
            kind, target, time.time_ns() + 4 * 10**9, time.monotonic_ns() + 4 * 10**9
        )
        outputs[label] = result["stdout"]
        metadata.append(
            {k: v for k, v in result.items() if k not in {"stdout", "stderr"}}
        )
    require(outputs["before"] == outputs["after"], "backup VM changed during inventory")
    return {
        "observed_mono_ns": started,
        "machine": outputs["after"],
        "medium": outputs["medium"],
        "queries": metadata,
    }


def checked_observation(plan, frame):
    require(
        0 <= time.monotonic_ns() - frame["observed_mono_ns"] <= 5 * 10**9
        and type(frame["machine"]) is bytes
        and len(frame["machine"]) <= 32768
        and type(frame["medium"]) is bytes
        and len(frame["medium"]) <= 32768,
        "backup observation is stale or unbounded",
    )
    require(
        digest(frame["machine"]) == plan["machine_sha256"]
        and digest(frame["medium"]) == plan["medium_sha256"],
        "backup stopped inventory changed",
    )
    machine, medium = (
        host.machine_fields(frame["machine"]),
        host.medium_fields(frame["medium"]),
    )
    paths = source_paths(plan["role"])
    require(
        machine["UUID"] == plan["target_vm_uuid"]
        and machine["VMState"] == "poweroff"
        and all(machine[f"nic{n}"] == "none" for n in range(1, 9))
        and machine["SATA-ImageUUID-0-0"] == medium["UUID"] == plan["source_disk_uuid"]
        and medium["Parent UUID"] == "base"
        and medium["Type"] == "normal (base)"
        and medium["State"] == "created"
        and PureWindowsPath(medium["Location"]) == PureWindowsPath(paths["disk"])
        and PureWindowsPath(machine["CfgFile"])
        == PureWindowsPath(paths["configuration"])
        and PureWindowsPath(machine["NvramFile"]) == PureWindowsPath(paths["nvram"]),
        "backup target is not the fixed stopped/disconnected base image",
    )
    return {
        "observed_mono_ns": frame["observed_mono_ns"],
        "machine_sha256": digest(frame["machine"]),
        "medium_sha256": digest(frame["medium"]),
    }


@contextmanager
def locked_source(path):
    """Windows share-read excludes writers/deletion while the handle is retained."""
    require(os.name == "nt", "backup capture requires Windows source share locks")
    import msvcrt
    from ctypes import wintypes

    path = safe(path)
    before = path.lstat()
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    api.CreateFileW.restype = wintypes.HANDLE
    api.CloseHandle.argtypes, api.CloseHandle.restype = [wintypes.HANDLE], wintypes.BOOL
    handle = api.CreateFileW(str(path), 0x80000000, 1, None, 3, 0x00200000, None)
    require(
        handle not in (None, ctypes.c_void_p(-1).value),
        "backup source cannot be read-locked",
    )
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        api.CloseHandle(handle)
        raise
    with os.fdopen(fd, "rb", buffering=0) as stream:
        info = os.fstat(stream.fileno())
        require(
            stat.S_ISREG(info.st_mode)
            and info.st_nlink == 1
            and file_identity(info) == file_identity(before),
            "backup source identity changed",
        )
        yield stream


def copy_file(source, destination, expected, deadline):
    initial = os.fstat(source.fileno())
    require(
        stat.S_ISREG(initial.st_mode)
        and initial.st_nlink == 1
        and initial.st_size == expected["bytes"],
        "backup source size/type/links changed",
    )
    checksum, count = hashlib.sha256(), 0
    with destination.open("xb") as output:
        while data := source.read(1024**2):
            require(time.monotonic() < deadline, "backup copy time budget expired")
            count += len(data)
            require(count <= expected["bytes"], "backup source grew")
            output.write(data)
            checksum.update(data)
        output.flush()
        os.fsync(output.fileno())
    require(
        count == expected["bytes"] and checksum.hexdigest() == expected["sha256"],
        "backup source bytes changed",
    )
    with destination.open("rb") as copied:
        require(
            hashlib.file_digest(copied, "sha256").hexdigest() == expected["sha256"],
            "backup readback differs",
        )
    source.seek(0)
    require(
        hashlib.file_digest(source, "sha256").hexdigest() == expected["sha256"],
        "backup source changed after copying",
    )
    return {
        "source_identity": file_identity(initial),
        "backup_identity": file_identity(destination.stat()),
    }


def capture(raw, sha, output, probe=observe, locker=locked_source):
    plan = checked(raw, sha)
    before = probe(plan["role"])
    first = checked_observation(plan, before)
    root = new_root(output)
    paths = source_paths(plan["role"])
    receipt = {
        "format": records.RECEIPT_FORMAT,
        "backup_id": uuid4().hex,
        "role": plan["role"],
        "target_vm_uuid": plan["target_vm_uuid"],
        "source_disk_uuid": plan["source_disk_uuid"],
        "source_poweroff": True,
        "independent": True,
        "never_attach": True,
        "files": {},
        "plan_sha256": sha,
        "first_observation": first,
        "sources": dict(SOURCE_EPOCH),
    }
    (root / "plan.json").write_bytes(raw)
    write_json(
        root / "intent.json", {"plan_sha256": sha, "state": "copying-not-accepted"}
    )
    with ExitStack() as stack:
        opened = {}
        for label, path in paths.items():
            if plan["expected_files"][label]["state"] == "file":
                opened[label] = stack.enter_context(locker(path))
            else:
                require(
                    not path.exists() and not path.is_symlink(), "absent NVRAM appeared"
                )
        deadline = time.monotonic() + 120
        for label, path in paths.items():
            expected = plan["expected_files"][label]
            row = {**expected, "source_relative": path.relative_to(ROOT).as_posix()}
            if expected["state"] == "file":
                dest = safe(
                    root
                    / {
                        "disk": "disk.vdi",
                        "configuration": "configuration.vbox",
                        "nvram": "nvram.bin",
                    }[label]
                )
                identities = copy_file(opened[label], dest, expected, deadline)
                require(
                    identities["source_identity"] != identities["backup_identity"],
                    "backup aliases the source",
                )
                row.update(
                    identities, backup_relative=dest.relative_to(ROOT).as_posix()
                )
            else:
                row["backup_relative"] = None
            receipt["files"][label] = row
        final_frame = probe(plan["role"])
        receipt["last_observation"] = checked_observation(plan, final_frame)
        for label, frame in (("before", before), ("after", final_frame)):
            for kind in ("machine", "medium"):
                with (root / (label + "-" + kind + ".stdout")).open("xb") as evidence:
                    evidence.write(frame[kind])
                    evidence.flush()
                    os.fsync(evidence.fileno())
            write_json(root / (label + "-queries.json"), frame.get("queries", []))
        checked(raw, sha)
        for label, path in paths.items():
            safe(path)
            if label in opened:
                require(
                    file_identity(path.stat())
                    == file_identity(os.fstat(opened[label].fileno())),
                    "backup source path was replaced",
                )
            else:
                require(
                    not path.exists() and not path.is_symlink(), "absent NVRAM appeared"
                )
        receipt.update(
            status="stopped-backup-reported-not-boot-authority",
            completed_utc_ns=time.time_ns(),
        )
        wire = canonical(receipt)
        owner.publish(root / "receipt.json", wire)
        result = records.binding(receipt, digest(wire))
        write_json(root / "binding.json", result)
    return {
        "status": receipt["status"],
        "receipt": description(root / "receipt.json"),
        "binding": result,
        "VM_mutations": 0,
        "native_boot_authorized": False,
    }


def verify_files(raw, sha):
    require(type(raw) is bytes and digest(raw) == sha, "backup receipt digest differs")
    receipt = host.object_bytes(raw)
    require(
        receipt["format"] == records.RECEIPT_FORMAT and receipt["never_attach"] is True,
        "backup receipt format differs",
    )
    records.binding(receipt, sha)
    identities = set()
    for row in receipt["files"].values():
        if row["state"] == "absent":
            require(row["backup_relative"] is None, "absent file has a backup path")
            continue
        path = safe(ROOT / row["backup_relative"])
        require(
            path != safe(ROOT / row["source_relative"]), "backup path aliases source"
        )
        with locked_source(path) as stream:
            info = os.fstat(stream.fileno())
            identity = file_identity(info)
            key = (identity["device"], identity["inode"])
            require(
                stat.S_ISREG(info.st_mode)
                and info.st_nlink == 1
                and identity == row["backup_identity"]
                and identity != row["source_identity"]
                and key not in identities
                and info.st_size == row["bytes"]
                and hashlib.file_digest(stream, "sha256").hexdigest() == row["sha256"],
                "backup identity/bytes changed",
            )
            identities.add(key)
    return records.binding(receipt, sha)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=tuple(SLOTS), default="guard")
    parser.add_argument("--capture", metavar="OUTPUT")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--plan-sha256")
    args = parser.parse_args()
    if args.capture:
        require(
            args.plan is not None and args.plan_sha256 is not None,
            "capture requires exact reviewed plan bytes/hash",
        )
        result = capture(args.plan.read_bytes(), args.plan_sha256, args.capture)
    else:
        result = {
            "status": "stopped-backup-preview",
            "native_calls": 0,
            "VM_mutations": 0,
            "plan": draft(args.role),
        }
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
