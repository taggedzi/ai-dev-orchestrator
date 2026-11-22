"""Prepared, one-shot original-owner poweroff boundary. Default CLI is unarmed.

Only the existing LeaseSupervisor may reach this path after its durable stop
intent. Command return remains distinct from independent VM poweroff evidence.
"""

import argparse
import json
import os
import re
import time
from pathlib import Path, PureWindowsPath

from .maintenance_host import OWNER_KEYS, object_bytes, process_identity
from .offline_repo import description, new_root, write_json
from .os_install import WORKSPACE
from .store import Hold
from .transfer_commands import canonical, digest
from .windows_readonly import MAX_OUTPUT, VBOX, VERSION, _run, live, require

VM_IDS = {
    "guard": "0eceb37e-f216-45ed-817c-7cf2fca3a32a",
    "executor": "74129e9c-5a65-44fa-9d35-79d458dc4704",
}
EXE_SHA = "178e016ed38cb6e369a5c17c6c960c176674b9c864030d8ce0ad2867613becff"
STOPS_ROOT = WORKSPACE / ".local/validation/owner-stops"
DIRECTORY = Path(__file__).parent
SOURCES = {
    name: DIRECTORY / name
    for name in (
        "maintenance_stop.py",
        "driver.py",
        "supervisor.py",
        "maintenance_host.py",
        "windows_readonly.py",
        "maintenance_serial.py",
        "maintenance_serial_worker.py",
        "transfer_commands.py",
        "store.py",
        "fixture.py",
    )
}
SOURCE_EPOCH = {name: digest(path.read_bytes()) for name, path in SOURCES.items()}


def draft(role):
    return {
        "format": "mcli1-original-stop-v1",
        "role": role,
        "target_vm_uuid": VM_IDS[role],
        "owner_nonce": None,
        "owner_binding_sha256": None,
        "process": {"pid": None, "created_filetime": None, "image": None},
        "lease": {k: VM_IDS[role] if k == "target" else None for k in OWNER_KEYS},
        "approval": {"native_stop": None},
        "hypervisor": {"path": str(VBOX), "sha256": EXE_SHA, "version": VERSION},
        "sources": dict(SOURCE_EPOCH),
    }


def checked(raw, external_sha):
    require(
        type(raw) is bytes and digest(raw) == external_sha, "stop plan digest differs"
    )
    plan = object_bytes(raw)
    require(
        set(plan) == set(draft("guard"))
        and plan["format"] == "mcli1-original-stop-v1"
        and plan["role"] in VM_IDS
        and plan["target_vm_uuid"] == VM_IDS[plan["role"]],
        "stop plan format/target differs",
    )
    approval = plan["approval"]
    require(
        type(approval) is dict
        and set(approval) == {"native_stop"}
        and isinstance(approval["native_stop"], str)
        and 0 < len(approval["native_stop"]) <= 256,
        "native stop approval is unbound",
    )
    require(
        isinstance(plan["owner_nonce"], str)
        and re.fullmatch(r"[0-9a-f]{32}", plan["owner_nonce"])
        and isinstance(plan["owner_binding_sha256"], str)
        and re.fullmatch(r"[0-9a-f]{64}", plan["owner_binding_sha256"]),
        "original stop owner is unbound",
    )
    process, lease = plan["process"], plan["lease"]
    require(
        set(process) == {"pid", "created_filetime", "image"}
        and type(process["pid"]) is int
        and process["pid"] > 0
        and type(process["created_filetime"]) is int
        and process["created_filetime"] > 0
        and isinstance(process["image"], str)
        and PureWindowsPath(process["image"]).is_absolute()
        and set(lease) == set(OWNER_KEYS)
        and lease["target"] == plan["target_vm_uuid"]
        and all(
            type(lease[k]) is int and lease[k] > 0 for k in OWNER_KEYS if k != "target"
        )
        and 0 < lease["expires_ns"] - lease["armed_ns"] <= 600 * 10**9
        and 0 < lease["expires_mono_ns"] - lease["armed_mono_ns"] <= 600 * 10**9,
        "original stop process/lease fields differ",
    )
    require(
        plan["hypervisor"]
        == {"path": str(VBOX), "sha256": EXE_SHA, "version": VERSION},
        "stop executable identity differs",
    )
    require(
        plan["sources"]
        == SOURCE_EPOCH
        == {name: digest(path.read_bytes()) for name, path in SOURCES.items()},
        "stop source cohort changed",
    )
    return plan


def context(store, plan, profile, identity):
    require(
        store.db.execute("PRAGMA database_list").fetchone()["file"]
        and store.db.execute("PRAGMA busy_timeout").fetchone()[0] <= 50,
        "bounded stop requires the original durable owner connection",
    )
    require(
        profile["target_vm_uuid"] == plan["target_vm_uuid"]
        and profile["lease_expires_utc_ns"] == plan["lease"]["expires_ns"]
        and profile["vboxmanage"] == plan["hypervisor"]["path"]
        and plan["process"]["pid"] == os.getpid()
        and identity(os.getpid()) == plan["process"],
        "only the bound original owner process may stop this VM",
    )
    lease = store.db.execute("SELECT * FROM lease WHERE singleton=1").fetchone()
    owner = store.db.execute(
        "SELECT * FROM maintenance_owner WHERE singleton=1"
    ).fetchone()
    authority = store.db.execute("SELECT * FROM authority WHERE singleton=1").fetchone()
    expected = canonical(
        {
            "format": "mcli1-original-owner-v1",
            "owner_nonce": plan["owner_nonce"],
            "lease": plan["lease"],
            "process": plan["process"],
        }
    )
    require(
        lease is not None
        and owner is not None
        and lease["state"] == "stopping"
        and {k: lease[k] for k in OWNER_KEYS} == plan["lease"]
        and owner["state"] == "watching"
        and owner["binding"] == expected
        and digest(expected) == plan["owner_binding_sha256"]
        and not authority["active"],
        "original owner/lease stop intent or fence is missing or changed",
    )
    # Expired run authority and older pulses must not deny the original emergency stop.
    return expected


def executable(plan):
    require(
        not os.environ.get("VBOX_USER_HOME")
        and digest(VBOX.read_bytes()) == plan["hypervisor"]["sha256"],
        "stop executable bytes/configuration root changed",
    )


def stop_directory(nonce):
    root = STOPS_ROOT / nonce
    for path in (STOPS_ROOT, *STOPS_ROOT.parents):
        if path.exists():
            state = path.lstat()
            require(
                not path.is_symlink()
                and not (getattr(state, "st_file_attributes", 0) & 0x400),
                "stop receipt ancestor is a link/reparse point",
            )
    STOPS_ROOT.mkdir(parents=True, exist_ok=True)
    root.mkdir(exist_ok=False)
    return root


def write_once(path, raw):
    with path.open("xb") as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())


def execute(store, profile, runner=None, identity=None):
    """Reached through driver.stop_vm by the original supervisor; never retries."""
    # Freeze all caller-owned values before validating their plan/profile bindings.
    profile = json.loads(canonical(profile))
    binding = profile.get("bounded_stop")
    require(
        type(binding) is dict and set(binding) == {"plan", "sha256"},
        "bounded original-owner stop plan is unbound",
    )
    raw = canonical(binding["plan"])
    plan = checked(raw, binding["sha256"])
    identity = process_identity if identity is None else identity
    runner = _run if runner is None else runner
    start, wall = time.monotonic_ns(), time.time_ns()
    context(store, plan, profile, identity)
    executable(plan)
    args = ["controlvm", plan["target_vm_uuid"], "poweroff"]
    command_sha = digest(canonical([str(VBOX), *args]))
    root = stop_directory(plan["owner_nonce"])
    intent = canonical(
        {
            "format": "mcli1-original-stop-intent-v1",
            "plan_sha256": binding["sha256"],
            "owner_binding_sha256": plan["owner_binding_sha256"],
            "command_sha256": command_sha,
            "target_vm_uuid": plan["target_vm_uuid"],
            "started_mono_ns": start,
            "started_utc_ns": wall,
        }
    )
    write_once(root / "poweroff.intent.json", intent)
    with store.transaction():
        context(store, plan, profile, identity)
        store.db.execute(
            "CREATE TABLE IF NOT EXISTS native_owner_stop (singleton INTEGER PRIMARY KEY CHECK(singleton=1), plan_sha TEXT, intent_sha TEXT, state TEXT, child_pid INTEGER, receipt_sha TEXT)"
        )
        require(
            store.db.execute("SELECT 1 FROM native_owner_stop").fetchone() is None,
            "native stop attempt already exists",
        )
        store.db.execute(
            "INSERT INTO native_owner_stop VALUES(1,?,?,'possible-send',NULL,NULL)",
            (binding["sha256"], digest(intent)),
        )
        store._event(
            "original-native-stop-intent",
            {"plan_sha256": binding["sha256"], "intent_sha256": digest(intent)},
        )
    gate = []

    def before_resume(pid):
        require(not gate, "native stop gate replayed")
        require(type(pid) is int and pid > 0, "native stop process identity is missing")
        live(wall + 3 * 10**9, start + 3 * 10**9)
        checked(raw, binding["sha256"])
        context(store, plan, profile, identity)
        executable(plan)
        require(
            (root / "poweroff.intent.json").read_bytes() == intent,
            "native stop filesystem intent changed",
        )
        with store.transaction():
            row = store.db.execute("SELECT * FROM native_owner_stop").fetchone()
            require(
                row["plan_sha"] == binding["sha256"]
                and row["intent_sha"] == digest(intent)
                and row["state"] == "possible-send"
                and row["child_pid"] is None,
                "native stop journal intent changed",
            )
            store.db.execute("UPDATE native_owner_stop SET child_pid=?", (pid,))
            store._event(
                "original-native-stop-process-gated",
                {"child_pid": pid, "command_sha256": command_sha},
            )
        gate.append(pid)

    result = runner(VBOX, args, wall + 3 * 10**9, start + 3 * 10**9, before_resume)
    require(
        len(gate) == 1
        and type(result["pid"]) is int
        and result["pid"] == gate[0]
        and type(result["exit"]) is int
        and type(result["stdout"]) is bytes
        and type(result["stderr"]) is bytes
        and max(len(result["stdout"]), len(result["stderr"])) <= MAX_OUTPUT
        and result["job_active_processes"] == 0,
        "native stop command failed, overflowed or was not reaped; reconcile without replay",
    )
    for stream in ("stdout", "stderr"):
        write_once(root / (stream + ".bin"), result[stream])
    write_once(
        root / "process.result.json",
        canonical(
            {
                **{k: v for k, v in result.items() if k not in {"stdout", "stderr"}},
                "command_sha256": command_sha,
                "stdout_sha256": digest(result["stdout"]),
                "stderr_sha256": digest(result["stderr"]),
                "independent_poweroff_still_required": True,
            }
        ),
    )
    require(result["exit"] == 0, "native stop command failed; reconcile without replay")
    live(wall + 3 * 10**9, start + 3 * 10**9)
    context(store, plan, profile, identity)
    receipt = canonical(
        {
            "status": "original-stop-command-returned-not-poweroff-acceptance",
            "target_vm_uuid": plan["target_vm_uuid"],
            "owner_nonce": plan["owner_nonce"],
            "plan_sha256": binding["sha256"],
            "command_sha256": command_sha,
            "child_pid": gate[0],
            "exit": result["exit"],
            "job_active_processes": 0,
            "stdout_sha256": digest(result["stdout"]),
            "stderr_sha256": digest(result["stderr"]),
            "started_mono_ns": start,
            "finished_mono_ns": time.monotonic_ns(),
            "independent_poweroff_still_required": True,
            "original_lease_expired_before_command": start
            >= plan["lease"]["expires_mono_ns"]
            or wall >= plan["lease"]["expires_ns"],
        }
    )
    write_once(root / "command.receipt.json", receipt)
    with store.transaction():
        context(store, plan, profile, identity)
        row = store.db.execute("SELECT * FROM native_owner_stop").fetchone()
        require(
            row["state"] == "possible-send"
            and row["plan_sha"] == binding["sha256"]
            and row["intent_sha"] == digest(intent)
            and row["child_pid"] == gate[0]
            and row["receipt_sha"] is None,
            "native stop journal changed before command receipt commit",
        )
        store.db.execute(
            "UPDATE native_owner_stop SET state='command-returned', receipt_sha=?",
            (digest(receipt),),
        )
        store._event(
            "original-native-stop-command-returned",
            {
                "receipt_sha256": digest(receipt),
                "independent_poweroff_still_required": True,
            },
        )
    return json.loads(receipt)


def prepare(role, output):
    root = new_root(output)
    raw = canonical(draft(role))
    (root / "stop-plan.json").write_bytes(raw)
    for name, path in SOURCES.items():
        (root / name).write_bytes(path.read_bytes())
    try:
        checked(raw, digest(raw))
    except Hold as exc:
        refusal = str(exc)
    else:
        raise Hold("unarmed stop plan unexpectedly passed")
    review = {
        "status": "unarmed-original-stop-preparation",
        "role": role,
        "plan": description(root / "stop-plan.json"),
        "refusal": refusal,
        "native_calls": 0,
        "VM_mutations": 0,
        "actual_owner_registered": False,
        "activation_authorized": False,
        "native_command_seconds_at_most": 3,
        "independent_poweroff_still_required": True,
        "launch_packet_complete": False,
    }
    write_json(root / "review.json", review)
    return review


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=tuple(VM_IDS), default="guard")
    parser.add_argument("--prepare")
    args = parser.parse_args()
    result = (
        prepare(args.role, args.prepare)
        if args.prepare
        else {
            "status": "unarmed-original-stop-preview",
            "native_calls": 0,
            "owner_activation_available": False,
            "plan": draft(args.role),
        }
    )
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
