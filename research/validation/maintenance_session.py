"""Prepared same-boot review handoff under one original owner and lease.

No native activation CLI. Construction requires an already running, independently
owned session; trusted collectors and approval authentication remain deployment work.
"""

import copy
import json
import os
import threading
import time
from pathlib import Path

from . import maintenance_config, maintenance_control, maintenance_guest, offline_repo
from . import maintenance_host as host
from . import maintenance_transfer as transfer
from . import owner_process as owner
from .transfer_commands import canonical, digest

require = transfer.require
SOURCES = {
    **owner.SOURCES,
    **{p.name: p for p in transfer.SOURCES.values()},
    "maintenance_session.py": Path(__file__),
    **{
        Path(m.__file__).name: Path(m.__file__)
        for m in (
            maintenance_config,
            maintenance_control,
            maintenance_guest,
            offline_repo,
        )
    },
}
SOURCE_EPOCH = {name: digest(path.read_bytes()) for name, path in SOURCES.items()}


def current_sources():
    return {name: digest(path.read_bytes()) for name, path in SOURCES.items()}


def draft():
    return {
        "format": "mcli1-maintenance-session-v1",
        "inspection_grant_sha256": None,
        "owner_binding_sha256": None,
        "owner_launch_sha256": None,
        "controller": None,
        "review_expires_utc_ns": None,
        "review_expires_mono_ns": None,
        "approval": None,
        "sources": dict(SOURCE_EPOCH),
    }


class MaintenanceSession:
    def __init__(
        self,
        controller,
        raw,
        sha,
        inspection,
        inspection_sha,
        identity=host.process_identity,
    ):
        require(type(raw) is bytes and digest(raw) == sha, "session digest differs")
        review = host.object_bytes(raw)
        require(
            set(review) == set(draft())
            and review["format"] == "mcli1-maintenance-session-v1",
            "session review format differs",
        )
        require(
            isinstance(review["approval"], str) and 0 < len(review["approval"]) <= 256,
            "same-boot session approval is unbound",
        )
        grant = transfer.checked_grant(inspection, inspection_sha)
        require(
            grant["purpose"] == "inspect"
            and review["inspection_grant_sha256"] == inspection_sha,
            "session must begin with the exact inspection",
        )
        require(
            review["sources"] == SOURCE_EPOCH == current_sources(),
            "session source cohort changed",
        )
        self.controller, self.store, self.identity = (
            controller,
            controller.store,
            identity,
        )
        self.review, self.grant = review, grant
        self.inspection, self.inspection_sha = inspection, inspection_sha
        self.closed, self.monitor_stop = False, threading.Event()
        self.watch, self.monitor = None, None
        self.thread_error = None
        self.store.db.execute("PRAGMA busy_timeout=50")
        row = self.store.db.execute("SELECT * FROM lease").fetchone()
        require(row is not None, "session requires the original lease")
        self.lease = {k: row[k] for k in host.OWNER_KEYS}
        for clock, key in (("utc", "expires_ns"), ("mono", "expires_mono_ns")):
            end = review["review_expires_" + clock + "_ns"]
            require(
                type(end) is int and 0 < end <= row[key] - 10 * 10**9,
                "session review consumes original stop reserve",
            )
            require(
                grant["phase_window"]["expires_" + clock + "_ns"] <= end,
                "inspection extends session review window",
            )
        self.review_grant = copy.deepcopy(grant)
        self.review_grant["phase_window"].update(
            expires_utc_ns=review["review_expires_utc_ns"],
            expires_mono_ns=review["review_expires_mono_ns"],
        )
        self.owner_binding = self.store.db.execute(
            "SELECT binding FROM maintenance_owner"
        ).fetchone()[0]
        binding = host.object_bytes(self.owner_binding)
        require(
            digest(self.owner_binding) == review["owner_binding_sha256"]
            and binding["format"] == "mcli1-original-owner-v1"
            and binding["owner_nonce"] == grant["lease"]["owner_nonce"]
            and binding["lease"] == self.lease,
            "session original owner binding differs",
        )
        self.owner_process = binding["process"]
        dbpath = self.store.db.execute("PRAGMA database_list").fetchone()["file"]
        self.root = Path(dbpath).resolve().parent
        require(
            Path(dbpath).resolve() == self.root / "owner.sqlite",
            "session requires the original owner Store path",
        )
        launch_raw = owner.read_packet(self.root / "owner.sealed.json")
        launch = host.object_bytes(launch_raw)
        require(
            digest(launch_raw) == review["owner_launch_sha256"]
            and launch["format"] == "mcli1-independent-owner-v1"
            and launch["sources"] == owner.SOURCE_EPOCH == owner.current_sources()
            and launch["root"] == owner.root_identity(self.root)
            and launch["owner"] == self.owner_process
            and launch["controller"] == review["controller"]
            and launch["lease"] == self.lease
            and launch["profile"]["target_vm_uuid"] == grant["target"]["vm_uuid"],
            "session is not owned by the sealed original controller",
        )
        self._live()
        with self.store.transaction():
            self._db_live(self.store.db)
            require(
                self.store.db.execute("SELECT 1 FROM transfer_attempt").fetchone()
                is None,
                "prior standalone transfer requires reconciliation",
            )
            require(
                self.store.db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='maintenance_session'"
                ).fetchone()
                is None,
                "session exists; restart cannot resume or renew",
            )
            self.store.db.execute(
                "CREATE TABLE maintenance_session (singleton INTEGER PRIMARY KEY CHECK(singleton=1), review BLOB NOT NULL, state TEXT NOT NULL, outcome BLOB, report BLOB, plan BLOB, approval BLOB)"
            )
            self.store.db.execute(
                "CREATE TABLE maintenance_session_phase (purpose TEXT PRIMARY KEY, grant_sha TEXT NOT NULL, nonce TEXT NOT NULL, state TEXT NOT NULL)"
            )
            self.store.db.execute(
                "INSERT INTO maintenance_session VALUES(1,?,'inspection-ready',NULL,NULL,NULL,NULL)",
                (raw,),
            )
            self.store._event(
                "maintenance-session-created",
                {
                    "review_sha256": sha,
                    "original_lease": self.lease,
                    "native_activation_authorized": False,
                },
            )
        try:
            self.monitor = threading.Thread(target=self._monitor, daemon=True)
            self.monitor.start()
        except BaseException:
            self.revoke("session monitor startup failed")
            raise

    def _db_live(self, db):
        transfer.check_lease(db, self.review_grant)
        lease = db.execute("SELECT * FROM lease").fetchone()
        row = db.execute("SELECT * FROM maintenance_owner").fetchone()
        require(
            {k: lease[k] for k in host.OWNER_KEYS} == self.lease
            and row is not None
            and row["binding"] == self.owner_binding
            and row["state"] == "watching"
            and 0 <= time.monotonic_ns() - row["observed_mono_ns"] <= 5 * 10**9,
            "session original owner or immutable lease changed",
        )

    def _live(self):
        require(not self.closed, "session is closed; no restart")
        require(
            self.review["sources"] == SOURCE_EPOCH == current_sources(),
            "session source cohort changed",
        )
        require(
            digest(owner.read_packet(self.root / "owner.sealed.json"))
            == self.review["owner_launch_sha256"],
            "session original launch changed",
        )
        require(
            self.identity(os.getpid()) == self.review["controller"]
            and self.identity(self.owner_process["pid"]) == self.owner_process
            and self.owner_process["pid"] != self.review["controller"]["pid"],
            "session controller/original owner process identity changed",
        )
        with self.store.transaction():
            self._db_live(self.store.db)

    def _monitor(self):
        try:
            while not self.monitor_stop.wait(0.05):
                self._live()
                watch = self.watch
                require(
                    watch is None or not watch.cancelled.is_set(),
                    "session authority lost",
                )
        except Exception as exc:  # noqa: BLE001 - Any uncertainty fences the original owner.
            if not self.monitor_stop.is_set():
                self.thread_error = type(exc).__name__
                self.revoke("same-boot review expired or authority lost")

    def revoke(self, reason):
        """Signal the existing original owner; never issue a second stop command."""
        self.monitor_stop.set()
        self.closed = True
        with self.store.transaction():
            self.store.db.execute(
                "UPDATE maintenance_session SET state='stopping' WHERE state!='reported-and-stop-reported'"
            )
            self.store.db.execute(
                "UPDATE authority SET active=0, generation=generation+1 WHERE active=1"
            )
            self.store._event("maintenance-session-revoked", {"reason": reason})
        if self.watch is not None:
            self.watch.close()

    def inspect(self, files):
        try:
            self._live()
            self.inspection_files = dict(files)
            return self.controller.run(
                self.inspection, self.inspection_sha, files, _session=self
            )
        except BaseException:
            self.revoke("session inspection failed; no replay")
            raise

    def begin_phase(self, controller, grant, sha, files):
        # Called inside the controller's intent transaction. No external I/O here.
        require(
            controller is self.controller and controller.store is self.store,
            "session belongs to another controller or Store",
        )
        self._db_live(self.store.db)
        state = self.store.db.execute("SELECT * FROM maintenance_session").fetchone()
        purpose = grant["purpose"]
        require(
            not self.closed
            and state["state"]
            == {"inspect": "inspection-ready", "controls": "controls-ready"}[purpose],
            "session phase is not dispatchable",
        )
        if purpose == "inspect":
            require(sha == self.inspection_sha, "inspection grant differs")
        else:
            approved = json.loads(state["approval"])
            require(
                sha == approved["controls_grant_sha256"],
                "approved control grant differs",
            )
        self.store.db.execute(
            "INSERT INTO maintenance_session_phase VALUES(?,?,?,'intent')",
            (purpose, sha, grant["run_nonce"]),
        )
        self.store.db.execute(
            "UPDATE maintenance_session SET state=?", (purpose + "-active",)
        )

    def await_review(self, grant, outcome, raw, receipt, request):
        self._live()
        require(
            receipt["worker_exit"] == 0 and receipt["job_active_processes"] == 0,
            "inspection worker is not reaped",
        )
        spec = json.loads(self.inspection_files["inspection-spec.json"])
        report = canonical(outcome["result"])
        plan = canonical(transfer.probe.control_plan(spec, outcome["result"]))
        # A normal return from the source-bound sender includes pipe/job cleanup.
        # The raw outer response and canonical observation are retained separately.
        with self.store.transaction():
            self._db_live(self.store.db)
            state = self.store.db.execute(
                "SELECT state FROM maintenance_session"
            ).fetchone()[0]
            require(
                state == "inspect-active" and not self.closed, "inspection was revoked"
            )
            self.store.db.execute(
                "UPDATE maintenance_session SET state='awaiting-review',outcome=?,report=?,plan=?",
                (raw, report, plan),
            )
            self.store.db.execute(
                "UPDATE maintenance_session_phase SET state='observed-awaiting-review' WHERE purpose='inspect'"
            )
            self.store._event(
                "maintenance-session-awaiting-review",
                {
                    "raw_outcome_sha256": digest(raw),
                    "observation_sha256": digest(report),
                    "plan_sha256": digest(plan),
                    "guest_dispatch_allowed": False,
                },
            )
        self.store.receipt("serial:" + request["request_id"], 200, raw)
        self.watch = transfer.AuthorityWatch(
            self.controller.database, self.review_grant, self.controller.live_probe
        )
        require(
            self.watch.ready.wait(1) and not self.watch.cancelled.is_set(),
            "review authority monitor unavailable",
        )
        self._live()

    def review_packet(self):
        row = self.store.db.execute("SELECT * FROM maintenance_session").fetchone()
        return {
            "status": row["state"],
            "installation_authority": None,
            "inspection_grant_sha256": self.inspection_sha,
            "observation": json.loads(row["report"]),
            "observation_sha256": digest(row["report"]),
            "raw_outcome_sha256": digest(row["outcome"]),
            "plan": json.loads(row["plan"]),
            "plan_sha256": digest(row["plan"]),
            "review_expires_utc_ns": self.review["review_expires_utc_ns"],
            "review_expires_mono_ns": self.review["review_expires_mono_ns"],
        }

    def approval_template(self, controls_sha):
        row = self.store.db.execute("SELECT * FROM maintenance_session").fetchone()
        require(row["state"] == "awaiting-review", "session is not awaiting review")
        return {
            "format": "mcli1-session-controls-approval-v1",
            "inspection_grant_sha256": self.inspection_sha,
            "controls_grant_sha256": controls_sha,
            "owner_binding_sha256": self.review["owner_binding_sha256"],
            "observation_sha256": digest(row["report"]),
            "plan_sha256": digest(row["plan"]),
            "target": self.grant["target"],
            "original_lease": self.lease,
            "sources": dict(SOURCE_EPOCH),
            "approval_reference": None,
        }

    def controls(self, raw, sha, files, approval, approval_sha):
        try:
            self._live()
            require(
                type(approval) is bytes and digest(approval) == approval_sha,
                "session control approval digest differs",
            )
            accepted = host.object_bytes(approval)
            ref = accepted.get("approval_reference")
            require(
                isinstance(ref, str) and 0 < len(ref) <= 256,
                "session control approval is unbound",
            )
            expected = self.approval_template(sha)
            expected["approval_reference"] = ref
            require(accepted == expected, "session approval scope differs")
            grant = transfer.checked_grant(raw, sha)
            spec = transfer.payloads(grant, files)
            require(grant["purpose"] == "controls", "session requires controls phase")
            for key in (
                "role",
                "run_nonce",
                "generation",
                "target",
                "lease",
                "backup",
                "disk_evidence",
                "sources",
            ):
                require(
                    grant[key] == self.grant[key],
                    "controls changed original session binding",
                )
            for clock in ("utc", "mono"):
                require(
                    grant["phase_window"]["expires_" + clock + "_ns"]
                    <= self.review["review_expires_" + clock + "_ns"],
                    "controls extend original review deadline",
                )
            row = self.store.db.execute("SELECT * FROM maintenance_session").fetchone()
            require(
                files["observation.json"] == row["report"]
                and canonical(
                    transfer.probe.control_plan(spec, json.loads(row["report"]))
                )
                == row["plan"],
                "controls differ from actual reviewed observation/actions",
            )
            watch = self.watch
            require(
                watch is not None and not watch.cancelled.is_set(),
                "review monitor unavailable",
            )
            watch.close()
            require(
                all(not t.is_alive() for t in watch.threads),
                "review sampler did not close",
            )
            self.watch = None
            self._live()
            with self.store.transaction():
                self._db_live(self.store.db)
                require(
                    self.store.db.execute(
                        "SELECT state FROM maintenance_session"
                    ).fetchone()[0]
                    == "awaiting-review",
                    "approval lost race with revocation or another approval",
                )
                self.store.db.execute(
                    "UPDATE maintenance_session SET state='controls-ready',approval=?",
                    (approval,),
                )
                self.store._event(
                    "maintenance-session-controls-approved",
                    {"approval_sha256": approval_sha},
                )
            return self.controller.run(raw, sha, files, _session=self)
        except BaseException:
            self.revoke("controls failed or approval refused; no replay")
            raise

    def stopping(self):
        self.monitor_stop.set()
        self.closed = True
        self.store.db.execute("UPDATE maintenance_session SET state='stopping'")
        self.store.db.execute(
            "UPDATE maintenance_session_phase SET state='stopping' WHERE purpose='controls'"
        )

    def finished(self, receipt):
        owner_row = self.store.db.execute("SELECT * FROM maintenance_owner").fetchone()
        lease = self.store.db.execute("SELECT * FROM lease").fetchone()
        require(
            owner_row["binding"] == self.owner_binding
            and owner_row["state"] == "stop-returned"
            and {k: lease[k] for k in host.OWNER_KEYS} == self.lease,
            "session original owner stop evidence is incomplete",
        )
        self.store.db.execute(
            "UPDATE maintenance_session SET state='reported-and-stop-reported'"
        )
        self.store.db.execute(
            "UPDATE maintenance_session_phase SET state='reported-and-stop-reported' WHERE purpose='controls'"
        )
        self.store._event(
            "maintenance-session-stop-reported",
            {"receipt_sha256": receipt["receipt_sha256"]},
        )

    def close(self):
        if not self.closed:
            self.revoke("session closed; original stop required")
        self.monitor_stop.set()
        if self.watch is not None:
            self.watch.close()
        if self.monitor is not None and self.monitor is not threading.current_thread():
            self.monitor.join(timeout=1)
