"""Real SQLite locks with synthetic VM/family facts; no native VM commands."""

import json
import sqlite3
import threading
import time
import unittest
from contextlib import closing
from unittest.mock import patch

from research.validation import frontend_start as start
from research.validation.store import Hold
from tests import test_frontend_start as start_tests


def busy(code=sqlite3.SQLITE_BUSY):
    error = sqlite3.OperationalError("injected journal failure")
    if code is not None:
        error.sqlite_errorcode = code
    return error


class ConnectionFault:
    def __init__(self, db, statement, *, after=False, code=sqlite3.SQLITE_BUSY):
        self.db, self.statement, self.after, self.code = db, statement, after, code
        self.injected = 0

    def execute(self, statement, *args):
        if statement == self.statement and self.injected == 0:
            self.injected += 1
            if self.after:
                self.db.execute(statement, *args)
            raise busy(self.code)
        return self.db.execute(statement, *args)

    def __getattr__(self, name):
        return getattr(self.db, name)


class StartupTraceTests(unittest.TestCase):
    """Keep exact startup phases when SQLite cannot settle; never replay start."""

    def setUp(self):
        self.case = start_tests.AdmissionTests(
            "test_exact_owner_gate_and_durable_possible_resume_precede_execution"
        )
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def test_start_begin_busy_is_traced_before_any_frontend_resume(self):
        self.case.store.db = ConnectionFault(self.case.store.db, "BEGIN IMMEDIATE")
        with self.assertRaises(sqlite3.OperationalError):
            self.case.launch()
        events = self.case.adapter.journal_trace
        failed = [e for e in events if e["stage"] == "start-begin-failed"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["phase"], "start-intent")
        self.assertEqual(failed[0]["sqlite_errorcode"], sqlite3.SQLITE_BUSY)
        self.assertFalse(failed[0]["retryable"])
        self.assertIsNone(self.case.adapter.family)

    def test_real_writer_at_possible_resume_holds_without_resuming_or_replay(self):
        original_resume = start_tests.FakeFamily.resume
        attempts = []

        def resume_while_locked(family, gate):
            with closing(
                sqlite3.connect(self.case.root / "owner.sqlite", isolation_level=None)
            ) as writer:
                writer.execute("BEGIN IMMEDIATE")
                try:
                    attempts.append("possible-resume")
                    return original_resume(family, gate)
                finally:
                    writer.execute("ROLLBACK")

        with (
            patch.object(start_tests.FakeFamily, "resume", resume_while_locked),
            self.assertRaises(sqlite3.OperationalError) as caught,
        ):
            self.case.launch()
        self.assertEqual(caught.exception.sqlite_errorcode, sqlite3.SQLITE_BUSY)
        self.assertEqual(attempts, ["possible-resume"])
        self.assertFalse(self.case.store.db.in_transaction)
        self.assertFalse(self.case.adapter.family.resumed)
        self.assertIsNotNone(self.case.adapter.family.terminal)
        row = self.case.store.db.execute("SELECT * FROM frontend_start").fetchone()
        self.assertEqual(row["state"], "intent")
        self.assertIsNone(row["process"])
        events = self.case.adapter.journal_trace
        self.assertEqual(
            [(e["phase"], e["stage"]) for e in events],
            [
                ("start-intent", "start-committed"),
                ("possible-resume", "start-begin-failed"),
            ],
        )
        self.assertFalse(events[-1]["transaction_open"])
        self.assertFalse(events[-1]["retryable"])
        self.assertEqual(
            self.case.store.db.execute("SELECT active FROM authority").fetchone()[0],
            0,
        )
        with self.assertRaises(Hold):
            self.case.launch()
        self.assertEqual(attempts, ["possible-resume"])

    def fault_commit(self, number):
        original = self.case.store.db

        class LostCommit:
            count = 0

            def execute(self, statement, *args):
                result = original.execute(statement, *args)
                if statement == "COMMIT":
                    self.count += 1
                    if self.count == number:
                        raise busy()
                return result

            def __getattr__(self, name):
                return getattr(original, name)

        self.case.store.db = LostCommit()
        with self.assertRaises(sqlite3.OperationalError):
            self.case.launch()
        return [
            e
            for e in self.case.adapter.journal_trace
            if e["stage"] == "start-commit-failed"
        ]

    def test_lost_possible_resume_commit_is_traced_without_resuming(self):
        failed = self.fault_commit(2)
        self.assertEqual(failed[0]["phase"], "possible-resume")
        self.assertFalse(failed[0]["retryable"])
        self.assertIsNotNone(self.case.adapter.family.terminal)
        with self.assertRaises(Hold):
            self.case.launch()

    def test_lost_resume_ack_commit_is_traced_without_a_second_start(self):
        failed = self.fault_commit(3)
        self.assertEqual(failed[0]["phase"], "resume-ack")
        self.assertFalse(failed[0]["retryable"])
        self.assertIsNotNone(self.case.adapter.family.terminal)
        with self.assertRaises(Hold):
            self.case.launch()


class ControllerJournalTests(unittest.TestCase):
    def setUp(self):
        self.case = start_tests.AdmissionTests(
            "test_exact_owner_gate_and_durable_possible_resume_precede_execution"
        )
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.case.launch()
        self.adapter, self.store, self.root = (
            self.case.adapter,
            self.case.store,
            self.case.root,
        )
        self.store.db.execute("PRAGMA busy_timeout=50")

    def writer(self):
        db = sqlite3.connect(
            self.root / "owner.sqlite", isolation_level=None, check_same_thread=False
        )
        db.execute("BEGIN IMMEDIATE")
        self.addCleanup(db.close)
        return db

    def release(self, writer, *, revoke=False):
        def run():
            time.sleep(0.25)
            if revoke:
                writer.execute("UPDATE authority SET active=0,generation=generation+1")
                writer.execute("COMMIT")
            else:
                writer.execute("ROLLBACK")

        thread = threading.Thread(target=run)
        thread.start()
        self.addCleanup(thread.join)

    def row(self):
        return self.store.db.execute("SELECT * FROM frontend_start").fetchone()

    def trace(self, stage):
        return [e for e in self.adapter.journal_trace if e["stage"] == stage]

    def assert_unaccepted(self):
        self.assertIsNone(self.adapter.joined)
        self.assertFalse((self.root / "frontend.session.receipt.json").exists())
        self.assertIsNotNone(self.adapter.family.terminal)

    def test_short_real_writer_wait_commits_once_without_renewing_authority(self):
        lease = dict(self.store.db.execute("SELECT * FROM lease").fetchone())
        self.store.db.execute("PRAGMA busy_timeout=700")
        writer = self.writer()
        self.release(writer)
        result = self.adapter.observe(self.case.frame())
        self.assertEqual(result["status"], "runtime-session-bound-not-guest-ready")
        self.assertEqual(self.row()["state"], "session-bound")
        self.assertTrue((self.root / "frontend.session.receipt.json").exists())
        self.assertEqual(len(self.trace("committed")), 1)
        self.assertGreater(len(self.trace("begin-failed")), 0)
        self.assertEqual(
            self.store.db.execute(
                "SELECT COUNT(*) FROM audit WHERE kind='frontend-session-bound'"
            ).fetchone()[0],
            1,
        )
        self.assertEqual(
            dict(self.store.db.execute("SELECT * FROM lease").fetchone()), lease
        )
        self.assertEqual(
            self.store.db.execute("PRAGMA busy_timeout").fetchone()[0], 700
        )
        self.assertFalse(self.store.db.in_transaction)

    def test_long_writer_lock_holds_without_receipt_or_memory_join(self):
        writer = self.writer()
        began = time.monotonic()
        try:
            with self.assertRaises((Hold, sqlite3.OperationalError)):
                self.adapter.observe(self.case.frame())
        finally:
            writer.execute("ROLLBACK")
        self.assertLess(time.monotonic() - began, 2.5)
        self.assert_unaccepted()
        self.assertEqual(self.row()["state"], "resumed")
        self.assertFalse(self.store.db.in_transaction)
        self.assertLessEqual(len(self.trace("begin-failed")), 16)

    def test_revocation_during_writer_wait_cannot_commit_a_join(self):
        writer = self.writer()
        self.release(writer, revoke=True)
        with self.assertRaises(Hold):
            self.adapter.observe(self.case.frame())
        self.assert_unaccepted()
        self.assertEqual(self.row()["state"], "resumed")

    def test_startup_expiry_during_wait_cannot_enter_the_body(self):
        writer = self.writer()

        def expire(_seconds):
            self.adapter.started_mono -= start.STARTUP_NS

        try:
            with (
                patch.object(start.time, "sleep", side_effect=expire),
                self.assertRaisesRegex(Hold, "startup timed out"),
            ):
                self.adapter.observe(self.case.frame())
        finally:
            writer.execute("ROLLBACK")
        self.assert_unaccepted()
        self.assertEqual(self.row()["state"], "resumed")

    def test_body_busy_rolls_back_without_repeating_work(self):
        original = self.store._event
        calls = []

        def event(kind, payload):
            if kind == "frontend-session-bound":
                calls.append(1)
                raise busy()
            return original(kind, payload)

        with (
            patch.object(self.store, "_event", side_effect=event),
            self.assertRaises(sqlite3.OperationalError),
        ):
            self.adapter.observe(self.case.frame())
        self.assertEqual(calls, [1])
        self.assert_unaccepted()
        self.assertEqual(self.row()["state"], "resumed")
        self.assertEqual(self.trace("body-failed")[0]["rollback"], "rolled-back")

    def commit_fault(self, *, after):
        db = self.store.db
        fault = ConnectionFault(db, "COMMIT", after=after)
        self.store.db = fault
        try:
            with self.assertRaises(sqlite3.OperationalError):
                self.adapter.observe(self.case.frame())
        finally:
            self.store.db = db
        self.assertEqual(fault.injected, 1)
        self.assert_unaccepted()
        self.assertEqual(self.row()["state"], "session-bound" if after else "resumed")
        self.assertFalse(self.trace("commit-failed")[0]["retryable"])
        self.assertFalse(self.store.db.in_transaction)

    def test_commit_busy_is_rolled_back_and_never_replayed(self):
        self.commit_fault(after=False)

    def test_lost_commit_acknowledgement_is_never_replayed_or_published(self):
        self.commit_fault(after=True)

    def begin_fault(self, code, *, after=False):
        db = self.store.db
        fault = ConnectionFault(db, "BEGIN IMMEDIATE", code=code, after=after)
        self.store.db = fault
        try:
            with self.assertRaises(sqlite3.OperationalError):
                self.adapter.observe(self.case.frame())
        finally:
            self.store.db = db
        self.assert_unaccepted()
        self.assertEqual(self.row()["state"], "resumed")
        self.assertEqual(len(self.trace("begin-failed")), 1)
        self.assertFalse(self.trace("begin-failed")[0]["retryable"])
        self.assertFalse(db.in_transaction)

    def test_locked_is_not_treated_as_plain_busy(self):
        self.begin_fault(sqlite3.SQLITE_LOCKED)

    def test_extended_busy_is_not_treated_as_plain_busy(self):
        self.begin_fault(sqlite3.SQLITE_BUSY_SNAPSHOT)

    def test_missing_error_code_is_not_retryable(self):
        self.begin_fault(None)

    def test_unacknowledged_begin_with_open_transaction_holds_after_rollback(self):
        self.begin_fault(sqlite3.SQLITE_BUSY, after=True)
        self.assertEqual(self.trace("begin-rollback")[0]["rollback"], "rolled-back")

    def test_receipt_publication_failure_after_commit_still_holds(self):
        publish = start.owner.publish

        def fail(path, raw):
            if path.name == "frontend.session.receipt.json":
                raise OSError("injected receipt write failure")
            return publish(path, raw)

        with (
            patch.object(start.owner, "publish", side_effect=fail),
            self.assertRaises(OSError),
        ):
            self.adapter.observe(self.case.frame())
        self.assert_unaccepted()
        self.assertEqual(self.row()["state"], "session-bound")
        self.assertEqual(len(self.trace("receipt-failed")), 1)
        artifact = json.loads((self.root / "frontend.journal.trace.json").read_bytes())
        self.assertFalse(artifact["native_commands_retried"])

    def test_existing_native_stop_intent_forbids_journal_entry(self):
        stoproot = self.root / "surrogate-stops"
        intent = stoproot / self.adapter.packet["owner_nonce"] / "poweroff.intent.json"
        intent.parent.mkdir(parents=True)
        intent.write_bytes(b"synthetic uncertain native stop")
        with (
            patch.object(start.owner.stop, "STOPS_ROOT", stoproot),
            self.assertRaisesRegex(Hold, "native stop intent"),
        ):
            self.adapter.observe(self.case.frame())
        self.assert_unaccepted()
        self.assertEqual(self.row()["state"], "resumed")

    def test_existing_native_stop_record_forbids_journal_entry(self):
        self.store.db.execute("CREATE TABLE native_owner_stop (state TEXT)")
        self.store.db.execute("INSERT INTO native_owner_stop VALUES('possible-send')")
        with self.assertRaisesRegex(Hold, "native stop record"):
            self.adapter.observe(self.case.frame())
        self.assert_unaccepted()
        self.assertEqual(self.row()["state"], "resumed")

    def test_short_writer_wait_sends_one_original_owner_request(self):
        self.adapter.observe(self.case.frame())
        lease = dict(self.store.db.execute("SELECT * FROM lease").fetchone())
        writer = self.writer()
        self.release(writer)
        request = self.adapter.request_owner_stop()
        self.assertEqual(request["grant_sha256"], self.adapter.sha)
        self.assertEqual(self.row()["state"], "owner-stop-requested")
        self.assertEqual(
            self.store.db.execute(
                "SELECT COUNT(*) FROM audit WHERE kind='frontend-original-owner-stop-requested'"
            ).fetchone()[0],
            1,
        )
        self.assertEqual(
            dict(self.store.db.execute("SELECT * FROM lease").fetchone()), lease
        )
        self.assertTrue(
            any(
                e["stage"] == "begin-failed" and e["phase"] == "owner-stop-request"
                for e in self.adapter.journal_trace
            )
        )
