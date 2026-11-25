"""Standalone, hash-bound transfer entry. Default previews without guest I/O."""

import base64
import hashlib
import json
import os
import re
import stat
import sys
import time
import types
from pathlib import Path

PROBE_SHA = "598837d6ef704d54716b9982660d6b0377bae690a3a26a9570f55a4586969c99"
CONTROL_SHA = "6b01cd7ca8e27ae56ed55d1817e336c2a2d5cdab4a667916557bd8347dc70391"
MAX_REPORT = 512 * 1024


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def read_identity():
    # Also compiled verbatim into the first read-only serial command.
    import json
    import os
    import subprocess
    import sys
    import time

    if sys.flags.optimize:
        raise RuntimeError("identity checks require the fixed isolated invocation")

    def text(path):
        with open(path) as source:
            value = source.read(129).strip()
        assert len(value) <= 128
        return value

    assert sys.platform == "linux" and os.geteuid() == 0
    assert not any(s in os.uname().release.lower() for s in ("wsl", "microsoft"))
    assert text("/proc/1/comm") == "systemd"
    assert sorted(os.listdir("/sys/class/net")) == ["lo"]
    mount = json.loads(
        subprocess.check_output(
            [
                "/usr/bin/findmnt",
                "--json",
                "--output",
                "TARGET,FSTYPE,UUID",
                "--target",
                "/",
            ],
            timeout=5,
            stderr=subprocess.DEVNULL,
            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C", "LC_ALL": "C"},
        )
    )
    assert len(mount["filesystems"]) == 1
    row = mount["filesystems"][0]
    assert row["target"] == "/" and row["fstype"] == "ext4" and not row.get("children")
    root = os.stat("/")
    namespace = os.stat("/proc/self/ns/mnt").st_ino
    assert namespace == os.stat("/proc/1/ns/mnt").st_ino and root.st_ino == 2
    return {
        "dmi_uuid": text("/sys/class/dmi/id/product_uuid").lower(),
        "root_fs_uuid": row["uuid"],
        "boot_id": text("/proc/sys/kernel/random/boot_id"),
        "root_dev": root.st_dev,
        "root_ino": root.st_ino,
        "mnt_ino": namespace,
        "guest_utc_ns": time.time_ns(),
        "guest_mono_ns": time.monotonic_ns(),
    }


def open_stage(path):
    require(
        re.fullmatch(r"/run/mcli1-(observe|control)-[0-9a-f]{32}", path),
        "unexpected transfer stage",
    )
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    run = os.open("/run", flags)
    try:
        info = os.fstat(run)
        require(
            info.st_uid == 0 and not stat.S_IMODE(info.st_mode) & 0o022,
            "unsafe run directory",
        )
        fd = os.open(path.rsplit("/", 1)[1], flags, dir_fd=run)
    finally:
        os.close(run)
    info = os.fstat(fd)
    if info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o700:
        os.close(fd)
        raise ValueError("unsafe transfer directory")
    return fd


def private_read(directory, name, limit):
    require(
        re.fullmatch(r"[a-z][a-z_.-]*", name) and "/" not in name,
        "invalid transfer member",
    )
    fd = os.open(
        name,
        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
        dir_fd=directory,
    )
    with os.fdopen(fd, "rb") as source:
        info = os.fstat(source.fileno())
        require(
            stat.S_ISREG(info.st_mode)
            and info.st_uid == 0
            and info.st_nlink == 1
            and stat.S_IMODE(info.st_mode) == 0o600,
            "unsafe transfer member",
        )
        data = source.read(limit + 1)
    require(len(data) <= limit, "transfer member exceeds bound")
    return data


def load(raw, path):
    module = types.ModuleType("mcli1_bound_transfer_member")
    module.__file__ = path
    exec(compile(raw, path, "exec"), module.__dict__)  # noqa: S102 - Caller verifies fixed source hashes first.
    return module


def live(capsule):
    window = capsule["guest_window"]
    require(
        window["issued_utc_ns"] <= time.time_ns() < window["expires_utc_ns"]
        and window["issued_mono_ns"] <= time.monotonic_ns() < window["expires_mono_ns"],
        "guest transfer window expired or clock moved",
    )


def execute(stage, capsule_sha):
    identity = read_identity()
    directory = open_stage(stage)
    try:
        raw = private_read(directory, "capsule.json", 64 * 1024)
        require(digest(raw) == capsule_sha, "transfer capsule changed")
        capsule = json.loads(raw)
        require(
            capsule["format"] == "mcli1-transfer-capsule-v1",
            "transfer capsule format changed",
        )
        expected = {
            "guest_transfer_entry.py",
            "guest_maintenance_probe.py",
            "inspection-spec.json",
        }
        if capsule["purpose"] == "controls":
            expected |= {
                "guest_maintenance_control.py",
                "request.json",
                "observation.json",
            }
        require(
            capsule["purpose"] in ("inspect", "controls")
            and set(capsule["files"]) == expected,
            "transfer capsule members changed",
        )
        require(
            all(
                set(row) == {"bytes", "sha256"}
                and type(row["bytes"]) is int
                and 0 <= row["bytes"] <= 1024**2
                and isinstance(row["sha256"], str)
                and re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
                for row in capsule["files"].values()
            ),
            "transfer member limits changed",
        )
        require(
            stage
            == "/run/mcli1-"
            + ("observe" if capsule["purpose"] == "inspect" else "control")
            + "-"
            + capsule["run_nonce"],
            "transfer stage changed",
        )
        live(capsule)
        require(
            all(
                identity[k] == capsule["identity"][k]
                for k in (
                    "dmi_uuid",
                    "root_fs_uuid",
                    "boot_id",
                    "root_dev",
                    "root_ino",
                    "mnt_ino",
                )
            ),
            "guest transfer identity changed",
        )
        blobs = {}
        for name, expected in capsule["files"].items():
            data = private_read(directory, name, expected["bytes"])
            require(
                len(data) == expected["bytes"] and digest(data) == expected["sha256"],
                "transfer member changed",
            )
            blobs[name] = data
        require(
            digest(blobs["guest_maintenance_probe.py"]) == PROBE_SHA
            and digest(blobs["guest_transfer_entry.py"])
            == digest(Path(__file__).read_bytes()),
            "transfer sources changed",
        )
        probe = load(
            blobs["guest_maintenance_probe.py"], stage + "/guest_maintenance_probe.py"
        )
        spec = probe.checked_spec(
            blobs["inspection-spec.json"],
            capsule["files"]["inspection-spec.json"]["sha256"],
        )
        require(
            spec["run_nonce"] == capsule["run_nonce"],
            "transfer inspection nonce changed",
        )
        if capsule["purpose"] == "inspect":
            require(
                set(blobs)
                == {
                    "guest_transfer_entry.py",
                    "guest_maintenance_probe.py",
                    "inspection-spec.json",
                },
                "unexpected inspection members",
            )
            reader = probe.NativeReader()
            reader.deadline = min(
                reader.deadline, capsule["guest_window"]["expires_mono_ns"] / 10**9
            )
            result = probe.inspect(spec, reader)
        else:
            require(
                capsule["purpose"] == "controls"
                and set(blobs)
                == {
                    "guest_transfer_entry.py",
                    "guest_maintenance_probe.py",
                    "guest_maintenance_control.py",
                    "inspection-spec.json",
                    "request.json",
                    "observation.json",
                },
                "unexpected control members",
            )
            require(
                digest(blobs["guest_maintenance_control.py"]) == CONTROL_SHA,
                "control source changed",
            )
            control = load(
                blobs["guest_maintenance_control.py"],
                stage + "/guest_maintenance_control.py",
            )
            request = control.checked_request(
                blobs["request.json"], capsule["files"]["request.json"]["sha256"]
            )
            require(
                request["window"]["expires_mono_ns"]
                <= capsule["guest_window"]["expires_mono_ns"]
                and request["window"]["expires_utc_ns"]
                <= capsule["guest_window"]["expires_utc_ns"],
                "control window exceeds original transfer authority",
            )
            result = control.apply_packet(
                stage, capsule["files"]["request.json"]["sha256"]
            )
        live(capsule)
        return {
            "format": "mcli1-transfer-result-v1",
            "purpose": capsule["purpose"],
            "run_nonce": capsule["run_nonce"],
            "grant_sha256": capsule["grant_sha256"],
            "capsule_sha256": capsule_sha,
            "result": result,
        }
    finally:
        os.close(directory)


def main():
    if len(sys.argv) == 1:
        print(json.dumps({"status": "unarmed-preview", "mutations": 0}))
        return
    require(len(sys.argv) == 4, "transfer entry arguments changed")
    capsule_sha, serial_nonce, index = sys.argv[1:]
    require(
        re.fullmatch(r"[0-9a-f]{64}", capsule_sha)
        and re.fullmatch(r"[0-9a-f]{32}", serial_nonce)
        and index.isdecimal(),
        "invalid transfer entry binding",
    )
    raw = canonical(execute(str(Path(__file__).absolute().parent), capsule_sha))
    require(len(raw) <= MAX_REPORT, "transfer report exceeds bound")
    for offset in range(0, len(raw), 512):
        print(
            "MCLI1_DATA_"
            + serial_nonce
            + "_"
            + index
            + ":"
            + base64.b64encode(raw[offset : offset + 512]).decode(),
            flush=True,
        )
    print("MCLI1_ACK_" + serial_nonce + "_" + index, flush=True)


if __name__ == "__main__":
    main()
