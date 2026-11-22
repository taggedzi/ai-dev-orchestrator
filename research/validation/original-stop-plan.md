# Bounded original-supervisor poweroff preparation

[maintenance_stop.py](maintenance_stop.py) now supplies the existing supervisor's
stop command through [driver.stop_vm](driver.py). This replaces its unbounded
output capture; it adds no second VM stop issuer. Default preview and `--prepare`
cannot start an owner or power off a VM. Native VM activation, poweroff, guest
commands and installation were not performed in this checkpoint.

## Current review packets

| Role | Unarmed local stop packet | Raw stop-plan SHA-256 |
| --- | --- | --- |
| Guard | `.local/validation/original-stop-guard-02` | `3c1649cbea5b9b35642091e80a419caf66fc31dee75868b870546dafc054b389` |
| Executor | `.local/validation/original-stop-executor-02` | `dcd10f776140be345f6c4e099d284d7152d406bc1406d201fda110e1c855b770` |

Both refuse with `native stop approval is unbound`. Owner process identity, nonce,
binding hash, original lease clocks and approval are empty. Earlier revision 01
packets remain intact. These are source/input reviews, not complete independently
launchable supervisors or native execution approvals.

The updated host contracts are `.local/validation/host-adapter-guard-04`, raw SHA-256
`07fe2e0f938612c3e7bc9727307d6cf753c7c2dc6f20304a1edf5af59495cdf5`, and
`.local/validation/host-adapter-executor-04`, raw SHA-256
`2afcc0e970942fb0ecfd83a9afdef2f122b7b9200ff45dbc52d8917299812600`.
They reference these stop plans and current source snapshots. Prior host revisions
02 and 03 remain historical. The four transfer revision 03 grants are unchanged:
the guest/controller/serial-transport cohort did not change here.

## Binding and one-shot execution

The static plan binds one selected VM UUID, the original owner PID/creation
FILETIME/image, owner nonce, immutable lease clocks and owner-record hash. It pins
the installed VBoxManage path/version/digest and ten current host source files.
The loaded process-start source epoch must still equal the reviewed plan and
current disk bytes before native execution. An approval reference is a consistency
field; authenticating its issuer remains an external integration requirement.

The deployment template now exposes an unfilled `bounded_stop`. Profile validation
rejects a missing plan or one with a different target, original expiry, executable
or source cohort, even if other approval/qualification fields are present. The
stop plan uses its own canonical byte encoding, including Unicode escaping.
This is structural admission, not proof that supplied approval evidence is true.
Legacy profiles have no native-stop fallback and must acquire the new binding
before any future launch.

At stop time the caller must be the registered original process, using its
existing durable Store. The original supervisor must already have recorded
`stopping`, and authority must be fenced. Target, owner record and original clocks
must remain unchanged. Owner connections now use a 50 ms SQLite busy timeout.
The check does not require still-active run authority, an unexpired lease, fresh
guest readiness or a matching current NIC/storage profile: emergency shutdown
must remain available after fencing, clock rollback, expiry or isolation drift.
It never changes the original lease or permits new guest work.

The sole command is absolute, pinned `VBoxManage controlvm <bound UUID> poweroff`,
with direct arguments and no shell. Oracle describes this as abrupt poweroff;
independent backup and explicit target-stop authority are prerequisites. See its
[7.2 command reference](https://docs.oracle.com/en/virtualization/virtualbox/7.2/user/vboxmanage.html).
No ACPI, retry, reset, alternate executable or enumeration fallback is supplied.

Before process execution the owner exclusively creates
`.local/validation/owner-stops/<owner-nonce>/poweroff.intent.json` and commits
`possible-send` in the original Store. An existing directory, even empty, refuses.
Deleting an operation row cannot remove that filesystem barrier. Partial intent,
lost acknowledgement, failed commit or process/receipt uncertainty remains held
for reconciliation; an owner-loop failure cannot automatically reissue the stop.

The process wrapper creates the child suspended, already assigned to a
non-inheritable one-process kill-on-close Job Object. Immediately before resume,
the callback rechecks the plan/source, executable, original owner/lease and both
intent records, then records the child PID. The child cannot run if this gate
fails. Microsoft's [creation-time job/handle attributes](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute)
and [Job Object documentation](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
describe the primitives; native scratch checks measure the prepared wrapper.

The command budget is three seconds, counting preceding preparation in this
callback, with at most 64 KiB per output stream. The wrapper verifies process,
stream and job-accounting cleanup before returning; cleanup waits are separately
bounded. The shared wrapper also now closes partial pipe allocations if a later
allocation fails. Host kernel stalls, filesystem flushes and physical power-loss
durability are not established as hard time bounds by these tests.

Bounded stdout/stderr and process metadata are retained even for a nonzero exit.
A zero exit with reaped streams/job permits only
`original-stop-command-returned-not-poweroff-acceptance`. Progress on stderr is
retained as data; it is not independent VM-state evidence. A failed receipt commit
leaves `possible-send` despite any receipt file. Only the original supervisor then
updates its stop ledger; the separate host adapter must still measure poweroff
and satisfy its original overall stop bound. Late emergency commands do not
retroactively satisfy that bound or renew the VM lease.

## Verification and remaining work

Nineteen focused stop checks passed: 15 synthetic cases and four native Windows
scratch/process cases. Two added profile checks use a real frozen fixture bundle
with explicitly synthetic approval/owner facts. They cover missing/mismatched
stop binding, Unicode encoding, source substitution, durable intent, original
expiry/rollback behavior, caller retargeting, lost acknowledgements, no replay and
journal failures. Native cases replace every intended VBox command with isolated
Python; they cover the suspended gate, bounded process/output cleanup and partial
pipe-allocation failure. They do not power off or otherwise modify a VM.

The final Windows regression passed **292 tests: 279 passed, 13 platform skips**.
The first full regression passed before the additional profile-admission checks;
its exact sources and receipts remain separate. Final regression results, current
packet inventories and earlier source revisions are recorded in
[evidence](original-stop-evidence.json). The earlier native stopped-VM inventory
was not refreshed, and current VDI bytes were not hashed.

Next, prepare and qualify an independently launched original owner that survives
controller death and automatically polls its lease/fence, including boot/startup
failure paths. No actual owner launch packet is qualified yet. Final running UART,
real stop latency/cleanup, COM service lifecycle, executable dependency loading,
host ACLs, genuine receipt issuers and approval authentication remain open.
The three-second command budget must be measured against real VBox poweroff under
separate scoped approval; a scratch surrogate cannot establish that it fits.
The [same-boot proposal](../../docs/decisions/0003-maintenance-same-boot-review.md)
is still unadopted. Guard creation, phase policy, guest installation and final
M1-11 through M1-14/product qualification remain incomplete.
