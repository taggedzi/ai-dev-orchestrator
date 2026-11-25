"""Run inside the trusted installer VM to describe the installed target."""

import base64
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def collect(target, token):
    root = Path(target)
    release = {}
    for line in (root / "etc/os-release").read_text().splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            release[key] = value.strip('"')
    if release.get("ID") != "ubuntu" or release.get("VERSION_ID") != "24.04":
        raise ValueError("unexpected installed OS")
    audit = subprocess.run(
        ["chroot", str(root), "dpkg", "--audit"],
        check=True,
        capture_output=True,
        timeout=30,
    )
    if audit.stdout.strip() or audit.stderr.strip():
        raise ValueError("package audit has unresolved findings")
    packages = subprocess.run(
        ["chroot", str(root), "dpkg-query", "-W"],
        check=True,
        capture_output=True,
        timeout=30,
    ).stdout
    architecture = (
        subprocess.run(
            ["chroot", str(root), "dpkg", "--print-architecture"],
            check=True,
            capture_output=True,
            timeout=30,
        )
        .stdout.decode()
        .strip()
    )
    if architecture != "amd64":
        raise ValueError("unexpected installed architecture")
    kernels = sorted(path.name for path in (root / "boot").glob("vmlinuz-*"))
    if not kernels:
        raise ValueError("no installed kernel files")
    identity = next(
        row.split(":")
        for row in (root / "etc/passwd").read_text().splitlines()
        if row.startswith("fixture:")
    )
    if int(identity[2]) == 0:
        raise ValueError("fixture operator must not be root")
    result = {
        "schema_version": 1,
        "token": token,
        "os_release": release,
        "architecture": architecture,
        "kernel_files": kernels,
        "package_inventory_sha256": hashlib.sha256(packages).hexdigest(),
        "package_rows": len(packages.splitlines()),
        "operator_uid": int(identity[2]),
        "classification": "installed target inspected from installer; first boot not verified",
    }
    directory = root / "var/lib/mcli1"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "packages.tsv").write_bytes(packages)
    raw = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    with (directory / "image-install.json").open("wb") as output:
        output.write(raw + b"\n")
        output.flush()
        os.fsync(output.fileno())
    with open("/dev/ttyS0", "w") as serial:
        serial.write(
            "\nMCLI1_OS_INSTALLED "
            + token
            + " "
            + base64.b64encode(raw).decode()
            + "\n"
        )
        serial.flush()
    return result


if __name__ == "__main__":
    collect(sys.argv[1], sys.argv[2])
