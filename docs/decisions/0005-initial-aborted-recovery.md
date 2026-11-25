# Explicit initial-Aborted recovery preparation

Latest checkpoint, November 24: a later separately approved
[joined-controller-loss run](../../research/validation/guard-controller-loss-evidence.json)
left the guard Aborted/unlocked and its original stop held. Review 10 and context
V3 below are historical. [Decision 0007](0007-held-guard-successor.md) now proposes
complete successor provenance and explicit reservation ownership; it is not yet
approved. Do not reuse the older current-profile claims below for admission.

The later separately approved [review 10](../../research/validation/guard-startup-normal-stop-evidence.json)
completed one normal guard startup/session/stop case from the explicit Aborted
initial state. Both VMs were then off/unlocked. Its successful stop does not repair
the earlier failures, qualify failure cases or authorize another activation.
The guard's new NVRAM/shutdown metadata also make capture 06 historical.

Current verified follow-up uses context V3 and the exact post-review-07 guard
metadata. It adds the latest orphan receipt as failure evidence and requires
fresh retirement proof for every retained creation. V1/V2 remain historical and
cannot be relabeled. The approved guard-only initial state, original clocks,
normal poweroff acceptance and separate native-approval boundary are unchanged.
See [journal preparation](../../research/validation/controller-journal-plan.md)
and [current evidence](../../research/validation/controller-journal-evidence.json).

Status: **Preparation approved, November 23, 2026.** The developer selected
“Approve recovery-model preparation” in the conversation. Implementation,
Python tests, read-only inventory and unattached backup capture are authorized.
Any native activation needs a later exact review. The [preparation implementation](../../research/validation/initial-aborted-plan.md)
now has typed records, capture, distinct recovery admission/review and focused
tests. Regression passed 502 checks with 13 platform skips (515 total); actual
unattached capture, separate-process backup readback and read-only preflight also
passed. See [preparation evidence](../../research/validation/initial-aborted-evidence.json).
Native activation remains separately gated. Ordinary poweroff-only
admission and normal shutdown acceptance keep their original requirements.

The later separately approved [native recovery attempt](../../research/validation/guard-startup-lock-hold-evidence.json)
held at the session lock, with no running sample qualified and one failed original
stop. Its review is consumed. All backing files remain unchanged; this decision
does not authorize replay or silently omit that new attempt from successor recovery provenance.

Continued preparation now uses context version 2, which requires both consumed
reviews, the new attempt's failed stop/every retained process, its unchanged
post-run backing files and the exact historical parent context. Version 1 stays
retained as history and cannot be relabeled for admission. This adds required
evidence within the same guard-only initial-state model; it adds no native
authority, state fallback, retry or deadline extension. Combined verification,
fresh unattached capture/readback and read-only preflight are recorded in
[current preparation evidence](../../research/validation/startup-session-probe-evidence.json).

The separately approved [review 07](../../research/validation/guard-startup-journal-hold-evidence.json)
later reached Running but failed while committing its session journal. Its sole
original stop failed and remains held. All processes retired and disks stayed
unchanged, but guard timestamp metadata changed. Context V2/capture 04 now predate
this consumed attempt and cannot be reused for admission. Any successor must bind
its new provenance/profile and receive another exact native approval.

## Problem and measured evidence

Approved native review
`98fa65d7365578352207992992a1d25ab8cf37dbf918d17e5f75aefd5c53ae6e`
resumed one guard frontend. A retained CLI display value caused a parser failure
while the COM session was still `Spawning`. Containment terminated the family.
The original owner's sole stop exited 1, reporting that the machine was not
currently running. Its journal stays held; no successful stop receipt exists.

The guard now reports `aborted` with an `Unlocked` session/PID zero. All original
Python identities and the frontend root are independently retired; both native
process jobs were empty. Both disks retain their original hashes. Guard NVRAM is
absent. Only its configuration's abort/time metadata changed; the executor's
configuration/NVRAM are unchanged. See [measured evidence](../../research/validation/guard-startup-parser-hold-evidence.json).

Current poweroff-only admission correctly rejects this state and the changed
configuration. Changing that boundary is a major decision under [AGENTS.md](../../AGENTS.md).
The parser repair alone supplies no recovery or native authority.

## Recommended preparation

Prepare one explicit initial-state path for the fixed guard, with these rules:

1. Bind a recovery context to the consumed review, original start/stop records,
   retained nonzero stop result, process-retirement proof and current bytes.
   Obtain two fresh consistent `Aborted`/`Unlocked`/PID-zero observations around
   capture. Require the same VM/disk UUIDs, approved hardware, disabled NICs and
   sharing transports, and the preserved executor off/unlocked and unchanged.
   Reject saved-state references, other offline states and unknown observations.
2. Capture a new independent, unattached byte-copy backup and current profile.
   Use a new versioned receipt that states `source_machine_state: aborted` and
   records the unlocked-session proof. Existing v2 receipts retain their literal
   `source_poweroff: true` meaning and are never rewritten or relabeled.
3. Bind the exact initial state and recovery context into the new guard grant
   and live review. Ordinary grants continue to require `poweroff`; no generic
   caller-controlled allowlist or fallback can admit `aborted`. All current
   file locks, image/source pins, one-use intents and clock checks still apply.
4. Permit only initial `aborted → starting → running` observation progress under
   that explicit grant. Initial waiting cannot join a session or dispatch work.
   Require the same stable locked-session PID/family join. Regression, an abort
   after joining, drift, expired authority or uncertain cleanup still holds.
5. Keep normal stop acceptance unchanged: the new original owner's single
   successful command, natural family exit and two fresh `poweroff`/`Unlocked`
   observations remain necessary. `Aborted` never substitutes for successful
   shutdown. Neither this decision nor a later success repairs the prior stop.

No VM configuration edit, restore, saved-state discard, installation, network
activation, extra stop or automatic boot is part of preparation. A later exact
native review must disclose starting from the measured aborted state and bind
the new receipts, source cohort, processes and immutable 600-second lease.
Existing admission/startup/sample/stop bounds stay unchanged.

## Source review and alternatives

Oracle's [Main API declaration](https://raw.githubusercontent.com/VirtualBox/virtualbox/main/src/VBox/Main/idl/VirtualBox.xidl)
defines `Aborted` as abnormal termination of the VM process. This supports
recording an explicit failure state; it does not prove guest integrity or an
accepted stop. The installed VM observations above are separate measured facts.

In [MachineImpl.cpp](https://raw.githubusercontent.com/VirtualBox/virtualbox/main/src/VBox/Main/src-server/MachineImpl.cpp),
header revision **114362, June 15, 2026**, `SessionMachine::discardSavedState`
requires `Saved` or `AbortedSaved`, so source review does not justify issuing
`discardstate` to this `Aborted` VM. Exact installed/source correspondence is
unknown. No such command has run.

An alternative is a separately approved replacement guard or stopped restore.
That changes VM/storage state and requires its own concrete plan. The recommended
path preserves the observed failure state and original evidence while preparing
an explicit later recovery attempt.

## Validation before a native review

Tests must cover ordinary-path refusal, guard-only recovery binding, mismatched
prior attempts/receipts, live or inaccessible old processes, saved/teleported or
unknown states, drift during backup, backward runtime transitions, unchanged
lease/deadlines, failed/lost acknowledgements and replay. They must prove that
`Aborted` remains invalid for normal stop acceptance. Actual read-only capture
and independent backup readback remain separate from synthetic VM facts.

Native startup/session/stop qualification, failure-case settlement, guest
readiness, UART ownership, installation/isolation and the product remain open.
