# Proposed: bounded same-boot maintenance review

Status: **Proposed; developer approval required.** No adoption or native action is
authorized by this record. This concerns the validation fixture, not the product
orchestrator architecture. The existing stop-after-attempt behavior stays active.

## Problem and evidence

The [transfer controller](../../research/validation/transfer-plan.md) always
fences and stops an admitted attempt, including a successful inspection. Its
controls grant must already contain a genuine observation, exact plan and scoped
approval. That observation includes the target's current boot ID. Rebooting after
inspection invalidates that binding. Fabricating the new boot ID, using an old
report, or approving a broader class of changes would change the current contract.

The Store also admits only one transfer attempt. Opening another Store would
separate controls from the original owner's durable lease and stop ledger. This
is a workflow gap; the synthetic controls tests establish neither a usable human
approval handoff nor permission to skip shutdown.

## Recommended design for approval

Prepare one maintenance session under the **original, immutable outside-VM lease**,
with these explicit states:

`inspection → awaiting review → approved controls → independent stop → reconciliation`

The original owner remains outside the guest and controller. Its existing wall
and monotonic deadlines stay fixed, at most 600 seconds from initial arm. Review
time counts against that lease. A rejection, absent/late approval, lost owner,
controller death, uncertainty or expired deadline leads to fencing and stop.
There is no lease renewal, pause/resume or automatic reissue.

During review the guest may remain running, but no guest command or further
mutation is admitted. The inspection worker must be reaped and its transport
closed. Host access controls must prevent another process from using the trusted
root console. This requires separating the permission to keep the VM alive
within its original lease from permission to dispatch a particular phase; the
current single active flag cannot express that distinction by itself.

The developer reviews the actual raw report and exact proposed action list.
A later control phase needs a new scoped approval bound to those hashes, this
session, target, boot ID, source cohort and remaining original budget. Immediately
before changes, the existing controls program must obtain a fresh inspection and
match the reviewed stable facts and action list. Only its documented timestamp
exclusion may be ignored; boot identity, package/configuration facts and planned
actions must remain bound.

Use one durable Store and append-only, uniquely identified phase attempts.
Each serial operation gets a new nonce; no previously possible-sent upload is
resubmitted. Prior inspection receipts remain evidence, not installation or task
acceptance. A process restart cannot resume the session's control phase. The
original owner still stops, and uncertain state remains available for manual
reconciliation. After the control phase, both the original owner's stop ledger
and an independent observation must confirm poweroff and the fixed storage and
disconnection profile before any completed report is issued.

## Alternative and consequence

Keep unconditional stop after every inspection. This preserves today's behavior
but leaves controls blocked until a separately reviewed acquisition/approval
mechanism supplies a genuine current-boot observation. Moving the same handoff
into an unqualified boot collector does not resolve its authority, timing or
restart requirements. Approving a generic conditional plan instead of an actual
report would require a different approval policy and is not proposed here.

## Required checks before activation

- A delayed approval cannot extend either original clock or enable a phase after
  expiry; an unanswered review stops without another conversation turn.
- No guest dispatch is possible while awaiting review. Approval and revocation
  races have one durable outcome; changed/replayed approvals and old boot IDs hold.
- Controller/worker death and interrupted journal writes cannot leave a resumed
  control path. The original owner survives independently and issues at most one
  native stop; missing stop evidence never becomes acceptance.
- The full actual inspection, review, fresh comparison, controls and independent
  stop workflow must run on the selected VM under separate scoped native approval.

## Requested decision and limits

Approve preparation of this session model, or retain today's unconditional stop
contract while another mechanism is designed. Approval of this design would not
authorize VM creation, boot, root access, transfer, control changes, installation,
network activation or final validation. Existing guard-creation and broker
phase-boundary decisions remain separate. No new session code has been added.
