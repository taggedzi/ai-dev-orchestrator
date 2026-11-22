# Maintenance host observations and original-owner handoff

[maintenance_host.py](maintenance_host.py) prepares a live-state collector,
durable original-owner registration and a stop observer for the
[transfer controller](transfer-plan.md). [windows_readonly.py](windows_readonly.py)
supplies bounded Windows query processes. There is no native activation CLI.
Default preview performs zero native calls. The review packets remain unarmed;
no VM boot, setting change, guest command or native poweroff was performed.

| Role | Current local packet | Raw adapter-contract SHA-256 |
| --- | --- | --- |
| Guard | `.local/validation/host-adapter-guard-02` | `1ee821c1dbd5b8c57d3e38faae9dffb2c764bed9e7ff500b22612258bd3c1e36` |
| Executor | `.local/validation/host-adapter-executor-02` | `1c09e39164d6e4b68f5ab9735ebd6b60306e3a5a2393d1bd4e6cc8a7186b9445` |

Owner, actual backup/preboot/source receipts and native approvals are empty. Guard
disk identity remains unmeasured. These source snapshots are review inputs, not
complete deployable host packages. Earlier adapter revision 01 remains intact.

The corresponding four unarmed transfer grants are now revision **03**:

| Role / purpose | Raw grant SHA-256 |
| --- | --- |
| Guard / inspect | `11f4b1813c2c42defe5f2c5acb7bc34573ddd8544b2d74734ac2cfa48e4c92b2` |
| Guard / controls | `e0e5fb445d8d9cea784f0744d76749a27bc6c0ef59ec28de04f0e6d2262cc941` |
| Executor / inspect | `d0bf59483073d1c4e92174af64c2c4e0aafe13926ce4f70a09fd2b3d3c86f342` |
| Executor / controls | `6b5eb74a7821189713770bd4cb7d72ad8e65dbabf593280e7217fc74251acb73` |

Each lives in `.local/validation/transfer-<role>-<purpose>-03` and refuses with
`transfer approval is unbound`. Revision 02 remains historical. The new transport
SHA-256 is `63fe667d48a538c95ea3c1092547fc4a9687419d5faa1acced37552894cbcbe9`;
probe, controls, compiler, entry and serial-worker source pins are unchanged.
The older transfer template's collector flag remains false; the prepared adapters
are separate inputs, and actual receipt producers/independent launch remain absent.

## Native query boundary

The public query API permits only the pinned executable's version, machine-readable
`showvminfo` for a reviewed UUID, and `showmediuminfo disk` for a reviewed UUID.
The executable is the absolute installed VBoxManage path, with its raw SHA-256
checked before each query; `VBOX_USER_HOME` overrides refuse. Arguments are passed
directly to Windows, with no host shell. The observed executable is VirtualBox
`7.2.22r175245`, SHA-256
`178e016ed38cb6e369a5c17c6c960c176674b9c864030d8ce0ad2867613becff`.
The dependency/DLL load path still needs qualification.

Each process is created suspended **already assigned** to a non-inheritable,
one-process kill-on-close Job Object. Windows' creation-time job-list attribute
avoids a separate assignment window if the parent dies. Only the null-input and
two output handles are inherited. Resume follows membership and deadline checks.
Output is bounded to 64 KiB per stream; the original wall/monotonic query deadline
is at most four seconds. A process signal alone is insufficient: both streams
and the Job Object count must be reaped. Cleanup has separate bounded waits;
kernel stalls and physical power loss remain unqualified. See Microsoft's
[process attributes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute),
[creation flags](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags)
and [Job Object documentation](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).

The collector brackets the disk query with two VM observations under one deadline.
It requires the exact role/CPU/memory, one expected base VDI at the fixed path,
no mounted optical medium, all eight NICs disabled, no shares, and the selected
UART pipe. Missing/duplicate fields and unsupported storage arrangements hold.
All configured/global/transient shared-folder records are denied. A stopped VM
with UART off can be parsed diagnostically but cannot satisfy running admission.

Oracle documents the query commands in its
[7.2 CLI reference](https://docs.oracle.com/en/virtualization/virtualbox/7.2/user/vboxmanage.html).
Source review of Oracle's
[VBoxManageInfo.cpp](https://raw.githubusercontent.com/VirtualBox/virtualbox/master/src/VBox/Frontends/VBoxManage/VBoxManageInfo.cpp),
header revision **114362, June 15, 2026**, identifies the raw, unescaped UART-mode
printf and the machine-readable storage/shared-folder fields. That upstream source
is not established as the installed binary's exact source revision. The parser
handles the observed recording section marker without shell evaluation. Enabled
UART output is source-derived and synthetic-tested, not natively measured.

## Owner and receipt binding

`RegisteredOwner` wraps the existing `LeaseSupervisor.poll`; it adds no second
poweroff command. It records its own PID, creation FILETIME, executable image,
owner nonce and original immutable lease fields in the same Store. Registration
cannot replace an existing owner or revive expired/fenced/extended authority.
The owning process must poll this wrapper, not bypass it using the older watch
loop. A possibly sent stop or a failed owner loop cannot be retried by this object.

The live adapter requires a **different process** as owner. It compares the
externally pinned binding, original Store row, fresh heartbeat and a live Windows
process handle with matching creation identity/image. This checks PID reuse and
liveness; it does not prove what code a trusted host process is executing. Host
ACLs, startup independence and approval authentication still need qualification.
The adapter does not start or reconstitute that owner.

Three proposed receipt formats bind an independent stopped backup, the target's
preboot disk and preserved source bytes. Exact raw receipt hashes and target/run
fields must match the grant. Backup disk/configuration/NVRAM hashes remain separate
from the live target's storage identity. These receipts have only synthetic
producers so far: parsing one does not freshly hash a disk or authenticate its
issuer. Genuine backup and scoped native approvals are still missing.

Read transactions use separate read-only SQLite connections with a 50 ms lock
timeout. A capture's timestamp starts before its native queries. It cannot refresh
an old sample after a blocked call. Exclusive intent/raw-query/capture files are
retained, with at most 256 captures; reuse, count exhaustion or overlapping captures
hold. The existing transfer monitor still enforces freshness, revocation and
its one-second initial-sample wait. A slow native startup therefore refuses; this
checkpoint does not extend that wait or original phase deadlines.

## Stop handoff

The controller's durable fence is the stop signal observed by the original owner.
The adapter first records its own exclusive wait intent. It requires the bound
controller stop state, original immutable owner/lease, and both original ledger
and owner wrapper reporting that the one-shot stop command returned. An owner
acknowledgement is not poweroff. Read-only observation may then wait for shutdown,
checking unchanged hardware and authority without issuing another stop.

Only a fresh independent poweroff capture produces the existing transfer receipt
shape. The adapter keeps its wait/capture budget within nine seconds and the
original lease's ten-second stop allowance; it cannot renew either deadline.
Missing evidence, changed authority, reboot or uncertainty remains a hold.

This is a prepared adapter, not qualified native shutdown. The old native stop
command still needs bounded-output/process qualification. Independent startup,
owner survival after controller death, actual running/UART collection and the
complete ten-second stop path have not been measured on the selected VM.

## Measurements and remaining gates

The first scratch-process check held because Job Object accounting had not yet
converged after process exit. Its source and receipt remain intact. A bounded
accounting wait fixed that case. The native Windows checks now cover a suspended
execution gate, output/timeout bounds, descendant denial, PID identity and parent
death before primary-thread resume. Controller, owner and VM observations in the
integration tests remain synthetic; those checks never issue a VBox poweroff.

A separate read-only native attempt held in the sandbox after version succeeded
and the COM-backed VM query timed out. The independently approved retry outside
the sandbox completed all four queries in **0.369 seconds**. Both VM observations
agreed: powered off, two CPUs, 4096 MiB, one base VDI, eight disabled NICs, no shares,
USB/clipboard/drag-and-drop disabled, UART off. This did not hash current VDI bytes
or establish a running maintenance lease, root session or stop measurement.
The exact retained source cohort and unchanged parser-function comparisons are
recorded in [evidence](host-adapter-evidence.json).

The final Windows regression passed **271 tests: 258 passed, 13 platform skips**.
All **23 host-adapter checks** passed, including five native Windows scratch-process
cases; the other 18 use synthetic data/authority. All 20 serial checks passed,
including a new delayed-accounting case against an actual local pipe/worker.
The first full run retained five sandbox PowerShell-launch errors and the serial
accounting failure. After fixing the latter and obtaining outside-sandbox command
approval for the former, the separate final run passed. No native VM mutation was
substituted for a synthetic refusal test.

Next, qualify bounded execution of the original owner's stop command and prepare
its complete independently supervised launch packet. The
[same-boot review proposal](../../docs/decisions/0003-maintenance-same-boot-review.md)
also needs developer selection before session changes. Current inspection attempts
still always stop; the new adapters do not make a stopped boot's observation usable
for later controls. Guard creation, broker phase policy, installation and final
M1-11 through M1-14 qualifications remain open.
