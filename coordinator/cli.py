"""Local product CLI; it never launches native tasks or sends model traffic."""

import argparse
import getpass
import json
import sqlite3
from pathlib import Path

from .application import Coordinator
from .domain import Invalid, Principal
from .store import Store


def load(path):
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise Invalid(f"duplicate JSON field: {key}")
            result[key] = value
        return result

    with Path(path).open("rb") as stream:
        raw = stream.read(1_048_577)
    if len(raw) > 1_048_576:
        raise Invalid("input exceeds one MiB")
    return json.loads(raw, object_pairs_hook=object_pairs)


def parser():
    result = argparse.ArgumentParser(
        description="Durable project planning and development-only scripted attempts. Live execution is disabled."
    )
    result.add_argument(
        "--db", type=Path, default=Path(".local/orchestrator/state.sqlite")
    )
    result.add_argument(
        "--command-id",
        help="Reuse only for the same local command after a lost acknowledgement",
    )
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "init", help="Create a new product store; refuses an existing file"
    )
    command = commands.add_parser(
        "migrate",
        help="Offline migration to current schema; stop existing coordinators first",
    )
    command.add_argument("--backup", type=Path, required=True)
    for name in ("project-create", "project-revise"):
        command = commands.add_parser(name)
        command.add_argument("file", type=Path)
        if name == "project-revise":
            command.add_argument("project_id")
            command.add_argument("--expected-version", type=int, required=True)
    command = commands.add_parser(
        "discovery-record",
        help="Append one stored discovery turn and revise the project",
    )
    command.add_argument("project_id")
    command.add_argument("--expected-version", type=int, required=True)
    command.add_argument("--question", required=True)
    command.add_argument("--answer", required=True)
    command.add_argument("--requirements", type=Path)
    for name in ("status", "pause", "resume", "recover"):
        command = commands.add_parser(name)
        command.add_argument("project_id")
        if name != "status":
            command.add_argument("--expected-version", type=int, required=True)
        if name in {"pause", "recover"}:
            command.add_argument("--reason", required=True)
    command = commands.add_parser("plan-submit")
    command.add_argument("project_id")
    command.add_argument("milestone_key")
    command.add_argument("file", type=Path)
    command.add_argument("--expected-project-version", type=int, required=True)
    command = commands.add_parser("plan-approve")
    command.add_argument("plan_id")
    command.add_argument("--digest", required=True)
    command.add_argument("--expected-project-version", type=int, required=True)
    command.add_argument("--expected-milestone-version", type=int, required=True)
    command = commands.add_parser(
        "plan-import-gsd",
        help="Import one frozen GSD schema-1 phase as an unapproved plan",
    )
    command.add_argument("project_id")
    command.add_argument("milestone_key")
    command.add_argument("snapshot", type=Path)
    command.add_argument("--digest", required=True)
    command.add_argument("--plans", type=Path, required=True)
    command.add_argument("--expected-project-version", type=int, required=True)
    command.add_argument("--baseline", required=True)
    command.add_argument("--max-attempts", type=int, required=True)
    command.add_argument("--check-timeout", type=int, required=True)
    command = commands.add_parser("task-claim")
    command.add_argument("project_id")
    command.add_argument("milestone_key")
    command.add_argument("task_key")
    command.add_argument("--expected-project-version", type=int, required=True)
    command.add_argument("--expected-milestone-version", type=int, required=True)
    for name in ("scripted-start", "scripted-abandon"):
        command = commands.add_parser(name)
        command.add_argument("attempt_id")
        command.add_argument("--expected-version", type=int, required=True)
        if name == "scripted-abandon":
            command.add_argument("--reason", required=True)
    command = commands.add_parser("scripted-result")
    command.add_argument("operation_id")
    command.add_argument("--outcome", choices=("candidate", "failed"), required=True)
    command.add_argument("--detail", default="")
    commands.add_parser("events")
    command = commands.add_parser("backup")
    command.add_argument("output", type=Path)
    command = commands.add_parser(
        "restore",
        help="Bind a verified archive as a new primary at a new path",
    )
    command.add_argument("archive", type=Path)
    command.add_argument("destination", type=Path)
    command.add_argument("--digest", required=True)
    command = commands.add_parser(
        "cost-report", help="Read one milestone's scripted cost report"
    )
    command.add_argument("project_id")
    command.add_argument("milestone_key")
    command = commands.add_parser(
        "model-policy-approve", help="Approve one scripted model policy"
    )
    command.add_argument("project_id")
    command.add_argument("milestone_key")
    command.add_argument("file", type=Path)
    command.add_argument("--expected-project-version", type=int, required=True)
    command.add_argument("--expected-milestone-version", type=int, required=True)
    command = commands.add_parser(
        "model-assign", help="Assign one scripted route to an attempt role"
    )
    command.add_argument("attempt_id")
    command.add_argument("role")
    command.add_argument("route_id")
    command.add_argument("file", type=Path)
    command.add_argument("--expected-attempt-version", type=int, required=True)
    command.add_argument("--expected-project-version", type=int, required=True)
    command = commands.add_parser(
        "model-permit", help="Reserve one scripted submission"
    )
    command.add_argument("assignment_id")
    command.add_argument("route_id")
    command.add_argument("submission_id")
    command.add_argument("reserved_units", type=int)
    command.add_argument("request_digest")
    command.add_argument("--expected-project-version", type=int, required=True)
    command = commands.add_parser(
        "model-lose-response", help="Record an unknown scripted response"
    )
    command.add_argument("permit_id")
    command.add_argument("--expected-version", type=int, required=True)
    command = commands.add_parser(
        "model-observe-usage", help="Record scripted usage quality"
    )
    command.add_argument("permit_id")
    command.add_argument("file", type=Path)
    command.add_argument("--expected-version", type=int, required=True)

    def promotion(name, help_text):
        item = commands.add_parser(name, help=help_text)
        item.add_argument("--repository", type=Path, required=True)
        item.add_argument("--artifacts", type=Path, required=True)
        return item

    command = promotion(
        "promotion-authorize-head",
        "Authorize one diverged expected head; this does not promote",
    )
    command.add_argument("attempt_id")
    command.add_argument("previous_head")
    command.add_argument("new_head")
    command.add_argument("authority_generation", type=int)
    command = promotion(
        "promotion-approve-regressions",
        "Approve one exact scripted regression policy",
    )
    command.add_argument("proposal_id")
    command.add_argument("file", type=Path)
    command.add_argument("--digest", required=True)
    command.add_argument("--expected-version", type=int, required=True)
    command = promotion(
        "promotion-approve-evidence",
        "Approve fresh checks and review for one distinct integrated commit",
    )
    command.add_argument("proposal_id")
    command.add_argument("file", type=Path)
    command.add_argument("--digest", required=True)
    command.add_argument("--expected-version", type=int, required=True)
    command = promotion(
        "promotion-begin",
        "Commit possible-send for one scripted promotion",
    )
    command.add_argument("proposal_id")
    command.add_argument("--expected-version", type=int, required=True)
    command = promotion(
        "promotion-promote",
        "Promote one scripted integration; lost acknowledgement uses promotion-reconcile",
    )
    command.add_argument("proposal_id")
    command.add_argument("--expected-version", type=int, required=True)
    command = promotion(
        "promotion-reconcile",
        "Read an existing milestone ref and record the scripted promotion once",
    )
    command.add_argument("proposal_id")
    return result


def execute(args):
    if args.command == "restore":
        Principal("local:" + getpass.getuser()).developer()
        return Store.restore(args.archive, args.destination, args.digest)
    if args.command == "migrate":
        return Store.migrate(args.db, args.backup)
    if args.command == "init":
        with Store.create(args.db) as store:
            return {"database": str(store.path), "created": True}
    with Store(args.db) as store:
        app = Coordinator(store, Principal("local:" + getpass.getuser()))
        command = args.command
        common = {"command_id": args.command_id}
        if command == "project-create":
            return app.create_project(load(args.file), **common)
        if command == "project-revise":
            return app.revise_project(
                args.project_id,
                load(args.file),
                expected_version=args.expected_version,
                **common,
            )
        if command == "discovery-record":
            requirements = (
                None if args.requirements is None else load(args.requirements)
            )
            return app.record_discovery(
                args.project_id,
                expected_version=args.expected_version,
                question=args.question,
                answer=args.answer,
                requirements=requirements,
                **common,
            )
        if command == "plan-submit":
            return app.submit_plan(
                args.project_id,
                args.milestone_key,
                load(args.file),
                expected_project_version=args.expected_project_version,
                **common,
            )
        if command == "plan-import-gsd":
            return app.import_gsd(
                args.project_id,
                args.milestone_key,
                args.snapshot,
                args.digest,
                args.plans,
                expected_project_version=args.expected_project_version,
                baseline_revision=args.baseline,
                max_attempts=args.max_attempts,
                check_timeout_seconds=args.check_timeout,
                **common,
            )
        if command == "plan-approve":
            return app.approve_plan(
                args.plan_id,
                args.digest,
                expected_project_version=args.expected_project_version,
                expected_milestone_version=args.expected_milestone_version,
                **common,
            )
        if command == "task-claim":
            return app.claim_task(
                args.project_id,
                args.milestone_key,
                args.task_key,
                expected_project_version=args.expected_project_version,
                expected_milestone_version=args.expected_milestone_version,
                **common,
            )
        if command in {"pause", "recover"}:
            return getattr(app, command)(
                args.project_id,
                expected_version=args.expected_version,
                reason=args.reason,
                **common,
            )
        if command == "resume":
            return app.resume(
                args.project_id, expected_version=args.expected_version, **common
            )
        if command == "scripted-start":
            return app.start_scripted(
                args.attempt_id, expected_version=args.expected_version, **common
            )
        if command == "scripted-result":
            return app.record_scripted_result(
                args.operation_id, args.outcome, detail=args.detail, **common
            )
        if command == "scripted-abandon":
            return app.abandon_scripted(
                args.attempt_id,
                expected_version=args.expected_version,
                reason=args.reason,
                **common,
            )
        if command == "status":
            return app.status(args.project_id)
        if command == "events":
            return app.events()
        if command == "backup":
            app.principal.developer()
            return store.backup(args.output)
        if command == "cost-report":
            return app.cost_report(args.project_id, args.milestone_key)
        if command == "model-policy-approve":
            return app.approve_model_policy(
                args.project_id,
                args.milestone_key,
                load(args.file),
                expected_project_version=args.expected_project_version,
                expected_milestone_version=args.expected_milestone_version,
                **common,
            )
        if command == "model-assign":
            return app.assign_model(
                args.attempt_id,
                args.role,
                args.route_id,
                load(args.file),
                expected_attempt_version=args.expected_attempt_version,
                expected_project_version=args.expected_project_version,
                **common,
            )
        if command == "model-permit":
            return app.begin_model_permit(
                args.assignment_id,
                args.route_id,
                args.submission_id,
                args.reserved_units,
                args.request_digest,
                expected_project_version=args.expected_project_version,
                **common,
            )
        if command == "model-lose-response":
            return app.lose_model_response(
                args.permit_id, expected_version=args.expected_version, **common
            )
        if command == "model-observe-usage":
            return app.observe_model_usage(
                args.permit_id,
                load(args.file),
                expected_version=args.expected_version,
                **common,
            )
        if command == "promotion-authorize-head":
            return app.authorize_diverged_head(
                args.attempt_id,
                args.previous_head,
                args.new_head,
                args.authority_generation,
                repository=args.repository,
                artifacts=args.artifacts,
                **common,
            )
        if command == "promotion-approve-regressions":
            return app.approve_regressions(
                args.proposal_id,
                load(args.file),
                args.digest,
                expected_version=args.expected_version,
                repository=args.repository,
                artifacts=args.artifacts,
                **common,
            )
        if command == "promotion-approve-evidence":
            return app.approve_evidence(
                args.proposal_id,
                load(args.file),
                args.digest,
                expected_version=args.expected_version,
                repository=args.repository,
                artifacts=args.artifacts,
                **common,
            )
        if command == "promotion-begin":
            return app.begin_promotion(
                args.proposal_id,
                expected_version=args.expected_version,
                repository=args.repository,
                artifacts=args.artifacts,
                **common,
            )
        if command == "promotion-promote":
            return app.promote(
                args.proposal_id,
                expected_version=args.expected_version,
                repository=args.repository,
                artifacts=args.artifacts,
            )
        if command == "promotion-reconcile":
            return app.reconcile_promotion(
                args.proposal_id,
                repository=args.repository,
                artifacts=args.artifacts,
            )
    raise Invalid("unknown command")


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        result = execute(args)
    except (
        Invalid,
        OSError,
        sqlite3.Error,
        json.JSONDecodeError,
        UnicodeError,
    ) as error:
        print(
            json.dumps(
                {"ok": False, "error": type(error).__name__, "message": str(error)}
            )
        )
        return 2
    print(
        json.dumps({"ok": True, "result": result}, ensure_ascii=False, sort_keys=True)
    )
    return 0
