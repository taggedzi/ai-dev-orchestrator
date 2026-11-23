# Boot precondition preparation

The later [backup/profile checkpoint](maintenance-profile-plan.md) supplies genuine
unattached file backups, explicit NVRAM state and measured current stopped target
settings. Version-2 backup bindings are accepted only explicitly; the older local
packets below remain historical and unarmed. The [frontend-family primitive](frontend-process-plan.md)
is prepared separately. The later [owner-bound start adapter](frontend-start-plan.md)
prepares actual intent/resume/monitoring with Python surrogates; native admission
and settlement remain unqualified.

[boot_preconditions.py](boot_preconditions.py) checks a live original owner,
stopped VM configuration and pinned backup receipts. It produces a report with
`native_dispatch_permit=false`; it has no VM-start command. The older
`first_boot.py` diagnostic has not been connected to this admission path and
must not be treated as the qualified starter for the next target run.

## Bound facts and failure handling

The caller supplies exact packet bytes/hash, the original `owner.sqlite`, a
trusted stopped-state probe and raw backup/preboot/source-preservation receipts.
The check requires the sealed owner launch, exact ready report, live PID creation
identities, independent Windows job membership, original owner binding, fresh
heartbeat and unchanged original lease/generation. Copied ready files and a live
process alone do not establish authority.

The packet has a maximum 15-second check window on both clocks and leaves at
least ten seconds of the original lease for stopping. Two fresh raw observations
must agree on the selected powered-off target, base VDI, CPU/RAM, firmware/APIC,
disk-only boot, UART pipe and disabled network/sharing transports. Every source
pin is rechecked against current disk bytes. Receipt parsing verifies consistency;
it does not itself create a backup, hash a disk or authenticate an issuer.

After original-owner admission, a failed first observation also fences authority.
Durable exclusive intent precedes the second observation and journal receipt.
Source/configuration drift, partial writes, a lost commit or a stop beginning
during publication retain a hold. Final commit rechecks the original ready pulse;
it cannot accept a heartbeat rolled back to before readiness. Retained files and
the single journal row prevent replay. A published report still never authorizes
a native start, including if its final journal commit fails.

## Local results and packets

All 25 boot checks passed on Windows. Five use actual independent owner/job
processes and Python surrogate stops; VM configuration and backup facts remain
synthetic. Missing readiness, controller-job loss, fencing and failed observation
are covered. The latter causes one original-owner surrogate stop. See the source
snapshots, native receipts and final regression in
[maintenance-session-evidence.json](maintenance-session-evidence.json).

Measured target identities are retained in two **unarmed** packets:

| Role | Local packet | Raw SHA-256 |
| --- | --- | --- |
| Guard | `.local/validation/boot-preconditions-guard-01/measured-target-unarmed.json` | `596fb51b81812581840384f630a919d9bf9db6797acb1ef2394ce7ca825a5eb2` |
| Executor | `.local/validation/boot-preconditions-executor-01/measured-target-unarmed.json` | `dcca57a8d3a4b9c0cd5ddac2f5db6da348adac587777d25defef6f52e89315c2` |

Both refuse with `boot scope/backup/configuration review is unbound`. Controller,
owner, original clocks and genuine backup bindings are deliberately unset.

## Startup settlement remains open

Source review of Oracle's
[VBoxManageMisc.cpp](https://raw.githubusercontent.com/VirtualBox/virtualbox/main/src/VBox/Frontends/VBoxManage/VBoxManageMisc.cpp),
header revision **112403, January 11, 2026**, shows a progress object returned by
launch, an indefinite completion wait, and later completion/result inspection.
This is not established as the installed binary's exact source. It does not
prove that terminating the CLI cancels the underlying startup operation.

The next starter must bind the exact approved target/configuration/backup and
original owner before any start intent, and account for an unanswered or late
startup operation before claiming final poweroff. Killing a client or observing
poweroff once is insufficient evidence against a later start. Prepare that
bounded path and its refusal/fault tests before requesting native boot approval.
Actual UART/root-session collection and the complete ten-second native stop path
remain unqualified.
