"""Typed initial-Aborted provenance; all process/file/VM facts here are synthetic."""

import copy
import unittest

from research.validation import backup_records as records
from research.validation import recovery_records as recovery
from research.validation.fixture import canonical
from research.validation.store import Hold
from research.validation.transfer_commands import digest


def intervening():
    processes = {
        name: {
            "pid": 4000 + i,
            "created_filetime": 5000 + i,
            "image": "C:/synthetic/process.exe",
        }
        for i, name in enumerate(("bootstrap", "controller", "owner", "frontend"))
    }
    return {
        "review_sha256": recovery.INTERVENING_REVIEW,
        "parent_context_sha256": recovery.PARENT_CONTEXT_SHA256,
        "owner_nonce": "8" * 32,
        "artifacts": {
            **dict.fromkeys(recovery.INTERVENING_ARTIFACTS, "7" * 64),
            "review.json": recovery.INTERVENING_REVIEW,
            "parent/recovery.json": recovery.PARENT_CONTEXT_SHA256,
        },
        "processes": processes,
        "family": [{**processes["frontend"], "exit_code": 1}],
        "stop_child_pid": 6000,
        "stop_exit": 1,
        "frontend_job_active_processes": 0,
        "stop_job_active_processes": 0,
    }


def latest():
    value = intervening()
    value.update(
        review_sha256=recovery.LATEST_REVIEW,
        parent_context_sha256=recovery.LATEST_PARENT_SHA256,
        artifacts={
            **dict.fromkeys(recovery.LATEST_ARTIFACTS, "7" * 64),
            "review.json": recovery.LATEST_REVIEW,
            "parent/recovery.json": recovery.LATEST_PARENT_SHA256,
        },
    )
    leaf = {"pid": 7010, "created_filetime": 8010, "image": "C:/synthetic/process.exe"}
    value.update(
        family=[
            {**value["processes"]["frontend"], "exit_code": 2},
            {**leaf, "exit_code": None},
        ],
        joined_process=leaf,
        join_receipt_sha256="7" * 64,
        frontend_ledger_state="resumed",
        frontend_ledger_receipt_sha=None,
    )
    return value


def context():
    observation = {
        "observed_mono_ns": 100,
        "machine_sha256": "a" * 64,
        "medium_sha256": "b" * 64,
        "session_sha256": "c" * 64,
    }
    return {
        "format": recovery.FORMAT,
        "role": "guard",
        "target_vm_uuid": recovery.GUARD_VM,
        "source_disk_uuid": recovery.GUARD_DISK,
        "initial_state": "aborted",
        "session_state": "Unlocked",
        "session_pid": 0,
        "prior": {
            "review_sha256": recovery.PRIOR_REVIEW,
            "owner_nonce": "d" * 32,
            "artifacts": {
                **dict.fromkeys(recovery.PRIOR_ARTIFACTS, "e" * 64),
                "review.json": recovery.PRIOR_REVIEW,
            },
            "processes": {
                name: {
                    "pid": 1000 + i,
                    "created_filetime": 2000 + i,
                    "image": "C:/synthetic/process.exe",
                }
                for i, name in enumerate(
                    ("bootstrap", "controller", "owner", "frontend")
                )
            },
            "stop_child_pid": 3000,
            "stop_exit": 1,
            "frontend_job_active_processes": 0,
            "stop_job_active_processes": 0,
        },
        "intervening": intervening(),
        "latest": latest(),
        "files": copy.deepcopy(recovery.FILES),
        "first_observation": observation,
        "last_observation": {**observation, "observed_mono_ns": 200},
        "completed_utc_ns": 300,
        "sources": {"synthetic.py": "f" * 64},
        "VM_mutations": 0,
        "VM_started": False,
        "native_boot_authorized": False,
    }


def receipt(value):
    files = {}
    for i, (name, state) in enumerate(value["files"].items()):
        row = {**state, "source_relative": "synthetic/source/" + name}
        if state["state"] == "file":
            row.update(
                source_identity={"device": 1, "inode": i + 1},
                backup_identity={"device": 1, "inode": i + 10},
                backup_relative="synthetic/backup/" + name,
            )
        else:
            row["backup_relative"] = None
        files[name] = row
    return {
        "format": records.RECOVERY_RECEIPT_FORMAT,
        "backup_id": "9" * 32,
        "role": "guard",
        "target_vm_uuid": recovery.GUARD_VM,
        "source_disk_uuid": recovery.GUARD_DISK,
        "source_machine_state": "aborted",
        "source_session_state": "Unlocked",
        "source_session_pid": 0,
        "recovery_context_sha256": recovery.context_sha256(value),
        "independent": True,
        "never_attach": True,
        "status": "aborted-backup-reported-not-boot-authority",
        "files": files,
    }


def grant(value, backup):
    return {
        "role": "guard",
        "target": {"vm_uuid": recovery.GUARD_VM, "disk_uuid": recovery.GUARD_DISK},
        "backup": records.binding(backup, digest(canonical(backup)), recovery=value),
        "disk_evidence": {"pre_boot_disk_sha256": value["files"]["disk"]["sha256"]},
    }


class ContextTests(unittest.TestCase):
    def test_historical_v2_cannot_omit_the_journal_hold(self):
        value = context()
        value["format"] = "mcli1-initial-aborted-context-v2"
        value.pop("latest")
        with self.assertRaises(Hold):
            recovery.checked(value)

    def test_latest_orphan_receipt_cannot_be_reclassified(self):
        for change in (
            {"frontend_ledger_state": "session-bound"},
            {"frontend_ledger_receipt_sha": "1" * 64},
            {"join_receipt_sha256": "1" * 64},
            {"family": []},
        ):
            value = context()
            value["latest"].update(change)
            with self.subTest(change=change), self.assertRaises(Hold):
                recovery.checked(value)

    def test_historical_v1_cannot_omit_the_newly_consumed_attempt(self):
        old = context()
        old["format"] = "mcli1-initial-aborted-context-v1"
        old.pop("intervening")
        with self.assertRaises(Hold):
            recovery.checked(old)

    def test_intervening_attempt_cannot_hide_a_successful_stop_or_live_family(self):
        for change in (
            {"stop_exit": 0},
            {"frontend_job_active_processes": 1},
            {"family": []},
            {"parent_context_sha256": "0" * 64},
            {"review_sha256": recovery.PRIOR_REVIEW},
        ):
            value = context()
            value["intervening"].update(change)
            with self.subTest(change=change), self.assertRaises(Hold):
                recovery.checked(value)

    def test_context_is_frozen_and_grants_no_execution_authority(self):
        original = context()
        frozen = recovery.checked(original)
        original["prior"]["processes"]["owner"]["pid"] = 999
        self.assertNotEqual(original, frozen)
        self.assertFalse(frozen["native_boot_authorized"])
        self.assertFalse(frozen["VM_started"])

    def test_other_roles_states_or_authority_claims_cannot_use_the_context(self):
        for changed in (
            {"role": "executor"},
            {"initial_state": "poweroff"},
            {"initial_state": "saved"},
            {"session_state": "Locked"},
            {"session_pid": True},
            {"VM_mutations": False},
            {"VM_started": True},
            {"native_boot_authorized": True},
            {"target_vm_uuid": "other"},
        ):
            with self.subTest(changed=changed), self.assertRaises(Hold):
                recovery.checked({**context(), **changed})

    def test_prior_attempt_process_and_cleanup_provenance_is_mandatory(self):
        for changed in (
            {"review_sha256": "a" * 64},
            {"owner_nonce": None},
            {"stop_exit": 0},
            {"frontend_job_active_processes": 1},
            {"stop_job_active_processes": False},
            {"artifacts": {}},
        ):
            value = context()
            value["prior"].update(changed)
            with self.subTest(changed=changed), self.assertRaises(Hold):
                recovery.checked(value)
        value = context()
        value["prior"]["processes"]["owner"]["pid"] = value["prior"]["processes"][
            "controller"
        ]["pid"]
        with self.assertRaises(Hold):
            recovery.checked(value)

    def test_drifted_or_reordered_capture_facts_are_refused(self):
        value = context()
        value["files"]["configuration"]["sha256"] = "0" * 64
        with self.assertRaises(Hold):
            recovery.checked(value)
        for changed in (
            {"observed_mono_ns": 100},
            {"machine_sha256": "0" * 64},
            {"session_sha256": "0" * 64},
        ):
            value = context()
            value["last_observation"].update(changed)
            with self.subTest(changed=changed), self.assertRaises(Hold):
                recovery.checked(value)


class BackupTests(unittest.TestCase):
    def test_v3_requires_explicit_exact_guard_context(self):
        value = context()
        backup = receipt(value)
        b = grant(value, backup)
        records.checked_receipt(backup, digest(canonical(backup)), b, recovery=value)
        self.assertNotIn("source_poweroff", backup)
        self.assertEqual(b["backup"]["source_machine_state"], "aborted")
        with self.assertRaises(Hold):
            records.checked_receipt(backup, digest(canonical(backup)), b)
        with self.assertRaises(Hold):
            records.binding(backup, digest(canonical(backup)))

    def test_poweroff_claim_or_context_change_cannot_relabel_v3(self):
        value = context()
        backup = receipt(value)
        b = grant(value, backup)
        for changed in (
            {"source_poweroff": True},
            {"source_session_pid": False},
            {"source_machine_state": "poweroff"},
            {"role": "executor"},
        ):
            altered = {**backup, **changed}
            with self.subTest(changed=changed), self.assertRaises(Hold):
                records.checked_receipt(
                    altered, digest(canonical(altered)), b, recovery=value
                )
        other = context()
        other["prior"]["owner_nonce"] = "8" * 32
        with self.assertRaises(Hold):
            records.checked_binding(b["backup"], recovery.GUARD_DISK, recovery=other)

    def test_historical_v2_is_not_implicitly_promoted_to_recovery(self):
        value = context()
        backup = receipt(value)
        for key in (
            "source_machine_state",
            "source_session_state",
            "source_session_pid",
            "recovery_context_sha256",
        ):
            backup.pop(key)
        backup.update(
            format=records.RECEIPT_FORMAT,
            status="stopped-backup-reported-not-boot-authority",
            source_poweroff=True,
        )
        normal = {
            **grant(value, receipt(value)),
            "backup": records.binding(backup, digest(canonical(backup))),
        }
        records.checked_receipt(backup, digest(canonical(backup)), normal)
        with self.assertRaises(Hold):
            records.checked_receipt(
                backup, digest(canonical(backup)), normal, recovery=value
            )
        with self.assertRaises(Hold):
            records.binding(backup, digest(canonical(backup)), recovery=value)

    def test_v3_does_not_lose_independent_file_or_target_checks(self):
        value = context()
        backup = receipt(value)
        b = grant(value, backup)
        backup["files"]["disk"]["backup_identity"] = backup["files"]["disk"][
            "source_identity"
        ]
        b["backup"] = records.binding(backup, digest(canonical(backup)), recovery=value)
        with self.assertRaises(Hold):
            records.checked_receipt(
                backup, digest(canonical(backup)), b, recovery=value
            )
        with self.assertRaises(Hold):
            records.checked_binding(
                b["backup"], "e832fc9c-23cc-40a8-8e66-fa0c624b8bd9", recovery=value
            )
