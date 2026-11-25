"""Decision 0007 preparation: held-guard successor provenance and scratch transfer.

This module does not boot a VM, attach a disk, or modify the production
admission ledger or the original owner journal. Scratch ledgers, Python
surrogates, read-only inventory and unattached copies are the whole scope.
Aborted is never recorded as a successful stop.
"""

import argparse
import ctypes
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from contextlib import closing, contextmanager
from ctypes import wintypes
from pathlib import Path
from uuid import uuid4

from . import boot_preconditions as boot
from . import maintenance_host as host
from . import native_session as session
from . import offline_startup as offline
from . import process_proof
from . import stopped_backup as backup
from .frontend_process import ControllerJob
from .offline_repo import new_root
from .owner_launch import SuspendedChild
from .store import Hold
from .transfer_commands import canonical, digest
from .windows_readonly import require

ROOT = backup.ROOT
GUARD_VM = "0eceb37e-f216-45ed-817c-7cf2fca3a32a"
GUARD_DISK = "a8f47315-d330-4b28-bbb0-6a721b4c6251"
PRODUCTION_LEDGER = ROOT / ".local/validation/offline-guard-admissions.sqlite"
PRODUCTION_OWNER = (
    ROOT
    / ".local/validation/offline-guard-run-ccc16a8440524bda84e57fdcd90055e7/owner/owner.sqlite"
)
PRODUCTION_LEDGER_SHA256 = (
    "f1eac66681934fd294c73efeb580ebc102b64e6586a17a13bdd7a1bec488260a"
)
PRODUCTION_OWNER_SHA256 = (
    "24bab655c096ee1fa16b4f4bed2d04a76a167eee93de7e0fd21c54cefade0313"
)
RUN_ROOT = ROOT / ".local/validation/offline-guard-run-ccc16a8440524bda84e57fdcd90055e7"
CONTEXT_FORMAT = "mcli1-held-guard-successor-context-v1"
PROFILE_FORMAT = "mcli1-held-guard-successor-profile-v1"
REVIEW_FORMAT = "mcli1-held-guard-successor-review-v1"
BACKUP_FORMAT = "mcli1-held-guard-successor-backup-v1"
CASE = "normal-guard-recovery-startup-session-stop"
MAX_LEASE_NS = 600 * 10**9
ADMISSION_KEYS = (
    "review_id",
    "review_sha",
    "approval_sha",
    "target",
    "output",
    "state",
    "revoked",
    "active",
    "binding_sha",
    "input_sha",
    "stop_receipt_sha",
)
HELD_ADMISSION = {
    "review_id": "ccc16a8440524bda84e57fdcd90055e7",
    "review_sha": "0925de6acf1a400301d84abf1177a0596f811ff142597e3e74ddc52c4f13a788",
    "approval_sha": "e9e355b6301b400c33f99af51e65fd0ff07356d660e0eafd2b6d6d94399b52d0",
    "target": GUARD_VM,
    "output": ".local/validation/offline-guard-run-ccc16a8440524bda84e57fdcd90055e7",
    "state": "held",
    "revoked": 0,
    "active": 1,
    "binding_sha": "280de430cee4d69e60c76cc44022c180b52c71fa7fcf843fef0def3526c85dca",
    "input_sha": "a094f8400f27df4ef3aba0c9738e0eeeef2fff43cced68eb1b57be94d28435e7",
    "stop_receipt_sha": None,
}
HISTORY = {
    "format": "mcli1-held-guard-successor-history-v1",
    "review_10_sha256": "027b509dfcbe0d710f5bdf0a63334b0668a351b6dd0e3907f8caf79e4996967b",
    "review_10_root": ".local/validation/guard-startup-review-10",
    "review_10_context_sha256": (
        "623e3701fab0d58601a21108291bc840a15da8a8b281dde8371917cc39781908"
    ),
    "review_10_capture": ".local/validation/initial-aborted-capture-06",
    "review_10_stop_receipt_sha256": (
        "5207498bf87b04045bab833420e8d32e1c431a3ff52fd002289ac7c096b3c29c"
    ),
    "review_10_stop_inventory_sha256": (
        "680cb440664422ee2d9ad1dac04096c671cbb93770d88277f3643cec18eafd74"
    ),
    "claims_about_failed_stop": False,
}
FILES = {
    "disk": {
        "state": "file",
        "bytes": 2625634304,
        "sha256": "a8a6024499644999738f089546096e93174a336c003f2d1ae841214c2fe22c43",
    },
    "configuration": {
        "state": "file",
        "bytes": 2373,
        "sha256": "6388740c34b3ce72b8d66f384a66c82d36fe9b8385a519998b7083ab07e29046",
    },
    "nvram": {
        "state": "file",
        "bytes": 540672,
        "sha256": "ec2dca0346cd722d9e47a263353fa97b71b3de1914d7f5084b87eec1c9b4a49c",
    },
}
EXECUTOR_FILES = {
    "disk": {
        "state": "file",
        "bytes": 2625634304,
        "sha256": "2eb1d9cd009ecfe83381d855137f5cee8c1317739f6209beddd6da8a10955a09",
    },
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
FAULT_PINS = {
    "static_review": (
        "static.review.json",
        "0925de6acf1a400301d84abf1177a0596f811ff142597e3e74ddc52c4f13a788",
    ),
    "approval": (
        "approval.json",
        "e9e355b6301b400c33f99af51e65fd0ff07356d660e0eafd2b6d6d94399b52d0",
    ),
    "runtime_binding": (
        "review.json",
        "280de430cee4d69e60c76cc44022c180b52c71fa7fcf843fef0def3526c85dca",
    ),
    "session_receipt": (
        "owner/frontend.session.receipt.json",
        "6314050d669c9d82002e5998ec5a0a35caff93fdedd81d12bfff2f2676128e53",
    ),
    "fault_intent": (
        "owner/controller.loss.intent.json",
        "9885c92a5c03b4b9be8b372c5308e34291f62c134a67ee17aaa416f98590a41d",
    ),
    "terminal": (
        "qualification.terminal.json",
        "b29038d707543ed79a3dde6c6783e2b7c2c512446f575eab330a929eaf1d486d",
    ),
}
STOP_PINS = {
    "intent": (
        ".local/validation/owner-stops/ccc16a8440524bda84e57fdcd90055e7/poweroff.intent.json",
        "97754013c8ebc036e43133dc0f1299d45afd0eb8f73cb47964533fbb0d64db5a",
    ),
    "result": (
        ".local/validation/owner-stops/ccc16a8440524bda84e57fdcd90055e7/process.result.json",
        "38a2b6e4b73975fa399868017d084b582ac3f4ccc287bfe59589c742dc5b62a6",
    ),
}
CREATIONS_SHA256 = "982e04f5def56b73655dd4eebdc1a06f927d14dc0a3b27b66e88eabd74551c6a"
SAMPLES_SHA256 = "2becdfa354ae448b7006af87ab2cc3c0ae67196367007b175035bc7fe65520f8"
LEASE_SHA256 = "5a739e48c887b51ba027d2081eb35d5d0f01b6f4589eecd5a898bb616485a780"
NS = "{http://www.virtualbox.org/}"
PROGRESS = {"aborted": 0, "starting": 1, "running": 2}
STOP_SCRIPT = (
    "import pathlib,sys\n"
    "pathlib.Path(sys.argv[1]).write_bytes(bytes.fromhex(sys.argv[2]))\n"
    "raise SystemExit(int(sys.argv[3]))\n"
)
FRONTEND_SCRIPT = "import sys\nsys.stdin.buffer.read()\nraise SystemExit(0)\n"


def hex_text(value, size):
    return (
        type(value) is str
        and len(value) == size
        and all(character in "0123456789abcdef" for character in value)
    )


def file_sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def assert_scratch(path):
    candidate = Path(path).resolve()
    require(
        candidate != PRODUCTION_LEDGER.resolve(),
        "production admission ledger is untouched",
    )
    require(
        candidate != PRODUCTION_OWNER.resolve(),
        "original owner journal is untouched",
    )


def immutable_uri(path):
    return Path(path).resolve().as_uri() + "?mode=ro&immutable=1"


def history_sha():
    return digest(canonical(HISTORY))


def held_row_sha():
    return digest(canonical(HELD_ADMISSION))


def prototype_context():
    """Pinned fault facts. File and process checks are separate."""
    return {
        "format": CONTEXT_FORMAT,
        "role": "guard",
        "target_vm_uuid": GUARD_VM,
        "source_disk_uuid": GUARD_DISK,
        "initial_state": "aborted",
        "session_state": "Unlocked",
        "session_pid": 0,
        "prior_static_review_sha256": FAULT_PINS["static_review"][1],
        "prior_approval_sha256": FAULT_PINS["approval"][1],
        "runtime_binding_sha256": FAULT_PINS["runtime_binding"][1],
        "original_lease_sha256": LEASE_SHA256,
        "session_receipt_sha256": FAULT_PINS["session_receipt"][1],
        "running_samples_sha256": SAMPLES_SHA256,
        "fault_intent_sha256": FAULT_PINS["fault_intent"][1],
        "terminal_sha256": FAULT_PINS["terminal"][1],
        "stop_intent_sha256": STOP_PINS["intent"][1],
        "stop_result_sha256": STOP_PINS["result"][1],
        "stop_receipt": None,
        "authority": {
            "generation": 4,
            "active": 0,
            "lease_state": "stopping",
            "stop_state": "possible-send",
            "stop_receipt_sha": None,
        },
        "process_creations_sha256": CREATIONS_SHA256,
        "held_admission": dict(HELD_ADMISSION),
        "history": dict(HISTORY),
        "history_sha256": history_sha(),
        "files": json.loads(canonical(FILES)),
        "old_stop_accepted": False,
        "native_boot_authorized": False,
        "VM_started": False,
    }


def checked(value):
    require(type(value) is dict, "successor context is not an object")
    require(
        value.get("format") != "mcli1-initial-aborted-context-v3"
        and not any(
            "allow" in str(key).lower() and "abort" in str(key).lower() for key in value
        ),
        "historical recovery context cannot authorize a successor",
    )
    value = json.loads(canonical(value))
    require(
        value.get("format") == CONTEXT_FORMAT,
        "successor context format differs",
    )
    expected = prototype_context()
    require(set(value) == set(expected), "successor context fields differ")
    require(value == expected, "successor context provenance differs")
    require(value["initial_state"] == "aborted", "successor initial state is not aborted")
    require(value["stop_receipt"] is None, "failed stop receipt must remain absent")
    require(value["old_stop_accepted"] is False, "Aborted is not a successful stop")
    require(
        value["history"]["claims_about_failed_stop"] is False,
        "review 10 history is not evidence for this failed stop",
    )
    require(value["authority"]["active"] == 0, "old authority is still active")
    require(value["native_boot_authorized"] is False, "preparation cannot authorize boot")
    return value


def _pinned(path, expected):
    raw = Path(path).read_bytes()
    require(digest(raw) == expected, "pinned successor artifact changed: " + str(path))
    return raw


def verify_fault_files():
    for name, digest_hex in FAULT_PINS.values():
        _pinned(RUN_ROOT / name, digest_hex)
    for relative, digest_hex in STOP_PINS.values():
        _pinned(ROOT / relative, digest_hex)
    _pinned(ROOT / HISTORY["review_10_root"] / "review.json", HISTORY["review_10_sha256"])
    _pinned(
        ROOT / HISTORY["review_10_capture"] / "recovery.json",
        HISTORY["review_10_context_sha256"],
    )
    receipt = (
        ROOT
        / ".local/validation/owner-stops/b9479f8f1aad43faadc74b1594148303/command.receipt.json"
    )
    _pinned(receipt, HISTORY["review_10_stop_receipt_sha256"])
    _pinned(
        ROOT
        / ".local/validation/owner-stops/b9479f8f1aad43faadc74b1594148303/inventory.json",
        HISTORY["review_10_stop_inventory_sha256"],
    )
    loss = json.loads((RUN_ROOT / "owner/controller.loss.intent.json").read_text(encoding="utf-8"))
    require(digest(canonical(loss["samples"])) == SAMPLES_SHA256, "running samples changed")
    require(len(loss["samples"]) == 2, "controller-loss running samples are not two")
    require(digest(canonical(loss["original_lease"])) == LEASE_SHA256, "original lease changed")
    terminal = json.loads((RUN_ROOT / "qualification.terminal.json").read_text(encoding="utf-8"))
    creations = terminal["identities_proven_retired"]
    require(digest(canonical(creations)) == CREATIONS_SHA256, "process creations changed")
    require(terminal["original_stop_accepted"] is False, "terminal accepted the failed stop")
    return creations


def verify_owner_journal():
    require(
        file_sha(PRODUCTION_OWNER) == PRODUCTION_OWNER_SHA256,
        "original owner journal drifted before the read",
    )
    db = sqlite3.connect(immutable_uri(PRODUCTION_OWNER), uri=True, timeout=0.05)
    db.row_factory = sqlite3.Row
    try:
        authority = db.execute("SELECT * FROM authority").fetchone()
        stop = db.execute("SELECT * FROM native_owner_stop").fetchone()
        lease = db.execute("SELECT * FROM lease").fetchone()
        require(
            authority["generation"] == 4 and authority["active"] == 0,
            "original authority is not the fenced generation",
        )
        require(
            stop["state"] == "possible-send" and stop["receipt_sha"] is None,
            "original stop receipt is no longer missing",
        )
        require(lease["state"] == "stopping", "original lease is not unfinished")
    finally:
        db.close()
    require(
        file_sha(PRODUCTION_OWNER) == PRODUCTION_OWNER_SHA256,
        "original owner journal changed during the read",
    )


def verify_files(*, hash_disk=False):
    paths = backup.source_paths("guard")
    for label, expected in FILES.items():
        path = paths[label]
        require(expected["state"] == "file", "held successor files are present")
        require(path.is_file(), "required guard file is missing: " + label)
        require(path.stat().st_size == expected["bytes"], "guard file size changed: " + label)
        if label != "disk" or hash_disk:
            require(file_sha(path) == expected["sha256"], "guard file bytes changed: " + label)
    if hash_disk:
        executor = backup.source_paths("executor")
        for label, expected in EXECUTOR_FILES.items():
            path = executor[label]
            require(path.is_file(), "executor file is missing")
            require(
                path.stat().st_size == expected["bytes"]
                and file_sha(path) == expected["sha256"],
                "executor file drifted",
            )


def require_retired(creations, probe):
    require(type(creations) is list, "process creations are incomplete")
    for record in creations:
        try:
            retired = probe(record)
        except (Hold, OSError) as error:
            raise Hold(
                "old process retirement is inaccessible: " + str(error)[:160]
            ) from error
        require(retired is True, "old process is still live")
    require(len(creations) == 6, "process creations are incomplete")


def load_provenance(*, probe=None, hash_disk=False):
    creations = verify_fault_files()
    verify_owner_journal()
    verify_files(hash_disk=hash_disk)
    require_retired(creations, process_proof.retired if probe is None else probe)
    return checked(prototype_context())


def startup_progress(states):
    """Forward Aborted, Starting and Running only. This does not touch a VM."""
    require(
        type(states) is list and bool(states) and states[0] == "aborted",
        "successor startup must begin aborted",
    )
    require(
        all(state in PROGRESS for state in states),
        "successor startup left the aborted/starting/running grant",
    )
    ranks = [PROGRESS[state] for state in states]
    require(ranks == sorted(ranks), "successor startup moved backward")
    return ranks


def draft_review(context, output_relative):
    checked(context)
    require(
        type(output_relative) is str
        and output_relative.startswith(".local/validation/held-successor-")
        and ".." not in output_relative,
        "successor output path is unbound",
    )
    return {
        "format": REVIEW_FORMAT,
        "case": CASE,
        "initial_state": "aborted",
        "role": "guard",
        "target_vm_uuid": GUARD_VM,
        "source_disk_uuid": GUARD_DISK,
        "context_sha256": digest(canonical(context)),
        "prior_held_row_sha256": held_row_sha(),
        "history_sha256": history_sha(),
        "inputs": json.loads(canonical(FILES)),
        "proposed_transfer": {
            "prior_review_id": HELD_ADMISSION["review_id"],
            "prior_state_remains": "held",
            "prior_stop_receipt": None,
            "prior_active_becomes": 0,
            "successor_active": 1,
            "settles_old_stop": False,
        },
        "activation_output_relative": output_relative,
        "native_boot_authorized": False,
        "executor_activation": False,
        "processes_allocated": 0,
        "leases_allocated": 0,
        "sources": {"held_successor.py": file_sha(Path(__file__))},
    }


def checked_review(review):
    require(
        set(review)
        == {
            "format",
            "case",
            "initial_state",
            "role",
            "target_vm_uuid",
            "source_disk_uuid",
            "context_sha256",
            "prior_held_row_sha256",
            "history_sha256",
            "inputs",
            "proposed_transfer",
            "activation_output_relative",
            "native_boot_authorized",
            "executor_activation",
            "processes_allocated",
            "leases_allocated",
            "sources",
        }
        and review["format"] == REVIEW_FORMAT
        and review["case"] == CASE
        and review["initial_state"] == "aborted"
        and review["native_boot_authorized"] is False
        and review["executor_activation"] is False
        and review["processes_allocated"] == 0
        and review["proposed_transfer"]["settles_old_stop"] is False
        and review["proposed_transfer"]["prior_stop_receipt"] is None
        and review["proposed_transfer"]["prior_state_remains"] == "held",
        "successor review is not the single aborted recovery case",
    )
    return review


class ScratchLedger:
    """Explicit transactions on a copy. The production ledger is refused."""

    def __init__(self, path):
        assert_scratch(path)
        self.path = Path(path)
        self.db = sqlite3.connect(self.path, timeout=1, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")

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


def seed_held(path, row=None):
    assert_scratch(path)
    source = HELD_ADMISSION if row is None else row
    with closing(offline.Admissions(path)) as admissions:
        admissions.db.execute(
            "INSERT INTO admissions VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                source["review_id"],
                source["review_sha"],
                source["approval_sha"],
                source["target"],
                source["output"],
                source["state"],
                source["revoked"],
                source["active"],
                source["binding_sha"],
                source["input_sha"],
            ),
        )


def migrate(path, *, before_ready=None):
    assert_scratch(path)
    ledger = ScratchLedger(path)
    try:
        version = ledger.db.execute("PRAGMA user_version").fetchone()[0]
        require(version == 0, "uncertain admission migration holds without repair")
        ledger.db.execute("PRAGMA user_version=1")
        with ledger.transaction():
            ledger.db.execute(
                """CREATE TABLE continuations (
                    prior_id TEXT PRIMARY KEY,
                    successor_id TEXT UNIQUE NOT NULL,
                    prior_row_sha TEXT NOT NULL,
                    approval_sha TEXT UNIQUE NOT NULL,
                    link_sha TEXT NOT NULL,
                    history_sha TEXT NOT NULL,
                    FOREIGN KEY(prior_id) REFERENCES admissions(review_id),
                    FOREIGN KEY(successor_id) REFERENCES admissions(review_id))"""
            )
            ledger.db.execute(
                """CREATE TABLE successor_stops (
                    successor_id TEXT PRIMARY KEY,
                    proof_sha TEXT NOT NULL,
                    accepted INTEGER NOT NULL CHECK(accepted=1),
                    FOREIGN KEY(successor_id) REFERENCES admissions(review_id))"""
            )
            columns = {
                item[1] for item in ledger.db.execute("PRAGMA table_info(admissions)")
            }
            if "stop_receipt_sha" not in columns:
                ledger.db.execute(
                    "ALTER TABLE admissions ADD COLUMN stop_receipt_sha TEXT"
                )
        if before_ready is not None:
            before_ready(ledger)
            return {"status": "migration-interrupted", "repaired": False}
        require(
            ledger.db.execute("PRAGMA user_version").fetchone()[0] == 1,
            "admission migration version drifted",
        )
        ledger.db.execute("PRAGMA user_version=2")
        return {"status": "scratch-migration-ready", "production_modified": False}
    finally:
        ledger.close()


def _ready(ledger):
    version = ledger.db.execute("PRAGMA user_version").fetchone()[0]
    require(version == 2, "admission migration is incomplete; no automatic repair")


def _row(ledger, ident):
    row = ledger.db.execute(
        "SELECT * FROM admissions WHERE review_id=?", (ident,)
    ).fetchone()
    require(row is not None, "admission row is missing")
    require(set(ADMISSION_KEYS) <= set(row.keys()), "admission row shape differs")
    return {key: row[key] for key in ADMISSION_KEYS}


def _refuse_graph(ledger, prior_id, successor_id):
    require(prior_id != successor_id, "continuation cycle")
    require(
        ledger.db.execute(
            "SELECT 1 FROM continuations WHERE prior_id=? OR successor_id=?",
            (prior_id, successor_id),
        ).fetchone()
        is None,
        "continuation fork",
    )
    seen, cursor = set(), prior_id
    while True:
        parent = ledger.db.execute(
            "SELECT prior_id FROM continuations WHERE successor_id=?",
            (cursor,),
        ).fetchone()
        if parent is None:
            break
        require(
            parent["prior_id"] not in seen and parent["prior_id"] != successor_id,
            "continuation cycle",
        )
        seen.add(parent["prior_id"])
        cursor = parent["prior_id"]


def transfer(ledger, successor, *, expected_prior=None, authority_active=0, history=None):
    """One compare-and-transfer. Returns only after commit and readback."""
    assert_scratch(ledger.path)
    expected = HELD_ADMISSION if expected_prior is None else expected_prior
    require(authority_active == 0, "old authority is not inactive")
    require(history == history_sha(), "successor history is missing or stale")
    require(
        hex_text(successor["review_id"], 32)
        and hex_text(successor["review_sha"], 64)
        and hex_text(successor["approval_sha"], 64)
        and successor["review_id"] != expected["review_id"]
        and successor["target"] == expected["target"],
        "successor identity or target differs",
    )
    link = {
        "format": "mcli1-held-guard-continuation-v1",
        "prior_id": expected["review_id"],
        "successor_id": successor["review_id"],
        "prior_row_sha": digest(canonical(expected)),
        "approval_sha": successor["approval_sha"],
        "history_sha": history,
        "prior_state_remains": "held",
        "prior_stop_receipt": None,
        "settles_old_stop": False,
    }
    link_sha = digest(canonical(link))
    try:
        with ledger.transaction():
            _ready(ledger)
            _refuse_graph(ledger, expected["review_id"], successor["review_id"])
            current = _row(ledger, expected["review_id"])
            require(current == expected, "prior admission row changed")
            require(
                current["state"] == "held"
                and current["active"] == 1
                and current["revoked"] == 0
                and current["stop_receipt_sha"] is None,
                "prior admission is not a held reservation",
            )
            updated = ledger.db.execute(
                """UPDATE admissions SET active=0
                   WHERE review_id=? AND review_sha=? AND approval_sha=? AND target=?
                     AND output=? AND state='held' AND revoked=0 AND active=1
                     AND binding_sha=? AND input_sha=? AND stop_receipt_sha IS NULL""",
                (
                    expected["review_id"],
                    expected["review_sha"],
                    expected["approval_sha"],
                    expected["target"],
                    expected["output"],
                    expected["binding_sha"],
                    expected["input_sha"],
                ),
            )
            require(updated.rowcount == 1, "prior reservation compare failed")
            ledger.db.execute(
                """INSERT INTO admissions
                   (review_id, review_sha, approval_sha, target, output, state, revoked,
                    active, binding_sha, input_sha, stop_receipt_sha)
                   VALUES(?,?,?,?,?,'consumed',0,1,NULL,NULL,NULL)""",
                (
                    successor["review_id"],
                    successor["review_sha"],
                    successor["approval_sha"],
                    successor["target"],
                    successor["output"],
                ),
            )
            ledger.db.execute(
                "INSERT INTO continuations VALUES(?,?,?,?,?,?)",
                (
                    expected["review_id"],
                    successor["review_id"],
                    link["prior_row_sha"],
                    successor["approval_sha"],
                    link_sha,
                    history,
                ),
            )
    except sqlite3.Error as error:
        raise Hold("successor transfer refused: " + str(error)[:160]) from error
    prior = _row(ledger, expected["review_id"])
    current_successor = _row(ledger, successor["review_id"])
    stored = ledger.db.execute(
        "SELECT * FROM continuations WHERE prior_id=?",
        (expected["review_id"],),
    ).fetchone()
    require(
        prior["state"] == "held"
        and prior["active"] == 0
        and prior["stop_receipt_sha"] is None
        and current_successor["state"] == "consumed"
        and current_successor["active"] == 1
        and current_successor["revoked"] == 0
        and stored["link_sha"] == link_sha
        and stored["history_sha"] == history
        and stored["successor_id"] == successor["review_id"],
        "successor transfer readback differs",
    )
    return {
        "allocation_allowed": True,
        "dispatch_authorized": False,
        "native_boot_authorized": False,
        "prior_id": expected["review_id"],
        "successor_id": successor["review_id"],
        "link_sha": link_sha,
        "old_stop_accepted": False,
    }


def allocate(ledger, token, starter):
    require(
        type(token) is dict
        and token.get("allocation_allowed") is True
        and token.get("dispatch_authorized") is False
        and token.get("native_boot_authorized") is False
        and not ledger.db.in_transaction,
        "successor process allocation is not confirmed",
    )
    row = _row(ledger, token["successor_id"])
    require(
        row["active"] == 1 and row["revoked"] == 0 and row["state"] == "consumed",
        "successor was revoked before process allocation",
    )
    return starter()


def inspect(path, prior_id):
    assert_scratch(path)
    db = sqlite3.connect(
        Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=0.05
    )
    db.row_factory = sqlite3.Row
    try:
        link = db.execute(
            "SELECT * FROM continuations WHERE prior_id=?", (prior_id,)
        ).fetchone()
        prior = db.execute(
            "SELECT state, active, stop_receipt_sha FROM admissions WHERE review_id=?",
            (prior_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        link, prior = None, None
    finally:
        db.close()
    return {
        "transfer_committed": link is not None,
        "prior_state": None if prior is None else prior["state"],
        "prior_active": None if prior is None else prior["active"],
        "prior_stop_receipt": None if prior is None else prior["stop_receipt_sha"],
        "dispatch_authorized": False,
        "native_boot_authorized": False,
        "allocation_performed": False,
    }


def snapshot_ledger(destination):
    assert_scratch(destination)
    destination = Path(destination)
    require(not destination.exists(), "snapshot output already exists")
    before = file_sha(PRODUCTION_LEDGER)
    require(before == PRODUCTION_LEDGER_SHA256, "production admission ledger drifted")
    source = sqlite3.connect(immutable_uri(PRODUCTION_LEDGER), uri=True, timeout=0.05)
    try:
        copied = sqlite3.connect(destination)
        try:
            source.backup(copied)
        finally:
            copied.close()
    finally:
        source.close()
    require(file_sha(PRODUCTION_LEDGER) == before, "snapshot wrote the production ledger")
    return {
        "source_sha256": before,
        "bytes": destination.stat().st_size,
        "transferred": False,
        "native_boot_authorized": False,
    }


def record_command(log, argv):
    require(type(argv) is list and bool(argv), "surrogate command is empty")
    text = " ".join(str(part) for part in argv).lower()
    require(
        "vboxmanage" not in text and "vboxheadless" not in text and "startvm" not in text,
        "preparation issued a native VM command",
    )
    log.append([str(part) for part in argv])


def job_pids(job):
    class Pids(ctypes.Structure):
        _fields_ = [
            ("assigned", wintypes.DWORD),
            ("count", wintypes.DWORD),
            ("pids", ctypes.c_size_t * 16),
        ]

    value = Pids()
    length = wintypes.DWORD()
    ok = job.api.QueryInformationJobObject(
        job.handle,
        3,
        ctypes.byref(value),
        ctypes.sizeof(value),
        ctypes.byref(length),
    )
    require(ok, "successor job query failed")
    require(0 <= value.count <= 16, "successor job process count exceeds its bound")
    return [value.pids[index] for index in range(value.count)]


def _wait_exit(child, seconds=5):
    deadline = time.monotonic() + seconds
    while child.poll() is None:
        require(time.monotonic() < deadline, "surrogate process did not exit")
        time.sleep(0.01)
    return child.poll()


class Surrogate:
    def __init__(self, root, successor_id):
        self.root = Path(root)
        self.successor_id = successor_id
        self.commands = []
        self.job = None
        self.frontend = None
        self.stop = None
        self.resumed = False
        self.stop_resumed = False
        self.identities = None
        self.receipt = self.root / "command.receipt.json"
        self.owner_db = self.root / "owner.sqlite"

    def close(self):
        if self.job is not None:
            self.job.close()
            self.job = None
        for child in (self.frontend, self.stop):
            if child is not None:
                child.close()
        self.frontend = self.stop = None


def open_surrogate(root, successor_id, *, stop_exit, observations):
    """Create the job and suspended Python processes. Nothing is resumed yet."""
    require_poweroff(observations)
    session_state = Surrogate(root, successor_id)
    session_state.root.mkdir(parents=True, exist_ok=False)
    session_state.observations = observations
    session_state.stop_exit = stop_exit
    nonce = uuid4().hex
    session_state.job = ControllerJob("Local\\MCLI1SuccessorPrep-" + nonce)
    try:
        front_argv = [sys.executable, "-I", "-B", "-c", FRONTEND_SCRIPT]
        record_command(session_state.commands, front_argv)
        session_state.frontend = SuspendedChild(
            ["-I", "-B", "-c", FRONTEND_SCRIPT], session_state.job
        )
        receipt = canonical(
            {
                "format": "mcli1-surrogate-stop-receipt-v1",
                "exit": stop_exit,
                "target_vm_uuid": GUARD_VM,
                "successor_id": successor_id,
                "native_command": False,
            }
        )
        session_state.receipt_bytes = receipt
        stop_argv = [
            sys.executable,
            "-I",
            "-B",
            "-c",
            STOP_SCRIPT,
            str(session_state.receipt),
            receipt.hex(),
            str(stop_exit),
        ]
        record_command(session_state.commands, stop_argv)
        session_state.stop = SuspendedChild(
            ["-I", "-B", "-c", STOP_SCRIPT, str(session_state.receipt), receipt.hex(), str(stop_exit)],
            session_state.job,
        )
    except Exception:
        session_state.close()
        raise
    return session_state


def bind_lease(session_state):
    require(session_state.resumed is False, "frontend resumed before its lease was bound")
    frontend = host.process_identity(session_state.frontend.pid)
    owner = host.process_identity(session_state.stop.pid)
    now, mono = time.time_ns(), time.monotonic_ns()
    lease = {
        "target": GUARD_VM,
        "armed_ns": now,
        "expires_ns": now + MAX_LEASE_NS,
        "armed_mono_ns": mono,
        "expires_mono_ns": mono + MAX_LEASE_NS,
        "state": "armed",
    }
    require(
        0 < lease["expires_ns"] - lease["armed_ns"] <= MAX_LEASE_NS,
        "successor lease exceeds 600 seconds",
    )
    session_state.identities = {"frontend": frontend, "owner": owner, "lease": lease}
    db = sqlite3.connect(session_state.owner_db, isolation_level=None)
    try:
        db.execute(
            """CREATE TABLE lease (singleton INTEGER PRIMARY KEY CHECK(singleton=1),
               target TEXT, armed_ns INTEGER, expires_ns INTEGER, armed_mono_ns INTEGER,
               expires_mono_ns INTEGER, state TEXT)"""
        )
        db.execute(
            """CREATE TABLE authority (singleton INTEGER PRIMARY KEY CHECK(singleton=1),
               generation INTEGER, active INTEGER)"""
        )
        db.execute(
            """CREATE TABLE native_owner_stop (singleton INTEGER PRIMARY KEY CHECK(singleton=1),
               plan_sha TEXT, intent_sha TEXT, state TEXT, child_pid INTEGER, receipt_sha TEXT)"""
        )
        db.execute(
            """CREATE TABLE maintenance_owner (singleton INTEGER PRIMARY KEY CHECK(singleton=1),
               binding BLOB, observed_mono_ns INTEGER, sequence INTEGER, state TEXT)"""
        )
        db.execute(
            "INSERT INTO lease VALUES(1,?,?,?,?,?,'armed')",
            (
                lease["target"],
                lease["armed_ns"],
                lease["expires_ns"],
                lease["armed_mono_ns"],
                lease["expires_mono_ns"],
            ),
        )
        db.execute("INSERT INTO authority VALUES(1,1,1)")
        db.execute(
            "INSERT INTO native_owner_stop VALUES(1,NULL,NULL,'unarmed',?,NULL)",
            (owner["pid"],),
        )
        db.execute(
            "INSERT INTO maintenance_owner VALUES(1,?,?,1,'watching')",
            (canonical(session_state.identities), mono),
        )
    finally:
        db.close()
    (session_state.root / "identities.json").write_bytes(canonical(session_state.identities))
    return session_state.identities


def resume_frontend(ledger, session_state, image_sha, image):
    require(digest(image) == image_sha, "unarmed bytes drifted")
    require(session_state.identities is not None, "identities are not bound")
    require(session_state.resumed is False, "frontend resume is one-shot")
    row = _row(ledger, session_state.successor_id)
    require(row["revoked"] == 0 and row["active"] == 1, "successor was revoked before arming")
    record_command(session_state.commands, ["resume-frontend-once"])
    session_state.frontend.resume(b"ready\n")
    session_state.resumed = True


def run_stop(session_state):
    require(session_state.resumed is True, "stop precedes the single frontend resume")
    require(session_state.stop_resumed is False, "surrogate stop is one-shot")
    record_command(session_state.commands, ["resume-python-stop-once"])
    session_state.stop.resume(b"stop\n")
    session_state.stop_resumed = True
    frontend_exit = _wait_exit(session_state.frontend)
    stop_exit = _wait_exit(session_state.stop)
    receipt = session_state.receipt.read_bytes()
    parsed = json.loads(receipt)
    require(parsed["exit"] == stop_exit, "stop receipt does not match the process exit")
    require(parsed["native_command"] is False, "surrogate stop recorded a native command")
    family = [
        {"pid": session_state.frontend.pid, "exit_code": frontend_exit},
        {"pid": session_state.stop.pid, "exit_code": stop_exit},
    ]
    active = job_pids(session_state.job)
    facts = {
        "family": family,
        "job_active_processes": len(active),
        "receipt_sha256": digest(receipt),
        "commands": session_state.commands,
        "observations": session_state.observations,
    }
    (session_state.root / "family.json").write_bytes(canonical(facts["family"]))
    (session_state.root / "job.json").write_bytes(
        canonical({"job_active_processes": facts["job_active_processes"]})
    )
    (session_state.root / "commands.json").write_bytes(canonical(session_state.commands))
    (session_state.root / "observations.json").write_bytes(
        canonical(session_state.observations)
    )
    db = sqlite3.connect(session_state.owner_db, isolation_level=None)
    try:
        db.execute("UPDATE authority SET active=0")
        db.execute("UPDATE lease SET state='stop-command-returned'")
        db.execute(
            """UPDATE native_owner_stop
               SET state='command-returned', receipt_sha=?, child_pid=?""",
            (facts["receipt_sha256"], session_state.stop.pid),
        )
        db.execute("UPDATE maintenance_owner SET state='stop-returned'")
    finally:
        db.close()
    return facts


def require_poweroff(observations):
    require(
        type(observations) is list and len(observations) == 2,
        "successor stop needs two observations",
    )
    machines = []
    stamps = []
    for item in observations:
        require(item.get("state") == "poweroff", "successor stop is not independently powered off")
        require(item.get("session_state") == "Unlocked", "successor session is not unlocked")
        require(item.get("session_pid") == 0, "successor session PID is not zero")
        require(item.get("nics_disabled") is True, "successor observation has an enabled NIC")
        require(item.get("enabled_transports") == [], "successor observation has an enabled transport")
        require(item.get("saved_state") is False, "successor observation contains saved state")
        require(item.get("hardware_uuid") == GUARD_VM, "successor hardware changed")
        require(hex_text(item.get("machine_sha256"), 64), "successor machine digest differs")
        machines.append(item["machine_sha256"])
        stamps.append(item["observed_mono_ns"])
    require(machines[0] == machines[1], "successor poweroff observations differ")
    require(stamps[0] != stamps[1], "successor poweroff observations are not two samples")


def accept_independent_stop(ledger, session_state):
    """Re-read the owner journal, receipt, family and observations. No settled flag."""
    observations = json.loads(
        (session_state.root / "observations.json").read_text(encoding="utf-8")
    )
    require_poweroff(observations)
    commands = json.loads((session_state.root / "commands.json").read_text(encoding="utf-8"))
    for argv in commands:
        record_command([], argv)
    family = json.loads((session_state.root / "family.json").read_text(encoding="utf-8"))
    job = json.loads((session_state.root / "job.json").read_text(encoding="utf-8"))
    receipt = (session_state.root / "command.receipt.json").read_bytes()
    parsed = json.loads(receipt)
    require(parsed["exit"] == 0 and parsed["native_command"] is False, "successor stop failed")
    require(
        all(type(row["exit_code"]) is int and row["exit_code"] == 0 for row in family),
        "successor family exit is not a natural zero",
    )
    require(job["job_active_processes"] == 0, "successor job is not empty")
    db = sqlite3.connect(
        session_state.owner_db.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.05
    )
    db.row_factory = sqlite3.Row
    try:
        lease = db.execute("SELECT * FROM lease").fetchone()
        authority = db.execute("SELECT * FROM authority").fetchone()
        native = db.execute("SELECT * FROM native_owner_stop").fetchone()
        owner = db.execute("SELECT * FROM maintenance_owner").fetchone()
        require(
            lease["state"] == "stop-command-returned"
            and 0 < lease["expires_ns"] - lease["armed_ns"] <= MAX_LEASE_NS
            and authority["active"] == 0
            and native["state"] == "command-returned"
            and native["receipt_sha"] == digest(receipt)
            and owner["state"] == "stop-returned",
            "successor owner journal does not prove the stop",
        )
    finally:
        db.close()
    row = _row(ledger, session_state.successor_id)
    require(row["revoked"] == 0 and row["active"] == 1, "successor was revoked after arming")
    proof = {
        "format": "mcli1-successor-stop-proof-v1",
        "successor_id": session_state.successor_id,
        "receipt_sha256": digest(receipt),
        "family": family,
        "observations": observations,
        "native_boot_authorized": False,
        "old_stop_accepted": False,
    }
    proof_sha = digest(canonical(proof))
    with ledger.transaction():
        current = _row(ledger, session_state.successor_id)
        require(current["revoked"] == 0 and current["active"] == 1, "successor revoked")
        ledger.db.execute(
            "INSERT INTO successor_stops VALUES(?,?,1)",
            (session_state.successor_id, proof_sha),
        )
    return {"proof_sha256": proof_sha, "native_commands": 0, "old_stop_accepted": False}


def require_profile(record, *, state):
    require(record.get("state") == state, "profile state differs")
    require(record.get("session_state") == "Unlocked", "profile session is not unlocked")
    require(record.get("session_pid") == 0, "profile session PID is not zero")
    require(record.get("nics_disabled") is True, "profile NIC is enabled")
    require(record.get("enabled_transports") == [], "profile transport is enabled")
    require(record.get("saved_state") is False, "profile contains saved state")
    require(record.get("hardware_uuid") == GUARD_VM, "profile hardware changed")
    require(hex_text(record.get("machine_sha256"), 64), "profile machine digest differs")
    require(hex_text(record.get("medium_sha256"), 64), "profile medium digest differs")


def require_guard_configuration(raw):
    require(len(raw) <= 64 * 1024, "guard configuration exceeds its bound")
    machine = ET.fromstring(raw).find(NS + "Machine")
    require(machine is not None, "guard configuration has no machine")
    require(machine.attrib.get("aborted") == "true", "guard configuration is not aborted")
    require(
        machine.attrib.get("uuid") == "{" + GUARD_VM + "}",
        "guard configuration uuid differs",
    )
    lowered = raw.decode("utf-8", "replace").lower()
    require("statefile" not in lowered and "<snapshot" not in lowered, "saved state is present")
    disk = machine.find(".//" + NS + "HardDisk")
    require(
        disk is not None and disk.attrib.get("uuid") == "{" + GUARD_DISK + "}",
        "copied guard disk uuid differs",
    )


def capture(
    output,
    *,
    sources,
    expected,
    observe,
    root_factory,
    executor=None,
    executor_expected=None,
    locker=backup.locked_source,
):
    """Unattached byte copy. The observer is read-only; no VM control command is issued."""
    root = root_factory(output)
    (root / "backup").mkdir()
    (root / "intent.json").write_bytes(
        canonical(
            {
                "status": "copying-not-accepted",
                "initial_state": "aborted",
                "native_boot_authorized": False,
                "never_attach": True,
            }
        )
    )
    first = observe("guard")
    require_profile(first, state="aborted")
    if executor is not None:
        for label, pin in executor_expected.items():
            path = executor[label]
            require(path.is_file(), "executor file disappeared")
            require(
                path.stat().st_size == pin["bytes"] and file_sha(path) == pin["sha256"],
                "executor file drifted before the copy",
            )
    deadline = time.monotonic() + 600
    files = {}
    for label, pin in expected.items():
        source = sources[label]
        require(pin["state"] == "file", "successor backup does not relabel an absent file")
        require(source.is_file(), "backup source is missing: " + label)
        if label == "configuration":
            require_guard_configuration(source.read_bytes())
        destination = root / "backup" / {
            "disk": "disk.vdi",
            "configuration": "configuration.vbox",
            "nvram": "nvram.bin",
        }[label]
        with locker(source) as stream:
            header = stream.read(512)
            stream.seek(0)
            identities = backup.copy_file(stream, destination, pin, deadline)
        with destination.open("rb") as copied:
            require(copied.read(512) == header, "disk header drifted")
        require(
            identities["source_identity"] != identities["backup_identity"],
            "backup aliases its source",
        )
        files[label] = {**pin, "backup_name": destination.name, **identities}
    last = observe("guard")
    require_profile(last, state="aborted")
    require(
        first["machine_sha256"] == last["machine_sha256"]
        and first["medium_sha256"] == last["medium_sha256"],
        "profile drifted during the unattached copy",
    )
    if executor is not None:
        for label, pin in executor_expected.items():
            path = executor[label]
            require(
                path.stat().st_size == pin["bytes"] and file_sha(path) == pin["sha256"],
                "executor file drifted during the copy",
            )
    if expected == FILES:
        context = checked(prototype_context())
    else:
        context = {
            "format": "mcli1-held-guard-successor-synthetic-capture-v1",
            "initial_state": "aborted",
            "old_stop_accepted": False,
            "native_boot_authorized": False,
            "files": {
                label: {"bytes": item["bytes"], "sha256": item["sha256"]}
                for label, item in files.items()
            },
        }
    profile = {
        "format": PROFILE_FORMAT,
        "status": "aborted-profile-reported-not-boot-authority",
        "initial_state": "aborted",
        "target_vm_uuid": GUARD_VM,
        "source_disk_uuid": GUARD_DISK,
        "first_observation": first,
        "last_observation": last,
        "native_boot_authorized": False,
        "VM_mutations": 0,
        "old_stop_accepted": False,
    }
    receipt = {
        "format": BACKUP_FORMAT,
        "initial_state": "aborted",
        "never_attach": True,
        "registered": False,
        "independent": True,
        "files": {
            label: {"bytes": item["bytes"], "sha256": item["sha256"], "backup_name": item["backup_name"]}
            for label, item in files.items()
        },
        "native_boot_authorized": False,
        "VM_mutations": 0,
    }
    (root / "profile.json").write_bytes(canonical(profile))
    (root / "backup/receipt.json").write_bytes(canonical(receipt))
    (root / "context.json").write_bytes(canonical(context))
    result = {
        "status": "held-successor-capture-reported-not-boot-authority",
        "initial_state": "aborted",
        "native_boot_authorized": False,
        "registered": False,
        "VM_mutations": 0,
        "old_stop_accepted": False,
        "profile_sha256": file_sha(root / "profile.json"),
        "backup_sha256": file_sha(root / "backup/receipt.json"),
    }
    (root / "preparation.receipt.json").write_bytes(canonical(result))
    return result


def quiescent_record(role, folder):
    """Read-only inventory. The returned record is Aborted for the guard only."""
    observer = session.NativeObserver(role)
    folder.mkdir(parents=True, exist_ok=False)
    try:
        frame = observer()
        frame = {**frame, "session_raw": observer.last["session_raw"]}
    finally:
        session.retain(folder, observer)
    state = "aborted" if role == "guard" else "poweroff"
    machine_state = 4 if role == "guard" else 1
    slot = backup.SLOTS[role]
    grant = {"role": role, "target": {"vm_uuid": slot["vm_uuid"], "disk_uuid": slot["disk_uuid"]}}
    expected = host.transfer.expected_host(grant)
    expected["state"] = state
    fields = host.machine_fields(frame["machine"])
    require(
        host.machine_profile(frame["machine"]) == expected
        and fields["hardwareuuid"] == slot["vm_uuid"]
        and all(fields.get(key) == value for key, value in boot.BOOT_FIELDS.items())
        and frame["session"]
        == {
            "vm_uuid": slot["vm_uuid"],
            "state_before": "Unlocked",
            "state_after": "Unlocked",
            "pid": 0,
        },
        "live profile is not the quiescent disconnected target",
    )
    native = session.session_record(frame["session_raw"], role)
    require(
        native["machine_before"] == native["machine_after"] == machine_state
        and native["pid"] == 0,
        "live session raw observation is not quiescent",
    )
    host.check_medium(frame["medium"], frame["machine"], grant)
    require(
        host.medium_fields(frame["medium"])["State"] == "created",
        "live medium remains locked",
    )
    return {
        "state": state,
        "session_state": "Unlocked",
        "session_pid": 0,
        "nics_disabled": True,
        "enabled_transports": [],
        "saved_state": False,
        "hardware_uuid": GUARD_VM if role == "guard" else slot["vm_uuid"],
        "machine_sha256": digest(frame["machine"]),
        "medium_sha256": digest(frame["medium"]),
        "readonly_inventory": True,
    }


def measured_capture(output_relative=".local/validation/held-successor-capture-01"):
    """Fresh read-only inventory plus one unattached copy. No transfer and no boot."""
    output = ROOT / output_relative
    require(not output.exists(), "held successor capture output already exists")
    context = load_provenance(hash_disk=True)
    staging = Path(tempfile.mkdtemp(prefix="held-successor-observe-"))
    try:
        executor_before = quiescent_record("executor", staging / "executor-before")
        quiescent_record("guard", staging / "guard-probe")
        observations = output / "observations"

        def observe(role):
            require(role == "guard", "unattached copy observes the guard")
            name = (
                "guard-before"
                if not (observations / "guard-before").exists()
                else "guard-after"
            )
            return quiescent_record(role, observations / name)

        result = capture(
            output,
            sources=backup.source_paths("guard"),
            expected=FILES,
            observe=observe,
            root_factory=new_root,
            executor=backup.source_paths("executor"),
            executor_expected=EXECUTOR_FILES,
        )
        shutil.copytree(staging / "executor-before", observations / "executor-before")
        executor_after = quiescent_record("executor", observations / "executor-after")
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    snapshot = snapshot_ledger(output / "admission-snapshot.sqlite")
    result.update(
        context_sha256=digest(canonical(context)),
        admission_snapshot=snapshot,
        executor_before=executor_before,
        executor_after=executor_after,
        production_ledger_sha256=file_sha(PRODUCTION_LEDGER),
        production_owner_sha256=file_sha(PRODUCTION_OWNER),
        transferred=False,
        measured_observations=True,
    )
    (output / "measured.json").write_bytes(canonical(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("verify-provenance", "capture"))
    parser.add_argument("--output", default=".local/validation/held-successor-capture-01")
    args = parser.parse_args()
    if args.command == "verify-provenance":
        value = load_provenance(hash_disk=False)
        print(
            json.dumps(
                {
                    "status": "held-successor-provenance-verified",
                    "context_sha256": digest(canonical(value)),
                    "old_stop_accepted": False,
                    "native_boot_authorized": False,
                }
            )
        )
        return
    result = measured_capture(args.output)
    print(json.dumps({"status": result["status"], "transferred": False}))


if __name__ == "__main__":
    main()
