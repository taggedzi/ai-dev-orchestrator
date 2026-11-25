# Original-owner-bound frontend preparation

The developer's [decision 0004 approval](../../docs/decisions/0004-startup-process-ownership.md)
covers this implementation and Python surrogate tests. It does not authorize a
VirtualBox frontend, VM boot, guest command or network activation. The
[private adapter](frontend_start.py) has a zero-native-call draft CLI; it is not
an operator-facing run command. See [the retained evidence](frontend-start-evidence.json).

## Admission and one-use execution

The exact start grant includes the original boot packet, stopped-profile receipt,
frontend executable/environment, fixed process limits, source cohort and a
separate native-run approval field. Existing preparation approvals cannot fill
that field for a native run. Only the actual controller PID inside the existing
twelve-process job is eligible. The live independent owner, ready proof,
original Store, immutable lease, generation and ten-second stop reserve must
agree before intent and again while the frontend is suspended.

Version-2 backup records are required. The adapter rehashes the independent
backup files and holds the current target disk/configuration/firmware under
Windows read-sharing locks. Guard admission also measures and holds the stopped
executor source disk. It checks the exact current configuration and two equal
stopped inventories against the approved profile. Explicit absent firmware state
is checked again at the final gate. Slow reads consume the original admission
window; they do not extend it.

Exclusive filesystem and SQLite start intents precede process creation. A second
exclusive intent and durable `possible-resume` journal state precede the one
primary-thread resume. Lost acknowledgement leaves that consumed state and
retires the process family. Deleting a journal row cannot erase the filesystem
intent. There is no start/restart retry or lease renewal. File locks are released
at the final suspended gate so VirtualBox can open the disk and update its own
configuration; these are not hypervisor-wide configuration locks.

## Monitoring and runtime identity

An independent controller thread checks the same original authority, live process
identities, job limits, source cohort, journal, family inventory and output faults.
It runs while the caller collects runtime observations. Startup must establish
session identity within fifteen seconds and before the original stop reserve.
After joining, fresh runtime observations are required at least every five seconds.

A trusted bounded observer supplies raw machine/medium bytes and a session-PID
read bracketed by session-state reads. A running VM requires both states to be
`Locked` and its session PID to match one exact frontend-family identity, including
PID creation time and image. Changed/foreign PIDs, unlocked or stale observations,
configuration drift and missing heartbeats retire the family. A successful join
publishes `runtime-session-bound-not-guest-ready`; it grants no guest dispatch.

The post-admission owner monitor checks the original lease directly. It does not
extend the expired admission window or allow that window to admit another start.
The existing boot-precondition command still produces no dispatch permit.

## Retirement and measured checks

For startup uncertainty, retirement contains the process family before attempting a potentially broken
journal write, then fences the original authority and records cleanup. Only the
independent original owner can issue the VM poweroff command. Process cleanup
does not accept that command, prove VM poweroff, or settle a late/detached start.
A raced, nonzero or lost original stop result remains held.

Retirement now also retains the bounded frontend stdout/stderr bytes after
containment and fencing. Their lengths/hashes must match the reaped primitive's
cleanup evidence. Exclusive publication failure preserves existing files and
holds; it cannot delay physical containment, retry execution or accept a stop.

The later [one-boot qualification preparation](startup-qualification-plan.md) adds
normal finish after a verified join: one durable stop request/fence asks the
original owner to act, while the controller retains containment for at most four
seconds under the unchanged original lease. Natural zero family exit is required.
Unknown acknowledgement, source/authority/binding drift or expiry retires the
family and remains held. This path issues no VM command and accepts no stop itself.
Seven additional checks, including two actual Windows original-owner cases, pass.

Normal finish retains query/synchronize handles for every validated family member,
binding each handle to its observed creation time. It checks those handles for exit
instead of repeating image-name queries while known processes terminate. Microsoft
[documents the lifetime of a retained process object and PID](https://devblogs.microsoft.com/oldnewthing/20110107-00/?p=11803/).
Running/startup monitoring still requires fresh identities. New or unreadable
unproven members, unknown wait results and nonzero frontend exit remain holds.
The cumulative inventory stays within three frontend and three pinned helper
identities; cleanup closes all retained handles. These changes grant no VM action
and leave original-stop acceptance and independent poweroff checks unchanged.

Twenty-eight focused checks pass. Seven run the actual Windows controller/job
and independent owner with three Python frontend processes and bounded query
workers. Four exercise actual original-file sharing locks with synthetic disk
bytes. The remaining checks inject authority, journal, observation and resume
failures. Coverage includes final-gate revocation, controller death, output flood,
unanswered session identity, the unchanged original stop reserve, lost resume
acknowledgement, lost original-stop acknowledgement, replay and runtime heartbeat
loss. No VirtualBox frontend was launched; VM and session facts are synthetic.

## Native normal case measured; further cases remain

The separately approved [review 10](guard-startup-normal-stop-evidence.json)
measured a committed exact native session-PID binding, two accepted running
samples, the original owner's sole successful stop and natural zero exits for
all four retained frontend/helper processes. Two independent poweroff/unlocked
observations completed within 2.597 seconds of the stop request. This qualifies
only that normal case. Native loss/late/detached/failure cases, guest readiness
and UART/root-session ownership remain open. Historical failed stops are not
repaired; no further native authority remains.

The later [controller journal correction](controller-journal-plan.md) reproduces
real SQLite writer contention. Confirmed BEGIN non-entry may wait within one
second and the original clocks; body/COMMIT/native commands are not replayed.
A committed binding now precedes receipt publication and in-memory acceptance.
Bounded phase/error traces are retained after containment. The full 556-check
cohort (543 passed, 13 platform skips) includes an independent writer process
with the actual Windows controller/original-owner/Python-family surrogate. These
checks grant no native startup/stop or guest-readiness qualification.

Oracle's [Main API declaration](https://raw.githubusercontent.com/VirtualBox/virtualbox/main/src/VBox/Main/idl/VirtualBox.xidl)
documents `IMachine.sessionPID` as valid only under `Locked` or `Unlocking` session
state. This adapter deliberately requires `Locked`. The source review does not
qualify a reader against the installed build. The reviewed
[VBoxManageInfo.cpp](https://raw.githubusercontent.com/VirtualBox/virtualbox/main/src/VBox/Frontends/VBoxManage/VBoxManageInfo.cpp),
header revision **114362, June 15, 2026**, supplies no `SessionPID` output field;
the adapter must not invent one from `showvminfo`.

The [native observer](native-session-plan.md) and concrete
[controller/owner qualification](startup-qualification-plan.md) are now prepared.
The observer's actual stopped-state queries passed; running facts in preparation
tests remain synthetic. Freeze real executable dependencies, current
inputs and stop/cleanup timing before requesting approval. Measure actual
hardening descendants, the runtime session-PID join, and whether any delayed or
detached runtime survives retirement. Then require independent stopped-state and
original-stop evidence. The conservative current retirement path can race the
original poweroff; that race remains a hold, never a successful stop. Actual
readiness, UART/root-session collection and installation remain separate gates.
