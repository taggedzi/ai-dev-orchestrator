"""Durable integration staging, fresh evidence, and one serialized promotion."""

import json
import re
import time
from uuid import uuid4

from .domain import (
    Conflict,
    canonical,
    digest,
    fields,
    ident,
    integer,
    require,
    text,
    unique,
)
from .verification import DIMENSIONS, Verification


class Integration:
    def __init__(self, coordinator, repository, artifacts):
        self.core, self.repo, self.artifacts = coordinator, repository, artifacts
        self.verify = Verification(coordinator, repository, artifacts)

    @property
    def db(self):
        return self.core.db

    def _proposal(self, proposal_id, *, owned=False):
        row = self.core._one(
            "SELECT * FROM integration_proposals WHERE id=?",
            (proposal_id,),
            "integration proposal",
        )
        if owned:
            self.verify._service()
            require(
                row["producer"] == self.core.principal.id,
                "proposal belongs to another controller",
                Conflict,
            )
        return row

    def _commit_id(self, value, label):
        require(
            type(value) is str and re.fullmatch(r"[0-9a-f]{40}", value) is not None,
            f"invalid {label}",
        )
        return value

    def _mapping_binding(
        self, attempt_id, previous_head, new_head, authority_generation
    ):
        return {
            "format": "diverged-head-mapping-v1",
            "attempt_id": attempt_id,
            "previous_head": previous_head,
            "new_head": new_head,
            "authority_generation": authority_generation,
        }

    def _mapping_claim(self, row):
        return {
            "id": row["id"],
            "attempt_id": row["attempt_id"],
            "previous_head": row["previous_head"],
            "new_head": row["new_head"],
            "authority_generation": row["authority_generation"],
            "authorization_digest": row["authorization_digest"],
        }

    def _require_mapping(self, contract, new_head, *, proposal_id):
        attempt = self.core._attempt(contract["attempt_id"])
        milestone = self.core._one(
            "SELECT * FROM milestones WHERE id=?",
            (contract["milestone_id"],),
            "milestone",
        )
        project = self.core._project(contract["project_id"])
        require(
            milestone["head_revision"]
            == contract["input_revision"]
            == attempt["input_revision"],
            "integration head changed",
            Conflict,
        )
        row = self.db.execute(
            "SELECT * FROM integration_head_mappings WHERE attempt_id=?",
            (contract["attempt_id"],),
        ).fetchone()
        require(row is not None, "diverged-head mapping missing", Conflict)
        require(
            row["project_id"] == contract["project_id"]
            and row["attempt_id"] == contract["attempt_id"]
            and row["previous_head"] == contract["input_revision"]
            and row["new_head"] == new_head,
            "diverged-head mapping differs",
            Conflict,
        )
        require(
            row["authority_generation"]
            == project["generation"]
            == contract["generation"]
            == attempt["project_generation"]
            and attempt["state"] == "awaiting_verification",
            "diverged-head mapping is stale",
            Conflict,
        )
        require(
            row["authorization_digest"]
            == digest(
                self._mapping_binding(
                    row["attempt_id"],
                    row["previous_head"],
                    row["new_head"],
                    row["authority_generation"],
                )
            ),
            "diverged-head mapping differs",
            Conflict,
        )
        if row["state"] == "consumed":
            require(
                proposal_id is not None and row["consumed_by"] == proposal_id,
                "diverged-head mapping already consumed",
                Conflict,
            )
        else:
            require(
                row["state"] == "authorized" and row["consumed_by"] is None,
                "diverged-head mapping differs",
                Conflict,
            )
        return row

    def _authority(self, intent):
        self.verify._current(intent["intake_reference"])
        milestone = self.core._one(
            "SELECT * FROM milestones WHERE id=?",
            (intent["contract"]["milestone_id"],),
            "milestone",
        )
        claim = intent.get("head_mapping")
        if milestone["head_revision"] == intent["expected_head"]:
            require(claim is None, "diverged-head mapping differs", Conflict)
        else:
            require(claim is not None, "diverged-head mapping missing", Conflict)
            require(
                set(claim)
                == {
                    "id",
                    "attempt_id",
                    "previous_head",
                    "new_head",
                    "authority_generation",
                    "authorization_digest",
                },
                "diverged-head mapping differs",
                Conflict,
            )
            existing = self.db.execute(
                "SELECT id FROM integration_proposals WHERE intake_id=?",
                (intent["intake_id"],),
            ).fetchone()
            row = self._require_mapping(
                intent["contract"],
                intent["expected_head"],
                proposal_id=existing["id"] if existing else None,
            )
            require(
                claim == self._mapping_claim(row),
                "diverged-head mapping differs",
                Conflict,
            )
        evidence = intent["candidate_evidence"]
        for item in [*evidence["check_evidence"], evidence["review_evidence"]]:
            row = self.core._one(
                "SELECT * FROM verification_operations WHERE id=?",
                (item["operation_id"],),
                "candidate evidence",
            )
            require(
                row["state"] == "returned"
                and row["receipt_digest"] == item["receipt_digest"],
                "candidate evidence was superseded or held",
                Conflict,
            )

    def authorize_diverged_head(
        self,
        attempt_id,
        previous_head,
        new_head,
        authority_generation,
        *,
        command_id=None,
    ):
        """Record one exact base change. Does not stage, promote, or accept."""
        ident(attempt_id, "attempt id")
        previous_head = self._commit_id(previous_head, "previous expected head")
        new_head = self._commit_id(new_head, "new expected head")
        integer(authority_generation, "authority generation")
        require(previous_head != new_head, "diverged-head mapping differs", Conflict)
        payload = {
            "attempt_id": attempt_id,
            "previous_head": previous_head,
            "new_head": new_head,
            "authority_generation": authority_generation,
        }
        cached = self.core.store.recall(
            "integration.authorize_head", self.core.principal, payload, command_id
        )
        if cached is not None:
            return cached
        with self.core.store.transaction(write=False):
            self._authorize_binding(
                attempt_id, previous_head, new_head, authority_generation
            )
        require(
            self.repo.descends_from(previous_head, new_head),
            "diverged-head mapping differs",
            Conflict,
        )

        def apply():
            self._authorize_binding(
                attempt_id, previous_head, new_head, authority_generation
            )
            binding = self._mapping_binding(
                attempt_id, previous_head, new_head, authority_generation
            )
            checksum = digest(binding)
            row = self.db.execute(
                "SELECT * FROM integration_head_mappings WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if row is not None:
                same = (
                    row["authorization_digest"] == checksum
                    and row["previous_head"] == previous_head
                    and row["new_head"] == new_head
                    and row["authority_generation"] == authority_generation
                    and row["actor"] == self.core.principal.id
                )
                require(
                    same and row["state"] == "authorized",
                    "diverged-head mapping already consumed"
                    if row["state"] == "consumed" and same
                    else "diverged-head mapping differs",
                    Conflict,
                )
                return {
                    "mapping_id": row["id"],
                    "state": row["state"],
                    "authorization_digest": checksum,
                    "consumed": False,
                    "task_accepted": False,
                }
            mapping_id = uuid4().hex
            attempt = self.core._attempt(attempt_id)
            self.db.execute(
                "INSERT INTO integration_head_mappings(id,attempt_id,project_id,previous_head,new_head,authority_generation,authorization_digest,actor,state,created_ns) VALUES(?,?,?,?,?,?,?,?,'authorized',?)",
                (
                    mapping_id,
                    attempt_id,
                    self._mapping_project(attempt),
                    previous_head,
                    new_head,
                    authority_generation,
                    checksum,
                    self.core.principal.id,
                    time.time_ns(),
                ),
            )
            return {
                "mapping_id": mapping_id,
                "state": "authorized",
                "authorization_digest": checksum,
                "consumed": False,
                "task_accepted": False,
            }

        return self.core._write(
            "integration.authorize_head",
            payload,
            apply,
            command_id,
            developer=True,
        )

    def _mapping_project(self, attempt):
        milestone = self.core._one(
            "SELECT * FROM milestones WHERE id=?",
            (attempt["milestone_id"],),
            "milestone",
        )
        return milestone["project_id"]

    def _authorize_binding(self, attempt_id, previous_head, new_head, generation):
        attempt = self.core._attempt(attempt_id)
        milestone = self.core._one(
            "SELECT * FROM milestones WHERE id=?",
            (attempt["milestone_id"],),
            "milestone",
        )
        project = self.core._project(milestone["project_id"])
        require(
            generation == project["generation"] == attempt["project_generation"]
            and attempt["state"] == "awaiting_verification"
            and project["paused"] == 0,
            "diverged-head mapping is stale",
            Conflict,
        )
        require(
            previous_head == milestone["head_revision"] == attempt["input_revision"]
            and new_head != previous_head,
            "diverged-head mapping differs",
            Conflict,
        )

    def _named_head(self, intake_id, expected_head):
        if expected_head is None:
            return
        self._commit_id(expected_head, "expected head")
        with self.core.store.transaction(write=False):
            contract = json.loads(
                self.core._one(
                    "SELECT * FROM candidate_intakes WHERE id=?",
                    (intake_id,),
                    "candidate intake",
                )["contract"]
            )
            if expected_head == contract["input_revision"]:
                return
            existing = self.db.execute(
                "SELECT id FROM integration_proposals WHERE intake_id=?",
                (intake_id,),
            ).fetchone()
            self._require_mapping(
                contract,
                expected_head,
                proposal_id=existing["id"] if existing else None,
            )

    def prepare(self, intake_id, *, expected_head=None, command_id=None):
        self.verify._service()
        payload = {"intake_id": intake_id}
        if expected_head is not None:
            payload["expected_head"] = expected_head
        cached = self.core.store.recall(
            "integration.prepare", self.core.principal, payload, command_id
        )
        if cached is not None:
            return cached
        self._named_head(intake_id, expected_head)
        gate = self.verify.gate(intake_id)
        require(
            gate["development_ready_for_integration"],
            "candidate evidence is incomplete or held",
            Conflict,
        )
        context = self.verify._candidate(intake_id)
        contract, intake = context["contract"], context["row"]
        intent = {
            "format": "integration-intent-v1",
            "classification": "scripted_development",
            "intake_id": intake_id,
            "repository_id": self.repo.marker["repository_id"],
            "intake_reference": {
                key: intake[key] for key in ("id", "version", "receipt_digest")
            },
            "contract": contract,
            "candidate_evidence": gate,
            "candidate_revision": gate["candidate_revision"],
            "expected_head": contract["input_revision"]
            if expected_head is None
            else expected_head,
            "allowed_paths": contract["task"]["allowed_paths"],
        }

        def apply():
            if intent["expected_head"] != contract["input_revision"]:
                existing = self.db.execute(
                    "SELECT id FROM integration_proposals WHERE intake_id=?",
                    (intake_id,),
                ).fetchone()
                intent["head_mapping"] = self._mapping_claim(
                    self._require_mapping(
                        contract,
                        intent["expected_head"],
                        proposal_id=existing["id"] if existing else None,
                    )
                )
            self._authority(intent)
            old = self.db.execute(
                "SELECT * FROM integration_proposals WHERE intake_id=?", (intake_id,)
            ).fetchone()
            if old:
                require(
                    old["intent"] == canonical(intent)
                    and old["producer"] == self.core.principal.id,
                    "intake already has another integration intent",
                    Conflict,
                )
                return {
                    "proposal_id": old["id"],
                    "version": old["version"],
                    "state": old["state"],
                }
            proposal_id = uuid4().hex
            self.db.execute(
                "INSERT INTO integration_proposals(id,intake_id,project_id,producer,version,state,intent,created_ns) VALUES(?,?,?,?,1,'prepared',?,?)",
                (
                    proposal_id,
                    intake_id,
                    contract["project_id"],
                    self.core.principal.id,
                    canonical(intent),
                    time.time_ns(),
                ),
            )
            return {"proposal_id": proposal_id, "version": 1, "state": "prepared"}

        return self.core._write(
            "integration.prepare",
            payload,
            apply,
            command_id,
        )

    def begin(self, proposal_id, *, expected_version, command_id=None):
        def apply():
            row = self._proposal(proposal_id, owned=True)
            self.core._version(row, expected_version)
            require(
                row["state"] == "prepared",
                "stage may already be sent; reconcile without replay",
                Conflict,
            )
            intent = json.loads(row["intent"])
            self._authority(intent)
            if "head_mapping" in intent:
                claim = intent["head_mapping"]
                consumed = self.db.execute(
                    "UPDATE integration_head_mappings SET state='consumed',consumed_by=?,consumed_ns=? WHERE id=? AND attempt_id=? AND state='authorized' AND consumed_by IS NULL AND authorization_digest=? AND previous_head=? AND new_head=? AND authority_generation=?",
                    (
                        proposal_id,
                        time.time_ns(),
                        claim["id"],
                        claim["attempt_id"],
                        claim["authorization_digest"],
                        claim["previous_head"],
                        claim["new_head"],
                        claim["authority_generation"],
                    ),
                )
                require(
                    consumed.rowcount == 1,
                    "diverged-head mapping already consumed",
                    Conflict,
                )
            self.db.execute(
                "UPDATE integration_proposals SET state='possible_send',version=version+1,sent_ns=? WHERE id=?",
                (time.time_ns(), proposal_id),
            )
            return {
                "proposal_id": proposal_id,
                "state": "possible_send",
                "version": row["version"] + 1,
            }

        return self.core._write(
            "integration.begin",
            {"proposal_id": proposal_id, "expected_version": expected_version},
            apply,
            command_id,
        )

    def _arguments(self, row):
        intent = json.loads(row["intent"])
        require(
            intent["repository_id"] == self.repo.marker["repository_id"],
            "integration repository differs",
            Conflict,
        )
        return intent, {
            "candidate": intent["candidate_revision"],
            "expected_head": intent["expected_head"],
            "proposal_id": row["id"],
            "authorization_digest": digest(intent),
            "allowed_paths": intent["allowed_paths"],
        }

    def _hold(self, proposal_id, reason):
        def apply():
            row = self._proposal(proposal_id, owned=True)
            if row["state"] != "conflicting":
                self.db.execute(
                    "UPDATE integration_proposals SET state='held',version=version+1 WHERE id=?",
                    (proposal_id,),
                )
            return {
                "proposal_id": proposal_id,
                "state": "conflicting" if row["state"] == "conflicting" else "held",
                "reason": reason,
                "task_accepted": False,
            }

        return self.core._write(
            "integration.hold",
            {"proposal_id": proposal_id, "reason": reason},
            apply,
            None,
        )

    def _record(self, reference, stage):
        intent = json.loads(reference["intent"])
        for revision in (stage["expected_head"], stage["revision"]):
            for file in self.repo.snapshot(revision).files().values():
                self.artifacts.put(file.data)
        packet = {
            "format": "integration-packet-v1",
            "intent": intent,
            "stage": stage,
            "candidate_evidence": intent["candidate_evidence"],
            "regression_results": [],
            "task_accepted": False,
        }
        packet_ref = self.artifacts.put(canonical(packet).encode())
        receipt = {
            "stage": stage,
            "packet": packet_ref,
            "classification": "scripted_development",
        }
        checksum = digest(receipt)
        self.artifacts.put(canonical(receipt).encode())

        def apply():
            row = self._proposal(reference["id"], owned=True)
            require(
                row["sent_ns"] is not None and row["intent"] == reference["intent"],
                "integration was not dispatched with this intent",
                Conflict,
            )
            self.db.execute(
                "INSERT OR IGNORE INTO integration_stage_observations VALUES(?,?,?,?)",
                (row["id"], checksum, canonical(receipt), time.time_ns()),
            )
            if row["receipt_digest"] and row["receipt_digest"] != checksum:
                self.core._fence(row["project_id"])
                self.db.execute(
                    "UPDATE integration_proposals SET state='conflicting',version=version+1 WHERE id=?",
                    (row["id"],),
                )
                return {
                    "proposal_id": row["id"],
                    "current": False,
                    "conflicting": True,
                    "task_accepted": False,
                }
            try:
                self._authority(intent)
                current = row["state"] != "conflicting"
            except Conflict:
                current = False
            state = (
                "staged"
                if current
                else "conflicting"
                if row["state"] == "conflicting"
                else "held"
            )
            duplicate = row["receipt_digest"] == checksum
            if not duplicate or row["state"] != state:
                self.db.execute(
                    "UPDATE integration_proposals SET state=?,version=version+1,receipt=?,receipt_digest=? WHERE id=?",
                    (state, canonical(receipt), checksum, row["id"]),
                )
            return {
                "proposal_id": row["id"],
                "state": state,
                "current": current,
                "revision": stage["revision"],
                "packet": packet_ref,
                "duplicate": duplicate,
                "task_accepted": False,
            }

        return self.core._write(
            "integration.observe",
            {"proposal_id": reference["id"], "receipt_digest": checksum},
            apply,
            None,
        )

    def run(self, proposal_id, *, expected_version):
        self.begin(proposal_id, expected_version=expected_version)
        with self.core.store.transaction(write=False):
            row = self._proposal(proposal_id, owned=True)
        _, arguments = self._arguments(row)
        try:
            self.repo.stage_integration(**arguments)
            stage = self.repo.observe_integration(**arguments)
        except (ValueError, OSError) as error:
            self._hold(proposal_id, str(error))
            raise
        return self._record(row, stage)

    def reconcile(self, proposal_id):
        with self.core.store.transaction(write=False):
            row = self._proposal(proposal_id, owned=True)
        require(row["sent_ns"] is not None, "integration was never sent", Conflict)
        _, arguments = self._arguments(row)
        try:
            stage = self.repo.observe_integration(**arguments)
        except (ValueError, OSError) as error:
            self._hold(proposal_id, str(error))
            raise
        return self._record(row, stage)

    def _validated(self, proposal_id):
        with self.core.store.transaction(write=False):
            row = self._proposal(proposal_id)
            require(
                row["state"] == "staged",
                "integration proposal is held or incomplete",
                Conflict,
            )
            intent, arguments = self._arguments(row)
            self._authority(intent)
        gate = self.verify.gate(row["intake_id"])
        require(
            gate == intent["candidate_evidence"],
            "candidate evidence changed before integration",
            Conflict,
        )
        receipt = json.loads(row["receipt"])
        require(
            self.verify._json(row["receipt_digest"]) == receipt,
            "integration receipt changed",
            Conflict,
        )
        stage = self.repo.observe_integration(**arguments)
        require(stage == receipt["stage"], "staged integration changed", Conflict)
        packet = self.verify._json(receipt["packet"]["sha256"])
        require(
            packet["intent"] == intent and packet["stage"] == stage,
            "integration packet changed",
            Conflict,
        )
        for manifest in (stage["source_manifest"], stage["input_source_manifest"]):
            for item in manifest:
                require(
                    len(self.artifacts.read(item["sha256"])) == item["bytes"],
                    "integration artifact size differs",
                    Conflict,
                )
        return row, intent, receipt

    def approve_regressions(
        self, proposal_id, spec, checksum, *, expected_version, command_id=None
    ):
        self.core.principal.developer()
        spec = json.loads(canonical(spec))
        require(digest(spec) == checksum, "regression policy digest differs", Conflict)
        payload = {
            "proposal_id": proposal_id,
            "policy_digest": checksum,
            "expected_version": expected_version,
        }
        cached = self.core.store.recall(
            "integration.approve_regressions", self.core.principal, payload, command_id
        )
        if cached is not None:
            return cached
        reference, intent, _receipt = self._validated(proposal_id)
        self.core._version(reference, expected_version)
        fields(spec, ("classification", "checks"), "regression policy")
        require(
            spec["classification"] == "scripted_development",
            "live regression execution is not qualified",
        )
        require(
            type(spec["checks"]) is list and spec["checks"],
            "regressions must be nonempty",
        )
        ids = []
        for profile in spec["checks"]:
            fields(
                profile,
                ("check_id", "producer", "definition_digest", "environment_digest"),
                "regression profile",
            )
            ids.append(ident(profile["check_id"]))
            text(profile["producer"], "regression producer", 200)
            require(
                profile["producer"] != intent["contract"]["implementation_actor"],
                "implementer cannot supply integration regressions",
            )
            definition = self.verify._json(profile["definition_digest"])
            fields(definition, ("check", "cases"), "regression definition")
            check = definition["check"]
            fields(check, ("id", "argv", "timeout_seconds"), "regression command")
            require(
                check["id"] == profile["check_id"]
                and type(check["argv"]) is list
                and 1 <= len(check["argv"]) <= 100,
                "invalid regression command",
            )
            integer(check["timeout_seconds"], "regression timeout", maximum=3600)
            for argument in check["argv"]:
                text(argument, "regression argument")
            require(
                type(definition["cases"]) is list
                and 1 <= len(definition["cases"]) <= 1000,
                "observable regressions required",
            )
            for case in definition["cases"]:
                fields(case, ("id", "input", "expected"), "regression case")
                ident(case["id"])
            unique([case["id"] for case in definition["cases"]], "regression case")
            require(
                self.verify._json(profile["environment_digest"]).get("classification")
                == "scripted_development",
                "live regression environment is not qualified",
            )
        unique(ids, "regression check")

        def apply():
            self._authority(intent)
            current = self._proposal(proposal_id)
            require(
                current["state"] == "staged"
                and current["version"] == reference["version"],
                "proposal changed during policy review",
                Conflict,
            )
            old = self.db.execute(
                "SELECT * FROM integration_policies WHERE proposal_id=?", (proposal_id,)
            ).fetchone()
            if old:
                require(
                    old["digest"] == checksum,
                    "proposal already has a different regression policy",
                    Conflict,
                )
                return {"policy_id": old["id"], "digest": checksum, "approved": True}
            policy_id = uuid4().hex
            self.db.execute(
                "INSERT INTO integration_policies VALUES(?,?,?,?,?,?)",
                (
                    policy_id,
                    proposal_id,
                    checksum,
                    canonical(spec),
                    self.core.principal.id,
                    time.time_ns(),
                ),
            )
            return {"policy_id": policy_id, "digest": checksum, "approved": True}

        return self.core._write(
            "integration.approve_regressions",
            payload,
            apply,
            command_id,
            developer=True,
        )

    def prepare_regressions(self, proposal_id, *, command_id=None):
        self.verify._service()
        payload = {"proposal_id": proposal_id}
        cached = self.core.store.recall(
            "integration.prepare_regressions", self.core.principal, payload, command_id
        )
        if cached is not None:
            return cached
        reference, intent, receipt = self._validated(proposal_id)
        with self.core.store.transaction(write=False):
            policy = self.core._one(
                "SELECT * FROM integration_policies WHERE proposal_id=?",
                (proposal_id,),
                "regression policy",
            )
        spec = json.loads(policy["spec"])
        require(digest(spec) == policy["digest"], "regression policy changed", Conflict)

        def apply():
            self._authority(intent)
            row = self._proposal(proposal_id)
            require(
                row["state"] == "staged" and row["version"] == reference["version"],
                "proposal changed before regression admission",
                Conflict,
            )
            results = []
            for profile in spec["checks"]:
                old = self.db.execute(
                    "SELECT * FROM integration_regressions WHERE proposal_id=? AND key=?",
                    (proposal_id, profile["check_id"]),
                ).fetchone()
                if old:
                    require(
                        old["scheduler"] == self.core.principal.id,
                        "regression belongs to another scheduler",
                        Conflict,
                    )
                    results.append(
                        {
                            "operation_id": old["id"],
                            "version": old["version"],
                            "state": old["state"],
                        }
                    )
                    continue
                operation_id = uuid4().hex
                binding = {
                    "format": "integration-regression-binding-v1",
                    "phase": "integration",
                    "kind": "check",
                    "operation_id": operation_id,
                    "proposal_id": proposal_id,
                    "proposal_receipt_digest": row["receipt_digest"],
                    "policy_digest": policy["digest"],
                    "candidate_revision": intent["candidate_revision"],
                    "expected_head": intent["expected_head"],
                    "subject_revision": receipt["stage"]["revision"],
                    "source_digest": receipt["stage"]["source_digest"],
                    "packet_digest": receipt["packet"]["sha256"],
                    "profile": profile,
                    "generation": intent["contract"]["generation"],
                    "classification": "scripted_development",
                }
                self.db.execute(
                    "INSERT INTO integration_regressions(id,proposal_id,key,producer,scheduler,version,state,binding,created_ns) VALUES(?,?,?,?,?,1,'prepared',?,?)",
                    (
                        operation_id,
                        proposal_id,
                        profile["check_id"],
                        profile["producer"],
                        self.core.principal.id,
                        canonical(binding),
                        time.time_ns(),
                    ),
                )
                results.append(
                    {"operation_id": operation_id, "version": 1, "state": "prepared"}
                )
            return {"operations": results, "task_accepted": False}

        return self.core._write(
            "integration.prepare_regressions",
            payload,
            apply,
            command_id,
        )

    def _regression(self, operation_id):
        return self.core._one(
            "SELECT * FROM integration_regressions WHERE id=?",
            (operation_id,),
            "integration regression",
        )

    def begin_regression(self, operation_id, *, expected_version, command_id=None):
        self.verify._service()
        with self.core.store.transaction(write=False):
            reference = self._regression(operation_id)
        require(
            reference["scheduler"] == self.core.principal.id,
            "regression belongs to another scheduler",
            Conflict,
        )
        _proposal, intent, _receipt = self._validated(reference["proposal_id"])

        def apply():
            self._authority(intent)
            proposal = self._proposal(reference["proposal_id"])
            row = self._regression(operation_id)
            self.core._version(row, expected_version)
            require(
                proposal["state"] == "staged"
                and proposal["receipt_digest"]
                == json.loads(row["binding"])["proposal_receipt_digest"],
                "proposal changed before dispatch",
                Conflict,
            )
            require(
                row["state"] == "prepared",
                "regression may already be sent; do not replay",
                Conflict,
            )
            self.db.execute(
                "UPDATE integration_regressions SET state='possible_send',version=version+1,sent_ns=? WHERE id=?",
                (time.time_ns(), operation_id),
            )
            return {
                "operation_id": operation_id,
                "state": "possible_send",
                "version": row["version"] + 1,
            }

        return self.core._write(
            "integration.begin_regression",
            {"operation_id": operation_id, "expected_version": expected_version},
            apply,
            command_id,
        )

    def submit_regression(self, operation_id, receipt, *, command_id=None):
        self.verify._service()
        receipt = json.loads(canonical(receipt))
        with self.core.store.transaction(write=False):
            reference = self._regression(operation_id)
        require(
            reference["producer"] == self.core.principal.id,
            "regression producer is not assigned",
            Conflict,
        )
        require(
            reference["sent_ns"] is not None, "regression was not dispatched", Conflict
        )
        assessment = self.verify._assess({**reference, "kind": "check"}, receipt)
        envelope = {
            "receipt": receipt,
            "assessment": assessment,
            "classification": "scripted_development",
        }
        checksum = digest(envelope)
        self.artifacts.put(canonical(envelope).encode())

        def apply():
            row = self._regression(operation_id)
            proposal = self._proposal(row["proposal_id"])
            self.db.execute(
                "INSERT OR IGNORE INTO integration_regression_observations VALUES(?,?,?,?)",
                (operation_id, checksum, canonical(envelope), time.time_ns()),
            )
            if row["receipt_digest"] and row["receipt_digest"] != checksum:
                self.core._fence(proposal["project_id"])
                self.db.execute(
                    "UPDATE integration_regressions SET state='conflicting',version=version+1 WHERE id=?",
                    (operation_id,),
                )
                return {
                    "operation_id": operation_id,
                    "current": False,
                    "conflicting": True,
                    "task_accepted": False,
                }
            try:
                self._authority(json.loads(proposal["intent"]))
                current = (
                    proposal["state"] == "staged"
                    and row["state"] != "conflicting"
                    and proposal["receipt_digest"]
                    == json.loads(row["binding"])["proposal_receipt_digest"]
                )
            except Conflict:
                current = False
            state = (
                "returned"
                if current and assessment["applicable"]
                else "conflicting"
                if row["state"] == "conflicting"
                else "held"
            )
            duplicate = row["receipt_digest"] == checksum
            if not duplicate or row["state"] != state:
                self.db.execute(
                    "UPDATE integration_regressions SET state=?,version=version+1,receipt=?,receipt_digest=? WHERE id=?",
                    (state, canonical(envelope), checksum, operation_id),
                )
            return {
                "operation_id": operation_id,
                "current": current,
                "state": state,
                "passed": current and assessment["passed"],
                "duplicate": duplicate,
                "task_accepted": False,
            }

        return self.core._write(
            "integration.regression_observe",
            {"operation_id": operation_id, "receipt_digest": checksum},
            apply,
            command_id,
        )

    def _evidence_spec(self, reference, intent, receipt, spec):
        fields(
            spec,
            ("classification", "phase", "checks", "review"),
            "integrated evidence policy",
        )
        require(
            spec["classification"] == "scripted_development"
            and spec["phase"] == "integrated",
            "live integrated execution is not qualified",
        )
        require(
            receipt["stage"]["revision"] != intent["candidate_revision"],
            "candidate evidence already binds this integrated commit",
            Conflict,
        )
        context = self.verify._candidate(intent["intake_id"])
        with self.core.store.transaction(write=False):
            candidate = self.core._one(
                "SELECT * FROM verification_policies WHERE intake_id=?",
                (intent["intake_id"],),
                "verification policy",
            )
        approved = json.loads(candidate["spec"])
        require(
            digest(approved) == candidate["digest"],
            "candidate verification policy changed",
            Conflict,
        )
        require(
            spec["checks"] == approved["checks"],
            "integrated checks differ from the approved candidate policy",
            Conflict,
        )
        review = spec["review"]
        fields(
            review,
            ("producer", "profile_digest", "rubric_digest", "context_digest"),
            "integrated review profile",
        )
        text(review["producer"], "integrated review producer", 200)
        producers = {item["producer"] for item in spec["checks"]}
        require(
            review["producer"]
            not in producers
            | {
                intent["contract"]["implementation_actor"],
                context["row"]["producer"],
            },
            "reviewer must be separate from implementer, checker and Git intake",
        )
        require(
            self.verify._json(review["profile_digest"]).get("classification")
            == "scripted_development",
            "live reviewer is not qualified",
        )
        rubric = self.verify._json(review["rubric_digest"])
        fields(rubric, ("version", "dimensions"), "review rubric")
        ident(rubric["version"])
        require(
            type(rubric["dimensions"]) is list
            and len(rubric["dimensions"]) == len(DIMENSIONS)
            and set(rubric["dimensions"]) == set(DIMENSIONS),
            "review rubric must cover all required dimensions",
        )
        session = self.verify._json(review["context_digest"])
        fields(session, ("session_id", "packet_digest", "purpose"), "review context")
        ident(session["session_id"])
        require(
            session["purpose"] == "independent_review"
            and session["packet_digest"] == receipt["packet"]["sha256"]
            and session["packet_digest"]
            != context["receipt"]["review_packet"]["sha256"],
            "integrated review names another packet",
            Conflict,
        )
        require(
            session["session_id"] != intent["contract"]["implementation_context"],
            "review context reuses implementation session",
            Conflict,
        )
        require(
            session["session_id"] != candidate["review_session"],
            "integrated review reuses the candidate review session",
            Conflict,
        )
        return session["session_id"]

    def approve_evidence(
        self, proposal_id, spec, checksum, *, expected_version, command_id=None
    ):
        """Approve fresh checks and a separate review for one distinct OID."""
        self.core.principal.developer()
        spec = json.loads(canonical(spec))
        require(
            digest(spec) == checksum, "integrated evidence digest differs", Conflict
        )
        payload = {
            "proposal_id": proposal_id,
            "policy_digest": checksum,
            "expected_version": expected_version,
        }
        cached = self.core.store.recall(
            "integration.approve_evidence", self.core.principal, payload, command_id
        )
        if cached is not None:
            return cached
        reference, intent, receipt = self._validated(proposal_id)
        self.core._version(reference, expected_version)
        session = self._evidence_spec(reference, intent, receipt, spec)

        def apply():
            self._authority(intent)
            current = self._proposal(proposal_id)
            require(
                current["state"] == "staged"
                and current["version"] == reference["version"],
                "proposal changed during evidence approval",
                Conflict,
            )
            old = self.db.execute(
                "SELECT * FROM integration_evidence_policies WHERE proposal_id=?",
                (proposal_id,),
            ).fetchone()
            if old:
                require(
                    old["digest"] == checksum,
                    "proposal already has different integrated evidence",
                    Conflict,
                )
                return {"policy_id": old["id"], "digest": checksum, "approved": True}
            require(
                self.db.execute(
                    "SELECT 1 FROM verification_policies WHERE review_session=?",
                    (session,),
                ).fetchone()
                is None
                and self.db.execute(
                    "SELECT 1 FROM integration_evidence_policies WHERE review_session=?",
                    (session,),
                ).fetchone()
                is None,
                "integrated review reuses the candidate review session",
                Conflict,
            )
            policy_id = uuid4().hex
            self.db.execute(
                "INSERT INTO integration_evidence_policies VALUES(?,?,?,?,?,?,?)",
                (
                    policy_id,
                    proposal_id,
                    checksum,
                    canonical(spec),
                    self.core.principal.id,
                    session,
                    time.time_ns(),
                ),
            )
            return {"policy_id": policy_id, "digest": checksum, "approved": True}

        return self.core._write(
            "integration.approve_evidence",
            payload,
            apply,
            command_id,
            developer=True,
        )

    def _integrated_binding(
        self,
        proposal,
        policy,
        receipt,
        kind,
        profile,
        operation_id,
        *,
        subject_packet,
        evidence,
    ):
        stage = receipt["stage"]
        return {
            "format": "integrated-evidence-binding-v1",
            "phase": "integrated",
            "kind": kind,
            "operation_id": operation_id,
            "proposal_id": proposal["id"],
            "proposal_receipt_digest": proposal["receipt_digest"],
            "policy_digest": policy["digest"],
            "subject_revision": stage["revision"],
            "source_digest": stage["source_digest"],
            "candidate_packet_digest": subject_packet,
            "packet_digest": receipt["packet"]["sha256"],
            "profile": profile,
            "check_evidence": evidence,
            "classification": "scripted_development",
        }

    def prepare_integrated_checks(self, proposal_id, *, command_id=None):
        self.verify._service()
        payload = {"proposal_id": proposal_id}
        cached = self.core.store.recall(
            "integration.prepare_integrated_checks",
            self.core.principal,
            payload,
            command_id,
        )
        if cached is not None:
            return cached
        reference, intent, receipt = self._validated(proposal_id)
        with self.core.store.transaction(write=False):
            policy = self.core._one(
                "SELECT * FROM integration_evidence_policies WHERE proposal_id=?",
                (proposal_id,),
                "integrated evidence policy",
            )
        spec = json.loads(policy["spec"])
        require(
            digest(spec) == policy["digest"],
            "integrated evidence policy changed",
            Conflict,
        )
        self._evidence_spec(reference, intent, receipt, spec)

        def apply():
            self._authority(intent)
            row = self._proposal(proposal_id)
            require(
                row["state"] == "staged" and row["version"] == reference["version"],
                "proposal changed before integrated check admission",
                Conflict,
            )
            results = []
            for profile in spec["checks"]:
                old = self.db.execute(
                    "SELECT * FROM integration_verifications WHERE proposal_id=? AND kind='check' AND key=?",
                    (proposal_id, profile["check_id"]),
                ).fetchone()
                if old:
                    require(
                        old["scheduler"] == self.core.principal.id,
                        "integrated check belongs to another scheduler",
                        Conflict,
                    )
                    results.append(
                        {
                            "operation_id": old["id"],
                            "version": old["version"],
                            "state": old["state"],
                        }
                    )
                    continue
                operation_id = uuid4().hex
                binding = self._integrated_binding(
                    row,
                    policy,
                    receipt,
                    "check",
                    profile,
                    operation_id,
                    subject_packet=receipt["packet"]["sha256"],
                    evidence=[],
                )
                self.db.execute(
                    "INSERT INTO integration_verifications(id,proposal_id,policy_id,kind,key,scheduler,producer,version,state,binding,created_ns) VALUES(?,?,?,'check',?,?,?,1,'prepared',?,?)",
                    (
                        operation_id,
                        proposal_id,
                        policy["id"],
                        profile["check_id"],
                        self.core.principal.id,
                        profile["producer"],
                        canonical(binding),
                        time.time_ns(),
                    ),
                )
                results.append(
                    {"operation_id": operation_id, "version": 1, "state": "prepared"}
                )
            return {"operations": results, "task_accepted": False}

        return self.core._write(
            "integration.prepare_integrated_checks", payload, apply, command_id
        )

    def _integrated(self, operation_id):
        return self.core._one(
            "SELECT * FROM integration_verifications WHERE id=?",
            (operation_id,),
            "integrated evidence",
        )

    def begin_integrated(self, operation_id, *, expected_version, command_id=None):
        self.verify._service()
        with self.core.store.transaction(write=False):
            reference = self._integrated(operation_id)
        require(
            reference["scheduler"] == self.core.principal.id,
            "integrated evidence belongs to another scheduler",
            Conflict,
        )
        _proposal, intent, _receipt = self._validated(reference["proposal_id"])

        def apply():
            self._authority(intent)
            proposal = self._proposal(reference["proposal_id"])
            row = self._integrated(operation_id)
            self.core._version(row, expected_version)
            binding = json.loads(row["binding"])
            require(
                proposal["state"] == "staged"
                and proposal["receipt_digest"] == binding["proposal_receipt_digest"]
                and json.loads(proposal["receipt"])["stage"]["revision"]
                == binding["subject_revision"],
                "integrated evidence is bound to another commit",
                Conflict,
            )
            require(
                row["state"] == "prepared",
                "integrated evidence may already be sent; do not replay",
                Conflict,
            )
            self.db.execute(
                "UPDATE integration_verifications SET state='possible_send',version=version+1,sent_ns=? WHERE id=?",
                (time.time_ns(), operation_id),
            )
            return {
                "operation_id": operation_id,
                "state": "possible_send",
                "version": row["version"] + 1,
            }

        return self.core._write(
            "integration.begin_integrated",
            {"operation_id": operation_id, "expected_version": expected_version},
            apply,
            command_id,
        )

    def submit_integrated(self, operation_id, receipt, *, command_id=None):
        self.verify._service()
        receipt = json.loads(canonical(receipt))
        with self.core.store.transaction(write=False):
            reference = self._integrated(operation_id)
            proposal = self._proposal(reference["proposal_id"])
        require(
            reference["producer"] == self.core.principal.id,
            "integrated evidence producer is not assigned",
            Conflict,
        )
        require(
            reference["sent_ns"] is not None,
            "integrated evidence was not dispatched",
            Conflict,
        )
        binding = json.loads(reference["binding"])
        assessment = self.verify._assess(reference, receipt)
        stage = json.loads(proposal["receipt"])["stage"]
        if (
            binding["subject_revision"] != stage["revision"]
            or binding["source_digest"] != stage["source_digest"]
        ):
            assessment = {
                "applicable": False,
                "passed": False,
                "reasons": [*assessment["reasons"], "changed_integrated_revision"],
            }
        envelope = {
            "receipt": receipt,
            "assessment": assessment,
            "classification": "scripted_development",
        }
        checksum = digest(envelope)
        self.artifacts.put(canonical(envelope).encode())

        def apply():
            row = self._integrated(operation_id)
            current_proposal = self._proposal(row["proposal_id"])
            self.db.execute(
                "INSERT OR IGNORE INTO integration_verification_observations VALUES(?,?,?,?)",
                (operation_id, checksum, canonical(envelope), time.time_ns()),
            )
            if row["receipt_digest"] and row["receipt_digest"] != checksum:
                self.core._fence(current_proposal["project_id"])
                self.db.execute(
                    "UPDATE integration_verifications SET state='conflicting',version=version+1 WHERE id=?",
                    (operation_id,),
                )
                return {
                    "operation_id": operation_id,
                    "current": False,
                    "conflicting": True,
                    "task_accepted": False,
                }
            try:
                self._authority(json.loads(current_proposal["intent"]))
                staged = json.loads(current_proposal["receipt"])["stage"]
                current = (
                    current_proposal["state"] == "staged"
                    and row["state"] != "conflicting"
                    and current_proposal["receipt_digest"]
                    == binding["proposal_receipt_digest"]
                    and staged["revision"] == binding["subject_revision"]
                )
            except Conflict:
                current = False
            state = (
                "returned"
                if current and assessment["applicable"]
                else "conflicting"
                if row["state"] == "conflicting"
                else "held"
            )
            duplicate = row["receipt_digest"] == checksum
            if not duplicate or row["state"] != state:
                self.db.execute(
                    "UPDATE integration_verifications SET state=?,version=version+1,receipt=?,receipt_digest=? WHERE id=?",
                    (state, canonical(envelope), checksum, operation_id),
                )
            return {
                "operation_id": operation_id,
                "current": current,
                "state": state,
                "passed": current and assessment["passed"],
                "duplicate": duplicate,
                "task_accepted": False,
            }

        return self.core._write(
            "integration.integrated_observe",
            {"operation_id": operation_id, "receipt_digest": checksum},
            apply,
            command_id,
        )

    def _integrated_checks(self, proposal_id, spec):
        with self.core.store.transaction(write=False):
            rows = [
                dict(row)
                for row in self.db.execute(
                    "SELECT * FROM integration_verifications WHERE proposal_id=? AND kind='check' ORDER BY key",
                    (proposal_id,),
                )
            ]
        require(
            {row["key"] for row in rows}
            == {item["check_id"] for item in spec["checks"]},
            "fresh integrated checks are missing",
            Conflict,
        )
        return [self.verify._passed_operation(row) for row in rows]

    def prepare_integrated_review(self, proposal_id, *, command_id=None):
        self.verify._service()
        payload = {"proposal_id": proposal_id}
        cached = self.core.store.recall(
            "integration.prepare_integrated_review",
            self.core.principal,
            payload,
            command_id,
        )
        if cached is not None:
            return cached
        reference, intent, receipt = self._validated(proposal_id)
        with self.core.store.transaction(write=False):
            policy = self.core._one(
                "SELECT * FROM integration_evidence_policies WHERE proposal_id=?",
                (proposal_id,),
                "integrated evidence policy",
            )
        spec = json.loads(policy["spec"])
        require(
            digest(spec) == policy["digest"],
            "integrated evidence policy changed",
            Conflict,
        )
        self._evidence_spec(reference, intent, receipt, spec)
        evidence = self._integrated_checks(proposal_id, spec)
        subject = {
            "format": "integrated-review-subject-v1",
            "contract": intent["contract"],
            "subject_revision": receipt["stage"]["revision"],
            "source_digest": receipt["stage"]["source_digest"],
        }
        subject_packet = self.artifacts.put(canonical(subject).encode())["sha256"]

        def apply():
            self._authority(intent)
            row = self._proposal(proposal_id)
            require(
                row["state"] == "staged"
                and row["receipt_digest"] == reference["receipt_digest"],
                "proposal changed before integrated review admission",
                Conflict,
            )
            old = self.db.execute(
                "SELECT * FROM integration_verifications WHERE proposal_id=? AND kind='review'",
                (proposal_id,),
            ).fetchone()
            if old:
                require(
                    old["scheduler"] == self.core.principal.id,
                    "integrated review belongs to another scheduler",
                    Conflict,
                )
                return {
                    "operations": [
                        {
                            "operation_id": old["id"],
                            "version": old["version"],
                            "state": old["state"],
                        }
                    ],
                    "task_accepted": False,
                }
            operation_id = uuid4().hex
            binding = self._integrated_binding(
                row,
                policy,
                receipt,
                "review",
                spec["review"],
                operation_id,
                subject_packet=subject_packet,
                evidence=evidence,
            )
            self.db.execute(
                "INSERT INTO integration_verifications(id,proposal_id,policy_id,kind,key,scheduler,producer,version,state,binding,created_ns) VALUES(?,?,?,'review','independent',?,?,1,'prepared',?,?)",
                (
                    operation_id,
                    proposal_id,
                    policy["id"],
                    self.core.principal.id,
                    spec["review"]["producer"],
                    canonical(binding),
                    time.time_ns(),
                ),
            )
            return {
                "operations": [
                    {"operation_id": operation_id, "version": 1, "state": "prepared"}
                ],
                "task_accepted": False,
            }

        return self.core._write(
            "integration.prepare_integrated_review", payload, apply, command_id
        )

    def _fresh_evidence(self, reference, intent, receipt):
        proposal_id = reference["id"]
        stage = receipt["stage"]
        require(
            stage["revision"] != intent["candidate_revision"],
            "candidate evidence already binds this integrated commit",
            Conflict,
        )
        with self.core.store.transaction(write=False):
            policy = self.core._one(
                "SELECT * FROM integration_evidence_policies WHERE proposal_id=?",
                (proposal_id,),
                "integrated evidence policy",
            )
            candidate = self.core._one(
                "SELECT review_session FROM verification_policies WHERE intake_id=?",
                (intent["intake_id"],),
                "verification policy",
            )
        spec = json.loads(policy["spec"])
        require(
            digest(spec) == policy["digest"]
            and policy["review_session"] != candidate["review_session"],
            "integrated review reuses the candidate review session",
            Conflict,
        )
        with self.core.store.transaction(write=False):
            rows = [
                dict(row)
                for row in self.db.execute(
                    "SELECT * FROM integration_verifications WHERE proposal_id=? ORDER BY kind,key",
                    (proposal_id,),
                )
            ]
        require(rows, "fresh integrated checks and review are missing", Conflict)
        for current in rows:
            binding = json.loads(current["binding"])
            require(
                binding["phase"] == "integrated"
                and binding["subject_revision"] == stage["revision"]
                and binding["source_digest"] == stage["source_digest"]
                and binding["proposal_receipt_digest"] == reference["receipt_digest"]
                and binding["policy_digest"] == policy["digest"],
                "integrated evidence is bound to another commit",
                Conflict,
            )
        checks = self._integrated_checks(proposal_id, spec)
        review = next((row for row in rows if row["kind"] == "review"), None)
        require(review is not None, "fresh integrated review is missing", Conflict)
        self.verify._passed_operation(review)
        require(
            json.loads(review["binding"])["check_evidence"] == checks,
            "integrated review consumed obsolete checks",
            Conflict,
        )
        return {
            "policy_digest": policy["digest"],
            "subject_revision": stage["revision"],
            "source_digest": stage["source_digest"],
            "checks": checks,
            "review": {
                "operation_id": review["id"],
                "receipt_digest": review["receipt_digest"],
            },
        }

    def gate(self, proposal_id):
        try:
            reference, intent, receipt = self._validated(proposal_id)
            with self.core.store.transaction(write=False):
                policy = self.core._one(
                    "SELECT * FROM integration_policies WHERE proposal_id=?",
                    (proposal_id,),
                    "regression policy",
                )
                rows = [
                    dict(row)
                    for row in self.db.execute(
                        "SELECT * FROM integration_regressions WHERE proposal_id=? ORDER BY key",
                        (proposal_id,),
                    ).fetchall()
                ]
            spec = json.loads(policy["spec"])
            require(
                digest(spec) == policy["digest"], "regression policy changed", Conflict
            )
            require(
                {row["key"] for row in rows}
                == {profile["check_id"] for profile in spec["checks"]},
                "required regressions are missing",
                Conflict,
            )
            evidence = [
                self.verify._passed_operation({**row, "kind": "check"}) for row in rows
            ]
            profiles = {profile["check_id"]: profile for profile in spec["checks"]}
            for profile in spec["checks"]:
                self.verify._json(profile["definition_digest"])
                require(
                    self.verify._json(profile["environment_digest"]).get(
                        "classification"
                    )
                    == "scripted_development",
                    "regression environment differs",
                    Conflict,
                )
            for row in rows:
                binding = json.loads(row["binding"])
                require(
                    binding["proposal_receipt_digest"] == reference["receipt_digest"]
                    and binding["policy_digest"] == policy["digest"]
                    and binding["subject_revision"] == receipt["stage"]["revision"]
                    and binding["profile"] == profiles[row["key"]],
                    "regression is bound to an obsolete integration",
                    Conflict,
                )
            with self.core.store.transaction(write=False):
                self._authority(intent)
                now = self._proposal(proposal_id)
                require(
                    now["state"] == "staged" and now["version"] == reference["version"],
                    "proposal changed during regression gate",
                    Conflict,
                )
                for item in evidence:
                    current = self._regression(item["operation_id"])
                    require(
                        current["state"] == "returned"
                        and current["receipt_digest"] == item["receipt_digest"],
                        "regression evidence changed",
                        Conflict,
                    )
            same_subject = receipt["stage"]["revision"] == intent["candidate_revision"]
            fresh = None
            if not same_subject:
                try:
                    fresh = self._fresh_evidence(reference, intent, receipt)
                except (Conflict, ValueError, OSError):
                    fresh = None
            ready = same_subject or fresh is not None
            return {
                "proposal_id": proposal_id,
                "development_ready_for_promotion": ready,
                "regressions_passed": True,
                "needs_fresh_integrated_checks_review": not ready,
                "live_eligible": False,
                "task_accepted": False,
                "integrated_revision": receipt["stage"]["revision"],
                "expected_head": intent["expected_head"],
                "regression_evidence": evidence,
                "integrated_evidence": fresh,
                "reasons": []
                if ready
                else [
                    "distinct integrated revision needs fresh mandatory checks and review"
                ],
            }
        except (ValueError, OSError) as error:
            return {
                "proposal_id": proposal_id,
                "development_ready_for_promotion": False,
                "regressions_passed": False,
                "live_eligible": False,
                "task_accepted": False,
                "reasons": [str(error)],
            }

    def _promotion(self, promotion_id):
        return self.core._one(
            "SELECT * FROM integration_promotions WHERE id=?",
            (promotion_id,),
            "promotion",
        )

    def _evidence_document(self, proposal_id):
        reference, intent, receipt = self._validated(proposal_id)
        gate = self.gate(proposal_id)
        require(
            gate["development_ready_for_promotion"],
            "integration is not ready for promotion",
            Conflict,
        )
        require(
            gate["integrated_revision"] == receipt["stage"]["revision"]
            and gate["expected_head"] == intent["expected_head"]
            and gate["live_eligible"] is False
            and gate["task_accepted"] is False,
            "staged commit changed",
            Conflict,
        )
        same = receipt["stage"]["revision"] == intent["candidate_revision"]
        fresh = gate["integrated_evidence"]
        if same:
            require(fresh is None, "staged commit changed", Conflict)
        else:
            require(
                fresh["subject_revision"] == receipt["stage"]["revision"]
                and fresh["source_digest"] == receipt["stage"]["source_digest"],
                "integrated evidence is bound to another commit",
                Conflict,
            )
        evidence = {
            "format": "promotion-evidence-v1",
            "classification": "scripted_development",
            "proposal_id": proposal_id,
            "proposal_receipt_digest": reference["receipt_digest"],
            "expected_head": intent["expected_head"],
            "integrated_revision": receipt["stage"]["revision"],
            "source_digest": receipt["stage"]["source_digest"],
            "same_subject": same,
            "regressions": gate["regression_evidence"],
            "integrated_evidence": fresh,
        }
        return reference, intent, receipt, evidence

    def _promotion_pins(self, evidence):
        proposal = self._proposal(evidence["proposal_id"])
        receipt = json.loads(proposal["receipt"])
        require(
            proposal["state"] == "staged"
            and proposal["receipt_digest"] == evidence["proposal_receipt_digest"]
            and receipt["stage"]["revision"] == evidence["integrated_revision"]
            and receipt["stage"]["source_digest"] == evidence["source_digest"],
            "staged commit changed",
            Conflict,
        )
        for item in evidence["regressions"]:
            row = self._regression(item["operation_id"])
            binding = json.loads(row["binding"])
            require(
                row["state"] == "returned"
                and row["receipt_digest"] == item["receipt_digest"]
                and binding["subject_revision"] == evidence["integrated_revision"],
                "regression is bound to an obsolete integration",
                Conflict,
            )
        fresh = evidence["integrated_evidence"]
        if evidence["same_subject"]:
            require(
                fresh is None
                and json.loads(proposal["intent"])["candidate_revision"]
                == evidence["integrated_revision"],
                "staged commit changed",
                Conflict,
            )
            return
        require(
            fresh["subject_revision"] == evidence["integrated_revision"]
            and fresh["source_digest"] == evidence["source_digest"],
            "integrated evidence is bound to another commit",
            Conflict,
        )
        for item in [*fresh["checks"], fresh["review"]]:
            row = self._integrated(item["operation_id"])
            binding = json.loads(row["binding"])
            require(
                row["state"] == "returned"
                and row["receipt_digest"] == item["receipt_digest"]
                and binding["subject_revision"] == evidence["integrated_revision"]
                and binding["source_digest"] == evidence["source_digest"],
                "integrated evidence is bound to another commit",
                Conflict,
            )

    def _promotion_receipt(self, row):
        return {
            "format": "promotion-receipt-v1",
            "ref": f"refs/orchestrator/milestones/{row['milestone_id']}",
            "expected_head": row["expected_head"],
            "integrated_revision": row["integrated_revision"],
            "evidence_digest": row["evidence_digest"],
            "milestone_version": row["expected_milestone_version"] + 1,
            "classification": "scripted_development",
            "live_eligible": False,
            "task_accepted": True,
        }

    def _promotion_result(self, row, receipt, *, duplicate):
        return {
            "promotion_id": row["id"],
            "proposal_id": row["proposal_id"],
            "state": "promoted",
            "milestone_id": row["milestone_id"],
            "expected_head": row["expected_head"],
            "integrated_revision": row["integrated_revision"],
            "milestone_version": receipt["milestone_version"],
            "evidence_digest": row["evidence_digest"],
            "duplicate": duplicate,
            "live_eligible": False,
            "task_accepted": True,
        }

    def begin_promotion(self, proposal_id, *, expected_version, command_id=None):
        """Commit possible-send for one acceptance before the milestone ref write."""
        reference, intent, _receipt, evidence = self._evidence_document(proposal_id)
        self.core._version(reference, expected_version)
        checksum = digest(evidence)
        contract = intent["contract"]
        payload = {
            "proposal_id": proposal_id,
            "expected_version": expected_version,
            "evidence_digest": checksum,
        }

        def apply():
            self._authority(intent)
            proposal = self._proposal(proposal_id)
            self.core._version(proposal, expected_version)
            require(
                proposal["state"] == "staged",
                "integration proposal is held or incomplete",
                Conflict,
            )
            self._promotion_pins(evidence)
            milestone = self.core._one(
                "SELECT * FROM milestones WHERE id=?",
                (contract["milestone_id"],),
                "milestone",
            )
            attempt = self.core._attempt(contract["attempt_id"])
            claim = intent.get("head_mapping")
            guard_head = (
                intent["expected_head"] if claim is None else claim["previous_head"]
            )
            if claim is not None:
                require(
                    claim["new_head"] == intent["expected_head"]
                    and claim["previous_head"] != claim["new_head"],
                    "diverged-head mapping differs",
                    Conflict,
                )
            require(
                milestone["head_revision"] == guard_head,
                "milestone head changed",
                Conflict,
            )
            require(
                attempt["milestone_id"] == milestone["id"]
                and attempt["plan_id"] == contract["plan_id"]
                and attempt["task_key"] == contract["task"]["id"]
                and attempt["state"] == "awaiting_verification"
                and attempt["settled"] == 0,
                "attempt is not awaiting acceptance",
                Conflict,
            )
            existing = self.db.execute(
                "SELECT * FROM integration_promotions WHERE proposal_id=?",
                (proposal_id,),
            ).fetchone()
            if existing is not None:
                require(
                    existing["state"] != "promoted",
                    "promotion already recorded",
                    Conflict,
                )
                require(
                    existing["state"] == "possible_send",
                    "promotion is held",
                    Conflict,
                )
                require(
                    False,
                    "promotion may already be sent; reconcile without replay",
                    Conflict,
                )
            promotion_id = uuid4().hex
            self.db.execute(
                "INSERT INTO integration_promotions(id,proposal_id,project_id,milestone_id,attempt_id,plan_id,task_key,expected_head,integrated_revision,expected_milestone_version,evidence_digest,evidence,version,state,sent_ns,created_ns) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1,'possible_send',?,?)",
                (
                    promotion_id,
                    proposal_id,
                    contract["project_id"],
                    milestone["id"],
                    attempt["id"],
                    contract["plan_id"],
                    contract["task"]["id"],
                    guard_head,
                    evidence["integrated_revision"],
                    milestone["version"],
                    checksum,
                    canonical(evidence),
                    time.time_ns(),
                    time.time_ns(),
                ),
            )
            return {
                "promotion_id": promotion_id,
                "proposal_id": proposal_id,
                "state": "possible_send",
                "version": 1,
                "milestone_id": milestone["id"],
                "expected_head": guard_head,
                "integrated_revision": evidence["integrated_revision"],
                "live_eligible": False,
                "task_accepted": False,
            }

        return self.core._write(
            "integration.begin_promotion",
            payload,
            apply,
            command_id,
            developer=True,
        )

    def _hold_promotion(self, promotion_id, reason):
        def apply():
            row = self._promotion(promotion_id)
            if row["state"] not in {"promoted", "conflicting"}:
                self.db.execute(
                    "UPDATE integration_promotions SET state='held',version=version+1 WHERE id=?",
                    (promotion_id,),
                )
            return {
                "promotion_id": promotion_id,
                "state": row["state"]
                if row["state"] in {"promoted", "conflicting"}
                else "held",
                "reason": reason,
                "live_eligible": False,
                "task_accepted": row["state"] == "promoted",
            }

        return self.core._write(
            "integration.promotion_hold",
            {"promotion_id": promotion_id, "reason": reason},
            apply,
            None,
            developer=True,
        )

    def _record_promotion(self, promotion_id):
        self.core.principal.developer()
        with self.core.store.transaction(write=False):
            row = dict(self._promotion(promotion_id))
        receipt = self._promotion_receipt(row)
        checksum = digest(receipt)
        if row["state"] == "promoted":
            require(
                row["receipt_digest"] == checksum, "promotion receipt changed", Conflict
            )
            self.repo.observe_milestone_ref(
                row["milestone_id"], row["integrated_revision"]
            )
            return self._promotion_result(row, receipt, duplicate=True)
        try:
            _reference, intent, _receipt, evidence = self._evidence_document(
                row["proposal_id"]
            )
            require(
                digest(evidence) == row["evidence_digest"],
                "promotion evidence changed",
                Conflict,
            )
        except (Conflict, ValueError, OSError) as error:
            self._hold_promotion(promotion_id, str(error))
            raise
        self.repo.observe_milestone_ref(row["milestone_id"], row["integrated_revision"])

        def apply():
            current = self._promotion(promotion_id)
            if current["state"] == "promoted":
                require(
                    current["receipt_digest"] == checksum,
                    "promotion receipt changed",
                    Conflict,
                )
                return self._promotion_result(current, receipt, duplicate=True)
            require(current["state"] == "possible_send", "promotion is held", Conflict)
            require(
                current["evidence_digest"] == row["evidence_digest"],
                "promotion evidence changed",
                Conflict,
            )
            self._authority(intent)
            self._promotion_pins(evidence)
            milestone = self.core._one(
                "SELECT * FROM milestones WHERE id=?",
                (current["milestone_id"],),
                "milestone",
            )
            attempt = self.core._attempt(current["attempt_id"])
            require(
                milestone["head_revision"] == current["expected_head"]
                and milestone["version"] == current["expected_milestone_version"]
                and attempt["state"] == "awaiting_verification"
                and attempt["settled"] == 0,
                "milestone head changed",
                Conflict,
            )
            moved = self.db.execute(
                "UPDATE milestones SET head_revision=?,version=version+1 WHERE id=? AND head_revision=? AND version=?",
                (
                    current["integrated_revision"],
                    milestone["id"],
                    current["expected_head"],
                    current["expected_milestone_version"],
                ),
            )
            require(moved.rowcount == 1, "milestone head changed", Conflict)
            self.db.execute(
                "INSERT INTO acceptances VALUES(?,?,?,?)",
                (
                    current["plan_id"],
                    current["task_key"],
                    current["integrated_revision"],
                    current["evidence_digest"],
                ),
            )
            settled = self.db.execute(
                "UPDATE attempts SET settled=1,version=version+1 WHERE id=? AND state='awaiting_verification' AND settled=0",
                (current["attempt_id"],),
            )
            require(
                settled.rowcount == 1,
                "attempt is not awaiting acceptance",
                Conflict,
            )
            self.db.execute(
                "UPDATE integration_promotions SET state='promoted',version=version+1,receipt=?,receipt_digest=? WHERE id=?",
                (canonical(receipt), checksum, promotion_id),
            )
            return self._promotion_result(
                self._promotion(promotion_id), receipt, duplicate=False
            )

        return self.core._write(
            "integration.promotion_observe",
            {"promotion_id": promotion_id, "receipt_digest": checksum},
            apply,
            None,
            developer=True,
        )

    def promote(self, proposal_id, *, expected_version):
        begun = self.begin_promotion(proposal_id, expected_version=expected_version)
        try:
            self.repo.advance_milestone_ref(
                begun["milestone_id"],
                begun["expected_head"],
                begun["integrated_revision"],
            )
        except (ValueError, OSError) as error:
            self._hold_promotion(begun["promotion_id"], str(error))
            raise
        return self._record_promotion(begun["promotion_id"])

    def reconcile_promotion(self, proposal_id):
        self.core.principal.developer()
        with self.core.store.transaction(write=False):
            row = self.core._one(
                "SELECT * FROM integration_promotions WHERE proposal_id=?",
                (proposal_id,),
                "promotion",
            )
        require(row["sent_ns"] is not None, "promotion was never sent", Conflict)
        try:
            self.repo.observe_milestone_ref(
                row["milestone_id"], row["integrated_revision"]
            )
        except (ValueError, OSError) as error:
            self._hold_promotion(row["id"], str(error))
            raise
        return self._record_promotion(row["id"])
