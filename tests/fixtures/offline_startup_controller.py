"""Python-only offline startup worker; all VM observations are synthetic replay."""

import json
import shutil
import sys
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import patch

workspace = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(workspace))
sys.path.insert(0, str(workspace / "tests"))

from research.validation import offline_startup as offline
from research.validation import startup_qualification as q
from research.validation.store import Hold
from research.validation.transfer_commands import canonical, digest


@contextmanager
def python_surrogates(root, ledger):
    """Retain actual file locks/jobs; substitute VM facts and native frontend."""
    root = Path(root)
    owner = root / "owner"
    original_paths = q.start.backup.source_paths
    metadata = Path(ledger).parent / "retained-source-metadata"
    metadata.mkdir(exist_ok=True)
    # The replayed profile is stopped-refresh-03, not the current native VM.
    # Give that historical metadata independent scratch identities in both the
    # bootstrap and worker. Never rewrite an existing scratch file: drift must
    # still fail the real preactivation and retained-file gates.
    frozen = {
        ("guard", "configuration"): workspace
        / ".local/validation/stopped-backup-guard-02/configuration.vbox",
        ("guard", "nvram"): workspace
        / ".local/validation/stopped-backup-guard-02/nvram.bin",
        ("executor", "configuration"): workspace
        / ".local/validation/guard-startup-review-10/postfiles/executor-configuration.bin",
        ("executor", "nvram"): workspace
        / ".local/validation/guard-startup-review-10/postfiles/executor-nvram.bin",
    }
    for (role, kind), source in frozen.items():
        target = metadata / f"{role}-{kind}.bin"
        if not target.exists():
            with target.open("xb") as stream, source.open("rb") as retained:
                shutil.copyfileobj(retained, stream)

    def source_paths(role):
        return {
            **original_paths(role),
            **{
                kind: metadata / f"{role}-{kind}.bin"
                for kind in ("configuration", "nvram")
            },
        }
    original_family = q.start.frontend._FrontendProcess
    original_request = q.start._PreparedStart.request_owner_stop
    original_controller_main = q.controller_main

    def running_pid():
        path = owner / "family-2.json"
        if not path.exists():
            return 0
        pid = json.loads(path.read_bytes())["pid"]
        try:
            q.start.host.process_identity(pid)
            return pid
        except (Hold, OSError):
            return 0

    class Observer:
        def __init__(self, role):
            self.role, self.last = role, None

        def frame(self):
            folder = (
                workspace
                / ".local/validation/stopped-refresh-03"
                / ("4-guard" if self.role == "guard" else "5-executor")
            )
            machine, medium = (
                (folder / "machine.stdout").read_bytes(),
                (folder / "medium.stdout").read_bytes(),
            )
            pid = running_pid() if self.role == "guard" else 0
            state = "running" if pid else "poweroff"
            if (
                self.role == "guard"
                and (owner / "controller.loss.intent.json").exists()
                and not pid
            ):
                state = "aborted"
            machine = machine.replace(
                b'VMState="poweroff"', ('VMState="' + state + '"').encode()
            )
            if pid:
                medium = medium.replace(
                    b"State:          created", b"State:          locked write"
                )
            vm = q.start.backup.SLOTS[self.role]["vm_uuid"]
            session = {
                "vm_uuid": vm,
                "state_before": "Locked" if pid else "Unlocked",
                "state_after": "Locked" if pid else "Unlocked",
                "pid": pid,
            }
            stamp = time.monotonic_ns()
            raw_session = canonical(
                {
                    "format": "mcli1-native-session-read-v1",
                    "version": q.session.VERSION,
                    "revision": q.session.REVISION,
                    "vm_uuid": vm,
                    "state_before": 2 if pid else 1,
                    "state_after": 2 if pid else 1,
                    "machine_before": q.session.MACHINE_STATES[state],
                    "machine_after": q.session.MACHINE_STATES[state],
                    "pid": pid,
                }
            )
            self.last = {
                "observed_mono_ns": stamp,
                "finished_mono_ns": stamp,
                "machine_first": machine,
                "machine": machine,
                "medium": medium,
                "session_raw": raw_session,
                "queries": [],
                "synthetic_VM_facts": True,
            }
            return {
                "observed_mono_ns": stamp,
                "machine": machine,
                "medium": medium,
                "session": session,
            }

        __call__ = frame

        def startup_observation(self, *, recovery=None):
            assert recovery is None
            return self.frame()

        def startup_session(self):
            frame = self.frame()
            self.last["phase"] = "startup-session-only"
            return {
                "format": "mcli1-startup-session-probe-v1",
                "observed_mono_ns": frame["observed_mono_ns"],
                "finished_mono_ns": self.last["finished_mono_ns"],
                "session_raw": self.last["session_raw"],
            }

    def family(executable, args):
        assert executable == Path(sys.executable).resolve()
        assert args == ["--startvm", q.target_uuid(), "--vrde", "off"]
        return original_family(
            executable,
            [
                "-I",
                "-B",
                str(Path(__file__).with_name("frontend_family.py")),
                str(owner),
                "0",
            ],
        )

    def request_stop(adapter):
        (owner / "allow.surrogate.stop").write_bytes(
            b"Python family may exit after original surrogate effect"
        )
        return original_request(adapter)

    def controller_main(*args, **kwargs):
        if (root / "test.pause-before-native").exists():
            q.owner.publish(
                root / "test.armed-barrier.json", canonical({"VM_actions": 0})
            )
            end = time.monotonic() + 15
            while time.monotonic() < end:
                time.sleep(0.01)
            raise Hold("test-only post-arm barrier ended without native action")
        return original_controller_main(*args, **kwargs)

    with ExitStack() as stack:
        for target, name, value in (
            (offline, "LEDGER", Path(ledger)),
            (q.start.backup, "source_paths", source_paths),
            (q.owner.stop, "STOPS_ROOT", owner / "surrogate-stops"),
            (q.start.frontend, "HEADLESS", Path(sys.executable).resolve()),
            (
                q.start.frontend,
                "HEADLESS_SHA256",
                digest(Path(sys.executable).read_bytes()),
            ),
            (q.start.frontend, "_FrontendProcess", family),
            (q.start._PreparedStart, "request_owner_stop", request_stop),
            (q.session, "NativeObserver", Observer),
            (q, "controller_main", controller_main),
        ):
            stack.enter_context(patch.object(target, name, value))
        yield


if __name__ == "__main__":
    with python_surrogates(Path(sys.argv[1]), Path(sys.argv[3])):
        offline.worker_main(Path(sys.argv[1]), sys.argv[2])
