"""M-CLI1 import fidelity and readiness oracles for the research fixture."""

import argparse
import re
import sys
from pathlib import Path

from .bundle import digest, load_json, safe_path, write
from .fixture import PROMPTS, TASKS, canonical
from .store import Hold


def field(frontmatter, name):
    rows = re.findall(
        r"^" + re.escape(name) + r":\s*(.*?)\s*$", frontmatter, re.MULTILINE
    )
    if len(rows) != 1:
        raise Hold("missing or ambiguous fixture frontmatter: " + name)
    return rows[0]


def check_graph(dependencies):
    if any(
        not isinstance(values, list) or len(set(values)) != len(values)
        for values in dependencies.values()
    ):
        raise Hold("invalid or duplicate plan dependencies")
    if any(
        target not in dependencies
        for values in dependencies.values()
        for target in values
    ):
        raise Hold("missing dependency target")
    remaining = dict(dependencies)
    finished = set()
    while remaining:
        ready = {key for key, values in remaining.items() if set(values) <= finished}
        if not ready:
            raise Hold("dependency cycle")
        finished.update(ready)
        remaining = {
            key: values for key, values in remaining.items() if key not in ready
        }


def _normalize(snapshot, raw):
    if (
        snapshot.get("schema_version") != 1
        or type(snapshot.get("schema_version")) is not int
    ):
        raise Hold("unsupported planning snapshot schema")
    if snapshot.get("milestone") != {
        "version": "v1.0",
        "name": "M-CLI1",
        "scope": "complete",
    }:
        raise Hold("fixture milestone identity or scope mismatch")
    phases = snapshot["phases"]
    if len(phases) != 1 or snapshot["orphan_phase_dirs"]:
        raise Hold("fixture requires exactly one declared phase")
    phase = phases[0]
    if (
        phase["phase_id"] != "01"
        or phase["dir"] != "01-validate-cli"
        or phase["scope"] != "complete"
    ):
        raise Hold("phase identity or scope mismatch")
    goal = phase["goal"]
    if (
        goal.get("scope") != "complete"
        or goal.get("value") != "Validate names and provide a CLI."
    ):
        raise Hold("phase goal missing or changed")
    if phase["dependencies"] != {"value": [], "scope": "complete"}:
        raise Hold("unexpected phase dependency")
    if any(
        row.get("code") not in {"uat_absent", "percent_withheld"}
        for row in snapshot["diagnostics"]
    ):
        raise Hold("unresolved planning diagnostics")
    requirements = {row["id"]: row for row in snapshot["requirements"]}
    if len(requirements) != len(snapshot["requirements"]) or set(requirements) != {
        "CLI-01",
        "CLI-02",
    }:
        raise Hold("fixture requirements missing or duplicated")
    for requirement in requirements.values():
        if (
            requirement["scope"] != "complete"
            or requirement["mappedPhases"] != ["1"]
            or requirement["diagnostics"]
        ):
            raise Hold("requirement mapping unknown or inconsistent")
    plans = {plan["id"]: plan for plan in phase["plans"]}
    if len(plans) != len(phase["plans"]) or set(plans) != {
        task["plan"] for task in TASKS
    }:
        raise Hold("fixture plans missing, unexpected, or duplicated")
    dependencies = {key: plan["dependsOn"] for key, plan in plans.items()}
    check_graph(dependencies)
    plan_to_task = {task["plan"]: task["id"] for task in TASKS}
    tasks = []
    sources = {}
    context_path = ".planning/phases/01-validate-cli/01-CONTEXT.md"
    if not raw.get(context_path):
        raise Hold("raw phase context missing")
    for expected in TASKS:
        plan = plans[expected["plan"]]
        if plan["scope"] != "complete" or plan["superseded"] or len(plan["tasks"]) != 1:
            raise Hold("ambiguous or superseded fixture plan")
        if plan["file"] != expected["plan"] + "-PLAN.md":
            raise Hold("plan filename mismatch")
        path = ".planning/phases/" + phase["dir"] + "/" + plan["file"]
        safe_path(path)
        data = raw[path]
        if len(data) > 128 * 1024:
            raise Hold("raw fixture PLAN exceeds import bound")
        sources[path] = digest(data)
        text = data.decode("utf-8")
        parts = text.split("---", 2)
        if len(parts) != 3 or parts[0].strip() or "<!" in text:
            raise Hold("malformed or unsupported raw PLAN")
        frontmatter, body = parts[1:]
        raw_dependencies = load_json(field(frontmatter, "depends_on"))
        if raw_dependencies != plan["dependsOn"]:
            raise Hold("export and raw dependency edges disagree")
        edge = [plan_to_task[target] for target in raw_dependencies]
        if edge != expected["depends_on"]:
            raise Hold("approved fixture dependency changed")
        if (
            load_json(field(frontmatter, "files_modified"))
            != expected["allowed_additions"]
        ):
            raise Hold("raw plan file scope changed")
        if load_json(field(frontmatter, "requirements")) != [
            "CLI-" + expected["id"].split("-")[1]
        ]:
            raise Hold("raw requirement binding changed")
        objectives = re.findall(r"<objective>(.*?)</objective>", body, re.DOTALL)
        if len(objectives) != 1 or objectives[0].strip() != plan["objective"]:
            raise Hold("plan objective missing or export/raw mismatch")
        fragments = re.findall(r"<tasks>.*?</tasks>", body, re.DOTALL)
        if len(fragments) != 1:
            raise Hold("raw tasks missing or ambiguous")
        # GSD's PLAN markup is XML-like, not XML: action prose can contain
        # literal placeholders such as Hello, <name>!. Preserve it verbatim.
        tags = ["name", "files", "action", "verify", "acceptance_criteria", "done"]
        pattern = (
            r'<tasks>\s*<task type="auto">\s*'
            + r"\s*".join(
                "<" + tag + ">(?P<" + tag + ">.*?)</" + tag + ">" for tag in tags
            )
            + r"\s*</task>\s*</tasks>"
        )
        match = re.fullmatch(pattern, fragments[0], re.DOTALL)
        if match is None:
            raise Hold("unsupported raw fixture task shape")
        task, native = match.groupdict(), plan["tasks"][0]
        if (
            native["name"] != expected["id"]
            or task["name"].strip() != native["name"]
            or native["index"] != 1
            or native["kind"] != "auto"
        ):
            raise Hold("task identity mismatch")
        planned = [value.strip() for value in task["files"].split(",")]
        if (
            planned != expected["allowed_additions"]
            or plan["plannedFiles"] != planned
            or native["plannedFiles"] != planned
        ):
            raise Hold("raw/export file scope mismatch")
        criteria = [
            line.strip().removeprefix("- ")
            for line in task["acceptance_criteria"].splitlines()
            if line.strip()
        ]
        if criteria != expected["criteria"] or native["acceptanceCriteria"] != criteria:
            raise Hold("acceptance criteria missing or changed")
        action = task["action"].strip()
        if action != PROMPTS[expected["id"]].split("\n", 1)[1].strip():
            raise Hold("raw fixture task action changed")
        verify = re.fullmatch(
            r"\s*<automated>(.*?)</automated>\s*", task["verify"], re.DOTALL
        )
        if verify is None:
            raise Hold("explicit automated verification required")
        verification = verify.group(1).strip()
        command = (
            "node --test test/"
            + ("validate" if expected["id"] == "T-01" else "cli")
            + ".test.js"
        )
        if verification != command:
            raise Hold("verification command changed")
        done = task["done"].strip()
        if not done or native["done"] != done:
            raise Hold("done condition missing or changed")
        tasks.append(
            {
                "id": expected["id"],
                "plan": expected["plan"],
                "depends_on": edge,
                "objective": plan["objective"],
                "planned_files": planned,
                "action": action,
                "verification": verification,
                "acceptance_criteria": criteria,
                "done": done,
                "source_plan_sha256": sources[path],
                "native_status_observation": native["status"],
            }
        )
    return {
        "format": "mcli1-gsd-import-probe-v1",
        "source_schema": 1,
        "milestone": "M-CLI1",
        "phase_goal": goal["value"],
        "tasks": tasks,
        "raw_plan_sha256": sources,
        "context_sha256": digest(raw[context_path]),
        "native_progress_observation": snapshot["progress"],
        "native_phase_verification_observation": phase["verification"],
        "classification": "fixture-only translation; native completion/status never supplies coordinator acceptance",
    }


def normalize(snapshot_bytes, raw):
    if len(snapshot_bytes) > 2 * 1024**2:
        raise Hold("snapshot capture exceeds fixture limit")
    try:
        result = _normalize(load_json(snapshot_bytes), raw)
    except Hold:
        raise
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise Hold("malformed planning export or raw PLAN") from error
    return result | {"snapshot_sha256": digest(snapshot_bytes)}


def eligible_tasks(normalized, accepted):
    """Synthetic readiness oracle; acceptance IDs must come from trusted evidence."""
    tasks = normalized["tasks"]
    accepted = set(accepted)
    if accepted - {task["id"] for task in tasks}:
        raise Hold("unknown accepted fixture task")
    return [
        task["id"]
        for task in tasks
        if task["id"] not in accepted and set(task["depends_on"]) <= accepted
    ]


def load_raw(project):
    project = Path(project)
    return {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in (project / ".planning").rglob("*")
        if path.is_file()
    }


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export_root", type=Path)
    args = parser.parse_args()
    root = args.export_root
    result = normalize(
        (root / "inspect.stdout").read_bytes(), load_raw(root / "planning-input")
    )
    write(root, "normalized-plan.json", canonical(result) + b"\n")
    print(
        canonical(
            {
                "tasks": [task["id"] for task in result["tasks"]],
                "initially_eligible": eligible_tasks(result, []),
                "after_T01_acceptance": eligible_tasks(result, ["T-01"]),
                "snapshot_sha256": result["snapshot_sha256"],
            }
        ).decode()
    )


if __name__ == "__main__":
    main()
