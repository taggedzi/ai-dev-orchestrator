"""Decision 0007 preparation. No test boots a VM or writes the production ledger."""

import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing, contextmanager
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from research.validation import held_successor as successor
from research.validation import offline_startup as offline
from research.validation import startup_qualification as qualification
from research.validation.store import Hold
from research.validation.transfer_commands import digest


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@contextmanager
def plain_lock(path):
    with Path(path).open("rb") as stream:
        yield stream


def profile(**changes):
    record = {
        "state": "aborted",
        "session_state": "Unlocked",
        "session_pid": 0,
        "nics_disabled": True,
        "enabled_transports": [],
        "saved_state": False,
        "hardware_uuid": successor.GUARD_VM,
        "machine_sha256": "ab" * 32,
        "medium_sha256": "cd" * 32,
    }
    record.update(changes)
    return record


def poweroff_pair():
    base = profile(state="poweroff")
    return [
        {**base, "observed_mono_ns": 10},
        {**base, "observed_mono_ns": 20},
    ]


class PreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ledger_sha = file_sha(successor.PRODUCTION_LEDGER)
        cls.owner_sha = file_sha(successor.PRODUCTION_OWNER)
        cls.ledger_wal = successor.PRODUCTION_LEDGER.with_name(
            successor.PRODUCTION_LEDGER.name + "-wal"
        ).stat().st_size

    @classmethod
    def tearDownClass(cls):
        if file_sha(successor.PRODUCTION_LEDGER) != cls.ledger_sha:
            raise AssertionError("production admission ledger changed")
        if file_sha(successor.PRODUCTION_OWNER) != cls.owner_sha:
            raise AssertionError("original owner journal changed")
        if (
            successor.PRODUCTION_LEDGER.with_name(
                successor.PRODUCTION_LEDGER.name + "-wal"
            ).stat().st_size
            != cls.ledger_wal
        ):
            raise AssertionError("production admission wal changed")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.addCleanup(patch.stopall)
        patch.object(
            qualification.start.backup,
            "safe",
            lambda path: Path(path).resolve(),
        ).start()
        self.path = self.root / "scratch.sqlite"
        successor.seed_held(self.path)
        successor.migrate(self.path)
        self.ledger = successor.ScratchLedger(self.path)
        self.addCleanup(self.ledger.close)

    def successor_row(self):
        ident = uuid4().hex
        return {
            "review_id": ident,
            "review_sha": digest(ident.encode()),
            "approval_sha": digest((ident + "approval").encode()),
            "target": successor.GUARD_VM,
            "output": ".local/validation/held-successor-run-" + ident,
        }

    def transfer(self, row=None, **kwargs):
        return successor.transfer(
            self.ledger,
            self.successor_row() if row is None else row,
            history=successor.history_sha(),
            **kwargs,
        )

    def test_provenance_binds_the_fault_and_refuses_aborted_success(self):
        value = successor.load_provenance()
        self.assertEqual(value["initial_state"], "aborted")
        self.assertIsNone(value["stop_receipt"])
        self.assertFalse(value["old_stop_accepted"])
        self.assertFalse(value["history"]["claims_about_failed_stop"])
        self.assertEqual(value["authority"]["stop_state"], "possible-send")
        changed = successor.prototype_context()
        changed["old_stop_accepted"] = True
        with self.assertRaises(Hold):
            successor.checked(changed)
        historical = successor.prototype_context()
        historical["format"] = "mcli1-initial-aborted-context-v3"
        with self.assertRaisesRegex(Hold, "historical recovery context"):
            successor.checked(historical)

    def test_review_is_one_aborted_case_without_boot_authority(self):
        review = successor.checked_review(
            successor.draft_review(
                successor.prototype_context(),
                ".local/validation/held-successor-review-test",
            )
        )
        self.assertEqual(review["initial_state"], "aborted")
        self.assertFalse(review["native_boot_authorized"])
        self.assertFalse(review["proposed_transfer"]["settles_old_stop"])
        review["case"] = "controller-loss"
        with self.assertRaises(Hold):
            successor.checked_review(review)
        self.assertEqual(
            successor.startup_progress(["aborted", "starting", "running"]),
            [0, 1, 2],
        )
        with self.assertRaises(Hold):
            successor.startup_progress(["aborted", "poweroff"])

    def test_transfer_keeps_the_ancestor_held_and_moves_only_exclusion(self):
        row = self.successor_row()
        started = []
        token = self.transfer(row)
        successor.allocate(self.ledger, token, lambda: started.append("python"))
        self.assertEqual(started, ["python"])
        self.assertFalse(token["native_boot_authorized"])
        prior = successor._row(self.ledger, successor.HELD_ADMISSION["review_id"])
        current = successor._row(self.ledger, row["review_id"])
        self.assertEqual((prior["state"], prior["active"], prior["stop_receipt_sha"]), ("held", 0, None))
        self.assertEqual((current["state"], current["active"]), ("consumed", 1))
        self.ledger.close()
        with closing(offline.Admissions(self.path)) as admissions:
            with self.assertRaisesRegex(Hold, "ancestor"):
                admissions.finish(prior["review_id"], settled=True)
            admissions.finish(row["review_id"], settled=False, release_unarmed=True)
            retained = admissions.row(row["review_id"])
            ancestor = admissions.row(prior["review_id"])
        self.assertEqual((retained["state"], retained["active"]), ("held", 1))
        self.assertEqual((ancestor["state"], ancestor["active"]), ("held", 0))

    def test_caller_bool_cannot_release_an_inherited_hold(self):
        row = self.successor_row()
        self.transfer(row)
        self.ledger.close()
        with closing(offline.Admissions(self.path)) as admissions:
            with self.assertRaisesRegex(Hold, "independent stop proof"):
                admissions.finish(row["review_id"], settled=True)
            retained = admissions.row(row["review_id"])
        self.assertEqual((retained["state"], retained["active"]), ("held", 1))

    def test_ordinary_unarmed_release_does_not_apply_to_a_successor(self):
        path = self.root / "ordinary.sqlite"
        with closing(offline.Admissions(path)) as admissions:
            admissions.db.execute(
                "INSERT INTO admissions VALUES(?,?,?,?,?,'consumed',0,1,NULL,NULL)",
                ("a" * 32, "b" * 64, "c" * 64, successor.GUARD_VM, "out"),
            )
            admissions.finish("a" * 32, settled=False, release_unarmed=True)
            row = admissions.row("a" * 32)
        self.assertEqual((row["state"], row["active"]), ("held", 0))

    def test_competing_successors_leave_one_active_reservation(self):
        first, second = self.successor_row(), self.successor_row()
        gate = __import__("threading").Barrier(2)
        results, errors = [], []

        def attempt(row):
            ledger = successor.ScratchLedger(self.path)
            try:
                gate.wait(2)
                results.append(
                    successor.transfer(ledger, row, history=successor.history_sha())
                )
            except Hold as error:
                errors.append(str(error))
            finally:
                ledger.close()

        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=2) as pool:
            pool.map(attempt, (first, second))
        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 1)
        self.ledger.close()
        seen = successor.inspect(self.path, successor.HELD_ADMISSION["review_id"])
        self.assertTrue(seen["transfer_committed"])
        self.assertFalse(seen["dispatch_authorized"])
        self.assertFalse(seen["allocation_performed"])
        self.assertEqual(seen["prior_state"], "held")
        self.assertIsNone(seen["prior_stop_receipt"])

    def test_replay_fork_cycle_stale_history_and_changed_row_refuse(self):
        first = self.successor_row()
        self.transfer(first)
        with self.assertRaisesRegex(Hold, "fork"):
            self.transfer(self.successor_row())
        with self.assertRaisesRegex(Hold, "fork"):
            self.transfer(first)
        current = successor._row(self.ledger, first["review_id"])
        with self.assertRaisesRegex(Hold, "cycle"):
            successor.transfer(
                self.ledger,
                {
                    **successor.HELD_ADMISSION,
                    "review_sha": "d" * 64,
                    "approval_sha": "e" * 64,
                    "output": ".local/validation/held-successor-cycle",
                },
                expected_prior=current,
                history=successor.history_sha(),
            )
        changed_path = self.root / "changed-row.sqlite"
        successor.seed_held(changed_path)
        successor.migrate(changed_path)
        changed = successor.ScratchLedger(changed_path)
        try:
            changed.db.execute(
                "UPDATE admissions SET binding_sha=? WHERE review_id=?",
                ("f" * 64, successor.HELD_ADMISSION["review_id"]),
            )
            with self.assertRaisesRegex(Hold, "prior admission row changed"):
                successor.transfer(
                    changed,
                    self.successor_row(),
                    history=successor.history_sha(),
                )
        finally:
            changed.close()
        with self.assertRaisesRegex(Hold, "stale"):
            successor.transfer(
                self.ledger,
                self.successor_row(),
                history="ab" * 32,
            )
        with self.assertRaisesRegex(Hold, "inactive"):
            successor.transfer(
                self.ledger,
                self.successor_row(),
                authority_active=1,
                history=successor.history_sha(),
            )

    def test_live_or_inaccessible_processes_and_revocation_hold(self):
        with self.assertRaisesRegex(Hold, "still live"):
            successor.require_retired([{"pid": 1}], lambda _record: False)
        with self.assertRaisesRegex(Hold, "inaccessible"):
            successor.require_retired(
                [{"pid": 1}],
                lambda _record: (_ for _ in ()).throw(Hold("process retirement could not be observed")),
            )
        row = self.successor_row()
        self.transfer(row)
        self.ledger.db.execute(
            "UPDATE admissions SET revoked=1 WHERE review_id=?",
            (row["review_id"],),
        )
        with self.assertRaisesRegex(Hold, "revoked"):
            successor.allocate(
                self.ledger,
                {
                    "allocation_allowed": True,
                    "dispatch_authorized": False,
                    "native_boot_authorized": False,
                    "successor_id": row["review_id"],
                },
                lambda: (_ for _ in ()).throw(AssertionError("allocated")),
            )

    def test_interrupted_migration_is_not_repaired(self):
        path = self.root / "interrupted.sqlite"
        successor.seed_held(path)

        def interrupt(_ledger):
            raise RuntimeError("migration interrupted")

        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            successor.migrate(path, before_ready=interrupt)
        with self.assertRaisesRegex(Hold, "without repair"):
            successor.migrate(path)
        ledger = successor.ScratchLedger(path)
        self.addCleanup(ledger.close)
        with self.assertRaisesRegex(Hold, "incomplete"):
            successor.transfer(
                ledger, self.successor_row(), history=successor.history_sha()
            )

    def test_lost_commit_acknowledgement_can_be_inspected_but_not_replayed(self):
        path = self.root / "ack.sqlite"
        successor.seed_held(path)
        successor.migrate(path)
        ledger = successor.ScratchLedger(path)
        connection = ledger.db

        class LostAck:
            def execute(self, sql, *args):
                result = connection.execute(sql, *args)
                if sql == "COMMIT":
                    raise OSError("lost commit acknowledgement")
                return result

            @property
            def in_transaction(self):
                return connection.in_transaction

        ledger.db = LostAck()
        allocated = []
        with self.assertRaisesRegex(OSError, "lost commit"):
            token = successor.transfer(
                ledger, self.successor_row(), history=successor.history_sha()
            )
            successor.allocate(ledger, token, lambda: allocated.append("process"))
        self.assertEqual(allocated, [])
        ledger.db = connection
        seen = successor.inspect(path, successor.HELD_ADMISSION["review_id"])
        self.assertTrue(seen["transfer_committed"])
        self.assertFalse(seen["dispatch_authorized"])
        self.assertFalse(seen["native_boot_authorized"])
        with self.assertRaises(Hold):
            successor.transfer(
                ledger, self.successor_row(), history=successor.history_sha()
            )
        ledger.close()

    def test_production_paths_and_snapshot_do_not_transfer_the_real_reservation(self):
        with self.assertRaisesRegex(Hold, "production admission ledger"):
            successor.migrate(successor.PRODUCTION_LEDGER)
        with self.assertRaisesRegex(Hold, "original owner journal"):
            successor.migrate(successor.PRODUCTION_OWNER)
        snapshot = self.root / "snapshot.sqlite"
        recorded = successor.snapshot_ledger(snapshot)
        self.assertFalse(recorded["transferred"])
        self.assertEqual(file_sha(successor.PRODUCTION_LEDGER), self.ledger_sha)
        successor.migrate(snapshot)
        copied = successor.ScratchLedger(snapshot)
        self.addCleanup(copied.close)
        token = successor.transfer(
            copied, self.successor_row(), history=successor.history_sha()
        )
        self.assertFalse(token["native_boot_authorized"])
        prior = successor._row(copied, successor.HELD_ADMISSION["review_id"])
        self.assertEqual((prior["state"], prior["active"], prior["stop_receipt_sha"]), ("held", 0, None))
        db = sqlite3.connect(
            successor.immutable_uri(successor.PRODUCTION_LEDGER), uri=True
        )
        try:
            real = db.execute(
                "SELECT state, active FROM admissions WHERE review_id=?",
                (successor.HELD_ADMISSION["review_id"],),
            ).fetchone()
        finally:
            db.close()
        self.assertEqual(tuple(real), ("held", 1))
        self.assertEqual(file_sha(successor.PRODUCTION_LEDGER), self.ledger_sha)

    def test_synthetic_capture_records_aborted_and_refuses_drift(self):
        source = self.root / "sources"
        source.mkdir()
        payloads = {
            "disk": b"vdi" + b"\0" * 520,
            "configuration": (
                '<?xml version="1.0"?>'
                '<VirtualBox xmlns="http://www.virtualbox.org/" version="1.19-windows">'
                f'<Machine uuid="{{{successor.GUARD_VM}}}" aborted="true">'
                "<MediaRegistry><HardDisks>"
                f'<HardDisk uuid="{{{successor.GUARD_DISK}}}" location="disk.vdi" format="VDI" type="Normal"/>'
                "</HardDisks></MediaRegistry></Machine></VirtualBox>"
            ).encode(),
            "nvram": b"nvram",
        }
        for name, raw in payloads.items():
            (source / name).write_bytes(raw)
        expected = {
            name: {"state": "file", "bytes": len(raw), "sha256": digest(raw)}
            for name, raw in payloads.items()
        }
        calls = {"count": 0}

        def observe(_role):
            calls["count"] += 1
            machine = "ab" * 32 if calls["count"] == 1 else "ef" * 32
            return profile(machine_sha256=machine)

        output = self.root / "capture-drift"
        with self.assertRaisesRegex(Hold, "drifted"):
            successor.capture(
                output,
                sources={name: source / name for name in payloads},
                expected=expected,
                observe=observe,
                root_factory=lambda path: path.mkdir() or path,
                locker=plain_lock,
            )
        self.assertFalse((output / "preparation.receipt.json").exists())
        self.assertTrue((output / "intent.json").exists())

        def stable(_role):
            return profile()

        output = self.root / "capture-ok"
        result = successor.capture(
            output,
            sources={name: source / name for name in payloads},
            expected=expected,
            observe=stable,
            root_factory=lambda path: path.mkdir() or path,
            locker=plain_lock,
        )
        self.assertEqual(result["initial_state"], "aborted")
        self.assertFalse(result["registered"])
        self.assertFalse(result["old_stop_accepted"])
        profile_text = json.loads((output / "profile.json").read_text(encoding="utf-8"))
        self.assertEqual(profile_text["initial_state"], "aborted")
        self.assertEqual(
            file_sha(output / "backup" / "disk.vdi"),
            expected["disk"]["sha256"],
        )
        missing = self.root / "capture-missing"
        partial = dict(expected)
        sources = {name: source / name for name in payloads}
        absent = self.root / "missing-nvram"
        sources["nvram"] = absent
        with self.assertRaisesRegex(Hold, "missing"):
            successor.capture(
                missing,
                sources=sources,
                expected=partial,
                observe=stable,
                root_factory=lambda path: path.mkdir() or path,
                locker=plain_lock,
            )
        self.assertFalse((missing / "preparation.receipt.json").exists())
        enabled = self.root / "capture-transport"

        def enabled_transport(_role):
            return profile(enabled_transports=["nat"])

        with self.assertRaisesRegex(Hold, "transport"):
            successor.capture(
                enabled,
                sources={name: source / name for name in payloads},
                expected=expected,
                observe=enabled_transport,
                root_factory=lambda path: path.mkdir() or path,
                locker=plain_lock,
            )

    def test_python_surrogate_stop_requires_independent_poweroff_proof(self):
        row = self.successor_row()
        image = b"unarmed-successor-image"
        token = self.transfer(row)
        self.assertTrue(token["allocation_allowed"])
        session = successor.open_surrogate(
            self.root / "surrogate-ok",
            row["review_id"],
            stop_exit=0,
            observations=poweroff_pair(),
        )
        try:
            successor.bind_lease(session)
            with self.assertRaisesRegex(Hold, "drifted"):
                successor.resume_frontend(self.ledger, session, digest(image), b"changed")
            self.assertFalse(session.resumed)
            successor.resume_frontend(self.ledger, session, digest(image), image)
            facts = successor.run_stop(session)
            self.assertEqual(facts["job_active_processes"], 0)
            self.assertTrue(
                all("vbox" not in " ".join(command).lower() for command in session.commands)
            )
            proof = successor.accept_independent_stop(self.ledger, session)
            self.assertFalse(proof["old_stop_accepted"])
        finally:
            session.close()
        self.ledger.close()
        with closing(offline.Admissions(self.path)) as admissions:
            admissions.finish(row["review_id"], settled=True)
            current = admissions.row(row["review_id"])
            prior = admissions.row(successor.HELD_ADMISSION["review_id"])
        self.assertEqual((current["state"], current["active"]), ("finished", 0))
        self.assertEqual((prior["state"], prior["active"], prior["stop_receipt_sha"]), ("held", 0, None))

        failed_path = self.root / "failed.sqlite"
        successor.seed_held(failed_path)
        successor.migrate(failed_path)
        failed = self.successor_row()
        ledger = successor.ScratchLedger(failed_path)
        successor.transfer(ledger, failed, history=successor.history_sha())
        failed_session = successor.open_surrogate(
            self.root / "surrogate-fail",
            failed["review_id"],
            stop_exit=1,
            observations=poweroff_pair(),
        )
        try:
            successor.bind_lease(failed_session)
            successor.resume_frontend(ledger, failed_session, digest(image), image)
            successor.run_stop(failed_session)
            with self.assertRaisesRegex(Hold, "stop failed"):
                successor.accept_independent_stop(ledger, failed_session)
        finally:
            failed_session.close()
            ledger.close()
        with closing(offline.Admissions(failed_path)) as admissions:
            with self.assertRaisesRegex(Hold, "independent stop proof"):
                admissions.finish(failed["review_id"], settled=True)
            retained = admissions.row(failed["review_id"])
        self.assertEqual((retained["state"], retained["active"]), ("held", 1))
        aborted = poweroff_pair()
        aborted[0]["state"] = "aborted"
        with self.assertRaisesRegex(Hold, "not independently powered off"):
            successor.require_poweroff(aborted)

    def test_revocation_before_and_after_arming_retains_exclusion(self):
        image = b"unarmed-successor-image"
        early = self.successor_row()
        self.transfer(early)
        session = successor.open_surrogate(
            self.root / "revoke-before",
            early["review_id"],
            stop_exit=0,
            observations=poweroff_pair(),
        )
        try:
            successor.bind_lease(session)
            self.ledger.db.execute(
                "UPDATE admissions SET revoked=1 WHERE review_id=?",
                (early["review_id"],),
            )
            with self.assertRaisesRegex(Hold, "revoked"):
                successor.resume_frontend(self.ledger, session, digest(image), image)
            self.assertFalse(session.resumed)
        finally:
            session.close()
        self.ledger.close()
        with closing(offline.Admissions(self.path)) as admissions:
            admissions.finish(early["review_id"], settled=False, release_unarmed=True)
            retained = admissions.row(early["review_id"])
        self.assertEqual((retained["state"], retained["active"]), ("held", 1))

        late_path = self.root / "late.sqlite"
        successor.seed_held(late_path)
        successor.migrate(late_path)
        late = self.successor_row()
        ledger = successor.ScratchLedger(late_path)
        successor.transfer(ledger, late, history=successor.history_sha())
        session = successor.open_surrogate(
            self.root / "revoke-after",
            late["review_id"],
            stop_exit=0,
            observations=poweroff_pair(),
        )
        try:
            successor.bind_lease(session)
            successor.resume_frontend(ledger, session, digest(image), image)
            self.ledger_is_open = ledger
            ledger.db.execute(
                "UPDATE admissions SET revoked=1 WHERE review_id=?",
                (late["review_id"],),
            )
            successor.run_stop(session)
            with self.assertRaisesRegex(Hold, "revoked"):
                successor.accept_independent_stop(ledger, session)
        finally:
            session.close()
            ledger.close()
        with closing(offline.Admissions(late_path)) as admissions:
            admissions.finish(late["review_id"], settled=False, release_unarmed=True)
            retained = admissions.row(late["review_id"])
        self.assertEqual((retained["state"], retained["active"]), ("held", 1))


class ProductionUntouchedTests(unittest.TestCase):
    def test_module_refuses_to_open_the_real_ledger_for_transfer(self):
        before = file_sha(successor.PRODUCTION_LEDGER)
        with self.assertRaises(Hold):
            successor.ScratchLedger(successor.PRODUCTION_LEDGER)
        self.assertEqual(file_sha(successor.PRODUCTION_LEDGER), before)
        self.assertEqual(before, successor.PRODUCTION_LEDGER_SHA256)
        self.assertEqual(file_sha(successor.PRODUCTION_OWNER), successor.PRODUCTION_OWNER_SHA256)


if __name__ == "__main__":
    unittest.main()
