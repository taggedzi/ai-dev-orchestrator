# Product CLI: durable planning and development attempts

The first product increment stores projects, requirements/context revisions,
milestone plans, exact approvals, attempts, possible-delivery intents and audit
events in its own SQLite database. It runs independently of the research harness.
Only a scripted development adapter is enabled. It does not execute check
commands, edit source, call a provider or accept/integrate revisions.

Use Python 3.13 or later with a patched SQLite build. On the inspected workstation,
`C:/Python315/python.exe` provides Python 3.15.2 / SQLite 3.53.4. Bare `python`
currently has an affected SQLite build and is refused for product-store access.
No new dependency installation is needed for the core and CLI.

New stores use schema 7. Existing schema-1 through schema-6 primary stores need the explicit
[offline migration](product-intake.md#schema-migration), with all old writers
stopped and a new backup destination. Ordinary startup never migrates a store.
`restore` binds a verified archive as a new primary. A copied store stays a non-writer.

## First two commands

From the repository root, create a new store and a development project:

```powershell
C:/Python315/python.exe -m coordinator --db .local/orchestrator/example.sqlite init
C:/Python315/python.exe -m coordinator --db .local/orchestrator/example.sqlite project-create examples/p1-project.json
```

The second command returns the project ID and version. Existing database files
are never overwritten by `init`. The example repository and all-`a` baseline OID
are explicitly fictional; no Git object existence or isolation is established.
For a real project, supply your own JSON matching the example's structure.

## Plan review and approval

Submit [the example plan](../examples/p1-plan.json), substituting the project ID:

```powershell
C:/Python315/python.exe -m coordinator --db .local/orchestrator/example.sqlite plan-submit PROJECT_ID M1 examples/p1-plan.json --expected-project-version 1
C:/Python315/python.exe -m coordinator --db .local/orchestrator/example.sqlite status PROJECT_ID
```

Submission does not approve the plan. Inspect the stored plan and its digest.
`plan-approve PLAN_ID --digest DIGEST --expected-project-version VERSION
--expected-milestone-version VERSION` records approval of that exact intent and
returns the new versions. Changed criteria, dependencies, context or commands
need their own revision/approval. All mutations return JSON; errors use exit 2
and a structured message. CLI identity comes from the local operating-system user;
this is not remote authentication or protection against a hostile host.

`task-claim PROJECT_ID M1 T1 --expected-project-version VERSION
--expected-milestone-version VERSION` consumes one attempt slot and records a
prepared scripted operation atomically. Dependencies must be accepted, and only
one unsettled attempt may occupy a milestone. Absolute task attempt counts carry
across plan revisions for the same milestone/task key. T2 cannot start merely
because T1 reports completion.

## Scripted results and recovery

`scripted-start ATTEMPT_ID --expected-version VERSION` commits `possible_send`
before a development sender acts. `scripted-result OPERATION_ID --outcome
candidate` records a simulated candidate awaiting verification; `--outcome failed`
records a known scripted failure. These commands are development state exercises.
They neither run an agent nor turn a candidate into accepted work. Costs and
reported model identity are labeled simulated.

After an interrupted sender, inspect `status`, then use `recover PROJECT_ID
--expected-version VERSION --reason REASON`. Recovery pauses the project, advances
authority, cancels proven-unsent work and holds possible delivery. Late receipts
are retained but cannot reactivate old authority. An operator may use
`scripted-abandon ATTEMPT_ID --expected-version VERSION --reason REASON` only for
the fenced, held scripted adapter, whose computation has no external effects.
That command cannot settle native or provider effects. `resume` does not revive
old attempts. Corrections create fresh attempt/operation IDs within the cap.

Use `pause` for a developer stop. `project-revise FILE PROJECT_ID
--expected-version VERSION` saves a new requirements/context revision and fences
existing execution; a matching new plan must be approved before continuation.
Duplicate or conflicting receipts never release task dependencies. Contradictory
current receipts pause/fence and retain both observations.

`--command-id ID` deduplicates an identical local mutation after a lost response.
Reusing the ID with another actor, payload or command refuses. This is a local
database guarantee, not a provider or executor idempotency key.

## Stored discovery

`discovery-record PROJECT_ID --expected-version VERSION --question TEXT
--answer TEXT` appends one interview turn and saves a new requirements and
context revision through the same fence as `project-revise`. The project
pauses, and the result reports `needs_new_plan_approval`. Optional
`--requirements FILE` is a JSON list that replaces the requirement list and
must pass the project spec. Omitted requirements stay as they are. `--command-id`
deduplicates the same way as the other mutations.

The turn is stored at `context.discovery.turns` as `n`, `question`, and
`answer`. `n` is the revision number of the spec that first contains that
turn. Earlier turns stay in order, and the rest of `context`, including
`goal`, stays in place. The revision digest covers the whole spec. A fresh
project starts at revision 1, so the first recorded turn is revision 2.

This command does not call a model and does not approve a plan. Continuation
still needs `plan-approve` of the exact plan digest. A stale
`--expected-version` writes nothing, including after `pause` or
`project-revise`. The same `--command-id` returns the stored result. A
different question or answer with that id is refused. `status` returns the
turns in `project.spec`. Opening the same store again returns the same
questions and answers.

This is stored discovery. It is not a claim of interview quality, and R8
remains open.

## Frozen planning import

`plan-import-gsd PROJECT_ID MILESTONE_KEY SNAPSHOT --digest SHA256 --plans DIR
--expected-project-version VERSION --baseline REVISION --max-attempts N
--check-timeout SECONDS` reads one frozen GSD Core schema-1 snapshot and the
raw PLAN files in `DIR`. Optional `--command-id` is the same local
acknowledgement key as the other mutations. The command prints the
`submit_plan` result as JSON. Refusal exits 2. A developer principal is
required before any plan write. A service principal cannot call it.

The snapshot bytes are hashed before a plan row is written. The supplied
digest must be that lowercase SHA-256. `schema_version` must be the integer
1. The snapshot cap is 2 MiB. Each PLAN cap is 128 KiB. The directory must
contain exactly the filenames named by the snapshot, one PLAN per plan. The
PLAN frontmatter and its single auto task must agree with the snapshot on
`depends_on`, planned files, the objective, the task name, and the
acceptance criteria. The `<automated>` verify command is split on ASCII
spaces into check argv. The caller supplies `baseline`, `max_attempts`, and
the check timeout. `requirements_revision` is the current project revision.
Task ids are the snapshot task names. Dependencies are those task names.
One criterion is stored per acceptance string and bound to the PLAN
requirement id. The phase goal is the plan title.

The result is one unapproved plan for the whole phase. `approved` is false.
Repeating the same command id returns that stored result. The same command
id with a different snapshot digest is refused. Approval stays on
`plan-approve` of the stored digest. GSD stays a read-only import. The
coordinator owns approval. R1 remains open.

The import does not revise the project, record discovery, or approve the
plan. Native GSD status, progress, the verification route, and done text are
not acceptance. `capabilities.task_acceptance` and `live_eligible` stay
false. No network fetch is performed. `coordinator/` does not import
`research`.

The checked-in fixture `tests/fixtures/gsd-schema-1.json` is 5270 bytes,
SHA-256 `3568a79095dd2868053f389295e11b57c45f18af79f5c74ace509f5ec9f9aa92`.
That file hash is not the research export stdout hash
`5fc3b148578fc357606e7744e12e692d914eb0b9354f99b60e21264bc8685df3`.
The copied PLAN bodies are:

| File | Bytes | SHA-256 |
| --- | --- | --- |
| `tests/fixtures/gsd-schema-1-plans/01-01-PLAN.md` | 1260 | `87c0d15f905df82fa8d607c3215cd8b9830e78e622a53fe6687084051bccff2c` |
| `tests/fixtures/gsd-schema-1-plans/01-02-PLAN.md` | 1335 | `82329e3c3146d52285e7b1215d41e447bd6670bffa64694fa63bf277fa5653ed` |

For that fixture the tasks are T-01 then T-02. T-02 depends on T-01. The
check commands are `node --test test/validate.test.js` and
`node --test test/cli.test.js`. The product project must already contain
CLI-01 and CLI-02. The import does not invent requirements.

## Disabled execution boundary

`integrations/openhands.py` records the reviewed OpenHands Agent Server v1.62.0
boundary at commit `504a88cab0fb48ee5226238ad7b8f1d865fa84a8`, but its live
client refuses every `dispatch` locally before any I/O, including unknown
operations. Same-conversation automatic resume and attach remain disabled.
Supplied connection, workspace, conversation, and credential values are ignored.

The `scripted_result` double is available only to the existing `scripted`
development adapter. Its results are labeled `scripted-development` and
simulated; they cannot set `live_eligible` or `capabilities.task_acceptance`.
It is not wired into the stored scripted commands. No CLI command dispatches
OpenHands, and the coordinator's live-refusal method writes no store row or
event. Live eligibility and native execution remain disabled.

## Backups and current limits

`backup NEW_PATH` creates a consistent, integrity-checked archive and returns
the lowercase SHA-256 of that checkpointed file. It refuses an existing target.
Archives can be inspected, but business mutations stay blocked.

`restore ARCHIVE DESTINATION --digest SHA256` does not use `--db`. It checks
the digest, schema, application id, WAL mode, archive flag, integrity, and
foreign keys, then creates one new primary at `DESTINATION` and rebinds
`primary_path` there. The archive file is not modified. A copied or moved store
keeps its old path and stays a non-writer. A digest mismatch, a byte change
between the two archive reads, or a failed check leaves no destination. Do not
edit `meta` to bypass this command. The command does not prove host power-loss
durability.

Stores bind their absolute path. An older prototype that lacks that binding
cannot perform business mutations. This holds even if copying stopped before
the archive marker was written. `events` returns the ordered local audit
history. Ordinary startup validates the current schema and never migrates it.
No distributed coordinator or shared-network database is supported by this
increment.

## Scripted promotion and cost

These commands use the same developer command layer as the planning commands.
They do not call a provider or execute a candidate check. `live_eligible` stays
false. A promotion result may set `task_accepted` true for that one scripted
integration. Status `capabilities.task_acceptance` stays false.

`cost-report PROJECT_ID MILESTONE_KEY` reads the schema-7 report for one
milestone. `status` also returns project totals in `cost`: `known_units`,
`estimated_units`, `pending_units`, and `unknown_units`. It lists
`pending_decisions` and sets `scripted_task_accepted` when one stored promotion
receipt recorded `task_accepted`. With no policy, the four totals are zero.

`model-policy-approve`, `model-assign`, `model-permit`, `model-lose-response`,
and `model-observe-usage` record the existing scripted policy, assignment,
reservation, and usage operations. `--command-id` deduplicates a repeated
command the same way as the other mutations.

Promotion commands also require `--repository` and `--artifacts`, the trusted
managed repository and evidence directory. They refuse a path that is not that
layout.

- `promotion-authorize-head ATTEMPT_ID PREVIOUS_HEAD NEW_HEAD GENERATION`
  records one diverged expected head. It does not stage or promote.
- `promotion-approve-regressions PROPOSAL_ID FILE --digest SHA256
  --expected-version VERSION` approves one exact regression policy.
- `promotion-approve-evidence PROPOSAL_ID FILE --digest SHA256
  --expected-version VERSION` approves fresh checks and a separate review for
  one distinct integrated commit.
- `promotion-begin PROPOSAL_ID --expected-version VERSION` commits
  `possible_send` before the milestone ref write.
- `promotion-promote PROPOSAL_ID --expected-version VERSION` performs that
  begin, the private milestone ref update, and the acceptance record.
  `--command-id` is not an acknowledgement key for this combined command. A
  lost response uses `promotion-reconcile`.
- `promotion-reconcile PROPOSAL_ID` reads the existing milestone ref and records
  the promotion once. A second call returns the stored result.

`restore` remains a separate command and still does not use `--db`. Real
execution, provider adapters, deployment, and the R1–R9 demonstration remain
unqualified. A green scripted run is not that demonstration.
