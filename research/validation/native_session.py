"""Fixed, bounded, read-only VirtualBox session/VM observer on Windows.

Default CLI is an inert preview. --observe only reads the selected preparation
VM; it has no launch, session lock, guest command, poweroff or setting method.
"""

import argparse
import json
import os
import time
from pathlib import Path

from . import maintenance_host as host
from . import recovery_records as recovery_model
from . import stopped_backup as backup
from . import windows_readonly as native
from .maintenance_stop import EXE_SHA
from .offline_repo import new_root, write_json
from .transfer_commands import canonical, digest

require = native.require
POWERSHELL = Path("C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
POWERSHELL_SHA256 = "95ce2acbc6cd9d7f4a22759d39a8d40fc2a53ceeecf068ef856849f0d2076961"
VERSION, REVISION = "7.2.22", 175245
SESSION_STATES = {1: "Unlocked", 2: "Locked", 3: "Spawning", 4: "Unlocking"}
MACHINE_STATES = {"poweroff": 1, "aborted": 4, "running": 6, "starting": 11}
SOURCES = {**backup.SOURCES, "native_session.py": Path(__file__)}
SOURCE_EPOCH = {n: digest(p.read_bytes()) for n, p in SOURCES.items()}


def script(role):
    require(role in backup.SLOTS, "unknown session observation role")
    target = backup.SLOTS[role]["vm_uuid"]
    # target is a fixed source constant, never shell text from a grant/guest.
    return (
        "$ErrorActionPreference='Stop';"
        "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);"
        "$box=$null;$machine=$null;try{"
        "$box=New-Object -ComObject VirtualBox.VirtualBox;"
        f"$machine=$box.FindMachine('{target}');"
        "$before=[int]$machine.SessionState;"
        "$stateBefore=[int]$machine.State;"
        "$sessionProcess=0;if($before -eq 2){$sessionProcess=[int64]$machine.SessionPID};"
        "$stateAfter=[int]$machine.State;"
        "$after=[int]$machine.SessionState;"
        "$result=[ordered]@{format='mcli1-native-session-read-v1';"
        "version=[string]$box.Version;revision=[int64]$box.Revision;"
        "vm_uuid=[string]$machine.Id;state_before=$before;state_after=$after;"
        "machine_before=$stateBefore;machine_after=$stateAfter;pid=$sessionProcess};"
        "$result|ConvertTo-Json -Compress"
        "}finally{"
        "if($null -ne $machine){[void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($machine)};"
        "if($null -ne $box){[void][Runtime.InteropServices.Marshal]::FinalReleaseComObject($box)}}"
    )


def startup_progress(states, before, after, *, recovery=None):
    """Validate forward-only reads; the returned ranks confer no readiness."""
    initial = "poweroff"
    if recovery is not None:
        recovery_model.checked(recovery)
        initial = "aborted"
    machines = {initial: 0, "starting": 1, "running": 2}
    sessions = {"Unlocked": 0, "Spawning": 1, "Locked": 2}
    require(
        type(states) is list
        and len(states) == 4
        and all(s in machines for s in states)
        and before in sessions
        and after in sessions,
        "unknown startup state",
    )
    ranks = [machines[s] for s in states]
    require(
        ranks == sorted(ranks) and sessions[before] <= sessions[after],
        "startup state moved backward",
    )
    return (ranks[0], sessions[before]), (ranks[-1], sessions[after])


def session_record(raw, role, *, startup=False):
    value = host.object_bytes(raw)
    require(
        set(value)
        == {
            "format",
            "version",
            "revision",
            "vm_uuid",
            "state_before",
            "state_after",
            "machine_before",
            "machine_after",
            "pid",
        }
        and value["format"] == "mcli1-native-session-read-v1"
        and value["version"] == VERSION
        and type(value["revision"]) is int
        and value["revision"] == REVISION
        and value["vm_uuid"] == backup.SLOTS[role]["vm_uuid"],
        "native session format/version/target differs",
    )
    for key in (
        "state_before",
        "state_after",
        "machine_before",
        "machine_after",
        "pid",
    ):
        require(type(value[key]) is int, "native session numeric type differs")
    require(
        value["state_before"] in SESSION_STATES
        and value["state_after"] in SESSION_STATES
        and (
            startup
            or (
                value["state_before"] == value["state_after"]
                and value["machine_before"] == value["machine_after"]
            )
        )
        and 0 <= value["pid"] <= 2**32 - 1
        and ((value["pid"] > 0) if value["state_before"] == 2 else value["pid"] == 0),
        "native session state/PID read is uncertain",
    )
    return value


class NativeObserver:
    def __init__(self, role, *, runner=native._run, queries=None):
        require(role in backup.SLOTS, "unknown native observer role")
        self.role, self.runner, self.last = role, runner, None
        self.slot = backup.SLOTS[role]
        self.queries = queries or native.VBoxQueries(
            EXE_SHA, [self.slot["vm_uuid"], self.slot["disk_uuid"]]
        )

    def pins(self):
        require(
            not os.environ.get("VBOX_USER_HOME")
            and digest(POWERSHELL.read_bytes()) == POWERSHELL_SHA256
            and SOURCE_EPOCH == {n: digest(p.read_bytes()) for n, p in SOURCES.items()},
            "native session executable/configuration/source changed",
        )

    def __call__(self):
        return self._capture(startup=False)

    def startup_observation(self, *, recovery=None):
        """Read startup progress only; strict observation remains the default."""
        return self._capture(startup=True, recovery=recovery)

    def _session_query(self, wall, mono, *, startup):
        result = self.runner(
            POWERSHELL,
            ["-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script(self.role)],
            wall,
            mono,
            before_resume=lambda _pid: self.pins(),
        )
        self.last["session_raw"] = result["stdout"]
        self.last["queries"].append(
            {
                "kind": "session",
                "target": self.slot["vm_uuid"],
                **{k: v for k, v in result.items() if k not in {"stdout", "stderr"}},
            }
        )
        require(
            result["exit"] == 0
            and not result["stderr"]
            and result["job_active_processes"] == 0
            and len(result["stdout"]) <= native.MAX_OUTPUT,
            "native session query failed or was not reaped",
        )
        return session_record(result["stdout"], self.role, startup=startup)

    def startup_session(self):
        """COM property reads only: no CLI query or VM session-lock request."""
        self.pins()
        wall, mono = time.time_ns() + 4 * 10**9, time.monotonic_ns() + 4 * 10**9
        started = time.monotonic_ns()
        self.last = {
            "observed_mono_ns": started,
            "queries": [],
            "phase": "startup-session-only",
        }
        self._session_query(wall, mono, startup=True)
        native.live(wall, mono)
        self.last["finished_mono_ns"] = time.monotonic_ns()
        return {
            "format": "mcli1-startup-session-probe-v1",
            "observed_mono_ns": started,
            "finished_mono_ns": self.last["finished_mono_ns"],
            "session_raw": self.last["session_raw"],
        }

    def _capture(self, *, startup, recovery=None):
        if recovery is not None:
            recovery_model.checked(recovery)
            require(
                startup and self.role == "guard",
                "recovery observation is guard startup only",
            )
        self.pins()
        wall, mono = time.time_ns() + 4 * 10**9, time.monotonic_ns() + 4 * 10**9
        started = time.monotonic_ns()
        self.last = {"observed_mono_ns": started, "queries": []}

        def query(kind, target, name):
            result = self.queries(kind, target, wall, mono)
            self.last[name] = result["stdout"]
            self.last["queries"].append(
                {
                    "kind": kind,
                    "target": target,
                    **{
                        k: v for k, v in result.items() if k not in {"stdout", "stderr"}
                    },
                }
            )
            return result["stdout"]

        first = query("machine", self.slot["vm_uuid"], "machine_first")
        medium = query("disk", self.slot["disk_uuid"], "medium")
        session = self._session_query(wall, mono, startup=startup)
        final = query("machine", self.slot["vm_uuid"], "machine")
        native.live(wall, mono)
        fields = host.machine_fields(final)
        first_fields = host.machine_fields(first)
        first_profile, final_profile = (
            host.machine_profile(first),
            host.machine_profile(final),
        )
        transition = None
        if startup:
            names = {v: k for k, v in MACHINE_STATES.items()}
            states = [
                first_fields["VMState"],
                names.get(session["machine_before"]),
                names.get(session["machine_after"]),
                fields["VMState"],
            ]
            before, after = (
                SESSION_STATES[session[k]] for k in ("state_before", "state_after")
            )
            startup_progress(states, before, after, recovery=recovery)
            first_profile = {**first_profile, "state": final_profile["state"]}
            if (
                len(set(states)) != 1
                or before != after
                or before == "Spawning"
                or (states[-1] == "running" and before != "Locked")
            ):
                transition = {
                    "format": "mcli1-startup-wait-v1",
                    "machine_states": states,
                }
        require(
            first_profile == final_profile
            and fields["hardwareuuid"]
            == first_fields["hardwareuuid"]
            == self.slot["vm_uuid"]
            and all(
                first_fields.get(k) == fields.get(k)
                for k in (
                    "firmware",
                    "apic",
                    "x2apic",
                    "boot1",
                    "boot2",
                    "boot3",
                    "boot4",
                    "autostart-enabled",
                    "teleporterenabled",
                    "nested-hw-virt",
                    "recording_enabled",
                    "recording_started",
                )
            )
            and (
                startup
                or session["machine_before"] == MACHINE_STATES.get(fields["VMState"])
            ),
            "native VM state/profile changed across session observation",
        )
        grant = {
            "role": self.role,
            "target": {
                "vm_uuid": self.slot["vm_uuid"],
                "disk_uuid": self.slot["disk_uuid"],
            },
        }
        host.check_medium(medium, final, grant)
        self.last["finished_mono_ns"] = time.monotonic_ns()
        frame = {
            "observed_mono_ns": started,
            "machine": final,
            "medium": medium,
            "session": {
                "vm_uuid": session["vm_uuid"],
                "state_before": SESSION_STATES[session["state_before"]],
                "state_after": SESSION_STATES[session["state_after"]],
                "pid": session["pid"],
            },
        }
        if transition is not None:
            frame["startup_transition"] = transition
        return frame


def retain(root, observer):
    """Keep raw bounded query bytes even when consistency validation holds."""
    record = dict(observer.last or {})
    for key in ("machine_first", "machine", "medium", "session_raw"):
        if key in record:
            raw = record.pop(key)
            (root / (key + ".stdout")).write_bytes(raw)
            record[key] = {"bytes": len(raw), "sha256": digest(raw)}
    write_json(root / "observations.json", record)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=tuple(backup.SLOTS), default="guard")
    parser.add_argument("--observe", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args()
    if not args.observe:
        print(
            json.dumps(
                {
                    "status": "read-only-session-preview",
                    "native_calls": 0,
                    "target": backup.SLOTS[args.role]["vm_uuid"],
                    "powershell_sha256": POWERSHELL_SHA256,
                    "script_sha256": digest(script(args.role).encode()),
                    "sources": SOURCE_EPOCH,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    require(
        args.output is not None, "read-only observation needs a new output directory"
    )
    root = new_root(args.output)
    observer = NativeObserver(args.role)
    try:
        frame = observer()
        write_json(
            root / "receipt.json",
            {
                "status": "native-read-only-session-observed-not-boot-authority",
                "role": args.role,
                "session": frame["session"],
                "VM_state": host.machine_fields(frame["machine"])["VMState"],
                "observed_mono_ns": frame["observed_mono_ns"],
                "sources": SOURCE_EPOCH,
                "VM_boots": 0,
                "VM_mutations": 0,
                "native_boot_authorized": False,
            },
        )
    finally:
        retain(root, observer)
    print(
        canonical(
            {
                "status": "read-only-session-recorded",
                "output": str(root),
                "VM_mutations": 0,
            }
        ).decode()
    )


if __name__ == "__main__":
    main()
