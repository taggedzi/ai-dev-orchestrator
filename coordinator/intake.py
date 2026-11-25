"""Durable trusted source-controller protocol, currently scripted development only.

The service Principal is supplied by trusted local composition, never HTTP input.
No live runtime adapter or task-acceptance command is enabled here.
"""

import json
import time
from uuid import uuid4

from .domain import Conflict, canonical, digest, require
from .source import CandidateBinding, Snapshot, SourceFile


class CandidateIntake:
    def __init__(self, coordinator, repository, artifacts):
        require(
            coordinator.principal.role == "service", "trusted intake service required"
        )
        self.core, self.repo, self.artifacts = coordinator, repository, artifacts

    @property
    def db(self):
        return self.core.db

    def _row(self, intake_id):
        row = self.core._one(
            "SELECT * FROM candidate_intakes WHERE id=?",
            (intake_id,),
            "candidate intake",
        )
        require(
            row["producer"] == self.core.principal.id,
            "intake belongs to another producer",
            Conflict,
        )
        require(
            json.loads(row["contract"])["repository_id"]
            == self.repo.marker["repository_id"],
            "intake belongs to another repository",
            Conflict,
        )
        return row

    def _contract(self, attempt_id):
        return self.current_contract(self.core, self.repo, attempt_id)

    @staticmethod
    def current_contract(core, repository, attempt_id):
        attempt = core._attempt(attempt_id)
        milestone = core._one(
            "SELECT * FROM milestones WHERE id=?",
            (attempt["milestone_id"],),
            "milestone",
        )
        project = core._project(milestone["project_id"])
        plan = core._plan(attempt["plan_id"])
        spec = json.loads(plan["spec"])
        operation = core._one(
            "SELECT * FROM operations WHERE attempt_id=?", (attempt_id,), "operation"
        )
        require(attempt["adapter"] == "scripted", "live source intake is not qualified")
        require(
            attempt["state"] == "awaiting_verification"
            and operation["state"] == "returned"
            and json.loads(operation["result"])["outcome"] == "candidate",
            "attempt has no current candidate outcome",
            Conflict,
        )
        require(
            not project["paused"]
            and project["generation"] == attempt["project_generation"],
            "attempt authority is fenced",
            Conflict,
        )
        require(
            milestone["approved_plan_id"] == plan["id"]
            and spec["requirements_revision"] == project["revision"],
            "plan approval is superseded",
            Conflict,
        )
        require(
            milestone["head_revision"] == attempt["input_revision"],
            "attempt input is superseded",
            Conflict,
        )
        approval = core._one(
            "SELECT * FROM approvals WHERE plan_id=?", (plan["id"],), "approval"
        )
        require(
            approval["digest"] == plan["digest"], "approval digest changed", Conflict
        )
        task = next(t for t in spec["tasks"] if t["id"] == attempt["task_key"])
        contract = {
            "format": "candidate-contract-v1",
            "repository_id": repository.marker["repository_id"],
            "project_id": project["id"],
            "project_revision": project["revision"],
            "project_spec": core._revision(project),
            "milestone_id": milestone["id"],
            "plan_id": plan["id"],
            "plan_digest": plan["digest"],
            "approval": approval,
            "attempt_id": attempt_id,
            "attempt_version": attempt["version"],
            "generation": project["generation"],
            "input_revision": attempt["input_revision"],
            "task": task,
            "task_digest": digest(task),
            "classification": "scripted_development",
            "native_stop_proof": None,
        }
        assignment = json.loads(attempt["assignment"])
        if (
            "implementation_actor" in assignment
            and "implementation_context" in assignment
        ):
            contract.update(
                format="candidate-contract-v2",
                implementation_actor=assignment["implementation_actor"],
                implementation_context=assignment["implementation_context"],
            )
        return contract

    def _current(self, contract):
        try:
            return digest(self._contract(contract["attempt_id"])) == digest(contract)
        except Conflict:
            return False

    @staticmethod
    def _binding(contract):
        return CandidateBinding(
            contract["attempt_id"],
            contract["plan_digest"],
            contract["task_digest"],
            contract["generation"],
        )

    def prepare(
        self, attempt_id, snapshot, *, expected_attempt_version, command_id=None
    ):
        require(type(snapshot) is Snapshot, "validated source snapshot required")
        payload = {
            "attempt_id": attempt_id,
            "source_digest": snapshot.digest,
            "repository_id": self.repo.marker["repository_id"],
            "expected_attempt_version": expected_attempt_version,
        }
        cached = self.core.store.recall(
            "candidate.prepare", self.core.principal, payload, command_id
        )
        if cached is not None:
            return cached
        with self.core.store.transaction(write=False):
            contract = self._contract(attempt_id)
        require(
            contract["attempt_version"] == expected_attempt_version
            and type(expected_attempt_version) is int,
            "attempt version changed",
            Conflict,
        )
        # Git reads and file I/O happen outside the SQLite write transaction.
        self.repo.candidate_intent(
            contract["input_revision"],
            snapshot,
            allowed_paths=contract["task"]["allowed_paths"],
            binding=self._binding(contract),
        )
        # Unreferenced immutable blobs after a refused DB admission are harmless.
        # This is artifact storage, never source execution or an authoritative ref.
        for file in snapshot.files().values():
            self.artifacts.put(file.data)
        manifest = self.artifacts.put(canonical(snapshot.manifest).encode())
        require(manifest["sha256"] == snapshot.digest, "snapshot manifest mismatch")

        def apply():
            require(
                self._current(contract),
                "intake authority changed during preflight",
                Conflict,
            )
            existing = self.db.execute(
                "SELECT * FROM candidate_intakes WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            if existing:
                require(
                    existing["producer"] == self.core.principal.id
                    and existing["source_digest"] == snapshot.digest
                    and existing["contract"] == canonical(contract),
                    "attempt already has a different candidate intent",
                    Conflict,
                )
                return {
                    "intake_id": existing["id"],
                    "version": existing["version"],
                    "state": existing["state"],
                }
            intake_id = uuid4().hex
            self.db.execute(
                "INSERT INTO candidate_intakes(id,attempt_id,project_id,producer,version,state,contract,source_digest,created_ns) VALUES(?,?,?,?,1,'prepared',?,?,?)",
                (
                    intake_id,
                    attempt_id,
                    contract["project_id"],
                    self.core.principal.id,
                    canonical(contract),
                    snapshot.digest,
                    time.time_ns(),
                ),
            )
            return {"intake_id": intake_id, "version": 1, "state": "prepared"}

        return self.core._write(
            "candidate.prepare",
            payload,
            apply,
            command_id,
        )

    def begin(self, intake_id, *, expected_version, command_id=None):
        def apply():
            row = self._row(intake_id)
            self.core._version(row, expected_version)
            require(
                row["state"] == "prepared",
                "intake already sent or held; reconcile without replay",
                Conflict,
            )
            require(
                self._current(json.loads(row["contract"])),
                "intake authority is fenced",
                Conflict,
            )
            self.db.execute(
                "UPDATE candidate_intakes SET state='possible_send',version=version+1,sent_ns=? WHERE id=?",
                (time.time_ns(), intake_id),
            )
            return {
                "intake_id": intake_id,
                "version": row["version"] + 1,
                "state": "possible_send",
            }

        return self.core._write(
            "candidate.begin",
            {"intake_id": intake_id, "expected_version": expected_version},
            apply,
            command_id,
        )

    def _load(self, intake_id):
        with self.core.store.transaction(write=False):
            row = self._row(intake_id)
        manifest = json.loads(self.artifacts.read(row["source_digest"]))
        snapshot = Snapshot(
            {
                item["path"]: SourceFile(
                    self.artifacts.read(item["sha256"]), item["mode"]
                )
                for item in manifest
            }
        )
        require(
            snapshot.digest == row["source_digest"],
            "stored source manifest changed",
            Conflict,
        )
        return row, json.loads(row["contract"]), snapshot

    def _hold(self, intake_id, reason):
        def apply():
            row = self._row(intake_id)
            if row["state"] != "conflicting":
                self.db.execute(
                    "UPDATE candidate_intakes SET state='held',version=version+1 WHERE id=?",
                    (intake_id,),
                )
            return {
                "intake_id": intake_id,
                "state": "held",
                "reason": reason,
                "task_accepted": False,
            }

        return self.core._write(
            "candidate.hold", {"intake_id": intake_id, "reason": reason}, apply, None
        )

    def _record(self, intake_id, contract, observed, snapshot):
        before = self.repo.snapshot(contract["input_revision"])
        for file in before.files().values():
            self.artifacts.put(file.data)
        packet = {
            "format": "candidate-review-packet-v1",
            "contract": contract,
            "candidate": observed,
            "source_manifest": snapshot.manifest,
            "input_source_manifest": before.manifest,
            "check_results": [],
            "review_results": [],
            "task_accepted": False,
        }
        packet_ref = self.artifacts.put(canonical(packet).encode())
        receipt = {
            "candidate": observed,
            "review_packet": packet_ref,
            "classification": "scripted_development",
            "native_stop_proof": None,
        }
        checksum = digest(receipt)
        self.artifacts.put(canonical(receipt).encode())

        def apply():
            row = self._row(intake_id)
            require(
                row["sent_ns"] is not None,
                "intake was never durably dispatched",
                Conflict,
            )
            require(
                row["contract"] == canonical(contract),
                "intake binding changed",
                Conflict,
            )
            self.db.execute(
                "INSERT OR IGNORE INTO intake_observations VALUES(?,?,?,?)",
                (intake_id, checksum, canonical(receipt), time.time_ns()),
            )
            if row["receipt_digest"] and row["receipt_digest"] != checksum:
                self.core._fence(row["project_id"])
                self.db.execute(
                    "UPDATE candidate_intakes SET state='conflicting',version=version+1 WHERE id=?",
                    (intake_id,),
                )
                return {
                    "intake_id": intake_id,
                    "current": False,
                    "conflicting": True,
                    "task_accepted": False,
                }
            live = self._current(contract) and row["state"] != "conflicting"
            state = (
                "sealed"
                if live
                else "held"
                if row["state"] != "conflicting"
                else "conflicting"
            )
            duplicate = row["receipt_digest"] == checksum
            if not duplicate or row["state"] != state:
                self.db.execute(
                    "UPDATE candidate_intakes SET state=?,version=version+1,receipt=?,receipt_digest=? WHERE id=?",
                    (state, canonical(receipt), checksum, intake_id),
                )
            return {
                "intake_id": intake_id,
                "current": live,
                "state": state,
                "revision": observed["revision"],
                "review_packet": packet_ref,
                "task_accepted": False,
                "simulated": True,
                "duplicate": duplicate,
            }

        return self.core._write(
            "candidate.observe",
            {"intake_id": intake_id, "receipt_digest": checksum},
            apply,
            None,
        )

    def run(self, intake_id, *, expected_version):
        # Admission is committed before any Git mutation. A second run refuses;
        # explicit reconciliation below only observes an already-existing ref.
        self.begin(intake_id, expected_version=expected_version)
        try:
            _row, contract, snapshot = self._load(intake_id)
            self.repo.seal(
                contract["input_revision"],
                snapshot,
                allowed_paths=contract["task"]["allowed_paths"],
                binding=self._binding(contract),
            )
            observed = self.repo.observe_candidate(
                contract["input_revision"],
                snapshot,
                allowed_paths=contract["task"]["allowed_paths"],
                binding=self._binding(contract),
            )
        except (Conflict, OSError, ValueError) as error:
            self._hold(intake_id, str(error))
            raise
        return self._record(intake_id, contract, observed, snapshot)

    def reconcile(self, intake_id):
        try:
            row, contract, snapshot = self._load(intake_id)
            require(row["sent_ns"] is not None, "intake was not sent", Conflict)
            observed = self.repo.observe_candidate(
                contract["input_revision"],
                snapshot,
                allowed_paths=contract["task"]["allowed_paths"],
                binding=self._binding(contract),
            )
        except (Conflict, OSError, ValueError) as error:
            self._hold(intake_id, str(error))
            raise
        return self._record(intake_id, contract, observed, snapshot)
