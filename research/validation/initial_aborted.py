"""Approved initial-Aborted preparation: read-only inventory and unattached copies.

There is no owner activation, VM start/stop, configuration edit, registration,
installation or restore operation. Native activation requires a separate review.
"""

import argparse
import hashlib
import json
import os
import time
import xml.etree.ElementTree as ET
from contextlib import ExitStack
from pathlib import Path
from uuid import uuid4

from . import boot_preconditions as boot
from . import maintenance_host as host
from . import native_session as session
from . import owner_process as owner
from . import process_proof
from . import recovery_records as model
from . import stopped_backup as backup
from .offline_repo import description, new_root
from .transfer_commands import canonical, digest
from .windows_readonly import require

ROOT = backup.ROOT
CAPTURE_RELATIVE = ".local/validation/initial-aborted-capture-01"
PROFILE_FORMAT = "mcli1-aborted-current-profile-v1"
OFFLINE_COPY_SECONDS = 600
EXECUTOR_FILES = {
    "disk": {"state": "file", "bytes": 2625634304, "sha256": host.SOURCE_DISK_SHA},
    "configuration": {
        "state": "file",
        "bytes": 3239,
        "sha256": "5dfe5bc297f585a934bb2090797c365fafcfbd4bb7cbe785c8916f1da7ccf4f2",
    },
    "nvram": {
        "state": "file",
        "bytes": 540672,
        "sha256": "cdfcb7d4b7eb19f0a4d990481704fbd02f81272e6f32d0651ed4a726546ce521",
    },
}
SOURCES = {
    **boot.SOURCES,
    **session.SOURCES,
    "initial_aborted.py": Path(__file__),
    "process_proof.py": Path(process_proof.__file__),
    "recovery_records.py": Path(model.__file__),
}
SOURCE_EPOCH = {name: digest(path.read_bytes()) for name, path in SOURCES.items()}


def source_pins():
    require(
        SOURCE_EPOCH == {n: digest(p.read_bytes()) for n, p in SOURCES.items()},
        "recovery preparation source changed",
    )


def _attempt_snapshot(*, kind, retired):
    """Reconcile fixed prior records and prove the original PID creations gone."""
    inputs = {
        "initial": (
            model.PRIOR_ROOT,
            model.PRIOR_REVIEW,
            model.PRIOR_ARTIFACTS,
            None,
            None,
            True,
        ),
        "lock": (
            model.INTERVENING_ROOT,
            model.INTERVENING_REVIEW,
            model.INTERVENING_ARTIFACTS,
            model.PARENT_CONTEXT,
            model.PARENT_CONTEXT_SHA256,
            False,
        ),
        "journal": (
            model.LATEST_ROOT,
            model.LATEST_REVIEW,
            model.LATEST_ARTIFACTS,
            model.LATEST_PARENT_CONTEXT,
            model.LATEST_PARENT_SHA256,
            True,
        ),
    }
    relative, expected_review, artifacts, parent_path, parent_sha, terminated = inputs[
        kind
    ]
    root = backup.safe(ROOT / relative)
    review_raw = owner.read_packet(root / "review.json")
    require(digest(review_raw) == expected_review, "recovery prior review differs")
    review = host.object_bytes(review_raw)
    nonce = review["original_stop_proposal"]["owner_nonce"]
    stoproot = backup.safe(owner.stop.STOPS_ROOT / nonce)
    raw = {}
    for name in artifacts:
        path = (
            stoproot / name.removeprefix("stop/")
            if name.startswith("stop/")
            else ROOT / parent_path
            if name == "parent/recovery.json"
            else root / "owner/runtime-observations/12" / name.removeprefix("running/")
            if name.startswith("running/")
            else root / name
        )
        raw[name] = owner.read_packet(backup.safe(path))
    packet = host.object_bytes(raw["owner/owner.sealed.json"])
    approval = host.object_bytes(raw["approval.json"])
    outcome = host.object_bytes(raw["owner/controller.outcome.json"])
    terminal = host.object_bytes(raw["owner/frontend.terminal.json"])
    resume = host.object_bytes(raw["owner/frontend.resume.intent.json"])
    intent = host.object_bytes(raw["owner/frontend.start.intent.json"])
    inspection = host.object_bytes(raw["independent-startup-inspection.json"])
    result = host.object_bytes(raw["stop/process.result.json"])
    stop_intent = host.object_bytes(raw["stop/poweroff.intent.json"])
    cleanup = outcome["retirement"]["cleanup"]
    stop_row = inspection["journal"]["native_owner_stop"]
    require(
        packet["owner_nonce"] == nonce
        and approval["format"] == "mcli1-one-guard-startup-approval-v1"
        and approval["review_sha256"] == expected_review
        and approval["reference"]
        == packet["profile"]["bounded_stop"]["plan"]["approval"]["native_stop"]
        and host.object_bytes(raw["qualification.terminal.json"])["status"]
        == "held-startup-qualification-no-replay"
        and packet["lease"] == review["original_lease"]
        and all(packet[k] == review[k] for k in ("bootstrap", "controller", "owner"))
        and outcome["review_sha256"] == expected_review
        and outcome["status"] == "held-controller-qualification"
        and outcome["failure"] is not None
        and outcome["samples"] == []
        and outcome["guest_ready"] is False
        and outcome["native_settlement_qualified"] is False
        and terminal == outcome["retirement"]
        and intent["grant_sha256"] == resume["grant_sha256"] == terminal["grant_sha256"]
        and cleanup["job_active_processes"] == 0
        and cleanup["terminated"] is terminated
        and cleanup["root_pid"] == resume["process"]["pid"]
        and terminal["original_stop_accepted"] is False
        and terminal["VM_poweroff_proven"] is False,
        "recovery prior startup/containment facts differ",
    )
    require(
        len(stop_row) == 1
        and stop_row[0]["state"] == "possible-send"
        and stop_row[0]["receipt_sha"] is None
        and result["pid"] == stop_row[0]["child_pid"]
        and type(result["exit"]) is int
        and result["exit"] == 1
        and type(result["job_active_processes"]) is int
        and result["job_active_processes"] == 0
        and result["command_sha256"]
        == stop_intent["command_sha256"]
        == digest(
            canonical([str(owner.stop.VBOX), "controlvm", model.GUARD_VM, "poweroff"])
        )
        and result["stderr_sha256"] == digest(raw["stop/stderr.bin"])
        and result["stdout_sha256"] == digest(raw["stop/stdout.bin"])
        and b"not currently running" in raw["stop/stderr.bin"]
        and not (stoproot / "command.receipt.json").exists()
        and host.object_bytes(raw["owner/owner.terminal.json"])["status"]
        == "held-owner-state-not-accepted",
        "recovery prior stop is not the fixed consumed nonzero result",
    )
    processes = {name: review[name] for name in ("bootstrap", "controller", "owner")}
    processes["frontend"] = resume["process"]
    require(
        all(retired(p) is True for p in processes.values()),
        "recovery prior process remains live",
    )
    value = {
        "review_sha256": expected_review,
        "owner_nonce": nonce,
        "artifacts": {name: digest(data) for name, data in raw.items()},
        "processes": processes,
        "stop_child_pid": result["pid"],
        "stop_exit": result["exit"],
        "frontend_job_active_processes": cleanup["job_active_processes"],
        "stop_job_active_processes": result["job_active_processes"],
    }
    if kind != "initial":
        family = cleanup["retained_process_exits"]
        require(
            cleanup["root_exit"] == (2 if kind == "journal" else 1)
            and digest(raw["parent/recovery.json"]) == parent_sha
            and review["inputs"]["recovery"]["sha256"] == parent_sha
            and (
                kind == "journal"
                or b"already locked for a session" in raw["owner/frontend.stderr.bin"]
            ),
            "follow-up native failure/parent differs",
        )
        require(
            digest(raw["owner/frontend.stderr.bin"]) == cleanup["stderr_sha256"]
            and len(raw["owner/frontend.stderr.bin"]) == cleanup["stderr_bytes"],
            "intervening frontend stderr differs from cleanup",
        )
        postfiles = host.object_bytes(raw["postfiles/receipt.json"])["files"]
        guard_files = model.FILES if kind == "journal" else model.HISTORICAL_FILES
        for role, expected in (("guard", guard_files), ("executor", EXECUTOR_FILES)):
            require(
                {
                    name: {k: row[k] for k in ("state", "bytes", "sha256") if k in row}
                    for name, row in postfiles[role].items()
                }
                == expected,
                "intervening preserved backing files differ",
            )
        value.update(parent_context_sha256=parent_sha, family=family)
        if kind == "journal":
            receipt = host.object_bytes(raw["owner/frontend.session.receipt.json"])
            binding = inspection["journal"]["frontend_start"]
            record = session.session_record(raw["running/session_raw.stdout"], "guard")
            require(
                outcome["failure"] == "OperationalError: database is locked"
                and len(binding) == 1
                and binding[0]["state"] == "resumed"
                and binding[0]["receipt_sha"] is None
                and binding[0]["grant_sha"] == terminal["grant_sha256"]
                and receipt["grant_sha256"] == terminal["grant_sha256"]
                and receipt["original_lease"] == packet["lease"]
                and record["state_before"] == record["state_after"] == 2
                and record["machine_before"] == record["machine_after"] == 6
                and receipt["process"]["pid"] == record["pid"],
                "latest running observation/orphan journal facts differ",
            )
            grant = {
                "role": "guard",
                "target": {"disk_uuid": model.GUARD_DISK, "vm_uuid": model.GUARD_VM},
            }
            expected = host.transfer.expected_host(grant)
            expected["state"] = "running"
            for name in ("running/machine_first.stdout", "running/machine.stdout"):
                fields = host.machine_fields(raw[name])
                require(
                    host.machine_profile(raw[name]) == expected
                    and fields["hardwareuuid"] == model.GUARD_VM
                    and all(fields.get(k) == v for k, v in boot.BOOT_FIELDS.items()),
                    "latest retained running profile differs",
                )
            host.check_medium(
                raw["running/medium.stdout"], raw["running/machine.stdout"], grant
            )
            value.update(
                joined_process=receipt["process"],
                join_receipt_sha256=digest(raw["owner/frontend.session.receipt.json"]),
                frontend_ledger_state=binding[0]["state"],
                frontend_ledger_receipt_sha=binding[0]["receipt_sha"],
            )
            model.checked_latest(value)
        else:
            model.checked_intervening(value)
        require(
            all(
                retired({k: p[k] for k in ("pid", "created_filetime", "image")}) is True
                for p in family
            ),
            "intervening family remains live",
        )
    return value


def prior_snapshot(*, retired=process_proof.retired):
    return _attempt_snapshot(kind="initial", retired=retired)


def intervening_snapshot(*, retired=process_proof.retired):
    return _attempt_snapshot(kind="lock", retired=retired)


def latest_snapshot(*, retired=process_proof.retired):
    return _attempt_snapshot(kind="journal", retired=retired)


def live_context(context):
    """Fresh prior provenance; it never accepts a stop or grants native authority."""
    value = model.checked(context)
    source_pins()
    require(
        value["sources"] == SOURCE_EPOCH
        and value["prior"] == prior_snapshot()
        and value["intervening"] == intervening_snapshot(),
        "recovery context prior/source provenance changed",
    )
    require(
        value["latest"] == latest_snapshot(),
        "latest recovery provenance changed",
    )
    return value


def observed(role, frame):
    slot = backup.SLOTS[role]
    state = "aborted" if role == "guard" else "poweroff"
    machine_state = 4 if role == "guard" else 1
    grant = {
        "role": role,
        "target": {"vm_uuid": slot["vm_uuid"], "disk_uuid": slot["disk_uuid"]},
    }
    expected = host.transfer.expected_host(grant)
    expected["state"] = state
    fields = host.machine_fields(frame["machine"])
    require(
        type(frame["observed_mono_ns"]) is int
        and 0 <= time.monotonic_ns() - frame["observed_mono_ns"] <= 5 * 10**9
        and host.machine_profile(frame["machine"]) == expected
        and fields["hardwareuuid"] == slot["vm_uuid"]
        and all(fields.get(k) == v for k, v in boot.BOOT_FIELDS.items())
        and frame["session"]
        == {
            "vm_uuid": slot["vm_uuid"],
            "state_before": "Unlocked",
            "state_after": "Unlocked",
            "pid": 0,
        }
        and type(frame["session"]["pid"]) is int,
        "recovery target/source is not the exact quiescent disconnected profile",
    )
    native_session = session.session_record(frame["session_raw"], role)
    require(
        native_session["machine_before"]
        == native_session["machine_after"]
        == machine_state
        and native_session["state_before"] == native_session["state_after"] == 1
        and native_session["pid"] == 0,
        "recovery machine/session raw observation differs",
    )
    host.check_medium(frame["medium"], frame["machine"], grant)
    require(
        host.medium_fields(frame["medium"])["State"] == "created",
        "recovery stopped medium remains locked",
    )
    return {
        "observed_mono_ns": frame["observed_mono_ns"],
        "machine_sha256": digest(frame["machine"]),
        "medium_sha256": digest(frame["medium"]),
        "session_sha256": digest(frame["session_raw"]),
    }


def profile(context, backup_receipt_sha):
    value = model.checked(context)
    return {
        "format": PROFILE_FORMAT,
        "status": "aborted-profile-reported-not-boot-authority",
        "role": "guard",
        "target_vm_uuid": model.GUARD_VM,
        "source_disk_uuid": model.GUARD_DISK,
        "initial_state": "aborted",
        "recovery_context_sha256": model.context_sha256(value),
        "backup_receipt_sha256": backup_receipt_sha,
        "disk_sha256": value["files"]["disk"]["sha256"],
        "configuration": value["files"]["configuration"],
        "nvram": value["files"]["nvram"],
        **value["last_observation"],
        "VM_mutations": 0,
        "VM_started": False,
        "native_boot_authorized": False,
        "network_enabled": False,
        "sources": dict(SOURCE_EPOCH),
    }


def load_capture(capture_relative=None):
    """Load complete fixed preparation metadata; admission still rehashes files."""
    relative = CAPTURE_RELATIVE if capture_relative is None else capture_relative
    require(
        type(relative) is str and 0 < len(relative) <= 32768 and "\x00" not in relative,
        "recovery capture directory is unbound",
    )
    root = backup.safe(ROOT / relative)
    paths = {
        "recovery": root / "recovery.json",
        "backup": root / "backup/receipt.json",
        "profile": root / "profile.json",
        "preparation": root / "preparation.receipt.json",
    }
    raw = {name: owner.read_packet(backup.safe(path)) for name, path in paths.items()}
    context = live_context(host.object_bytes(raw["recovery"]))
    require(
        digest(raw["recovery"]) == model.context_sha256(context),
        "recovery context encoding differs",
    )
    marker = host.object_bytes(raw["preparation"])
    require(
        marker
        == {
            "status": "initial-aborted-preparation-reported-not-boot-authority",
            "context": description(paths["recovery"]),
            "backup": description(paths["backup"]),
            "profile": description(paths["profile"]),
            "VM_mutations": 0,
            "native_boot_authorized": False,
        },
        "recovery preparation is incomplete or changed",
    )
    receipt = host.object_bytes(raw["backup"])
    binding = backup.records.binding(receipt, digest(raw["backup"]), recovery=context)
    grant = {
        "role": "guard",
        "target": {"vm_uuid": model.GUARD_VM, "disk_uuid": model.GUARD_DISK},
        "backup": binding,
        "disk_evidence": {"pre_boot_disk_sha256": model.FILES["disk"]["sha256"]},
    }
    backup.records.checked_receipt(
        receipt, digest(raw["backup"]), grant, recovery=context
    )
    require(
        host.object_bytes(raw["profile"]) == profile(context, digest(raw["backup"])),
        "recovery profile provenance differs",
    )
    return context, {
        name: {"path": str(path), "sha256": digest(raw[name])}
        for name, path in paths.items()
    }


def capture(
    output,
    *,
    observer_factory=session.NativeObserver,
    prior_check=prior_snapshot,
    intervening_check=None,
    latest_check=None,
    locker=backup.locked_source,
):
    source_pins()
    prior = prior_check()
    intervening_check = (
        intervening_snapshot if intervening_check is None else intervening_check
    )
    intervening = intervening_check()
    latest_check = latest_snapshot if latest_check is None else latest_check
    latest = latest_check()
    root = new_root(backup.safe(ROOT / output))
    (root / "backup").mkdir()
    observations = root / "observations"
    observations.mkdir()
    owner.publish(
        root / "intent.json",
        canonical(
            {
                "status": "recovery-copying-not-accepted",
                "prior": prior,
                "intervening": intervening,
                "latest": latest,
                "expected_files": model.FILES,
                "sources": SOURCE_EPOCH,
                "VM_mutations": 0,
            }
        ),
    )

    def observe(role, name):
        folder = observations / name
        folder.mkdir()
        observer = observer_factory(role)
        try:
            frame = observer()
            frame = {**frame, "session_raw": observer.last["session_raw"]}
            return observed(role, frame)
        finally:
            session.retain(folder, observer)

    paths = backup.source_paths("guard")
    files = {}
    first = observe("guard", "guard-before")
    source_before = observe("executor", "executor-before")
    with ExitStack() as stack:
        opened = {}
        for label, path in paths.items():
            if model.FILES[label]["state"] == "file":
                opened[label] = stack.enter_context(locker(path))
            else:
                require(
                    not path.exists() and not path.is_symlink(),
                    "recovery absent NVRAM appeared",
                )
        source_paths = backup.source_paths("executor")
        source_opened = {
            name: stack.enter_context(locker(path))
            for name, path in source_paths.items()
        }
        cfg = opened["configuration"]
        raw_cfg = cfg.read(64 * 1024 + 1)
        cfg.seek(0)
        require(
            len(raw_cfg) <= 64 * 1024
            and digest(raw_cfg) == model.FILES["configuration"]["sha256"],
            "recovery current configuration differs",
        )
        machine = ET.fromstring(raw_cfg).find("{http://www.virtualbox.org/}Machine")
        require(
            machine is not None
            and machine.attrib.get("aborted") == "true"
            and not any("statefile" in k.lower() for k in machine.attrib)
            and machine.find("{http://www.virtualbox.org/}Snapshot") is None,
            "recovery contains a saved execution state/snapshot",
        )
        deadline = time.monotonic() + OFFLINE_COPY_SECONDS
        for label, path in paths.items():
            expected = model.FILES[label]
            row = {**expected, "source_relative": path.relative_to(ROOT).as_posix()}
            if label in opened:
                dest = backup.safe(
                    root
                    / "backup"
                    / {
                        "disk": "disk.vdi",
                        "configuration": "configuration.vbox",
                        "nvram": "nvram.bin",
                    }[label]
                )
                identities = backup.copy_file(opened[label], dest, expected, deadline)
                require(
                    identities["source_identity"] != identities["backup_identity"],
                    "recovery backup aliases source",
                )
                row.update(
                    identities, backup_relative=dest.relative_to(ROOT).as_posix()
                )
            else:
                row["backup_relative"] = None
            files[label] = row
        source_files = {}
        for name, stream in source_opened.items():
            measured = {
                "state": "file",
                "bytes": os.fstat(stream.fileno()).st_size,
                "sha256": hashlib.file_digest(stream, "sha256").hexdigest(),
            }
            require(
                measured == EXECUTOR_FILES[name],
                "recovery preserved executor file changed",
            )
            source_files[name] = measured
        source_identities = {
            name: backup.file_identity(os.fstat(stream.fileno()))
            for name, stream in source_opened.items()
        }
        # Native inventory may initialize/refresh its configuration cache. Keep
        # those reads outside write-excluding file locks, then reacquire and
        # independently rehash before publishing any completed preparation.
        stack.close()
        last = observe("guard", "guard-after")
        source_after = observe("executor", "executor-after")
        require(
            all(
                source_before[k] == source_after[k]
                for k in ("machine_sha256", "medium_sha256", "session_sha256")
            ),
            "recovery preserved source observation changed",
        )
        for label, path in paths.items():
            backup.safe(path)
            if label in opened:
                opened[label] = stack.enter_context(locker(path))
                require(
                    backup.file_identity(path.stat())
                    == backup.file_identity(os.fstat(opened[label].fileno()))
                    == files[label]["source_identity"]
                    and os.fstat(opened[label].fileno()).st_size
                    == model.FILES[label]["bytes"]
                    and hashlib.file_digest(opened[label], "sha256").hexdigest()
                    == model.FILES[label]["sha256"],
                    "recovery source path replaced",
                )
            else:
                require(
                    not path.exists() and not path.is_symlink(),
                    "recovery absent NVRAM appeared",
                )
        for name, path in source_paths.items():
            backup.safe(path)
            source_opened[name] = stack.enter_context(locker(path))
            require(
                backup.file_identity(path.stat())
                == backup.file_identity(os.fstat(source_opened[name].fileno()))
                == source_identities[name]
                and os.fstat(source_opened[name].fileno()).st_size
                == EXECUTOR_FILES[name]["bytes"]
                and hashlib.file_digest(source_opened[name], "sha256").hexdigest()
                == EXECUTOR_FILES[name]["sha256"],
                "recovery preserved executor path changed",
            )
        require(prior == prior_check(), "recovery prior provenance changed during copy")
        require(
            intervening == intervening_check(),
            "intervening provenance changed during copy",
        )
        require(latest == latest_check(), "latest provenance changed during copy")
        source_pins()
        context = model.checked(
            {
                "format": model.FORMAT,
                "role": "guard",
                "target_vm_uuid": model.GUARD_VM,
                "source_disk_uuid": model.GUARD_DISK,
                "initial_state": "aborted",
                "session_state": "Unlocked",
                "session_pid": 0,
                "prior": prior,
                "intervening": intervening,
                "latest": latest,
                "files": model.FILES,
                "first_observation": first,
                "last_observation": last,
                "completed_utc_ns": time.time_ns(),
                "sources": SOURCE_EPOCH,
                "VM_mutations": 0,
                "VM_started": False,
                "native_boot_authorized": False,
            }
        )
        context_sha = model.context_sha256(context)
        receipt = {
            "format": backup.records.RECOVERY_RECEIPT_FORMAT,
            "backup_id": uuid4().hex,
            "role": "guard",
            "target_vm_uuid": model.GUARD_VM,
            "source_disk_uuid": model.GUARD_DISK,
            "source_machine_state": "aborted",
            "source_session_state": "Unlocked",
            "source_session_pid": 0,
            "recovery_context_sha256": context_sha,
            "offline_copy_budget_ns": OFFLINE_COPY_SECONDS * 10**9,
            "independent": True,
            "never_attach": True,
            "files": files,
            "first_observation": first,
            "last_observation": last,
            "source_preservation": {
                "files": source_files,
                "before": source_before,
                "after": source_after,
            },
            "sources": SOURCE_EPOCH,
            "completed_utc_ns": time.time_ns(),
            "status": "aborted-backup-reported-not-boot-authority",
        }
        receipt_raw = canonical(receipt)
        binding = backup.records.binding(receipt, digest(receipt_raw), recovery=context)
        owner.publish(root / "recovery.json", canonical(context))
        owner.publish(root / "backup/receipt.json", receipt_raw)
        owner.publish(root / "backup/binding.json", canonical(binding))
        owner.publish(
            root / "profile.json", canonical(profile(context, digest(receipt_raw)))
        )
    require(
        backup.verify_files(receipt_raw, digest(receipt_raw), recovery=context)
        == binding,
        "recovery independent backup verification differs",
    )
    source_pins()
    result = {
        "status": "initial-aborted-preparation-reported-not-boot-authority",
        "context": description(root / "recovery.json"),
        "backup": description(root / "backup/receipt.json"),
        "profile": description(root / "profile.json"),
        "VM_mutations": 0,
        "native_boot_authorized": False,
    }
    owner.publish(root / "preparation.receipt.json", canonical(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("preview", "capture"), nargs="?", default="preview"
    )
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.command == "preview":
        result = {
            "format": model.FORMAT,
            "prior_review_sha256": model.PRIOR_REVIEW,
            "files": model.FILES,
            "VM_mutations": 0,
            "native_boot_authorized": False,
            "status": "unarmed-recovery-preparation-preview",
        }
    else:
        require(
            args.output is not None,
            "recovery capture requires a new workspace output directory",
        )
        result = capture(args.output)
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
