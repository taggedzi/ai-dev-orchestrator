"""Durable project commands. Only a development-only scripted adapter is enabled."""

import json
import time
from uuid import uuid4

from integrations.openhands import LiveDispatchRefused, OpenHandsClient

from .domain import (
    Conflict,
    Invalid,
    NotFound,
    Principal,
    canonical,
    digest,
    fields,
    ident,
    integer,
    plan_spec,
    project_spec,
    require,
    text,
)
from .evidence import EvidenceStore
from .gsd_import import parse_gsd_import
from .integration import Integration
from .model_policy import ModelPolicy, model_status
from .source import TrustedRepository

ACTIVE = "('reserved','executing','held','awaiting_verification')"


class Coordinator:
    def __init__(self, store, principal):
        require(isinstance(principal, Principal), "trusted principal required")
        self.store, self.principal = store, principal

    @property
    def db(self):
        return self.store.db

    def _write(self, name, payload, action, command_id, *, developer=False):
        if developer:
            self.principal.developer()
        command_id = uuid4().hex if command_id is None else command_id

        def apply():
            result = action()
            self.db.execute(
                "INSERT INTO events(command_id,actor,kind,payload,created_ns) VALUES(?,?,?,?,?)",
                (
                    command_id,
                    self.principal.id,
                    name,
                    canonical({"request": payload, "result": result}),
                    time.time_ns(),
                ),
            )
            return result

        return self.store.command(name, self.principal, payload, apply, command_id)

    def _one(self, sql, parameters, label):
        row = self.db.execute(sql, parameters).fetchone()
        require(row is not None, f"{label} not found", NotFound)
        return dict(row)

    def _project(self, project_id):
        return self._one("SELECT * FROM projects WHERE id=?", (project_id,), "project")

    def _attempt(self, attempt_id):
        return self._one("SELECT * FROM attempts WHERE id=?", (attempt_id,), "attempt")

    def _milestone(self, project_id, key):
        return self._one(
            "SELECT * FROM milestones WHERE project_id=? AND key=?",
            (project_id, key),
            "milestone",
        )

    def _plan(self, plan_id):
        return self._one("SELECT * FROM plans WHERE id=?", (plan_id,), "plan")

    @staticmethod
    def _version(row, expected):
        integer(expected, "expected version")
        require(
            row["version"] == expected,
            "record version changed; inspect current state",
            Conflict,
        )

    def _revision(self, project):
        row = self._one(
            "SELECT * FROM project_revisions WHERE project_id=? AND revision=?",
            (project["id"], project["revision"]),
            "project revision",
        )
        return json.loads(row["spec"])

    def _fence(self, project_id):
        # Prepared work has not been sent. Possible delivery remains an unknown
        # effect; neither pause nor process restart makes it safe to replay.
        self.db.execute(
            "UPDATE operations SET state='cancelled' WHERE state='prepared' AND attempt_id IN (SELECT a.id FROM attempts a JOIN milestones m ON a.milestone_id=m.id WHERE m.project_id=? AND a.state='reserved')",
            (project_id,),
        )
        self.db.execute(
            "UPDATE operations SET state='unknown' WHERE state='possible_send' AND attempt_id IN (SELECT a.id FROM attempts a JOIN milestones m ON a.milestone_id=m.id WHERE m.project_id=?)",
            (project_id,),
        )
        self.db.execute(
            "UPDATE attempts SET state=CASE state WHEN 'reserved' THEN 'cancelled' ELSE 'held' END,version=version+1 WHERE state IN ('reserved','executing','awaiting_verification') AND settled=0 AND milestone_id IN (SELECT id FROM milestones WHERE project_id=?)",
            (project_id,),
        )
        self.db.execute(
            "UPDATE candidate_intakes SET state='held',version=version+1 WHERE project_id=? AND state IN ('prepared','possible_send','sealed')",
            (project_id,),
        )
        self.db.execute(
            "UPDATE verification_operations SET state='held',version=version+1 WHERE intake_id IN (SELECT id FROM candidate_intakes WHERE project_id=?) AND state IN ('prepared','possible_send','returned')",
            (project_id,),
        )
        self.db.execute(
            "UPDATE integration_proposals SET state='held',version=version+1 WHERE project_id=? AND state IN ('prepared','possible_send','staged')",
            (project_id,),
        )
        self.db.execute(
            "UPDATE integration_regressions SET state='held',version=version+1 WHERE proposal_id IN (SELECT id FROM integration_proposals WHERE project_id=?) AND state IN ('prepared','possible_send','returned')",
            (project_id,),
        )
        self.db.execute(
            "UPDATE integration_verifications SET state='held',version=version+1 WHERE proposal_id IN (SELECT id FROM integration_proposals WHERE project_id=?) AND state IN ('prepared','possible_send','returned')",
            (project_id,),
        )
        self.db.execute(
            "UPDATE integration_promotions SET state='held',version=version+1 WHERE project_id=? AND state IN ('prepared','possible_send')",
            (project_id,),
        )
        self.db.execute(
            "UPDATE model_permits SET state='held',version=version+1 WHERE project_id=? AND state IN ('prepared','possible_send')",
            (project_id,),
        )
        self.db.execute(
            "UPDATE projects SET paused=1,generation=generation+1,version=version+1 WHERE id=?",
            (project_id,),
        )

    @staticmethod
    def _discovery_turns(context):
        if "discovery" not in context:
            return []
        discovery = context["discovery"]
        require(
            type(discovery) is dict and set(discovery) == {"turns"},
            "discovery fields must be turns",
        )
        stored = discovery["turns"]
        require(type(stored) is list, "discovery turns must be a list")
        turns = []
        for turn in stored:
            fields(turn, ("n", "question", "answer"), "discovery turn")
            turns.append(
                {
                    "n": integer(turn["n"], "discovery turn revision"),
                    "question": text(turn["question"], "discovery question"),
                    "answer": text(turn["answer"], "discovery answer"),
                }
            )
        return turns

    def _store_revision(self, project, spec):
        self._fence(project["id"])
        revision = project["revision"] + 1
        self.db.execute(
            "INSERT INTO project_revisions VALUES(?,?,?,?)",
            (project["id"], revision, canonical(spec), digest(spec)),
        )
        self.db.execute(
            "UPDATE projects SET revision=? WHERE id=?",
            (revision, project["id"]),
        )
        return {
            "project_id": project["id"],
            "version": project["version"] + 1,
            "requirements_revision": revision,
            "paused": True,
            "needs_new_plan_approval": True,
        }

    def create_project(self, spec, *, command_id=None):
        spec = project_spec(spec)

        def apply():
            project_id = uuid4().hex
            self.db.execute("INSERT INTO projects VALUES(?,1,1,1,0)", (project_id,))
            self.db.execute(
                "INSERT INTO project_revisions VALUES(?,1,?,?)",
                (project_id, canonical(spec), digest(spec)),
            )
            return {"project_id": project_id, "version": 1, "requirements_revision": 1}

        return self._write("project.create", spec, apply, command_id, developer=True)

    def revise_project(self, project_id, spec, *, expected_version, command_id=None):
        spec = project_spec(spec)

        def apply():
            project = self._project(project_id)
            self._version(project, expected_version)
            return self._store_revision(project, spec)

        return self._write(
            "project.revise",
            {
                "project_id": project_id,
                "spec": spec,
                "expected_version": expected_version,
            },
            apply,
            command_id,
            developer=True,
        )

    def record_discovery(
        self,
        project_id,
        *,
        expected_version,
        question,
        answer,
        requirements=None,
        command_id=None,
    ):
        question = text(question, "discovery question")
        answer = text(answer, "discovery answer")
        if requirements is not None:
            project_spec(
                {
                    "name": "stored",
                    "repository": "stored",
                    "requirements": requirements,
                    "context": {"goal": "stored"},
                }
            )

        def apply():
            project = self._project(project_id)
            self._version(project, expected_version)
            current = self._revision(project)
            context = dict(current["context"])
            turns = self._discovery_turns(context)
            turns.append(
                {
                    "n": project["revision"] + 1,
                    "question": question,
                    "answer": answer,
                }
            )
            context["discovery"] = {"turns": turns}
            spec = project_spec(
                {
                    "name": current["name"],
                    "repository": current["repository"],
                    "requirements": current["requirements"]
                    if requirements is None
                    else requirements,
                    "context": context,
                }
            )
            return self._store_revision(project, spec)

        return self._write(
            "discovery.record",
            {
                "project_id": project_id,
                "expected_version": expected_version,
                "question": question,
                "answer": answer,
                "requirements": requirements,
            },
            apply,
            command_id,
            developer=True,
        )

    def submit_plan(
        self,
        project_id,
        milestone_key,
        spec,
        *,
        expected_project_version,
        command_id=None,
        source_digest=None,
    ):
        ident(milestone_key, "milestone key")
        if source_digest is not None:
            require(
                type(source_digest) is str
                and len(source_digest) == 64
                and all(character in "0123456789abcdef" for character in source_digest),
                "snapshot digest must be lowercase sha256",
            )

        def apply():
            project = self._project(project_id)
            self._version(project, expected_project_version)
            normalized = plan_spec(
                spec, {r["id"] for r in self._revision(project)["requirements"]}
            )
            require(
                normalized["requirements_revision"] == project["revision"],
                "plan requirements revision is stale",
                Conflict,
            )
            milestone = self.db.execute(
                "SELECT * FROM milestones WHERE project_id=? AND key=?",
                (project_id, milestone_key),
            ).fetchone()
            if milestone is None:
                milestone_id, version, revision = uuid4().hex, 1, 1
                self.db.execute(
                    "INSERT INTO milestones VALUES(?,?,?,1,NULL,?)",
                    (
                        milestone_id,
                        project_id,
                        milestone_key,
                        normalized["baseline_revision"],
                    ),
                )
            else:
                milestone_id, version = milestone["id"], milestone["version"] + 1
                revision = self.db.execute(
                    "SELECT MAX(revision)+1 FROM plans WHERE milestone_id=?",
                    (milestone_id,),
                ).fetchone()[0]
                self.db.execute(
                    "UPDATE milestones SET version=? WHERE id=?",
                    (version, milestone_id),
                )
            plan_id, checksum = uuid4().hex, digest(normalized)
            self.db.execute(
                "INSERT INTO plans VALUES(?,?,?,?,?)",
                (plan_id, milestone_id, revision, canonical(normalized), checksum),
            )
            return {
                "plan_id": plan_id,
                "digest": checksum,
                "revision": revision,
                "milestone_version": version,
                "project_version": project["version"],
                "approved": False,
            }

        payload = {
            "project_id": project_id,
            "milestone_key": milestone_key,
            "spec": spec,
            "expected_project_version": expected_project_version,
        }
        if source_digest is not None:
            payload["snapshot_sha256"] = source_digest
        return self._write("plan.submit", payload, apply, command_id)

    def import_gsd(
        self,
        project_id,
        milestone_key,
        snapshot,
        snapshot_digest,
        plans,
        *,
        expected_project_version,
        baseline_revision,
        max_attempts,
        check_timeout_seconds,
        command_id=None,
    ):
        """Import one frozen schema-1 phase and submit it unapproved."""
        self.principal.developer()
        parsed = parse_gsd_import(snapshot, snapshot_digest, plans)
        with self.store.transaction(write=False):
            project = self._project(project_id)
            self._version(project, expected_project_version)
            revision = project["revision"]
            current_ids = {row["id"] for row in self._revision(project)["requirements"]}
        for requirement_id in parsed["snapshot_requirement_ids"]:
            require(requirement_id in current_ids, "snapshot requirement is absent")
        tasks = []
        for task in parsed["tasks"]:
            tasks.append(
                {
                    "id": task["id"],
                    "title": task["title"],
                    "instructions": task["instructions"],
                    "depends_on": task["depends_on"],
                    "allowed_paths": task["allowed_paths"],
                    "criteria": [
                        {
                            "id": criterion["id"],
                            "description": criterion["description"],
                            "requirement_id": criterion["requirement_id"],
                            "checks": ["verify"],
                        }
                        for criterion in task["criteria"]
                    ],
                    "checks": [
                        {
                            "id": "verify",
                            "argv": task["argv"],
                            "timeout_seconds": check_timeout_seconds,
                        }
                    ],
                    "max_attempts": max_attempts,
                }
            )
        spec = plan_spec(
            {
                "title": parsed["title"],
                "baseline_revision": baseline_revision,
                "requirements_revision": revision,
                "tasks": tasks,
            },
            current_ids,
        )
        return self.submit_plan(
            project_id,
            milestone_key,
            spec,
            expected_project_version=expected_project_version,
            command_id=command_id,
            source_digest=snapshot_digest,
        )

    def approve_plan(
        self,
        plan_id,
        checksum,
        *,
        expected_project_version,
        expected_milestone_version,
        command_id=None,
    ):
        def apply():
            plan = self._plan(plan_id)
            milestone = self._one(
                "SELECT * FROM milestones WHERE id=?",
                (plan["milestone_id"],),
                "milestone",
            )
            project = self._project(milestone["project_id"])
            self._version(project, expected_project_version)
            self._version(milestone, expected_milestone_version)
            require(
                plan["digest"] == checksum,
                "approval digest does not match exact plan",
                Conflict,
            )
            spec = json.loads(plan["spec"])
            require(
                spec["requirements_revision"] == project["revision"],
                "requirements changed since plan submission",
                Conflict,
            )
            require(
                spec["baseline_revision"] == milestone["head_revision"],
                "plan baseline differs from milestone head",
                Conflict,
            )
            unsettled = self.db.execute(
                f"SELECT 1 FROM attempts a JOIN milestones m ON a.milestone_id=m.id WHERE m.project_id=? AND a.state IN {ACTIVE} AND a.settled=0",
                (project["id"],),
            ).fetchone()
            require(
                unsettled is None,
                "unsettled attempts prevent replacing plan authority",
                Conflict,
            )
            require(
                self.db.execute(
                    "SELECT 1 FROM approvals WHERE plan_id=?", (plan_id,)
                ).fetchone()
                is None,
                "plan already approved; use its existing authority",
                Conflict,
            )
            self.db.execute(
                "INSERT INTO approvals VALUES(?,?,?,?)",
                (plan_id, self.principal.id, checksum, time.time_ns()),
            )
            self.db.execute(
                "UPDATE milestones SET approved_plan_id=?,version=version+1 WHERE id=?",
                (plan_id, milestone["id"]),
            )
            self.db.execute(
                "UPDATE projects SET version=version+1,generation=generation+1 WHERE id=?",
                (project["id"],),
            )
            return {
                "plan_id": plan_id,
                "digest": checksum,
                "project_version": project["version"] + 1,
                "milestone_version": milestone["version"] + 1,
                "approved": True,
            }

        return self._write(
            "plan.approve",
            {
                "plan_id": plan_id,
                "digest": checksum,
                "expected_project_version": expected_project_version,
                "expected_milestone_version": expected_milestone_version,
            },
            apply,
            command_id,
            developer=True,
        )

    def pause(self, project_id, *, expected_version, reason, command_id=None):
        text(reason, "pause/recovery reason")

        def apply():
            project = self._project(project_id)
            self._version(project, expected_version)
            self._fence(project_id)
            return {
                "project_id": project_id,
                "version": expected_version + 1,
                "paused": True,
                "generation": project["generation"] + 1,
            }

        return self._write(
            "project.pause",
            {
                "project_id": project_id,
                "expected_version": expected_version,
                "reason": reason,
            },
            apply,
            command_id,
            developer=True,
        )

    def recover(self, project_id, *, expected_version, reason, command_id=None):
        # Recovery fences rather than inferring that a former sender stopped.
        return self.pause(
            project_id,
            expected_version=expected_version,
            reason="recovery: " + text(reason, "recovery reason"),
            command_id=command_id,
        )

    def resume(self, project_id, *, expected_version, command_id=None):
        def apply():
            project = self._project(project_id)
            self._version(project, expected_version)
            require(project["paused"] == 1, "project is not paused", Conflict)
            active = self.db.execute(
                "SELECT p.spec FROM milestones m JOIN plans p ON m.approved_plan_id=p.id WHERE m.project_id=?",
                (project_id,),
            ).fetchall()
            require(
                any(
                    json.loads(p["spec"])["requirements_revision"]
                    == project["revision"]
                    for p in active
                ),
                "no current approved plan; approve current intent before resuming",
                Conflict,
            )
            self.db.execute(
                "UPDATE projects SET paused=0,version=version+1,generation=generation+1 WHERE id=?",
                (project_id,),
            )
            return {
                "project_id": project_id,
                "version": expected_version + 1,
                "paused": False,
                "generation": project["generation"] + 1,
            }

        return self._write(
            "project.resume",
            {"project_id": project_id, "expected_version": expected_version},
            apply,
            command_id,
            developer=True,
        )

    def claim_task(
        self,
        project_id,
        milestone_key,
        task_key,
        *,
        expected_project_version,
        expected_milestone_version,
        command_id=None,
    ):
        def apply():
            project = self._project(project_id)
            milestone = self._milestone(project_id, milestone_key)
            self._version(project, expected_project_version)
            self._version(milestone, expected_milestone_version)
            require(not project["paused"], "project is paused", Conflict)
            require(
                milestone["approved_plan_id"] is not None,
                "milestone has no approved plan",
                Conflict,
            )
            plan = self._plan(milestone["approved_plan_id"])
            spec = json.loads(plan["spec"])
            require(
                spec["requirements_revision"] == project["revision"],
                "approved plan is superseded by requirements",
                Conflict,
            )
            task = next((t for t in spec["tasks"] if t["id"] == task_key), None)
            require(task is not None, "task not found in approved plan", NotFound)
            accepted = {
                r[0]
                for r in self.db.execute(
                    "SELECT task_key FROM acceptances WHERE plan_id=?", (plan["id"],)
                )
            }
            require(task_key not in accepted, "task is already accepted", Conflict)
            require(
                set(task["depends_on"]) <= accepted,
                "task dependencies are not accepted",
                Conflict,
            )
            require(
                self.db.execute(
                    f"SELECT 1 FROM attempts WHERE milestone_id=? AND state IN {ACTIVE} AND settled=0",
                    (milestone["id"],),
                ).fetchone()
                is None,
                "milestone has an unsettled attempt",
                Conflict,
            )
            count = self.db.execute(
                "SELECT COUNT(*) FROM attempts WHERE milestone_id=? AND task_key=?",
                (milestone["id"], task_key),
            ).fetchone()[0]
            require(
                count < task["max_attempts"],
                "absolute task attempt limit exhausted",
                Conflict,
            )
            attempt_id, operation_id = uuid4().hex, uuid4().hex
            assignment = {
                "profile": "scripted-development-v1",
                "reason": "development-only; no live adapter qualified",
                "requested_model": "scripted/model-v1",
                "resolved_model": None,
                "resolved_provider": None,
                "cost_kind": "simulated",
            }
            self.db.execute(
                "INSERT INTO attempts VALUES(?,?,?,?,?,1,'reserved','scripted',?,?,0)",
                (
                    attempt_id,
                    milestone["id"],
                    plan["id"],
                    task_key,
                    project["generation"],
                    milestone["head_revision"],
                    canonical(assignment),
                ),
            )
            self.db.execute(
                "INSERT INTO operations VALUES(?,?,'prepared',NULL)",
                (operation_id, attempt_id),
            )
            return {
                "attempt_id": attempt_id,
                "operation_id": operation_id,
                "version": 1,
                "state": "reserved",
                "adapter": "scripted",
                "input_revision": milestone["head_revision"],
            }

        return self._write(
            "task.claim",
            {
                "project_id": project_id,
                "milestone_key": milestone_key,
                "task_key": task_key,
                "expected_project_version": expected_project_version,
                "expected_milestone_version": expected_milestone_version,
            },
            apply,
            command_id,
        )

    def refuse_live_dispatch(self, project_id, operation):
        try:
            OpenHandsClient().dispatch(operation, project_id=project_id)
        except LiveDispatchRefused as error:
            return error.refusal
        raise RuntimeError("disabled live dispatch returned without a refusal")

    def start_scripted(self, attempt_id, *, expected_version, command_id=None):
        def apply():
            attempt = self._attempt(attempt_id)
            self._version(attempt, expected_version)
            milestone = self._one(
                "SELECT * FROM milestones WHERE id=?",
                (attempt["milestone_id"],),
                "milestone",
            )
            project = self._project(milestone["project_id"])
            require(
                attempt["adapter"] == "scripted",
                "only the scripted development adapter is enabled",
            )
            require(
                not project["paused"]
                and project["generation"] == attempt["project_generation"]
                and milestone["approved_plan_id"] == attempt["plan_id"],
                "attempt authority is fenced",
                Conflict,
            )
            require(
                attempt["state"] == "reserved",
                "attempt cannot dispatch again",
                Conflict,
            )
            operation = self._one(
                "SELECT * FROM operations WHERE attempt_id=?",
                (attempt_id,),
                "operation",
            )
            require(
                operation["state"] == "prepared",
                "operation may already have been delivered",
                Conflict,
            )
            self.db.execute(
                "UPDATE operations SET state='possible_send' WHERE id=?",
                (operation["id"],),
            )
            self.db.execute(
                "UPDATE attempts SET state='executing',version=version+1,assignment=? WHERE id=?",
                (
                    canonical(
                        {
                            **json.loads(attempt["assignment"]),
                            "implementation_actor": self.principal.id,
                            "implementation_context": operation["id"],
                        }
                    ),
                    attempt_id,
                ),
            )
            return {
                "operation_id": operation["id"],
                "attempt_id": attempt_id,
                "version": expected_version + 1,
                "state": "possible_send",
                "simulated": True,
            }

        return self._write(
            "scripted.start",
            {"attempt_id": attempt_id, "expected_version": expected_version},
            apply,
            command_id,
        )

    def record_scripted_result(
        self, operation_id, outcome, *, detail="", command_id=None
    ):
        require(
            type(outcome) is str and outcome in {"candidate", "failed"},
            "scripted outcome must be candidate or failed",
        )
        require(type(detail) is str and len(detail) <= 65536, "invalid result detail")
        receipt = {
            "outcome": outcome,
            "detail": detail,
            "simulated": True,
            "resolved_model": "scripted/model-v1",
            "resolved_provider": "scripted-local",
            "cost_kind": "simulated",
            "cost": 0,
        }

        def apply():
            operation = self._one(
                "SELECT * FROM operations WHERE id=?", (operation_id,), "operation"
            )
            attempt = self._attempt(operation["attempt_id"])
            require(
                attempt["adapter"] == "scripted",
                "scripted receipt cannot settle a live adapter",
            )
            milestone = self._one(
                "SELECT * FROM milestones WHERE id=?",
                (attempt["milestone_id"],),
                "milestone",
            )
            project = self._project(milestone["project_id"])
            checksum = digest(receipt)
            duplicate = self.db.execute(
                "SELECT 1 FROM observations WHERE operation_id=? AND digest=?",
                (operation_id, checksum),
            ).fetchone()
            if duplicate:
                live = (
                    not project["paused"]
                    and project["generation"] == attempt["project_generation"]
                )
                return {
                    "operation_id": operation_id,
                    "accepted": live and operation["state"] == "returned",
                    "duplicate": True,
                }
            self.db.execute(
                "INSERT INTO observations VALUES(?,?,?,?)",
                (operation_id, checksum, canonical(receipt), time.time_ns()),
            )
            if (
                project["paused"]
                or project["generation"] != attempt["project_generation"]
            ):
                return {
                    "operation_id": operation_id,
                    "accepted": False,
                    "late_observation_retained": True,
                }
            if operation["state"] == "returned":
                self._fence(project["id"])
                self.db.execute(
                    "UPDATE attempts SET state='held',version=version+1 WHERE id=?",
                    (attempt["id"],),
                )
                self.db.execute(
                    "UPDATE operations SET state='conflicting' WHERE id=?",
                    (operation_id,),
                )
                return {
                    "operation_id": operation_id,
                    "accepted": False,
                    "conflicting_receipts": True,
                }
            require(
                operation["state"] == "possible_send"
                and attempt["state"] == "executing",
                "operation was not dispatched or is held",
                Conflict,
            )
            state = "awaiting_verification" if outcome == "candidate" else "failed"
            self.db.execute(
                "UPDATE operations SET state='returned',result=? WHERE id=?",
                (canonical(receipt), operation_id),
            )
            self.db.execute(
                "UPDATE attempts SET state=?,version=version+1,assignment=? WHERE id=?",
                (
                    state,
                    canonical(
                        {
                            **json.loads(attempt["assignment"]),
                            "resolved_model": receipt["resolved_model"],
                            "resolved_provider": receipt["resolved_provider"],
                        }
                    ),
                    attempt["id"],
                ),
            )
            return {
                "operation_id": operation_id,
                "attempt_id": attempt["id"],
                "accepted": True,
                "attempt_state": state,
                "task_accepted": False,
                "simulated": True,
            }

        return self._write(
            "scripted.result",
            {"operation_id": operation_id, "receipt": receipt},
            apply,
            command_id,
        )

    def abandon_scripted(
        self, attempt_id, *, expected_version, reason, command_id=None
    ):
        text(reason, "reconciliation reason")

        def apply():
            attempt = self._attempt(attempt_id)
            self._version(attempt, expected_version)
            milestone = self._one(
                "SELECT * FROM milestones WHERE id=?",
                (attempt["milestone_id"],),
                "milestone",
            )
            project = self._project(milestone["project_id"])
            require(
                attempt["adapter"] == "scripted"
                and attempt["state"] == "held"
                and project["paused"]
                and project["generation"] != attempt["project_generation"],
                "only fenced, held scripted work can be abandoned",
                Conflict,
            )
            self.db.execute(
                "UPDATE attempts SET state='failed',version=version+1 WHERE id=?",
                (attempt_id,),
            )
            self.db.execute(
                "UPDATE operations SET state='abandoned' WHERE attempt_id=?",
                (attempt_id,),
            )
            return {
                "attempt_id": attempt_id,
                "version": expected_version + 1,
                "state": "failed",
                "simulated": True,
            }

        return self._write(
            "scripted.abandon",
            {
                "attempt_id": attempt_id,
                "expected_version": expected_version,
                "reason": reason,
            },
            apply,
            command_id,
            developer=True,
        )

    def _bound_integration(self, repository, artifacts):
        self.principal.developer()
        try:
            repo = TrustedRepository(repository)
            evidence = EvidenceStore(artifacts)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            raise Invalid(
                "managed repository or evidence store is not available"
            ) from error
        return Integration(self, repo, evidence)

    def cost_report(self, project_id, milestone_key):
        self.principal.developer()
        return ModelPolicy(self).report(project_id, milestone_key)

    def approve_model_policy(
        self,
        project_id,
        milestone_key,
        spec,
        *,
        expected_project_version,
        expected_milestone_version,
        command_id=None,
    ):
        return ModelPolicy(self).approve_policy(
            project_id,
            milestone_key,
            spec,
            expected_project_version=expected_project_version,
            expected_milestone_version=expected_milestone_version,
            command_id=command_id,
        )

    def assign_model(
        self,
        attempt_id,
        role,
        route_id,
        requested,
        *,
        expected_attempt_version,
        expected_project_version,
        command_id=None,
    ):
        return ModelPolicy(self).assign(
            attempt_id,
            role,
            route_id,
            requested,
            expected_attempt_version=expected_attempt_version,
            expected_project_version=expected_project_version,
            command_id=command_id,
        )

    def begin_model_permit(
        self,
        assignment_id,
        route_id,
        submission_id,
        reserved_units,
        request_digest,
        *,
        expected_project_version,
        command_id=None,
    ):
        return ModelPolicy(self).begin_permit(
            assignment_id,
            route_id,
            submission_id,
            reserved_units,
            request_digest,
            expected_project_version=expected_project_version,
            command_id=command_id,
        )

    def lose_model_response(self, permit_id, *, expected_version, command_id=None):
        return ModelPolicy(self).lose_response(
            permit_id, expected_version=expected_version, command_id=command_id
        )

    def observe_model_usage(
        self, permit_id, usage, *, expected_version, command_id=None
    ):
        return ModelPolicy(self).observe_usage(
            permit_id, usage, expected_version=expected_version, command_id=command_id
        )

    def authorize_diverged_head(
        self,
        attempt_id,
        previous_head,
        new_head,
        authority_generation,
        *,
        repository,
        artifacts,
        command_id=None,
    ):
        return self._bound_integration(repository, artifacts).authorize_diverged_head(
            attempt_id,
            previous_head,
            new_head,
            authority_generation,
            command_id=command_id,
        )

    def approve_regressions(
        self,
        proposal_id,
        spec,
        checksum,
        *,
        expected_version,
        repository,
        artifacts,
        command_id=None,
    ):
        return self._bound_integration(repository, artifacts).approve_regressions(
            proposal_id,
            spec,
            checksum,
            expected_version=expected_version,
            command_id=command_id,
        )

    def approve_evidence(
        self,
        proposal_id,
        spec,
        checksum,
        *,
        expected_version,
        repository,
        artifacts,
        command_id=None,
    ):
        return self._bound_integration(repository, artifacts).approve_evidence(
            proposal_id,
            spec,
            checksum,
            expected_version=expected_version,
            command_id=command_id,
        )

    def begin_promotion(
        self,
        proposal_id,
        *,
        expected_version,
        repository,
        artifacts,
        command_id=None,
    ):
        return self._bound_integration(repository, artifacts).begin_promotion(
            proposal_id, expected_version=expected_version, command_id=command_id
        )

    def promote(self, proposal_id, *, expected_version, repository, artifacts):
        return self._bound_integration(repository, artifacts).promote(
            proposal_id, expected_version=expected_version
        )

    def reconcile_promotion(self, proposal_id, *, repository, artifacts):
        return self._bound_integration(repository, artifacts).reconcile_promotion(
            proposal_id
        )

    def _cost_totals(self, reports):
        names = (
            "known_units",
            "estimated_units",
            "pending_units",
            "unknown_units",
        )
        return {name: sum(report[name] for report in reports) for name in names} | {
            "live_eligible": False
        }

    def _pending_decisions(self, project, milestones, plans, policies, promotions):
        by_id = {milestone["id"]: milestone for milestone in milestones}
        covered = {policy["milestone_id"] for policy in policies}
        decisions = []
        for plan in plans:
            milestone = by_id[plan["milestone_id"]]
            approved = milestone["approved_plan_id"] == plan["id"]
            stale = plan["spec"]["requirements_revision"] != project["revision"]
            if not approved:
                decisions.append(
                    {
                        "kind": "plan_approval",
                        "milestone_key": milestone["key"],
                        "plan_id": plan["id"],
                        "digest": plan["digest"],
                        "summary": f"Approve the exact plan for {milestone['key']}",
                    }
                )
            elif stale:
                decisions.append(
                    {
                        "kind": "requirements_changed",
                        "milestone_key": milestone["key"],
                        "plan_id": plan["id"],
                        "summary": (
                            f"Requirements changed for {milestone['key']}; "
                            "approve a matching plan"
                        ),
                    }
                )
        for milestone in milestones:
            if milestone["approved_plan_id"] and milestone["id"] not in covered:
                decisions.append(
                    {
                        "kind": "model_policy",
                        "milestone_key": milestone["key"],
                        "milestone_id": milestone["id"],
                        "summary": (
                            f"Approve a scripted model policy for {milestone['key']}"
                        ),
                    }
                )
        for item in promotions:
            if item["state"] in {"possible_send", "held"}:
                decisions.append(
                    {
                        "kind": "promotion_reconcile",
                        "promotion_id": item["id"],
                        "proposal_id": item["proposal_id"],
                        "state": item["state"],
                        "summary": "Reconcile the scripted promotion",
                    }
                )
        return decisions

    def status(self, project_id):
        with self.store.transaction(write=False):
            project = self._project(project_id)
            milestones = []
            for milestone_row in self.db.execute(
                "SELECT * FROM milestones WHERE project_id=? ORDER BY key",
                (project_id,),
            ).fetchall():
                milestone = dict(milestone_row)
                plan = (
                    self._plan(milestone["approved_plan_id"])
                    if milestone["approved_plan_id"]
                    else None
                )
                task_states = []
                if plan:
                    spec = json.loads(plan["spec"])
                    accepted = {
                        r[0]
                        for r in self.db.execute(
                            "SELECT task_key FROM acceptances WHERE plan_id=?",
                            (plan["id"],),
                        )
                    }
                    for task in spec["tasks"]:
                        latest = self.db.execute(
                            "SELECT state FROM attempts WHERE milestone_id=? AND task_key=? AND settled=0 AND state IN "
                            + ACTIVE,
                            (milestone["id"], task["id"]),
                        ).fetchone()
                        count = self.db.execute(
                            "SELECT COUNT(*) FROM attempts WHERE milestone_id=? AND task_key=?",
                            (milestone["id"], task["id"]),
                        ).fetchone()[0]
                        state = "ready"
                        if task["id"] in accepted:
                            state = "accepted"
                        elif latest:
                            state = latest["state"]
                        elif not set(task["depends_on"]) <= accepted:
                            state = "blocked_dependencies"
                        elif count >= task["max_attempts"]:
                            state = "exhausted"
                        elif spec["requirements_revision"] != project["revision"]:
                            state = "needs_approval"
                        elif project["paused"]:
                            state = "paused"
                        task_states.append(
                            {
                                "id": task["id"],
                                "title": task["title"],
                                "state": state,
                                "attempts_consumed": count,
                                "max_attempts": task["max_attempts"],
                            }
                        )
                milestones.append(
                    {
                        **milestone,
                        "approved_plan_digest": plan["digest"] if plan else None,
                        "tasks": task_states,
                    }
                )
            attempts = []
            for row in self.db.execute(
                "SELECT a.*,o.id AS operation_id,o.state AS operation_state,o.result FROM attempts a JOIN operations o ON o.attempt_id=a.id JOIN milestones m ON a.milestone_id=m.id WHERE m.project_id=? ORDER BY a.rowid",
                (project_id,),
            ):
                value = dict(row)
                value["assignment"] = json.loads(value["assignment"])
                value["result"] = (
                    json.loads(value["result"]) if value["result"] else None
                )
                attempts.append(value)
            plans = [
                dict(r)
                for r in self.db.execute(
                    "SELECT p.id,p.milestone_id,p.revision,p.digest,p.spec FROM plans p JOIN milestones m ON m.id=p.milestone_id WHERE m.project_id=? ORDER BY p.rowid",
                    (project_id,),
                )
            ]
            for plan in plans:
                plan["spec"] = json.loads(plan["spec"])
            intakes = []
            for row in self.db.execute(
                "SELECT * FROM candidate_intakes WHERE project_id=? ORDER BY created_ns,id",
                (project_id,),
            ):
                item = dict(row)
                item["contract"] = json.loads(item["contract"])
                item["receipt"] = (
                    json.loads(item["receipt"]) if item["receipt"] else None
                )
                item["current"] = (
                    item["state"] == "sealed"
                    and not project["paused"]
                    and item["contract"]["generation"] == project["generation"]
                )
                intakes.append(item)
            verification = []
            for row in self.db.execute(
                "SELECT v.* FROM verification_operations v JOIN candidate_intakes i ON i.id=v.intake_id WHERE i.project_id=? ORDER BY v.created_ns,v.id",
                (project_id,),
            ):
                item = dict(row)
                item["binding"] = json.loads(item["binding"])
                item["receipt"] = (
                    json.loads(item["receipt"]) if item["receipt"] else None
                )
                verification.append(item)
            proposals = []
            for row in self.db.execute(
                "SELECT * FROM integration_proposals WHERE project_id=? ORDER BY created_ns,id",
                (project_id,),
            ):
                item = dict(row)
                item["intent"] = json.loads(item["intent"])
                item["receipt"] = (
                    json.loads(item["receipt"]) if item["receipt"] else None
                )
                proposals.append(item)
            mappings = [
                dict(row)
                for row in self.db.execute(
                    "SELECT * FROM integration_head_mappings WHERE project_id=? ORDER BY created_ns,id",
                    (project_id,),
                )
            ]
            regressions = []
            for row in self.db.execute(
                "SELECT r.* FROM integration_regressions r JOIN integration_proposals p ON p.id=r.proposal_id WHERE p.project_id=? ORDER BY r.created_ns,r.id",
                (project_id,),
            ):
                item = dict(row)
                item["binding"] = json.loads(item["binding"])
                item["receipt"] = (
                    json.loads(item["receipt"]) if item["receipt"] else None
                )
                regressions.append(item)
            integrated = []
            for row in self.db.execute(
                "SELECT v.* FROM integration_verifications v JOIN integration_proposals p ON p.id=v.proposal_id WHERE p.project_id=? ORDER BY v.created_ns,v.id",
                (project_id,),
            ):
                item = dict(row)
                item["binding"] = json.loads(item["binding"])
                item["receipt"] = (
                    json.loads(item["receipt"]) if item["receipt"] else None
                )
                integrated.append(item)
            promotions = []
            for row in self.db.execute(
                "SELECT * FROM integration_promotions WHERE project_id=? ORDER BY created_ns,id",
                (project_id,),
            ):
                item = dict(row)
                item["evidence"] = json.loads(item["evidence"])
                item["receipt"] = (
                    json.loads(item["receipt"]) if item["receipt"] else None
                )
                promotions.append(item)
            reported = model_status(self.db, project_id)
            return {
                "project": {**project, "spec": self._revision(project)},
                "milestones": milestones,
                "plans": plans,
                "attempts": attempts,
                "candidate_intakes": intakes,
                "verification_operations": verification,
                "integration_proposals": proposals,
                "integration_head_mappings": mappings,
                "integration_regressions": regressions,
                "integration_verifications": integrated,
                "integration_promotions": promotions,
                **reported,
                "cost": self._cost_totals(reported["model_reports"]),
                "pending_decisions": self._pending_decisions(
                    project,
                    milestones,
                    plans,
                    reported["model_policies"],
                    promotions,
                ),
                "scripted_task_accepted": any(
                    (item["receipt"] or {}).get("task_accepted") is True
                    for item in promotions
                ),
                "live_eligible": False,
                "capabilities": {
                    "execution": "scripted development only",
                    "native_execution": False,
                    "task_acceptance": False,
                },
            }

    def list_projects(self):
        with self.store.transaction(write=False):
            result = []
            for row in self.db.execute("SELECT * FROM projects ORDER BY rowid"):
                project = dict(row)
                spec = self._revision(project)
                result.append(
                    {**project, "name": spec["name"], "repository": spec["repository"]}
                )
            return result

    def event_page(self, *, after=0, limit=100):
        integer(after, "event cursor", minimum=0)
        integer(limit, "event page size", maximum=200)
        with self.store.transaction(write=False):
            items = [
                {**dict(row), "payload": json.loads(row["payload"])}
                for row in self.db.execute(
                    "SELECT * FROM events WHERE sequence>? ORDER BY sequence LIMIT ?",
                    (after, limit),
                )
            ]
            return {
                "items": items,
                "next_sequence": items[-1]["sequence"] if items else after,
            }

    def events(self):
        with self.store.transaction(write=False):
            return [
                {**dict(row), "payload": json.loads(row["payload"])}
                for row in self.db.execute("SELECT * FROM events ORDER BY sequence")
            ]
