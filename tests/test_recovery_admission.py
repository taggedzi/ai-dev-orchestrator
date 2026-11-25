"""Guard-only recovery admission with the existing synthetic owner/family fixture."""

import copy
import time
import unittest
from unittest.mock import patch

from research.validation import frontend_start as start
from research.validation import startup_qualification as qualification
from research.validation.fixture import canonical
from research.validation.store import Hold
from research.validation.transfer_commands import digest
from tests import test_boot_preconditions as boot_tests
from tests import test_frontend_start as start_tests
from tests import test_recovery_records as records_tests


class RecoveryAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.case = start_tests.AdmissionTests(
            "test_exact_owner_gate_and_durable_possible_resume_precede_execution"
        )
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        b = self.case.grant["boot"]
        b["target"]["disk_uuid"] = start.recovery_host.model.GUARD_DISK
        b["disk_evidence"]["pre_boot_disk_sha256"] = start.recovery_host.model.FILES[
            "disk"
        ]["sha256"]
        self.context = records_tests.context()
        self.context["sources"] = dict(start.recovery_host.SOURCE_EPOCH)
        frame = self.snapshot()
        for key, stamp in (("first_observation", 100), ("last_observation", 200)):
            self.context[key].update(
                observed_mono_ns=stamp,
                machine_sha256=digest(frame["machine"]),
                medium_sha256=digest(frame["medium"]),
            )
        self.prior = patch.object(
            start.recovery_host,
            "prior_snapshot",
            return_value=copy.deepcopy(self.context["prior"]),
        ).start()
        patch.object(
            start.recovery_host,
            "intervening_snapshot",
            return_value=copy.deepcopy(self.context["intervening"]),
        ).start()
        patch.object(
            start.recovery_host,
            "latest_snapshot",
            return_value=copy.deepcopy(self.context["latest"]),
        ).start()
        backup = records_tests.receipt(self.context)
        backup_sha = digest(canonical(backup))
        b["backup"] = start.backup.records.binding(
            backup, backup_sha, recovery=self.context
        )
        preboot = {
            "format": "mcli1-recovery-preboot-disk-v1",
            "run_nonce": b["run_nonce"],
            "target_vm_uuid": b["target"]["vm_uuid"],
            "disk_uuid": b["target"]["disk_uuid"],
            "disk_sha256": b["disk_evidence"]["pre_boot_disk_sha256"],
            "state": "aborted",
            "backup_receipt_sha256": backup_sha,
            "recovery_context_sha256": start.recovery_host.model.context_sha256(
                self.context
            ),
        }
        preservation = self.case.receipts[2]
        b["disk_evidence"].update(
            pre_boot_receipt_sha256=digest(canonical(preboot)),
            source_preservation_receipt_sha256=digest(canonical(preservation)),
        )
        profile = start.recovery_host.profile(self.context, backup_sha)
        self.case.grant.update(
            format=start.RECOVERY_FORMAT,
            recovery=self.context,
            profile_receipt_sha256=digest(canonical(profile)),
        )
        self.case.receipts = [backup, preboot, preservation, profile]
        self.case.adapter.probe = self.snapshot
        self.case.addCleanup(self.case.adapter.close)

    def snapshot(self):
        frame = boot_tests.snapshot(self.case.grant["boot"])
        frame["machine"] = frame["machine"].replace(b'"poweroff"', b'"aborted"')
        frame["medium"] = frame["medium"].replace(b"locked write", b"created")
        return frame

    def test_explicit_recovery_wait_joins_only_a_later_locked_running_session(self):
        self.case.launch()
        adapter = self.case.adapter
        lease = dict(self.case.store.db.execute("SELECT * FROM lease").fetchone())
        started = adapter.started_mono
        result = adapter.observe(
            self.case.waiting_frame(
                states=["aborted", "starting", "running", "running"]
            )
        )
        self.assertEqual(result["status"], "awaiting-session-identity")
        self.assertIsNone(adapter.joined)
        self.assertFalse((self.case.root / "frontend.session.receipt.json").exists())
        self.assertEqual(
            adapter.observe(self.case.frame())["status"],
            "runtime-session-bound-not-guest-ready",
        )
        self.assertEqual(adapter.started_mono, started)
        self.assertEqual(
            dict(self.case.store.db.execute("SELECT * FROM lease").fetchone()), lease
        )

    def test_ordinary_grants_cannot_acquire_recovery_via_an_extra_field_or_v3_backup(
        self,
    ):
        self.case.grant["format"] = "mcli1-direct-frontend-start-v1"
        with self.assertRaises(Hold):
            self.case.launch()
        self.case.grant.pop("recovery")
        with self.assertRaises(Hold):
            self.case.launch()
        self.assertIsNone(self.case.adapter.family)
        self.assertFalse((self.case.root / "frontend.start.intent.json").exists())

    def test_default_boot_snapshot_stays_poweroff_only(self):
        with self.assertRaises(Hold):
            start.boot.stopped_snapshot(self.case.grant["boot"], self.snapshot())
        start.boot.stopped_snapshot(
            self.case.grant["boot"], self.snapshot(), recovery=self.context
        )

    def test_changed_prior_provenance_at_the_suspended_gate_prevents_resume(self):
        original = start_tests.FakeFamily.resume

        def resume(family, gate):
            self.prior.return_value = {
                **self.prior.return_value,
                "owner_nonce": "0" * 32,
            }
            original(family, gate)

        with (
            patch.object(start_tests.FakeFamily, "resume", resume),
            self.assertRaises(Hold),
        ):
            self.case.launch()
        self.assertFalse(self.case.adapter.family.resumed)
        self.assertIsNotNone(self.case.adapter.family.terminal)
        self.assertFalse((self.case.root / "frontend.resume.intent.json").exists())

    def test_new_admission_window_cannot_revive_the_original_expired_lease(self):
        expired = time.monotonic_ns() - 1
        self.case.store.db.execute("UPDATE lease SET expires_mono_ns=?", (expired,))
        with self.assertRaises(Hold):
            self.case.launch()
        self.assertIsNone(self.case.adapter.family)
        self.assertEqual(
            self.case.store.db.execute("SELECT expires_mono_ns FROM lease").fetchone()[
                0
            ],
            expired,
        )

    def test_abort_after_session_join_is_held_not_successful_shutdown(self):
        self.case.launch()
        self.case.adapter.observe(self.case.frame())
        with self.assertRaises(Hold):
            self.case.adapter.observe(self.case.frame(state="aborted"))
        self.assertFalse(self.case.adapter.terminal["original_stop_accepted"])
        self.assertFalse(self.case.adapter.terminal["VM_poweroff_proven"])

    def test_controller_packet_preserves_typed_recovery_and_a_fresh_bounded_window(
        self,
    ):
        rows = {}
        for name, value in (
            ("backup", self.case.receipts[0]),
            ("profile", self.case.receipts[3]),
            ("recovery", self.context),
            ("preparation", {}),
        ):
            path = self.case.root / ("capture-" + name + ".json")
            raw = canonical(value)
            path.write_bytes(raw)
            rows[name] = {"path": str(path), "sha256": digest(raw)}

        def measure(b, _raw, *, recovery):
            self.assertEqual(recovery, self.context)
            preboot = {**self.case.receipts[1], "run_nonce": b["run_nonce"]}
            source = {**self.case.receipts[2], "run_nonce": b["run_nonce"]}
            b["disk_evidence"].update(
                pre_boot_disk_sha256=recovery["files"]["disk"]["sha256"],
                pre_boot_receipt_sha256=digest(canonical(preboot)),
                source_preservation_receipt_sha256=digest(canonical(source)),
            )
            return preboot, source

        pending = type("Pending", (), {"root": self.case.root})()
        with patch.object(qualification, "measured_receipts", measure):
            payload = qualification.controller_input(
                pending,
                {"format": qualification.RECOVERY_REVIEW_FORMAT, "inputs": rows},
                "a" * 64,
                {"reference": "test:Python-only"},
            )
        grant = payload["grant"]
        self.assertEqual(grant["format"], start.RECOVERY_FORMAT)
        self.assertEqual(grant["recovery"], self.context)
        self.assertEqual(
            grant["boot"]["window"]["expires_mono_ns"]
            - grant["boot"]["window"]["issued_mono_ns"],
            15 * 10**9,
        )
        start.checked(canonical(grant), digest(canonical(grant)))
        start.host.receipt_pins(
            grant["boot"],
            *map(canonical, payload["receipts"][:3]),
            recovery=self.context,
        )
        with self.assertRaises(Hold):
            start.boot.checked(
                canonical(grant["boot"]), digest(canonical(grant["boot"]))
            )
