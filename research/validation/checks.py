"""Independent fixture graders. Execute only trusted synthetic source locally."""

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from .bundle import digest, inventory
from .fixture import TASKS, canonical


def run_node(root, args):
    result = subprocess.run(
        ["node", *args],
        cwd=root,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=30,
        shell=False,
        check=False,
    )
    if len(result.stdout) + len(result.stderr) > 1024**2:
        raise ValueError("check output exceeds fixture limit")
    return {
        "exit": result.returncode,
        "stdout": result.stdout.decode("utf-8"),
        "stderr": result.stderr.decode("utf-8"),
    }


def scope(base, candidate, task):
    before, after = inventory(Path(base)), inventory(Path(candidate))
    allowed = next(row["allowed_additions"] for row in TASKS if row["id"] == task)
    return set(after) - set(before) == set(allowed) and all(
        after.get(path) == record for path, record in before.items()
    )


def validator(root, value, repeat=1):
    script = """import { validateName } from './src/validate.js';
const results = [];
for (let i = 0; i < COUNT; i++) {
  try { results.push({value: validateName(INPUT)}); }
  catch (e) { results.push({name: e.name, message: e.message}); }
}
console.log(JSON.stringify(results));
""".replace("COUNT", str(repeat)).replace("INPUT", json.dumps(value))
    result = run_node(root, ["--input-type=module", "-e", script])
    if result["exit"] != 0:
        return {"process_failure": result}
    return json.loads(result["stdout"])


def grade(root, task, integrated=False, review=False):
    root = Path(root)
    checks = []

    def record(name, expected, actual):
        checks.append(
            {
                "check": name,
                "pass": actual == expected,
                "expected": expected,
                "actual": actual,
            }
        )

    if integrated:
        result = run_node(root, ["--test", "test/name-policy.test.js"])
        record("legacy-v1", 0, result["exit"])
    if task == "T-01" or integrated:
        result = run_node(root, ["--test", "test/validate.test.js"])
        record("validator-unit-v1", 0, result["exit"])
        blank = {"name": "TypeError", "message": "Name must not be blank"}
        for value in ("Ada", "  Ada  ", "", "   ", "\t"):
            expected = {"value": value} if value.strip() else blank
            record(
                "whitespace-grader-v1:" + json.dumps(value),
                [expected],
                validator(root, value),
            )
        if integrated:
            record("repeat-blank-v1", [blank, blank], validator(root, "\t", 2))
        if review:
            record("review-mixed-blank", [blank], validator(root, " \t "))
            for value in ("\u00a0", "\ufeff", "\u2028\t"):
                record(
                    "review-ECMAScript-blank:" + json.dumps(value),
                    [blank],
                    validator(root, value),
                )
    if task == "T-02":
        result = run_node(root, ["--test", "test/cli.test.js"])
        record("cli-unit-v1", 0, result["exit"])
        for args in (["Ada"], ["  Ada  "], [], [""], ["   "], ["\t"]):
            valid = bool(args and args[0].strip())
            expected = {
                "exit": 0 if valid else 2,
                "stdout": f"Hello, {args[0]}!\n" if valid else "",
                "stderr": "" if valid else "Name must not be blank\n",
            }
            record(
                "cli-subprocess-grader-v1:" + json.dumps(args),
                expected,
                run_node(root, ["src/cli.js", *args]),
            )
        if review:
            # Substitution has a separate copy/digest and never alters the subject.
            with tempfile.TemporaryDirectory(prefix="mcli1-substitution-") as temporary:
                copy = Path(temporary) / "source"
                shutil.copytree(root, copy)
                (copy / "src/validate.js").write_bytes(
                    b"export function validateName() { throw new TypeError('fixture-substitution'); }\n"
                )
                record(
                    "review-validator-reuse",
                    {"exit": 2, "stdout": "", "stderr": "fixture-substitution\n"},
                    run_node(copy, ["src/cli.js", "Ada"]),
                )
    return {
        "task": task,
        "phase": "integrated" if integrated else "candidate",
        "review_checks": review,
        "source_manifest_sha256": digest(canonical(inventory(root))),
        "pass": all(row["pass"] for row in checks),
        "checks": checks,
        "classification": "local trusted-gold check; not isolated executor or independent reviewer qualification",
    }
