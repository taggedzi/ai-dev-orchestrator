"""Collect first-boot observations as the non-root fixture operator."""

import base64
import hashlib
import json
import os
import platform
import pwd
import subprocess
import sys
from pathlib import Path


def command(arguments, timeout=30):
    result = subprocess.run(
        arguments, capture_output=True, check=False, timeout=timeout
    )
    return {
        "exit": result.returncode,
        "stdout": result.stdout.decode("utf-8", errors="replace"),
        "stderr": result.stderr.decode("utf-8", errors="replace"),
    }


def collect(token):
    release = {}
    for line in Path("/etc/os-release").read_text().splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            release[key] = value.strip('"')
    cloud = command(["cloud-init", "status", "--wait", "--format=json"], timeout=180)
    try:
        cloud["report"] = json.loads(cloud["stdout"][cloud["stdout"].index("{") :])
    except (ValueError, KeyError):
        cloud["report"] = None
    packages = subprocess.run(
        ["dpkg-query", "-W"], check=True, capture_output=True, timeout=30
    ).stdout
    audit = command(["dpkg", "--audit"])
    ssh = command(["dpkg-query", "-W", "-f=${Status}", "openssh-server"])
    root_mount = next(
        line.split()[:4]
        for line in Path("/proc/mounts").read_text().splitlines()
        if line.split()[1] == "/"
    )
    result = {
        "schema_version": 1,
        "token": token,
        "os_release": release,
        "running_kernel": platform.release(),
        "machine": platform.machine(),
        "python_version": platform.python_version(),
        "uid": os.getuid(),
        "fixture_uid": pwd.getpwnam("fixture").pw_uid,
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        "command_line": Path("/proc/cmdline").read_text().strip(),
        "root_mount": root_mount,
        "interfaces": sorted(path.name for path in Path("/sys/class/net").iterdir()),
        "cloud_init": cloud,
        "package_audit": audit,
        "package_inventory_sha256": hashlib.sha256(packages).hexdigest(),
        "package_rows": len(packages.splitlines()),
        "ssh_server_installed": ssh["exit"] == 0
        and ssh["stdout"] == "install ok installed",
        "cgroup_v2": Path("/sys/fs/cgroup/cgroup.controllers").is_file(),
        "classification": "guest-reported base OS boot observations; not independent containment evidence",
    }
    raw = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    print(
        "\nMCLI1_BOOT_RESULT " + token + " " + base64.b64encode(raw).decode(),
        flush=True,
    )
    return result


if __name__ == "__main__":
    collect(sys.argv[1])
