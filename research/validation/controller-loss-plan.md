# One joined-controller-loss qualification

Status: **One separately approved native case measured; original stop held.**
Exact inert review
`0925de6acf1a400301d84abf1177a0596f811ff142597e3e74ddc52c4f13a788`
was approved and consumed once. Two Running samples preceded controller exit 29;
the job emptied and independent Aborted/unlocked/PID-zero observations completed
within 2.668 seconds. All original/family identities retired. The sole original
stop exited 1 (`not currently running`), leaving no successful command receipt.
Admission remains held with its target reservation active; no retry ran.
Both disks, guard NVRAM and executor files are unchanged; only guard abort/time
metadata changed. [Native evidence](guard-controller-loss-evidence.json).

The sections below retain the pre-run preparation and acceptance policy. Their
stopped inputs predate the fault; they cannot admit the current Aborted guard.
Recovery provenance and held-reservation settlement need review before any
separately approved later boot. No new native authority remains.

## Preparation history

The first exact review,
`c43c796cdb66927682e62d22df0618de2c4a70738f146d15da08f38782abf41f`,
expired unarmed without approval. Zero VM starts/stops occurred and all three
suspended process identities independently retired. Its lease/approval cannot be
reused. See [closure/workflow evidence](feasibility-walkthrough-evidence.json).
[Decision 0006](../../docs/decisions/0006-review-before-native-lease.md) preparation
is now approved and [verified](offline-approval-evidence.json). The inert review
at `.local/validation/offline-guard-review-01/review.json`, SHA-256
`0925de6acf1a400301d84abf1177a0596f811ff142597e3e74ddc52c4f13a788`,
bound this same case without a process/lease before the native decision.
See [the new path](offline-approval-plan.md) and the consumed result above.
The purpose is to test what happens when the controller disappears while the
guard is running. This is a separate failure case from the successful
[normal startup/session/stop run](guard-startup-normal-stop-evidence.json).
It does not complete executor recovery or the product orchestrator.

## Existing authority and inputs used by this run

[Decision 0004](../../docs/decisions/0004-startup-process-ownership.md) approved
direct-frontend implementation and Python surrogate controller-death tests. The
new case exercises that existing kill-on-close job ownership; it adds no new
owner, poweroff issuer, lease renewal, retry or guest action. Native activation
remains separately gated. All earlier reviews are consumed or expired.

Before this run both VMs were poweroff/unlocked/PID-zero with all eight NICs disabled. A fresh
unattached byte-copy guard backup includes the NVRAM created by review 10. The
original VDI UUID/bytes are retained; **never attach or register the backup**.
The executor's disk, configuration and NVRAM are unchanged. Capture and independent
readback rechecked retirement of all seven original/native-family identities.

| Input | Retained path | SHA-256 |
| --- | --- | --- |
| Ordinary stopped backup receipt | `.local/validation/stopped-backup-guard-02/receipt.json` | `45acabef323344be8f5bc79f54e0ce1f5d1a8450a11cf6e15257138bcd2e1427` |
| Observed current profile | `.local/validation/stopped-refresh-03/profile.json` | `5afa03519f4d0a8d8a634f208841dcbf5676420d2253d16cfc5dc84e26c53393` |

The profile is a fresh read-only observation of the approved hardware, with no
setting command claimed. Guard configuration is 2,358 bytes, SHA-256
`1ec80854e03eb158afa58cb7410d13398b608b734115e36586db3446463cf97c`.
Guard NVRAM is 540,672 bytes, SHA-256
`ec2dca0346cd722d9e47a263353fa97b71b3de1914d7f5084b87eec1c9b4a49c`.
Capture 06/context V3 remain historical; this case uses ordinary poweroff-only
admission, not another Aborted recovery grant.

## Exact proposed native case

`python -m research.validation.startup_qualification prepare-controller-loss
--output <new direct child of .local/validation>` prepares suspended Python
controller/original-owner processes only. The new review format is
`mcli1-one-guard-controller-loss-review-v1`. Its policy explicitly names the
fault, exit code 29, the unchanged single boot and single original stop, and the
requirement to retain a failed stop as held. A normal/recovery approval cannot
select this case. It cannot be combined with initial-Aborted admission.

One separately approved boot may start only guard
`0eceb37e-f216-45ed-817c-7cf2fca3a32a`, using the pinned directly owned
`VBoxHeadless --startvm <UUID> --vrde off`. Boot and abrupt termination may write
guard disk/configuration/NVRAM and leave it Aborted. The executor stays stopped
and unchanged. No guest command, installation, network activation, restore or
native-command retry is included.

After the durable exact session-PID join and two accepted running observations,
the controller checks its original authority/live family, publishes an exclusive
fault intent with identities, samples, source-bound grant and original lease,
then checks authority again. `os._exit(29)` skips Python cleanup and closes the
controller's non-inheritable frontend job handle. The Windows job contains its
family. The separate original owner detects controller loss and retains its
already prepared single poweroff attempt. The controller issues no normal stop
request before the fault. Missing/changed samples, revocation, publication failure
or a failed second authority check cannot qualify the injected fault.

The historical live-review path used at most 600 seconds from preparation and
required timely approval with the existing 60-second reserve. The offline path
used here performs initial human review and protected hashing while unarmed,
then constructs one original lease before activation. Neither path resets an
armed lease, startup/sample/heartbeat or stop bound. See Decision 0006 for the
implemented distinction.

## Evidence and acceptance limits

The independent bootstrap requires the exact reviewed exit code and barrier,
empty outer job, retired controller/owner/every retained family creation, the
committed session receipt, durable authority fence and one bounded original-stop
process result. Two read-only observations must find the fixed disconnected
profile, unlocked session and PID zero within ten seconds of the original fault
intent on both clocks. They may report poweroff or Aborted **as containment
evidence only**. Running/unknown states, incomplete evidence or late observations
hold without another command.

Even an exit-zero original stop cannot turn abnormal process termination into
the normal-stop success criteria. A nonzero stop keeps its possible-send/null
receipt state; missing acknowledgement/result remains held. This case always
reports `original_stop_accepted: false` and `native_settlement_qualified: false`.
The narrower `controller_loss_case_measured` flag records only the proved fault,
fence, process containment and bounded observations. It grants no restart or
workspace reuse. Earlier failed stops remain held.

This does not qualify loss during unsettled startup, arbitrary late/detached
behavior, bootstrap/owner loss, guest readiness, root/UART ownership,
installation/hardening, isolation, executor recovery or the full product.
Kernel/filesystem stalls are not claimed to obey a hard real-time bound. A native
hold requires manual reconciliation and fresh current bindings before any
separately approved later run.

## Measured preparation

[Evidence](controller-loss-preparation-evidence.json) retains **574 tests: 561
passed, 13 platform skips**, no failures/errors or source drift; Ruff passes.
The new 18 checks include exact fault-policy approval, two-sample/authority gates,
publication/revocation failures, original-stop uncertainty, wrong plans/unfenced
authority, running-state refusal, original fault-clock enforcement and the actual
Windows Python controller/owner/family fault. Its VM facts are synthetic.

Fresh actual stopped capture, independent backup/current-file readback and
read-only preflight also passed, with zero new VM starts/stops/settings changes.
Two local capture attempts stopped before copying on script/path errors and are
retained incomplete. The first full sandbox regression could not launch five
existing PowerShell refusal/preview checks (WinError 1920); unchanged code passed
the full outside-sandbox regression. None of those checks activated a VM.
