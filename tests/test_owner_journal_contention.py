"""Real SQLite contention; no native VM command, model call or guest execution."""

import json
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from research.validation import maintenance_host as host
from research.validation.store import Hold, Store
from research.validation.supervisor import LeaseSupervisor
from tests import test_boot_preconditions as boot_tests
from tests import test_owner_launch as owner_tests


def busy():
    error = sqlite3.OperationalError("injected database is locked")
    error.sqlite_errorcode = sqlite3.SQLITE_BUSY
    return error


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "owner.sqlite")
        self.addCleanup(self.store.close)
        self.profile = {
            "target_vm_uuid": host.transfer.SLOTS["guard"][0],
            "lease_expires_utc_ns": time.time_ns() + 30 * 10**9,
        }
        self.supervisor = LeaseSupervisor(self.store, self.profile)
        self.owner = host.RegisteredOwner(
            self.supervisor,
            uuid4().hex,
            identity=lambda pid: {
                "pid": pid,
                "created_filetime": 1,
                "image": r"C:\synthetic\python.exe",
            },
        )
        self.original = dict(self.store.db.execute("SELECT * FROM lease").fetchone())
        self.stops = []

    def writer(self):
        db = sqlite3.connect(
            self.root / "owner.sqlite", isolation_level=None, check_same_thread=False
        )
        db.execute("BEGIN IMMEDIATE")
        return db

    def test_short_real_writer_lock_does_not_kill_owner_or_renew_lease(self):
        writer = self.writer()
        self.addCleanup(writer.close)

        def release():
            time.sleep(0.3)
            writer.execute("ROLLBACK")

        thread = threading.Thread(target=release)
        thread.start()
        self.addCleanup(thread.join)
        began = time.monotonic()
        self.assertFalse(self.owner.poll(stopper=lambda *_: self.stops.append(1)))
        self.assertGreaterEqual(time.monotonic() - began, 0.25)
        self.assertIsNotNone(self.owner.binding)
        self.assertEqual(
            dict(self.store.db.execute("SELECT * FROM lease").fetchone()), self.original
        )
        self.assertEqual(self.stops, [])
        self.assertFalse(self.store.db.in_transaction)

    def test_long_real_writer_lock_holds_after_bounded_wait_without_stop(self):
        writer = self.writer()
        began = time.monotonic()
        try:
            with self.assertRaises(sqlite3.OperationalError):
                self.owner.poll(stopper=lambda *_: self.stops.append(1))
        finally:
            writer.execute("ROLLBACK")
            writer.close()
        self.assertLess(time.monotonic() - began, 2)
        self.assertIsNone(self.owner.binding)
        self.assertEqual(self.stops, [])
        self.assertEqual(
            dict(self.store.db.execute("SELECT * FROM lease").fetchone()), self.original
        )

    def test_busy_after_durable_stop_intent_cannot_replay_the_stopper(self):
        self.store.fence("test stop request")

        def uncertain(*_args):
            self.stops.append(1)
            raise busy()

        with self.assertRaises(sqlite3.OperationalError):
            self.owner.poll(stopper=uncertain)
        self.assertEqual(self.stops, [1])
        self.assertEqual(
            self.store.db.execute("SELECT state FROM lease").fetchone()[0], "stopping"
        )
        with self.assertRaises(Hold):
            self.owner.poll(stopper=uncertain)
        self.assertEqual(self.stops, [1])

    def test_existing_possible_send_record_prevents_busy_retry_even_if_armed(self):
        self.store.db.execute("CREATE TABLE native_owner_stop (state TEXT)")
        self.store.db.execute("INSERT INTO native_owner_stop VALUES('possible-send')")
        with (
            patch.object(self.supervisor, "poll", side_effect=busy()) as poll,
            self.assertRaises(sqlite3.OperationalError),
        ):
            self.owner.poll()
        self.assertEqual(poll.call_count, 1)

    def test_busy_wait_cannot_cross_original_monotonic_expiry(self):
        writer = self.writer()
        try:
            with (
                patch.object(
                    host.time,
                    "monotonic_ns",
                    return_value=self.original["expires_mono_ns"],
                ),
                self.assertRaises(sqlite3.OperationalError),
            ):
                self.owner.poll(stopper=lambda *_: self.stops.append(1))
        finally:
            writer.execute("ROLLBACK")
            writer.close()
        self.assertEqual(self.stops, [])
        self.assertEqual(
            dict(self.store.db.execute("SELECT * FROM lease").fetchone()), self.original
        )

    def test_expiry_while_waiting_cannot_enter_another_poll_attempt(self):
        clocks = {
            "wall": self.original["armed_ns"] + 10**9,
            "mono": self.original["armed_mono_ns"] + 10**9,
        }

        def expire(_seconds):
            clocks.update(
                wall=self.original["expires_ns"], mono=self.original["expires_mono_ns"]
            )

        with (
            patch.object(host.time, "time_ns", side_effect=lambda: clocks["wall"]),
            patch.object(host.time, "monotonic_ns", side_effect=lambda: clocks["mono"]),
            patch.object(host.time, "sleep", side_effect=expire),
            patch.object(self.owner, "_poll_once", side_effect=busy()) as poll,
            self.assertRaises(sqlite3.OperationalError),
        ):
            self.owner.poll()
        self.assertEqual(poll.call_count, 1)
        self.assertEqual(
            dict(self.store.db.execute("SELECT * FROM lease").fetchone()), self.original
        )


class TerminalAdmissionTests(unittest.TestCase):
    setUp = boot_tests.PreparedTests.setUp

    def test_terminal_report_denies_still_live_owner_identity(self):
        (self.root / "owner.terminal.json").write_text("{}")
        with self.assertRaisesRegex(Hold, "terminal receipt"):
            host_boot = boot_tests.boot
            host_boot.owner_live(
                self.store,
                self.grant,
                identity=lambda pid: self.identities[pid],
                jobs=lambda _: None,
            )


@unittest.skipUnless(
    sys.platform == "win32", "Windows original-owner process and surrogate stop"
)
class NativeContentionTests(owner_tests.NativeOwnerFixture, unittest.TestCase):
    artifact_root = None

    def test_real_owner_survives_short_writer_lock_then_stops_once(self):
        pending = self.pending(seconds=30)
        self.seal()
        writer = sqlite3.connect(pending.root / "owner.sqlite", isolation_level=None)
        try:
            writer.execute("BEGIN IMMEDIATE")
            time.sleep(0.4)
        finally:
            writer.execute("ROLLBACK")
            writer.close()
        self.assertTrue(self.alive(self.owner_identity))
        time.sleep(0.15)
        self.assertFalse((pending.root / "owner.terminal.json").exists())
        self.assertFalse((pending.root / "surrogate.calls.jsonl").exists())
        store = Store(pending.root / "owner.sqlite")
        try:
            lease = store.db.execute("SELECT * FROM lease").fetchone()
            self.assertEqual({k: lease[k] for k in host.OWNER_KEYS}, pending.lease)
            store.fence("test-only contention recovery complete")
        finally:
            store.close()
        self.terminal()
        calls = (pending.root / "surrogate.calls.jsonl").read_text().splitlines()
        self.assertEqual(len(calls), 1)
        self.assertFalse(json.loads(calls[0])["actual_VM_command"])

    def test_persistent_lock_still_retains_terminal_when_fencing_is_busy(self):
        pending = self.pending(seconds=30)
        self.seal()
        writer = sqlite3.connect(pending.root / "owner.sqlite", isolation_level=None)
        try:
            writer.execute("BEGIN IMMEDIATE")
            terminal = self.terminal()
            self.assertEqual(terminal["status"], "held-owner-state-not-accepted")
            self.assertEqual(terminal["error_type"], "OperationalError")
            self.assertIn("database is locked", terminal["error"])
            self.assertIn("OperationalError", terminal["fence_error"])
            self.assertFalse((pending.root / "surrogate.calls.jsonl").exists())
        finally:
            writer.execute("ROLLBACK")
            writer.close()


if __name__ == "__main__":
    unittest.main()
