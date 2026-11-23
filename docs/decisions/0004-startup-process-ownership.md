# Explicit startup process ownership

Status: **Direct frontend preparation approved, November 22, 2026.** The developer
selected “Approve direct frontend preparation” in the conversation. This concerns
fixture startup, not product architecture adoption. Implementation and Python
surrogate tests are authorized; no native boot is authorized.

## Problem and evidence

The current boot preconditions produce no dispatch permit. The historical
`VBoxManage startvm` path delegates a launch and waits on a progress object. A
bounded client exit or one poweroff observation does not establish that no startup
operation can finish later. An unqualified late start could outlive the owner's
single stop command.

Read-only inventory found installed `VBoxHeadless.exe` file/product version
`7.2.22.175245`, SHA-256
`e862a58b74c085306c5e8103529ddea1159e48862712cb5d4a68305c886fd51d`.
No frontend was launched. Oracle's
[VBoxHeadless source](https://raw.githubusercontent.com/VirtualBox/virtualbox/main/src/VBox/Frontends/VBoxHeadless/VBoxHeadless.cpp),
header revision **114470, June 22, 2026**, locks a VM session, requests power-up,
then runs an event loop. That source is not established as the installed binary's
exact source. Its process/COM failure behavior still requires native measurement.

## Recommended preparation

Prepare a direct, pinned `VBoxHeadless --startvm <UUID> --vrde off` launcher.
Create it suspended, already assigned to its own non-inheritable kill-on-close
Windows job. The controller retains the lifetime handle. No daemon or CLI launcher
may stand in for the actual runtime process family. Pin the executable,
environment, target/configuration/backup, original owner/lease and source cohort
before the one-use start intent and before primary-thread resume.

Keep the independent original owner and existing single `controlvm poweroff`
issuer. The frontend job supplies a second **process containment/termination
mechanism**, including controller death or an unsettled start. It is not a second
poweroff command and must never fabricate the original owner's command receipt.
If process termination races with that command, its nonzero/lost result remains a
hold even if later observation finds the VM off. No restart, lease renewal,
takeover or automatic replay follows.

Completion must require the exact frontend PID to terminate, the job/process and
bounded output collectors to be reaped, and fresh independent poweroff/configuration
observations. Startup readiness remains separate from guest readiness. Native
proof must establish that no detached/delayed startup survives frontend/job
termination; source review and Python surrogates cannot establish that property.

First prepare tests using Python frontends only: denial before owner readiness,
suspended gate failure, expiry/fencing during startup, delayed readiness,
controller death, output overflow, lost acknowledgement, nonzero exit and no
replay. Then prepare the exact native target run for separate approval.

## Alternative and recorded decision

Retain a COM progress-based starter and first qualify its cancellation/settlement
and session lifecycle, including non-cancelable and lost-handle paths. Do not use
CLI termination as the settlement proof. This avoids changing frontend ownership
but leaves the current native boot gate closed until those properties are proven.

The developer approved preparation of the direct frontend/job approach. The COM
progress design remains the alternative if native qualification contradicts the
prepared ownership assumptions.

## Source and measured follow-up to the initial process-count assumption

The initial one-process assumption does not describe Oracle's Windows hardening
path. [SUPR3HardenedMain-win.cpp](https://raw.githubusercontent.com/VirtualBox/virtualbox/main/src/VBox/HostDrivers/Support/win/SUPR3HardenedMain-win.cpp),
header revision **115205, September 8, 2026**, describes two respawns and a parent
waiting for child termination. This is source review, not an installed-build run.

Native Python surrogate tests on this host also found one console-helper process
per Python frontend. The prepared primitive therefore bounds a family to three
frontend processes plus at most three pinned `conhost.exe` helpers, six total.
The outer controller job allows twelve processes for the controller, family and
bounded query/transport workers. These are preparation limits; a native run must
review/freeze its actual process tree and identities separately. No helper is
ignored when proving cleanup, and unknown images or extra processes hold.

The private [process primitive](../../research/validation/frontend_process.py)
now measures this actual nested caller arrangement with Python processes, including
controller death and a separate bounded query. The later
[owner-bound adapter](../../research/validation/frontend-start-plan.md) adds exact
admission, durable one-use resume, a watchdog and a prepared runtime session-PID
join. Its 28 checks include seven actual Windows controller/owner cases; all VM
and session facts remain synthetic. A fixed native session observer and the
actual frontend/session/stop measurements remain required before activation.
