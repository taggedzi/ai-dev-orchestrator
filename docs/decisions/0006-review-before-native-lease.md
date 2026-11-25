# Review the native action before allocating its live lease

Status: **Preparation approved, November 24, 2026.** The developer answered
“I approve” to this preparation decision in the conversation. This concerns the
fixture's initial native activation approval, not product architecture adoption.
Authorized scope is implementation, Python surrogate tests and read-only preflight only.
Any later native run still needs its own exact reviewed artifact and approval.

The [implementation](../../research/validation/offline-approval-plan.md) now
passes **608 checks: 595 passed, 13 platform skips**, with no source drift.
Actual Windows Python cases and actual read-only preflight are recorded
separately in [evidence](../../research/validation/offline-approval-evidence.json).
The developer subsequently gave separate exact approval of inert review
`0925de6acf1a400301d84abf1177a0596f811ff142597e3e74ddc52c4f13a788`.
Its consumed native run measured joined-controller-loss containment in 2.668
seconds. The sole original stop exited 1 and remains held; Aborted is not accepted
shutdown. The target reservation remains active. See
[native evidence](../../research/validation/guard-controller-loss-evidence.json).
No further native authority follows from either approval.

## Problem and measured evidence

The [current startup review](../../research/validation/startup-qualification-plan.md)
constructs suspended Python controller/owner processes and a fixed 600-second
lease before asking the developer to approve their exact identities and expiry.
Five retained unarmed reviews expired without activation. The latest loss review
retired all three original process identities with zero VM starts/stops.
See [walkthrough evidence](../../research/validation/feasibility-walkthrough-evidence.json)
and the [developer workflow assessment](../developer-experience-walkthrough.md).

The existing refusal is correct under that contract. Reusing an expired review,
quietly extending its lease, treating goal continuation as approval or replaying
a consumed run would violate it. The measured usability problem is that no VM
is active while the initial decision consumes the short execution lifetime.

## Proposed preparation

Prepare an explicit optional initial-review path with these boundaries:

The first implementation is for the fixed guard and its existing normal or
joined-controller-loss case. Executor activation and initial-Aborted recovery
do not gain a new path from this preparation; any later extension needs its own
concrete admission checks and native review.

1. Produce an immutable **inert review artifact**. It binds a unique review ID,
   fixed target/role, exact executable/arguments/environment, source cohort,
   current backup/profile receipts, one named case and its permitted faults,
   possible disk/configuration/NVRAM writes, one boot, the original single stop,
   all existing budgets and the maximum 600-second lease. It allocates no
   controller/owner process, job, lease or VM authority while awaiting a human.
2. Record explicit approval of those exact bytes. A distinct format must keep
   this separate from the existing live-PID/absolute-expiry review. Old approvals
   and expired review hashes cannot be converted or reused. Approval of this
   preparation design is not native approval. The later exact native artifact
   remains a separate decision, without a short live-session countdown.
3. An explicit activation command consumes the approved artifact once in a
   durable, target-bound admission intent **before** preflight or process
   construction. Consumption is independent of output directory and survives
   restart or a lost result. A failed or interrupted admission stays consumed;
   it cannot allocate another session, retry a command or renew a lease.
   Writing an approval file alone must not launch a background watcher or VM.
4. Recheck the exact approval, revocation, sources/binaries/environment, current
   stopped/unlocked target and preserved executor, backup bytes and current
   profile before allocating live authority. Perform the expensive full-file
   checks during this unarmed phase. Retain the existing file-identity/read-lock
   protections into the final start gate; a stale observation or unlocked gap
   must not substitute for fresh admission evidence. Drift or uncertainty
   refuses the consumed attempt without a native stop while still unarmed.
5. Construct the suspended controller and original owner only after approval
   and successful unarmed checks. The trusted binder records their actual PID
   creation identities, jobs, source/input bindings and one fresh immutable
   wall/monotonic lease into the consumed admission. The **existing 600-second
   lease begins at its construction**, before seal/resume/start. It never resets.
   Both process identity and final source/approval/target gates still precede
   owner activation and the single frontend resume.
6. Preserve the existing owner, kill-on-close frontend family, short start grant,
   startup/sample/heartbeat bounds, original stop reserve and one poweroff
   issuer. No new lifetime, fallback owner, extra stop, restore, guest action,
   network activation or automatic retry follows from the static artifact.
   A partial unsealed process allocation closes without native commands; once
   armed, the original owner retains its original immutable lease and stop.

The operator would approve the exact action/input/budget policy before process
allocation. They would no longer approve actual live PIDs or absolute lease
timestamps in advance. Those become independently verified, retained outputs
of the trusted binder. **This changes the approval contract** and is why a new
decision is required under [AGENTS.md](../../AGENTS.md). A digest is a consistency
binding, not authentication against a hostile host; existing trust/ACL limits
must remain explicit.

Initial activation consent remains revocable before arming, with revocation and
consumption ordered durably. A stale worker or changed artifact cannot activate
after revocation. After arming, the current authority/fencing rules apply. An
unknown admission or acknowledgement never becomes permission to reconstruct a
new owner or perform another boot.

## Preserved maintenance-review boundary

[Decision 0003](0003-maintenance-same-boot-review.md) remains unchanged. Once the
VM is running, inspection, waiting for an actual current-boot report review and
approved controls all consume the same original lease. No answer, a late answer,
revocation or uncertainty still fences and stops. This proposal does not approve
a generic conditional guest plan or move that same-boot review outside the lease.

Normal stop acceptance also stays unchanged: original successful command receipt,
natural zero frontend exits, empty jobs/pipes and independent poweroff/unlocked
proof remain necessary. Aborted and abnormal termination remain held evidence.
Native controller-loss qualification stays a separate case with its narrower
containment result; it cannot grant restart or normal-stop acceptance.

## Required preparation checks

- Default artifact preparation makes zero native calls and creates no process,
  job or lease. Human delay alone cannot consume or extend an active VM lifetime.
- Changed case, target, source, binary, receipt, policy, output path or approval
  digest cannot cross the admission gate. Existing live-review formats retain
  their exact old semantics and cannot enter this new path accidentally.
- Concurrent activation, restart, alternate output paths, failed preflight,
  partial process construction and lost acknowledgements consume at most one
  admission. Unknown delivery creates a hold, never a new session or command.
- Actual Windows Python controller/owner/frontends demonstrate that identities
  and jobs bind before resume, the lease is immutable and at most 600 seconds
  from construction, and independent original-stop behavior survives failures.
- Unarmed inspection time and active execution clocks remain distinguishable.
  The startup, heartbeat and stop budgets still apply under both original clocks.
  A simulated long human/preflight delay must not renew a previously armed lease.
- Revocation before, during and after consumption/arming has one durable outcome.
  No command, installation, networking, native fault or VM boot is included in
  these tests. Native activation remains separately approved after reviewable
  preparation evidence exists.

## Alternatives and decision requested

Retain live-PID/absolute-expiry reviews and wait for the developer to be available
for each short window. This is the current behavior and remains valid until a
new design is approved and verified. Its observed intervention cost is recorded;
no lifetime limit is relaxed here to avoid that cost.

Recommended decision: **approve preparation of the inert-review/one-use-binding
model**, limited to implementation, Python surrogate tests and read-only checks.
No product implementation, dependency installation, paid experiment, remote
write or native activation is requested by this decision.
