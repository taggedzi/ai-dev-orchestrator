# Project status and restart point

## Scripted model policy and cost — November 24, 2026

Schema 7 adds one model policy per milestone, one eligibility assignment per
attempt role, and one permit per physical submission. An unavailable route, a
fallback route, and a reused submission id are denied and store no new
reservation. Repeating a permit command returns the original row. Implementation
spend cannot consume `protected_review_units`. A review permit can still use
that allowance after the implementation ceiling is exhausted. `lose_response`
keeps the reservation as unknown usage across reopen. A known amount settles
only that amount and releases the unused remainder for a new submission id. An
estimate stays reserved at the full amount. Pause holds an unsent permit and
does not release a reserved or reconciled row. The report separates known,
estimated, pending, and unknown units. `live_eligible` and
`capabilities.task_acceptance` stay false. No provider call is made.

Measured with `.local/product-web-venv/Scripts/python.exe`, Python 3.15.2 /
SQLite 3.53.4: the product modules passed **109 tests, 0 skips**. Ruff check
passed on the edited Python. The retained
[87-test evidence bundle](implementation/product-integration-evidence.json) was
not rewritten and was not migrated. No commit, push, publication, reservation
transfer, or VM boot occurred. This turn did not query VirtualBox.

Next work waits on the qualification lane before any P4 executor or live model
route. Decision 0007 preparation remains measured; a real transfer is still
unapproved.

## Scripted promotion and fresh integrated evidence — November 24, 2026

Schema 6 adds `attempts.settled`, integrated evidence tables, and one promotion
row per proposal. A distinct integrated commit stays held until fresh mandatory
checks and a separate review bind that OID. Candidate review and a passing
regression do not supply them. `I = C` stays promotion-ready from the existing
candidate evidence plus passing regressions.

`begin_promotion()` is developer-only and commits possible-send before Git.
`advance_milestone_ref()` writes only `refs/orchestrator/milestones/`. One
database transaction compares the milestone head guard, stores the integrated
revision, inserts one acceptance, and settles the attempt. It does not bump
project generation. A missing ref is held and is not created during reconcile.
Crash recovery reads the existing ref once; the second reconcile does not call
`update-ref`. Task 2 becomes ready only from that acceptance, and its input
revision equals the promoted commit. The promotion result can set
`task_accepted` true. Status `capabilities.task_acceptance` and `live_eligible`
stay false. `update_validation_ref()` is unchanged and is not promotion.

The disposable Git fixture covers a rejected candidate, a rejected integrated
review, a changed SHA, integrated checks bound to the promoted commit, one crash
reconcile, and task 2 starting from that revision. All of those outcomes are
scripted. Measured with `.local/product-web-venv/Scripts/python.exe`, Python
3.15.2 / SQLite 3.53.4: the product modules passed **100 tests, 0 skips**.
Ruff check and format passed on the edited Python. The retained
[87-test evidence bundle](implementation/product-integration-evidence.json) was
not rewritten and was not migrated. No commit, push, publication, reservation
transfer, or VM boot occurred. No `VBoxSVC`, `VBoxManage`, or `VBoxHeadless`
process was present.

Scripted model policy and cost were measured after this checkpoint. Decision
0007 preparation remains measured; a real transfer is still unapproved.

## Authorized diverged-head mapping — November 24, 2026

Schema 5 stores one developer authorization per attempt. The record binds the
attempt, the previous expected head, the new head, and the authority generation.
`authorize_diverged_head()` does not stage. A missing, stale, different, or
already consumed mapping refuses `prepare(expected_head=...)`. `begin()` consumes
a matching mapping once, in the same transaction as possible-send. Replaying the
same authorize command returns its committed result. A new command after
consumption conflicts.

A valid mapping makes private staging use that head as the merge base. The
milestone row, publication refs, and acceptance rows stay unchanged.
`task_accepted` and `live_eligible` stay false. A passing scripted regression on
the merged subject still sets `needs_fresh_integrated_checks_review` and does
not promote. `update_validation_ref()` is unchanged and is not promotion.

Measured with `.local/product-web-venv/Scripts/python.exe`, Python 3.15.2 /
SQLite 3.53.4: the product modules passed **92 tests, 0 skips**. The rerun adds
four mapping tests and a v4-to-v5 migration test to the previous cohort. Ruff
check and format passed on the edited Python. The retained
[87-test evidence bundle](implementation/product-integration-evidence.json) was
not rewritten and was not migrated. No commit, push, publication, reservation
transfer, or VM boot occurred. No `VBoxSVC`, `VBoxManage`, or `VBoxHeadless`
process was present. The previously recorded VBoxSVC pid 24848 was absent.

Next slice: fresh checks and review bound to a distinct integrated OID, then
one serialized promotion. Decision 0007 preparation remains measured; a real
transfer is still unapproved.

## Held-guard successor preparation — November 24, 2026

The developer resumed the full product after the earlier pause. Decision 0007
preparation is measured and the product remains incomplete. Start with
[NEXT_AGENT.md](NEXT_AGENT.md) and [HANDOFF.md](HANDOFF.md).

Scratch continuation tests and Python surrogates passed: 15 successor tests and
26 non-native offline-startup tests, Python 3.15.2 / SQLite 3.53.4. Ruff check
of those successor files passed. The production admission row is still
held/active=1. An unattached copy and read-only inventory are in
`.local/validation/held-successor-capture-01`. Guard stayed aborted/unlocked;
executor stayed poweroff/unlocked. The snapshot was not transferred. Evidence:
[held-successor-evidence.json](../research/validation/held-successor-evidence.json).

`NativeBindingTests` did not pass. On CPython 3.15 the normal binding case held
with `OperationalError: database is locked` inside controller qualification.
The product-web venv launcher also splits that test's process identity. The
87-test product checkpoint is unchanged. VBoxSVC pid 24848 remains from the
read-only inventory; no headless VM process remained. Real transfer and boot
still need an exact review. The promotion checkpoint above is the current
product result. P3–P6 remain.
No commit, push or release was made.

Current file-only check: `python .local/validation/verify-agent-handoff-02.py`.
Historical checkpoints below retain their original observations and limitations.

## Last implementation checkpoint — integration staging and regressions, November 24, 2026

The full goal remains active and incomplete. Schema 4 now persists integration
intent before private Git staging, exact stage packets and developer-approved
regression policies/operations/observations. Ref recovery is read-only; missing
effects hold without replay. Scope/parent/tree/authorization and source artifacts
are checked. Regressions bind the exact integrated subject and expected head;
conflicts and revoked authority hold. Candidate gates now also verify original
source artifacts.

**87 product tests passed**, no skips, with [retained evidence](implementation/product-integration-evidence.json)
and actual DB/Git/artifact staging/regression plus private merge/CAS controls.
Ruff/format, whitespace, integrity/FKs, Git fsck and both native journal hashes
pass. Process deaths after staging and a validation-ref update are covered.
Explicit migration from schemas 1–3 preserves held/pending records. No live
handle remains: full 91255 and focused 98712/98285 ended 0.

All check/review/regression outcomes are scripted. No candidate commands, VM
actions, provider calls, installation or publication ran. Milestone head stays
at baseline and T2 remains blocked. Fresh mandatory checks/review on distinct I,
live promotion and acceptance/release were still absent at this checkpoint.
A validation-only CAS is not milestone promotion. The diverged-head mapping
measured above came later and does not replace this retained 87-test bundle.

Scripted fresh checks/review and one promotion were measured after this
checkpoint. Decision 0007 preparation
is measured; a real transfer is still unapproved. [Handoff](HANDOFF.md),
[integration contract](product-integration.md). Real runtime/reviewer qualification,
browser QA and the old failed complete research cohort remain open. Older
checkpoints below are historical where superseded.

## Earlier checkpoint — candidate verification records, November 24, 2026

The full goal remains active and incomplete. Schema 3 now persists exact approved
check/review profiles, separate assigned producers, committed dispatch intents,
immutable results and applicability assessments. Missing coverage, stale/context
mismatches, artifact/ref changes and conflicting receipts cannot satisfy the
fresh candidate gate. Conflicts fence authority; late results remain held.
Implementation actor/context is recorded at dispatch; unknown legacy identities
cannot qualify independent review. Explicit migration supports v1/v2 with backup,
drift refusal and transactional rollback, preserving holds.

**70 product tests passed**, no skips. Retained [evidence](implementation/product-verification-evidence.json)
includes source/logs and a real product/Git/artifact policy/check/review smoke.
All observed check/reviewer outcomes are scripted; a green development gate still
has live eligibility and task acceptance false. T2 stays blocked. Ruff/format,
whitespace, integrity/FKs, Git object and native journal hash checks pass.
No live handle remains: full run 80477 and focused runs 4158/16074 ended 0.
No candidate commands, model calls, VM actions, installations or publication ran.

Next implement exact integration/regression and guarded promotion/acceptance;
prepare the already approved held-guard successor to advance native qualification.
Deployed producer authentication, actual reviewer quality, browser usability and
the old failed research full suite remain open. [Handoff](HANDOFF.md),
[verification protocol](product-verification.md). Older checkpoints below are historical.

## Earlier checkpoint — durable candidate intake, November 24, 2026

The full goal remains active and incomplete. Schema 2 now persists candidate
intake against exact approved attempt/source/authority bindings. Intent precedes
Git writes; recovery observes existing refs without replay. Frozen review packets
and late held observations survive restart. Pause/revision fence candidates.
The explicit offline v1→v2 migration archives first, refuses source drift and
rolls back failed DDL; restore/path rebinding remain open.

**53 product tests passed**, zero skips, with retained source/logs and actual
product-intake/Git/packet plus CLI-migration smoke. Ruff, formatting, whitespace,
integrity/FK and Git object checks pass. Both native journals are unchanged.
[Evidence](implementation/product-intake-evidence.json), [protocol](product-intake.md)
and [handoff](HANDOFF.md). No live task handle remains; full cohort exec 9279 ended 0.
No source code ran, no VM/provider action or new installation occurred, and no
task was accepted. The older research full-suite error and browser QA remain open.

Next add check/reviewer result admission and applicability, then guarded
promotion/acceptance; verify the browser UI when URL observation works. Existing
approvals persist. The following checkpoints are historical where superseded.

## Earlier checkpoint — web and trusted source intake, November 24, 2026

The full goal remains active and incomplete. Decisions 0007/0008 and the exact
web installation are approved. The local planning API/dashboard exists; all 19
installed packages, RECORD hashes and wheel hashes verify, `pip check` passes,
and base Python packages are unchanged. No browser usability pass is claimed:
URL observation failed and the temporary test server was terminated.

The P2 source foundation now constructs scoped, exact-byte candidates in managed
bare Git repositories and stores artifacts by SHA-256. One candidate per attempt,
direct private refs and deterministic reconstruction allow observed reconciliation
after a real child-process exit. It does not accept/promote tasks, release
dependents or prove qualified runtime stop. It is not yet wired to the ledger.

**38 product tests pass**, no skips, with Ruff/format/whitespace and Git object
checks passing. Retained [evidence](implementation/product-source-evidence.json)
includes source snapshots and an actual Git/artifact smoke. Both native journals
retain their original hashes. No VM mutation, provider traffic, new installation,
main-repository commit, remote write or release occurred in this increment.

Next connect durable candidate admission/current authority, independent check/
review packets and guarded acceptance; complete browser QA when URL observation
works. [The handoff](HANDOFF.md) records exact commands, approval limits and
terminal handles. The older research full suite remains failed at its startup
BEGIN BUSY case; product tests do not repair it. P1 migration/restore and all
P2–P6 full acceptance requirements remain open.

---

## Historical checkpoints (superseded where they describe current product state)


## Latest web checkpoint — November 24, 2026

Approved offline project-local installation completed: 19 hash-locked packages
in `.local/product-web-venv`, `pip check` passed. API/dashboard implementation
now exists with authenticated loopback sessions, CSRF/Host/Origin protection,
project creation/revision, plan approval and pause/resume/recovery. **26 core/web
tests passed**, zero skips; Ruff and formatting pass. No real execution/acceptance.
Starlette's HTTPX test-client deprecation warning remains visible.

Browser QA could not run: Computer Use stopped because it could not confidently
determine the browser URL. Temporary test server cleanup is recorded in the
[handoff](HANDOFF.md). Installed-file evidence, a retained web test/source cohort,
broader doc reconciliation and actual browser QA remain next. No native action,
provider call or remote write occurred. Full goal stays active and incomplete.
The following earlier core checkpoint is historical where it says no installation
or HTTP/dashboard exists.

Updated November 24, 2026. The active goal remains the full project, including the
vision's lifecycle requirements; this checkpoint is not completion. The developer
approved same-boot session preparation, disconnected guard creation, broker
phase-ceiling preparation, both stopped-only maintenance profiles and direct
frontend preparation and initial-Aborted recovery preparation in this conversation.
The work remains within those
separate scopes. The branch remains
`research/m1-11-executor-recovery`; HEAD is now checkpoint `e609dbc` (observed
during this work; the agent did not create it). No agent commit, push or release
was requested. See the [requirement-by-requirement completion audit](completion-audit.md).

## Current handoff: first product core and CLI implemented

The resumed goal is active. The new `coordinator/` package now implements
versioned project/context/requirements, validated dependency plans and exact
approvals, durable attempt/operation admission, pause/fencing and uncertain-result
recovery. Only explicit scripted development operations are enabled. It does not
execute checks or coding tasks, accept/integrate revisions or contact providers.

**15 product tests passed** under existing Python 3.15.2 / SQLite 3.53.4.
A retained **21-process CLI smoke** exercised approval/refusal, held delivery,
recovery, stale-result denial, a fresh attempt, a simulated candidate, continued
dependency blocking and archive backup. Integrity, lint, formatting and whitespace
checks pass. Both actual VM-related journals are byte-identical. See
[P1 core evidence](implementation/p1-core-evidence-02.json), [CLI usage](product-cli.md)
and [current handoff](HANDOFF.md). No installation or native action ran.

P1's API/dashboard and P2-P6 remain open; all product requirements remain
incomplete at their full acceptance scope. The older failed complete research
cohort is not reclassified by these passing product tests. Next prepare the exact
HTTP/UI dependency lock and install review; trusted P2 Git/evidence work can
proceed using scratch repositories while that review is pending.

## Prior handoff: approval before product code

The developer approved **Decisions 0007 and 0008** with “I approve the decisions.”
See the [approval record](decisions/0007-0008-approval.json). Do not request those
approvals again. Product implementation may proceed alongside native research;
guard-successor preparation may use scratch/Python tests and read-only/unattached
capture. Actual reservation transfers, native actions, dependency installation,
provider-data/paid experiments, remote writes and publication remain separate.

The developer requested a handoff before more implementation because of their
weekly token allowance. **No product source has been written:** `coordinator/`
and `integrations/` remain empty. Start the next agent at [HANDOFF.md](HANDOFF.md),
then implement P1's durable project/plan/approval/attempt domain and CLI, with
scratch-store recovery/dependency/fencing tests under existing Python 3.15.2.
The [full delivery plan](product-delivery-plan.md) still covers all R1-R9.

No live task handle remains. Latest native guard outcome and failed full
regression below remain unchanged. The old goal API still reports blocked; a
requested restart was refused because the goal is unfinished. The handoff contains
replacement goal text. No false completion or new native action was used to reset it.

## Historical proposal checkpoint — superseded by approval above

At this checkpoint two concrete proposals were ready but not yet approved:

- [Decision 0008](decisions/0008-product-implementation-boundary.md) proposes a
  Python/SQLite coordinator, CLI/API/dashboard, read-only planning import and
  qualified executor/model adapters. The [delivery plan](product-delivery-plan.md)
  covers all R1-R9. Approval would allow product implementation alongside native
  research; live execution and final acceptance still require the open gates.
- [Decision 0007](decisions/0007-held-guard-successor.md) proposes guard-only
  recovery preparation with complete new provenance and an explicitly reviewed
  future reservation transfer. The old stop stays held. Preparation would use
  scratch ledgers, Python surrogates and read-only/unattached capture only.

New storage review measured Python 3.13.17 / SQLite 3.50.4, WAL mode and passing
read-only integrity checks on both current journals. The installed build is
within SQLite's documented WAL-reset affected range. No corruption or connection
to earlier lock errors is established. A verified patched runtime is required
before further native admission writes or product persistence qualification;
no installation or journal mutation ran. See the
[storage plan](../research/validation/coordinator-storage-plan.md) and
[proposal evidence](../research/validation/product-progression-evidence.json).

Further inventory found preinstalled Python 3.15.2 / SQLite 3.53.4 with the
official release source ID. Its complete candidate regression is **not green**:
609 tests, 594 passed, 14 skipped and one startup-BEGIN BUSY hold. Five initial
fixture failures were traced to historical replay metadata reading the changed
real guard configuration; only the test fixture was corrected and a drift
negative case added. Six focused binder cases passed, but the subsequent full
cohort's controller-loss case held before resume. No production code, bound,
retry policy, native grant or real ledger changed. Preserve that failure and
keep runtime compatibility unqualified. See
[candidate evidence](../research/validation/patched-runtime-evidence.json).

The [controlled startup-entry check](../research/validation/startup-entry-lock-evidence.json)
now reproduces that pre-resume BUSY branch using a real competing SQLite
connection. Four focused diagnostics pass: no frontend resume, no transaction
entry/replay, authority fenced and lease clocks unchanged. Family/VM facts are
synthetic; the earlier competing writer is still unknown. No production policy
or held journal changed. The last complete regression remains failed; the
current tree collects 610 tests and has no new complete passing cohort.

The full goal remains active. Existing preparation approvals do not authorize
the new reservation semantics or product implementation/order change. Native
activation, installation, provider-data/paid experiments and publication keep
their separate concrete approval scopes.

## Latest native checkpoint: joined controller loss contained; original stop held

The developer separately approved exact inert review
`0925de6acf1a400301d84abf1177a0596f811ff142597e3e74ddc52c4f13a788`.
Its one-use activation completed one disconnected guard boot, committed the
session binding to PID 33132 and accepted two Running observations. The controller
then exited 29 at the approved fault barrier. Its kill-on-close job emptied;
two independent Aborted/unlocked/PID-zero observations completed within **2.668
seconds** of fault intent. All original and retained process identities retired.

The original owner's sole stop exited 1 (`not currently running`), leaving
`possible-send` with no command receipt. **Containment is measured; successful
shutdown is not accepted.** The consumed admission remains `held`, with its
target reservation active. No retry, replacement owner, restore or release ran.
Both disks, guard NVRAM and all executor files are unchanged. Only guard
abort/time metadata changed; executor remains poweroff and all NICs are disabled.
See [native evidence](../research/validation/guard-controller-loss-evidence.json).

Next prepare explicit recovery provenance and held-reservation settlement
semantics for review before another native run. Ordinary admission refuses the
current Aborted guard; existing recovery context does not bind this new run.
Do not reuse stopped-refresh-03 as the current profile or clear the ledger.
Startup-loss/late/detached cases, guest readiness and the product remain open.

## Implemented offline-review preparation used by this run

The developer approved decision 0006 preparation. The
[offline-review implementation](../research/validation/offline-approval-plan.md)
now creates an inert action/input artifact before any process or lease. Explicit
activation consumes it once, verifies/locks inputs in an unarmed worker, then
constructs the original owner and immutable at-most-600-second lease. Actual
process identities/clocks bind before native resume. Drift, replay and revocation
refuse; unknown results remain held without another owner or command.

Full regression passed **608 tests: 595 passed, 13 platform skips**, no
failures/errors or source drift; Ruff passes. Five Windows Python cases cover
normal finish, controller loss, revocation before/after arming and lost owner
acknowledgement. Startup error tracing adds no retry; the controller-loss proof's
owner-packet field was corrected and checked against the actual Python packet.
Those VM facts remain synthetic.

Actual read-only preflight verified nine protected files and both stopped,
unlocked, disconnected VMs. The controller-loss artifact is
`.local/validation/offline-guard-review-01/review.json`, SHA-256
`0925de6acf1a400301d84abf1177a0596f811ff142597e3e74ddc52c4f13a788`.
That preparation record predates approval and consumption. Human review allocated
no process or lease; native activation and its held result are recorded above.
See [preparation evidence](../research/validation/offline-approval-evidence.json).

## Historical timing problem and approval decision

The prepared controller-loss review
`c43c796cdb66927682e62d22df0618de2c4a70738f146d15da08f38782abf41f`
expired without exact approval. Its three suspended process identities are
independently retired; no VM start or stop ran. All live reviews are closed.
No automatic replacement lease or native run is authorized.

The [developer workflow assessment](developer-experience-walkthrough.md) now
records current developer actions, visible evidence and the remaining product
gaps for M1-14. It also records five named unarmed review expiries. Fresh GitHub
read-only inventory confirms #11–#14 remain open and PR #25 remains unmerged;
no remote changes were made. [Retained evidence](../research/validation/feasibility-walkthrough-evidence.json).

[Decision 0006](decisions/0006-review-before-native-lease.md) approved preparation of
an inert exact initial-review artifact before constructing the one-use native
process session. The maximum 600-second lease and all armed stop/deadline rules
stay fixed; running-guest maintenance review still consumes that original lease.
It changes approval from advance live-PID/absolute-time review to a source/input/
action policy plus independently verified process binding. Preparation is now
verified above; native activation remains separate.
The full project and its architecture/implementation decision remain incomplete.

## Historical preparation: joined controller loss

The [controller-loss preparation](../research/validation/controller-loss-plan.md)
now has a distinct exact review/fault policy. Only after two accepted joined
running samples and fresh authority checks can it deliberately exit the
controller without cleanup. The existing Windows job contains the family; the
same original owner retains its single stop. The independent proof is limited
to fault/fence/process containment and bounded inactive-session observations.
Aborted or a nonzero/unknown stop remains held; this case cannot claim normal
stop acceptance or grant restart authority.

Full regression passed **574 tests: 561 passed, 13 platform skips**, no
failures/errors or source drift; Ruff passes. Actual Windows Python controller
loss, empty job, retired family and one original-owner surrogate stop passed.
Fresh stopped capture 03/backup guard 02 includes the guard's current NVRAM;
separate-process readback 01 and read-only preflight 01 passed. Both VMs remain
off/unlocked/disconnected, with executor files preserved. No new VM activation
or setting change ran during this preparation. Retained partial captures and the
sandbox-only PowerShell launch failures are recorded in
[evidence](../research/validation/controller-loss-preparation-evidence.json).
The first exact live review expired unarmed as recorded above. The later inert
review was separately approved and consumed; its narrower native containment
result is now recorded at the top. Other loss/failure cases and the product
remain unqualified.

## Historical review 10: normal startup/session/stop measured

Review 10, `027b509dfcbe0d710f5bdf0a63334b0668a351b6dd0e3907f8caf79e4996967b`,
received timely exact approval and completed one disconnected guard boot from
Aborted. The durable session binding matched frontend PID 10204; two running
samples were accepted. Both controller journal transactions committed once,
with the binding commit preceding receipt publication. No SQLite BUSY occurred
in this native run; controlled contention coverage remains separate.

The original owner's sole stop exited 0. All four retained frontend/helper
processes exited naturally with code 0, the job/pipes emptied, and independent
poweroff/unlocked/PID-zero observations completed in **2.597 seconds** from the
stop request. All original process identities independently retired. Both VMs
were then poweroff/unlocked with all NICs disabled. Both disks and all executor
files are unchanged. The authorized guard boot created 540,672-byte NVRAM and
updated only its abort/time configuration metadata; hardware payload is unchanged.
See [normal-case evidence](../research/validation/guard-startup-normal-stop-evidence.json).

Reviews 08 and 09 closed unarmed with zero VM starts/stops; their closure evidence
is linked from that result. No review, lease or further VM authority remains.
Capture 06 predates the guard's new NVRAM/poweroff metadata and cannot be reused
as the current profile. Earlier failed stops remain held. This success qualifies
only the normal guard startup/session/stop case: native failure cases, guest
readiness/UART ownership, installation/hardening, isolation, executor recovery and
the product remain open. Next prepare a scoped failure-case plan and refreshed
stopped inputs before requesting any further native activation. That preparation
is now recorded above; it supplies no native activation authority.

## Controller journal correction and recovery inputs used by review 10

The [journal preparation](../research/validation/controller-journal-plan.md) now
reproduces real writer contention and permits only bounded waiting for confirmed
BEGIN non-entry. Transaction bodies/COMMIT and native commands are never
replayed. Original authority and all clocks remain in force. A committed binding
now precedes receipt publication and accepting the in-memory join; uncertain
commit/publication remains held. Future bounded traces retain the failure phase
and SQLite code; the consumed run's missing exact statement is not reconstructed.

Final regression: **556 tests, 543 passed, 13 platform skips**, no failures/errors;
Ruff passes. A real Windows controller/original owner/Python family and an
independent SQLite writer committed one join and one original-owner surrogate
stop. New context V3 requires recovery-history reviews 04/05/07, every retained
creation, the unaccepted orphan receipt and current guard metadata.

Actual capture 05 timed out on its initial read-only query before copying and is
retained incomplete. A follow-up observation passed; cause remains unisolated.
Fresh unattached capture 06, independent readback 03 and read-only preflight 04
passed, with guard aborted/unlocked and executor off/unlocked. No new VM
activation or settings change ran during this preparation. See
[current evidence](../research/validation/controller-journal-evidence.json).
Those inputs were subsequently consumed by the separately approved review 10
above. No consumed native session is reusable.

## Historical review 07: Running observed, session journal held

The developer approved exact review
`fba9d14f0b7cadd70786674b730b34c8375fbba60c1d9b4886d725b9df86d77f`
in time. One native guard boot reached `Running`. A stable COM bracket reported
`Locked`/`Locked`, machine state Running and PID 4424, matching the exact retained
frontend creation identity. Startup used COM-only waiting before the full CLI
profile read; all NICs remained disabled.

Recording the join then raised `OperationalError: database is locked`. The
filesystem session receipt exists, but SQLite remains `resumed` with a null
receipt hash: the binding did not commit and **zero running samples were accepted**.
The exact failing transaction statement/competing writer was not retained. The
receipt is provisional evidence, not accepted session authority or guest readiness.

Containment forcibly reaped the family (root exit 2, empty job). One leaf's exit
code was still unavailable at initial cleanup; independent later creation-identity
checks prove all retained family and original processes retired. The original
owner issued its sole stop; it exited 1 (`not currently running`) and remains
`possible-send`, with no accepted command receipt. No command was retried.

Fresh final inventory shows guard **aborted/unlocked/PID-zero** and executor
**poweroff/unlocked/PID-zero**. Both disks are unchanged. Executor configuration
and NVRAM are unchanged; guard NVRAM is absent. Only guard configuration timestamp
metadata changed, to SHA-256
`91c25dbe0e2281892a1cceeef07abc9c8a80d1595b12f1c7e403c1d2edbe17aa`.
Hardware payload is unchanged. See [native journal-hold evidence](../research/validation/guard-startup-journal-hold-evidence.json).

The prepared correction is described above. Capture 04/context V2 now
predate this consumed run and changed guard metadata, so they cannot admit a
successor. A new recovery context/backup/profile must bind this run first.
No live review or new native authorization remains.

## COM-only startup correction and successor inputs verified

Startup waiting now uses bounded COM property reads that request no VM session
lock. Only a stable locked starting/running state with the exact live pinned
frontend PID permits a full CLI profile observation. The probe cannot join or
count as a running sample; all full profile/storage checks, original authority,
forward-only progress and deadlines remain required. Post-join observation and
normal stop acceptance are unchanged.

Context V2 additionally binds consumed review 05, its failed stop, all retained
family identities and unchanged post-run files to the historical context used
in that review. Both consumed attempts are freshly reconciled. Context V1 remains
retained history and cannot be reused or relabeled for admission.

Final combined regression: **533 tests, 520 passed, 13 platform skips**, no
failures/errors; Ruff passes. Actual COM-only probes used zero CLI queries and
observed guard aborted/unlocked/PID-zero and executor poweroff/unlocked/PID-zero.
Fresh unattached capture 04, separate-process readback 02 and read-only preflight
03 passed. No new VM start/stop or setting edit occurred in this correction.
See [current evidence](../research/validation/startup-session-probe-evidence.json).
Next prepare a fresh exact recovery review using capture 04; native activation
still requires separate timely approval. Review 06 received no timely approval
and expired unarmed: zero VM starts/stops, with all three original process
identities independently retired. See [closure evidence](../research/validation/guard-startup-probe-review-expiry-evidence.json).
The developer has returned; a fresh exact review may be prepared, but the expired
review, lease and process identities cannot be reused.

## Latest approved recovery run held at the session lock

The developer approved exact review
`680a7aa23fe6efcd1db67344d1271e4e32b71e08f62e47736cbe8e8712dbefd0`
within its original lease. One native frontend root was created/resumed from the
explicit initial-Aborted grant. VirtualBox exited 1 at `LockMachine`, reporting
the guard already locked for a session. No running sample qualified. The
watchdog recorded root exit before original-stop acceptance; the controller's
later `frontend is retired` is a secondary symptom. The sole original-owner stop
also exited 1 (`not currently running`), leaving `possible-send` and no accepted
command receipt. This review and stop are consumed; no retry ran.

Independent inspection proves the bootstrap, controller, owner and all retained
frontend/helper identities retired; the frontend job is empty. Fresh inventory
shows guard **aborted/unlocked/PID-zero**, executor **poweroff/unlocked/PID-zero**,
with disabled NICs. Both disks, both configurations and executor NVRAM exactly
match their pre-run hashes; guard NVRAM remains absent. No new guest log was
created. See [native lock-hold evidence](../research/validation/guard-startup-lock-hold-evidence.json).

Oracle's reviewed `showvminfo` implementation takes a shared session lock, while
the direct frontend needs a VM lock before power-up. Startup status polling
therefore supplies a concrete possible competing lock. Exact installed lock
ownership/timing is not measured, so this remains a source-supported hypothesis.
The prepared correction and mandatory successor provenance are described above.
Further native activation needs its own exact review/approval.

## Initial-Aborted preparation verified

Approved [decision 0005](decisions/0005-initial-aborted-recovery.md) now has an
[implementation and capture plan](../research/validation/initial-aborted-plan.md).
Typed version-3 backup/context/profile records, fixed-prior process reconciliation,
read-only capture, distinct frontend/review formats and initial-Aborted progress
are implemented. Ordinary admission stays poweroff-only; normal stop proof still
rejects aborted state. The later separately approved native attempt is recorded above.

Focused schema, real scratch-copy, negative admission and Windows Python-family
checks pass. The latter uses a real controller job and original owner with only
Python frontends/stops and synthetic VM facts. Latest regression: **516 tests,
503 passed, 13 platform skips**, no failures/errors; Ruff passes. An earlier
cohort's two process-exit lookup races remain recorded as failed checks. Normal
finish now uses retained handles for previously validated family identities;
unknown/new members and nonzero frontend exit still hold. Final independent stop
acceptance also checks retained frontend exit codes after cleanup; its negative
control and final source cohort are in [exit-proof evidence](../research/validation/frontend-final-exit-evidence.json).

Actual capture 03 completed with a new independent unattached disk/configuration
backup and explicit absent NVRAM. Separate-process readback rehashed that backup
and both VMs' current files. Fresh observations confirm guard aborted/unlocked,
executor poweroff/unlocked and PID zero; read-only recovery preflight passed.
No VM was started/stopped or configured during that preparation. See
[recovery preparation evidence](../research/validation/initial-aborted-evidence.json).
Its later exact native review was approved and is now consumed as described
above. No earlier review, recovery grant or stop can be replayed.

## Latest native parser hold and approved recovery preparation

After the developer returned, exact fresh review
`98fa65d7365578352207992992a1d25ab8cf37dbf918d17e5f75aefd5c53ae6e`
was approved. It resumed one guard frontend and reached `Starting` in the native
log, but no running session sample passed. Installed CLI diagnostics caused a
parser hold while COM reported `Spawning`; containment terminated the family.
The original owner's sole stop exited 1 (`not currently running`), with its job
reaped. The journal remains `possible-send` with no successful command receipt.
This review is consumed and no command is replayed.

The guard now reports **aborted/unlocked**, with all eight NICs disabled. The
executor is **poweroff/unlocked**. All original Python identities and the frontend
root are independently retired; the frontend job was empty. Both disks retain
their original hashes. Guard NVRAM remains absent. Only guard abort/time metadata
changed; its hardware payload and executor configuration/NVRAM are unchanged.
See [native parser-hold evidence](../research/validation/guard-startup-parser-hold-evidence.json).

The parser now recognizes only the observed bounded `VideoMode` composite and
`VRDEClients==0` numeric grammar. Exact retained-byte replay produces a wait-only
spawning frame. Retirement also retains bounded console bytes after containment
and fencing, with lengths/hashes checked against cleanup evidence; publication
failure holds. Final regression: **471 tests, 458 passed, 13 platform skips**,
no failures/errors; Ruff passes. Six added checks and the actual Python output
overflow case are retained in [repair evidence](../research/validation/runtime-parser-evidence.json).
Historical source descriptors resolve to byte-identical retained snapshots;
cross-linked earlier summaries and measured results have not been rewritten.

The developer approved [decision 0005 preparation](decisions/0005-initial-aborted-recovery.md):
an explicit guard-only initial-Aborted recovery context, new versioned backup and
current profile, and unchanged strict normal-stop acceptance. Implement and test
that model next, then measure its read-only backup/profile capture. Current
poweroff-only admission stays closed. Any further native activation needs its own
exact live review; no live native process remains. The full product is incomplete.

The preboot interval enclosing disk hashes was 266.97 seconds in this run;
independent posthold file measurement took 3.06 seconds. These measured durations
do not isolate a cache/storage/scheduling cause or establish a worst-case I/O
bound. The original lease and admission limits were not extended.

## Previous unarmed review closure

Fresh review `7580226fe0d7a9e75c702a57e68c69966e5c8f3a4f3328fd8b0423cdedf1118a`
received no approval before its original reserve deadline and closed unarmed.
The retained exec handle returned exit 0. Independent Windows creation-identity
checks prove its bootstrap, controller and suspended owner retired. No approval,
owner activation, sealed/ready owner, controller input or frontend intent exists;
the journal has no frontend-start or native-stop table. **Zero VM boots and zero
native stop commands occurred.** See [unarmed-review evidence](../research/validation/guard-startup-unarmed-review-evidence.json).

This is not a third native qualification attempt. The original two native reviews
remain consumed, and this expired review/lease cannot be activated by a late
answer. No live review or process remains. Wait for the developer's decision
before preparing another exact live review; automatic goal continuation is not
approval. Native startup/stop and the product lifecycle remain incomplete.

## Forward startup observation preparation

Initial collection now treats only known forward machine/session progress as
wait-only. The adapter checks the exact granted profile/storage and live family,
rejects regression within or between frames, and requires a stable locked
session-PID join before counting either running sample. Waits cannot publish a
session receipt, authorize guest work or reset a deadline. Default preactivation,
post-join and independent stop observations remain strict.

Final regression: **465 tests, 452 passed, 13 platform skips**, no failures or
errors; Ruff and whitespace checks pass. Eight added checks cover forward waits,
drift/backward states, unchanged authority, cross-frame regression and sample
counting. Actual read-only preflight passed for both stopped/unlocked VMs with no
native start or stop. Exact sources, logs and observations are retained in
[startup progress evidence](../research/validation/startup-progress-evidence.json).
An earlier Python normal-finish check hit a conservative process-exit identity
hold; the full final run passed. Ambiguous exits still hold without acceptance.

Both prior native reviews remain consumed. This preparation is not a diagnosis
of their failures. The resulting fresh review later closed unarmed as recorded
above. Native running/stop qualification and the full product remain open.

## Previous native successor hold and owner contention repair

The developer approved successor review
`72f98453006968770162d719590e5c3ce0972db3412c780332c80b8c2bb8978f`.
Its read-only preactivation passed and one native frontend was created/resumed.
The watchdog contained the family before any running session sample passed. Both
VMs were independently off afterward and all disk/configuration/NVRAM hashes
remained unchanged. The owner process had exited without a terminal record; its
lease stayed armed/watching and no native stop intent was entered. That session
is consumed, not resumed or replayed. See [successor hold evidence](../research/validation/guard-startup-successor-hold-evidence.json).

A controlled 0.4-second temporary SQLite writer lock reproduced owner exit 1
without a terminal or stop. The original native exception was not retained, so
the controlled reproduction does not establish its exact cause. The repaired
owner tolerates SQLite BUSY only while the same lease is armed, no stop has begun
and rollback is confirmed. Waiting is capped at one second and both original
expiry clocks, rechecked after sleeping. A stopping/possible-send command is never
retried. Persistent contention now retains a held terminal even if fencing fails;
terminal files deny admission immediately. Family identity failures identify the
PID, and the bootstrap briefly observes the existing owner on exit without
issuing any replacement command or accepting an unknown stop.

Final regression: **457 tests, 444 passed, 13 platform skips**, no failures or
errors; Ruff passes. Twelve added checks include actual short/persistent writer
locks with Python-only stops, expiry during a wait, non-replay after stop intent,
terminal admission refusal and bootstrap observation. A fresh actual read-only
preflight passed for both off/unlocked VMs under the repaired source cohort.
Sources, logs and artifacts are retained in [owner contention evidence](../research/validation/owner-contention-evidence.json).

No running native startup/session/stop case is qualified yet. Both prior sessions
stay closed. A further native attempt requires a fresh exact live review under
the repaired source/policy cohort. Product implementation and the full lifecycle
goal remain open.

Before that review, expected forward startup observations were inspected. Source review
of `NativeObserver.__call__` shows its strict first/final profile comparison also
requires an unchanged VM state; the session reader similarly requires stable
states. That is appropriate for preactivation/final acceptance, but may reject a
legitimate `poweroff`/`starting`/`running` transition during initial collection.
A separate startup observation now marks known forward progress as wait-only.
The adapter checks the original profile/storage/family and rejects regression
within or between frames. Waits publish no session receipt and do not count toward
the two running samples; a stable locked session-PID join remains required.
Unknown or backward states, target/profile drift and query failures still hold.
The original lease and startup/sample deadlines are unchanged; collection checks
the sample deadline again after each observation. Default preactivation and final
acceptance remain strict. The later source cohort is verified above.
This is a source finding, not an established cause of either consumed native hold.

## Previous preactivation correction

The runner now checks its pinned image/environment, exact receipts, current
configuration and stopped/unlocked VM sessions before activating the original
owner. It retains raw observations, rechecks freshness, sources, approval and the
unchanged original lease, then journals possible activation. An earlier hold leaves
both native start and stop paths unarmed. The new `preflight` CLI creates no
owner/controller and has no VM mutation operation.

Actual standalone preflight passed for both stopped VMs. The full ordered path
also passed in Windows jobs with a suspended controller, a Python-only stop owner
and real backup/current-file locks. Preflight/owner activation took 1.34 seconds;
input locking/hashing took 4.63 seconds in that run. These are measured durations,
not worst-case bounds or a diagnosis of the first timeout. The old native stop PID
and VBoxManage/VBoxHeadless client names were independently absent outside the
sandbox; the missing original acknowledgement stays held.

Final regression: **445 tests, 432 passed, 13 platform skips**, no failures or
errors; Ruff passes. Nine new checks include timeout, drift, source-change and
read-only CLI cases, plus actual suspended-owner nonactivation. Sources, logs and
native read-only/surrogate artifacts are retained in
[preactivation evidence](../research/validation/preactivation-evidence.json).

Next prepare a fresh live review for the corrected source/policy cohort and seek
its exact one-boot decision. The consumed first session below is never resumed,
renewed or replayed. Native running/start/stop qualification, guest readiness,
hardening/isolation and the complete product lifecycle remain open.

## Previous approved qualification attempt: held before start

The developer approved the exact one-boot guard review SHA-256
`fc14c0ca697b09726c3fcdc84ed78810e876fce6f7e9997305a0a733cdef54db`.
That session is now terminal and must never be resumed or replayed. Its first
bounded read-only VBoxManage query timed out after original-owner readiness,
before `controller.input.json`, a start/resume intent or a frontend journal existed.
Authoritative retained state proves **zero boots and zero frontends created**.

The original owner entered its single stop path during cleanup. Its native journal
is `possible-send` with no successful command receipt; the result remains unknown
and unaccepted. No replacement command ran. Independent later queries report both
VMs powered off with unlocked sessions/PID zero. Full disk, configuration and NVRAM
measurements match every earlier value; the guard firmware file is still absent.
Windows creation-identity checks prove the bootstrap, controller and owner retired.
See [the held-run evidence](../research/validation/guard-startup-hold-evidence.json).

The read-only context diagnostic also passed: 0.39 seconds before the Python-only
owner and 0.38 seconds while that independent owner watched a suspended controller
in the actual twelve-process job. Every diagnostic stop was a Python surrogate.
Owner/job presence alone did not reproduce the timeout. Actual backup/current-file
hashing and locks separately took 4.74 seconds; this is not a worst-case bound.
Service warm-up, process context and I/O effects remain unisolated; no cause is
established. Next put fixed read-only preflight ahead of native owner activation
and prove an early hold issues no native stop, before any successor exact review.
Running native startup/stop and the full product remain open.

## Native observer and qualification preparation checkpoint

The [fixed native session observer](../research/validation/native-session-plan.md)
now reports both actual VMs powered off, with `Unlocked` sessions and PID zero.
The guard's bounded four-query sequence took 1.30 seconds; the executor's took
1.17 seconds. All successful query jobs were reaped. The first sandbox query held
on timeout; the same read-only observer succeeded outside the sandbox. No VM was
booted or changed.

The startup adapter now supports a bounded owner-first normal finish after a
verified runtime join. It requests the original owner's single poweroff, retains
containment for at most four seconds and requires natural family exit. Startup
uncertainty still triggers immediate retirement. A lost original acknowledgement
stays held. Runtime source pins now include the entire qualification controller.

The [one-boot guard qualification](../research/validation/startup-qualification-plan.md)
has a concrete preparation/approval/controller/independent-proof path. Preparation
creates suspended Python processes and a complete live review only. No native
start is allowed without matching separate approval within the original lease.
Boot may write guard disk/configuration/NVRAM; guest commands, installation,
networking, retries, restores and additional boots are outside this proposed run.

Final regression: **436 tests, 423 passed, 13 platform skips**, no failures or
errors; Ruff passes. The 55 focused checks include actual Windows owner/jobs and
Python frontend/stop surrogates, with synthetic VM/session facts. Source snapshots,
logs, native stopped observations and successor policy inputs are retained in
[qualification evidence](../research/validation/native-qualification-evidence.json).
Unarmed static inputs are `.local/validation/native-qualification-inputs-01`,
inventory SHA-256 `b2cb04bb271aad1562a16a93c82b00a865e435f4759463f3a13dbe4fc960bb80`.

The exact review was subsequently approved and held before start, as recorded
above. Actual startup/session/stop behavior and later
native failure cases, guest readiness, UART, hardening/isolation and the complete
product lifecycle remain open.

## Previous original-owner startup preparation

The [owner-bound frontend adapter](../research/validation/frontend-start-plan.md)
now binds the original owner/ready proof, immutable Store/lease, current stopped
profile, actual backup/current-file bytes, executable/environment and source cohort.
Exclusive filesystem/SQLite intents precede its one possible resume. A separate
watchdog checks authority, job/family/output state and the original stop reserve.
Runtime session-PID matching produces no guest-readiness or dispatch permission.

All **28 focused startup checks pass**. Seven exercise the actual Windows
controller/job and independent owner with Python frontend/stop surrogates; four
exercise real file-sharing locks with synthetic disk bytes. Lost resume or
original-stop acknowledgement, controller death, revocation, output overflow,
stale runtime evidence and replay remain held. No VirtualBox frontend or VM ran.
Final regression: **409 tests, 396 passed, 13 platform skips**, no failures or
errors; Ruff and whitespace checks pass. Exact sources, logs, process/file-lock
artifacts and the initial input-drift failure are retained in
[startup evidence](../research/validation/frontend-start-evidence.json). Current
unarmed successor inputs are `.local/validation/startup-input-review-02`, inventory
SHA-256 `bb4eced4dd6fda41487730073e211dadc6f69d11d4dd216e82a2593754daf914`.
Earlier cohorts below retain their execution-time results and source snapshots.

Next prepare a fixed bounded native session observer and the exact controller/owner
qualification run for separate review. The installed frontend's descendants,
session join, late/detached startup and stop/retirement timing remain unqualified.
The conservative retirement path can race the sole original poweroff command;
cleanup cannot turn a raced or unknown result into acceptance. Guest readiness,
UART/root-session collection, hardening and the product lifecycle remain open.

## Previous backup/profile/process checkpoint

The two preparation VMs now have [verified unattached file backups](../research/validation/stopped-backup-plan.md).
Each original 2,625,634,304-byte VDI was copied under Windows read-sharing locks,
read back, and independently rehashed alongside its original. The guard's NVRAM
absence is explicit; the executor's existing firmware file is hash-bound. Version-2
backup bindings are opt-in, retaining old version-1 packet semantics. Backup
images retain their original UUIDs and must never be attached or registered.

The developer-approved [stopped profile changes](../research/validation/maintenance-profile-plan.md)
were applied and independently reobserved. Both VMs remain powered off with eight
disabled NICs, four SATA ports and their fixed UART server settings. Both now have
x2APIC off/APIC on. Disk hashes and NVRAM state are unchanged. Current guard
configuration SHA-256 is `986cf055dec3732488666adfe7e8715965faac421c9dc9c651eecb411f5c4f7e`;
executor configuration is `5dfe5bc297f585a934bb2090797c365fafcfbd4bb7cbe785c8916f1da7ccf4f2`.
The backups intentionally retain the earlier configurations. No VM boot, guest
command, package install or network activation occurred.

[Decision 0004](decisions/0004-startup-process-ownership.md) approves direct
frontend/job preparation. Source review exposed Windows hardening respawns, and
native Python tests exposed console-helper processes. The new private
[frontend-family primitive](../research/validation/frontend-process-plan.md) accounts
for at most three frontend images plus three pinned console helpers, under a
twelve-process outer controller job. Eight native scratch checks pass, including
the actual nested controller/family/query arrangement, abrupt parent loss and full
family cleanup. No VirtualBox frontend was launched. This primitive still needs
the actual original-owner/lease/start-grant adapter and runtime session-PID join.

Final regression: **381 tests, 368 passed, 13 platform skips**; Ruff passes. New
source snapshots, logs, native backup/profile receipts and process artifacts are
hash-indexed in [backup evidence](../research/validation/stopped-backup-evidence.json),
[profile evidence](../research/validation/maintenance-profile-evidence.json) and
[frontend evidence](../research/validation/frontend-process-evidence.json).
Current unarmed input context is `.local/validation/startup-input-review-01`;
earlier packets and summaries retain their historical source cohorts.

The later adapter checkpoint above implements this cohort's planned integration
with Python surrogates. The older `.local/validation/startup-input-review-01`
packets retain their historical sources and remain unarmed. Product implementation
and the complete lifecycle goal remain open.

### Previous session and broker checkpoint

The [same-boot session](../research/validation/maintenance-session-plan.md) now
retains inspection and an exact action list for review, denies guest dispatch
while waiting, and admits controls under the original immutable lease. Each phase
has separate durable operation IDs. Expiry/revocation/journal/replay cases pass;
a native original-owner test confirms one surrogate stop after an unanswered
review. Host collection and final stop observation understand the session ledger.
The [boot preconditions](../research/validation/boot-preconditions-plan.md) bind
live readiness, jobs, original Store and stopped configuration but deliberately
issue no native-start permission. Actual startup integration/settlement remains
the next control-path gap.

The [guard creation](../research/validation/guard-preparation-plan.md) completed
under exact plan digest `d9b76875fa1892d015f109fe15f2584620d01d2f729451848221805713dcba85`.
`mcli1-guard-01` is powered off with eight disabled NICs; disk UUID is
`a8f47315-d330-4b28-bbb0-6a721b4c6251`, hash
`a8a6024499644999738f089546096e93174a336c003f2d1ae841214c2fe22c43`.
Independent bounded queries and both full disk hashes passed; the executor source
remains unchanged at `2eb1d9cd009ecfe83381d855137f5cee8c1317739f6209beddd6da8a10955a09`.
The guard has one SATA port and no first-boot NVRAM file. Maintenance admission
requires a reviewed four-port/UART configuration and a genuine backup record that
represents absent NVRAM correctly. No boot, guest command, installation or network
activation occurred in this checkpoint.

The [broker ceiling](../research/validation/broker-ceiling-plan.md) is now an
explicit approved preparation mode with raw/effective hash/count bindings and
unchanged token/money caps. Strict rejection and its old binding digest remain
the default. All four retained native prepared bodies match their effective
counterparts through the integrated admission path; response counts in this new
comparison are synthetic, not qualified measurements.

Final regression: **352 tests, 339 passed, 13 platform skips**, with no failures or
errors; Ruff passes. Full logs, source snapshots and native-process receipts are
hash-indexed in [session evidence](../research/validation/maintenance-session-evidence.json),
[guard evidence](../research/validation/guard-provisioning-evidence.json) and
[broker evidence](../research/validation/broker-ceiling-evidence.json). Earlier
packets and measurements remain intact, with historical source cohorts; none is
armed by these approvals. Product implementation, native target/session/start/stop
qualification and M1-11 through M1-14 remain open.

Next, prepare the exact stopped target configuration, genuine backup/absence
receipts and bounded startup path with late/unanswered-start handling. Obtain its
separate native approval only after those controls are concrete. Then qualify
readiness, offline hardening, external filtering/gateway and executor behavior in
the established prerequisite order. The two design-preparation decisions and
disconnected guard creation no longer await a decision.

### Earlier preparation checkpoints

The [independent original-owner checkpoint](../research/validation/owner-launch-plan.md)
sealed stop plans against suspended real PIDs and original leases. Its 290-pass
regression and unarmed launch/host revision 05 packets remain historical. The new
session source cohort includes subsequent Store/compiler/host changes; use its
successor review inputs rather than silently arming those older packets.

The GSD freeze/conformance work was committed at `048cb6b`, and dependency inputs
at `fec5bfb`. The real pinned schema-1 export and five negative import controls,
exact Agent Server preparation image and offline non-root/read-only startup smoke
remain separate evidence. The earlier VM diagnostic measured one unattended
two-CPU x2APIC-off boot and ACPI shutdown. These observations do not qualify the
new guard or an integrated executor deployment.

The [bounded original-stop checkpoint](../research/validation/original-stop-plan.md) replaced unrestricted subprocess capture and requires a matching deployment-profile stop binding. Its 279-pass regression and unarmed stop revision 02 plans remain intact. Later launch preparation uses that same stop issuer and source cohort.

The [host-adapter checkpoint](../research/validation/host-adapter-plan.md) prepared live observation/original-owner binding and independently measured stopped-state inventory. Its 258-pass regression and read-only inventory remain historical; no complete native owner/stop workflow was qualified. New host packets bind the later stop command and profile admission changes.

The [transfer controller checkpoint](../research/validation/transfer-plan.md) prepared identity-gated staging and invocation, original-authority monitoring and independent-stop requirements. Its revision 02 source snapshots and 234-pass/59-Linux-check results remain historical; current grants bind the later serial accounting fix.

The [guest control executor stage](../research/validation/guest-control-plan.md) prepared exclusive controls and permanent partial-state holds. Its earlier source pins are historical: use the corrected cohort in the transfer review for future activation. No old or new control packet has been applied on a selected VM.

The [bounded serial worker stage](../research/validation/maintenance-serial-plan.md) passed eighteen focused checks, including native Windows blocked-write termination, parent-death cleanup and exact job membership. Its role requests remain unarmed; the primitive does not supply guest command generation, VM admission or independent VM stop.

The [guest inspection and control-change stage](../research/validation/guest-maintenance-plan.md) prepared a standalone read-only payload, create-only planner and two unarmed role specs. Sixteen focused checks passed on the Linux tool host, including bounded pipe cleanup and APT staging ownership. Native guest observation and actual control changes remain unperformed.

The [maintenance admission and host preview](../research/validation/maintenance-runner-plan.md) prepared durable intent, one-use handoff and complete postcondition/stop checks, with thirteen focused synthetic tests. Its packets remain unarmed. The newer guest inspection report is diagnostic and does not yet provide the complete host admission frame or a qualified native transport.

The [maintenance media and configuration stage](../research/validation/maintenance-media-plan.md) produced a 599,830,528-byte ISO with 142 byte-verified files; it remains unattached. Native APT parsing accepted the preview and refused seven unsafe cases. Those frozen inputs are unchanged by the admission checkpoint.

The [native tool-resolution input check](../research/validation/resolved-tool-plan.md) passed on the pinned preparation image: terminal/file_editor only, one initial system event, zero tool actions/inference, both executors closed and no direct children after cleanup. Generated function schemas are 8,051 bytes; the static prompt is 15,235 bytes. These are byte lengths, not token-fit evidence. Raw conversion/prompt bytes and all preflights are retained; the container was removed and Desktop stopped. [Evidence](../research/validation/resolved-tool-evidence.json) leaves deployment schema/wire and final-target qualifications explicitly open. Guard creation approval is still pending.

The subsequent [OS archive retrieval](../research/validation/os-update-artifact-evidence.json) completed separately: 106 archives, 297,065,488 bytes, all hashes/sizes and package/version/architecture identities verified. It retrieved 102 files and reused four cached files, preserving host package state and frozen inputs. No guest update or VirtualBox operation ran. The pending disconnected guard creation approval is unchanged; actual guard disk bindings, offline bootstrap/install/hardening and final qualification remain next.

The [OS-update proposal](../research/validation/os-update-plan.md) now has measured, coherent role transactions from the inspected base: executor 97 upgrades/five additions; guard 97 upgrades/nine additions. Both pinned replays pass without removals or held-back packages, and all 489 proposed final versions are present in authenticated metadata. The archive union is 106 files/about 283 MiB, with four small files already cached at resolution time. No update was installed. Guest bootstrap, package/service hardening, final readiness/isolation and product implementation remain open; the disconnected guard creation decision is still pending.

The latest [guard package preparation](../research/validation/guard-package-plan.md) retrieved four archives totaling 527,232 bytes and verified their identities/hashes against signed Ubuntu metadata. Nothing was installed. A separate offline simulation identifies 97 OS upgrades and five new kernel packages; the stock nftables service also needs its permissive example and flush-on-stop behavior replaced. Prepare coherent OS-update/hardening inputs before qualifying final profiles. The disconnected guard creation plan and its digest are unchanged, and its separate approval remains pending.

M1-01 through M1-10 research designs have been merged. They cover executor interfaces, planning, routing, ownership, isolation, recovery policy, verification, spending, and the [two-task validation fixture](../research/two-task-validation-fixture.md). These documents describe proposed behavior and source findings; they do not establish that an integrated system works.

The restart audit began on `research/m1-11-executor-recovery` at `56cdfe2e2169f742c61f618eccf0ce4b439e03d4`, with a clean working tree. Its [PR #25](https://github.com/taggedzi/ai-dev-orchestrator/pull/25) was open and unmerged at the November 20 check. It adds the [recovery preflight](../research/executor-cancellation-recovery.md) and a [Linux marker probe](../research/fixtures/executor-recovery-probe.py). Every executor runtime case remains Inconclusive. The later fixture commit is local; no push or merge was requested.

The developer [approved the M1-10 design](https://github.com/taggedzi/ai-dev-orchestrator/pull/24#issuecomment-6962022192) while explicitly keeping the recommendation Conditional until the fixture is frozen, approved, and executed. No later approval was found in PR #25 or the issue #11 discussion. On November 20, issues #11–#14 remained open with no comments.

| Work | Current evidence | Next check |
| --- | --- | --- |
| [#11 executor recovery](https://github.com/taggedzi/ai-dev-orchestrator/issues/11) | Source review, preflight, probe and procedures; no runtime measurements | Measure success, cancellation, lost acknowledgements and crash recovery after the applicable isolation and gateway gates pass. |
| [#12 target isolation](https://github.com/taggedzi/ai-dev-orchestrator/issues/12) | Four denial groups and an allowed edit are specified; target unqualified | Freeze the exact deployment, then collect direct probes, positive controls, stop and cleanup evidence. |
| [#13 gateway controls](https://github.com/taggedzi/ai-dev-orchestrator/issues/13) | Local scripted route and spending rules are specified; no verified endpoint | Measure allowed and forbidden routes, identifier joins, interrupted replies and retained unknown-spend holds. |
| [#14 feasibility decision](https://github.com/taggedzi/ai-dev-orchestrator/issues/14) | Depends on #11–#13 | Assess R1–R6 and the developer walkthrough, propose the architecture decision, and record developer approval before implementation planning. |

PR #25 currently includes `Closes #11`, although #11 requires measurements absent from that PR. Before merging, remove that automatic closing reference or explicitly preserve the unfinished measurement work in another tracking issue. No GitHub metadata was changed during this checkpoint.

## Refreshed local preflight

These are measured workstation inventory observations from November 20, separate from the November 17 preflight. No VM, container, executor or inference service was started.

| Read-only check | Observation | Limit |
| --- | --- | --- |
| `Get-Command` | VirtualBox, Docker, uv, Node and Python resolve. `agent-server` and `openhands` do not resolve on PATH. | Other environments and package installations were not searched. CLI presence does not qualify a runtime. |
| `wsl --list --verbose` | Six distributions are listed, all stopped, including `docker-desktop`. | The sandbox initially denied enumeration; the read-only check succeeded outside it. Distribution contents and runtime controls remain unverified. |
| `VBoxManage list vms` and `list runningvms` | Seven VMs are registered, including `ai-dev-test`; no running VMs were listed. | A registered name does not establish intended use or permission to modify it. |
| `VBoxManage showvminfo ai-dev-test --machinereadable` (selected fields) | Powered off; configured for 2 vCPUs and 4096 MiB; guest type label Ubuntu 24.10 (64-bit); NIC 1 NAT, other NICs disabled; clipboard and drag-and-drop disabled; VRDE off; USB on. | This is hypervisor configuration, not a guest OS measurement. Images, actual guest version, sharing, egress enforcement, container limits, observers and cleanup are unqualified. NAT alone does not demonstrate the required destination restrictions. |

The existing `ai-dev-test` VM is a candidate for operator review only. Do not infer that it is disposable. The existing proposal calls for a fresh dedicated Linux VM with an unprivileged container; any reuse or replacement needs an explicit target choice and an exact deployment freeze.

## Proposed next work: prepare the validation fixture

The developer authorized this preparation scope after reviewing the checkpoint. The [fixture and local harness](../research/validation/README.md) now provide reproducible synthetic inputs, independent graders, durable intents and simulated spending, local Chat/fault services, marker collection, and a prepared lease supervisor. The [deployment plan](../research/validation/deployment-plan.md) records the next target review. This remains experiment preparation, separate from implementing the product orchestrator.

| Preparation deliverable | Required content |
| --- | --- |
| Reproducible fixture inputs | M-CLI1 seed, two dependent tasks, raw GSD plans/export, exact Git objects, checks, gold patches, scripted replies, rubric and expected outcomes from M1-10. |
| Trusted experiment harness | Durable operation journal, bounded local Chat service with no forwarding, fault proxy, independent marker/process observers, stop supervisor and sealed evidence collection. Keep any simplified native-only probe claims narrower than coordinator recovery. |
| Target deployment plan | Named disposable target; exact image and tool digests; identities, mounts, network rules, resource limits, evidence retention, stop and cleanup controls. No changes to existing VMs without approval. |
| Frozen review packet | Hash-indexed inputs, scenario permissions, numeric limits, expected assertions and unresolved prerequisites. Obtain run approval only after the required pins and controls are concrete. |

Retain OpenHands SDK/Agent Server v1.62.0 at `504a88cab0fb48ee5226238ad7b8f1d865fa84a8`, LiteLLM 1.105.1, Node 22.16.0 and Git 2.51.0 as the existing experiment's proposed pins. Record any version change and its affected source review and tests rather than silently updating the cohort. See the [manifest requirements](../research/two-task-validation-fixture.md#fixture-manifest-and-retention) for the remaining pins.

Carry forward M1-10's proposed limits for review: 2 guest vCPUs/4 GiB RAM; container 1 CPU/2 GiB and 128 tasks; VM authority at most 10 minutes; forced stop within 10 seconds of fencing; 30 seconds per model call/check; 60 seconds for reconciliation. Storage, retry, simulated-spending and scenario-specific limits remain governed by the full [threshold table](../research/two-task-validation-fixture.md#proposed-numeric-thresholds). These values remain proposals.

Use synthetic inputs, dummy credentials and local scripted inference. Simulated billing can test accounting policy but cannot establish hosted billing behavior, model quality or real cost savings. Fixture construction is authorized. Tool/dependency installation, VM changes, paid inference and sending repository data to a provider still require the applicable explicit authorization under [AGENTS.md](../AGENTS.md).

After authorization and freeze, follow the existing order: validate the trusted harness, qualify #12 isolation, establish minimal #13 route/metering controls, run B0/B1 and the remaining fault cases, then assemble #14 evidence. Keep native resume disabled until the applicable recovery evidence qualifies it.

## Next research check

The [maintenance configuration/media stage](../research/validation/maintenance-media-plan.md) now has exact ISO/profile identities, complete readback hashes and ten native apt-config measurements. The guest-path missing-directory warning is scoped explicitly; an equivalent workspace layout and seven negative cases passed. The installed Windows libarchive wrote a data-only ISO and read back all 142 files without extraction/mounting. Frozen inputs and WSL status stayed unchanged. New configuration code passed the full 156-test suite (155 passed, one existing skip). Next is maintenance runner/host preview and refusal checks, followed by separate target/attachment/install review; no VM change, install, provider call or product implementation occurred. See [evidence](../research/validation/maintenance-media-evidence.json).

The [maintenance side-effect review](../research/validation/maintenance-procedure.md) now retains 327 new control components and 282 selected payload texts from all 114 archives, plus 274 older installed scripts/helpers and a 34-file hook follow-up. A fresh full sparse-view comparison matched the stopped/disconnected source; subsequent read-only captures preserved its full hash and WSL status. Critical findings include direct PID 1 reexec, automatic needrestart mode, conditional cloud metadata lookup and APT activation hooks. The proposed bounded maintenance procedure now requires the actual guest dpkg database, fresh private APT configuration, persistent masks and no automatic repair/replay. Media, native configuration/runner preview, actual target bindings and boot/install approvals remain open; the guard-creation and phase-boundary decisions are unchanged. See [evidence](../research/validation/maintenance-evidence.json).

The [combined offline installation input](../research/validation/offline-install-plan.md), measured November 22, retains 114 unique archives / 370,837,818 bytes with the original three signed releases and six Main/Universe indexes. Independent signatures, a private file-only APT refresh and exact combined transactions passed: executor 97 upgrades/16 additions to proposed 496 rows; guard 97 upgrades/nine additions to 489. No removals/held-back effects or WSL status changes occurred. Three held preparation attempts and the successful receipt remain separate. The proposed maintenance contract has no installation authority or apply script. Next is remaining OS script/automatic-service review and concrete maintenance preparation; actual guard creation and phase-boundary choices remain separately pending. See [evidence](../research/validation/offline-install-evidence.json).

The [engine archive/text stage](../research/validation/engine-input-plan.md#measured-retrieval-and-text-review-result) now retains all 11 archives with verified size/hash/control identities, plus control scripts, runtime changelogs and three stock units. Eight archives were retrieved; three were reused. WSL status stayed unchanged; no downloaded script/binary, daemon or validation VM ran. Source review identifies automatic service/socket and AppArmor handling that must be controlled by the offline install plan. Changelog inspection does not settle runc backport status; security/runtime qualification remains open. See [artifact evidence](../research/validation/engine-artifact-evidence.json). The next concrete work is offline installation/hardening preparation while phase-boundary and guard-creation decisions remain pending.

The [offline engine resolution](../research/validation/engine-input-plan.md#measured-resolution-result) proposed 11 additions totaling 74,229,720 bytes against the hypothetical 485-row post-OS executor inventory, with no baseline upgrades/removals/held-back packages. Native `dpkg-query`, signatures, both component indexes and exact-version replay passed. At that checkpoint, three archives were cached and eight / 73,772,330 bytes required retrieval; the archive stage above has completed it. The first catalog attempt held on the Main-only parser and is preserved separately. No package was installed or engine started; security/backport, installation and runtime qualification remain open. See [catalog](../research/validation/engine-inputs.json) and [resolution evidence](../research/validation/engine-resolution-evidence.json). Pending phase-boundary and guard-creation decisions remain unchanged.

The [container-engine metadata stage](../research/validation/engine-input-plan.md) now retains all three Universe indexes from the same signed OS cohort, with compressed/expanded hashes verified. Docker `29.1.3-0ubuntu3~24.04.2` is a repository candidate; no engine transaction has been resolved or installed. The first attempt held on a valid concatenated XZ stream; its receipt remains intact, and the corrected attempt reused only reverified data. Next is dependency resolution against the hypothetical post-update 485-row executor inventory and a distro backport/feature review. This independent preparation does not settle either pending architecture/guard decision. See [metadata evidence](../research/validation/engine-metadata-evidence.json).

The [phase-boundary decision proposal](decisions/0002-fixture-phase-output-boundary.md) is now concrete and awaiting developer selection. Its recommended broker ceiling would reduce only the output maximum under the trusted frozen phase while binding raw/effective hashes; one-step Agent runs would instead require an LLM-switch route and continuation qualification. A local comparison reproduced all four previously captured capped native bodies exactly, without starting an SDK, task, broker or VM. The strict rejection contract is still active. See [review evidence](../research/validation/phase-handoff-review-evidence.json). No architecture selection, normalization activation or dispatch approval is inferred from this preparation.

The [trusted phase preparation](../research/validation/phase-policy-plan.md) adds strict frozen count/role declarations, output-cap checks and atomic task/attempt/role/reservation matching to the loopback fixture broker. A changed transcript/policy after restart holds. Native direct SDK calls with explicit per-call options now serialize 6,000 for initial edit and 1,000 for finish projections, with four mock denials and no sockets, executors or model responses. This does not change the unmodified Agent.step path: a trusted Agent phase handoff, complete input/response counting evidence and final wire qualification remain open. Finish dispatch stays held. Cleanup restored Desktop to stopped; guard creation is still separately pending. See [phase evidence](../research/validation/phase-policy-evidence.json).

The [native request preparation check](../research/validation/wire-input-plan.md) captured four SDK/LiteLLM HTTP bodies at a mock transport returning 403, with no socket connections, executors or model responses. Prepared first-call input estimates are 5,209/5,228 tokens. Synthetic finish projections request `max_completion_tokens=6000`, exceeding the proposed finish output cap of 1,000. Hold finish dispatch until a trusted per-phase cap is enforced and observed at serialization and broker admission. Real tool output, Agent.step additions, correction/review inputs and final-target wire are still open. The container was removed and Desktop stopped again; guard creation remains separately pending. See [wire input evidence](../research/validation/wire-input-evidence.json).

The [prepared token-count check](../research/validation/token-fit-plan.md) measured the retained system prompt and two native tool definitions in the pinned offline image: 4,985 local estimated tokens, with SDK/LiteLLM message-only agreement and zero inference attempts. That leaves 1,015 under the proposed 6,000-token finish/review input cap before user/history/review context. Complete role requests and captured Chat wire remain unmeasured; caps and deployment schema approval stay unchanged. The probe container was removed and Desktop stopped again. See [token evidence](../research/validation/token-fit-evidence.json).

Finish the reproducible validation environment for M1-12. The exact image/toolchain now has offline build/startup evidence. Freeze and test the narrow conversation/API grant, external network-enforcement plan and final guest-readiness/hardening profile, then qualify all four denial groups and the allowed edit on that same frozen deployment. A Desktop startup check cannot substitute for the selected VirtualBox target. Guest runtime installation and final deployment/run approval remain separate actions.

The [runtime preparation](../research/validation/runtime-image-plan.md) selected and retained 186 hash-pinned Linux/Python archives. The [later offline build](../research/validation/image-build-plan.md#measured-build-and-startup-result) pins both base-image manifests, four build tools and upstream source. It passed `pip check`, SDK/tool imports and final non-root/read-only startup. Image ID is `sha256:f242d7a2b69742fde04385231647c54c57396b251ddfd7a5f34095073970e868`; the 999,058,944-byte archive SHA-256 is `4859acc886856d990bef0215be182999bf6a7021db54ba06db30888ca01caf66`. Measured versions are Python 3.13.17, Node 22.16.0, Git 2.51.0, OpenHands 1.62.0 and LiteLLM 1.105.1, with 189 Python distributions and 87 base dpkg rows. The initial probe was invalid because of newline escaping; its records remain separate. The corrected check uses `LITELLM_LOCAL_MODEL_COST_MAP=True` to prevent the observed default remote metadata fetch. All four health/info routes returned 200. Both smoke containers were stopped and removed, Desktop was stopped and the engine became unavailable. See [build evidence](../research/validation/image-build-evidence.json). Previous review bundles remain unchanged.

This image is still a preparation candidate. `/server_info` advertised 17 tools including delegation/workflow tools; a fixed two-tool conversation grant and external ingress allowlist remain unqualified. The Desktop AppArmor label was empty, and its base inventory includes apt 3.0.3. Final-target enforcing LSM and patch/security qualification remain open. The separate Docker workspace distribution is absent (`workspace_version` unknown); the candidate serves the proposed local conversation runtime. No model call, conversation or executor task ran, and none of these observations qualifies M1-12 or the product scheduler.

The [control admission preparation](../research/validation/control-policy-plan.md) now validates an explicit two-tool request against the pinned SDK and retains both action-model schemas and the native request schema. An initial 12,000-token context setting was rejected by the SDK's 16,384 minimum; the corrected request uses 32,768 context capacity, separate from the unchanged 12,000-token per-request broker input bound. Local conformance covers exact request/route/credential grants, persistent uncertainty, no automatic mutation replay, fencing/stop access, concurrent admissions and an independent fault-proxy receipt. No Conversation, executor or inference was started. Actual resolved tool/Chat schemas, per-role token fitting, final network placement and required WebSocket observation remain open. See [control evidence](../research/validation/control-schema-evidence.json).

The developer selected the [guard VM topology](decisions/0001-validation-network-boundary.md) for preparation in this thread. The [first-stage creation review](../research/validation/guard-preparation-plan.md) now fixes the guard identity/resources and full source-disk clone, with eight NICs disabled and no boot. Read-only native inventory and a new stopped partition copy confirm the current source hash; package metadata identifies missing nftables, and loopback port 18181 was available. The native script has a no-action preview and tested refusal paths. The network contract keeps actual interfaces/MACs, effective rules and activation evidence explicitly unfilled. See [preparation evidence](../research/validation/guard-preparation-evidence.json). Next is separate approval for disconnected VM creation, followed by offline package/hardening and trusted network qualification. The topology decision does not approve native creation, NIC activation or final tests. The control gate currently binds loopback only; no guard VM or network has been provisioned. Docker was stopped again after the metadata probes, and prior review bundles remain unchanged.

The [GSD export/import stage](../research/validation/gsd-export-plan.md) used the explicitly approved, integrity-pinned published CLI in isolated local storage. Planning-host Node 26.13.1 satisfies its Node >=24 requirement; executor Node 22.16.0 and Git 2.51.0 pins were preserved. The selected schema-1 snapshot is `5fc3b148578fc357606e7744e12e692d914eb0b9354f99b60e21264bc8685df3`. It preserves both tasks and their dependency, with raw PLAN files supplying action/check bodies absent from the snapshot. Missing targets, dropped edges, cycles, malformed task markup and an unsupported schema all block the fixture import. Native completion is never coordinator acceptance. See the [measured evidence](../research/validation/gsd-export-evidence.json) and [external review-packet freeze](../research/validation/gsd-freeze-evidence.json). The candidate profile fills the actual GSD digest while leaving runtime, isolation and approval fields unqualified.

The guest-readiness preparation still follows the [stopped-image findings](../research/validation/offline-inspection.md#corrected-trial-result-and-next-check). Earlier boots stalled or needed pause/resume; the last one-CPU trial missed the ACPI shutdown deadline. Read-only inspection established that the installer intentionally created the cloud-init disable marker and Linux handled the power event, reaching its power-off target. It also found the offline network-online wait failure. The GSD stage made no VM changes. See the [inspection evidence](../research/validation/offline-inspection-evidence.json).

The one-variable diagnostic initially failed before guest boot because VirtualBox's x2APIC setter also disabled ordinary APIC. Source review identified the coupling; the corrected command enables ordinary APIC last and verifies the exact profile before starting. The corrected trial completed one unattended two-CPU x2APIC-off boot/shutdown cycle in 234.271 seconds, with no pause/resume or emergency stop. Native poweroff was observed about 8.2 seconds after the ACPI receipt. The [diagnostic evidence](../research/validation/boot-diagnostic-evidence.json) retains the failed native start and the successful cycle separately. This is not yet repeated-start qualification or a proven cause of earlier stalls.

The latest receipt confirms Ubuntu 24.04.5, kernel `6.8.0-139-generic`, Python 3.12.3, UID 1000, ext4 root, loopback only, unchanged 480-row packages, clean package audit and no SSH server. Nine legacy predicates pass; `cloud_init_done` remains false because the known installer marker disables it. Historical verdicts are preserved. The next stage must test a narrowly bound readiness rule for that inspected policy before three consecutive cold-start/ACPI cycles, holding on any failure. Address the disconnected image's network-online wait during later hardening.

The current VDI SHA-256 is `2eb1d9cd009ecfe83381d855137f5cee8c1317739f6209beddd6da8a10955a09`. Native verification confirms poweroff, two vCPUs, 4096 MiB, ordinary APIC and x2APIC restored on, eight disabled NICs and UART off. The existing `ai-dev-test` VM and host virtualization/security configuration were unchanged. Runtime hardening, containment and executor behavior remain unqualified. The [deployment plan](../research/validation/deployment-plan.md) records the remaining controls. Issues #11–#14 and PR #25 were reread November 21 and remain open; PR #25 still contains the premature `Closes #11` reference. No remote changes were made.

The original 220-file review bundle remains unchanged at its recorded digest. Later revisions retain the native GSD export and measured preparation image with their own hashes. GSD fixture conformance does not qualify a real product importer, scheduler or acceptance ledger. Final-target image/tool binding, resolved SDK/Chat schemas, exact transcripts, external supervisor/observer controls and runtime qualification remain open. Product implementation and product architecture adoption remain gated on the feasibility decision.
