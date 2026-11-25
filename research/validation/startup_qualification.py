"""Prepare one disconnected guard startup/session/normal-stop qualification.

Preparation creates only suspended Python controller/owner processes. It publishes
their exact identities, original lease, stop proposal and source/input hashes for
review. Only a separately approved, matching review reply can activate them.
No guest command, installation, networking, restore or second boot is provided.
"""

import argparse
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
from . import process_proof
from .offline_repo import new_root
from .store import Store
from .transfer_commands import canonical, digest
from .windows_readonly import require

ROOT = start.backup.ROOT
SOURCES = {
    **start.SOURCES,
    "startup_qualification.py": Path(__file__),
    "process_proof.py": Path(process_proof.__file__),
    "offline_startup.py": Path(__file__).with_name("offline_startup.py"),
}
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
    "preactivation": "read-only-target-and-source-stopped-proof",
    "bootstrap_owner_exit_wait_ns": 5 * 10**9,
}
RECOVERY_REVIEW_FORMAT = "mcli1-one-guard-recovery-review-v1"
LOSS_REVIEW_FORMAT = "mcli1-one-guard-controller-loss-review-v1"
LOSS_EXIT = 29
BOUND_REVIEW_FORMAT = "mcli1-offline-guard-runtime-binding-v1"


def is_controller_loss(review):
    return review.get("format") == LOSS_REVIEW_FORMAT or (
        review.get("format") == BOUND_REVIEW_FORMAT
        and review.get("case") == "controller-loss"
    )


def current_sources():
    return {n: digest(p.read_bytes()) for n, p in SOURCES.items()}


def fixed_inputs(*, recovery=False, capture_relative=None):
    if recovery:
        return start.recovery_host.load_capture(capture_relative)[1]
    require(capture_relative is None, "ordinary review cannot select recovery inputs")
    paths = {
        "backup": ROOT / ".local/validation/stopped-backup-guard-02/receipt.json",
        "profile": ROOT / ".local/validation/stopped-refresh-03/profile.json",
    }
    return {
        name: {
            "path": str(start.backup.safe(path)),
            "sha256": digest(path.read_bytes()),
        }
        for name, path in paths.items()
    }


def review_policy(recovery, inputs, *, controller_loss=False):
    require(not (recovery and controller_loss), "controller loss is poweroff-only")
    value = dict(POLICY)
    if recovery:
        value.update(
            initial_machine_state="aborted",
            recovery_context_sha256=inputs["recovery"]["sha256"],
        )
    if controller_loss:
        value.update(
            fault="abrupt-controller-exit-after-two-running-samples",
            fault_exit_code=LOSS_EXIT,
            original_stop_failure_remains_held=True,
            normal_stop_acceptance=False,
        )
    return value


def approved_review(raw, sha, approval_raw):
    require(
        type(raw) is bytes and digest(raw) == sha, "qualification review digest differs"
    )
    review = start.host.object_bytes(raw)
    approval = start.host.object_bytes(approval_raw)
    is_recovery = review.get("format") == RECOVERY_REVIEW_FORMAT
    is_loss = review.get("format") == LOSS_REVIEW_FORMAT
    if is_recovery:
        require(
            type(review.get("capture_relative")) is str,
            "recovery review capture directory is unbound",
        )
        inputs = fixed_inputs(
            recovery=True, capture_relative=review["capture_relative"]
        )
    else:
        inputs = fixed_inputs()
    require(
        review["format"]
        in {
            "mcli1-one-guard-startup-review-v1",
            RECOVERY_REVIEW_FORMAT,
            LOSS_REVIEW_FORMAT,
        }
        and review["policy"]
        == review_policy(is_recovery, inputs, controller_loss=is_loss)
        and review["sources"] == SOURCE_EPOCH == current_sources()
        and review["inputs"] == inputs,
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


def preactivation_probe(root, review):
    """Read-only checks while both controller and original owner are suspended.

    A timeout or stale/changed target must leave the native stop path unarmed.
    These checks do not replace the later original-owner/lease start gate.
    """
    require(
        review["native_argv"]
        == [str(start.frontend.HEADLESS), "--startvm", target_uuid(), "--vrde", "off"]
        and review["native_executable_sha256"] == start.frontend.HEADLESS_SHA256,
        "qualification reviewed frontend command differs",
    )
    start.image_environment(
        {
            "executable": {"sha256": review["native_executable_sha256"]},
            "environment_sha256": review["environment_sha256"],
        }
    )
    raw_inputs = {
        name: Path(row["path"]).read_bytes() for name, row in review["inputs"].items()
    }
    context = (
        start.recovery_host.live_context(
            start.host.object_bytes(raw_inputs["recovery"])
        )
        if review.get("format") == RECOVERY_REVIEW_FORMAT
        else None
    )
    require(
        all(
            digest(raw) == review["inputs"][name]["sha256"]
            for name, raw in raw_inputs.items()
        ),
        "preactivation receipt bytes changed",
    )
    profile = start.host.object_bytes(raw_inputs["profile"])
    guard = start.boot.draft("guard")
    guard["target"].update(
        vm_uuid=target_uuid(),
        dmi_uuid=target_uuid(),
        disk_uuid=start.backup.SLOTS["guard"]["disk_uuid"],
    )
    guard["backup"] = start.backup.records.binding(
        start.host.object_bytes(raw_inputs["backup"]),
        digest(raw_inputs["backup"]),
        recovery=context,
    )
    guard["disk_evidence"]["pre_boot_disk_sha256"] = profile["disk_sha256"]
    start.profile_binding(
        {
            **(
                {"format": start.RECOVERY_FORMAT, "recovery": context}
                if context is not None
                else {}
            ),
            "boot": guard,
            "profile_receipt_sha256": review["inputs"]["profile"]["sha256"],
        },
        raw_inputs["profile"],
    )
    paths = start.backup.source_paths("guard")
    require(
        start.backup.file_state(paths["configuration"]) == profile["configuration"]
        and start.backup.file_state(paths["nvram"]) == profile["nvram"],
        "preactivation current configuration/firmware changed",
    )
    if context is not None:
        source_paths = start.backup.source_paths("executor")
        require(
            all(
                start.backup.file_state(source_paths[k])
                == start.recovery_host.EXECUTOR_FILES[k]
                for k in ("configuration", "nvram")
            ),
            "recovery preserved executor configuration/firmware changed",
        )
    captures = root / "preactivation-observations"
    captures.mkdir(exist_ok=False)
    observations = {}
    for role in ("guard", "executor"):
        folder = captures / role
        folder.mkdir()
        observer = session.NativeObserver(role)
        try:
            frame = observer()
            slot = start.backup.SLOTS[role]
            b = guard if role == "guard" else start.boot.draft(role)
            b["target"].update(
                vm_uuid=slot["vm_uuid"],
                disk_uuid=slot["disk_uuid"],
                dmi_uuid=slot["vm_uuid"],
            )
            observed = start.boot.stopped_snapshot(
                b,
                {k: frame[k] for k in ("observed_mono_ns", "machine", "medium")},
                recovery=context if role == "guard" else None,
            )
            require(
                frame["session"]
                == {
                    "vm_uuid": slot["vm_uuid"],
                    "state_before": "Unlocked",
                    "state_after": "Unlocked",
                    "pid": 0,
                },
                "preactivation session is not stopped and unlocked",
            )
            if role == "guard":
                require(
                    observed["machine_sha256"] == profile["machine_sha256"]
                    and observed["medium_sha256"] == profile["medium_sha256"],
                    "preactivation guard profile bytes differ",
                )
            observations[role] = observed
        finally:
            session.retain(folder, observer)
    require(
        all(
            0 <= time.monotonic_ns() - row["observed_mono_ns"] <= 5 * 10**9
            for row in observations.values()
        ),
        "preactivation observations aged out",
    )
    owner.publish(
        root / "preactivation.receipt.json",
        canonical(
            {
                "status": "read-only-preactivation-reported-not-start-authority",
                "observations": observations,
                "owner_activated": False,
                "native_stop_commands": 0,
                "VM_boots": 0,
            }
        ),
    )
    return observations


def activate_reviewed_owner(pending, root, raw, sha, approval_raw):
    """The only transition from suspended review to the native original owner."""
    require(
        owner.read_packet(root / "review.json") == raw,
        "published qualification review changed",
    )
    review, approval = approved_review(raw, sha, approval_raw)
    observations = preactivation_probe(root, review)
    # Probe/file I/O consumes the original lease. It never renews approval time.
    review, approval = approved_review(raw, sha, approval_raw)
    require(
        all(
            0 <= time.monotonic_ns() - row["observed_mono_ns"] <= 5 * 10**9
            for row in observations.values()
        ),
        "preactivation observations stale before owner activation",
    )
    plan = json.loads(canonical(pending.proposal))
    plan["approval"]["native_stop"] = approval["reference"]
    owner.stop.write_once(
        root / "owner.activation.intent.json",
        canonical(
            {
                "review_sha256": sha,
                "stop_plan_sha256": digest(canonical(plan)),
                "observations": observations,
            }
        ),
    )
    pending.seal(canonical(plan), digest(canonical(plan)), approval["reference"])
    pending.ready()
    return review, approval


def measured_receipts(b, backup_raw, *, recovery=None):
    """Measure current stopped disk facts before issuing the short start window."""
    paths = start.backup.source_paths("guard")
    source = start.backup.source_paths("executor")["disk"]
    captures = Path(b["owner"]["root"]) / "preboot-observations"
    captures.mkdir(exist_ok=False)

    def capture(role, name):
        observer = session.NativeObserver(role)
        folder = captures / name
        folder.mkdir()
        try:
            return observer()
        finally:
            session.retain(folder, observer)

    frame = capture("guard", "guard-before")
    start.boot.stopped_snapshot(
        b,
        {k: frame[k] for k in ("observed_mono_ns", "machine", "medium")},
        recovery=recovery,
    )
    source_before = capture("executor", "source-before")
    require(
        start.host.machine_fields(source_before["machine"])["VMState"] == "poweroff"
        and source_before["session"]["state_before"]
        == source_before["session"]["state_after"]
        == "Unlocked",
        "preserved executor is not stopped before measurement",
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
    frame = capture("guard", "guard-after")
    start.boot.stopped_snapshot(
        b,
        {k: frame[k] for k in ("observed_mono_ns", "machine", "medium")},
        recovery=recovery,
    )
    source_frame = capture("executor", "source-after")
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
    if recovery is not None:
        preboot.update(
            format="mcli1-recovery-preboot-disk-v1",
            state="aborted",
            recovery_context_sha256=start.recovery_host.model.context_sha256(recovery),
        )
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


def controller_input(pending, review, review_sha, approval, *, measure=None):
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
    context = (
        start.recovery_host.live_context(start.host.object_bytes(inputs["recovery"]))
        if review.get("format") == RECOVERY_REVIEW_FORMAT
        else None
    )
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
        start.host.object_bytes(inputs["backup"]),
        digest(inputs["backup"]),
        recovery=context,
    )
    b["approval"] = {k: approval["reference"] for k in b["approval"]}
    if measure is not None:
        require(context is None, "prepared lock handoff is poweroff-only")
        preboot, preservation = measure(b, inputs["backup"])
    else:
        preboot, preservation = (
            measured_receipts(b, inputs["backup"], recovery=context)
            if context is not None
            else measured_receipts(b, inputs["backup"])
        )
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
    if context is not None:
        grant.update(format=start.RECOVERY_FORMAT, recovery=context)
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


def controller_main(root, external_sha, *, input_factory=None, review_checker=None):
    root = Path(root)
    raw = owner.read_packet(root / "controller.input.json")
    require(digest(raw) == external_sha, "qualification controller activation differs")
    payload = start.host.object_bytes(raw)
    review_raw = owner.read_packet(root.parent / "review.json")
    approval_raw = owner.read_packet(root.parent / "approval.json")
    review, _ = (review_checker or approved_review)(
        review_raw, payload["review_sha256"], approval_raw
    )
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
    runtime_recovery = payload["grant"].get("recovery")

    def capture(*, startup=False, session_only=False):
        folder = captures / str(len(sequence) + 1)
        folder.mkdir()
        sequence.append(folder.name)
        observer.last = None
        try:
            if session_only:
                return observer.startup_session()
            if startup and runtime_recovery is not None:
                return observer.startup_observation(recovery=runtime_recovery)
            return observer.startup_observation() if startup else observer()
        finally:
            session.retain(folder, observer)

    def stopped():
        frame = capture()
        return {k: frame[k] for k in ("observed_mono_ns", "machine", "medium")}

    with closing(Store(root / "owner.sqlite")) as store:
        store.db.execute("PRAGMA busy_timeout=50")
        adapter = (
            start._PreparedStart(store, stopped)
            if input_factory is None
            else start._PreparedStart(store, stopped, input_factory=input_factory)
        )
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
                if adapter.joined is None:
                    probe = capture(session_only=True)
                    progress = adapter.observe_startup_session(probe)
                    require(
                        time.monotonic_ns() - begin < POLICY["runtime_limit_ns"]
                        and time.time_ns() - wall < POLICY["runtime_limit_ns"],
                        "qualification runtime sample window ended during session probe",
                    )
                    if not progress["profile_observation_allowed"]:
                        time.sleep(0.1)
                        continue
                frame = capture(startup=adapter.joined is None)
                result = adapter.observe(frame)
                require(
                    time.monotonic_ns() - begin < POLICY["runtime_limit_ns"]
                    and time.time_ns() - wall < POLICY["runtime_limit_ns"],
                    "qualification runtime sample window ended during observation",
                )
                if result["status"] == "runtime-session-bound-not-guest-ready":
                    samples.append(
                        {
                            "observed_mono_ns": frame["observed_mono_ns"],
                            "session": frame["session"],
                            "members": adapter.family.members(),
                        }
                    )
                time.sleep(0.1)
            if is_controller_loss(review):
                _controller_loss_exit(root, payload["review_sha256"], adapter, samples)
                raise RuntimeError("abrupt controller exit unexpectedly returned")
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


def _controller_loss_exit(root, review_sha, adapter, samples):
    """Skip cleanup only after the explicitly reviewed two-sample fault barrier.

    Windows closes this controller's non-inheritable frontend job handle. The
    independent original owner survives; no replacement stop is supplied here.
    """
    with adapter.lock:
        members = adapter._live()
        require(
            len(samples) == POLICY["running_observations"]
            and adapter.joined in members
            and samples[0]["observed_mono_ns"] < samples[1]["observed_mono_ns"]
            and all(
                sample["session"]
                == {
                    "vm_uuid": target_uuid(),
                    "state_before": "Locked",
                    "state_after": "Locked",
                    "pid": adapter.joined["pid"],
                }
                and adapter.joined in sample["members"]
                for sample in samples
            ),
            "controller-loss barrier lacks two exact joined running samples",
        )
        require(
            not (root / "frontend.owner-stop.intent.json").exists(),
            "controller-loss fault cannot follow a normal stop request",
        )
        owner.publish(
            root / "controller.loss.intent.json",
            canonical(
                {
                    "format": "mcli1-joined-controller-loss-intent-v1",
                    "review_sha256": review_sha,
                    "grant_sha256": adapter.sha,
                    "original_lease": adapter.packet["lease"],
                    "issued_utc_ns": time.time_ns(),
                    "issued_mono_ns": time.monotonic_ns(),
                    "controller": start.host.process_identity(os.getpid()),
                    "members": members,
                    "samples": samples,
                    "exit_code": LOSS_EXIT,
                    "guest_commands": 0,
                    "normal_stop_requested": False,
                }
            ),
        )
        adapter._live()  # Evidence publication cannot renew the original clocks.
        os._exit(LOSS_EXIT)


def process_retired(record):
    """Prove this exact PID creation is gone; access denial is not a death proof."""
    return process_proof.retired(record)


def stop_proof(root, packet, outcome):
    """Independent bootstrap verification. Never issues or retries a VM command."""
    require(
        outcome["failure"] is None,
        "controller qualification held: " + str(outcome["failure"])[:256],
    )
    request = start.host.object_bytes(
        owner.read_packet(root / "frontend.owner-stop.intent.json")
    )
    deadline = request["issued_mono_ns"] + POLICY["stop_observation_limit_ns"]
    wall = request["issued_utc_ns"] + POLICY["stop_observation_limit_ns"]
    cleanup = outcome["retirement"]["cleanup"]
    retained = cleanup["retained_process_exits"]
    require(
        1 <= len(retained) <= start.frontend.FAMILY_LIMIT
        and len({row["pid"] for row in retained}) == len(retained)
        and any(row["pid"] == cleanup["root_pid"] for row in retained)
        and all(
            type(row["exit_code"]) is int
            and (
                Path(row["image"]).resolve() != start.frontend.HEADLESS
                or row["exit_code"] == 0
            )
            for row in retained
        ),
        "qualification retained family exit proof is incomplete or nonzero",
    )
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


def observe_owner_exit(root, pending):
    """Keep the bootstrap alive briefly for the retained owner's existing stop.

    This only observes its process handle; it sends no command or replacement
    signal and accepts no stop result. A live/unknown owner stays held.
    """
    if not getattr(pending, "sealed", False):
        return
    wall, mono = time.time_ns(), time.monotonic_ns()
    code = pending.child.poll()
    while (
        code is None
        and time.time_ns() - wall < POLICY["bootstrap_owner_exit_wait_ns"]
        and time.monotonic_ns() - mono < POLICY["bootstrap_owner_exit_wait_ns"]
    ):
        time.sleep(0.01)
        code = pending.child.poll()
    owner.publish(
        root / "bootstrap.owner-observation.json",
        canonical(
            {
                "status": "original-owner-process-observed-not-stop-acceptance",
                "process": pending.owner,
                "exit": code,
                "terminal_exists": (pending.root / "owner.terminal.json").exists(),
                "elapsed_ns": time.monotonic_ns() - mono,
                "original_stop_accepted": False,
            }
        ),
    )


def controller_loss_proof(root, review, pending, controller, job):
    """Observe the explicitly injected loss. Never accept it as normal shutdown."""
    require(
        is_controller_loss(review)
        and review["policy"]
        == review_policy(False, review["inputs"], controller_loss=True)
        and review["sources"] == SOURCE_EPOCH == current_sources(),
        "controller-loss review/source policy differs",
    )
    folder = pending.root
    intent = start.host.object_bytes(
        owner.read_packet(folder / "controller.loss.intent.json")
    )
    bound = start.host.object_bytes(
        owner.read_packet(folder / "frontend.session.receipt.json")
    )
    packet = start.host.object_bytes(owner.read_packet(folder / "owner.sealed.json"))
    require(
        intent["format"] == "mcli1-joined-controller-loss-intent-v1"
        and intent["review_sha256"] == digest(owner.read_packet(root / "review.json"))
        and intent["controller"] == review["controller"]
        and intent["original_lease"] == review["original_lease"]
        and packet["lease"] == review["original_lease"]
        and packet["controller"] == review["controller"]
        and packet["owner"] == review["owner"]
        and packet["owner_nonce"] == review["original_stop_proposal"]["owner_nonce"]
        and intent["exit_code"] == controller.poll() == LOSS_EXIT
        and intent["normal_stop_requested"] is False
        and len(intent["samples"]) == POLICY["running_observations"]
        and intent["samples"][0]["observed_mono_ns"]
        < intent["samples"][1]["observed_mono_ns"]
        and bound["process"] in intent["members"]
        and bound["grant_sha256"] == intent["grant_sha256"]
        and bound["original_lease"] == intent["original_lease"]
        and all(
            sample["session"]
            == {
                "vm_uuid": target_uuid(),
                "state_before": "Locked",
                "state_after": "Locked",
                "pid": bound["process"]["pid"],
            }
            and bound["process"] in sample["members"]
            for sample in intent["samples"]
        )
        and not (folder / "frontend.owner-stop.intent.json").exists()
        and not (folder / "controller.outcome.json").exists(),
        "controller did not exit at its reviewed joined-session barrier",
    )
    mono_end = intent["issued_mono_ns"] + POLICY["stop_observation_limit_ns"]
    wall_end = intent["issued_utc_ns"] + POLICY["stop_observation_limit_ns"]

    def within():
        require(
            time.monotonic_ns() < mono_end and time.time_ns() < wall_end,
            "controller-loss containment observation exceeded ten seconds",
        )

    within()
    while (
        job.active() or pending.child.poll() is None
    ) and time.monotonic_ns() < mono_end:
        within()
        time.sleep(0.02)
    within()
    require(job.active() == 0, "controller-loss outer job is not empty")
    require(pending.child.poll() in {0, 1}, "original owner exit is unknown")
    identities = [review["controller"], review["owner"], *intent["members"]]
    require(
        1 <= len(intent["members"]) <= start.frontend.FAMILY_LIMIT
        and len({row["pid"] for row in identities}) == len(identities)
        and all(process_retired(row) for row in identities),
        "controller/original-owner/frontend identity remains live or unknown",
    )
    with closing(
        sqlite3.connect(
            (folder / "owner.sqlite").resolve().as_uri() + "?mode=ro",
            uri=True,
            timeout=0.05,
        )
    ) as db:
        db.row_factory = sqlite3.Row
        lease = db.execute("SELECT * FROM lease").fetchone()
        native = db.execute("SELECT * FROM native_owner_stop").fetchall()
        authority = db.execute("SELECT active FROM authority").fetchone()
        joined = db.execute("SELECT * FROM frontend_start").fetchone()
        require(
            {k: lease[k] for k in start.host.OWNER_KEYS} == review["original_lease"]
            and authority[0] == 0
            and len(native) == 1
            and native[0]["plan_sha"] == packet["profile"]["bounded_stop"]["sha256"]
            and joined["state"] == "session-bound"
            and joined["grant_sha"] == intent["grant_sha256"]
            and joined["receipt_sha"]
            == digest(owner.read_packet(folder / "frontend.session.receipt.json")),
            "controller-loss durable fence/join/original stop evidence differs",
        )
        native = dict(native[0])
    stoproot = owner.stop.STOPS_ROOT / review["original_stop_proposal"]["owner_nonce"]
    result = start.host.object_bytes(
        owner.read_packet(stoproot / "process.result.json")
    )
    require(
        type(result["exit"]) is int
        and result["exit"] >= 0
        and result["pid"] == native["child_pid"]
        and result["job_active_processes"] == 0,
        "original stop process has no bounded known result",
    )
    command_acknowledged = native["state"] == "command-returned"
    if command_acknowledged:
        raw = owner.read_packet(stoproot / "command.receipt.json")
        receipt = start.host.object_bytes(raw)
        require(
            digest(raw) == native["receipt_sha"]
            and receipt["exit"] == result["exit"] == 0
            and receipt["job_active_processes"] == 0
            and receipt["child_pid"] == native["child_pid"]
            and receipt["plan_sha256"] == native["plan_sha"]
            and receipt["target_vm_uuid"] == target_uuid()
            and receipt["owner_nonce"]
            == review["original_stop_proposal"]["owner_nonce"],
            "original stop command acknowledgement differs",
        )
    else:
        require(
            native["state"] == "possible-send"
            and native["receipt_sha"] is None
            and result["exit"] != 0
            and not (stoproot / "command.receipt.json").exists(),
            "uncertain original stop must remain held without a replacement receipt",
        )
    observations = []
    for number in (1, 2):
        within()
        target = root / ("independent-loss-" + str(number))
        target.mkdir()
        observer = session.NativeObserver("guard")
        try:
            frame = observer()
            fields = start.host.machine_fields(frame["machine"])
            require(
                fields["VMState"] in {"poweroff", "aborted"}
                and frame["session"]
                == {
                    "vm_uuid": target_uuid(),
                    "state_before": "Unlocked",
                    "state_after": "Unlocked",
                    "pid": 0,
                },
                "controller-loss target is still active or unknown",
            )
            expected = start.boot.transfer.expected_host(
                {
                    "role": "guard",
                    "target": {"disk_uuid": start.backup.SLOTS["guard"]["disk_uuid"]},
                }
            )
            expected["state"] = fields["VMState"]
            require(
                start.host.machine_profile(frame["machine"]) == expected
                and all(fields.get(k) == v for k, v in start.boot.BOOT_FIELDS.items()),
                "controller-loss target profile changed",
            )
            observations.append(
                {
                    "state": fields["VMState"],
                    "observed_mono_ns": frame["observed_mono_ns"],
                    "machine_sha256": digest(frame["machine"]),
                    "medium_sha256": digest(frame["medium"]),
                }
            )
        finally:
            session.retain(target, observer)
    within()
    require(current_sources() == SOURCE_EPOCH, "controller-loss source cohort changed")
    return {
        "status": "joined-controller-loss-contained-original-stop-remains-held",
        "controller_loss_case_measured": True,
        "controller_exit": LOSS_EXIT,
        "original_stop_exit": result["exit"],
        "original_stop_command_acknowledged": command_acknowledged,
        "original_stop_accepted": False,
        "normal_start_session_stop_qualified": False,
        "native_settlement_qualified": False,
        "guest_ready": False,
        "startup_loss_late_detached_cases_qualified": False,
        "job_active_processes": 0,
        "identities_proven_retired": identities,
        "observations": observations,
        "containment_elapsed_ns": time.monotonic_ns() - intent["issued_mono_ns"],
        "note": "Abnormal family termination is containment evidence; neither Aborted nor a successful command alone meets normal-stop acceptance. No retry or reuse.",
    }


def prepare(output, *, recovery=False, capture_relative=None, controller_loss=False):
    require(not (recovery and controller_loss), "controller loss is poweroff-only")
    root = new_root(output)
    require(
        recovery or capture_relative is None,
        "ordinary review cannot select recovery inputs",
    )
    inputs = (
        fixed_inputs(recovery=True, capture_relative=capture_relative)
        if recovery
        else fixed_inputs()
    )
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
            "format": LOSS_REVIEW_FORMAT
            if controller_loss
            else RECOVERY_REVIEW_FORMAT
            if recovery
            else "mcli1-one-guard-startup-review-v1",
            "created_utc_ns": time.time_ns(),
            "policy": review_policy(recovery, inputs, controller_loss=controller_loss),
            "sources": dict(SOURCE_EPOCH),
            "inputs": inputs,
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
        if recovery:
            review["capture_relative"] = (
                start.recovery_host.CAPTURE_RELATIVE
                if capture_relative is None
                else capture_relative
            )
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
        review, approval = activate_reviewed_owner(
            pending, root, raw, digest(raw), owner.read_packet(root / "approval.json")
        )
        payload = controller_input(pending, review, digest(raw), approval)
        input_raw = canonical(payload)
        owner.publish(pending.root / "controller.input.json", input_raw)
        controller.resume(digest(input_raw).encode() + b"\n")
        end = time.monotonic() + 60
        while controller.poll() is None and time.monotonic() < end:
            time.sleep(0.05)
        require(
            controller.poll() == (LOSS_EXIT if controller_loss else 0),
            "qualification controller did not exit successfully; no replay",
        )
        packet = start.host.object_bytes(
            owner.read_packet(pending.root / "owner.sealed.json")
        )
        if controller_loss:
            terminal = controller_loss_proof(root, review, pending, controller, job)
        else:
            outcome = start.host.object_bytes(
                owner.read_packet(pending.root / "controller.outcome.json")
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
        unarmed = not (root / "owner.activation.intent.json").exists()
        terminal = {
            "status": "held-before-native-owner-activation"
            if unarmed
            else "held-startup-qualification-no-replay",
            "error": type(error).__name__ + ": " + str(error)[:256],
            "VM_boots": 0 if unarmed else "inspect-durable-start-intent",
            "native_stop_commands": 0 if unarmed else "inspect-original-stop-ledger",
            "native_settlement_qualified": False,
        }
        raise
    finally:
        job.close()  # Contains controller/family even if a result/query was lost.
        controller.close()
        if pending is not None:
            observe_owner_exit(root, pending)
            pending.close()  # A sealed owner retains its independent job/lease.
        owner.publish(root / "qualification.terminal.json", canonical(terminal))
        print(canonical(terminal).decode(), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=(
            "preview",
            "preflight",
            "prepare",
            "preflight-recovery",
            "prepare-recovery",
            "prepare-controller-loss",
        ),
        default="preview",
        nargs="?",
    )
    parser.add_argument("--output")
    parser.add_argument("--capture-root")
    args = parser.parse_args()
    require(
        args.capture_root is None
        or args.command in {"preflight-recovery", "prepare-recovery"},
        "capture root applies only to recovery review/preflight",
    )
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
    elif args.command in {"preflight", "preflight-recovery"}:
        require(
            args.output is not None, "read-only preflight needs a new output directory"
        )
        root = new_root(args.output)
        review = {
            "inputs": fixed_inputs(recovery=True, capture_relative=args.capture_root)
            if args.command == "preflight-recovery"
            else fixed_inputs(),
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
        }
        if args.command == "preflight-recovery":
            review["format"] = RECOVERY_REVIEW_FORMAT
            review["capture_relative"] = (
                start.recovery_host.CAPTURE_RELATIVE
                if args.capture_root is None
                else args.capture_root
            )
        owner.publish(
            root / "preflight.inputs.json",
            canonical(
                {
                    "review": review,
                    "sources": SOURCE_EPOCH,
                    "VM_boots": 0,
                    "native_stop_commands": 0,
                }
            ),
        )
        preactivation_probe(root, review)
        print(
            canonical(
                {
                    "status": "read-only-preactivation-check-reported",
                    "output": str(root),
                    "VM_boots": 0,
                    "native_stop_commands": 0,
                }
            ).decode()
        )
    else:
        require(
            args.output is not None,
            "qualification preparation needs a new output directory",
        )
        if args.command == "prepare-recovery":
            prepare(args.output, recovery=True, capture_relative=args.capture_root)
        elif args.command == "prepare-controller-loss":
            prepare(args.output, controller_loss=True)
        else:
            prepare(args.output)


if __name__ == "__main__":
    main()
