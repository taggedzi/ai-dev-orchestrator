"""Durable model eligibility, broker permits, and cost reports.

This module records scripted policy decisions only. It does not open a socket,
call a provider, or make a route live-eligible.
"""

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
)

MISSING_OBSERVED = ("provider", "resolved_model", "response_id")
ROLES = ("implementation", "review")
QUALITIES = ("known", "estimated", "pending", "unknown")


def _sha256(value, label):
    require(
        type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
        f"invalid {label}",
    )
    return value


def _optional_text(value, label):
    if value is None:
        return None
    cleaned = text(value, label, 200)
    require(
        "://" not in cleaned and any(c.isspace() for c in cleaned) is False,
        f"invalid {label}",
    )
    return cleaned


def _optional_units(value, label):
    if value is None:
        return None
    return integer(value, label, minimum=0)


def _policy_spec(value):
    fields(value, ("classification", "limits", "routes"), "model policy")
    require(
        value["classification"] == "scripted_development",
        "model policy classification must be scripted_development",
    )
    fields(
        value["limits"],
        ("max_reserved_units", "max_submissions", "protected_review_units"),
        "model limits",
    )
    maximum = integer(
        value["limits"]["max_reserved_units"], "max reserved units", minimum=0
    )
    submissions = integer(
        value["limits"]["max_submissions"], "max submissions", maximum=10000
    )
    protected = integer(
        value["limits"]["protected_review_units"], "protected review units", minimum=0
    )
    require(
        protected <= maximum, "protected review allowance exceeds the cumulative limit"
    )
    routes = value["routes"]
    require(
        type(routes) is list and 1 <= len(routes) <= 100,
        "routes must be a nonempty list",
    )
    seen = []
    for route in routes:
        fields(route, ("id", "kind", "requested_model", "available"), "route")
        seen.append(ident(route["id"], "route id"))
        require(route["kind"] in {"local", "gateway", "direct"}, "invalid route kind")
        text(route["requested_model"], "requested model", 200)
        require(type(route["available"]) is bool, "route availability must be boolean")
    require(len(seen) == len(set(seen)), "duplicate route id")
    require(submissions >= 1, "invalid max submissions")
    return json.loads(canonical(value))


def _requested(value):
    fields(
        value,
        ("model", "max_output_tokens", "reasoning_effort"),
        "requested configuration",
    )
    text(value["model"], "requested model", 200)
    integer(value["max_output_tokens"], "max output tokens", maximum=10_000_000)
    require(
        value["reasoning_effort"] in {"none", "low", "medium", "high"},
        "invalid reasoning effort",
    )
    return json.loads(canonical(value))


def _usage(value, reserved_units):
    fields(
        value,
        (
            "quality",
            "units",
            "input_tokens",
            "output_tokens",
            "provider",
            "resolved_model",
            "response_id",
        ),
        "usage",
    )
    require(value["quality"] in QUALITIES, "invalid usage quality")
    units = _optional_units(value["units"], "usage units")
    tokens_in = _optional_units(value["input_tokens"], "input tokens")
    tokens_out = _optional_units(value["output_tokens"], "output tokens")
    provider = _optional_text(value["provider"], "provider")
    resolved = _optional_text(value["resolved_model"], "resolved model")
    response = _optional_text(value["response_id"], "response id")
    if value["quality"] in {"known", "estimated"}:
        require(
            units is not None and units <= reserved_units,
            "usage units exceed the reservation",
        )
    else:
        require(
            units is None and tokens_in is None and tokens_out is None,
            "pending or unknown usage cannot carry amounts",
        )
        require(
            provider is None and resolved is None and response is None,
            "pending or unknown usage cannot carry a resolved identity",
        )
    return {
        "format": "model-usage-v1",
        "quality": value["quality"],
        "units": units,
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
        "provider": provider,
        "resolved_model": resolved,
        "response_id": response,
    }


def _unknown_usage():
    return _usage(
        {
            "quality": "unknown",
            "units": None,
            "input_tokens": None,
            "output_tokens": None,
            "provider": None,
            "resolved_model": None,
            "response_id": None,
        },
        0,
    )


def _charge(row):
    if row["state"] == "prepared":
        return 0
    if row["state"] == "reconciled":
        return row["settled_units"]
    return row["reserved_units"]


def _charges(db, milestone_id):
    implementation = review = total = submissions = 0
    for row in db.execute(
        "SELECT role,state,reserved_units,settled_units FROM model_permits WHERE milestone_id=?",
        (milestone_id,),
    ):
        amount = _charge(row)
        if row["state"] != "prepared":
            submissions += 1
        total += amount
        if row["role"] == "review":
            review += amount
        else:
            implementation += amount
    return {
        "implementation": implementation,
        "review": review,
        "total": total,
        "submissions": submissions,
    }


def _missing_from(usages):
    found = set()
    for usage in usages:
        for name in MISSING_OBSERVED:
            if usage.get(name):
                found.add(name)
    return [name for name in MISSING_OBSERVED if name not in found]


def model_status(db, project_id):
    policies = []
    for row in db.execute(
        "SELECT * FROM model_policies WHERE project_id=? ORDER BY approved_ns,id",
        (project_id,),
    ):
        item = dict(row)
        item["spec"] = json.loads(item["spec"])
        policies.append(item)
    assignments = []
    for row in db.execute(
        "SELECT * FROM model_assignments WHERE project_id=? ORDER BY created_ns,id",
        (project_id,),
    ):
        item = dict(row)
        item["requested"] = json.loads(item["requested"])
        item["missing"] = json.loads(item["missing"])
        assignments.append(item)
    permits = []
    for row in db.execute(
        "SELECT * FROM model_permits WHERE project_id=? ORDER BY created_ns,id",
        (project_id,),
    ):
        item = dict(row)
        item["usage"] = json.loads(item["usage"]) if item["usage"] else None
        permits.append(item)
    reports = [report_for_policy(db, policy) for policy in policies]
    return {
        "model_policies": policies,
        "model_assignments": assignments,
        "model_permits": permits,
        "model_reports": reports,
    }


def report_for_policy(db, policy):
    spec = (
        policy["spec"]
        if isinstance(policy["spec"], dict)
        else json.loads(policy["spec"])
    )
    limits = spec["limits"]
    charges = _charges(db, policy["milestone_id"])
    known = estimated = pending = unknown = interventions = 0
    permit_rows = [
        dict(row)
        for row in db.execute(
            "SELECT * FROM model_permits WHERE policy_id=? ORDER BY created_ns,id",
            (policy["id"],),
        )
    ]
    for row in permit_rows:
        usage = json.loads(row["usage"]) if row["usage"] else None
        if row["state"] in {"held", "conflicting"}:
            interventions += 1
            unknown += row["reserved_units"]
        elif row["state"] == "reconciled":
            known += row["settled_units"]
        elif row["state"] == "possible_send":
            pending += row["reserved_units"]
        elif row["state"] == "reserved" and usage:
            if usage["quality"] == "estimated":
                estimated += usage["units"]
            elif usage["quality"] == "unknown":
                unknown += row["reserved_units"]
            else:
                pending += row["reserved_units"]
    assignment_rows = []
    for row in db.execute(
        "SELECT * FROM model_assignments WHERE policy_id=? ORDER BY created_ns,id",
        (policy["id"],),
    ):
        usages = [
            json.loads(item["usage"])
            for item in db.execute(
                "SELECT usage FROM model_permits WHERE assignment_id=? AND usage IS NOT NULL",
                (row["id"],),
            )
            if item["usage"]
        ]
        assignment_rows.append(
            {
                "id": row["id"],
                "attempt_id": row["attempt_id"],
                "role": row["role"],
                "route_id": row["route_id"],
                "decision": row["decision"],
                "requested": json.loads(row["requested"]),
                "missing_observed": _missing_from(usages),
            }
        )
    protected = limits["protected_review_units"]
    return {
        "format": "model-cost-report-v1",
        "classification": "scripted_development",
        "live_eligible": False,
        "task_accepted": False,
        "milestone_id": policy["milestone_id"],
        "policy_id": policy["id"],
        "policy_digest": policy["digest"],
        "known_units": known,
        "estimated_units": estimated,
        "pending_units": pending,
        "unknown_units": unknown,
        "reserved_units": charges["total"],
        "implementation_units": charges["implementation"],
        "review_units": charges["review"],
        "protected_review_units": protected,
        "protected_review_remaining": max(0, protected - charges["review"]),
        "implementation_ceiling": limits["max_reserved_units"] - protected,
        "submissions": charges["submissions"],
        "max_submissions": limits["max_submissions"],
        "interventions": interventions,
        "assignments": assignment_rows,
    }


class ModelPolicy:
    def __init__(self, coordinator):
        self.core = coordinator

    @property
    def db(self):
        return self.core.db

    def approve_policy(
        self,
        project_id,
        milestone_key,
        spec,
        *,
        expected_project_version,
        expected_milestone_version,
        command_id=None,
    ):
        spec = _policy_spec(spec)
        checksum = digest(spec)

        def apply():
            project = self.core._project(project_id)
            milestone = self.core._milestone(project_id, milestone_key)
            self.core._version(project, expected_project_version)
            self.core._version(milestone, expected_milestone_version)
            require(not project["paused"], "project is paused", Conflict)
            require(
                milestone["approved_plan_id"] is not None,
                "milestone has no approved plan",
                Conflict,
            )
            require(
                self.db.execute(
                    "SELECT 1 FROM model_policies WHERE milestone_id=?",
                    (milestone["id"],),
                ).fetchone()
                is None,
                "model policy already recorded",
                Conflict,
            )
            policy_id = uuid4().hex
            self.db.execute(
                "INSERT INTO model_policies VALUES(?,?,?,?,?,?,?)",
                (
                    policy_id,
                    milestone["id"],
                    project_id,
                    checksum,
                    canonical(spec),
                    self.core.principal.id,
                    time.time_ns(),
                ),
            )
            return {
                "policy_id": policy_id,
                "digest": checksum,
                "milestone_id": milestone["id"],
                "live_eligible": False,
                "task_accepted": False,
                "classification": "scripted_development",
            }

        return self.core._write(
            "model.approve_policy",
            {
                "project_id": project_id,
                "milestone_key": milestone_key,
                "spec": spec,
                "expected_project_version": expected_project_version,
                "expected_milestone_version": expected_milestone_version,
            },
            apply,
            command_id,
            developer=True,
        )

    def assign(
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
        require(role in ROLES, "invalid model role")
        route_id = ident(route_id, "route id")
        requested = _requested(requested)

        def apply():
            attempt = self.core._attempt(attempt_id)
            self.core._version(attempt, expected_attempt_version)
            milestone = self.core._one(
                "SELECT * FROM milestones WHERE id=?",
                (attempt["milestone_id"],),
                "milestone",
            )
            project = self.core._project(milestone["project_id"])
            self.core._version(project, expected_project_version)
            require(not project["paused"], "project is paused", Conflict)
            require(
                attempt["state"] in {"reserved", "executing", "awaiting_verification"}
                and attempt["settled"] == 0,
                "attempt is not eligible for assignment",
                Conflict,
            )
            policy = self.db.execute(
                "SELECT * FROM model_policies WHERE milestone_id=?",
                (milestone["id"],),
            ).fetchone()
            require(policy is not None, "milestone has no model policy", Conflict)
            route = next(
                (
                    item
                    for item in json.loads(policy["spec"])["routes"]
                    if item["id"] == route_id
                ),
                None,
            )
            require(route is not None, "route is not in the approved policy", Conflict)
            require(route["available"], "route unavailable", Conflict)
            require(
                self.db.execute(
                    "SELECT 1 FROM model_assignments WHERE attempt_id=? AND role=?",
                    (attempt_id, role),
                ).fetchone()
                is None,
                "model assignment already recorded",
                Conflict,
            )
            missing = list(MISSING_OBSERVED)
            assignment_id = uuid4().hex
            self.db.execute(
                "INSERT INTO model_assignments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    assignment_id,
                    attempt_id,
                    milestone["id"],
                    project["id"],
                    policy["id"],
                    role,
                    route_id,
                    canonical(requested),
                    digest(requested),
                    "eligible",
                    canonical(missing),
                    self.core.principal.id,
                    time.time_ns(),
                ),
            )
            return {
                "assignment_id": assignment_id,
                "decision": "eligible",
                "role": role,
                "route_id": route_id,
                "requested_model": route["requested_model"],
                "requested": requested,
                "missing_observed": missing,
                "live_eligible": False,
                "task_accepted": False,
                "classification": "scripted_development",
            }

        return self.core._write(
            "model.assign",
            {
                "attempt_id": attempt_id,
                "role": role,
                "route_id": route_id,
                "requested": requested,
                "expected_attempt_version": expected_attempt_version,
                "expected_project_version": expected_project_version,
            },
            apply,
            command_id,
            developer=True,
        )

    def begin_permit(
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
        route_id = ident(route_id, "route id")
        submission_id = ident(submission_id, "submission id")
        reserved_units = integer(reserved_units, "reserved units")
        request_digest = _sha256(request_digest, "request digest")

        def apply():
            assignment = self.core._one(
                "SELECT * FROM model_assignments WHERE id=?",
                (assignment_id,),
                "model assignment",
            )
            project = self.core._project(assignment["project_id"])
            self.core._version(project, expected_project_version)
            require(not project["paused"], "project is paused", Conflict)
            require(
                assignment["decision"] == "eligible",
                "assignment is not eligible",
                Conflict,
            )
            require(
                route_id == assignment["route_id"], "fallback route denied", Conflict
            )
            attempt = self.core._attempt(assignment["attempt_id"])
            require(
                attempt["state"] in {"reserved", "executing", "awaiting_verification"}
                and attempt["settled"] == 0
                and attempt["milestone_id"] == assignment["milestone_id"],
                "attempt is not eligible for a permit",
                Conflict,
            )
            policy = self.core._one(
                "SELECT * FROM model_policies WHERE id=?",
                (assignment["policy_id"],),
                "model policy",
            )
            route = next(
                item
                for item in json.loads(policy["spec"])["routes"]
                if item["id"] == route_id
            )
            require(route["available"], "route unavailable", Conflict)
            require(
                self.db.execute(
                    "SELECT 1 FROM model_permits WHERE submission_id=?",
                    (submission_id,),
                ).fetchone()
                is None,
                "submission replay denied",
                Conflict,
            )
            limits = json.loads(policy["spec"])["limits"]
            charges = _charges(self.db, assignment["milestone_id"])
            added_implementation = (
                reserved_units if assignment["role"] != "review" else 0
            )
            require(
                charges["submissions"] + 1 <= limits["max_submissions"]
                and charges["total"] + reserved_units <= limits["max_reserved_units"]
                and charges["implementation"] + added_implementation
                <= limits["max_reserved_units"] - limits["protected_review_units"],
                "cumulative limit exhausted",
                Conflict,
            )
            permit_id = uuid4().hex
            allowance = "review" if assignment["role"] == "review" else "general"
            now = time.time_ns()
            self.db.execute(
                "INSERT INTO model_permits VALUES(?,?,?,?,?,?,?,?,?,?,?,NULL,?,1,'possible_send',NULL,NULL,?,?)",
                (
                    permit_id,
                    assignment_id,
                    assignment["attempt_id"],
                    assignment["project_id"],
                    assignment["milestone_id"],
                    assignment["policy_id"],
                    assignment["role"],
                    route_id,
                    submission_id,
                    request_digest,
                    reserved_units,
                    allowance,
                    now,
                    now,
                ),
            )
            return {
                "permit_id": permit_id,
                "submission_id": submission_id,
                "state": "possible_send",
                "reserved_units": reserved_units,
                "route_id": route_id,
                "allowance": allowance,
                "version": 1,
                "duplicate": False,
                "live_eligible": False,
                "task_accepted": False,
                "classification": "scripted_development",
            }

        return self.core._write(
            "model.begin_permit",
            {
                "assignment_id": assignment_id,
                "route_id": route_id,
                "submission_id": submission_id,
                "reserved_units": reserved_units,
                "request_digest": request_digest,
                "expected_project_version": expected_project_version,
            },
            apply,
            command_id,
            developer=True,
        )

    def lose_response(self, permit_id, *, expected_version, command_id=None):
        usage = _unknown_usage()
        checksum = digest(usage)

        def apply():
            row = self._permit(permit_id)
            self.core._version(row, expected_version)
            if row["usage_digest"] == checksum and row["state"] == "reserved":
                return self._usage_result(row, usage, duplicate=True)
            require(
                row["state"] in {"possible_send", "held"} and row["usage"] is None,
                "response loss does not match this permit",
                Conflict,
            )
            self.db.execute(
                "UPDATE model_permits SET state='reserved',version=version+1,usage=?,usage_digest=? WHERE id=?",
                (canonical(usage), checksum, permit_id),
            )
            current = self._permit(permit_id)
            return self._usage_result(current, usage, duplicate=False)

        return self.core._write(
            "model.lose_response",
            {"permit_id": permit_id, "expected_version": expected_version},
            apply,
            command_id,
            developer=True,
        )

    def observe_usage(self, permit_id, usage, *, expected_version, command_id=None):
        def apply():
            row = self._permit(permit_id)
            self.core._version(row, expected_version)
            envelope = _usage(usage, row["reserved_units"])
            checksum = digest(envelope)
            if row["usage_digest"] and row["usage_digest"] != checksum:
                self.core._fence(row["project_id"])
                self.db.execute(
                    "UPDATE model_permits SET state='conflicting',settled_units=NULL,version=version+1 WHERE id=?",
                    (permit_id,),
                )
                return {
                    "permit_id": permit_id,
                    "state": "conflicting",
                    "current": False,
                    "conflicting": True,
                    "duplicate": False,
                    "live_eligible": False,
                    "task_accepted": False,
                }
            if row["usage_digest"] == checksum:
                return self._usage_result(row, envelope, duplicate=True)
            require(
                row["state"] in {"possible_send", "held", "reserved"},
                "permit cannot accept usage",
                Conflict,
            )
            settled = envelope["units"] if envelope["quality"] == "known" else None
            state = "reconciled" if envelope["quality"] == "known" else "reserved"
            self.db.execute(
                "UPDATE model_permits SET state=?,settled_units=?,version=version+1,usage=?,usage_digest=? WHERE id=?",
                (state, settled, canonical(envelope), checksum, permit_id),
            )
            current = self._permit(permit_id)
            return self._usage_result(current, envelope, duplicate=False)

        return self.core._write(
            "model.observe_usage",
            {
                "permit_id": permit_id,
                "usage": usage,
                "expected_version": expected_version,
            },
            apply,
            command_id,
            developer=True,
        )

    def report(self, project_id, milestone_key):
        with self.core.store.transaction(write=False):
            milestone = self.core._milestone(project_id, milestone_key)
            policy = self.db.execute(
                "SELECT * FROM model_policies WHERE milestone_id=?",
                (milestone["id"],),
            ).fetchone()
            require(policy is not None, "milestone has no model policy", Conflict)
            return report_for_policy(self.db, policy)

    def _permit(self, permit_id):
        return self.core._one(
            "SELECT * FROM model_permits WHERE id=?", (permit_id,), "model permit"
        )

    @staticmethod
    def _usage_result(row, usage, *, duplicate):
        return {
            "permit_id": row["id"],
            "submission_id": row["submission_id"],
            "state": row["state"],
            "quality": usage["quality"],
            "reserved_units": row["reserved_units"],
            "settled_units": row["settled_units"],
            "version": row["version"],
            "duplicate": duplicate,
            "missing_observed": [
                name for name in MISSING_OBSERVED if not usage.get(name)
            ],
            "live_eligible": False,
            "task_accepted": False,
            "classification": "scripted_development",
        }
