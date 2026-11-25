"""Standalone guest control executor. Default is an unarmed preview.

This changes only reviewed maintenance controls under separate authority. It
cannot install packages, remove controls, repair partial state or reboot a VM.
"""

import argparse
import base64
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
import types
from pathlib import Path

PROBE_SHA256 = "598837d6ef704d54716b9982660d6b0377bae690a3a26a9570f55a4586969c99"
STATE = "/var/lib/mcli1-maintenance-control"
MAX_BYTES = 2 * 1024**2
MAX_COMMAND = 64 * 1024


class Refuse(ValueError):
    pass


def require(value, message):
    if not value:
        raise Refuse(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def stable(observed):
    return {k: v for k, v in observed.items() if k != "guest_finished_mono_ns"}


def platform_guard(system=sys.platform, uid=None, release=None):
    require(system == "linux", "controls require the selected Linux guest")
    require((os.geteuid() if uid is None else uid) == 0, "controls require guest root")
    release = platform.release() if release is None else release
    require(
        not any(s in release.lower() for s in ("wsl", "microsoft")),
        "WSL is not a control target",
    )


def checked_request(raw, external_sha):
    require(
        len(raw) <= MAX_BYTES and sha(raw) == external_sha,
        "control request digest changed",
    )
    request = json.loads(raw)
    require(
        set(request)
        == {
            "format",
            "run_nonce",
            "role",
            "program_sha256",
            "probe_sha256",
            "spec_sha256",
            "observation_sha256",
            "stable_observation_sha256",
            "plan_sha256",
            "dpkg_configuration_sha256",
            "host_intent_receipt_sha256",
            "approval",
            "window",
        },
        "control request fields changed",
    )
    require(
        request["format"] == "mcli1-guest-control-v1", "control request format changed"
    )
    require(request["role"] in ("guard", "executor"), "unsupported control role")
    require(
        set(request["approval"])
        == {
            "boot",
            "transfer",
            "observation",
            "control_changes",
            "backup",
            "dpkg_configuration_review",
        }
        and all(
            isinstance(v, str)
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", v)
            for v in request["approval"].values()
        ),
        "control approval is unbound",
    )
    require(
        isinstance(request["run_nonce"], str)
        and re.fullmatch(r"[0-9a-f]{32}", request["run_nonce"]),
        "control nonce is unbound",
    )
    require(
        all(
            isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v)
            for k, v in request.items()
            if k.endswith("sha256")
        ),
        "control input digest is unbound",
    )
    require(
        request["program_sha256"] == sha(Path(__file__).read_bytes())
        and request["probe_sha256"] == PROBE_SHA256,
        "control programs changed",
    )
    require(
        set(request["window"])
        == {"issued_utc_ns", "issued_mono_ns", "expires_utc_ns", "expires_mono_ns"},
        "control window fields changed",
    )
    require(
        all(type(v) is int for v in request["window"].values()),
        "guest control window is unbound",
    )
    for clock in ("utc", "mono"):
        require(
            0
            < request["window"]["expires_" + clock + "_ns"]
            - request["window"]["issued_" + clock + "_ns"]
            <= 60 * 10**9,
            "control window exceeds sixty seconds",
        )
    return request


def check_window(request, wall_ns=time.time_ns, mono_ns=time.monotonic_ns):
    window = request["window"]
    for clock, now in (("utc", wall_ns()), ("mono", mono_ns())):
        require(
            window["issued_" + clock + "_ns"]
            <= now
            < window["expires_" + clock + "_ns"],
            "control authority expired or clock moved",
        )


class OwnedTree:
    """Directory-relative, exclusive POSIX operations; never follows ancestors."""

    def __init__(self, root="/", owner=0):
        self.owner = owner
        self.flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        self.fd = os.open(root, self.flags)
        try:
            self.check_directory(self.fd)
        except Exception:
            os.close(self.fd)
            raise

    def close(self):
        os.close(self.fd)

    @staticmethod
    def components(path):
        require(
            isinstance(path, str) and path.startswith("/"),
            "control path must be absolute",
        )
        parts = path[1:].split("/")
        require(
            all(
                p not in ("", ".", "..") and re.fullmatch(r"[A-Za-z0-9._-]+", p)
                for p in parts
            ),
            "control path escaped its root",
        )
        return parts

    def check_directory(self, fd):
        info = os.fstat(fd)
        require(
            stat.S_ISDIR(info.st_mode)
            and info.st_uid == self.owner
            and not stat.S_IMODE(info.st_mode) & 0o022,
            "control ancestor ownership/mode changed",
        )

    def directory(self, parts):
        fd = os.dup(self.fd)
        try:
            for part in parts:
                next_fd = os.open(part, self.flags, dir_fd=fd)
                os.close(fd)
                fd = next_fd
                self.check_directory(fd)
            return fd
        except Exception:
            os.close(fd)
            raise

    def parent(self, path):
        parts = self.components(path)
        return self.directory(parts[:-1]), parts[-1]

    @staticmethod
    def write_all(fd, data):
        remaining = memoryview(data)
        while remaining:
            written = os.write(fd, remaining)
            require(written > 0, "control file write made no progress")
            remaining = remaining[written:]

    def read(self, path, maximum=MAX_BYTES):
        parent, name = self.parent(path)
        fd = None
        try:
            fd = os.open(
                name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                dir_fd=parent,
            )
            info = os.fstat(fd)
            require(
                stat.S_ISREG(info.st_mode)
                and info.st_uid == self.owner
                and info.st_nlink == 1
                and not stat.S_IMODE(info.st_mode) & 0o022,
                "control input ownership/type/links changed",
            )
            data = bytearray()
            while chunk := os.read(fd, min(65536, maximum + 1 - len(data))):
                data.extend(chunk)
                require(len(data) <= maximum, "control input exceeds bound")
            return bytes(data)
        finally:
            if fd is not None:
                os.close(fd)
            os.close(parent)

    def create_file(self, path, data, mode=0o600):
        require(
            len(data) <= MAX_BYTES and mode in (0o600, 0o755),
            "invalid control file bytes/mode",
        )
        parent, name = self.parent(path)
        fd = None
        try:
            fd = os.open(
                name,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=parent,
            )
            os.fsync(parent)  # Preserve even an interrupted/partial new leaf.
            info = os.fstat(fd)
            require(
                stat.S_ISREG(info.st_mode)
                and info.st_uid == self.owner
                and info.st_nlink == 1,
                "new control file ownership/type changed",
            )
            self.write_all(fd, data)
            os.fchmod(fd, mode)
            os.fsync(fd)
            os.lseek(fd, 0, os.SEEK_SET)
            actual = bytearray()
            while chunk := os.read(fd, 65536):
                actual.extend(chunk)
                require(len(actual) <= len(data), "control file grew while verifying")
            require(bytes(actual) == data, "new control file bytes changed")
            return {"path": path, "bytes": len(data), "sha256": sha(data)}
        finally:
            if fd is not None:
                os.close(fd)
            os.close(parent)

    def mkdir(self, path, uid=None, gid=None, mode=0o700):
        uid = self.owner if uid is None else uid
        gid = os.getegid() if gid is None else gid
        require(
            type(uid) is int and type(gid) is int and mode in (0o700, 0o755),
            "invalid control directory owner/mode",
        )
        parent, name = self.parent(path)
        fd = None
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent)
            os.fsync(parent)
            fd = os.open(name, self.flags, dir_fd=parent)
            self.check_directory(fd)
            os.fchmod(fd, mode)
            os.fchown(fd, uid, gid)
            os.fsync(fd)
            info = os.fstat(fd)
            require(
                (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode))
                == (uid, gid, mode),
                "new control directory metadata differs",
            )
            return {"path": path, "uid": uid, "gid": gid, "mode": mode}
        finally:
            if fd is not None:
                os.close(fd)
            os.close(parent)

    def symlink(self, path, target):
        require(target == "/dev/null", "control link target changed")
        parent, name = self.parent(path)
        try:
            os.symlink(target, name, dir_fd=parent)
            os.fsync(parent)
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
            require(
                stat.S_ISLNK(info.st_mode)
                and info.st_uid == self.owner
                and os.readlink(name, dir_fd=parent) == target,
                "new control mask changed",
            )
            return {"path": path, "target": target, "uid": info.st_uid}
        finally:
            os.close(parent)

    def metadata(self, path):
        parent, name = self.parent(path)
        try:
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
            result = {
                "uid": info.st_uid,
                "gid": info.st_gid,
                "mode": stat.S_IMODE(info.st_mode),
                "links": info.st_nlink,
            }
            if stat.S_ISLNK(info.st_mode):
                return {
                    **result,
                    "kind": "symlink",
                    "target": os.readlink(name, dir_fd=parent),
                }
            if stat.S_ISDIR(info.st_mode):
                return {**result, "kind": "directory"}
            require(stat.S_ISREG(info.st_mode), "special control file")
            return {**result, "kind": "file", "sha256": sha(self.read(path))}
        finally:
            os.close(parent)


class Journal:
    """Global create-only marker, retained inputs and append-only action records."""

    def __init__(self, tree, inputs, check=lambda: None):
        import fcntl

        self.fd, self.lock = None, None
        self.count, self.last = 0, "0" * 64
        check()
        tree.mkdir(STATE)
        # Existing even-empty STATE refuses a later invocation after a crash.
        try:
            for name, raw in inputs.items():
                check()
                tree.create_file(STATE + "/" + name, raw)
            check()
            tree.create_file(STATE + "/lock", b"")
            check()
            tree.create_file(STATE + "/events.jsonl", b"")
            directory = tree.directory(tree.components(STATE))
            try:
                self.lock = os.open(
                    "lock", os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory
                )
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.fd = os.open(
                    "events.jsonl",
                    os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=directory,
                )
            finally:
                os.close(directory)
        except Exception:
            self.close()
            raise

    def append(self, value):
        record = {"sequence": self.count, "previous_sha256": self.last, **value}
        raw = canonical(record)
        require(
            os.fstat(self.fd).st_size + len(raw) + 1 <= MAX_BYTES,
            "control journal output limit",
        )
        OwnedTree.write_all(self.fd, raw + b"\n")
        os.fsync(self.fd)
        self.last, self.count = sha(raw), self.count + 1

    def close(self):
        for key in ("fd", "lock"):
            fd = getattr(self, key, None)
            if fd is not None:
                os.close(fd)
                setattr(self, key, None)


class ControlCommands:
    def __init__(self, masks, check, seconds=5):
        require(
            type(seconds) in (int, float) and 0 < seconds <= 5,
            "control command timeout exceeds bound",
        )
        self.masks, self.check = set(masks), check
        self.seconds = seconds

    def __call__(self, argv):
        import select

        allowed = argv == ["/usr/bin/systemctl", "daemon-reload"] or (
            argv[:3] == ["/usr/bin/systemctl", "--no-ask-password", "stop"]
            and 1 <= len(argv[3:]) <= 64
            and len(set(argv[3:])) == len(argv[3:])
            and set(argv[3:]) <= self.masks
        )
        require(allowed, "command outside reviewed control operations")
        self.check()
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
        pipes = {child.stdout: bytearray(), child.stderr: bytearray()}
        pending, timed_out, exceeded = list(pipes), False, False
        deadline = time.monotonic() + self.seconds
        try:
            for pipe in pending:
                os.set_blocking(pipe.fileno(), False)
            while pending:
                self.check()
                if time.monotonic() >= deadline:
                    timed_out = True
                    break
                ready, _, _ = select.select(
                    pending, [], [], min(0.05, max(0, deadline - time.monotonic()))
                )
                for pipe in ready:
                    chunk = os.read(pipe.fileno(), 4096)
                    if not chunk:
                        pending.remove(pipe)
                        continue
                    if sum(len(x) for x in pipes.values()) + len(chunk) > MAX_COMMAND:
                        exceeded = True
                        break
                    pipes[pipe].extend(chunk)
                if exceeded:
                    break
            if not pending and not timed_out and not exceeded:
                try:
                    child.wait(timeout=max(0.001, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    timed_out = True
        finally:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait(timeout=1)
            child.stdout.close()
            child.stderr.close()
        return {
            "exit": child.returncode,
            "timed_out": timed_out,
            "output_exceeded": exceeded,
            "stdout_base64": base64.b64encode(pipes[child.stdout]).decode(),
            "stderr_base64": base64.b64encode(pipes[child.stderr]).decode(),
        }


def execute_actions(actions, tree, commands, journal, check):
    completed = 0
    for index, action in enumerate(actions):
        check()
        journal.append({"phase": "action-intent", "index": index, "action": action})
        check()  # Journal/fsync time counts against the original window.
        kind = action["action"]
        if kind == "create-exclusive-file":
            result = tree.create_file(
                action["path"], action["content"].encode(), action["mode"]
            )
        elif kind == "create-exclusive-directory":
            result = tree.mkdir(
                action["path"], action["uid"], action["gid"], action["mode"]
            )
        elif kind == "create-exclusive-symlink":
            result = tree.symlink(action["path"], action["target"])
        else:
            require(kind == "reviewed-command", "unknown control action")
            result = commands(action["argv"])
        journal.append({"phase": "action-reported", "index": index, "result": result})
        if kind == "reviewed-command":
            require(
                result
                == {
                    "exit": 0,
                    "timed_out": False,
                    "output_exceeded": False,
                    "stdout_base64": "",
                    "stderr_base64": "",
                },
                "control command incomplete or warned; stop/reconcile",
            )
        completed += 1
        check()
    return completed


def validate_observations(request, spec, before_raw, fresh, probe):
    before = json.loads(before_raw)
    require(
        sha(before_raw) == request["observation_sha256"], "reviewed observation changed"
    )
    require(
        request["run_nonce"] == spec["run_nonce"] == fresh["run_nonce"]
        and request["role"] == spec["role"] == fresh["role"],
        "control role/nonce changed",
    )
    require(
        sha(canonical(stable(before)))
        == request["stable_observation_sha256"]
        == sha(canonical(stable(fresh))),
        "fresh guest state differs from review",
    )
    require(
        sha(canonical(fresh["dpkg_configurations"]))
        == request["dpkg_configuration_sha256"],
        "reviewed dpkg configuration changed",
    )
    plan = probe.control_plan(spec, fresh)
    require(
        sha(canonical(plan)) == request["plan_sha256"],
        "regenerated control plan differs",
    )
    return plan


def verify_post(spec, observed, plan, tree, probe):
    require(
        observed["target"] == spec["target"]
        and observed["run_nonce"] == spec["run_nonce"],
        "post-control target changed",
    )
    require(
        observed["baseline_status_sha256"] == probe.STATUS
        and not observed["audit_stdout"]
        and not observed["package_processes"]
        and not observed["runtime_processes"],
        "post-control package/runtime state changed",
    )
    policy = observed["policy"]
    require(
        policy
        == {
            "kind": "file",
            "uid": 0,
            "mode": 0o755,
            "sha256": sha(spec["policy"]["content"].encode()),
        },
        "post-control policy differs",
    )
    require(
        set(observed["units"]) == set(spec["masks"]),
        "post-control unit inventory changed",
    )
    require(
        observed["dpkg_configurations"] == plan["dpkg_configuration_review_required"],
        "post-control dpkg configuration changed",
    )
    for row in observed["units"].values():
        props, admin = row["properties"], row["admin"]
        require(
            admin.get("kind") == "symlink"
            and admin.get("uid") == 0
            and admin.get("target") == "/dev/null"
            and row["helper"] == {"kind": "absent"},
            "post-control administrator/helper mask failed",
        )
        require(
            props["LoadState"] == "masked"
            and props["FragmentPath"] == "/dev/null"
            and props["ActiveState"] == "inactive"
            and not props["DropInPaths"],
            "effective control mask/quiescence failed",
        )
        require(
            set(props["Names"].split()) <= set(spec["masks"]),
            "post-control unit aliases changed",
        )
    for action in plan["actions"]:
        if action["action"] == "create-exclusive-directory":
            actual = tree.metadata(action["path"])
            require(
                all(actual[k] == action[k] for k in ("uid", "gid", "mode"))
                and actual["kind"] == "directory",
                "post-control directory metadata changed",
            )
            if action["path"].endswith("/partial"):
                account = observed["apt_sandbox_user"]
                require(
                    account["name"] == "_apt"
                    and (account["uid"], account["gid"])
                    == (action["uid"], action["gid"]),
                    "post-control APT account changed",
                )
        elif action["action"] == "create-exclusive-file":
            actual = tree.metadata(action["path"])
            require(
                actual["kind"] == "file"
                and actual["uid"] == 0
                and actual["mode"] == action["mode"]
                and actual["links"] == 1
                and actual["sha256"] == sha(action["content"].encode()),
                "post-control file changed",
            )


def load_probe(tree, packet):
    path = packet + "/guest_maintenance_probe.py"
    raw = tree.read(path)
    require(sha(raw) == PROBE_SHA256, "bound probe source changed")
    module = types.ModuleType("mcli1_bound_guest_probe")
    module.__file__ = path
    exec(compile(raw, path, "exec"), module.__dict__)  # noqa: S102 - Fixed digest and protected root file, not supplied code.
    return module


def apply_packet(packet, external_sha):
    platform_guard()
    tree = OwnedTree()
    journal = None
    try:
        require(
            re.fullmatch(r"/run/mcli1-control-[0-9a-f]{32}", packet),
            "unsupported control packet directory",
        )
        packet_info = tree.metadata(packet)
        require(
            packet_info["kind"] == "directory"
            and packet_info["uid"] == 0
            and packet_info["mode"] == 0o700,
            "control packet directory is not private root storage",
        )
        raw = tree.read(packet + "/request.json")
        request = checked_request(raw, external_sha)
        require(
            packet.endswith(request["run_nonce"]),
            "packet path belongs to another control attempt",
        )
        require(
            Path(__file__).absolute().as_posix()
            == packet + "/guest_maintenance_control.py",
            "control source is outside its approved packet",
        )
        require(
            sha(tree.read(packet + "/guest_maintenance_control.py"))
            == request["program_sha256"],
            "staged control source differs",
        )
        check = lambda: check_window(request)
        check()
        spec_raw = tree.read(packet + "/inspection-spec.json")
        require(sha(spec_raw) == request["spec_sha256"], "inspection spec changed")
        before_raw = tree.read(packet + "/observation.json")
        probe = load_probe(tree, packet)
        spec = probe.checked_spec(spec_raw, request["spec_sha256"])
        reader = probe.NativeReader()
        reader.deadline = min(
            reader.deadline, request["window"]["expires_mono_ns"] / 10**9
        )
        fresh = probe.inspect(spec, reader)
        require(
            0 <= time.monotonic_ns() - fresh["guest_finished_mono_ns"] <= 5 * 10**9,
            "fresh control inspection expired",
        )
        plan = validate_observations(request, spec, before_raw, fresh, probe)
        check()
        inputs = {
            "request.json": raw,
            "inspection-spec.json": spec_raw,
            "observation.json": before_raw,
            "fresh-before.json": canonical(fresh),
            "plan.json": canonical(plan),
        }
        journal = Journal(tree, inputs, check)
        journal.append(
            {
                "phase": "controls-admitted",
                "request_sha256": external_sha,
                "run_nonce": request["run_nonce"],
            }
        )
        commands = ControlCommands(spec["masks"], check)
        completed = execute_actions(plan["actions"], tree, commands, journal, check)
        post = probe.inspect(spec, reader)
        verify_post(spec, post, plan, tree, probe)
        check()
        tree.create_file(STATE + "/after.json", canonical(post))
        journal.append(
            {
                "phase": "controls-postconditions-reported",
                "post_sha256": sha(canonical(post)),
                "actions_completed": completed,
            }
        )
        return {
            "status": "controls-reported-not-installation-acceptance",
            "run_nonce": request["run_nonce"],
            "actions_completed": completed,
            "journal_last_sha256": journal.last,
            "state_directory": STATE,
            "installation_performed": False,
            "independent_stop_still_required": True,
        }
    except Exception:
        if journal is not None:
            try:
                journal.append(
                    {"phase": "held", "stop_and_reconciliation_required": True}
                )
            except (OSError, ValueError):
                pass  # The persistent directory and preceding intent remain.
        raise
    finally:
        if journal is not None:
            journal.close()
        tree.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply")
    parser.add_argument("--request-sha256")
    args = parser.parse_args()
    if args.apply:
        result = apply_packet(args.apply, args.request_sha256)
    else:
        require(args.request_sha256 is None, "control digest requires --apply")
        result = {
            "status": "unarmed-preview",
            "mutations": 0,
            "installation_available": False,
        }
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 - Never expose packet/configuration bytes.
        sys.stderr.write("guest controls held; stop and retain state for review\n")
        sys.exit(2)
