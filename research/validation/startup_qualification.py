"""Prepare one disconnected guard startup/session/normal-stop qualification.

Preparation creates only suspended Python controller/owner processes. It publishes
their exact identities, original lease, stop proposal and source/input hashes for
review. Only a separately approved, matching review reply can activate them.
No guest command, installation, networking, restore or second boot is provided.
"""

import argparse
import ctypes
import hashlib
import json
import os
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from . import frontend_start as start
from . import native_session as session
from . import owner_launch as launch
from . import owner_process as owner
from .offline_repo import new_root
from .store import Store
from .transfer_commands import canonical, digest
from .windows_readonly import require

ROOT = start.backup.ROOT
SOURCES = {**start.SOURCES, "startup_qualification.py": Path(__file__)}
SOURCE_EPOCH = {n: digest(p.read_bytes()) for n, p in SOURCES.items()}
POLICY = {
    "role": "guard",
    "VM_boots": 1,
    "running_observations": 2,
    "runtime_limit_ns": 10 * 10**9,
    "original_lease_ns": 600 * 10**9,
    "review_reserve_ns": 60 * 10**9,
    "stop_observation_limit_ns": 10 * 10**9,
    "guest_commands": 0,
    "NIC_activations": 0,
    "package_installs": 0,
    "restore_operations": 0,
    "retries": 0,
}


def current_sources():
    return {n: digest(p.read_bytes()) for n, p in SOURCES.items()}


def fixed_inputs():
    paths = {
        "backup": ROOT / ".local/validation/stopped-backup-guard-01/receipt.json",
        "profile": ROOT / ".local/validation/maintenance-profile-guard-01/receipt.json",
    }
    return {
        name: {
            "path": str(start.backup.safe(path)),
            "sha256": digest(path.read_bytes()),
        }
        for name, path in paths.items()
    }


def approved_review(raw, sha, approval_raw):
    require(
        type(raw) is bytes and digest(raw) == sha, "qualification review digest differs"
    )
    review = start.host.object_bytes(raw)
    approval = start.host.object_bytes(approval_raw)
    require(
        review["format"] == "mcli1-one-guard-startup-review-v1"
        and review["policy"] == POLICY
        and review["sources"] == SOURCE_EPOCH == current_sources()
        and review["inputs"] == fixed_inputs(),
        "qualification source/policy/input review changed",
    )
    require(
        set(approval) == {"format", "review_sha256", "reference", "approved_utc_ns"}
        and approval["format"] == "mcli1-one-guard-startup-approval-v1"
        and approval["review_sha256"] == sha
        and isinstance(approval["reference"], str)
        and 0 < len(approval["reference"]) <= 256
        and type(approval["approved_utc_ns"]) is int
        and review["created_utc_ns"] <= approval["approved_utc_ns"] <= time.time_ns(),
        "exact native qualification approval is unbound",
    )
    lease = review["original_lease"]
    require(
        time.time_ns() < lease["expires_ns"] - POLICY["review_reserve_ns"]
        and time.monotonic_ns()
        < lease["expires_mono_ns"] - POLICY["review_reserve_ns"],
        "qualification approval is late; no activation",
    )
    return review, approval


def measured_receipts(b, backup_raw):
    """Measure current stopped disk facts before issuing the short start window."""
    paths = start.backup.source_paths("guard")
    source = start.backup.source_paths("executor")["disk"]
    observer = session.NativeObserver("guard")
    frame = observer()
    start.boot.stopped_snapshot(
        b, {k: frame[k] for k in ("observed_mono_ns", "machine", "medium")}
    )
    with start.backup.locked_source(paths["disk"]) as stream:
        target_sha = hashlib.file_digest(stream, "sha256").hexdigest()
    with start.backup.locked_source(source) as stream:
        source_sha = hashlib.file_digest(stream, "sha256").hexdigest()
    require(
        target_sha == b["backup"]["disk_sha256"]
        and source_sha == start.host.SOURCE_DISK_SHA,
        "qualification current disk/source changed",
    )
    frame = observer()
    start.boot.stopped_snapshot(
        b, {k: frame[k] for k in ("observed_mono_ns", "machine", "medium")}
    )
    source_frame = session.NativeObserver("executor")()
    require(
        start.host.machine_fields(source_frame["machine"])["VMState"] == "poweroff"
        and source_frame["session"]["state_before"]
        == source_frame["session"]["state_after"]
        == "Unlocked",
        "preserved executor is not stopped",
    )
    preboot = {
        "format": "mcli1-preboot-disk-v1",
        "run_nonce": b["run_nonce"],
        "target_vm_uuid": b["target"]["vm_uuid"],
        "disk_uuid": b["target"]["disk_uuid"],
        "disk_sha256": target_sha,
        "state": "poweroff",
        "backup_receipt_sha256": digest(backup_raw),
    }
    preservation = {
        "format": "mcli1-source-preservation-v1",
        "run_nonce": b["run_nonce"],
        "target_vm_uuid": b["target"]["vm_uuid"],
        "source_disk_uuid": start.boot.transfer.EXECUTOR_DISK,
        "before_sha256": source_sha,
        "after_sha256": source_sha,
        "state": "poweroff",
    }
    b["disk_evidence"] = {
        "pre_boot_disk_sha256": target_sha,
        "pre_boot_receipt_sha256": digest(canonical(preboot)),
        "source_preservation_receipt_sha256": digest(canonical(preservation)),
    }
    return preboot, preservation


def controller_input(pending, review, review_sha, approval):
    sealed_raw = owner.read_packet(pending.root / "owner.sealed.json")
    packet = start.host.object_bytes(sealed_raw)
    ready_raw = owner.read_packet(pending.root / "owner.ready.json")
    ready = start.host.object_bytes(ready_raw)
    inputs = {
        name: Path(value["path"]).read_bytes()
        for name, value in review["inputs"].items()
    }
    require(
        all(
            digest(raw) == review["inputs"][name]["sha256"]
            for name, raw in inputs.items()
        ),
        "qualification approved receipt bytes changed",
    )
    profile = start.host.object_bytes(inputs["profile"])
    b = start.boot.draft("guard")
    b.update(run_nonce=uuid4().hex, generation=1)
    b["owner"] = {
        "root": str(pending.root),
        "launch_sha256": digest(sealed_raw),
        "ready_sha256": digest(ready_raw),
        "binding_sha256": ready["owner_binding_sha256"],
    }
    b["caller"] = {"role": "controller", "process": packet["controller"]}
    b["target"] = {
        "vm_uuid": profile["target_vm_uuid"],
        "disk_uuid": profile["source_disk_uuid"],
        "dmi_uuid": profile["target_vm_uuid"],
    }
    b["backup"] = start.backup.records.binding(
        start.host.object_bytes(inputs["backup"]), digest(inputs["backup"])
    )
    b["approval"] = {k: approval["reference"] for k in b["approval"]}
    preboot, preservation = measured_receipts(b, inputs["backup"])
    now, mono = time.time_ns(), time.monotonic_ns()
    b["window"] = {
        "issued_utc_ns": now,
        "issued_mono_ns": mono,
        "expires_utc_ns": now + 15 * 10**9,
        "expires_mono_ns": mono + 15 * 10**9,
    }
    grant = start.draft("guard")
    grant.update(
        boot=b,
        profile_receipt_sha256=digest(inputs["profile"]),
        environment_sha256=digest(canonical(start.frontend.frontend_environment())),
        approval={"native_run": approval["reference"]},
    )
    return {
        "format": "mcli1-qualification-controller-input-v1",
        "review_sha256": review_sha,
        "grant": grant,
        "receipts": [
            start.host.object_bytes(inputs["backup"]),
            preboot,
            preservation,
            profile,
        ],
        "sources": dict(SOURCE_EPOCH),
    }


def controller_main(root, external_sha):
    root = Path(root)
    raw = owner.read_packet(root / "controller.input.json")
    require(digest(raw) == external_sha, "qualification controller activation differs")
    payload = start.host.object_bytes(raw)
    review_raw = owner.read_packet(root.parent / "review.json")
    approval_raw = owner.read_packet(root.parent / "approval.json")
    review, _ = approved_review(review_raw, payload["review_sha256"], approval_raw)
    require(
        payload["format"] == "mcli1-qualification-controller-input-v1"
        and payload["sources"] == SOURCE_EPOCH
        and review["controller"] == start.host.process_identity(os.getpid()),
        "qualification controller source/PID differs",
    )
    observer = session.NativeObserver("guard")
    captures = root / "runtime-observations"
    captures.mkdir(exist_ok=False)
    sequence = []

    def capture():
        folder = captures / str(len(sequence) + 1)
        folder.mkdir()
        sequence.append(folder.name)
        observer.last = None
        try:
            return observer()
        finally:
            session.retain(folder, observer)

    def stopped():
        frame = capture()
        return {k: frame[k] for k in ("observed_mono_ns", "machine", "medium")}

    with closing(Store(root / "owner.sqlite")) as store:
        store.db.execute("PRAGMA busy_timeout=50")
        adapter = start._PreparedStart(store, stopped)
        failure, samples = None, []
        try:
            grant_raw = canonical(payload["grant"])
            adapter.start(
                grant_raw, digest(grant_raw), *map(canonical, payload["receipts"])
            )
            begin, wall = time.monotonic_ns(), time.time_ns()
            while len(samples) < POLICY["running_observations"]:
                require(
                    time.monotonic_ns() - begin < POLICY["runtime_limit_ns"]
                    and time.time_ns() - wall < POLICY["runtime_limit_ns"],
                    "qualification runtime sample window ended",
                )
                frame = capture()
                result = adapter.observe(frame)
                if result["status"] == "runtime-session-bound-not-guest-ready":
                    samples.append(
                        {
                            "observed_mono_ns": frame["observed_mono_ns"],
                            "session": frame["session"],
                            "members": adapter.family.members(),
                        }
                    )
                time.sleep(0.1)
            adapter.request_owner_stop()
            end = time.monotonic() + 6
            while adapter.terminal is None and time.monotonic() < end:
                time.sleep(0.01)
            require(
                adapter.terminal is not None,
                "qualification finish watchdog did not return",
            )
        except Exception as error:  # noqa: BLE001 -- preserve the held run and contain without replay
            failure = type(error).__name__ + ": " + str(error)[:256]
        finally:
            outcome = adapter.close()
            owner.publish(
                root / "controller.outcome.json",
                canonical(
                    {
                        "status": "controller-finished-awaiting-independent-stop"
                        if failure is None
                        else "held-controller-qualification",
                        "failure": failure,
                        "review_sha256": payload["review_sha256"],
                        "samples": samples,
                        "retirement": outcome,
                        "guest_ready": False,
                        "native_settlement_qualified": False,
                    }
                ),
            )


def process_retired(record):
    """Prove this exact PID creation is gone; access denial is not a death proof."""
    require(sys.platform == "win32", "native process retirement proof requires Windows")
    from ctypes import wintypes

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes, api.OpenProcess.restype = (
        [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD],
        wintypes.HANDLE,
    )
    api.WaitForSingleObject.argtypes, api.WaitForSingleObject.restype = (
        [wintypes.HANDLE, wintypes.DWORD],
        wintypes.DWORD,
    )
    api.GetProcessTimes.argtypes, api.GetProcessTimes.restype = (
        [wintypes.HANDLE, *([ctypes.c_void_p] * 4)],
        wintypes.BOOL,
    )
    api.CloseHandle.argtypes, api.CloseHandle.restype = [wintypes.HANDLE], wintypes.BOOL
    handle = api.OpenProcess(0x1000 | 0x100000, False, record["pid"])
    if not handle:
        require(
            ctypes.get_last_error() == 87, "process retirement could not be observed"
        )
        return True
    try:
        status = api.WaitForSingleObject(handle, 0)
        require(status in {0, 0x102}, "process retirement wait failed")
        if status == 0:
            return True
        stamps = [ctypes.c_uint64() for _ in range(4)]
        require(
            api.GetProcessTimes(handle, *[ctypes.byref(s) for s in stamps]),
            "process retirement identity unavailable",
        )
        return stamps[0].value != record["created_filetime"]
    finally:
        require(api.CloseHandle(handle), "process retirement handle did not close")


def stop_proof(root, packet, outcome):
    """Independent bootstrap verification. Never issues or retries a VM command."""
    request = start.host.object_bytes(
        owner.read_packet(root / "frontend.owner-stop.intent.json")
    )
    deadline = request["issued_mono_ns"] + POLICY["stop_observation_limit_ns"]
    wall = request["issued_utc_ns"] + POLICY["stop_observation_limit_ns"]
    cleanup = outcome["retirement"]["cleanup"]
    require(
        outcome["failure"] is None
        and "original stop returned" in outcome["retirement"]["reason"]
        and not outcome["retirement"]["errors"]
        and cleanup["job_active_processes"] == 0
        and cleanup["root_exit"] == 0
        and cleanup["terminated"] is False
        and not cleanup["output_fault"]
        and len(outcome["samples"]) == POLICY["running_observations"],
        "qualification did not finish through the original owner and natural process exit",
    )
    with closing(
        sqlite3.connect(
            (root / "owner.sqlite").resolve().as_uri() + "?mode=ro",
            uri=True,
            timeout=0.05,
        )
    ) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")
        lease = db.execute("SELECT * FROM lease").fetchone()
        native = db.execute("SELECT * FROM native_owner_stop").fetchone()
        registered = db.execute("SELECT * FROM maintenance_owner").fetchone()
        authority = db.execute("SELECT * FROM authority").fetchone()
        require(
            {k: lease[k] for k in start.host.OWNER_KEYS} == packet["lease"]
            and lease["state"] == "stop-command-returned"
            and registered["state"] == "stop-returned"
            and authority["active"] == 0
            and native["state"] == "command-returned"
            and native["plan_sha"] == packet["profile"]["bounded_stop"]["sha256"],
            "qualification original stop ledger is incomplete",
        )
        receipt_raw = owner.read_packet(
            owner.stop.STOPS_ROOT / packet["owner_nonce"] / "command.receipt.json"
        )
        receipt = start.host.object_bytes(receipt_raw)
        require(
            digest(receipt_raw) == native["receipt_sha"]
            and receipt["exit"] == 0
            and receipt["job_active_processes"] == 0
            and receipt["child_pid"] == native["child_pid"]
            and receipt["plan_sha256"] == native["plan_sha"]
            and receipt["target_vm_uuid"] == target_uuid()
            and receipt["owner_nonce"] == packet["owner_nonce"],
            "qualification original command receipt differs",
        )
    for sample in outcome["samples"]:
        for process in sample["members"]:
            require(
                process_retired(process),
                "qualification frontend/helper identity remains live",
            )
    observer, frames = session.NativeObserver("guard"), []
    for number in (1, 2):
        require(
            time.monotonic_ns() < deadline and time.time_ns() < wall,
            "qualification independent stop observation exceeded ten seconds",
        )
        folder = root.parent / ("independent-stop-" + str(number))
        folder.mkdir()
        try:
            frame = observer()
            fields = start.host.machine_fields(frame["machine"])
            require(
                fields["VMState"] == "poweroff"
                and frame["session"]
                == {
                    "vm_uuid": target_uuid(),
                    "state_before": "Unlocked",
                    "state_after": "Unlocked",
                    "pid": 0,
                },
                "qualification VM/session is not independently powered off",
            )
            expected = start.boot.transfer.expected_host(
                {
                    "role": "guard",
                    "target": {"disk_uuid": start.backup.SLOTS["guard"]["disk_uuid"]},
                }
            )
            expected["state"] = "poweroff"
            require(
                start.host.machine_profile(frame["machine"]) == expected
                and all(fields.get(k) == v for k, v in start.boot.BOOT_FIELDS.items()),
                "qualification stopped target profile changed",
            )
            frames.append(
                {
                    "observed_mono_ns": frame["observed_mono_ns"],
                    "machine_sha256": digest(frame["machine"]),
                    "medium_sha256": digest(frame["medium"]),
                }
            )
        finally:
            session.retain(folder, observer)
    require(
        time.monotonic_ns() < deadline and time.time_ns() < wall,
        "qualification stop proof finished after ten seconds",
    )
    return {
        "status": "one-native-start-session-and-normal-stop-measured",
        "stop_receipt_sha256": digest(receipt_raw),
        "observations": frames,
        "stop_elapsed_ns": time.monotonic_ns() - request["issued_mono_ns"],
        "guest_ready": False,
        "late_detached_start_failure_cases_qualified": False,
    }


def target_uuid():
    return start.backup.SLOTS["guard"]["vm_uuid"]


def prepare(output):
    root = new_root(output)
    nonce = uuid4().hex
    job = start.frontend.ControllerJob("Local\\MCLI1Controller-" + nonce)
    code = f"import sys;sys.path.insert(0,{str(ROOT)!r});from research.validation.startup_qualification import controller_main;controller_main({str(root / 'owner')!r},sys.stdin.buffer.read(65).strip().decode('ascii'))"
    controller = launch.SuspendedChild(["-I", "-B", "-c", code], job)
    pending = None
    terminal = {"status": "expired-or-aborted-unarmed-review", "VM_boots": 0}
    try:
        pending = launch.PendingOwner(
            root / "owner",
            "guard",
            nonce,
            start.host.process_identity(controller.pid),
            time.time_ns() + POLICY["original_lease_ns"],
            "conversation:approved-direct-frontend-preparation;suspended-Python-only",
        )
        review = {
            "format": "mcli1-one-guard-startup-review-v1",
            "created_utc_ns": time.time_ns(),
            "policy": dict(POLICY),
            "sources": dict(SOURCE_EPOCH),
            "inputs": fixed_inputs(),
            "original_lease": pending.lease,
            "original_stop_proposal": pending.proposal,
            "controller": pending.controller,
            "bootstrap": pending.bootstrap,
            "owner": pending.owner,
            "native_argv": [
                str(start.frontend.HEADLESS),
                "--startvm",
                target_uuid(),
                "--vrde",
                "off",
            ],
            "native_executable_sha256": start.frontend.HEADLESS_SHA256,
            "environment_sha256": digest(
                canonical(start.frontend.frontend_environment())
            ),
            "native_boot_authorized": False,
        }
        raw = canonical(review)
        owner.publish(root / "review.json", raw)
        print(
            canonical(
                {
                    "status": "suspended-review-ready",
                    "path": str(root / "review.json"),
                    "sha256": digest(raw),
                    "original_lease": pending.lease,
                    "VM_boots": 0,
                }
            ).decode(),
            flush=True,
        )
        while (
            time.time_ns() < pending.lease["expires_ns"] - POLICY["review_reserve_ns"]
            and time.monotonic_ns()
            < pending.lease["expires_mono_ns"] - POLICY["review_reserve_ns"]
        ):
            if (root / "abort").exists():
                return terminal
            if (root / "approval.json").exists():
                break
            require(
                controller.poll() is None
                and pending.child.poll() is None
                and current_sources() == SOURCE_EPOCH,
                "provisional process/source changed during review",
            )
            time.sleep(0.1)
        else:
            return terminal
        review, approval = approved_review(
            raw, digest(raw), owner.read_packet(root / "approval.json")
        )
        plan = json.loads(canonical(pending.proposal))
        plan["approval"]["native_stop"] = approval["reference"]
        pending.seal(canonical(plan), digest(canonical(plan)), approval["reference"])
        pending.ready()
        payload = controller_input(pending, review, digest(raw), approval)
        input_raw = canonical(payload)
        owner.publish(pending.root / "controller.input.json", input_raw)
        controller.resume(digest(input_raw).encode() + b"\n")
        end = time.monotonic() + 60
        while controller.poll() is None and time.monotonic() < end:
            time.sleep(0.05)
        require(
            controller.poll() == 0,
            "qualification controller did not exit successfully; no replay",
        )
        outcome = start.host.object_bytes(
            owner.read_packet(pending.root / "controller.outcome.json")
        )
        packet = start.host.object_bytes(
            owner.read_packet(pending.root / "owner.sealed.json")
        )
        terminal = stop_proof(pending.root, packet, outcome)
        source = start.backup.source_paths("executor")["disk"]
        with start.backup.locked_source(source) as stream:
            require(
                hashlib.file_digest(stream, "sha256").hexdigest()
                == start.host.SOURCE_DISK_SHA,
                "qualification changed the preserved executor disk",
            )
        terminal["source_disk_preserved"] = True
        terminal["VM_boots"] = 1
        return terminal
    except Exception as error:
        terminal = {
            "status": "held-startup-qualification-no-replay",
            "error": type(error).__name__ + ": " + str(error)[:256],
            "VM_boots": "inspect-durable-start-intent",
            "native_settlement_qualified": False,
        }
        raise
    finally:
        job.close()  # Contains controller/family even if a result/query was lost.
        controller.close()
        if pending is not None:
            pending.close()  # A sealed owner retains its independent job/lease.
        owner.publish(root / "qualification.terminal.json", canonical(terminal))
        print(canonical(terminal).decode(), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("preview", "prepare"), default="preview", nargs="?"
    )
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.command == "preview":
        print(
            canonical(
                {
                    "status": "unarmed-qualification-preview",
                    "policy": POLICY,
                    "inputs": fixed_inputs(),
                    "sources": SOURCE_EPOCH,
                    "native_calls": 0,
                }
            ).decode()
        )
    else:
        require(
            args.output is not None,
            "qualification preparation needs a new output directory",
        )
        prepare(args.output)


if __name__ == "__main__":
    main()
