# Frontend process-family preparation

The developer approved [direct frontend preparation](../../docs/decisions/0004-startup-process-ownership.md).
[frontend_process.py](frontend_process.py) now supplies a private suspended-process
primitive, bounded pipes, family PID inventory and job retirement. Its CLI is a
zero-native-call preview. The later [owner-bound adapter](frontend-start-plan.md)
adds prepared admission and monitoring; neither preview authorizes a native run.

## Source findings and measured family

Read-only file inventory pins installed `VBoxHeadless.exe` at version
`7.2.22.175245`, SHA-256
`e862a58b74c085306c5e8103529ddea1159e48862712cb5d4a68305c886fd51d`.
Oracle's frontend source, header revision 114470, requests power-up and then pumps
events. Its Windows hardening source, revision 115205, describes two respawns and
parents waiting on children. These source observations are not installed-build
runtime qualification. Links and limitations are recorded in decision 0004.

The initial one-process assumption was therefore unsuitable. Native Python
surrogates on this host additionally produced one `conhost.exe` helper per frontend.
Early diagnostic attempts held on the unexpectedly larger PID inventory. The
prepared family now allows at most three frontend images and three helpers, six
processes total; the outer controller job allows twelve for the controller,
frontend family and bounded query/transport workers. Native runtime counts must
still be measured and explicitly frozen before a VM run.

Only the exact executable supplied by the trusted caller and the pinned system
`C:\Windows\System32\conhost.exe` are eligible family images. The observed helper
is file version `10.0.26100.10068`, SHA-256
`0afce92d925a7ef2ae27c088e9416c52c762979c9ceb8dfca46371afa8c6bd83`.
Extra/unknown images, excessive counts or an incomplete PID list hold. The helper
is included in cleanup evidence. This is a preparation pin, not a promise that
every other Windows host has the same helper or process behavior.

## Process guarantees measured with Python

Creation assigns the root to its non-inheritable kill-on-close job before its
primary thread can run. Only null stdin and bounded output handles are inherited.
A callable gate runs before the one permitted resume. Output is bounded to 64 KiB
per stream. Retirement checks root termination, the entire job's process count/PID
list and both pipe collectors. A retired family is reported as process cleanup,
never proof of VM poweroff or startup settlement.

Eight native Windows checks pass. They cover a real controller inside its outer
job creating three frontend surrogates and a separate bounded query; normal exit;
abrupt controller exit; outer-job termination; a denied suspended gate; output
overflow; delayed execution and one-shot resume; unexpected images/counts; and
retention of a nonzero root exit. Native helpers are observed and reaped alongside
the surrogates. No VirtualBox frontend or VM was launched by these tests. See
[frontend-process-evidence.json](frontend-process-evidence.json).

## Next integration check

The [owner-bound adapter](frontend-start-plan.md) now connects those inputs and
monitors authority, process/output faults and runtime identity. Its 28 additional
checks use Python surrogates and synthetic VM/session facts. The sole VM poweroff
command remains with the independent original owner; job retirement cannot
fabricate or accept its ledger receipt. A native session observer and concrete
startup/stop qualification remain next.

Native qualification must identify the actual VM session PID among the hardened
family, establish no detached/delayed runtime survives retirement, and obtain
independent stopped-state evidence. Caller job/PID admission, DLL loading, host
ACLs, serial/root-session ownership, readiness and stop timing still require their
actual target measurements. Surrogate success alone does not open a native boot gate.
