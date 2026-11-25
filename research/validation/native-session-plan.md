# Bounded native session observer

The later [review 10](guard-startup-normal-stop-evidence.json) measured the exact
native running session-PID join and normal stop. A subsequent separately approved
[controller-loss run](guard-controller-loss-evidence.json) measured containment
in 2.668 seconds. Its original stop failed and remains held; guard is now
Aborted/unlocked/PID-zero, executor poweroff/unlocked/PID-zero. No retry ran.
The earlier stopped backup/profile predates this fault and cannot admit it.
Earlier observations below retain their historical scope; guest readiness and
broader native failure cases remain unqualified.

[native_session.py](native_session.py) reads the two dedicated preparation VMs.
Its default CLI is an inert preview. `--observe` makes read-only queries and
retains bounded raw output; it has no VM launch, lock, poweroff, guest-command or
configuration method. No dependency was installed.

The observer pins the existing VBoxManage executable and Windows PowerShell
`10.0.26100.9818`, SHA-256
`95ce2acbc6cd9d7f4a22759d39a8d40fc2a53ceeecf068ef856849f0d2076961`.
A fixed PowerShell command accesses `VirtualBox.VirtualBox`, finds one fixed VM
UUID, and reads version/revision, machine/session states and the session PID.
It reads that PID only when the first session state is `Locked`; a second state
read must agree. There is no caller-supplied script or arbitrary target.

The whole sequence—machine, medium, session, machine—shares one four-second
deadline on both clocks. Every process has bounded output and job/pipe cleanup.
The oldest observation timestamp accompanies the final frame. Machine profile,
firmware/boot fields, disk identity and COM machine state must agree. Changed
states, source/binary pins, stderr, timeout, unknown output or incomplete cleanup
hold without retry. The controller independently joins a valid running session
PID to its exact live frontend family; the observer alone supplies no authority.

## Measurements and limits

The installed COM server reports `7.2.22`, revision `175245`. Both actual VMs
were observed powered off, with `Unlocked` before/after and PID zero. The guard
sequence took about 1.30 seconds; the executor also finished within four seconds.
All query jobs were empty afterward. The initial sandboxed guard query timed out
and was reaped; the same read-only observation succeeded outside the sandbox.
The command prefix was approved for this bounded observer. No frontend or VM ran.

Raw evidence is retained in `.local/validation/native-session-guard-01` (initial
sandbox hold), `native-session-guard-02` and `native-session-executor-01`.
The original nine conformance checks cover fixed commands/deadlines, stable and conflicting
states/PIDs, numeric types, native failures, missing cleanup, source/configuration
drift and retained partial observations. VM facts in those tests are synthetic.

Oracle's [Main API declaration](https://raw.githubusercontent.com/VirtualBox/virtualbox/main/src/VBox/Main/idl/VirtualBox.xidl)
documents `sessionPID` validity under `Locked` or `Unlocking` state. Preparation
requires `Locked` for a runtime join. The upstream source's exact correspondence
to the installed binary remains unknown; installed-build stopped behavior is
measured separately above. Running-state behavior, actual hardening descendants,
late/detached startup, guest readiness and native stop timing remain unqualified.

The next native check needs a fresh exact [one-boot guard review](startup-qualification-plan.md).

## COM-only waiting before runtime profile reads

The approved [recovery attempt held at the session lock](guard-startup-lock-hold-evidence.json).
Source review of Oracle's [showvminfo implementation](https://raw.githubusercontent.com/VirtualBox/virtualbox/main/src/VBox/Frontends/VBoxManage/VBoxManageInfo.cpp),
header revision 114362 (June 15, 2026), shows `LockMachine(LockType_Shared)` around
its profile reads. [VBoxHeadless](https://raw.githubusercontent.com/VirtualBox/virtualbox/main/src/VBox/Frontends/VBoxHeadless/VBoxHeadless.cpp),
revision 114470 (June 22, 2026), needs `LockType_VM` before power-up. Exact installed
lock ownership/timing is unmeasured, so polling interference remains a hypothesis.

The corrected controller first uses `startup_session()`: only the existing bounded
COM property script runs, with no CLI query or VM session-lock request. A separate
typed probe is checked against the original authority, clocks, forward-only state
progress and exact live pinned frontend family. Only a stable `Locked` session in
`starting` or `running` with that family's PID allows the full CLI profile read.
A probe cannot join, publish a session receipt, count as a running sample or
authorize guest work. Full target/profile/storage checks still precede any join.
After joining, the strict full observer remains in use.

Waiting consumes the unchanged fifteen-second startup bound and ten-second sample
window under the original lease; every probe retains the four-second query bound.
No retry, sleep-based launch assumption or lease extension was added. Actual
COM-only measurements observed guard aborted/unlocked and executor poweroff/unlocked
with PID zero, using zero CLI queries. This measures offline probe behavior only.
The [combined evidence](startup-session-probe-evidence.json) records 533 tests:
520 passed, 13 platform skips, no failures/errors, plus fresh backup/readback and
read-only preflight. Native startup/stop remains unqualified.

The later separately approved [native run](guard-startup-journal-hold-evidence.json)
used those probes and reached a stable Running/Locked session with PID 4424 in
the exact frontend family. SQLite failed while committing its join; the published
filesystem receipt remained provisional and no running sample was accepted.
This is measured running observation, not completed startup/stop qualification or
guest readiness. The consumed attempt was contained and cannot be replayed.

## Initial startup collection

The private `startup_observation()` path permits only forward observations along
`poweroff → starting → running` and `Unlocked → Spawning → Locked`. It marks
changing reads, spawning sessions and running-without-locked-identity as wait-only.
The adapter checks the exact granted target/profile/storage, timestamp, family PID
and progress across successive frames. A wait cannot join the session, publish a
session receipt, count as a running sample or authorize guest work. The next stable
locked running frame still needs the exact family PID join.

The four-second query bound, fifteen-second startup bound, ten-second sample
window and original lease stay fixed. Query failure, unknown/backward state or
profile drift still holds. Default/CLI observation, preactivation and independent
stop acceptance retain their strict unchanged-state checks. This is preparation
based on source review, not a diagnosis of either consumed native attempt.
Eight additional cross-layer checks and the full 452-pass regression are retained
in [startup progress evidence](startup-progress-evidence.json), alongside a fresh
actual read-only preflight. No native running session is qualified by those tests.

The later approved review `98fa65d7365578352207992992a1d25ab8cf37dbf918d17e5f75aefd5c53ae6e`
reached a spawning session and held on installed CLI diagnostics. Its retained
`VideoMode="0,0,0"@0,0 1` is a composite value, and `VRDEClients==0` contains
two equals signs. Oracle's linked formatter (revision 114362) emits both forms.
The parser now accepts only their explicit bounded numeric grammars, preserving
duplicate-key and transport/profile checks. Offline replay of the exact retained
bytes produces a wait-only spawning frame; it cannot prove native readiness.
See [held-run evidence](guard-startup-parser-hold-evidence.json).

The guard is now aborted/unlocked and its configuration records the abort; the
old poweroff-only gate remains closed. See [proposed recovery preparation](../../docs/decisions/0005-initial-aborted-recovery.md).

The first approved qualification session later held before controller activation
on its first read-only query; its original stop result stayed unknown. Both VMs
and all backing files were independently unchanged. The successor preactivation
phase now places fixed read-only checks ahead of owner activation, with retained
raw output and no native stop on an early hold. Standalone checks and an actual
Python-owner/job/real-file-lock context passed; the initial timeout cause remains
unproven. See [held-session evidence](guard-startup-hold-evidence.json).
