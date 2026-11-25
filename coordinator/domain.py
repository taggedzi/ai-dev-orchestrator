"""Validated, provider-neutral intent; no execution or research-harness imports."""

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath


class Invalid(ValueError):
    """Malformed input or an unavailable capability."""


class Conflict(Invalid):
    """Intent is stale or the current state prevents this operation."""


class NotFound(Invalid):
    """The requested entity does not exist."""


def require(condition, message, error=Invalid):
    if not condition:
        raise error(message)


def canonical(value):
    try:
        raw = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        require(len(raw.encode("utf-8")) <= 1_048_576, "record exceeds one MiB")
        return raw
    except (TypeError, ValueError) as error:
        if isinstance(error, Invalid):
            raise
        raise Invalid("record must contain finite JSON values") from error


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def text(value, label, maximum=8192):
    require(
        type(value) is str and 0 < len(value) <= maximum and "\0" not in value,
        f"invalid {label}",
    )
    return value


def ident(value, label="identifier"):
    require(
        type(value) is str and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", value),
        f"invalid {label}",
    )
    return value


def integer(value, label, minimum=1, maximum=2**63 - 1):
    require(type(value) is int and minimum <= value <= maximum, f"invalid {label}")
    return value


def fields(value, names, label):
    require(
        type(value) is dict and set(value) == set(names),
        f"{label} fields must be {', '.join(names)}",
    )


def unique(items, label):
    require(len(items) == len(set(items)), f"duplicate {label}")


@dataclass(frozen=True)
class Principal:
    """Trusted caller identity supplied by the local CLI or a future auth boundary."""

    id: str
    role: str = "developer"

    def __post_init__(self):
        text(self.id, "actor", 200)
        require(self.role in {"developer", "service"}, "invalid actor role")

    def developer(self):
        require(self.role == "developer", "developer authority required")


def project_spec(value):
    fields(value, ("name", "repository", "requirements", "context"), "project")
    text(value["name"], "project name", 200)
    text(value["repository"], "repository", 4096)
    require(type(value["context"]) is dict, "context must be an object")
    canonical(value["context"])
    requirements = value["requirements"]
    require(
        type(requirements) is list and 1 <= len(requirements) <= 1000,
        "requirements must be a nonempty list",
    )
    for row in requirements:
        fields(row, ("id", "text"), "requirement")
        ident(row["id"], "requirement id")
        text(row["text"], "requirement text")
    unique([r["id"] for r in requirements], "requirement id")
    return json.loads(canonical(value))


def plan_spec(value, requirement_ids):
    fields(
        value, ("title", "baseline_revision", "requirements_revision", "tasks"), "plan"
    )
    text(value["title"], "plan title", 200)
    require(
        type(value["baseline_revision"]) is str
        and re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", value["baseline_revision"]),
        "baseline must be a full lowercase Git object id",
    )
    integer(value["requirements_revision"], "requirements revision")
    tasks = value["tasks"]
    require(
        type(tasks) is list and 1 <= len(tasks) <= 1000, "tasks must be a nonempty list"
    )
    keys = []
    for task in tasks:
        fields(
            task,
            (
                "id",
                "title",
                "instructions",
                "depends_on",
                "allowed_paths",
                "criteria",
                "checks",
                "max_attempts",
            ),
            "task",
        )
        keys.append(ident(task["id"], "task id"))
        text(task["title"], "task title", 200)
        text(task["instructions"], "task instructions", 65536)
        integer(task["max_attempts"], "absolute task attempt limit", maximum=100)
        require(type(task["depends_on"]) is list, "dependencies must be a list")
        for dependency in task["depends_on"]:
            ident(dependency, "dependency")
        unique(task["depends_on"], "dependency")
        paths = task["allowed_paths"]
        require(type(paths) is list and paths, "allowed paths must be nonempty")
        for path in paths:
            text(path, "allowed path", 4096)
            parts = path.split("/")
            require(
                not PurePosixPath(path).is_absolute()
                and not any(
                    p in {"", ".", ".."} or p.casefold() == ".git" for p in parts
                )
                and not any(c in path for c in "\\:*?[]"),
                "allowed paths must be literal relative paths outside .git",
            )
        unique(paths, "allowed path")
        checks = task["checks"]
        require(type(checks) is list and checks, "checks must be nonempty")
        check_ids = []
        for check in checks:
            fields(check, ("id", "argv", "timeout_seconds"), "check")
            check_ids.append(ident(check["id"], "check id"))
            require(
                type(check["argv"]) is list and 1 <= len(check["argv"]) <= 100,
                "check argv must be nonempty",
            )
            for arg in check["argv"]:
                text(arg, "check argument", 8192)
            integer(check["timeout_seconds"], "check timeout", maximum=3600)
        unique(check_ids, "check id")
        criteria = task["criteria"]
        require(type(criteria) is list and criteria, "criteria must be nonempty")
        criterion_ids = []
        for criterion in criteria:
            fields(
                criterion,
                ("id", "description", "requirement_id", "checks"),
                "criterion",
            )
            criterion_ids.append(ident(criterion["id"], "criterion id"))
            text(criterion["description"], "criterion description")
            ident(criterion["requirement_id"], "criterion requirement id")
            require(
                criterion["requirement_id"] in requirement_ids,
                "criterion refers to an unknown requirement",
            )
            require(
                type(criterion["checks"]) is list and criterion["checks"],
                "criterion must name observable checks",
            )
            require(
                all(type(c) is str and c in check_ids for c in criterion["checks"]),
                "criterion refers to an unknown check",
            )
            unique(criterion["checks"], "criterion check")
        unique(criterion_ids, "criterion id")
    unique(keys, "task id")
    remaining = {task["id"]: set(task["depends_on"]) for task in tasks}
    require(
        all(deps <= set(keys) for deps in remaining.values()), "unresolved dependency"
    )
    while remaining:
        ready = {key for key, deps in remaining.items() if not deps}
        require(ready, "task graph contains a cycle")
        remaining = {
            key: deps - ready for key, deps in remaining.items() if key not in ready
        }
    return json.loads(canonical(value))
