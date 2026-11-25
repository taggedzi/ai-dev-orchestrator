# Integration staging and regression evidence

`coordinator/integration.py` now records durable integration proposals and
regressions bound to the exact staged revision. This is development preparation;
it executes no candidate/check commands. The developer can authorize a head,
approve regression or integrated evidence, begin, promote, and reconcile through
the [CLI](product-cli.md#scripted-promotion-and-cost) and the loopback API.
Those commands call this module. A promotion receipt can record
`task_accepted` for that one integration. Status `capabilities.task_acceptance`
and `live_eligible` stay false. A green development gate is not live acceptance.

## Proposal protocol

Preparation requires the fresh [candidate check/review gate](product-verification.md).
The frozen intent names its exact evidence set, intake version/receipt,
repository, attempt contract, expected head and allowed paths. Without a
diverged-head mapping, the milestone head must remain the attempt's input.
One intake cannot silently acquire a different proposal or controller.

The controller commits possible-send before Git writes. Staging retains a
private intent-object ref and a private proposal ref. For direct integration,
the proposed commit equals the already-reviewed candidate; the separate intent
object still binds its authorization. A reused proposal ID with different
authorization cannot be reconciled merely because the candidate OID is unchanged.

The receipt records exact parent order, tree, before/after manifests and effective
diff digest. Changed paths relative to the expected head must stay within scope.
The packet joins the frozen candidate evidence to that stage. Byte artifacts and
Git objects are rechecked before regression admission and gate evaluation.

Process loss leaves an uncertain operation. `reconcile()` reads the existing
intent/proposal refs and never recreates a missing effect. Missing or changed
refs hold. A partial intent-ref write with no proposal is not a completed stage.
Valid late observations remain held after pause/revision; the old generation
cannot resume authority. Duplicate observations deduplicate, and conflicting
ones fence the project. Uncertain SQL completion is not permission to rerun Git.

## Git merge and ref primitives

The managed Git engine supports direct staging and clean two-parent merges,
without a checkout or index. A merge uses the candidate's single input parent as
the explicit base; the head must descend from it and must not already contain
the candidate. Ordered parents are `[expected_head, candidate]`. Exit status
decides whether the merge is clean; a conflict tree is never retained as a
proposal. Scope and regular-file/path checks apply to the effective merged tree.

These primitives are measured in private scratch controls. A scratch repository
may name a different expected head only through one developer authorization.
`authorize_diverged_head()` binds the attempt, the previous expected head, the
new head, and the current authority generation. The new head must descend from
the previous head. The record is not itself a stage, a milestone move, or an
acceptance. `prepare(expected_head=...)` refuses a missing, stale, different,
or already consumed mapping before it can stage. `begin()` consumes a matching
mapping once in the same transaction as possible-send. The same authorize
command replays its committed result; a later command for that consumed binding
conflicts. Staging then uses the authorized head as its base. The milestone row,
publication refs, and acceptance table stay unchanged.

When the staged commit differs from the reviewed candidate, the gate stays held
until fresh mandatory checks and a separate review bind that exact OID. The
checks must deep-equal the approved candidate policy. The review session must be
new, and its packet must name the integrated stage rather than the candidate
packet. A passing regression or the old candidate review does not supply them.
A changed subject OID invalidates that evidence. For `I = C`, the candidate
evidence already binds the commit, so a second review is not required.

`update_validation_ref()` measures expected-old-OID updates only in
`refs/orchestrator/validation/`. A stale guard refuses even when another update
already produced the requested OID; observation is not proof this command sent
the write. This is neither a milestone/publication ref nor an acceptance API.
Promotion uses `advance_milestone_ref()` on `refs/orchestrator/milestones/` only.

## Exact regression records

The developer approves an exact immutable policy with regression commands,
observable cases, assigned producers and environment digests. Currently all
profiles are explicitly scripted. The implementer cannot supply the independent
regression receipt. Admission freezes the proposal receipt, expected head,
candidate and integrated OIDs, source/packet/policy/profile and generation.
Dispatch commits possible-send and cannot be replayed after process loss.

Results use the strict check receipt contract: complete case coverage, matching
binding/source/environment and retained observations/logs. A failing, incomplete,
stale or mismatched result cannot qualify. Duplicate/conflicting receipts and
pause follow the same durable hold rules. A fresh gate rechecks candidate
evidence, the staged subject, policy, artifacts, receipt joins and authority.

For `I = C`, a complete scripted regression chain can report
`development_ready_for_promotion=true` without a second review. For `I != C`,
that flag stays false until the fresh integrated checks and review pass. In both
cases the gate keeps `live_eligible=false` and `task_accepted=false`.

`begin_promotion()` is developer-only. It freezes the milestone head guard, the
integrated revision, and the evidence digest, then commits `possible_send`
before Git. The guard is the current milestone head: the stage base when no
mapping exists, or the mapping's previous head when staging used an authorized
diverged head. `promote()` creates or CAS-updates the private milestone ref and
then one database transaction compares that guard, stores the integrated
revision, inserts one acceptance, and sets the attempt `settled` so it leaves
the active-attempt index. It does not bump project generation. A missing or
still-old ref is held and is not recreated. A crash after the ref update is
reconciled by reading the existing ref once; a second reconcile returns the
stored result and does not call `update-ref` again. The promotion result can
report `task_accepted=true` for that row. Status `capabilities.task_acceptance`
stays false. Task 2 can be claimed only after that acceptance, and its input
revision is the accepted integration. `live_eligible` stays false. Qualified
runner/reviewer authentication and real isolation remain prerequisites for live use.

## Persistence and measured evidence

Schema **4** adds proposals, regression policies/operations and immutable
observations. Schema **5** adds one `integration_head_mappings` row per attempt.
Schema **6** adds `attempts.settled`, integrated evidence policies/operations/
observations, and one `integration_promotions` row per proposal. Settlement
releases the active-attempt index without marking the attempt failed or
cancelled. Explicit offline migration supports schemas 1–6, backs up first,
preserves held/possible-send history, and never invents a head mapping, a
promotion, model policy, or native permission. Schema **7** adds model
eligibility, permits, and usage rows. It does not call a provider or make a
route live-eligible. See [model policy](product-model-policy.md).
Follow [the migration procedure](product-intake.md#schema-migration). Explicit
archive restore is specified in [product intake](product-intake.md#archive-restore).
Host-power-loss qualification remains open.

[Retained evidence](implementation/product-integration-evidence.json) records
**87 passing product tests**, zero skips, Ruff/format/whitespace, integrity/FKs
and Git fsck. That bundle is still the schema-4 checkpoint and was not migrated.
A later scratch rerun of the product modules passed **92 tests**, zero skips, on
Python 3.15.2 / SQLite 3.53.4. That rerun covered mapping only. The promotion scratch rerun passed **100 tests,
0 skips**, including fresh integrated checks/review, changed-SHA refusal, one
crash reconcile, and task 2 claiming the accepted integration. The current
scratch rerun passed **109 tests, 0 skips**, recorded in [status](status.md).
It adds scripted model eligibility, denied route/fallback/replay, the protected
review allowance, response-loss reservation across reopen, a new submission for
an authorized retry, and a v6 migration that preserves a promotion without
creating a model policy. A v5 migration
preserves a head mapping without creating a promotion. Sixteen earlier
integration tests still include real direct/merge/conflict/scope cases,
changed-head CAS, child-process exit after stage and validation-ref writes,
read-only recovery, competing admissions, regression rejection/conflict, late
results and missing source artifacts. A v3 migration case preserves a pending
verification without allocating stage authority.

The retained 87-test smoke joins actual DB/Git/artifact records with scripted
check, review and regression outcomes, plus separate private merge/CAS controls.
That checkpoint's milestone head is unchanged and its T2 remains blocked. The
later promotion tests use new scratch repositories. No candidate execution, VM
change, provider call, installation or publication occurred.

The Git primitives follow upstream [`merge-tree`](https://git-scm.com/docs/git-merge-tree)
and [`update-ref`](https://git-scm.com/docs/git-update-ref). Documentation explains
the operations; the retained run establishes only the cases measured on Git
2.56.1.windows.1. It does not qualify live integration or complete the full product.
