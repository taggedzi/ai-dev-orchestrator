"""Standalone, read-only Linux maintenance inspection; default is a preview.

The host prepares the external spec digest. No service, package or file mutation
is implemented. Never treat a guest monotonic timestamp as a host timestamp.
"""

import argparse
import hashlib
import json
import os
import platform
import re
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path
from uuid import UUID

FORMAT = "mcli1-guest-maintenance-inspection-v1"
PROPOSAL = "42b91618b6f35639aee882e9654a7e8df20ef530b6cc5de23663f2400141d232"
STATUS = "b9f366f301a3ae82652a1bb983c905c53e325d78e44b831ed8da16a4176190b4"
MAX_BYTES = 2 * 1024**2
UNIT_PROPERTIES = (
    "Id,Names,LoadState,ActiveState,SubState,UnitFileState,FragmentPath,DropInPaths"
)


class Refuse(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Refuse(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def uuid(value):
    try:
        return isinstance(value, str) and str(UUID(value)) == value
    except ValueError:
        return False


def checked_spec(raw, external_sha):
    require(len(raw) <= MAX_BYTES and sha(raw) == external_sha, "spec digest changed")
    spec = json.loads(raw)
    require(
        set(spec)
        == {
            "format",
            "role",
            "run_nonce",
            "target",
            "approval",
            "program_sha256",
            "proposal_sha256",
            "masks",
            "policy",
            "private_paths",
            "config_files",
        },
        "inspection spec fields changed",
    )
    require(spec["format"] == FORMAT, "unsupported inspection spec")
    require(spec["role"] in ("guard", "executor"), "unknown inspection role")
    require(spec["proposal_sha256"] == PROPOSAL, "procedure changed")
    require(spec["program_sha256"] == sha(Path(__file__).read_bytes()), "probe changed")
    require(
        isinstance(spec["run_nonce"], str)
        and re.fullmatch(r"[0-9a-f]{32}", spec["run_nonce"]),
        "inspection nonce is unbound",
    )
    target = spec["target"]
    require(
        set(target) == {"dmi_uuid", "root_fs_uuid", "boot_id"}, "target fields changed"
    )
    require(all(uuid(v) for v in target.values()), "inspection target is unbound")
    require(
        set(spec["approval"]) == {"boot", "observation"}
        and all(
            isinstance(v, str)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", v)
            for v in spec["approval"].values()
        ),
        "inspection approval is unbound",
    )
    masks = spec["masks"]
    require(
        isinstance(masks, list)
        and len(masks) == len(set(masks))
        and 1 <= len(masks) <= 64
        and all(
            re.fullmatch(r"[a-z0-9][a-z0-9.-]*\.(service|socket|timer)", v)
            for v in masks
        ),
        "invalid unit names",
    )
    require(
        spec["policy"]
        == {
            "path": "/usr/sbin/policy-rc.d",
            "content": "#!/bin/sh\nexit 101\n",
            "mode": 0o755,
        },
        "policy changed",
    )
    require(
        isinstance(spec["private_paths"], list)
        and len(spec["private_paths"]) == len(set(spec["private_paths"]))
        and all(
            re.fullmatch(
                r"/(run|var/(cache|lib|log))/mcli1-maintenance(/[a-z][a-z.]*)*", p
            )
            for p in spec["private_paths"]
        ),
        "private path escaped maintenance directories",
    )
    require(
        set(spec["config_files"])
        == {
            "/run/mcli1-maintenance/apt.config",
            "/run/mcli1-maintenance/apt/sources.list",
            "/run/mcli1-maintenance/apt/apt.conf",
            "/run/mcli1-maintenance/apt/preferences",
        },
        "configuration destinations changed",
    )
    require(
        all(isinstance(v, str) for v in spec["config_files"].values()),
        "invalid config bytes",
    )
    return spec


def one_mount(raw, path):
    rows = json.loads(raw)["filesystems"]
    require(len(rows) == 1 and not rows[0].get("children"), "ambiguous mount")
    row = rows[0]
    require(
        set(row) >= {"target", "source", "fstype", "uuid", "options", "maj:min"},
        "mount fields missing",
    )
    require(
        path.startswith(row["target"].rstrip("/") + "/") or row["target"] == path,
        "mount target changed",
    )
    return row


def unit_properties(raw, unit):
    result = {}
    for line in raw.splitlines():
        require("=" in line, "malformed unit property")
        key, value = line.split("=", 1)
        require(key not in result, "duplicate unit property")
        result[key] = value
    require(set(result) == set(UNIT_PROPERTIES.split(",")), "unit properties missing")
    require(
        result["Id"] == unit or unit in result["Names"].split(), "unit identity changed"
    )
    return result


class NativeReader:
    """Fixed read-only commands with a shared deadline and bounded pipe reads."""

    def __init__(self, seconds=60):
        self.deadline = time.monotonic() + seconds

    def remaining(self):
        left = self.deadline - time.monotonic()
        require(left > 0, "guest inspection deadline")
        return left

    def read(self, path, limit=MAX_BYTES):
        self.remaining()
        # O_NONBLOCK prevents a replaced FIFO from blocking before fstat.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as source:
            require(stat.S_ISREG(os.fstat(source.fileno()).st_mode), "nonregular input")
            raw = source.read(limit + 1)
        require(len(raw) <= limit, "input exceeds inspection limit")
        return raw

    def metadata(self, path):
        self.remaining()
        p = Path(path)
        # Reject redirected ancestors of configuration/control paths.
        for parent in p.parents:
            if parent.is_symlink():
                raise Refuse("control/configuration ancestor is a symlink")
        try:
            info = p.lstat()
        except FileNotFoundError:
            return {"kind": "absent"}
        result = {"uid": info.st_uid, "mode": stat.S_IMODE(info.st_mode)}
        if stat.S_ISLNK(info.st_mode):
            return {**result, "kind": "symlink", "target": os.readlink(p)}
        if stat.S_ISREG(info.st_mode):
            return {**result, "kind": "file", "sha256": sha(self.read(path))}
        require(stat.S_ISDIR(info.st_mode), "special control/configuration path")
        return {**result, "kind": "directory"}

    def command(self, argv):
        import select

        self.remaining()
        # Bind the operation and every option, not just the executable name.
        allowed = argv == ["/usr/bin/dpkg", "--audit"] or argv == [
            "/usr/bin/findmnt",
            "--json",
            "--output",
            "TARGET,SOURCE,FSTYPE,UUID,OPTIONS,MAJ:MIN",
            "--target",
            "/",
        ]
        allowed = allowed or (
            len(argv) == 6
            and argv[:5]
            == [
                "/usr/bin/systemctl",
                "--no-pager",
                "show",
                "--all",
                "--property=" + UNIT_PROPERTIES,
            ]
            and re.fullmatch(r"[a-z0-9][a-z0-9.-]*\.(service|socket|timer)", argv[5])
        )
        require(allowed, "command outside read-only inspection allowlist")
        child = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={
                "PATH": "/usr/sbin:/usr/bin:/sbin:/bin",
                "LANG": "C",
                "LC_ALL": "C",
                "SYSTEMD_PAGER": "cat",
            },
            start_new_session=True,
        )
        result = {child.stdout: bytearray(), child.stderr: bytearray()}
        pending = list(result)
        deadline = min(self.deadline, time.monotonic() + 5)
        try:
            for pipe in pending:
                os.set_blocking(pipe.fileno(), False)
            while pending:
                require(time.monotonic() < deadline, "inspection command deadline")
                ready, _, _ = select.select(
                    pending, [], [], min(0.1, max(0, deadline - time.monotonic()))
                )
                for pipe in ready:
                    chunk = os.read(pipe.fileno(), 4096)
                    if not chunk:
                        pending.remove(pipe)
                        continue
                    result[pipe].extend(chunk)
                    require(
                        sum(len(v) for v in result.values()) <= MAX_BYTES,
                        "inspection command output limit",
                    )
            code = child.wait(timeout=max(0.001, deadline - time.monotonic()))
            stdout, stderr = (
                bytes(result[p]).decode("utf-8") for p in (child.stdout, child.stderr)
            )
            require(code == 0 and not stderr, "inspection command failed or warned")
            return stdout
        finally:
            # Reap the fixed query and terminate any descendants still in its group.
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait(timeout=1)
            child.stdout.close()
            child.stderr.close()

    def mount(self, path):
        return one_mount(
            self.command(
                [
                    "/usr/bin/findmnt",
                    "--json",
                    "--output",
                    "TARGET,SOURCE,FSTYPE,UUID,OPTIONS,MAJ:MIN",
                    "--target",
                    path,
                ]
            ),
            path,
        )

    def configurations(self):
        paths = ["/etc/dpkg/dpkg.cfg"]
        directory = Path("/etc/dpkg/dpkg.cfg.d")
        info = self.metadata(str(directory))
        require(
            info["kind"] in ("absent", "directory"),
            "dpkg configuration directory changed",
        )
        if info["kind"] == "directory":
            paths += [str(p) for p in sorted(directory.iterdir())]
        require(len(paths) <= 64, "too many dpkg configuration files")
        result = {}
        for path in paths:
            info = self.metadata(path)
            require(
                info["kind"] in ("absent", "file"),
                "unexpected dpkg configuration entry",
            )
            row = {"metadata": info}
            if info["kind"] == "file":
                data = self.read(path)
                require(
                    sha(data) == info["sha256"], "dpkg configuration changed while read"
                )
                row["content"] = data.decode("utf-8")
            result[path] = row
        return result

    def interfaces(self):
        self.remaining()
        return sorted(p.name for p in Path("/sys/class/net").iterdir())

    def apt_identity(self):
        import pwd

        self.remaining()
        account = pwd.getpwnam("_apt")
        return {"name": account.pw_name, "uid": account.pw_uid, "gid": account.pw_gid}

    def processes(self):
        packages, runtimes = [], []
        for path in Path("/proc").iterdir():
            if not path.name.isdecimal():
                continue
            try:
                comm = self.read(str(path / "comm"), 256).decode().strip()
            except FileNotFoundError:
                continue  # A process may exit between enumeration and reading comm.
            if comm in {
                "apt",
                "apt-get",
                "dpkg",
                "dpkg-deb",
                "unattended-upgr",
                "packagekitd",
                "snap",
                "snapd",
            }:
                packages.append({"pid": int(path.name), "comm": comm})
            if comm in {
                "dockerd",
                "containerd",
                "containerd-shim",
                "runc",
            } or comm.startswith("containerd-shim"):
                runtimes.append({"pid": int(path.name), "comm": comm})
        return packages, runtimes


def inspect(spec, reader, system=sys.platform, uid=None, kernel=None):
    # These checks precede native queries and reads beyond the external spec.
    require(system == "linux", "inspection requires the selected Linux guest")
    require(
        (os.geteuid() if uid is None else uid) == 0, "inspection requires guest root"
    )
    release = platform.release() if kernel is None else kernel
    require(
        not any(x in release.lower() for x in ("wsl", "microsoft")),
        "WSL is not the selected guest",
    )
    require(
        reader.read("/proc/1/comm", 256).strip() == b"systemd", "PID 1 is not systemd"
    )
    actual = {
        "dmi_uuid": reader.read("/sys/class/dmi/id/product_uuid", 128)
        .decode()
        .strip()
        .lower(),
        "boot_id": reader.read("/proc/sys/kernel/random/boot_id", 128).decode().strip(),
    }
    root = reader.mount("/")
    actual["root_fs_uuid"] = root["uuid"]
    require(
        actual == spec["target"] and root["fstype"] == "ext4",
        "guest boot/root identity differs",
    )
    require(reader.interfaces() == ["lo"], "guest is not disconnected")
    before = reader.read("/var/lib/dpkg/status")
    require(sha(before) == STATUS, "original package baseline changed")
    units = {}
    for unit in spec["masks"]:
        props = unit_properties(
            reader.command(
                [
                    "/usr/bin/systemctl",
                    "--no-pager",
                    "show",
                    "--all",
                    "--property=" + UNIT_PROPERTIES,
                    unit,
                ]
            ),
            unit,
        )
        units[unit] = {
            "properties": props,
            "admin": reader.metadata("/etc/systemd/system/" + unit),
            "helper": reader.metadata(
                "/var/lib/systemd/deb-systemd-helper-masked/" + unit
            ),
        }
    audit = reader.command(["/usr/bin/dpkg", "--audit"])
    require(audit == "", "dpkg audit is not empty")
    package_processes, runtime_processes = reader.processes()
    require(
        reader.read("/var/lib/dpkg/status") == before,
        "package state changed during inspection",
    )
    private_paths = {
        p: reader.metadata(p)
        for p in spec["private_paths"] + list(spec["config_files"])
    }
    return {
        "format": FORMAT,
        "status": "observed-not-admitted",
        "role": spec["role"],
        "run_nonce": spec["run_nonce"],
        "target": actual,
        "kernel_release": release,
        "baseline_status_sha256": sha(before),
        "audit_stdout": audit,
        "units": units,
        "policy": reader.metadata(spec["policy"]["path"]),
        "private_paths": private_paths,
        "dpkg_configurations": reader.configurations(),
        "apt_sandbox_user": reader.apt_identity(),
        "package_processes": package_processes,
        "runtime_processes": runtime_processes,
        "guest_finished_mono_ns": time.monotonic_ns(),
        "mutations": 0,
        "host_timestamp_or_authority": False,
    }


def control_plan(spec, observed):
    """Describe changes only; the returned actions have no execution backend."""
    require(
        observed["format"] == FORMAT and observed["role"] == spec["role"],
        "inspection role changed",
    )
    require(
        observed["target"] == spec["target"]
        and observed["run_nonce"] == spec["run_nonce"],
        "inspection target/nonce changed",
    )
    require(
        observed["baseline_status_sha256"] == STATUS and not observed["audit_stdout"],
        "baseline/audit changed",
    )
    require(
        not observed["package_processes"] and not observed["runtime_processes"],
        "package/runtime activity requires review",
    )
    require(set(observed["units"]) == set(spec["masks"]), "unit inventory changed")
    expected_policy = {
        "kind": "file",
        "uid": 0,
        "mode": spec["policy"]["mode"],
        "sha256": sha(spec["policy"]["content"].encode()),
    }
    require(
        observed["policy"] in ({"kind": "absent"}, expected_policy),
        "existing policy differs",
    )
    changes, stop = [], []
    if observed["policy"]["kind"] == "absent":
        changes.append({"action": "create-exclusive-file", **spec["policy"]})
    for unit in spec["masks"]:
        state = observed["units"][unit]
        require(
            state["helper"] == {"kind": "absent"},
            "helper mask state exists; do not erase it",
        )
        admin, props = state["admin"], state["properties"]
        matching = (
            admin.get("kind") == "symlink"
            and admin.get("uid") == 0
            and admin.get("target") == "/dev/null"
        )
        require(admin == {"kind": "absent"} or matching, "administrator unit conflicts")
        require(not props["DropInPaths"], "unit drop-ins require review")
        names = set(props["Names"].split())
        require(
            names <= set(spec["masks"]) and unit in names, "unit aliases require review"
        )
        require(
            props["ActiveState"] in ("active", "inactive"),
            "unit transition/failure requires review",
        )
        if matching:
            require(
                props["LoadState"] == "masked" and props["FragmentPath"] == "/dev/null",
                "admin mask is not effective",
            )
        else:
            require(
                props["LoadState"] in ("loaded", "not-found"),
                "unexpected effective unit state",
            )
            changes.append(
                {
                    "action": "create-exclusive-symlink",
                    "path": "/etc/systemd/system/" + unit,
                    "target": "/dev/null",
                }
            )
        if props["ActiveState"] == "active":
            stop.append(unit)
    require(
        all(v == {"kind": "absent"} for v in observed["private_paths"].values()),
        "private configuration already exists; no overwrite/replay",
    )
    require(
        set(observed["private_paths"])
        == set(spec["private_paths"]) | set(spec["config_files"]),
        "private path inventory changed",
    )
    changes.append(
        {"action": "reviewed-command", "argv": ["/usr/bin/systemctl", "daemon-reload"]}
    )
    # Mask before stopping; stop timers/sockets before their service actors.
    for suffix in (".timer", ".socket", ".service"):
        names = sorted(x for x in stop if x.endswith(suffix))
        if names:
            changes.append(
                {
                    "action": "reviewed-command",
                    "argv": ["/usr/bin/systemctl", "--no-ask-password", "stop", *names],
                }
            )
    account = observed["apt_sandbox_user"]
    require(
        set(account) == {"name", "uid", "gid"}
        and account["name"] == "_apt"
        and type(account["uid"]) is int
        and 0 < account["uid"] < 1000
        and type(account["gid"]) is int
        and account["gid"] > 0,
        "APT sandbox account requires review",
    )
    for path in spec["private_paths"]:
        acquisition = path.startswith(("/var/lib/", "/var/cache/"))
        partial = acquisition and path.endswith("/partial")
        changes.append(
            {
                "action": "create-exclusive-directory",
                "path": path,
                "uid": account["uid"] if partial else 0,
                "gid": account["gid"] if partial else 0,
                "mode": 0o755 if acquisition and not partial else 0o700,
            }
        )
    changes += [
        {"action": "create-exclusive-file", "path": p, "content": data, "mode": 0o600}
        for p, data in sorted(spec["config_files"].items())
    ]
    return {
        "status": "proposed-not-executed",
        "run_nonce": spec["run_nonce"],
        "actions": changes,
        "dpkg_configuration_review_required": observed["dpkg_configurations"],
        "before_install_still_required": [
            "Explicit control-change authority, independent VM lease and stop enforcement",
            "Review exact dpkg configuration bytes and all relevant unit activation paths",
            "Recheck effective masks, quiescence and no Docker socket/group authority",
            "Verify mounted ISO and every member; reserve space by actual filesystem",
            "Validate actual APT dump, signed file-only refresh, exact live simulation and archive hashes",
            "Measure _apt access to list/archive staging and media; hold on root sandbox fallback",
        ],
        "executor_available": False,
        "installation_authority": None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observe")
    parser.add_argument("--spec-sha256")
    args = parser.parse_args()
    if args.observe:
        spec = checked_spec(Path(args.observe).read_bytes(), args.spec_sha256)
        result = inspect(spec, NativeReader())
    else:
        require(args.spec_sha256 is None, "spec digest requires --observe")
        result = {
            "status": "preview",
            "native_queries": 0,
            "mutations": 0,
            "apply_available": False,
        }
    raw = json.dumps(result, sort_keys=True)
    require(len(raw.encode()) <= MAX_BYTES, "inspection report exceeds output limit")
    print(raw)


if __name__ == "__main__":
    main()
