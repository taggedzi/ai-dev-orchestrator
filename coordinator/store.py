"""One local product database, explicit transactions and versioned schema."""

import hashlib
import json
import sqlite3
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

from .domain import Conflict, Invalid, canonical, digest, require, text

APPLICATION_ID = 0x41444F31
SCHEMA_VERSION = 7

SCHEMA_V1 = (
    "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE projects (id TEXT PRIMARY KEY, version INTEGER NOT NULL, revision INTEGER NOT NULL, generation INTEGER NOT NULL, paused INTEGER NOT NULL CHECK(paused IN (0,1)))",
    "CREATE TABLE project_revisions (project_id TEXT NOT NULL REFERENCES projects(id), revision INTEGER NOT NULL, spec TEXT NOT NULL, digest TEXT NOT NULL, PRIMARY KEY(project_id,revision))",
    "CREATE TABLE milestones (id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), key TEXT NOT NULL, version INTEGER NOT NULL, approved_plan_id TEXT, head_revision TEXT NOT NULL, UNIQUE(project_id,key))",
    "CREATE TABLE plans (id TEXT PRIMARY KEY, milestone_id TEXT NOT NULL REFERENCES milestones(id), revision INTEGER NOT NULL, spec TEXT NOT NULL, digest TEXT NOT NULL, UNIQUE(milestone_id,revision))",
    "CREATE TABLE approvals (plan_id TEXT PRIMARY KEY REFERENCES plans(id), actor TEXT NOT NULL, digest TEXT NOT NULL, created_ns INTEGER NOT NULL)",
    "CREATE TABLE attempts (id TEXT PRIMARY KEY, milestone_id TEXT NOT NULL REFERENCES milestones(id), plan_id TEXT NOT NULL REFERENCES plans(id), task_key TEXT NOT NULL, project_generation INTEGER NOT NULL, version INTEGER NOT NULL, state TEXT NOT NULL CHECK(state IN ('reserved','executing','held','awaiting_verification','failed','cancelled')), adapter TEXT NOT NULL CHECK(adapter='scripted'), input_revision TEXT NOT NULL, assignment TEXT NOT NULL)",
    "CREATE UNIQUE INDEX one_active_attempt ON attempts(milestone_id) WHERE state IN ('reserved','executing','held','awaiting_verification')",
    "CREATE TABLE operations (id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL UNIQUE REFERENCES attempts(id), state TEXT NOT NULL CHECK(state IN ('prepared','possible_send','returned','unknown','cancelled','abandoned','conflicting')), result TEXT)",
    "CREATE TABLE observations (operation_id TEXT NOT NULL REFERENCES operations(id), digest TEXT NOT NULL, payload TEXT NOT NULL, created_ns INTEGER NOT NULL, PRIMARY KEY(operation_id,digest))",
    "CREATE TABLE acceptances (plan_id TEXT NOT NULL REFERENCES plans(id), task_key TEXT NOT NULL, integrated_revision TEXT NOT NULL, evidence_digest TEXT NOT NULL, PRIMARY KEY(plan_id,task_key))",
    "CREATE TABLE commands (id TEXT PRIMARY KEY, request_digest TEXT NOT NULL, result TEXT NOT NULL)",
    "CREATE TABLE events (sequence INTEGER PRIMARY KEY AUTOINCREMENT, command_id TEXT NOT NULL, actor TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL, created_ns INTEGER NOT NULL)",
)

INTAKE_SCHEMA = (
    "CREATE TABLE candidate_intakes (id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL UNIQUE REFERENCES attempts(id), project_id TEXT NOT NULL REFERENCES projects(id), producer TEXT NOT NULL, version INTEGER NOT NULL, state TEXT NOT NULL CHECK(state IN ('prepared','possible_send','sealed','held','conflicting')), contract TEXT NOT NULL, source_digest TEXT NOT NULL, receipt TEXT, receipt_digest TEXT, sent_ns INTEGER, created_ns INTEGER NOT NULL)",
    "CREATE TABLE intake_observations (intake_id TEXT NOT NULL REFERENCES candidate_intakes(id), digest TEXT NOT NULL, payload TEXT NOT NULL, created_ns INTEGER NOT NULL, PRIMARY KEY(intake_id,digest))",
)
VERIFICATION_SCHEMA = (
    "CREATE TABLE verification_policies (id TEXT PRIMARY KEY, intake_id TEXT NOT NULL UNIQUE REFERENCES candidate_intakes(id), digest TEXT NOT NULL, spec TEXT NOT NULL, actor TEXT NOT NULL, review_session TEXT NOT NULL UNIQUE, approved_ns INTEGER NOT NULL)",
    "CREATE TABLE verification_operations (id TEXT PRIMARY KEY, intake_id TEXT NOT NULL REFERENCES candidate_intakes(id), policy_id TEXT NOT NULL REFERENCES verification_policies(id), kind TEXT NOT NULL CHECK(kind IN ('check','review')), key TEXT NOT NULL, scheduler TEXT NOT NULL, producer TEXT NOT NULL, version INTEGER NOT NULL, state TEXT NOT NULL CHECK(state IN ('prepared','possible_send','returned','held','conflicting')), binding TEXT NOT NULL, receipt TEXT, receipt_digest TEXT, sent_ns INTEGER, created_ns INTEGER NOT NULL, UNIQUE(intake_id,kind,key))",
    "CREATE TABLE verification_observations (operation_id TEXT NOT NULL REFERENCES verification_operations(id), digest TEXT NOT NULL, payload TEXT NOT NULL, created_ns INTEGER NOT NULL, PRIMARY KEY(operation_id,digest))",
)
SCHEMA_V2 = SCHEMA_V1 + INTAKE_SCHEMA
INTEGRATION_SCHEMA = (
    "CREATE TABLE integration_proposals (id TEXT PRIMARY KEY, intake_id TEXT NOT NULL UNIQUE REFERENCES candidate_intakes(id), project_id TEXT NOT NULL REFERENCES projects(id), producer TEXT NOT NULL, version INTEGER NOT NULL, state TEXT NOT NULL CHECK(state IN ('prepared','possible_send','staged','held','conflicting')), intent TEXT NOT NULL, receipt TEXT, receipt_digest TEXT, sent_ns INTEGER, created_ns INTEGER NOT NULL)",
    "CREATE TABLE integration_stage_observations (proposal_id TEXT NOT NULL REFERENCES integration_proposals(id), digest TEXT NOT NULL, payload TEXT NOT NULL, created_ns INTEGER NOT NULL, PRIMARY KEY(proposal_id,digest))",
    "CREATE TABLE integration_policies (id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL UNIQUE REFERENCES integration_proposals(id), digest TEXT NOT NULL, spec TEXT NOT NULL, actor TEXT NOT NULL, approved_ns INTEGER NOT NULL)",
    "CREATE TABLE integration_regressions (id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL REFERENCES integration_proposals(id), key TEXT NOT NULL, producer TEXT NOT NULL, scheduler TEXT NOT NULL, version INTEGER NOT NULL, state TEXT NOT NULL CHECK(state IN ('prepared','possible_send','returned','held','conflicting')), binding TEXT NOT NULL, receipt TEXT, receipt_digest TEXT, sent_ns INTEGER, created_ns INTEGER NOT NULL, UNIQUE(proposal_id,key))",
    "CREATE TABLE integration_regression_observations (operation_id TEXT NOT NULL REFERENCES integration_regressions(id), digest TEXT NOT NULL, payload TEXT NOT NULL, created_ns INTEGER NOT NULL, PRIMARY KEY(operation_id,digest))",
)
SCHEMA_V3 = SCHEMA_V2 + VERIFICATION_SCHEMA
SCHEMA_V4 = SCHEMA_V3 + INTEGRATION_SCHEMA
HEAD_MAPPING_SCHEMA = (
    "CREATE TABLE integration_head_mappings (id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL UNIQUE REFERENCES attempts(id), project_id TEXT NOT NULL REFERENCES projects(id), previous_head TEXT NOT NULL, new_head TEXT NOT NULL, authority_generation INTEGER NOT NULL, authorization_digest TEXT NOT NULL UNIQUE, actor TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('authorized','consumed')), consumed_by TEXT REFERENCES integration_proposals(id), created_ns INTEGER NOT NULL, consumed_ns INTEGER, CHECK((state='authorized' AND consumed_by IS NULL AND consumed_ns IS NULL) OR (state='consumed' AND consumed_by IS NOT NULL AND consumed_ns IS NOT NULL)))",
)
SCHEMA_V5 = SCHEMA_V4 + HEAD_MAPPING_SCHEMA
ATTEMPT_SETTLEMENT = (
    "ALTER TABLE attempts ADD COLUMN settled INTEGER NOT NULL DEFAULT 0 CHECK(settled IN (0,1))",
    "DROP INDEX one_active_attempt",
    "CREATE UNIQUE INDEX one_active_attempt ON attempts(milestone_id) WHERE state IN ('reserved','executing','held','awaiting_verification') AND settled=0",
)
INTEGRATED_EVIDENCE_SCHEMA = (
    "CREATE TABLE integration_evidence_policies (id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL UNIQUE REFERENCES integration_proposals(id), digest TEXT NOT NULL, spec TEXT NOT NULL, actor TEXT NOT NULL, review_session TEXT NOT NULL UNIQUE, approved_ns INTEGER NOT NULL)",
    "CREATE TABLE integration_verifications (id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL REFERENCES integration_proposals(id), policy_id TEXT NOT NULL REFERENCES integration_evidence_policies(id), kind TEXT NOT NULL CHECK(kind IN ('check','review')), key TEXT NOT NULL, scheduler TEXT NOT NULL, producer TEXT NOT NULL, version INTEGER NOT NULL, state TEXT NOT NULL CHECK(state IN ('prepared','possible_send','returned','held','conflicting')), binding TEXT NOT NULL, receipt TEXT, receipt_digest TEXT, sent_ns INTEGER, created_ns INTEGER NOT NULL, UNIQUE(proposal_id,kind,key))",
    "CREATE TABLE integration_verification_observations (operation_id TEXT NOT NULL REFERENCES integration_verifications(id), digest TEXT NOT NULL, payload TEXT NOT NULL, created_ns INTEGER NOT NULL, PRIMARY KEY(operation_id,digest))",
    "CREATE TABLE integration_promotions (id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL UNIQUE REFERENCES integration_proposals(id), project_id TEXT NOT NULL REFERENCES projects(id), milestone_id TEXT NOT NULL REFERENCES milestones(id), attempt_id TEXT NOT NULL REFERENCES attempts(id), plan_id TEXT NOT NULL REFERENCES plans(id), task_key TEXT NOT NULL, expected_head TEXT NOT NULL, integrated_revision TEXT NOT NULL, expected_milestone_version INTEGER NOT NULL, evidence_digest TEXT NOT NULL, evidence TEXT NOT NULL, version INTEGER NOT NULL, state TEXT NOT NULL CHECK(state IN ('prepared','possible_send','promoted','held','conflicting')), receipt TEXT, receipt_digest TEXT, sent_ns INTEGER, created_ns INTEGER NOT NULL)",
)
SCHEMA_V6 = SCHEMA_V5 + ATTEMPT_SETTLEMENT + INTEGRATED_EVIDENCE_SCHEMA
MODEL_POLICY_SCHEMA = (
    "CREATE TABLE model_policies (id TEXT PRIMARY KEY, milestone_id TEXT NOT NULL UNIQUE REFERENCES milestones(id), project_id TEXT NOT NULL REFERENCES projects(id), digest TEXT NOT NULL, spec TEXT NOT NULL, actor TEXT NOT NULL, approved_ns INTEGER NOT NULL)",
    "CREATE TABLE model_assignments (id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL REFERENCES attempts(id), milestone_id TEXT NOT NULL REFERENCES milestones(id), project_id TEXT NOT NULL REFERENCES projects(id), policy_id TEXT NOT NULL REFERENCES model_policies(id), role TEXT NOT NULL CHECK(role IN ('implementation','review')), route_id TEXT NOT NULL, requested TEXT NOT NULL, requested_digest TEXT NOT NULL, decision TEXT NOT NULL CHECK(decision='eligible'), missing TEXT NOT NULL, actor TEXT NOT NULL, created_ns INTEGER NOT NULL, UNIQUE(attempt_id,role))",
    "CREATE TABLE model_permits (id TEXT PRIMARY KEY, assignment_id TEXT NOT NULL REFERENCES model_assignments(id), attempt_id TEXT NOT NULL REFERENCES attempts(id), project_id TEXT NOT NULL REFERENCES projects(id), milestone_id TEXT NOT NULL REFERENCES milestones(id), policy_id TEXT NOT NULL REFERENCES model_policies(id), role TEXT NOT NULL CHECK(role IN ('implementation','review')), route_id TEXT NOT NULL, submission_id TEXT NOT NULL UNIQUE, request_digest TEXT NOT NULL, reserved_units INTEGER NOT NULL CHECK(reserved_units>=0), settled_units INTEGER CHECK(settled_units IS NULL OR (settled_units>=0 AND settled_units<=reserved_units)), allowance TEXT NOT NULL CHECK(allowance IN ('general','review')), version INTEGER NOT NULL, state TEXT NOT NULL CHECK(state IN ('prepared','possible_send','reserved','reconciled','held','conflicting')), usage TEXT, usage_digest TEXT, sent_ns INTEGER, created_ns INTEGER NOT NULL, CHECK((state IN ('prepared','possible_send','held') AND usage IS NULL AND usage_digest IS NULL AND settled_units IS NULL) OR (state='reserved' AND usage IS NOT NULL AND usage_digest IS NOT NULL AND settled_units IS NULL) OR (state='reconciled' AND usage IS NOT NULL AND usage_digest IS NOT NULL AND settled_units IS NOT NULL) OR (state='conflicting' AND usage IS NOT NULL AND usage_digest IS NOT NULL AND settled_units IS NULL)))",
)
SCHEMA = SCHEMA_V6 + MODEL_POLICY_SCHEMA
MIGRATIONS = {
    1: INTAKE_SCHEMA,
    2: VERIFICATION_SCHEMA,
    3: INTEGRATION_SCHEMA,
    4: HEAD_MAPPING_SCHEMA,
    5: ATTEMPT_SETTLEMENT + INTEGRATED_EVIDENCE_SCHEMA,
    6: MODEL_POLICY_SCHEMA,
}


def require_primary(db, path):
    require(
        db.execute("SELECT value FROM meta WHERE key='archive'").fetchone()[0] == "0",
        "backup archive is read-only; restore/recovery is required",
    )
    primary = db.execute("SELECT value FROM meta WHERE key='primary_path'").fetchone()
    require(
        primary is not None and primary[0] == str(path),
        "copied or older store requires explicit restore/recovery",
    )


def archive_connection(source, output):
    output = Path(output).resolve()
    with output.open("xb"):
        pass
    destination = sqlite3.connect(output, autocommit=True)
    try:
        source.backup(destination)
        destination.execute("PRAGMA synchronous=FULL")
        destination.execute("BEGIN IMMEDIATE")
        destination.execute("UPDATE meta SET value='1' WHERE key='archive'")
        destination.execute("COMMIT")
        require(
            destination.execute("PRAGMA integrity_check").fetchall() == [("ok",)],
            "backup integrity check failed",
        )
        require(
            not destination.execute("PRAGMA foreign_key_check").fetchall(),
            "backup foreign-key check failed",
        )
        destination.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        destination.close()
    payload = load_archive_bytes(output)
    return {
        "path": str(output),
        "mode": "archive",
        "restore_requires_recovery": True,
        "digest": archive_sha256(payload),
    }


def load_archive_bytes(path):
    return Path(path).read_bytes()


def archive_sha256(payload):
    return hashlib.sha256(payload).hexdigest()


def discard_store(path):
    path = Path(path)
    path.unlink(missing_ok=True)
    Path(str(path) + "-wal").unlink(missing_ok=True)
    Path(str(path) + "-shm").unlink(missing_ok=True)


def inspect_archive_payload(payload):
    """Open a private copy of the exact bytes. The caller's file is not a writer."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "archive.sqlite"
        path.write_bytes(payload)
        try:
            db = sqlite3.connect(
                path.as_uri() + "?mode=ro", uri=True, autocommit=True, timeout=1.0
            )
        except sqlite3.DatabaseError as error:
            raise Invalid("archive integrity check failed") from error
        try:
            try:
                require(
                    db.execute("PRAGMA application_id").fetchone()[0] == APPLICATION_ID,
                    "not an orchestrator store",
                )
                require(
                    db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION,
                    "unsupported product schema; migration required",
                )
                require(
                    db.execute("PRAGMA journal_mode").fetchone()[0] == "wal",
                    "product store requires WAL mode",
                )
                archive = db.execute(
                    "SELECT value FROM meta WHERE key='archive'"
                ).fetchone()
                require(
                    archive is not None and archive[0] == "1",
                    "restore source must be an archive",
                )
                require(
                    db.execute("PRAGMA integrity_check").fetchall() == [("ok",)],
                    "archive integrity check failed",
                )
                require(
                    not db.execute("PRAGMA foreign_key_check").fetchall(),
                    "archive foreign-key check failed",
                )
            except sqlite3.DatabaseError as error:
                raise Invalid("archive integrity check failed") from error
        finally:
            db.close()


def rebind_restored(path):
    """Turn a byte copy of an archive into the primary bound to this path."""
    path = Path(path)
    db = sqlite3.connect(path, autocommit=True, timeout=1.0)
    try:
        require(
            db.execute("PRAGMA journal_mode").fetchone()[0] == "wal",
            "product store requires WAL mode",
        )
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA trusted_schema=OFF")
        db.execute("BEGIN IMMEDIATE")
        try:
            require(
                db.execute("PRAGMA application_id").fetchone()[0] == APPLICATION_ID,
                "not an orchestrator store",
            )
            require(
                db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION,
                "unsupported product schema; migration required",
            )
            archive = db.execute(
                "SELECT value FROM meta WHERE key='archive'"
            ).fetchone()
            require(
                archive is not None and archive[0] == "1",
                "restore source must be an archive",
            )
            require(
                db.execute("PRAGMA integrity_check").fetchall() == [("ok",)],
                "archive integrity check failed",
            )
            require(
                not db.execute("PRAGMA foreign_key_check").fetchall(),
                "archive foreign-key check failed",
            )
            db.execute("UPDATE meta SET value='0' WHERE key='archive'")
            db.execute("UPDATE meta SET value=? WHERE key='primary_path'", (str(path),))
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        require(
            db.execute("PRAGMA integrity_check").fetchall() == [("ok",)],
            "restored integrity check failed",
        )
        require(
            not db.execute("PRAGMA foreign_key_check").fetchall(),
            "restored foreign-key check failed",
        )
        require(
            db.execute("SELECT value FROM meta WHERE key='archive'").fetchone()[0]
            == "0",
            "restored store is still an archive",
        )
        require(
            db.execute("SELECT value FROM meta WHERE key='primary_path'").fetchone()[0]
            == str(path),
            "restored store kept its old path",
        )
    finally:
        db.close()


def patched_sqlite(version=None):
    version = sqlite3.sqlite_version_info if version is None else version
    return (
        version >= (3, 51, 3)
        or (version[:2] == (3, 50) and version[2] >= 7)
        or (version[:2] == (3, 44) and version[2] >= 6)
    )


def runtime_check():
    require(
        patched_sqlite(),
        f"SQLite {sqlite3.sqlite_version} needs the WAL-reset fix; use a verified patched runtime",
    )


class Store:
    def __init__(self, path):
        runtime_check()
        self.path = Path(path).resolve()
        self.lock = threading.RLock()
        self.db = sqlite3.connect(
            self.path.as_uri() + "?mode=rw",
            uri=True,
            autocommit=True,
            check_same_thread=False,
            timeout=1.0,
        )
        self.db.row_factory = sqlite3.Row
        try:
            require(
                self.db.execute("PRAGMA application_id").fetchone()[0]
                == APPLICATION_ID,
                "not an orchestrator store",
            )
            require(
                self.db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION,
                "unsupported product schema; migration required",
            )
            require(
                self.db.execute("PRAGMA journal_mode").fetchone()[0] == "wal",
                "product store requires WAL mode",
            )
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute("PRAGMA trusted_schema=OFF")
        except BaseException:
            self.db.close()
            raise

    @classmethod
    def create(cls, path):
        runtime_check()
        path = Path(path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb"):
            pass
        db = sqlite3.connect(path, autocommit=True)
        try:
            require(
                db.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal",
                "cannot enable WAL",
            )
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("BEGIN IMMEDIATE")
            try:
                for statement in SCHEMA:
                    db.execute(statement)
                db.execute("INSERT INTO meta VALUES('archive','0')")
                db.execute("INSERT INTO meta VALUES('primary_path',?)", (str(path),))
                db.execute(f"PRAGMA application_id={APPLICATION_ID}")
                db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
        finally:
            db.close()
        return cls(path)

    def close(self):
        with self.lock:
            self.db.close()

    @classmethod
    def migrate(cls, path, backup):
        """Explicit offline migration; never upgrades on ordinary open.

        Stop old coordinator processes first. A backup is captured before DDL;
        concurrent commits during capture cause refusal, not a retry.
        """
        runtime_check()
        path = Path(path).resolve()
        db = sqlite3.connect(
            path.as_uri() + "?mode=rw", uri=True, autocommit=True, timeout=1.0
        )
        try:
            require(
                db.execute("PRAGMA application_id").fetchone()[0] == APPLICATION_ID,
                "not an orchestrator store",
            )
            previous = db.execute("PRAGMA user_version").fetchone()[0]
            require(
                previous in MIGRATIONS,
                "only older supported product schemas can migrate",
            )
            require(
                db.execute("PRAGMA journal_mode").fetchone()[0] == "wal",
                "product store requires WAL mode",
            )
            require_primary(db, path)
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA trusted_schema=OFF")
            require(
                db.execute("PRAGMA integrity_check").fetchall() == [("ok",)],
                "source integrity check failed",
            )
            require(
                not db.execute("PRAGMA foreign_key_check").fetchall(),
                "source foreign-key check failed",
            )
            before = db.execute("PRAGMA data_version").fetchone()[0]
            archive = archive_connection(db, backup)
            db.execute("BEGIN IMMEDIATE")
            try:
                require(
                    db.execute("PRAGMA data_version").fetchone()[0] == before,
                    "source changed during backup; migration held",
                    Conflict,
                )
                require(
                    db.execute("PRAGMA user_version").fetchone()[0] == previous,
                    "schema changed during backup",
                    Conflict,
                )
                require_primary(db, path)
                for version in range(previous, SCHEMA_VERSION):
                    for statement in MIGRATIONS[version]:
                        db.execute(statement)
                db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
                db.execute("COMMIT")
            except BaseException:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise
        finally:
            db.close()
        return {"schema": SCHEMA_VERSION, "backup": archive, "database": str(path)}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    @contextmanager
    def transaction(self, *, write=True):
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            try:
                yield
                self.db.execute("COMMIT")
            except BaseException:
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK")
                raise

    def command(self, name, principal, payload, apply, command_id):
        text(command_id, "command id", 200)
        request_digest = digest(
            {
                "command": name,
                "actor": principal.id,
                "role": principal.role,
                "payload": payload,
            }
        )
        with self.transaction():
            require(
                self.db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION,
                "schema changed; close this coordinator and inspect migration",
                Conflict,
            )
            require_primary(self.db, self.path)
            old = self.db.execute(
                "SELECT * FROM commands WHERE id=?", (command_id,)
            ).fetchone()
            if old:
                require(
                    old["request_digest"] == request_digest,
                    "command id reused with different intent or actor",
                    Conflict,
                )
                return json.loads(old["result"])
            result = apply()
            self.db.execute(
                "INSERT INTO commands VALUES(?,?,?)",
                (command_id, request_digest, canonical(result)),
            )
            return result

    def recall(self, name, principal, payload, command_id):
        """Inspect a committed command before an expensive read-only preflight."""
        if command_id is None:
            return None
        text(command_id, "command id", 200)
        checksum = digest(
            {
                "command": name,
                "actor": principal.id,
                "role": principal.role,
                "payload": payload,
            }
        )
        with self.transaction(write=False):
            old = self.db.execute(
                "SELECT * FROM commands WHERE id=?", (command_id,)
            ).fetchone()
            if old is None:
                return None
            require(
                old["request_digest"] == checksum,
                "command id reused with different intent or actor",
                Conflict,
            )
            return json.loads(old["result"])

    def backup(self, output):
        """Consistent new archive; cannot be opened for business mutations."""
        with self.lock:
            return archive_connection(self.db, output)

    @classmethod
    def restore(cls, archive, destination, expected_digest):
        """Bind a verified archive as a new primary. The archive is not modified.

        Two reads of the archive must be identical. A mismatch, a failed check,
        or a failed rebind leaves no destination. This is not power-loss proof.
        """
        runtime_check()
        archive = Path(archive).resolve()
        destination = Path(destination).resolve()
        require(archive.is_file(), "archive is missing")
        require(
            archive != destination,
            "restore destination must differ from the archive",
        )
        require(
            type(expected_digest) is str
            and len(expected_digest) == 64
            and all(character in "0123456789abcdef" for character in expected_digest),
            "invalid archive digest",
        )
        payload = load_archive_bytes(archive)
        require(
            archive_sha256(payload) == expected_digest,
            "archive digest mismatch",
            Conflict,
        )
        inspect_archive_payload(payload)
        require(
            load_archive_bytes(archive) == payload,
            "archive drifted during restore",
            Conflict,
        )
        require(not destination.exists(), "restore destination exists")
        destination.parent.mkdir(parents=True, exist_ok=True)
        created = False
        try:
            with destination.open("xb") as handle:
                handle.write(payload)
            created = True
            rebind_restored(destination)
        except BaseException:
            if created:
                discard_store(destination)
            raise
        return {
            "path": str(destination),
            "mode": "primary",
            "schema": SCHEMA_VERSION,
            "digest": expected_digest,
            "archive": str(archive),
        }
