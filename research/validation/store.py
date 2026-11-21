"""Durable experiment intents and simulated spend. Single SQLite authority."""

import hashlib
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from .fixture import POLICY, canonical


class Hold(ValueError):
    """No new effect is permitted until evidence or authority resolves the hold."""


def money(value):
    if type(value) is not int or value < 0:
        raise ValueError("money must be a nonnegative integer in micro-USD")
    return value


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(
            path, timeout=5, isolation_level=None, check_same_thread=False
        )
        self.lock = threading.RLock()
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS authority (singleton INTEGER PRIMARY KEY CHECK(singleton=1), generation INTEGER, active INTEGER);
            INSERT OR IGNORE INTO authority VALUES(1, 1, 1);
            CREATE TABLE IF NOT EXISTS audit (seq INTEGER PRIMARY KEY, time_ns INTEGER NOT NULL, kind TEXT NOT NULL, payload BLOB NOT NULL, previous TEXT NOT NULL, digest TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, generation INTEGER NOT NULL, state TEXT NOT NULL, status INTEGER, response BLOB);
            CREATE TABLE IF NOT EXISTS permits (id TEXT PRIMARY KEY, task TEXT NOT NULL, attempt TEXT NOT NULL, role TEXT NOT NULL, generation INTEGER NOT NULL, request_hash TEXT NOT NULL, bound INTEGER NOT NULL, actual INTEGER, state TEXT NOT NULL, generation_id TEXT UNIQUE);
        """)

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    def _event(self, kind, payload):
        raw = canonical(payload)
        if len(raw) > 1024**2:
            raise ValueError("oversized journal record")
        last = self.db.execute(
            "SELECT seq, digest FROM audit ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        seq, previous = (last["seq"] + 1, last["digest"]) if last else (1, "0" * 64)
        if seq > 10000:
            raise Hold("journal record limit reached")
        now = time.time_ns()
        checksum = hashlib.sha256(
            canonical([seq, now, kind, previous]) + raw
        ).hexdigest()
        self.db.execute(
            "INSERT INTO audit VALUES(?,?,?,?,?,?)",
            (seq, now, kind, raw, previous, checksum),
        )

    def event(self, kind, payload):
        with self.transaction():
            self._event(kind, payload)

    def active(self, generation):
        row = self.db.execute("SELECT * FROM authority").fetchone()
        if not row["active"] or generation != row["generation"]:
            raise Hold("authority fenced or stale")

    def fence(self, reason):
        with self.transaction():
            self.db.execute("UPDATE authority SET active=0, generation=generation+1")
            self._event("authority-fenced", {"reason": reason})

    def begin(self, operation, request_hash, generation=1):
        """Persist possible-send before I/O; never automatically repeat it."""
        if not operation or len(operation) > 128:
            raise ValueError("invalid operation ID")
        with self.transaction():
            self.active(generation)
            row = self.db.execute(
                "SELECT * FROM operations WHERE id=?", (operation,)
            ).fetchone()
            if row:
                if (
                    row["request_hash"] != request_hash
                    or row["generation"] != generation
                ):
                    raise Hold("operation binding conflict")
                raise Hold("operation already issued; reconcile read-only")
            if self.db.execute(
                "SELECT 1 FROM operations WHERE state='possible-send'"
            ).fetchone():
                raise Hold("unresolved earlier mutation; reconcile read-only")
            self.db.execute(
                "INSERT INTO operations VALUES(?,?,?,'possible-send',NULL,NULL)",
                (operation, request_hash, generation),
            )
            self._event(
                "operation-intent",
                {
                    "id": operation,
                    "request_hash": request_hash,
                    "generation": generation,
                },
            )

    def receipt(self, operation, status, response):
        if len(response) > 1024**2:
            raise Hold("response too large")
        with self.transaction():
            row = self.db.execute(
                "SELECT * FROM operations WHERE id=?", (operation,)
            ).fetchone()
            if not row:
                raise Hold("receipt without intent")
            if row["state"] == "received":
                if row["status"] != status or row["response"] != response:
                    raise Hold("conflicting operation receipt")
                return
            self.db.execute(
                "UPDATE operations SET state='received',status=?,response=? WHERE id=?",
                (status, response, operation),
            )
            self._event(
                "operation-receipt",
                {
                    "id": operation,
                    "status": status,
                    "response_sha256": hashlib.sha256(response).hexdigest(),
                },
            )

    def reserve(self, permit, task, attempt, role, request_hash, bound, generation=1):
        bound = money(bound)
        limits = POLICY["limits"]
        if task not in ("T-01", "T-02") or role not in (
            "edit",
            "correction",
            "finish",
            "review",
        ):
            raise Hold("unknown task or role")
        if bound == 0 or bound > limits[role] or not permit or not attempt:
            raise Hold("invalid permit or request bound")
        with self.transaction():
            self.active(generation)
            if self.db.execute(
                "SELECT 1 FROM permits WHERE id=?", (permit,)
            ).fetchone():
                raise Hold("permit already exists")
            if self.db.execute(
                "SELECT 1 FROM permits WHERE state!='settled'"
            ).fetchone():
                raise Hold("one unresolved request already holds dispatch")
            rows = self.db.execute("SELECT * FROM permits").fetchall()
            exposure = lambda row: (
                row["actual"] if row["actual"] is not None else row["bound"]
            )
            if sum(map(exposure, rows)) + bound > limits["milestone"]:
                raise Hold("milestone cap")
            task_rows = [row for row in rows if row["task"] == task]
            if sum(map(exposure, task_rows)) + bound > limits[task]:
                raise Hold("task cap")
            review = role == "review"
            bucket_rows = [
                row for row in task_rows if (row["role"] == "review") == review
            ]
            bucket_limit = (
                limits["review_per_task"]
                if review
                else limits[task] - limits["review_per_task"]
            )
            if sum(map(exposure, bucket_rows)) + bound > bucket_limit:
                raise Hold("protected review allocation")
            if not review:
                attempts = {
                    row["attempt"] for row in task_rows if row["role"] != "review"
                }
                if attempt not in attempts and len(attempts) >= 2:
                    raise Hold("default correction limit")
                attempt_rows = [
                    row
                    for row in task_rows
                    if row["attempt"] == attempt and row["role"] != "review"
                ]
                if (
                    len(attempt_rows) >= 3
                    or sum(map(exposure, attempt_rows)) + bound > limits["attempt"]
                ):
                    raise Hold("attempt cap")
            self.db.execute(
                "INSERT INTO permits VALUES(?,?,?,?,?,?,?,NULL,'reserved',NULL)",
                (permit, task, attempt, role, generation, request_hash, bound),
            )
            self._event(
                "reservation",
                {
                    "id": permit,
                    "task": task,
                    "attempt": attempt,
                    "role": role,
                    "bound": bound,
                    "generation": generation,
                },
            )

    def consume(self, request_hash):
        with self.transaction():
            row = self.db.execute(
                "SELECT * FROM permits WHERE state='reserved'"
            ).fetchone()
            if not row or row["request_hash"] != request_hash:
                raise Hold("no exact-request permit")
            self.active(row["generation"])
            self.db.execute(
                "UPDATE permits SET state='possible-send' WHERE id=?", (row["id"],)
            )
            self._event(
                "submission-intent", {"id": row["id"], "request_hash": request_hash}
            )
            return dict(row)

    def settle(self, permit, actual, generation_id):
        actual = money(actual)
        if not generation_id:
            raise Hold("missing generation identity")
        conflict = None
        with self.transaction():
            row = self.db.execute(
                "SELECT * FROM permits WHERE id=?", (permit,)
            ).fetchone()
            if not row or row["state"] == "reserved":
                raise Hold("settlement without possible send")
            if row["actual"] is not None:
                if row["actual"] != actual or row["generation_id"] != generation_id:
                    conflict = "conflicting final settlement"
                else:
                    return
            elif actual > row["bound"]:
                conflict = "charge exceeds qualified bound"
            else:
                other = self.db.execute(
                    "SELECT id FROM permits WHERE generation_id=?", (generation_id,)
                ).fetchone()
                if other and other["id"] != permit:
                    conflict = "generation reused across submissions"
            if conflict:
                self.db.execute(
                    "UPDATE permits SET state='conflict' WHERE id=?", (permit,)
                )
                self.db.execute(
                    "UPDATE authority SET active=0, generation=generation+1"
                )
                self._event(
                    "settlement-conflict-hold",
                    {"id": permit, "reason": conflict, "reported_actual": actual},
                )
            else:
                self.db.execute(
                    "UPDATE permits SET state='settled',actual=?,generation_id=? WHERE id=?",
                    (actual, generation_id, permit),
                )
                self._event(
                    "settlement",
                    {
                        "id": permit,
                        "actual": actual,
                        "generation_id": generation_id,
                        "simulated": True,
                    },
                )
        if conflict:
            raise Hold(conflict)

    def snapshot(self):
        with self.transaction():
            rows = [
                dict(row)
                for row in self.db.execute("SELECT * FROM permits ORDER BY rowid")
            ]
            return {
                "settled_micro_usd": sum(row["actual"] or 0 for row in rows),
                "held_micro_usd": sum(
                    row["bound"]
                    if row["actual"] is None
                    else max(0, row["bound"] - row["actual"])
                    for row in rows
                    if row["state"] != "settled"
                ),
                "exposure_qualified": not any(
                    row["state"] == "conflict" for row in rows
                ),
                "permits": rows,
                "authority": dict(
                    self.db.execute("SELECT * FROM authority").fetchone()
                ),
                "operations": [
                    dict(row)
                    | {
                        "response": None,
                        "response_sha256": hashlib.sha256(row["response"]).hexdigest()
                        if row["response"] is not None
                        else None,
                    }
                    for row in self.db.execute(
                        "SELECT * FROM operations ORDER BY rowid"
                    )
                ],
            }

    def audit(self):
        with self.lock:
            previous = "0" * 64
            result = []
            for expected, row in enumerate(
                self.db.execute("SELECT * FROM audit ORDER BY seq"), 1
            ):
                checksum = hashlib.sha256(
                    canonical([row["seq"], row["time_ns"], row["kind"], previous])
                    + row["payload"]
                ).hexdigest()
                if (
                    row["seq"] != expected
                    or row["previous"] != previous
                    or row["digest"] != checksum
                ):
                    raise Hold("audit chain mismatch")
                previous = row["digest"]
                result.append(
                    dict(row) | {"payload": __import__("json").loads(row["payload"])}
                )
            return result
