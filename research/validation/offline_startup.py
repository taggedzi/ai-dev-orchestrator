"""Inert guard review and one-use binding, authorized by decision 0006.

Preparing an artifact creates no process/job/lease and makes no native call.
Activation requires a distinct exact native approval; preparation approval is
never supplied as that approval. The original owner remains the only VM stop
issuer. This is fixture preparation, not product orchestration.
"""

import argparse
import hashlib
import json
import os
import sqlite3
import time
from contextlib import closing, contextmanager
from pathlib import Path
from uuid import uuid4

from . import startup_qualification as q
from .store import Hold
from .transfer_commands import canonical, digest
from .windows_readonly import require

ROOT = q.ROOT
DIRECTORY = ROOT / ".local/validation"
LEDGER = DIRECTORY / "offline-guard-admissions.sqlite"
REVIEW_FORMAT = "mcli1-offline-guard-review-v1"
APPROVAL_FORMAT = "mcli1-offline-guard-native-approval-v1"
PREP_LIMIT_NS = 600 * 10**9
CASES = {"normal", "controller-loss"}


def fixed_inputs():
    path = DIRECTORY / "stopped-refresh-03/preparation.receipt.json"
    return {
        **q.fixed_inputs(),
        "preservation": {
            "path": str(q.start.backup.safe(path)),
            "sha256": digest(path.read_bytes()),
        },
    }


def run_relative(review_id):
    return ".local/validation/offline-guard-run-" + review_id


def policy(case):
    require(case in CASES, "unknown offline guard case")
    return {
        **q.review_policy(False, {}, controller_loss=case == "controller-loss"),
        "unarmed_preparation_limit_ns": PREP_LIMIT_NS,
        "initial_state": "poweroff",
        "approval_before_process_allocation": True,
    }


def draft(case="normal"):
    review_id = uuid4().hex
    return {
        "format": REVIEW_FORMAT,
        "review_id": review_id,
        "created_utc_ns": time.time_ns(),
        "case": case,
        "policy": policy(case),
        "role": "guard",
        "target_vm_uuid": q.target_uuid(),
        "disk_uuid": q.start.backup.SLOTS["guard"]["disk_uuid"],
        "inputs": fixed_inputs(),
        "sources": dict(q.SOURCE_EPOCH),
        "native_argv": [
            str(q.start.frontend.HEADLESS),
            "--startvm",
            q.target_uuid(),
            "--vrde",
            "off",
        ],
        "native_executable_sha256": q.start.frontend.HEADLESS_SHA256,
        "environment_sha256": digest(
            canonical(q.start.frontend.frontend_environment())
        ),
        "activation_output_relative": run_relative(review_id),
        "writes_permitted": ["guard-disk", "guard-configuration", "guard-NVRAM"],
        "processes_allocated": 0,
        "leases_allocated": 0,
        "native_boot_authorized": False,
    }


def checked(raw, sha, *, current=True):
    require(type(raw) is bytes and digest(raw) == sha, "offline review digest differs")
    review = q.start.host.object_bytes(raw)
    expected = {
        "format",
        "review_id",
        "created_utc_ns",
        "case",
        "policy",
        "role",
        "target_vm_uuid",
        "disk_uuid",
        "inputs",
        "sources",
        "native_argv",
        "native_executable_sha256",
        "environment_sha256",
        "activation_output_relative",
        "writes_permitted",
        "processes_allocated",
        "leases_allocated",
        "native_boot_authorized",
    }
    require(
        set(review) == expected and review["format"] == REVIEW_FORMAT,
        "offline review fields/format differ",
    )
    ident = review["review_id"]
    require(
        type(ident) is str
        and len(ident) == 32
        and all(c in "0123456789abcdef" for c in ident),
        "offline review ID differs",
    )
    require(
        type(review["created_utc_ns"]) is int
        and 0 < review["created_utc_ns"] <= time.time_ns(),
        "offline review creation clock differs",
    )
    require(
        canonical(review["policy"]) == canonical(policy(review["case"]))
        and review["role"] == "guard"
        and review["target_vm_uuid"] == q.target_uuid()
        and review["disk_uuid"] == q.start.backup.SLOTS["guard"]["disk_uuid"]
        and review["activation_output_relative"] == run_relative(ident)
        and review["writes_permitted"]
        == ["guard-disk", "guard-configuration", "guard-NVRAM"]
        and type(review["processes_allocated"]) is int
        and review["processes_allocated"] == 0
        and type(review["leases_allocated"]) is int
        and review["leases_allocated"] == 0
        and review["native_boot_authorized"] is False,
        "offline review scope differs",
    )
    if current:
        require(
            review["sources"] == q.SOURCE_EPOCH == q.current_sources()
            and review["inputs"] == fixed_inputs(),
            "offline source/input cohort changed",
        )
        require(
            review["native_argv"]
            == [
                str(q.start.frontend.HEADLESS),
                "--startvm",
                q.target_uuid(),
                "--vrde",
                "off",
            ]
            and review["native_executable_sha256"] == q.start.frontend.HEADLESS_SHA256
            and review["environment_sha256"]
            == digest(canonical(q.start.frontend.frontend_environment())),
            "offline executable/environment policy differs",
        )
    return review


def approved(raw, sha, approval_raw):
    review = checked(raw, sha)
    approval = q.start.host.object_bytes(approval_raw)
    require(
        set(approval) == {"format", "review_sha256", "reference", "approved_utc_ns"}
        and approval["format"] == APPROVAL_FORMAT
        and approval["review_sha256"] == sha
        and type(approval["reference"]) is str
        and 0 < len(approval["reference"]) <= 256
        and type(approval["approved_utc_ns"]) is int
        and review["created_utc_ns"] <= approval["approved_utc_ns"] <= time.time_ns(),
        "exact offline native approval is unbound",
    )
    return review, approval


class Admissions:
    """One target reservation and one durable consumption per reviewed artifact."""

    def __init__(self, path=None, *, create=True):
        self.path = q.start.backup.safe(Path(LEDGER if path is None else path))
        self.db = sqlite3.connect(
            self.path if create else self.path.as_uri() + "?mode=rw",
            uri=not create,
            timeout=0.05,
            isolation_level=None,
        )
        self.db.row_factory = sqlite3.Row
        if create:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute(
                "CREATE TABLE IF NOT EXISTS admissions (review_id TEXT PRIMARY KEY, review_sha TEXT UNIQUE NOT NULL, approval_sha TEXT, target TEXT NOT NULL, output TEXT NOT NULL, state TEXT NOT NULL, revoked INTEGER NOT NULL, active INTEGER NOT NULL, binding_sha TEXT, input_sha TEXT)"
            )
            self.db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS one_active_guard ON admissions(target) WHERE active=1"
            )

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

    def row(self, ident):
        row = self.db.execute(
            "SELECT * FROM admissions WHERE review_id=?", (ident,)
        ).fetchone()
        require(row is not None, "offline admission is missing")
        return dict(row)

    def consume(self, review, sha, approval_sha):
        with self.transaction():
            require(
                self.db.execute(
                    "SELECT 1 FROM admissions WHERE review_id=? OR review_sha=?",
                    (review["review_id"], sha),
                ).fetchone()
                is None,
                "offline admission already consumed or revoked; no replay",
            )
            self.db.execute(
                "INSERT INTO admissions VALUES(?,?,?,?,?,'consumed',0,1,NULL,NULL)",
                (
                    review["review_id"],
                    sha,
                    approval_sha,
                    q.target_uuid(),
                    review["activation_output_relative"],
                ),
            )

    def live(self, review, sha, approval_sha):
        row = self.row(review["review_id"])
        require(
            row["review_sha"] == sha
            and row["approval_sha"] == approval_sha
            and row["target"] == q.target_uuid()
            and row["output"] == review["activation_output_relative"]
            and row["revoked"] == 0
            and row["active"] == 1
            and row["state"] in {"consumed", "constructed", "armed"},
            "offline admission is revoked, settled or changed",
        )
        return row

    def revoke(self, review, sha):
        with self.transaction():
            row = self.db.execute(
                "SELECT * FROM admissions WHERE review_id=?", (review["review_id"],)
            ).fetchone()
            if row is None:
                self.db.execute(
                    "INSERT INTO admissions VALUES(?,?,NULL,?,?,'revoked',1,0,NULL,NULL)",
                    (
                        review["review_id"],
                        sha,
                        q.target_uuid(),
                        review["activation_output_relative"],
                    ),
                )
            else:
                require(row["review_sha"] == sha, "revocation review changed")
                self.db.execute(
                    "UPDATE admissions SET revoked=1 WHERE review_id=?",
                    (review["review_id"],),
                )

    def _table(self, name):
        return (
            self.db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (name,),
            ).fetchone()
            is not None
        )

    def inherited_hold(self, ident):
        """True when this admission received a held ancestor's target exclusion."""
        if not self._table("continuations"):
            return False
        return (
            self.db.execute(
                "SELECT 1 FROM continuations WHERE successor_id=?",
                (ident,),
            ).fetchone()
            is not None
        )

    def ancestor_hold(self, ident):
        if not self._table("continuations"):
            return False
        return (
            self.db.execute(
                "SELECT 1 FROM continuations WHERE prior_id=?",
                (ident,),
            ).fetchone()
            is not None
        )

    def independent_stop_accepted(self, ident):
        if not self._table("successor_stops"):
            return False
        row = self.db.execute(
            "SELECT accepted FROM successor_stops WHERE successor_id=?",
            (ident,),
        ).fetchone()
        return row is not None and row["accepted"] == 1

    def finish(self, ident, *, settled, release_unarmed=False):
        successor = False
        proved = False
        with self.transaction():
            if self.ancestor_hold(ident):
                raise Hold("held ancestor cannot be settled")
            successor = self.inherited_hold(ident)
            if successor:
                # A caller-supplied settled flag cannot discard inherited exclusion.
                row = self.db.execute(
                    "SELECT revoked FROM admissions WHERE review_id=?",
                    (ident,),
                ).fetchone()
                require(row is not None, "successor admission is missing")
                proved = (
                    bool(settled)
                    and row["revoked"] == 0
                    and self.independent_stop_accepted(ident)
                )
                self.db.execute(
                    "UPDATE admissions SET state=?,active=? WHERE review_id=?",
                    (
                        "finished" if proved else "held",
                        0 if proved else 1,
                        ident,
                    ),
                )
            else:
                self.db.execute(
                    "UPDATE admissions SET state=?,active=? WHERE review_id=?",
                    (
                        "finished" if settled else "held",
                        0 if settled or release_unarmed else 1,
                        ident,
                    ),
                )
        if successor and settled and not proved:
            raise Hold("successor release requires independent stop proof")

    def constructed(self, review, sha, approval_sha, binding_sha):
        with self.transaction():
            row = self.live(review, sha, approval_sha)
            require(
                row["state"] == "consumed", "offline process binding already attempted"
            )
            self.db.execute(
                "UPDATE admissions SET state='constructed',binding_sha=? WHERE review_id=?",
                (binding_sha, review["review_id"]),
            )

    @contextmanager
    def arm(self, review, sha, approval_sha):
        # Revocation and the one owner activation have a single database order.
        # A lost COMMIT acknowledgement still leaves the artifact consumed.
        with self.transaction():
            row = self.live(review, sha, approval_sha)
            require(
                row["state"] == "constructed",
                "offline owner activation already attempted",
            )
            yield

    def input_ready(self, ident, input_sha):
        require(self.db.in_transaction, "offline arm transaction is missing")
        self.db.execute(
            "UPDATE admissions SET state='armed',input_sha=? WHERE review_id=?",
            (input_sha, ident),
        )


def prepare(output, *, case="normal"):
    review = draft(case)
    root = q.new_root(output)
    raw = canonical(review)
    q.owner.publish(root / "review.json", raw)
    return {
        "status": "inert-guard-review-ready",
        "path": str(root / "review.json"),
        "sha256": digest(raw),
        "case": case,
        "native_calls": 0,
        "processes_allocated": 0,
        "leases_allocated": 0,
    }


def input_bytes(review):
    values = {
        name: Path(row["path"]).read_bytes() for name, row in review["inputs"].items()
    }
    require(
        all(
            digest(raw) == review["inputs"][name]["sha256"]
            for name, raw in values.items()
        ),
        "offline input bytes changed",
    )
    return values


def preflight(raw, sha, output):
    """Read-only current-file/profile proof; never consumes native approval."""
    review = checked(raw, sha)
    root = q.new_root(output)
    q.owner.publish(root / "review.json", raw)
    wall, mono = time.time_ns() + PREP_LIMIT_NS, time.monotonic_ns() + PREP_LIMIT_NS
    before = root / "before"
    before.mkdir()
    q.preactivation_probe(before, review)
    with closing(PreparedInputs(review)) as inputs:
        require(
            time.time_ns() < wall and time.monotonic_ns() < mono,
            "offline read-only preparation budget ended",
        )
        after = root / "after"
        after.mkdir()
        q.preactivation_probe(after, review)
        checked(raw, sha)
        report = inputs.ready()
        report["process"] = report.pop("controller")
        report.update(
            format="mcli1-offline-readonly-preflight-v1",
            status="offline-readonly-preflight-not-native-authority",
        )
        q.owner.publish(root / "receipt.json", canonical(report))
    return {
        "status": report["status"],
        "output": str(root),
        "VM_boots": 0,
        "leases_allocated": 0,
        "native_boot_authorized": False,
    }


class PreparedInputs(q.start._InputLocks):
    """Hash while unarmed; keep the same handles through the final resume gate."""

    def __init__(self, review):
        self.review, self.values, self.used = review, input_bytes(review), False
        self.profile = q.start.host.object_bytes(self.values["profile"])
        binding = q.start.backup.records.binding(
            q.start.host.object_bytes(self.values["backup"]),
            digest(self.values["backup"]),
        )
        self.binding = binding
        super().__init__(
            {"boot": {"role": "guard", "backup": binding}},
            self.values["backup"],
            self.profile,
        )
        try:
            receipt = q.start.host.object_bytes(self.values["backup"])
            for row in receipt["files"].values():
                if row["state"] == "file":
                    self.hold(
                        q.start.backup.safe(ROOT / row["backup_relative"]),
                        {k: row[k] for k in ("state", "bytes", "sha256")},
                    )
            preservation = q.start.host.object_bytes(self.values["preservation"])[
                "preserved_executor_files"
            ]
            for name in ("configuration", "nvram"):
                self.hold(
                    q.start.backup.source_paths("executor")[name], preservation[name]
                )
            require(
                preservation["disk"]["sha256"] == q.start.host.SOURCE_DISK_SHA,
                "preserved source pin differs",
            )
            self.check()
        except BaseException:
            self.close()
            raise

    def ready(self):
        self.check()
        return {
            "format": "mcli1-unarmed-locked-inputs-v1",
            "review_sha256": digest(canonical(self.review)),
            "controller": q.start.host.process_identity(os.getpid()),
            "sources": dict(q.SOURCE_EPOCH),
            "disk_sha256": self.profile["disk_sha256"],
            "source_disk_sha256": q.start.host.SOURCE_DISK_SHA,
            "files": [
                {
                    "path": path.relative_to(ROOT).as_posix(),
                    "identity": identity,
                    "bytes": size,
                }
                for path, _stream, identity, size in self.files
            ],
            "prepared_utc_ns": time.time_ns(),
            "prepared_mono_ns": time.monotonic_ns(),
            "VM_boots": 0,
            "leases_allocated": 0,
        }

    def use(self, grant, backup_raw, profile):
        require(
            not self.used
            and grant.get("recovery") is None
            and grant["boot"]["role"] == "guard"
            and grant["boot"]["backup"] == self.binding
            and backup_raw == self.values["backup"]
            and profile == self.profile,
            "prepared input lock handoff differs or was already used",
        )
        self.check()
        self.used = True
        return self


def check_prepared(review, ready, controller):
    values = input_bytes(review)
    profile = q.start.host.object_bytes(values["profile"])
    require(
        ready["format"] == "mcli1-unarmed-locked-inputs-v1"
        and ready["review_sha256"] == digest(canonical(review))
        and ready["controller"] == q.start.host.process_identity(controller.pid)
        and ready["sources"] == q.SOURCE_EPOCH
        and ready["disk_sha256"] == profile["disk_sha256"]
        and ready["source_disk_sha256"] == q.start.host.SOURCE_DISK_SHA
        and ready["VM_boots"] == ready["leases_allocated"] == 0
        and 4 <= len(ready["files"]) <= 12,
        "unarmed lock preparation differs",
    )
    expected = {
        path.relative_to(ROOT).as_posix()
        for path in q.start.backup.source_paths("guard").values()
        if path.exists()
    }
    expected |= {
        path.relative_to(ROOT).as_posix()
        for path in q.start.backup.source_paths("executor").values()
    }
    expected |= {
        row["backup_relative"]
        for row in q.start.host.object_bytes(values["backup"])["files"].values()
        if row["state"] == "file"
    }
    require(
        {row["path"] for row in ready["files"]} == expected
        and len(expected) == len(ready["files"]),
        "prepared locked file inventory differs",
    )
    for row in ready["files"]:
        path = q.start.backup.safe(ROOT / row["path"])
        info = path.stat()
        require(
            q.start.backup.file_identity(info) == row["identity"]
            and info.st_size == row["bytes"],
            "prepared locked file identity changed",
        )


def prepared_receipts(b, backup_raw, ready):
    preboot = {
        "format": "mcli1-preboot-disk-v1",
        "run_nonce": b["run_nonce"],
        "target_vm_uuid": b["target"]["vm_uuid"],
        "disk_uuid": b["target"]["disk_uuid"],
        "disk_sha256": ready["disk_sha256"],
        "state": "poweroff",
        "backup_receipt_sha256": digest(backup_raw),
    }
    preservation = {
        "format": "mcli1-source-preservation-v1",
        "run_nonce": b["run_nonce"],
        "target_vm_uuid": b["target"]["vm_uuid"],
        "source_disk_uuid": q.start.boot.transfer.EXECUTOR_DISK,
        "before_sha256": ready["source_disk_sha256"],
        "after_sha256": ready["source_disk_sha256"],
        "state": "poweroff",
    }
    b["disk_evidence"] = {
        "pre_boot_disk_sha256": ready["disk_sha256"],
        "pre_boot_receipt_sha256": digest(canonical(preboot)),
        "source_preservation_receipt_sha256": digest(canonical(preservation)),
    }
    return preboot, preservation


def binding_for(review, sha, approval_sha, pending):
    lease = pending.lease
    for armed, expires, now in (
        ("armed_ns", "expires_ns", time.time_ns()),
        ("armed_mono_ns", "expires_mono_ns", time.monotonic_ns()),
    ):
        require(
            type(lease[armed]) is int
            and type(lease[expires]) is int
            and 0 < lease[expires] - lease[armed] <= q.POLICY["original_lease_ns"]
            and lease[armed] <= now < lease[expires] - q.start.RESERVE_NS,
            "offline original lease is expired or expanded before arming",
        )
    require(lease["target"] == q.target_uuid(), "offline lease target differs")
    return {
        "format": q.BOUND_REVIEW_FORMAT,
        "review_id": review["review_id"],
        "static_review_sha256": sha,
        "static_approval_sha256": approval_sha,
        "case": review["case"],
        "policy": q.review_policy(
            False, review["inputs"], controller_loss=review["case"] == "controller-loss"
        ),
        "sources": dict(q.SOURCE_EPOCH),
        "inputs": review["inputs"],
        "activation_output_relative": review["activation_output_relative"],
        "native_argv": review["native_argv"],
        "native_executable_sha256": review["native_executable_sha256"],
        "environment_sha256": review["environment_sha256"],
        "original_lease": pending.lease,
        "original_stop_proposal": pending.proposal,
        "controller": pending.controller,
        "bootstrap": pending.bootstrap,
        "owner": pending.owner,
        "native_boot_authorized": False,
    }


def checked_binding(raw, sha, approval_raw):
    require(
        type(raw) is bytes and digest(raw) == sha,
        "offline runtime binding digest differs",
    )
    bound = q.start.host.object_bytes(raw)
    require(
        bound["format"] == q.BOUND_REVIEW_FORMAT,
        "offline runtime binding format differs",
    )
    root = q.start.backup.safe(ROOT / run_relative(bound["review_id"]))
    static_raw = q.owner.read_packet(root / "static.review.json")
    review, approval = approved(static_raw, bound["static_review_sha256"], approval_raw)
    require(
        bound["review_id"] == review["review_id"]
        and bound["static_approval_sha256"] == digest(approval_raw)
        and bound["case"] == review["case"]
        and bound["sources"] == review["sources"]
        and bound["inputs"] == review["inputs"]
        and bound["activation_output_relative"] == review["activation_output_relative"]
        and bound["policy"]
        == q.review_policy(
            False, review["inputs"], controller_loss=review["case"] == "controller-loss"
        )
        and all(
            bound[key] == review[key]
            for key in ("native_argv", "native_executable_sha256", "environment_sha256")
        )
        and bound["native_boot_authorized"] is False,
        "offline runtime/static approval binding changed",
    )
    with closing(Admissions(create=False)) as admissions:
        row = admissions.live(review, digest(static_raw), digest(approval_raw))
        require(
            row["state"] == "armed"
            and row["binding_sha"] == sha
            and row["input_sha"] is not None,
            "offline runtime is not the one armed binding",
        )
    lease = bound["original_lease"]
    for armed, expires, now in (
        ("armed_ns", "expires_ns", time.time_ns()),
        ("armed_mono_ns", "expires_mono_ns", time.monotonic_ns()),
    ):
        require(
            type(lease[armed]) is int
            and type(lease[expires]) is int
            and 0 < lease[expires] - lease[armed] <= q.POLICY["original_lease_ns"]
            and lease[armed] <= now < lease[expires] - q.start.RESERVE_NS,
            "offline original lease is expired or expanded",
        )
    require(
        lease["target"] == q.target_uuid()
        and bound["original_stop_proposal"]["lease"] == lease,
        "offline original stop lease differs",
    )
    require(
        bound["controller"] == q.start.host.process_identity(os.getpid())
        and all(
            q.start.host.process_identity(bound[role]["pid"]) == bound[role]
            for role in ("owner", "bootstrap")
        ),
        "offline runtime process binding differs",
    )
    return bound, approval


def worker_main(root, static_sha):
    """One Python worker hashes/holds inputs before any original owner exists."""
    root = Path(root)
    raw = q.owner.read_packet(root / "static.review.json")
    approval_raw = q.owner.read_packet(root / "approval.json")
    review, _ = approved(raw, static_sha, approval_raw)
    deadline, wall_end = (
        time.monotonic_ns() + PREP_LIMIT_NS,
        time.time_ns() + PREP_LIMIT_NS,
    )
    with closing(Admissions(create=False)) as admissions:
        admissions.live(review, static_sha, digest(approval_raw))
        with closing(PreparedInputs(review)) as inputs:
            require(
                time.monotonic_ns() < deadline and time.time_ns() < wall_end,
                "unarmed input hashing exceeded preparation budget",
            )
            q.owner.publish(root / "preparation.ready.json", canonical(inputs.ready()))
            while time.monotonic_ns() < deadline and time.time_ns() < wall_end:
                require(
                    q.current_sources() == q.SOURCE_EPOCH,
                    "unarmed worker source changed",
                )
                row = admissions.live(review, static_sha, digest(approval_raw))
                inputs.check()
                if row["state"] == "armed":
                    payload_raw = q.owner.read_packet(
                        root / "owner/controller.input.json"
                    )
                    require(
                        digest(payload_raw) == row["input_sha"],
                        "offline activation input differs",
                    )
                    q.controller_main(
                        root / "owner",
                        row["input_sha"],
                        input_factory=inputs.use,
                        review_checker=checked_binding,
                    )
                    return
                time.sleep(0.05)
            raise Hold("unarmed lock preparation window ended")


class NativeRuntime:
    """Concrete process boundary; tests substitute Python-only factories here."""

    @staticmethod
    def job(ident):
        return q.start.frontend.ControllerJob("Local\\MCLI1Controller-" + ident)

    @staticmethod
    def controller(root, sha, job):
        code = f"import sys;sys.path.insert(0,{str(ROOT)!r});from research.validation.offline_startup import worker_main;worker_main({str(root)!r},sys.stdin.buffer.read(65).strip().decode('ascii'))"
        return q.launch.SuspendedChild(["-I", "-B", "-c", code], job)

    @staticmethod
    def owner(root, ident, controller):
        return q.launch.PendingOwner(
            root / "owner",
            "guard",
            ident,
            q.start.host.process_identity(controller.pid),
            time.time_ns() + q.POLICY["original_lease_ns"],
            "decision-0006:approved-inert-artifact;one-use-binder",
        )


def activate(raw, sha, approval_raw, *, runtime=None):
    review, approval = approved(raw, sha, approval_raw)
    approval_sha = digest(approval_raw)
    runtime = NativeRuntime() if runtime is None else runtime
    with closing(Admissions()) as admissions:
        admissions.consume(review, sha, approval_sha)
        root = q.start.backup.safe(ROOT / review["activation_output_relative"])
        controller = pending = job = None
        created = False
        controller_record = owner_record = None
        settled = False
        result = {
            "status": "held-offline-admission-no-replay",
            "native_settlement_qualified": False,
        }
        try:
            root = q.new_root(root)
            created = True
            q.owner.publish(root / "static.review.json", raw)
            q.owner.publish(root / "approval.json", approval_raw)
            preflight = root / "unarmed-preflight"
            preflight.mkdir()
            q.preactivation_probe(preflight, review)
            admissions.live(review, sha, approval_sha)
            approved(raw, sha, approval_raw)
            job = runtime.job(review["review_id"])
            controller = runtime.controller(root, sha, job)
            controller_record = q.start.host.process_identity(controller.pid)
            q.owner.publish(
                root / "preparation.worker.intent.json",
                canonical(
                    {
                        "review_sha256": sha,
                        "controller": q.start.host.process_identity(controller.pid),
                        "VM_boots": 0,
                        "leases_allocated": 0,
                    }
                ),
            )
            controller.resume(sha.encode() + b"\n")
            deadline, wall_end = (
                time.monotonic_ns() + PREP_LIMIT_NS,
                time.time_ns() + PREP_LIMIT_NS,
            )
            while not (root / "preparation.ready.json").exists():
                require(
                    time.monotonic_ns() < deadline
                    and time.time_ns() < wall_end
                    and controller.poll() is None,
                    "unarmed preparation did not return; no replay",
                )
                admissions.live(review, sha, approval_sha)
                require(q.current_sources() == q.SOURCE_EPOCH, "unarmed source changed")
                time.sleep(0.05)
            ready = q.start.host.object_bytes(
                q.owner.read_packet(root / "preparation.ready.json")
            )
            require(
                time.monotonic_ns() < deadline
                and time.time_ns() < wall_end
                and controller.poll() is None,
                "unarmed ready proof is late or retired",
            )
            check_prepared(review, ready, controller)
            final = root / "final-unarmed-preflight"
            final.mkdir()
            q.preactivation_probe(final, review)
            admissions.live(review, sha, approval_sha)
            approved(raw, sha, approval_raw)
            pending = runtime.owner(root, review["review_id"], controller)
            owner_record = dict(pending.owner)
            bound = binding_for(review, sha, approval_sha, pending)
            bound_raw = canonical(bound)
            q.owner.publish(root / "review.json", bound_raw)
            admissions.constructed(review, sha, approval_sha, digest(bound_raw))
            with admissions.arm(review, sha, approval_sha):
                approved(raw, sha, approval_raw)
                check_prepared(review, ready, controller)
                plan = json.loads(canonical(pending.proposal))
                plan["approval"]["native_stop"] = approval["reference"]
                q.owner.publish(
                    root / "owner.activation.intent.json",
                    canonical(
                        {
                            "static_review_sha256": sha,
                            "binding_sha256": digest(bound_raw),
                            "stop_plan_sha256": digest(canonical(plan)),
                        }
                    ),
                )
                pending.seal(
                    canonical(plan), digest(canonical(plan)), approval["reference"]
                )
                pending.ready()
                payload = q.controller_input(
                    pending,
                    bound,
                    digest(bound_raw),
                    approval,
                    measure=lambda b, backup_raw: prepared_receipts(
                        b, backup_raw, ready
                    ),
                )
                payload_raw = canonical(payload)
                q.owner.publish(pending.root / "controller.input.json", payload_raw)
                admissions.input_ready(review["review_id"], digest(payload_raw))
            end = time.monotonic() + 60
            while controller.poll() is None and time.monotonic() < end:
                admissions.live(review, sha, approval_sha)
                time.sleep(0.05)
            require(
                controller.poll()
                == (q.LOSS_EXIT if review["case"] == "controller-loss" else 0),
                "offline controller did not finish its one case; no replay",
            )
            if review["case"] == "controller-loss":
                result = q.controller_loss_proof(root, bound, pending, controller, job)
            else:
                outcome = q.start.host.object_bytes(
                    q.owner.read_packet(pending.root / "controller.outcome.json")
                )
                packet = q.start.host.object_bytes(
                    q.owner.read_packet(pending.root / "owner.sealed.json")
                )
                result = q.stop_proof(pending.root, packet, outcome)
            with q.start.backup.locked_source(
                q.start.backup.source_paths("executor")["disk"]
            ) as stream:
                require(
                    hashlib.file_digest(stream, "sha256").hexdigest()
                    == q.start.host.SOURCE_DISK_SHA,
                    "offline run changed preserved executor disk",
                )
            result.update(VM_boots=1, source_disk_preserved=True)
            settled = review["case"] == "normal"
            return result
        except BaseException as error:
            result["error"] = type(error).__name__ + ": " + str(error)[:256]
            result["VM_boots"] = (
                0
                if not (root / "owner.activation.intent.json").exists()
                else "inspect-durable-start-intent"
            )
            raise
        finally:
            # Physical containment precedes reporting or repairing the admission DB.
            errors = []

            def cleanup(action):
                try:
                    action()
                except BaseException as error:  # noqa: BLE001 -- finish containment before reporting cancellation/failure
                    errors.append(type(error).__name__ + ": " + str(error)[:256])

            if job is not None:
                cleanup(job.close)
            if controller is not None:
                end = time.monotonic() + 2
                while controller.poll() is None and time.monotonic() < end:
                    time.sleep(0.01)
                if controller.poll() is None:
                    errors.append("controller retirement is unknown")
                cleanup(controller.close)
            if pending is not None:
                cleanup(lambda: q.observe_owner_exit(root, pending))
                cleanup(pending.close)
            retired = True
            for record in (controller_record, owner_record):
                if record is not None:
                    try:
                        retired = q.process_retired(record) and retired
                    except BaseException as error:  # noqa: BLE001 -- unknown retirement must hold, never skip remaining cleanup
                        retired = False
                        errors.append(type(error).__name__ + ": " + str(error)[:256])
            settled = settled and retired and not errors
            unarmed = (
                created
                and not (root / "owner.activation.intent.json").exists()
                and not (root / "owner/owner.sealed.json").exists()
            )
            inherited = False
            try:
                inherited = admissions.inherited_hold(review["review_id"])
            except BaseException as error:  # noqa: BLE001 -- unknown inheritance must keep exclusion
                inherited = True
                errors.append(type(error).__name__ + ": " + str(error)[:256])
            release_unarmed = (
                unarmed
                and retired
                and not errors
                and (owner_record is not None or not (root / "owner").exists())
                and not inherited
            )
            if errors:
                result.update(
                    status="held-offline-cleanup-unknown",
                    cleanup_errors=errors,
                    native_settlement_qualified=False,
                )
            try:
                admissions.finish(
                    review["review_id"],
                    settled=settled,
                    release_unarmed=release_unarmed,
                )
            except BaseException as error:  # noqa: BLE001 -- preserve the held result after physical containment
                result.update(
                    status="held-offline-admission-settlement-unknown",
                    admission_error=type(error).__name__ + ": " + str(error)[:256],
                    native_settlement_qualified=False,
                )
                errors.append(result["admission_error"])
            if created:
                q.owner.publish(root / "qualification.terminal.json", canonical(result))
            require(
                not errors, "offline cleanup/admission settlement is unknown; no replay"
            )


def revoke(raw, sha):
    review = checked(raw, sha, current=False)
    with closing(Admissions()) as admissions:
        admissions.revoke(review, sha)
    root = q.start.backup.safe(ROOT / review["activation_output_relative"])
    store_path = root / "owner/owner.sqlite"
    if store_path.exists():
        with closing(q.Store(store_path)) as store:
            store.fence("offline native approval revoked")
    return {
        "status": "offline-revocation-recorded-stop-proof-still-required",
        "review_sha256": sha,
        "native_commands": 0,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=("prepare", "preflight", "activate", "revoke"),
        default="prepare",
        nargs="?",
    )
    parser.add_argument("--case", choices=sorted(CASES), default="normal")
    parser.add_argument("--output")
    parser.add_argument("--review")
    parser.add_argument("--sha256")
    parser.add_argument("--approval")
    args = parser.parse_args()
    if args.command == "prepare":
        require(
            args.output is not None
            and args.review is None
            and args.approval is None
            and args.sha256 is None,
            "inert preparation needs only a new output and case",
        )
        result = prepare(args.output, case=args.case)
    elif args.command == "preflight":
        require(
            args.review is not None
            and args.sha256 is not None
            and args.output is not None
            and args.approval is None,
            "read-only preflight needs review/hash/new output without approval",
        )
        result = preflight(
            q.owner.read_packet(q.start.backup.safe(Path(args.review))),
            args.sha256,
            args.output,
        )
    else:
        require(
            args.review is not None and args.sha256 is not None and args.output is None,
            "offline action needs exact review/hash and no alternate output",
        )
        raw = q.owner.read_packet(q.start.backup.safe(Path(args.review)))
        if args.command == "revoke":
            require(
                args.approval is None, "revocation cannot grant activation approval"
            )
            result = revoke(raw, args.sha256)
        else:
            require(
                args.approval is not None,
                "activation needs a separate exact native approval",
            )
            result = activate(
                raw,
                args.sha256,
                q.owner.read_packet(q.start.backup.safe(Path(args.approval))),
            )
    print(canonical(result).decode())


if __name__ == "__main__":
    main()
