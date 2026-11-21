"""Frozen synthetic inputs for M-CLI1. All strings are UTF-8/LF."""

import json


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


SEED = {
    "package.json": '{\n  "name": "m-cli1-fixture",\n  "version": "1.0.0",\n  "private": true,\n  "type": "module"\n}\n',
    "src/name-policy.js": "// Stateless pattern for blank names.\nexport const blankPattern = /^\\s*$/u;\n",
    "test/name-policy.test.js": """import assert from 'node:assert/strict';
import test from 'node:test';
import { blankPattern } from '../src/name-policy.js';

test('legacy search recognizes blank names', () => {
  assert.equal('Ada'.search(blankPattern), -1);
  assert.equal('\\t'.search(blankPattern), 0);
  assert.equal('\\t'.search(blankPattern), 0);
});
""",
}

T1 = {
    "src/validate.js": """export function validateName(input) {
  if (/^\\s*$/u.test(input)) throw new TypeError('Name must not be blank');
  return input;
}
""",
    "test/validate.test.js": """import assert from 'node:assert/strict';
import test from 'node:test';
import { validateName } from '../src/validate.js';

for (const name of ['Ada', '  Ada  ']) {
  test(`preserves ${JSON.stringify(name)}`, () => assert.equal(validateName(name), name));
}
for (const name of ['', '   ', '\\t']) {
  test(`rejects ${JSON.stringify(name)}`, () => {
    assert.throws(() => validateName(name), { name: 'TypeError', message: 'Name must not be blank' });
  });
}
""",
}

T2 = {
    "src/cli.js": """import { validateName } from './validate.js';

try {
  const name = validateName(process.argv[2] ?? '');
  process.stdout.write(`Hello, ${name}!\\n`);
} catch (error) {
  process.stderr.write(`${error.message}\\n`);
  process.exitCode = 2;
}
""",
    "test/cli.test.js": """import assert from 'node:assert/strict';
import test from 'node:test';
import { spawnSync } from 'node:child_process';

for (const args of [['Ada'], ['  Ada  '], [], [''], ['   '], ['\\t']]) {
  test(`CLI ${JSON.stringify(args)}`, () => {
    const result = spawnSync(process.execPath, ['src/cli.js', ...args], { encoding: 'utf8', timeout: 5000 });
    assert.equal(result.error, undefined);
    const valid = args.length > 0 && /\\S/u.test(args[0]);
    assert.equal(result.status, valid ? 0 : 2);
    assert.equal(result.stdout, valid ? `Hello, ${args[0]}!\\n` : '');
    assert.equal(result.stderr, valid ? '' : 'Name must not be blank\\n');
  });
}
""",
}

TASKS = [
    {
        "id": "T-01",
        "plan": "01-01",
        "depends_on": [],
        "allowed_additions": list(T1),
        "criteria": ["valid-names-preserved", "blank-names-rejected"],
        "candidate_checks": ["scope-v1", "validator-unit-v1", "whitespace-grader-v1"],
        "integrated_checks": [
            "legacy-v1",
            "validator-unit-v1",
            "whitespace-grader-v1",
            "repeat-blank-v1",
        ],
    },
    {
        "id": "T-02",
        "plan": "01-02",
        "depends_on": ["T-01"],
        "allowed_additions": list(T2),
        "criteria": [
            "validator-reused",
            "valid-exits-zero",
            "blank-exits-two-with-stderr",
        ],
        "candidate_checks": ["scope-v1", "cli-unit-v1", "cli-subprocess-grader-v1"],
        "integrated_checks": [
            "legacy-v1",
            "validator-unit-v1",
            "whitespace-grader-v1",
            "repeat-blank-v1",
            "cli-unit-v1",
            "cli-subprocess-grader-v1",
        ],
    },
]

PROMPTS = {
    "T-01": """M-CLI1 PR-01 T-01 | base={input_oid} | operation={message_op} | task={task_digest}
Add src/validate.js and test/validate.test.js only. Export validateName(input) for string inputs. Return nonblank names unchanged. Throw TypeError with message Name must not be blank for empty and ECMAScript whitespace-only strings, including tabs and mixed whitespace. Use a stateless check. Use node:test and node:assert/strict for Ada, padded Ada, empty, spaces and one tab. Run node --test test/validate.test.js. Report the two paths and test exit. Use the assigned source and preloaded tools. Leave Git, dependencies and network configuration alone.
""",
    "T-02": """M-CLI1 PR-01 T-02 | base={input_oid} | operation={message_op} | task={task_digest}
Add src/cli.js and test/cli.test.js only. Import validateName from ./validate.js. Validate argv[2], defaulting missing input to the empty string. For success print Hello, <name>! followed by LF to stdout and exit 0. For a validation error print its message followed by LF to stderr and exit 2. Use node:test, node:assert/strict and node:child_process for argv cases Ada, padded Ada, missing, empty, spaces and one tab. Assert exit, stdout and stderr. Run node --test test/cli.test.js. Report the two paths and test exit. Use the assigned source and preloaded tools. Leave Git, dependencies and network configuration alone.
""",
}

PINS = {
    "gsd": {"version": "1.21.0", "commit": "357508df233ccca0dcf4332b385d6bee9b113da9"},
    "openhands": {
        "version": "1.62.0",
        "commit": "504a88cab0fb48ee5226238ad7b8f1d865fa84a8",
    },
    "litellm": "1.105.1",
    "node": "22.16.0",
    "git": "2.51.0",
}

POLICY = {
    "id": "fixture-policy-v1",
    "status": "proposed",
    "currency": "micro-USD",
    "paid_inference": False,
    "model": "fixture/model-v1",
    "sdk_model": "openai/fixture/model-v1",
    "num_retries": 0,
    "fallbacks": [],
    "native_resume": False,
    "limits": {
        "milestone": 1500000,
        "T-01": 500000,
        "T-02": 800000,
        "review_per_task": 160000,
        "attempt": 320000,
        "edit": 240000,
        "correction": 160000,
        "finish": 80000,
        "review": 120000,
    },
    "runtime": {
        "vm_cpus": 2,
        "vm_ram_mib": 4096,
        "container_cpus": 1,
        "container_ram_mib": 2048,
        "container_pids": 128,
        "vm_lifetime_seconds": 600,
        "stop_seconds": 10,
        "call_seconds": 30,
        "check_seconds": 30,
        "reconciliation_seconds": 60,
        "task_seconds": 1200,
        "milestone_seconds": 2400,
    },
    "storage": {
        "guest_bytes": 8 * 1024**3,
        "source_bytes": 1024**3,
        "scratch_bytes": 128 * 1024**2,
        "artifact_bytes": 10 * 1024**2,
        "diagnostic_bytes": 10 * 1024**2,
        "files": 128,
        "file_bytes": 1024**2,
    },
    "retention_days": 90,
    "expected": {
        "B0": {"attempts": 2, "reviews": 2, "submissions": 6, "settled": 360000},
        "B1": {"attempts": 3, "reviews": 3, "submissions": 9, "settled": 540000},
    },
}


def sources():
    """Named full trees; rejected candidates remain outside clean ancestry."""
    clean1 = SEED | T1
    clean2 = clean1 | T2
    mixed = clean1 | {
        "src/validate.js": T1["src/validate.js"].replace(
            r"/^\s*$/u", r"/^(?: +|\t+)?$/u"
        )
    }
    stateful = clean1 | {
        "src/validate.js": "import { blankPattern } from './name-policy.js';\n"
        + T1["src/validate.js"].replace(
            r"/^\s*$/u.test(input)", "blankPattern.test(input)"
        )
    }
    maintenance = SEED | {
        "src/name-policy.js": "// Pattern may retain match state.\nexport const blankPattern = /^\\s*$/gu;\n"
    }
    return {
        "S0": SEED,
        "C1": clean1,
        "C2": clean2,
        "B1-rejected": mixed,
        "C-D": stateful,
        "H-D": maintenance,
        "I-D": stateful | maintenance,
        "I-D-corrected": maintenance | T1,
    }


def planning_files():
    files = {
        ".planning/PROJECT.md": "# M-CLI1\n\nValidate a name and expose a dependency-free CLI. Synthetic experiment only.\n",
        ".planning/REQUIREMENTS.md": "# Requirements\n\n- [ ] **CLI-01**: Preserve nonblank names; reject ECMAScript whitespace-only names.\n- [ ] **CLI-02**: Reuse the validator; greet on stdout or exit 2 with an error on stderr.\n",
        ".planning/ROADMAP.md": "# Roadmap\n\n## Milestone v1.0: M-CLI1\n\n- [ ] **Phase 1: Validate CLI** - Implement CLI-01 and CLI-02.\n\n### Phase 1: Validate CLI\n**Goal:** Validate names and provide a CLI.\n**Depends on:** Nothing\n**Requirements:** CLI-01, CLI-02\n**Success Criteria:** Validator and CLI meet their frozen checks.\n**Plans:** 2 plans\n\nPlans:\n- [ ] 01-01-PLAN.md - Name validator\n- [ ] 01-02-PLAN.md - CLI\n",
        ".planning/STATE.md": "# Project State\n\n## Current Position\n\nPhase: 1 of 1 (Validate CLI)\nPlan: 0 of 2 in current phase\nStatus: Ready to execute\n",
        ".planning/config.json": canonical(
            {
                "mode": "interactive",
                "parallelization": False,
                "git": {"branching_strategy": "none"},
            }
        ).decode()
        + "\n",
        ".planning/phases/01-validate-cli/01-CONTEXT.md": "# Phase 1 Context\n\nPreserve input bytes for nonblank strings. Blank includes mixed ECMAScript whitespace. Missing argv is blank. CLI uses only argv[2]. No dependencies, Git writes or network access.\n",
    }
    for n, task in enumerate(TASKS, 1):
        actions = PROMPTS[task["id"]].split("\n", 1)[1].strip()
        deps = "[]" if n == 1 else '["01-01"]'
        files[f".planning/phases/01-validate-cli/01-0{n}-PLAN.md"] = f"""---
phase: 01-validate-cli
plan: 0{n}
type: execute
wave: {n}
depends_on: {deps}
files_modified: {json.dumps(task["allowed_additions"])}
autonomous: true
requirements: ["CLI-0{n}"]
---

<objective>Implement {task["id"]} from the frozen synthetic milestone.</objective>
<context>@01-CONTEXT.md</context>
<tasks>
<task type="auto">
  <name>{task["id"]}</name>
  <files>{", ".join(task["allowed_additions"])}</files>
  <action>{actions}</action>
  <verify><automated>node --test test/{"validate" if n == 1 else "cli"}.test.js</automated></verify>
  <acceptance_criteria>{", ".join(task["criteria"])}</acceptance_criteria>
  <done>All frozen candidate checks and independent review pass on the exact revision.</done>
</task>
</tasks>
"""
    return files
