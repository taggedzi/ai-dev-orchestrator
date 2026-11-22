# Bounded serial worker preparation

The [guest inspection stage](guest-maintenance-plan.md) now has a Windows serial
I/O primitive with native **local synthetic pipe/process** evidence. It does not
configure a VM, authenticate a root session, generate guest commands or execute
guest control changes. The two prepared guest requests remain unarmed. This is
fixture preparation; VM admission and final runtime qualification remain open.

## Frozen review artifacts

| Role | Local directory | Raw request SHA-256 |
| --- | --- | --- |
| Guard | `.local/validation/maintenance-serial-guard-02` | `606ad15def332ca2d7cb1b23d9e4406a447b50630aef669f7a2131d02f0c6f12` |
| Executor | `.local/validation/maintenance-serial-executor-02` | `1c5c708cca58d7790d07e98dd64a4d0a878287da7f2d155a1b5af2ae31103039` |

Each directory has exactly four files: request, review, parent source and worker
source. Both 364-byte request files refuse with `serial activation is unbound`.
Their activation reference, nonce and deadlines are null, and command steps are
empty. Revision 01 remains intact. Revision 02 requires the worker's exact named
Job Object before connecting. File hashes and test receipts are in the
[evidence](maintenance-serial-evidence.json).

[maintenance_serial.py](maintenance_serial.py) previews by default. `--prepare`
creates a new review directory; neither option opens a native pipe or changes a
VM. [maintenance_serial_worker.py](maintenance_serial_worker.py) is standalone
and also previews by default. Its internal worker entry point requires a complete
hash-bound stdin request and matching configured Job Object before pipe I/O.
There is no login or password handler.

## What the boundary enforces

The original console client performs blocking writes in its caller. Here, the
parent puts all native serial I/O in a separate process. Before sending the stdin
start gate, it assigns the worker to a fresh non-inheritable Job Object with
kill-on-close and an active-process limit of one. Existing job names hold. The
worker opens its exact named job, verifies membership/limits, then closes that
query handle before connecting; retaining it would defeat parent-death cleanup.

Microsoft documents that closing the final kill-on-close job handle terminates
associated processes, and describes job assignment and inherited membership in
its [Job Objects overview](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
and [basic-limit structure reference](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_limit_information).
These are source expectations; the local native checks below test selected
behaviors on this host.

Requests bind raw bytes, worker-source hash, nonce, local pipe name, exact ordered
steps and absolute wall/host-monotonic deadlines. The parent admits at most a
90-second exchange window and polls deadline/revocation while I/O runs. Cleanup
uses a bounded process wait and stream-thread joins. This does not renew the
outside-VM lease. Python documents the shared process clock semantics of
[monotonic time](https://docs.python.org/3.13/library/time.html#time.monotonic);
the guest's clock remains a separate domain.

Guest-mode pipe names bind only the two selected fixture UUIDs. Local-test names
use a separate nonce namespace and no VM target. Full requests are limited to
256 KiB and 128 steps. Each sent line is printable ASCII, at most 2,047 characters
plus carriage return. No shell runs on the host.

Acknowledgements must occupy their own complete line and match nonce/step order;
an echoed command containing the token cannot acknowledge it. Duplicate or
out-of-order tokens hold. The worker hashes at most 2 MiB of console output and
returns only explicitly framed data, limited to 1 MiB, with its byte hash. The
parent validates the exact receipt fields, counts and decoded data hash. Normal
console text is not returned, and worker errors never echo request/console bytes.
Line parsing and stream output are bounded. This is transport reporting, not
authentication of a guest or acceptance of its claimed facts.

## Intent, uncertainty and stop ownership

`persist_intent` requires a file-backed Store and commits `possible-send` before
worker launch. Store generation/fencing, duplicate IDs and unresolved mutations
block later admissions. The lower-level I/O function requires a durable-intent
callback; `run_journaled` supplies the actual Store integration. Assignment
failure kills the still-gated worker directly rather than waiting for an empty
job to terminate it.

An acknowledged exchange remains `possible-send`. It produces an audit event,
not a Store receipt or task/package acceptance. A failure after an attempted
handoff fences Store authority and retains uncertainty. There is no reconnect,
resend, intent deletion or automatic repair. Database-loss and physical-power-loss
recovery are not qualified by these process tests.

The trusted controller must still bind original VM lease/ownership, target/disk/
backup/UART and root-session identities, verify actual approval, freeze the exact
permitted commands and signal revocation. The primitive's reference strings and
hashes are consistency checks, not approval authentication. It does not inspect
command semantics or prove who owns the pipe. Its request deadline must be taken
from the approved original lease, not chosen as new authority.

Terminating this host worker does **not** stop the VM or undo a guest command.
The independent VM supervisor must observe fencing and enforce stop/reap under
its original deadline. A returned acknowledgement cannot prove that guest work
has stopped. Host creation/kernel failures and control-process scheduling are
not a hard real-time guarantee; independent stop enforcement remains necessary.

## Measured preparation checks

Eighteen focused tests passed on Windows x64 / Python **3.13.17**. Nine exercise
the request/protocol/journal logic; nine use actual Windows pipes/processes/jobs.
Native cases cover a successful local exchange with retained uncertainty, lost
acknowledgement deadline, revocation, assignment failure, faulty worker output,
corrupt data receipt, blocked kernel pipe write, parent death and exact job
membership/name refusal. The blocked-write case uses an oversized **synthetic**
write to make the kernel block; production line bounds remain unchanged. Reaped
jobs report zero active processes where queried. Parent-death testing waits on
the worker's retained Windows process handle, rather than assuming a PID vanished.

One intermediate named-job test exposed a loop variable overwriting the requested
job name. Its failed log/receipt is retained; the corrected source and test peer
cleanup passed the final focused run. The earlier PowerShell stderr-redirection
attempt reported a shell failure despite its unittest log saying OK; later runs
write logs directly through unittest and retain explicit result counts. Neither
case involved a VM. Full regression and exact source identities are in evidence.

No VirtualBox command, guest pipe connection, WSL operation, media mount,
installation, provider call or upload ran in this checkpoint. Prior guest,
admission, ISO and architecture artifacts remain unchanged; no current VM or
source-disk state was freshly measured.

## Next check

Prepare the identity-gated guest command sequence and create-only control
executor, then bind the controller to the original VM lease, revocation and
independent stop observer. Native transfer/observation/control changes require
their applicable explicit approvals. Disconnected guard creation and the
phase-boundary decision remain pending. Actual installation, final readiness,
isolation/routing/recovery and the feasibility decision remain open.
