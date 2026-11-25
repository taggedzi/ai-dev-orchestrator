"""Read-only GSD Core schema-1 import. Native status is not acceptance."""

import hashlib
import json
import re
from pathlib import Path

from .domain import Invalid, ident, require, text, unique

SNAPSHOT_LIMIT = 2 * 1024 * 1024
PLAN_LIMIT = 128 * 1024
_TASK_TAGS = ("name", "files", "action", "verify", "acceptance_criteria", "done")
_TASK_PATTERN = re.compile(
    r'<tasks>\s*<task type="auto">\s*'
    + r"\s*".join(
        "<" + tag + ">(?P<" + tag + ">.*?)</" + tag + ">" for tag in _TASK_TAGS
    )
    + r"\s*</task>\s*</tasks>",
    re.DOTALL,
)


def _digest(value):
    require(
        type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
        "snapshot digest must be lowercase sha256",
    )
    return value


def _pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "duplicate JSON field")
        result[key] = value
    return result


def _nonfinite(_value):
    raise Invalid("malformed planning snapshot or raw PLAN")


def _json(value):
    try:
        parsed = json.loads(value, object_pairs_hook=_pairs, parse_constant=_nonfinite)
    except Invalid:
        raise
    except (json.JSONDecodeError, UnicodeError, ValueError) as error:
        raise Invalid("malformed planning snapshot or raw PLAN") from error
    return parsed


def _read_file(path, limit, label):
    path = Path(path)
    require(path.is_file(), f"{label} is missing")
    require(
        not path.is_symlink() and not path.is_junction(),
        f"{label} must be a regular file",
    )
    require(path.stat().st_size <= limit, f"{label} exceeds the import bound")
    data = path.read_bytes()
    require(len(data) <= limit, f"{label} exceeds the import bound")
    return data


def _plain_name(value):
    require(
        type(value) is str
        and value not in {"", ".", ".."}
        and "/" not in value
        and "\\" not in value
        and "\0" not in value,
        "plan file name is unsafe",
    )
    return value


def _string_list(value, label):
    require(
        type(value) is list and all(type(item) is str for item in value),
        f"invalid {label}",
    )
    return value


def _field(frontmatter, name):
    rows = re.findall(
        r"^" + re.escape(name) + r":[ \t]*(.*?)[ \t]*$",
        frontmatter,
        re.MULTILINE,
    )
    require(len(rows) == 1, "PLAN frontmatter field is missing or repeated")
    return rows[0]


def _criteria(value):
    return [
        line.strip().removeprefix("- ") for line in value.splitlines() if line.strip()
    ]


def _argv(verify):
    require(
        verify.count("<automated>") == 1 and verify.count("</automated>") == 1,
        "automated verification is missing or repeated",
    )
    found = re.fullmatch(r"\s*<automated>(.*?)</automated>\s*", verify, re.DOTALL)
    require(found is not None, "automated verification is missing or repeated")
    command = found.group(1).strip()
    require(
        command
        and '"' not in command
        and "'" not in command
        and "\t" not in command
        and "\r" not in command
        and "\n" not in command,
        "verification command is not a plain argv",
    )
    argv = command.split(" ")
    require(all(argv), "verification command is not a plain argv")
    for arg in argv:
        text(arg, "check argument", 8192)
    return argv


def _order(tasks):
    pending = [task["id"] for task in tasks]
    dependencies = {task["id"]: list(task["depends_on"]) for task in tasks}
    ordered = []
    while pending:
        ready = [key for key in pending if not dependencies[key]]
        require(ready, "task graph contains a cycle")
        for key in ready:
            pending.remove(key)
            ordered.append(key)
            for values in dependencies.values():
                if key in values:
                    values.remove(key)
    by_id = {task["id"]: task for task in tasks}
    return [by_id[key] for key in ordered]


def _read_plans(directory, names):
    directory = Path(directory)
    require(
        directory.is_dir()
        and not directory.is_symlink()
        and not directory.is_junction(),
        "plans directory is missing",
    )
    root = directory.resolve()
    found = {}
    for entry in directory.iterdir():
        require(
            entry.is_file() and not entry.is_symlink() and not entry.is_junction(),
            "plan files do not match the snapshot",
        )
        require(entry.stat().st_size <= PLAN_LIMIT, "PLAN exceeds 128 KiB")
        data = entry.read_bytes()
        require(len(data) <= PLAN_LIMIT, "PLAN exceeds 128 KiB")
        candidate = entry.resolve()
        require(candidate.parent == root, "plan file name is unsafe")
        found[entry.name] = data
    require(set(found) == set(names), "plan files do not match the snapshot")
    return found


def _task(plan, raw, requirement_ids):
    require(
        plan.get("scope") == "complete" and plan.get("superseded") is False,
        "plan is superseded or not complete",
    )
    native_tasks = plan.get("tasks")
    require(
        type(native_tasks) is list and len(native_tasks) == 1,
        "PLAN auto task is missing or repeated",
    )
    native = native_tasks[0]
    require(
        type(native) is dict
        and native.get("kind") == "auto"
        and native.get("type") == "auto",
        "PLAN auto task is missing or repeated",
    )
    plan_id = plan.get("id")
    require(type(plan_id) is str and plan_id, "invalid plan id")
    _plain_name(plan.get("file"))
    depends_on = _string_list(plan.get("dependsOn"), "plan dependencies")
    unique(depends_on, "dependency")
    planned = _string_list(plan.get("plannedFiles"), "planned files")
    require(planned, "planned files disagree")
    require(native.get("plannedFiles") == planned, "planned files disagree")
    require(type(plan.get("objective")) is str, "plan objective disagrees")
    objective = text(plan["objective"].strip(), "task title", 200)
    require(type(native.get("name")) is str, "task name disagrees")
    task_name = ident(native["name"].strip(), "task id")
    criteria = _string_list(native.get("acceptanceCriteria"), "acceptance criteria")
    require(criteria, "acceptance criteria disagree")
    try:
        body_text = raw.decode("utf-8")
    except UnicodeError as error:
        raise Invalid("malformed planning snapshot or raw PLAN") from error
    require("<!" not in body_text, "malformed raw PLAN")
    parts = body_text.split("---", 2)
    require(len(parts) == 3 and not parts[0].strip(), "malformed raw PLAN")
    frontmatter, body = parts[1], parts[2]
    raw_dependencies = _json(_field(frontmatter, "depends_on"))
    require(raw_dependencies == depends_on, "plan dependency edges disagree")
    raw_files = _json(_field(frontmatter, "files_modified"))
    require(raw_files == planned, "planned files disagree")
    raw_requirements = _json(_field(frontmatter, "requirements"))
    require(
        type(raw_requirements) is list and len(raw_requirements) == 1,
        "PLAN requirement id is missing or repeated",
    )
    requirement_id = ident(raw_requirements[0], "requirement id")
    require(
        requirement_id in requirement_ids,
        "plan requirement is not in the snapshot",
    )
    objectives = re.findall(r"<objective>(.*?)</objective>", body, re.DOTALL)
    require(
        len(objectives) == 1 and objectives[0].strip() == objective,
        "plan objective disagrees",
    )
    fragments = re.findall(r"<tasks>.*?</tasks>", body, re.DOTALL)
    require(len(fragments) == 1, "PLAN auto task is missing or repeated")
    match = _TASK_PATTERN.fullmatch(fragments[0])
    require(match is not None, "PLAN auto task is missing or repeated")
    require(match.group("name").strip() == task_name, "task name disagrees")
    parsed_files = [part.strip() for part in match.group("files").split(",")]
    require(parsed_files == planned, "planned files disagree")
    parsed_criteria = _criteria(match.group("acceptance_criteria"))
    require(parsed_criteria == criteria, "acceptance criteria disagree")
    return {
        "plan_id": plan_id,
        "id": task_name,
        "title": objective,
        "instructions": text(match.group("action").strip(), "task instructions", 65536),
        "depends_on_plans": depends_on,
        "allowed_paths": planned,
        "requirement_id": requirement_id,
        "criteria": parsed_criteria,
        "argv": _argv(match.group("verify")),
    }


def _parse(snapshot, digest, plans):
    data = _read_file(snapshot, SNAPSHOT_LIMIT, "snapshot")
    require(
        hashlib.sha256(data).hexdigest() == digest,
        "snapshot digest does not match the file",
    )
    try:
        parsed = _json(data.decode("utf-8"))
    except UnicodeError as error:
        raise Invalid("malformed planning snapshot or raw PLAN") from error
    require(type(parsed) is dict, "malformed planning snapshot or raw PLAN")
    version = parsed.get("schema_version")
    require(
        type(version) is int and version == 1,
        "unsupported planning snapshot schema",
    )
    phases = parsed.get("phases")
    require(
        type(phases) is list and len(phases) == 1 and type(phases[0]) is dict,
        "snapshot must contain one phase",
    )
    phase = phases[0]
    goal = phase.get("goal")
    require(
        type(goal) is dict and goal.get("scope", "complete") == "complete",
        "phase goal is not complete",
    )
    title = text(goal.get("value"), "plan title", 200)
    rows = parsed.get("requirements")
    require(type(rows) is list, "malformed planning snapshot or raw PLAN")
    requirement_ids = []
    for row in rows:
        require(type(row) is dict, "malformed planning snapshot or raw PLAN")
        requirement_ids.append(ident(row.get("id"), "requirement id"))
    unique(requirement_ids, "requirement id")
    phase_plans = phase.get("plans")
    require(
        type(phase_plans) is list and phase_plans,
        "snapshot phase has no plans",
    )
    names = []
    for plan in phase_plans:
        require(type(plan) is dict, "malformed planning snapshot or raw PLAN")
        names.append(_plain_name(plan.get("file")))
    require(len(names) == len(set(names)), "plan files do not match the snapshot")
    blobs = _read_plans(plans, names)
    records = [
        _task(plan, blobs[plan["file"]], requirement_ids) for plan in phase_plans
    ]
    require(
        len({record["plan_id"] for record in records}) == len(records),
        "duplicate plan id",
    )
    require(
        len({record["id"] for record in records}) == len(records),
        "duplicate task id",
    )
    by_plan = {record["plan_id"]: record["id"] for record in records}
    tasks = []
    for record in records:
        dependencies = []
        for target in record["depends_on_plans"]:
            require(target in by_plan, "missing dependency target")
            dependencies.append(by_plan[target])
        unique(dependencies, "dependency")
        tasks.append(
            {
                "id": record["id"],
                "title": record["title"],
                "instructions": record["instructions"],
                "depends_on": dependencies,
                "allowed_paths": record["allowed_paths"],
                "criteria": [
                    {
                        "id": criterion,
                        "description": criterion,
                        "requirement_id": record["requirement_id"],
                    }
                    for criterion in record["criteria"]
                ],
                "argv": record["argv"],
            }
        )
    return {
        "title": title,
        "tasks": _order(tasks),
        "snapshot_requirement_ids": requirement_ids,
    }


def parse_gsd_import(snapshot, digest, plans):
    """Return one phase translated into product task records. Does not write."""
    _digest(digest)
    try:
        return _parse(snapshot, digest, plans)
    except Invalid:
        raise
    except (OSError, KeyError, TypeError, ValueError, UnicodeError) as error:
        raise Invalid("malformed planning snapshot or raw PLAN") from error
