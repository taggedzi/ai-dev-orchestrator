# Independent original-owner process preparation

[owner_launch.py](owner_launch.py) prepares the suspended-process handoff;
[owner_process.py](owner_process.py) runs the existing original lease supervisor
outside the controller's job. Default CLI preview and `--prepare` do not launch
an owner. No VM was created, booted, reconfigured or powered off. This remains
fixture preparation, not product implementation or final deployment qualification.

## Current review packets

| Role | Local directory | Raw launch-review SHA-256 |
| --- | --- | --- |
| Guard | `.local/validation/owner-launch-guard-01` | `0f459bd7b825fa2c2b8acec412fb2c3313156d8298ca4baf0cd79a70d55591cf` |
| Executor | `.local/validation/owner-launch-executor-01` | `c3451670ea99c2f7b23ab504a03678bed2bcec3cb321f0d66302559cc3cb3e3f` |

Both are unarmed. Controller/job identity, suspended owner identity, original
expiry and scoped process/stop approvals are empty. They freeze twelve host
source files; no approval is inferred from the project goal or previous topology
preparation. These packets are reviews, not complete activatable launch grants.

Updated host contracts are `.local/validation/host-adapter-guard-05`, SHA-256
`7ff93ddbd79114f3171f1660e31998bd7c257aa82bfd870cfac7a70019e38b74`, and
`.local/validation/host-adapter-executor-05`, SHA-256
`3d68ed35cea3ded7e1548ed7637be9d5493a319890f1004b1810e66a241cc49c`.
They link the launch reviews and expanded source snapshots. Host revision 04,
original-stop revision 02 and transfer revision 03 remain intact; the latter two
source cohorts were not changed here. No packet has native-target activation authority.

## Exact review before execution

A trusted bootstrap outside the controller's named job creates a fresh attempt
directory and original lease, then creates the owner **suspended**. The process
is already in its unique provisional job. Its real PID/creation FILETIME/image and
the original stored wall/monotonic deadlines are therefore available before any
worker code runs. The proposal contains these exact facts and an empty stop approval.

The operator can review that concrete plan. Resuming requires its exact canonical
bytes/hash, a scoped native-stop approval reference and a separate owner-start
reference. Only the approval field may differ from the proposal. Changed target,
process, original clocks or source bytes refuse. Review/startup time consumes the
original at-most-600-second lease; late approval cannot extend it. The provisional
process can be closed without registration or VM action. An existing attempt
directory cannot be reused to create another original lease.

The parent seals a bounded packet with the full plan, root directory identity,
controller/bootstrap/owner identities and source epoch. It supplies the reviewed
packet hash through the private stdin pipe before resuming the primary thread.
The fixed bootstrap uses isolated Python and an explicit project source path.
The worker independently validates bytes, root, source, process and original
Store rows before registration. Approval references and hashes remain consistency
checks; authenticating their issuers and securing their transport is still required.

## Independence and lifetime

Kernel observations require the actual controller in its named job, and both
bootstrap and owner outside that job. PID creation identity must still match.
Controller-job query handles are closed immediately: retaining even a query handle
could delay kill-on-last-close. Microsoft's
[IsProcessInJob reference](https://learn.microsoft.com/en-us/windows/win32/api/jobapi/nf-jobapi-isprocessinjob)
and [Job Object documentation](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
describe these membership and lifetime semantics.

Before readiness, the worker opens its own non-inheritable job handle and removes
the provisional kill-on-parent-close coupling. Its two-process limit permits only
the owner and one bounded stop child. It then registers the original owner in the
same Store. Closing bootstrap handles after readiness leaves the worker alive;
losing the controller or the bootstrap's handles cannot kill it through those
specific jobs. Controller handles and stdin are not kept open as lifetime dependencies.

The ready proof is checked against the live owner PID, job limits, immutable
original lease, active generation, fresh owner row and live controller. It
explicitly grants **no VM-start permission**. A later boot adapter must combine
it with separately approved target/backup/start bindings. The owner polls the
original supervisor, fences on lost/reused controller identity or source changes,
and uses the same one-shot bounded stop path. It neither starts a VM nor renews,
restarts, takes over or reissues a possible-sent stop.

Ready and terminal reports publish only flushed complete bytes through exclusive
hard links; staging names remain for inspection. See Python's
[os.link documentation](https://docs.python.org/3.13/library/os.html#os.link).
Packets are size-bounded and link/reparse paths refuse. This is not a physical
power-loss durability or hostile-host filesystem-race guarantee. The deployed
filesystem must support the operation; test receipts came from Windows scratch paths.

## Measured results

All eleven focused checks passed: five packet/preview checks and six native
Windows process/job cases. They cover exact sealing, changed root/approval/source,
bounded packets, complete publication, missing approval, canonical encoding,
original expiry, fenced readiness, controller-job termination, bootstrap exit and
lost surrogate acknowledgements without replay. The generated production bootstrap
and owner loop execute; only the stop/executable boundary is replaced by explicit
test-only Python surrogates. These tests use synthetic VM/approval facts.

The retained bootstrap-death case records a single surrogate dispatch from the
original owner after both controller and bootstrap are no longer live. Other
cases retain ready/terminal reports, original SQLite rows and surrogate output.
The lost-ack case keeps uncertain stop state rather than issuing again.
Final regression passed **303 tests: 290 passed, 13 platform skips**. Earlier
fixture versions and a negative-test setup error remain separate. Exact inventories,
source bindings and process observations are in [evidence](owner-launch-evidence.json).

## Remaining gates and next check

Integrate the ready proof into the actual boot/startup admission path, including
denial before owner readiness and startup/boot failure handling. The current ready
file alone must never authorize a VM start. Real backup/target/media/root-session
bindings, running UART collection and native poweroff timing remain unqualified.

These results do not prove survival of arbitrary ancestor-job termination,
Windows logoff/reboot, owner crash, storage loss or host kernel stalls. The worker's
filesystem/source reads, SQLite operations and native calls are not a hard real-time
guarantee under those failures. This is a prepared library, not an installed service.
Host ACLs, executable dependencies and approval authentication still need qualification.
The three-second VBox command budget and complete target stop path still need
separately approved measurement. Guard creation, broker phase policy and the
[same-boot session proposal](../../docs/decisions/0003-maintenance-same-boot-review.md)
remain pending. Final M1-11 through M1-14 and the product lifecycle remain incomplete.
