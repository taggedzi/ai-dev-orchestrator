# Agent milestones to finish the orchestrator

Status: **open, November 24, 2026.** The product is incomplete. This file is the
work order for later agents. It does not close R1–R9, and it does not replace
[the vision](vision.md), [requirements](requirements.md), or
[the delivery plan](product-delivery-plan.md).

Pickup files `AGENTS.md`, `docs/HANDOFF.md`, `docs/NEXT_AGENT.md`,
`docs/status.md`, and `docs/implementation/agent-handoff-evidence.json` are
hash-pinned by `python .local/validation/verify-agent-handoff-02.py`. This work
order is a new file, so that check still applies to the older pickup. Do not
edit those pinned files in an ordinary milestone. A session that must change
them copies the old bytes into a new `.local/validation/` snapshot, writes a
new resolutions file and a new verifier, and leaves the old evidence JSON
unchanged.

## How to take a milestone

1. Read [AGENTS.md](../AGENTS.md), [the vision](vision.md), [HANDOFF.md](HANDOFF.md),
   [NEXT_AGENT.md](NEXT_AGENT.md), and this file.
2. Take the lowest-numbered **open** milestone. One milestone per session.
3. Use `.local/product-web-venv/Scripts/python.exe` or `C:/Python315/python.exe`
   (Python 3.15.2 / SQLite 3.53.4). Bare `python` is 3.13 with an affected
   SQLite and must not write a product store.
4. Use a new scratch database. Do not migrate or open a retained evidence store
   to try new code.
5. `coordinator/` must not import `research`.
6. Keep `live_eligible` false and status `capabilities.task_acceptance` false
   unless milestone P5 says the measured run recorded one acceptance.
7. Update this file's status line for the milestone you finished, plus the
   protocol doc for that area. Record commands, counts, and limits.
8. No commit, push, publication, new dependency, provider call, VM command, or
   held-reservation transfer. No subagent delegation.

Workspace: `E:\Home\Documents\Programming\ai-dev-orchestrator`. Branch:
`research/m1-11-executor-recovery`. Last observed HEAD:
`e609dbce6af8f3f845ea8226bf2648fbe245197c`. Preserve dirty and untracked files
and `.local` artifacts. HEAD alone is not the tree.

## Already measured — do not rebuild

| Increment | What exists | Evidence to leave untouched |
| --- | --- | --- |
| P1 planning authority | Versioned project, context, requirements, exact plan approval, one attempt, pause/revision/recovery, CLI and loopback web on the same commands. Schema is **7**. | [p1-core-evidence-02.json](implementation/p1-core-evidence-02.json), [product-web-evidence.json](implementation/product-web-evidence.json). Web install of the 19 pinned wheels is done. |
| Scripted P2 | Trusted Git intake, immutable packets, scripted checks/reviews, private staging, diverged-head mapping, fresh checks and review on a distinct integrated commit, one serialized promotion. Task 2's input can be that accepted revision on a scratch fixture. | Retained bundle is **87 passed** in [product-integration-evidence.json](implementation/product-integration-evidence.json). Later scratch runs passed **100** (promotion) and **109** (model policy). Do not rewrite the 87-test bundle. |
| Scripted P3 | One policy per milestone, one eligibility assignment per attempt role, one permit per submission. Denied route, fallback, and replay. Protected review allowance. Known, estimated, pending, and unknown reports. | [product-model-policy.md](product-model-policy.md) and the schema-7 section of [status.md](status.md). |
| Decision 0007 preparation | Scratch successor tests (15) and non-native offline-startup tests (26), plus one unattached backup. Production row `ccc16a8440524bda84e57fdcd90055e7` stays held/active=1. | [held-successor-evidence.json](../research/validation/held-successor-evidence.json). `transferred` is false. |

Approvals already recorded, so do not ask again: Decisions
[0007 and 0008](decisions/0007-0008-approval.json), and the
[web install](implementation/web-install-approval.json). Decision 0008 allows
the remaining local product implementation and scratch tests. It does not allow
a commit to this repository, deployment, a live model, or native work.
Decision 0007 preparation does not allow a real reservation transfer or a VM boot.

## Stale sentences

Later measurements moved past some older paragraphs. Use this file when they
disagree.

- [NEXT_AGENT.md](NEXT_AGENT.md) says the product schema is 4 and that restore
  is unimplemented. Current `coordinator/store.py` has `SCHEMA_VERSION = 7`.
  M1 added `restore`. M2 kept it and added the promotion and cost commands.
- [README.md](README.md) says the product never promotes a milestone. Scripted
  promotion is measured. `live_eligible` stays false.
- [completion-audit.md](completion-audit.md) still says R2 has no measured
  assignment and R4 has no guarded promotion. Scripted P3 and scripted promotion
  exist. R1–R9 stay incomplete until the final proofs in the delivery plan.
- The retained 87-test bundle is a historical checkpoint. Later scratch
  counts include 100, 109, M1's 114, M2's 118, M3's 121, M4's 126, and M5's
  132. Product tests do not repair the research cohort (**609 tests: 594 passed,
  14 skipped, one startup-BEGIN BUSY error**).

## Open product milestones

These stay inside Decision 0008. Each one ends with scratch tests, Ruff on the
edited Python, and an updated protocol paragraph. A green scripted run is a
milestone result, not P4, P5, or a completed requirement.

### M1. Archive restore and path rebinding

**Status:** done, November 24, 2026. The product modules passed **114 tests,
0 skips**, on `.local/product-web-venv` (Python 3.15.2 / SQLite 3.53.4),
including the new scratch tests in `tests/test_coordinator.py`. Ruff check and
format passed on the edited Python. Scratch tests in `tests/test_coordinator.py`
cover backup, a file copy, restore to a new path, one pause on that primary,
and refusal of the archive and the copy. A digest mismatch, a corrupt page, a
byte change between the two reads, a failed rebind, an unmarked copy, and an
older `user_version` leave no destination. `backup` now returns the checkpointed
file's SHA-256. `python -m coordinator restore ARCHIVE DESTINATION --digest SHA256`
does not open `--db`. Protocol: [product-intake.md](product-intake.md#archive-restore)
and [product-cli.md](product-cli.md). This is not host power-loss durability.
The original primary at its bound path is unchanged. Schema stays 7.
`AGENTS.md`, `docs/HANDOFF.md`, `docs/NEXT_AGENT.md`, and `docs/status.md` were
not edited. `docs/implementation/agent-handoff-evidence.json` records the new
hashes for `coordinator/store.py`, `coordinator/cli.py`, and
`tests/test_coordinator.py`. The 87-test snapshots were not rewritten.

Backups set `archive=1` and bind `primary_path`. `require_primary` refuses
business writes on an archive or a copied store. Do not improvise a restore by
editing metadata. Do not open `.local/validation/offline-guard-admissions.sqlite`
or `owner/owner.sqlite`.

### M2. Operator surface for scripted promotion and cost

**Status:** done, November 24, 2026. The product modules passed **118 tests,
0 skips**, on `.local/product-web-venv` (Python 3.15.2 / SQLite 3.53.4),
including the HTTP tests in `tests/test_coordinator_operator.py`. Ruff check
and format passed on the edited Python. `restore` from M1 remains. The same
command layer now also exposes `cost-report`, `model-policy-approve`,
`model-assign`, `model-permit`, `model-lose-response`, `model-observe-usage`,
`promotion-authorize-head`, `promotion-approve-regressions`,
`promotion-approve-evidence`, `promotion-begin`, `promotion-promote`, and
`promotion-reconcile`. The loopback routes call those methods. Status `cost`
has `known_units`, `estimated_units`, `pending_units`, and `unknown_units`.
Status also has `pending_decisions` and `scripted_task_accepted`. The project
panel renders those fields, plus `capabilities.task_acceptance` and
`live_eligible`, from `GET /api/projects/{id}`.

The HTTP run recorded a scripted report of known 4, estimated 3, pending 2,
and unknown 5. One scratch promote returned `task_accepted` true for that
integration, and status `scripted_task_accepted` was true. The CLI reconcile
returned that stored duplicate. `capabilities.task_acceptance` and
`live_eligible` stayed false. A missing managed repository was refused before
any promotion write. No provider call and no candidate command execution.
`coordinator/application.py` does not import `research`. Schema stays 7.

Protocol: [product CLI](product-cli.md#scripted-promotion-and-cost),
[product web](product-web.md), [product integration](product-integration.md),
and [model policy](product-model-policy.md). Browser proof of the panel remains
M6. `AGENTS.md`, `docs/HANDOFF.md`, `docs/NEXT_AGENT.md`, and `docs/status.md`
were not edited. Moved-source hashes in
`docs/implementation/agent-handoff-evidence.json` were updated for the edited
pinned files. The 87-test snapshots were not rewritten. M3 is recorded below.

### M3. Guided discovery records

**Status:** done, November 25, 2026. The product modules passed **121 tests,
0 skips**, on `.local/product-web-venv` (Python 3.15.2 / SQLite 3.53.4).
Ruff check and format passed on the edited Python. Schema stays 7.
`discovery-record` and `POST /api/projects/{id}/discovery` append one
developer-supplied turn and save it through the existing revision fence.
Turns live in `context.discovery.turns`. `n` is the revision that first
contains the turn. Optional requirements replace the list; omitted
requirements stay. The same command id returns the stored result, and a
different question or answer with that id is refused.

Scratch coverage: two turns survived a second coordinator and a new CLI
process on the same file. A stale expected version, including the version
from before pause and a stale `project-revise`, wrote nothing. A turn on
the version after pause and approval appended revision 4. Plan submission
stayed unapproved until `plan-approve` of the stored digest; a different
digest was refused. `capabilities.task_acceptance` and `live_eligible`
stayed false. No provider call and no candidate command. This is stored
discovery, not interview quality. R8 remains open. Browser proof remains
M6. Next open milestone is M4.

Protocol: [product CLI](product-cli.md#stored-discovery) and
[product web](product-web.md). `AGENTS.md`, `docs/HANDOFF.md`,
`docs/NEXT_AGENT.md`, and `docs/status.md` were not edited. Moved-source
hashes were updated for the edited pinned files. The 87-test snapshots
were not rewritten.

Depends on M2 because both edit the CLI and web surface. The developer
approves an exact plan digest afterward, through the existing approval
command. Pause and revision fence an in-progress discovery by the current
expected version. Reopen returns the same answers.

### M4. Frozen planning import

**Status:** done, November 25, 2026. The product modules passed **126 tests,
0 skips**, on `.local/product-web-venv` (Python 3.15.2 / SQLite 3.53.4).
Ruff check and format passed on the edited Python. Schema stays 7. No new
table and no migration. `plan-import-gsd` and
`POST /api/projects/{id}/plan-import-gsd` read one frozen GSD Core schema-1
snapshot plus the raw PLAN files named by that snapshot, then submit one
unapproved plan through `submit_plan`. The stored result has `approved`
false. The same command id returns that result. A different snapshot digest
with that id is refused. Exact `plan-approve` of the stored digest remains
mandatory. GSD stays a read-only import. The coordinator owns approval. R1
remains open.

The checked-in snapshot `tests/fixtures/gsd-schema-1.json` is 5270 bytes,
SHA-256 `3568a79095dd2868053f389295e11b57c45f18af79f5c74ace509f5ec9f9aa92`.
That is the file hash, not the research export stdout hash
`5fc3b148578fc357606e7744e12e692d914eb0b9354f99b60e21264bc8685df3`.
Copied PLAN bodies, taken from `planning_files()` and not read through a
`research` import by `coordinator/` or the product tests:

| File | Bytes | SHA-256 |
| --- | --- | --- |
| `tests/fixtures/gsd-schema-1-plans/01-01-PLAN.md` | 1260 | `87c0d15f905df82fa8d607c3215cd8b9830e78e622a53fe6687084051bccff2c` |
| `tests/fixtures/gsd-schema-1-plans/01-02-PLAN.md` | 1335 | `82329e3c3146d52285e7b1215d41e447bd6670bffa64694fa63bf277fa5653ed` |

Scratch coverage on a new store with requirements CLI-01 and CLI-02: the
fixture import returned `approved` false. Status showed one unapproved plan,
an empty `approved_plan_id`, and `pending_decisions` contained
`plan_approval` for that digest. Tasks were T-01 then T-02, and T-02 depends
on T-01. Check argv were `node --test test/validate.test.js` and
`node --test test/cli.test.js`. A second coordinator on the same file
returned the same plan digest. A one-byte snapshot change presented with the
original digest refused, and a one-byte PLAN change refused, both with the
plan count unchanged. Schema values other than integer 1, a dependency
cycle, and a snapshot requirement absent from the project each refused
before a plan write. `plan-approve` of a different digest was refused.
`plan-approve` of the stored digest succeeded. The import had not approved
it. `capabilities.task_acceptance` and `live_eligible` stayed false. No
network connection was opened.

Limits: snapshot bytes must match the supplied SHA-256 before any plan
write. `schema_version` must be integer 1. The snapshot cap is 2 MiB and
each PLAN cap is 128 KiB. Missing, extra, and oversized PLAN files refuse.
A superseded or incomplete plan, a duplicated id, a missing dependency
target, a cycle, an unsafe path, and a requirement id absent from the
current project refuse with no plan row. Native GSD status, progress,
verification route, and done text are not acceptance and do not set
`task_accepted`, `capabilities.task_acceptance`, or `live_eligible`. The
import does not call `revise_project`, `record_discovery`, or `approve_plan`.
`coordinator/` does not import `research`. `integrations/` stays empty. This
is not M5, a live GSD fetch, browser QA, or P4–P6. Pinned GSD Core remains
v1.21.0 at `357508df233ccca0dcf4332b385d6bee9b113da9`; that commit was not
fetched. Browser proof remains M6. Next open milestone is M5.

Protocol: [product CLI](product-cli.md#frozen-planning-import) and
[product web](product-web.md). `AGENTS.md`, `docs/HANDOFF.md`,
`docs/NEXT_AGENT.md`, and `docs/status.md` were not edited. Moved-source
hashes were updated for the edited pinned files. The 87-test snapshots were
not rewritten.

### M5. Disabled execution boundary

**Status:** done, November 25, 2026. The product modules passed **132 tests,
0 skips**, on `.local/product-web-venv` (Python 3.15.2 / SQLite 3.53.4),
including six new scratch tests in `tests/test_coordinator_execution.py`. Ruff
check and format passed on the edited Python. Schema stays 7: no table,
migration, or `attempts.adapter` value changed.

The standard-library-only boundary in `integrations/openhands.py` records
OpenHands Agent Server v1.62.0 at commit
`504a88cab0fb48ee5226238ad7b8f1d865fa84a8`. Its single live `dispatch` method
refuses every reviewed or unknown operation before I/O with a stable local
exception. The refusal has `live_eligible` false and does not set
`capabilities.task_acceptance`. Connection, workspace, conversation, and API-key
payloads are ignored. `Coordinator.refuse_live_dispatch` returns that refusal to
developer and service principals without a store write or event insert. No CLI
command or HTTP route dispatches OpenHands.

`scripted_result` accepts only caller `scripted` and outcomes `candidate` or
`failed`. It returns a simulated `scripted-development` result with the existing
scripted model, provider, and zero-cost fields. It refuses any other caller and
cannot set `live_eligible` or task acceptance. The double is not wired into the
existing claim, start, result, or abandon commands; their stored shapes remain
unchanged.

Scratch coverage patched `socket.socket` and observed no call. A fake API key did
not appear in status or the database file. Refusals left attempts and events
unchanged, a service principal received the same refusal, and source scans found
no research, network, or process imports at the integration boundary. Existing
scripted claim/start/result behavior still used adapter `scripted`. Status kept
`live_eligible`, `capabilities.task_acceptance`, and
`capabilities.native_execution` false.

Limits: no socket, SDK, new dependency, schema change, or candidate execution.
Same-conversation automatic resume and attach stay disabled. This is not P4, a
live model route, browser QA, or qualification of commit
`504a88cab0fb48ee5226238ad7b8f1d865fa84a8`. R1 and R8 remain open. Next open
milestone is M6, which stays blocked.

Protocol: [product CLI](product-cli.md#disabled-execution-boundary).
`AGENTS.md`, `docs/HANDOFF.md`, `docs/NEXT_AGENT.md`, and `docs/status.md` were
not edited. Only the existing `coordinator/application.py` moved-source entry
changed in `docs/implementation/agent-handoff-evidence.json`.
`tests/test_coordinator_web.py`, retained snapshots, and historical evidence
were not rewritten.

### M6. Browser QA of the loopback dashboard

**Status:** driver installed, dashboard flows not run. On November 25, 2026
the developer made Playwright **1.64.1** a lasting project browser-test
dependency. It is not a product runtime dependency and it is not part of the
approved 19-wheel web install. M6 is its first use. The hash-locked set is
[browser-qa.in](../requirements/browser-qa.in) and
[browser-qa-win-py315.lock](../requirements/browser-qa-win-py315.lock):
playwright 1.64.1, greenlet 3.5.6, pyee 14.0.0, typing-extensions 4.16.0.
Those wheels are installed in `.local/browser-qa-venv` with
`C:\Python315\python.exe`. `pip check` passed. `.local/product-web-venv` was
not modified. Headless Chromium 156.0.8078.4, the revision already cached for
this Playwright release, launched and reported `page.url` as `about:blank`.
That was not a dashboard session. The old Computer Use failure and its dead
server stay as recorded. Do not start the product server only to recheck that
failure.

Use `.local/browser-qa-venv/Scripts/python.exe` for the browser. When it can
read the page URL, exercise create/revise, plan approval, pause/resume/recover,
and the M2 cost and pending-decision panels. Loopback, exact Host/Origin, and
the existing session stay in force. Record the URL and the actions. A
screenshot alone is not the result. If the URL is still unreadable, stop and
leave this milestone blocked.

## Qualification gates

P4 and P5 stay blocked until the applicable gate below has its own measured
evidence and, where stated, a new exact developer approval. Do not start these
gates from a product milestone.

| Gate | Needed before | Current measured state | Still required |
| --- | --- | --- | --- |
| Q1. Decision 0007 transfer | Any later guard boot | Scratch tests, surrogates, read-only inventory, unattached copy. Row stays held/active=1. | A new exact approval of one named transfer artifact. One atomic compare/transfer. The old stop stays unaccepted. No boot in the approval-writing session. |
| Q2. M1-12 isolation, issue #12 | Executing candidate code on the final profile | Specified. Final target unqualified. | Denial groups, live positive controls, one allowed edit, stop/cleanup. |
| Q3. M1-13 gateway, issue #13 | A gateway model route | Local conformance and simulated spending. | Allowed and forbidden routes, identity joins, interrupted replies, unknown-spend holds on the deployed gateway. |
| Q4. M1-11 executor recovery, issue #11 | A qualified executor route | Preflight and source review. Runtime cases inconclusive. PR #25 must keep that inconclusive state visible. | Success, cancellation, lost acknowledgement, and crash, with independent stop/reap and reconcile-or-hold. |
| Q5. Guest readiness | A qualified target profile | Guard aborted/unlocked. Executor poweroff/unlocked. OS update set is cached. | Installation, hardening, UART ownership, effective isolation. Each change has its own approval. |
| Q6. Provider budget | Any paid or provider-data call | No live route. | A named budget and scope. Subscription access needs a terms assessment; an unsupported interface stays unavailable. |
| Q7. Research cohort hold | Nothing in M1–M6 | 609 tests, one startup-BEGIN BUSY. Four focused SQLite diagnostics passed. `NativeBindingTests` held on `database is locked`. | Diagnosis only if the developer asks. Do not rerun the full research suite as part of a product milestone. Do not weaken the binding test. |

`Aborted` is not a successful stop. Do not clear the held admission, call
`finish(settled=True)`, or replay the old owner stop.

## Live acceptance milestones

### P4. Qualified adapters

**Status:** blocked on Q2 and Q4 for the executor, and on Q3 or a local/direct
equivalent plus Q6 when the route is paid.

Connect only a profile that has the gate evidence above. Preserve deployed
versions and input hashes. One allowed request, identity and usage evidence,
and a failure that holds. An unqualified adapter stays disabled. M5's refusal
remains the default for every route that lacks that evidence.

### P5. Two-task proof of concept

**Status:** blocked on P4, M1, and M2.

One approved milestone, two dependent tasks, on a fixture chosen before the
run. Real isolated edits. One injected recoverable failure and a fresh bounded
attempt. Rejected candidate and rejected review stay unpromoted. A changed SHA
invalidates review. Integrated checks bind the promoted commit. Task 2 starts
from that accepted revision. The developer report lists usage, cost, and
interventions, with estimates and unknowns separated. Every artifact links to
the approved plan, the attempts, and the exact revisions.

This is the vision's proof of concept and the R1–R6 demonstration in
[the delivery plan](product-delivery-plan.md). Scripted stand-ins do not
substitute.

### P6. Lifecycle and release preparation

**Status:** blocked on P5. M3 can land earlier as stored discovery.

A fresh operator follows setup, discovery, and approval through the P5 run,
pauses and redirects active work, and restarts without losing context. Backup
and restore use M1 on a disposable instance. The session produces a verified
package, a dependency and license inventory, migration and recovery notes, and
a requirement-by-requirement audit. Publication stays a separate developer
action.

## Definition of done

The project is done when the delivery plan's final proofs exist:

| Requirement | Proof |
| --- | --- |
| R1 | Approved versioned P5 plan. Task 2's input equals the accepted task-1 integration. |
| R2 | Eligibility, requested configuration, and observed identities for each implementation and review task. Missing fields stay labeled. |
| R3 | Qualified target controls, independent allowed and denied probes, real scoped edits, revisions, and test records. |
| R4 | Separate reviewer and mandatory checks for each exact candidate. Guarded integrated revision and a passing regression before a dependent is released. |
| R5 | Durable attempts across a crash. One injected recoverable failure inside the limit. Exhausted or uncertain results escalate with no blind replay. |
| R6 | Milestone totals across implementation, corrective work, and review. Known amounts separated from estimates, pending, and unknown. |
| R7 | Pause and redirect tested during execution. Stale authority cannot dispatch, spend, or promote. Scope, architecture, exception, and publication stay gated. |
| R8 | Discovery produces durable requirements and context. Dashboard shows progress, cost, failures, and pending decisions. Release artifacts exist. |
| R9 | Repeatable self-hosted setup, backup, and restart. Observed qualified local, gateway, and direct API integrations. A written subscription-access assessment. |

Unit tests, the 109-test scratch run, and a green scripted promotion do not
meet this table.

## Session prompt

Copy one block. Fill nothing else.

```text
Workspace: E:\Home\Documents\Programming\ai-dev-orchestrator
Read AGENTS.md, docs/vision.md, docs/HANDOFF.md, docs/NEXT_AGENT.md, and docs/agent-milestones.md.
Do milestone M1 only. Follow its dependencies, prohibitions, and acceptance.
Use the product-web venv or C:/Python315/python.exe. Scratch stores only.
Do not edit the hash-pinned pickup files. Update docs/agent-milestones.md and the protocol doc for this milestone.
No commit, push, publication, new dependency, provider call, VM command, or reservation transfer.
```

Replace `M1` with `M2`, `M3`, `M4`, or `M5` only after the dependency named in
that section is recorded done in the status line above. M6, Q1–Q7, P4, P5, and
P6 stay closed until this file says their gate is open.
