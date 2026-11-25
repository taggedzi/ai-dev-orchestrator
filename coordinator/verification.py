"""Exact candidate check/review admission. No test execution or acceptance API.

Principals come from trusted local composition. Remote service authentication and
qualified runner/reviewer adapters are separate deployment work. All supported
profiles and receipts in this increment are explicitly scripted development data.
"""

import json
import time
from uuid import uuid4

from .domain import Conflict, canonical, digest, fields, ident, require, text, unique
from .intake import CandidateIntake
from .source import Snapshot, SourceFile

DIMENSIONS = (
    "correctness",
    "criteria",
    "maintainability",
    "security",
    "tests",
    "scope",
    "architecture",
)


class Verification:
    def __init__(self, coordinator, repository, artifacts):
        self.core, self.repo, self.artifacts = coordinator, repository, artifacts

    @property
    def db(self):
        return self.core.db

    def _service(self):
        require(
            self.core.principal.role == "service",
            "trusted verification service required",
        )

    def _json(self, checksum):
        value = json.loads(self.artifacts.read(checksum))
        require(type(value) is dict, "verification artifact must be an object")
        return value

    def _current(self, reference):
        row = self.core._one(
            "SELECT * FROM candidate_intakes WHERE id=?",
            (reference["id"],),
            "candidate intake",
        )
        require(
            row["state"] == "sealed"
            and row["version"] == reference["version"]
            and row["receipt_digest"] == reference["receipt_digest"],
            "candidate intake changed or held",
            Conflict,
        )
        contract = json.loads(row["contract"])
        actual = CandidateIntake.current_contract(
            self.core, self.repo, row["attempt_id"]
        )
        require(
            canonical(actual) == canonical(contract),
            "candidate authority is fenced",
            Conflict,
        )

    def _candidate(self, intake_id):
        with self.core.store.transaction(write=False):
            row = self.core._one(
                "SELECT * FROM candidate_intakes WHERE id=?",
                (intake_id,),
                "candidate intake",
            )
            self._current(row)
        receipt = json.loads(row["receipt"])
        require(
            self._json(row["receipt_digest"]) == receipt,
            "candidate receipt changed",
            Conflict,
        )
        packet = self._json(receipt["review_packet"]["sha256"])
        contract = json.loads(row["contract"])
        require(
            packet["contract"] == contract
            and packet["candidate"] == receipt["candidate"],
            "candidate packet binding changed",
            Conflict,
        )
        require(
            contract["repository_id"] == self.repo.marker["repository_id"],
            "candidate repository differs",
            Conflict,
        )
        snapshot = Snapshot(
            {
                item["path"]: SourceFile(
                    self.artifacts.read(item["sha256"]), item["mode"]
                )
                for item in packet["source_manifest"]
            }
        )
        require(
            snapshot.digest == row["source_digest"],
            "candidate source manifest differs",
            Conflict,
        )
        original = Snapshot(
            {
                item["path"]: SourceFile(
                    self.artifacts.read(item["sha256"]), item["mode"]
                )
                for item in packet["input_source_manifest"]
            }
        )
        require(
            original.files() == self.repo.snapshot(contract["input_revision"]).files(),
            "candidate input artifacts differ",
            Conflict,
        )
        observed = self.repo.observe_candidate(
            contract["input_revision"],
            snapshot,
            allowed_paths=contract["task"]["allowed_paths"],
            binding=CandidateIntake._binding(contract),
        )
        require(
            observed == receipt["candidate"],
            "candidate ref or objects changed",
            Conflict,
        )
        return {"row": row, "contract": contract, "receipt": receipt, "packet": packet}

    def _validate_policy(self, context, spec):
        fields(spec, ("classification", "checks", "review"), "verification policy")
        require(
            spec["classification"] == "scripted_development",
            "live verification is not qualified",
        )
        contract = context["contract"]
        require(
            contract.get("format") == "candidate-contract-v2"
            and contract.get("implementation_actor")
            and contract.get("implementation_context"),
            "implementation identity/context is unknown; cannot establish independence",
            Conflict,
        )
        checks = spec["checks"]
        require(type(checks) is list and checks, "check profiles must be nonempty")
        approved = {c["id"]: c for c in contract["task"]["checks"]}
        ids, producers = [], set()
        for check in checks:
            fields(
                check,
                ("check_id", "producer", "definition_digest", "environment_digest"),
                "check profile",
            )
            ident(check["check_id"])
            text(check["producer"], "check producer", 200)
            require(
                check["producer"] != contract["implementation_actor"],
                "implementer cannot supply independent checks",
            )
            definition = self._json(check["definition_digest"])
            fields(definition, ("check", "cases"), "check definition")
            require(
                check["check_id"] in approved
                and definition["check"] == approved[check["check_id"]],
                "check differs from approved task",
            )
            cases = definition["cases"]
            require(
                type(cases) is list and 1 <= len(cases) <= 1000,
                "observable cases must be nonempty",
            )
            for case in cases:
                fields(case, ("id", "input", "expected"), "check case")
                ident(case["id"])
                canonical(case)
            unique([case["id"] for case in cases], "case id")
            require(
                self._json(check["environment_digest"]).get("classification")
                == "scripted_development",
                "unqualified environment profile",
            )
            ids.append(check["check_id"])
            producers.add(check["producer"])
        unique(ids, "check profile")
        require(set(ids) == set(approved), "policy must preserve every approved check")
        review = spec["review"]
        fields(
            review,
            ("producer", "profile_digest", "rubric_digest", "context_digest"),
            "review profile",
        )
        text(review["producer"], "review producer", 200)
        require(
            review["producer"]
            not in producers
            | {contract["implementation_actor"], context["row"]["producer"]},
            "reviewer must be separate from implementer, checker and Git intake",
        )
        require(
            self._json(review["profile_digest"]).get("classification")
            == "scripted_development",
            "live reviewer is not qualified",
        )
        rubric = self._json(review["rubric_digest"])
        fields(rubric, ("version", "dimensions"), "review rubric")
        ident(rubric["version"])
        require(
            type(rubric["dimensions"]) is list
            and len(rubric["dimensions"]) == len(DIMENSIONS)
            and all(type(value) is str for value in rubric["dimensions"])
            and set(rubric["dimensions"]) == set(DIMENSIONS),
            "review rubric must cover all required dimensions",
        )
        session = self._json(review["context_digest"])
        fields(session, ("session_id", "packet_digest", "purpose"), "review context")
        ident(session["session_id"])
        require(
            session["purpose"] == "independent_review"
            and session["packet_digest"]
            == context["receipt"]["review_packet"]["sha256"],
            "review context names another packet",
        )
        require(
            session["session_id"] != contract["implementation_context"],
            "review context reuses implementation session",
        )
        return session["session_id"]

    def approve_policy(
        self, intake_id, spec, checksum, *, expected_intake_version, command_id=None
    ):
        self.core.principal.developer()
        spec = json.loads(canonical(spec))
        require(digest(spec) == checksum, "policy approval digest differs", Conflict)
        payload = {
            "intake_id": intake_id,
            "policy_digest": checksum,
            "expected_intake_version": expected_intake_version,
        }
        cached = self.core.store.recall(
            "verification.approve", self.core.principal, payload, command_id
        )
        if cached is not None:
            return cached
        context = self._candidate(intake_id)
        self.core._version(context["row"], expected_intake_version)
        session = self._validate_policy(context, spec)
        frozen = canonical(spec)

        def apply():
            self._current(context["row"])
            old = self.db.execute(
                "SELECT * FROM verification_policies WHERE intake_id=?", (intake_id,)
            ).fetchone()
            if old:
                require(
                    old["digest"] == checksum,
                    "candidate already has a different approved policy",
                    Conflict,
                )
                return {"policy_id": old["id"], "digest": checksum, "approved": True}
            require(
                self.db.execute(
                    "SELECT 1 FROM verification_policies WHERE review_session=?",
                    (session,),
                ).fetchone()
                is None,
                "review session was already used",
                Conflict,
            )
            policy_id = uuid4().hex
            self.db.execute(
                "INSERT INTO verification_policies VALUES(?,?,?,?,?,?,?)",
                (
                    policy_id,
                    intake_id,
                    checksum,
                    frozen,
                    self.core.principal.id,
                    session,
                    time.time_ns(),
                ),
            )
            return {"policy_id": policy_id, "digest": checksum, "approved": True}

        return self.core._write(
            "verification.approve", payload, apply, command_id, developer=True
        )

    def _policy(self, intake_id):
        row = self.core._one(
            "SELECT * FROM verification_policies WHERE intake_id=?",
            (intake_id,),
            "verification policy",
        )
        spec = json.loads(row["spec"])
        require(
            digest(spec) == row["digest"],
            "approved verification policy changed",
            Conflict,
        )
        return row, spec

    def _binding(
        self,
        context,
        policy,
        kind,
        profile,
        operation_id,
        *,
        packet=None,
        evidence=None,
    ):
        contract, row = context["contract"], context["row"]
        return {
            "format": "verification-binding-v1",
            "operation_id": operation_id,
            "intake_id": row["id"],
            "intake_receipt_digest": row["receipt_digest"],
            "repository_id": contract["repository_id"],
            "attempt_id": contract["attempt_id"],
            "generation": contract["generation"],
            "plan_digest": contract["plan_digest"],
            "task_digest": contract["task_digest"],
            "criteria_digest": digest(contract["task"]["criteria"]),
            "input_revision": contract["input_revision"],
            "subject_revision": context["receipt"]["candidate"]["revision"],
            "source_digest": row["source_digest"],
            "candidate_packet_digest": context["receipt"]["review_packet"]["sha256"],
            "packet_digest": packet or context["receipt"]["review_packet"]["sha256"],
            "policy_digest": policy["digest"],
            "kind": kind,
            "phase": "candidate",
            "profile": profile,
            "check_evidence": evidence or [],
            "classification": "scripted_development",
        }

    def _prepare(
        self,
        context,
        policy,
        kind,
        profiles,
        *,
        packet=None,
        evidence=None,
        command_id=None,
    ):
        def apply():
            self._current(context["row"])
            if evidence is not None:
                for item in evidence:
                    current = self.core._one(
                        "SELECT * FROM verification_operations WHERE id=?",
                        (item["operation_id"],),
                        "check operation",
                    )
                    require(
                        current["state"] == "returned"
                        and current["receipt_digest"] == item["receipt_digest"],
                        "check evidence changed before review admission",
                        Conflict,
                    )
            operations = []
            for key, profile in profiles:
                old = self.db.execute(
                    "SELECT * FROM verification_operations WHERE intake_id=? AND kind=? AND key=?",
                    (context["row"]["id"], kind, key),
                ).fetchone()
                if old:
                    require(
                        old["scheduler"] == self.core.principal.id
                        and old["policy_id"] == policy["id"],
                        "operation belongs to another scheduler or policy",
                        Conflict,
                    )
                    operations.append(
                        {
                            "operation_id": old["id"],
                            "version": old["version"],
                            "state": old["state"],
                            "binding_digest": digest(json.loads(old["binding"])),
                        }
                    )
                    continue
                operation_id = uuid4().hex
                binding = self._binding(
                    context,
                    policy,
                    kind,
                    profile,
                    operation_id,
                    packet=packet,
                    evidence=evidence,
                )
                self.db.execute(
                    "INSERT INTO verification_operations(id,intake_id,policy_id,kind,key,scheduler,producer,version,state,binding,created_ns) VALUES(?,?,?,?,?,?,?,1,'prepared',?,?)",
                    (
                        operation_id,
                        context["row"]["id"],
                        policy["id"],
                        kind,
                        key,
                        self.core.principal.id,
                        profile["producer"],
                        canonical(binding),
                        time.time_ns(),
                    ),
                )
                operations.append(
                    {
                        "operation_id": operation_id,
                        "version": 1,
                        "state": "prepared",
                        "binding_digest": digest(binding),
                    }
                )
            return {"operations": operations, "task_accepted": False}

        return self.core._write(
            f"verification.prepare_{kind}",
            {
                "intake_id": context["row"]["id"],
                "policy_id": policy["id"],
                "packet_digest": packet,
                "check_evidence": evidence,
            },
            apply,
            command_id,
        )

    def prepare_checks(self, intake_id, *, command_id=None):
        self._service()
        context = self._candidate(intake_id)
        with self.core.store.transaction(write=False):
            policy, spec = self._policy(intake_id)
        self._validate_policy(context, spec)
        return self._prepare(
            context,
            policy,
            "check",
            [(p["check_id"], p) for p in spec["checks"]],
            command_id=command_id,
        )

    def _operation(self, operation_id):
        return self.core._one(
            "SELECT * FROM verification_operations WHERE id=?",
            (operation_id,),
            "verification operation",
        )

    def begin(self, operation_id, *, expected_version, command_id=None):
        self._service()
        with self.core.store.transaction(write=False):
            operation = self._operation(operation_id)
        require(
            operation["scheduler"] == self.core.principal.id,
            "operation belongs to another scheduler",
            Conflict,
        )
        context = self._candidate(operation["intake_id"])

        def apply():
            self._current(context["row"])
            row = self._operation(operation_id)
            self.core._version(row, expected_version)
            require(
                row["state"] == "prepared",
                "verification may already be sent; do not replay",
                Conflict,
            )
            self.db.execute(
                "UPDATE verification_operations SET state='possible_send',version=version+1,sent_ns=? WHERE id=?",
                (time.time_ns(), operation_id),
            )
            return {
                "operation_id": operation_id,
                "state": "possible_send",
                "version": row["version"] + 1,
            }

        return self.core._write(
            "verification.begin",
            {"operation_id": operation_id, "expected_version": expected_version},
            apply,
            command_id,
        )

    def _assess(self, row, receipt):
        fields(
            receipt, ("binding_digest", "verdict", "details"), "verification receipt"
        )
        binding = json.loads(row["binding"])
        reasons = []
        applicable = receipt["binding_digest"] == digest(binding)
        if not applicable:
            reasons.append("binding_mismatch")
        details, profile = receipt["details"], binding["profile"]
        if row["kind"] == "check":
            fields(
                details,
                ("source_digest", "environment_digest", "log_digest", "cases"),
                "check receipt details",
            )
            require(
                type(receipt["verdict"]) is str
                and receipt["verdict"] in {"pass", "fail", "inconclusive"},
                "invalid check verdict",
            )
            self.artifacts.read(details["log_digest"])
            definition = self._json(profile["definition_digest"])
            cases = details["cases"]
            require(
                type(cases) is list and len(cases) <= 1000, "invalid case observations"
            )
            ids, statuses = [], []
            for case in cases:
                fields(case, ("id", "status", "observation_digest"), "case observation")
                ident(case["id"])
                require(
                    type(case["status"]) is str
                    and case["status"] in {"pass", "fail", "inconclusive"},
                    "invalid case status",
                )
                self.artifacts.read(case["observation_digest"])
                ids.append(case["id"])
                statuses.append(case["status"])
            expected = {c["id"] for c in definition["cases"]}
            if len(ids) != len(set(ids)) or set(ids) != expected:
                applicable = False
                reasons.append("case_coverage_mismatch")
            if (
                details["source_digest"] != binding["source_digest"]
                or details["environment_digest"] != profile["environment_digest"]
            ):
                applicable = False
                reasons.append("source_or_environment_mismatch")
            passed = (
                applicable
                and receipt["verdict"] == "pass"
                and all(status == "pass" for status in statuses)
            )
        else:
            fields(
                details,
                (
                    "context_digest",
                    "rubric_digest",
                    "criteria",
                    "dimensions",
                    "findings",
                    "check_evidence",
                ),
                "review receipt details",
            )
            require(
                type(receipt["verdict"]) is str
                and receipt["verdict"] in {"pass", "reject", "hold"},
                "invalid review verdict",
            )
            packet = self._json(binding["candidate_packet_digest"])
            criteria = {c["id"] for c in packet["contract"]["task"]["criteria"]}
            for name, expected in (
                ("criteria", criteria),
                ("dimensions", set(DIMENSIONS)),
            ):
                values = details[name]
                require(
                    type(values) is dict
                    and all(
                        type(v) is str and v in {"satisfied", "violated", "unresolved"}
                        for v in values.values()
                    ),
                    "invalid review coverage",
                )
                if set(values) != expected:
                    applicable = False
                    reasons.append(f"{name}_coverage_mismatch")
            if (
                details["context_digest"] != profile["context_digest"]
                or details["rubric_digest"] != profile["rubric_digest"]
                or details["check_evidence"] != binding["check_evidence"]
            ):
                applicable = False
                reasons.append("review_context_or_evidence_mismatch")
            findings = details["findings"]
            require(
                type(findings) is list and len(findings) <= 1000,
                "invalid reviewer findings",
            )
            ids = []
            for finding in findings:
                fields(
                    finding,
                    (
                        "id",
                        "criterion_id",
                        "severity",
                        "location",
                        "reproduction_digest",
                        "expected",
                        "actual",
                        "impact",
                    ),
                    "finding",
                )
                ids.append(ident(finding["id"]))
                require(
                    finding["criterion_id"] is None
                    or (
                        type(finding["criterion_id"]) is str
                        and finding["criterion_id"] in criteria
                    ),
                    "finding names unknown criterion",
                )
                require(
                    type(finding["severity"]) is str
                    and finding["severity"] in {"critical", "major", "minor"},
                    "invalid finding severity",
                )
                for name in ("location", "expected", "actual", "impact"):
                    text(finding[name], f"finding {name}")
                self.artifacts.read(finding["reproduction_digest"])
            unique(ids, "finding id")
            passed = (
                applicable
                and receipt["verdict"] == "pass"
                and not findings
                and all(
                    v == "satisfied"
                    for values in (details["criteria"], details["dimensions"])
                    for v in values.values()
                )
            )
        if not passed:
            reasons.append("failed_or_incomplete")
        return {"applicable": applicable, "passed": passed, "reasons": reasons}

    def submit(self, operation_id, receipt, *, command_id=None):
        self._service()
        receipt = json.loads(canonical(receipt))
        with self.core.store.transaction(write=False):
            reference = self._operation(operation_id)
        require(
            reference["producer"] == self.core.principal.id,
            "receipt producer is not assigned to this operation",
            Conflict,
        )
        require(
            reference["sent_ns"] is not None,
            "verification operation was never dispatched",
            Conflict,
        )
        assessment = self._assess(reference, receipt)
        envelope = {
            "receipt": receipt,
            "assessment": assessment,
            "classification": "scripted_development",
        }
        checksum = digest(envelope)
        self.artifacts.put(canonical(envelope).encode())

        def apply():
            row = self._operation(operation_id)
            self.db.execute(
                "INSERT OR IGNORE INTO verification_observations VALUES(?,?,?,?)",
                (operation_id, checksum, canonical(envelope), time.time_ns()),
            )
            intake = self.core._one(
                "SELECT * FROM candidate_intakes WHERE id=?",
                (row["intake_id"],),
                "candidate intake",
            )
            if row["receipt_digest"] and row["receipt_digest"] != checksum:
                self.core._fence(intake["project_id"])
                self.db.execute(
                    "UPDATE verification_operations SET state='conflicting',version=version+1 WHERE id=?",
                    (operation_id,),
                )
                return {
                    "operation_id": operation_id,
                    "current": False,
                    "conflicting": True,
                    "task_accepted": False,
                }
            try:
                self._current(intake)
                live = row["state"] != "conflicting"
            except Conflict:
                live = False
            duplicate = row["receipt_digest"] == checksum
            state = (
                "returned"
                if live and assessment["applicable"]
                else "held"
                if row["state"] != "conflicting"
                else "conflicting"
            )
            if not duplicate or row["state"] != state:
                self.db.execute(
                    "UPDATE verification_operations SET state=?,version=version+1,receipt=?,receipt_digest=? WHERE id=?",
                    (state, canonical(envelope), checksum, operation_id),
                )
            return {
                "operation_id": operation_id,
                "current": live,
                "state": state,
                "passed": live and assessment["passed"],
                "duplicate": duplicate,
                "receipt_digest": checksum,
                "task_accepted": False,
            }

        return self.core._write(
            "verification.observe",
            {"operation_id": operation_id, "receipt_digest": checksum},
            apply,
            command_id,
        )

    def _passed_operation(self, row):
        require(
            row["state"] == "returned" and row["receipt_digest"],
            "verification result is missing or held",
            Conflict,
        )
        envelope = self._json(row["receipt_digest"])
        require(
            canonical(envelope) == row["receipt"],
            "verification receipt changed",
            Conflict,
        )
        assessment = self._assess(row, envelope["receipt"])
        require(
            assessment["applicable"] and assessment["passed"],
            "verification failed or is incomplete",
            Conflict,
        )
        return {"operation_id": row["id"], "receipt_digest": row["receipt_digest"]}

    def _check_evidence(self, intake_id, spec):
        with self.core.store.transaction(write=False):
            rows = [
                dict(r)
                for r in self.db.execute(
                    "SELECT * FROM verification_operations WHERE intake_id=? AND kind='check' ORDER BY key",
                    (intake_id,),
                ).fetchall()
            ]
        require(
            {r["key"] for r in rows} == {c["check_id"] for c in spec["checks"]},
            "required checks are not all admitted",
            Conflict,
        )
        return [self._passed_operation(row) for row in rows]

    def prepare_review(self, intake_id, *, command_id=None):
        self._service()
        context = self._candidate(intake_id)
        with self.core.store.transaction(write=False):
            policy, spec = self._policy(intake_id)
        session = self._validate_policy(context, spec)
        evidence = self._check_evidence(intake_id, spec)
        packet = {
            "format": "independent-review-input-v1",
            "candidate_packet_digest": context["receipt"]["review_packet"]["sha256"],
            "policy_digest": policy["digest"],
            "check_evidence": evidence,
            "review_profile": spec["review"],
            "session_id": session,
        }
        artifact = self.artifacts.put(canonical(packet).encode())
        return self._prepare(
            context,
            policy,
            "review",
            [("independent", spec["review"])],
            packet=artifact["sha256"],
            evidence=evidence,
            command_id=command_id,
        )

    def gate(self, intake_id):
        try:
            context = self._candidate(intake_id)
            with self.core.store.transaction(write=False):
                _policy, spec = self._policy(intake_id)
            self._validate_policy(context, spec)
            evidence = self._check_evidence(intake_id, spec)
            with self.core.store.transaction(write=False):
                review = self.core._one(
                    "SELECT * FROM verification_operations WHERE intake_id=? AND kind='review'",
                    (intake_id,),
                    "independent review",
                )
            self._passed_operation(review)
            binding = json.loads(review["binding"])
            require(
                binding["check_evidence"] == evidence,
                "review consumed obsolete check evidence",
                Conflict,
            )
            self._json(binding["packet_digest"])
            with self.core.store.transaction(write=False):
                self._current(context["row"])
                current = self._operation(review["id"])
                require(
                    current["state"] == "returned"
                    and current["receipt_digest"] == review["receipt_digest"],
                    "review changed during gate evaluation",
                    Conflict,
                )
            return {
                "intake_id": intake_id,
                "development_ready_for_integration": True,
                "live_eligible": False,
                "task_accepted": False,
                "classification": "scripted_development",
                "candidate_revision": context["receipt"]["candidate"]["revision"],
                "check_evidence": evidence,
                "review_evidence": {
                    "operation_id": review["id"],
                    "receipt_digest": review["receipt_digest"],
                },
                "reasons": [],
            }
        except (Conflict, ValueError, OSError) as error:
            return {
                "intake_id": intake_id,
                "development_ready_for_integration": False,
                "live_eligible": False,
                "task_accepted": False,
                "reasons": [str(error)],
            }
