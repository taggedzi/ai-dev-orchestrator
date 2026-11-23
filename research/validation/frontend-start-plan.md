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

Retirement contains the process family before attempting a potentially broken
journal write, then fences the original authority and records cleanup. Only the
independent original owner can issue the VM poweroff command. Process cleanup
does not accept that command, prove VM poweroff, or settle a late/detached start.
A raced, nonzero or lost original stop result remains held.

Twenty-eight focused checks pass. Seven run the actual Windows controller/job
and independent owner with three Python frontend processes and bounded query
workers. Four exercise actual original-file sharing locks with synthetic disk
bytes. The remaining checks inject authority, journal, observation and resume
failures. Coverage includes final-gate revocation, controller death, output flood,
unanswered session identity, the unchanged original stop reserve, lost resume
acknowledgement, lost original-stop acknowledgement, replay and runtime heartbeat
loss. No VirtualBox frontend was launched; VM and session facts are synthetic.

## Native qualification still required

Oracle's [Main API declaration](https://raw.githubusercontent.com/VirtualBox/virtualbox/main/src/VBox/Main/idl/VirtualBox.xidl)
documents `IMachine.sessionPID` as valid only under `Locked` or `Unlocking` session
state. This adapter deliberately requires `Locked`. The source review does not
qualify a reader against the installed build. The reviewed
[VBoxManageInfo.cpp](https://raw.githubusercontent.com/VirtualBox/virtualbox/main/src/VBox/Frontends/VBoxManage/VBoxManageInfo.cpp),
header revision **114362, June 15, 2026**, supplies no `SessionPID` output field;
the adapter must not invent one from `showvminfo`.

Next prepare a fixed bounded read-only native session observer and the concrete
controller/owner qualification run. Freeze real executable dependencies, current
inputs and stop/cleanup timing before requesting approval. Measure actual
hardening descendants, the runtime session-PID join, and whether any delayed or
detached runtime survives retirement. Then require independent stopped-state and
original-stop evidence. The conservative current retirement path can race the
original poweroff; that race remains a hold, never a successful stop. Actual
readiness, UART/root-session collection and installation remain separate gates.
