# Start here

Updated November 24, 2026. The developer resumed the full R1–R9 product after
the earlier goal pause. Decision 0007 preparation is measured. The product is
not complete, and this is not a release.

## Workspace and objective

Use this exact workspace:
`E:\Home\Documents\Programming\ai-dev-orchestrator`.
Branch: `research/m1-11-executor-recovery`; last observed HEAD:
`e609dbce6af8f3f845ea8226bf2648fbe245197c`.
There are extensive dirty/untracked files and essential ignored `.local` artifacts.
**HEAD alone is not the handoff.** Preserve the workspace, evidence and user changes.
No agent commit, push or publication is authorized or was made.

Read [AGENTS.md](../AGENTS.md), [the vision](vision.md), [HANDOFF.md](HANDOFF.md)
and [the complete delivery plan](product-delivery-plan.md). Continue the full
orchestrator and R1–R9, including real isolated coding, model selection/cost,
independent review, integration, discovery, self-hosting and release preparation.
The current scripted prototype is not the requested final product.

## Exact stopping point

The retained product evidence is still **87 passing product tests**, zero skips,
with source snapshots, actual SQLite/Git/artifact smoke and private merge/CAS
controls. [Evidence](implementation/product-integration-evidence.json). That
bundle was not rewritten. Mapping was measured at 92 tests. Promotion was
measured at 100 tests. The current scratch rerun passed **109 tests, 0 skips**,
including scripted model eligibility, permits, cost limits, and usage quality.
`capabilities.task_acceptance` and `live_eligible` stay false. A promotion
result can record `task_accepted=true` for that one integration, and task 2's
input is that accepted revision. Real task execution and provider calls stay false.

Decision 0007 preparation is additionally measured. `tests.test_held_successor`
passed 15 tests. Non-native offline-startup tests passed 26. The unattached
capture is `.local/validation/held-successor-capture-01`, summarized in
[held-successor-evidence.json](../research/validation/held-successor-evidence.json).
The production row is still held/active=1. `NativeBindingTests` did not pass:
the normal case held on `OperationalError: database is locked`. The read-only
query left VBoxSVC pid 24848. Later checks, after mapping and after the
promotion slice, found no VBoxSVC, VBoxManage, or VBoxHeadless process.

## Current goal

**Scripted P2 acceptance and scripted P3 model policy are measured. P4 waits
on the qualification lane.**

The product lane is the complete orchestrator in [the delivery plan](product-delivery-plan.md).
P1, the scripted P2 scenario, and the scripted P3 cost ledger are in place:
plans, loopback controls, Git intake, check/review records, private staging,
diverged-head mapping, fresh checks and review on a distinct integrated commit,
one serialized promotion, and model eligibility/permits/limits/reports.
Native successor transfer, model-provider calls, browser QA, and release packaging
wait behind it.

The measured P2 sequence, in order:

1. **Authorized diverged-head mapping.** Schema 5 stores one developer
   authorization per attempt. `begin()` consumes it once. A missing, stale,
   replayed, or different mapping refuses the stage. The mapping does not itself
   promote or accept a task.
2. **Fresh checks and review on the integrated OID.** When the integrated commit
   differs from the reviewed candidate, the gate stays held until new mandatory
   checks and a separate review bind that exact OID. A passing regression on the
   old candidate does not supply them. `I = C` still becomes promotion-ready from
   the candidate evidence plus passing regressions.
3. **One serialized promotion and acceptance.** `begin_promotion()` commits
   possible-send before Git. One transaction compares the milestone head guard,
   records the promoted commit, and accepts only that integration.
   `update_validation_ref()` remains a private validation CAS. Promotion uses
   `refs/orchestrator/milestones/`. Crash after the ref update reconciles the
   existing effect once and does not create another. Task 2 becomes ready only
   from that accepted task-1 result, and its input revision equals that commit.
   `live_eligible` and real task execution stay false. Status
   `capabilities.task_acceptance` stays false.

The delivery-plan fixture now passes on disposable Git repositories: a rejected
candidate cannot promote, a changed SHA invalidates review, integrated checks
bind the promoted commit, one crash reconciles once, and task 2 starts from the
accepted task-1 integration. Scripted outcomes stay labeled scripted. Schema 6
adds the evidence and promotion tables plus `attempts.settled`. The retained
87-test evidence file was not migrated. Schema 7 adds the model policy tables.
The same limits apply: scripted promotion and scripted cost records are not
qualified execution or a live route.

Measured P3 behavior, in `coordinator/model_policy.py`:

- An unavailable route, a fallback route, and a reused submission id are denied.
- The same permit command returns the original reservation.
- Implementation spend cannot consume the protected review allowance.
- Unknown usage keeps its reservation across reopen.
- A known amount releases only the unused remainder, and the retry gets a new
  submission id.
- Estimates stay fully reserved. Pause does not release a reserved permit.
- Reports separate known, estimated, pending, and unknown units.
  `live_eligible` stays false.

Do not start a provider call. P4 executor and live model routes wait until the
qualification lane allows them.

Limits that stay in force: do not transfer the held guard reservation or boot a
VM. Successor code is in `research/validation/held_successor.py`.
`Admissions.finish` keeps an inherited exclusion until an independent successor
stop is stored. Ordinary ledgers without a continuations table keep the old
unarmed-release behavior. No commit, push, or publication.

Useful native code locations:

- `research/validation/offline_startup.py`: `Admissions.finish` and `activate`
  cleanup now consult continuations only when that table exists. Do not migrate
  the production ledger from `Admissions.__init__`.
- `research/validation/initial_aborted.py` and `recovery_records.py`: existing
  fixed history covers reviews 04/05/07 and is stale for the current offline
  controller-loss run. Do not loosen the old type or add a generic allow-Aborted flag.
- `startup_qualification.stop_proof`: independently verifies the original owner
  journal/receipt, natural family exits and two bounded poweroff observations.
  A successor's settled release must not reduce this proof to a caller-supplied bool.

Decision 0007 requires one atomic compare/transfer with immutable history,
one successor/no fork or replay, retained inherited exclusion on unarmed failure,
lost-commit-ACK hold and process allocation only after confirmed commit/readback.
Tests must include competing successors, revocation, drift, incomplete provenance,
migration interruption and successful/failed surrogate stop. Actual Windows
Python jobs/owners/frontends and synthetic VM observations are required; do not
present pure JSON fixtures as the complete preparation evidence.

## Critical native facts and approval limits

The actual admissions ledger remains untouched:
`.local/validation/offline-guard-admissions.sqlite`.
Row `ccc16a8440524bda84e57fdcd90055e7` is **held, active=1**.
Its sole original stop exited 1 with no command receipt. Do not clear/reset it,
call `finish(settled=True)`, replay the old owner/stop or release exclusion.
Aborted is not successful shutdown. The November 24 read-only inventory and
unattached copy agree: guard aborted/unlocked, executor poweroff/unlocked.
That capture is not a reservation transfer.

[HANDOFF.md](HANDOFF.md#native-state-and-authority--untouched) contains exact run,
target, source and journal hashes; [native evidence](../research/validation/guard-controller-loss-evidence.json)
contains the consumed review and containment measurement. The entire Decision
0007 history/backup/profile contract must be satisfied before a native review.

Decisions **0007/0008** and the exact **19-package local web installation** are
already approved. Proofs: [decision approval](decisions/0007-0008-approval.json)
and [installation approval](implementation/web-install-approval.json).
Do not ask again for those scopes. Installations beyond that set, native changes/
activation, real transfer, provider-data/paid experiments, remote writes and
publication retain separate approval requirements. No subagent delegation is authorized.

## Runtime, verification and outstanding gaps

Use `.local/product-web-venv/Scripts/python.exe` or existing
`C:/Python315/python.exe`: Python 3.15.2 / SQLite 3.53.4. Bare `python` has affected
SQLite 3.50.4: use it only for file-only verifiers, never new authority writes.
Product schema is 4. Do not migrate retained historical evidence stores to try
new code; use fresh scratch data. Restore/path rebinding is unimplemented.

For a cheap initial check, run:

```powershell
python .local/validation/verify-agent-handoff-02.py
```

It resolves changed handoff documents through retained originals rather than
rewriting old hashes. Full product commands are in HANDOFF.md. Avoid rerunning
the expensive suites without a code change or specific concern.

The last complete research cohort remains **609 tests: 594 passed, 14 skipped,
one startup-BEGIN BUSY error**. Four focused actual-SQLite diagnostics passed,
but the old writer/timing is unknown. Product tests do not repair that result.
Browser QA also remains open: Computer Use could not determine the browser URL;
its temporary server was terminated. No product server, subagent or test process
remains. A process check after the mapping slice found no VBoxSVC, VBoxManage,
or VBoxHeadless. The earlier pid 24848 was absent.
Last product run `91255` and focused `98712`/`98285` exited 0.

Remaining delivery lanes: live model routes, qualified
P4 executor/planning/provider adapters, real P5 two-task milestone and P6 discovery/
dashboard/self-hosting/release preparation. See the [completion audit](completion-audit.md).
Keep requirements incomplete until their actual evidence exists. Update this
pickup point and HANDOFF/status at each meaningful stopping point.
