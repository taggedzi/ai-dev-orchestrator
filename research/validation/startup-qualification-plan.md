# One disconnected guard startup qualification

Current status: **One separately approved normal native startup/session/stop
case passed.** Review 10, SHA-256
`027b509dfcbe0d710f5bdf0a63334b0668a351b6dd0e3907f8caf79e4996967b`,
booted the disconnected guard from Aborted, committed the exact session binding,
accepted two running samples and completed the original owner's sole stop with
exit 0. All frontend/helper processes exited naturally with code 0; two independent
poweroff/unlocked observations completed within 2.597 seconds of the stop request.
See [normal-case evidence](guard-startup-normal-stop-evidence.json).

Both disks/executor files are unchanged. Guard NVRAM was created and abort/time
metadata updated. Both VMs are now off/unlocked with all NICs disabled. Capture 06
predates those changes and is historical, not a current stopped-profile binding.
Reviews 08/09 expired unarmed. No live review, approval, lease or stop is reusable.
Native failure cases, guest readiness and wider qualification remain open.

The next [joined-controller-loss case](controller-loss-plan.md) now has verified
preparation and a distinct exact native review format. Its ordinary poweroff-only
inputs are the refreshed guard backup 02/current profile in stopped capture 03.
It never treats abnormal termination/Aborted as normal-stop acceptance. Native
fault activation still requires its own exact timely approval.

## Consumed reviews

Review 07, `fba9d14f0b7cadd70786674b730b34c8375fbba60c1d9b4886d725b9df86d77f`,
was approved in time. One VM boot reached Running and stable locked-session PID
4424 matched its retained frontend identity. SQLite then reported `database is
locked` while recording the join. The filesystem receipt exists but its database
binding never committed; no running samples were accepted. Containment reaped
the family, and the one original stop exited 1. Both disks and executor files
are unchanged; guard timestamp metadata changed, leaving guard aborted/unlocked.
See [journal-hold evidence](guard-startup-journal-hold-evidence.json). The exact
failed statement and competing writer are unmeasured. Context V2/capture 04 now
predate this consumed run and changed configuration; no new review may reuse them.

The corrected preparation's review 06,
`4507ab8096d8d9ead05f75f0b62f38402ed5ab490ce17eded3a4f7aebbca9bb9`,
received no timely approval and closed unarmed. No VM start/stop or owner
activation occurred; all original process identities are retired. See
[closure evidence](guard-startup-probe-review-expiry-evidence.json). It is not a
native attempt. The developer's return permits preparing a fresh review, while
native activation still requires that new review's separate timely approval.

The first exact review was approved, held before start and is closed.
Review SHA-256 was `fc14c0ca697b09726c3fcdc84ed78810e876fce6f7e9997305a0a733cdef54db`.
The first read-only preflight timed out after original-owner readiness, before
controller activation or a start intent. Zero frontends/boots occurred; the single
original stop result is unknown and stays held. Independent observations and full
file hashes prove both VMs remain off and unchanged. See
[held-run evidence](guard-startup-hold-evidence.json). No retry or new lease follows
from that approval. Diagnose/correct the preflight before any successor review.

The successor review `72f98453006968770162d719590e5c3ce0972db3412c780332c80b8c2bb8978f`
was also approved and is now consumed. Preflight passed and the native frontend
resumed, but its family was contained before a running sample passed. The owner
exited without a terminal or native stop intent. Both VMs were subsequently off
with all backing files unchanged. See [successor evidence](guard-startup-successor-hold-evidence.json).
No native running/start/stop case is qualified and neither session may be replayed.

The later fresh review
`7580226fe0d7a9e75c702a57e68c69966e5c8f3a4f3328fd8b0423cdedf1118a`
received no timely approval and closed unarmed. Its bootstrap, controller and
suspended owner are independently retired; no native start or stop ran. See
[unarmed-review evidence](guard-startup-unarmed-review-evidence.json). This is not
a third native attempt, and a late answer cannot reuse its lease. Wait for the
developer before preparing another live review.

After the developer returned, fresh exact review
`98fa65d7365578352207992992a1d25ab8cf37dbf918d17e5f75aefd5c53ae6e`
was approved. It resumed one frontend and reached `Starting` in the native log,
but no running sample qualified. A retained CLI diagnostic caused a parser hold;
the family was contained. The original stop exited 1 because the VM was not
currently running. The guard is aborted/unlocked with changed abort/time metadata;
both disks and the executor's configuration/NVRAM are unchanged. See
[parser-hold evidence](guard-startup-parser-hold-evidence.json). This review is
consumed. Ordinary poweroff-only admission stays closed. Approved
[decision 0005](../../docs/decisions/0005-initial-aborted-recovery.md) now has
[verified recovery preparation](initial-aborted-evidence.json) and
[final exit checks](frontend-final-exit-evidence.json): 516 regression
checks (503 passed, 13 platform skips), actual unattached capture, independent
readback and read-only preflight. That preparation grants no native boot.

The developer then approved exact recovery review
`680a7aa23fe6efcd1db67344d1271e4e32b71e08f62e47736cbe8e8712dbefd0`.
One frontend root resumed, but VirtualBox failed `LockMachine` with an
already-locked session error. All frontend processes exited 1 naturally; no
running sample qualified. The single original stop exited 1 and remains held.
Both VMs' backing files are unchanged; guard remains aborted/unlocked and executor
poweroff/unlocked, with all reviewed process identities retired. See
[lock-hold evidence](guard-startup-lock-hold-evidence.json). Source review shows
`showvminfo` acquires a shared session lock, making current startup polling a
candidate competitor for the frontend's VM lock. Exact installed conflicting lock
ownership is unmeasured. This review is consumed and grants no retry.

The [current correction](startup-session-probe-evidence.json) uses COM-only probes
before any runtime CLI read, requiring stable locked starting/running state and
the exact live pinned frontend PID first. Probes cannot count as running samples,
join or publish a session receipt. Full profile/storage verification still
precedes joining, and all existing clocks/deadlines remain unchanged. Actual
offline probes, 533 regression checks (520 passed, 13 platform skips), fresh
unattached capture 04, separate-process readback 02 and read-only preflight 03 pass.

The successor code now checks the pinned image/environment, exact guard profile,
configuration/firmware and both stopped/unlocked VM sessions **before activating
the original owner**. It retains the raw observations, rechecks the same approval,
source cohort and original lease, then journals possible owner activation before
sealing/resuming it. An earlier timeout or changed input leaves both Python
processes suspended and issues no native stop. The consumed first session and its
unknown stop result stay closed. Any successor native run needs its own exact
live review; no lease or approval is renewed automatically.

[Decision 0004](../../docs/decisions/0004-startup-process-ownership.md) states:
“Implementation and Python surrogate tests are authorized; no native boot is
authorized.” The new [qualification runner](startup_qualification.py) prepares
the concrete native review and waits for that separate decision.

## Exact scope

The [journal correction](controller-journal-plan.md) now permits only bounded
waiting for known BEGIN non-entry, never replaying a transaction body, COMMIT or
native command. Receipt publication and in-memory acceptance follow a confirmed
binding commit. Phase/error traces are retained after containment. All original
authority, startup/sample/heartbeat/stop bounds remain enforced. Its 556 checks
(543 passed, 13 platform skips) and actual independent-writer Python surrogate,
fresh capture/readback/preflight are in [current evidence](controller-journal-evidence.json).

One boot of `mcli1-guard-01`, VM UUID
`0eceb37e-f216-45ed-817c-7cf2fca3a32a`, using the directly owned, pinned
`VBoxHeadless --startvm <UUID> --vrde off` process family. It retains the approved
one-CPU/1-GiB/four-SATA-port/APIC-on/x2APIC-off/UART profile, eight disabled NICs
and disabled sharing transports. No guest command, installation, network
activation, restore, second boot or mutation retry is included.

Boot itself can write the guard disk, configuration and first-boot NVRAM. Those
writes are part of this proposed run. Its existing independent backups remain
unattached. The stopped executor's original disk is measured before and after
and must retain SHA-256
`2eb1d9cd009ecfe83381d855137f5cee8c1317739f6209beddd6da8a10955a09`.

The earlier ordinary reviews bound the historical guard backup and stopped-profile
receipts, SHA-256
`c16629a52d55229edd3f66c2afb3c99af231451379ae26814668421837e4715f` and
`dca350813141f8a51e4b9a69f4fe6ff28152b28eb35b36638753ce1c077cceab`.
Current disk/configuration/firmware bytes and stopped inventories are rechecked;
the earlier file hashes do not stand in for fresh measurements.

The consumed recovery review selected
`.local/validation/initial-aborted-capture-03`. Its version-3 backup receipt has
SHA-256 `a9fccffb5272c4d1436812c762e1ef64e7017812e1091fa044e9d9ee969a453c`;
current-profile receipt SHA-256 is
`de120a92eb4b8347e57025bd418b54fdf8596891fa71576133c53827fec285ff`.
The explicit recovery context SHA-256 is
`65e6e54ff8b939c66f547f6b3b7156895fb7fce4bc046237dbda97939466266a`.
It binds consumed run 04, retired creation identities, its held exit-1 stop and
the new independent backup. The backup is never registered or attached. Initial
Aborted is admitted only through this guard-specific typed grant; normal final
stop acceptance still requires poweroff.

Consumed review 07 selected
`.local/validation/initial-aborted-capture-04`. Context version 2 requires both
consumed reviews, the failed original stops, every retained creation identity and
the exact historical parent context. Backup receipt SHA-256:
`7f0eb906ae2a159fadb2a80751157c1852e67092b57cd170e457145b3013842f`.
Current-profile receipt SHA-256:
`de357402708c15be77f8b621e318b980dd14186399359fbc0687d45dbf828c68`.
Recovery context SHA-256:
`0bff309b8928c81a74771cb1c0724187d640a099f87dc6baefb84015d7eba668`.
That binding permitted only an explicitly reviewed guard start from measured Aborted;
the preserved executor remains off/unlocked. New success cannot repair either
old stop, and there is no automatic retry or review renewal.

## Review and timing

The consumed successful review 10 selected `.local/validation/initial-aborted-capture-06`,
with context V3 binding recovery-history reviews 04, 05 and 07 and current guard
metadata. The orphan receipt from 07 remains unaccepted evidence. The fresh
backup stays unattached and no prior stop or lease is reused.
Backup receipt SHA-256:
`7cfd314bb0aba03ef765292562ad2002b1dec07d0dc2712ee75add361b458b41`.
Current-profile SHA-256:
`f1099451c3cdab31efc448baa52e9fbabfecdbca74b1cac4ebd9dc3fdf47324a`.
Recovery context SHA-256:
`623e3701fab0d58601a21108291bc840a15da8a8b281dde8371917cc39781908`.

`prepare` (ordinary) or `prepare-recovery --capture-root
.local/validation/initial-aborted-capture-06` creates only two suspended Python
processes in the prepared Windows
jobs: the controller and its separate original owner. The immutable original
lease starts then and lasts at most 600 seconds. A complete `review.json` binds
their PID creation identities, stop proposal, caller/owner jobs, lease, exact
sources, executable/environment, fixed receipt inputs and one-boot policy. Its
external SHA-256 is the review's approval boundary. No VM command runs while
this review is unanswered.

The matching approval must arrive with at least sixty seconds of the original
lease left. No answer, cancellation, changed inputs/processes/sources or a late
answer closes the suspended jobs without starting a VM. No lease renewal occurs.
After approval the runner performs those bounded read-only checks while the
owner is still suspended. Only fresh matching results can precede sealing the
exact reviewed original-stop proposal. It then starts the independent owner,
verifies readiness, measures current stopped disk
facts, and derives the short start grant from those fixed inputs and fresh clocks.
The derived packet and receipts are retained before one controller resume.

The current owner tolerates only confirmed rolled-back SQLite BUSY while the
same original lease remains armed and no native stop record exists. The wait is
at most one second, also bounded by both original expiry clocks. It cannot renew
the lease, retry an uncertain stop or take over an owner. A held terminal is
published even when a journal fence also fails, and it immediately blocks further
admission. This repairs a controlled contention failure; the missing exception
from the consumed native successor cannot be reconstructed.

The separate `preflight --output <new-directory>` command performs only the
read-only phase. It creates no owner/controller process and has no VM start or
stop operation. Native read-only preflight passed for both stopped VMs. The same
ordered path also passed with actual Windows jobs, a suspended controller,
Python-only original stop and real backup/current-file locks. These observations
do not establish the first timeout's cause or native running behavior.

The adapter's admission window and startup session-identity bound are fifteen
seconds each under the same original lease. Runtime collection allows at most
ten seconds for two consistent running observations. There is no guest-readiness
claim. The session PID must belong to the actual hardened frontend family; an
unknown helper or extra process holds.

Initial runtime collection uses a separate wait-only observation for forward
`poweroff → starting → running` (ordinary) or `aborted → starting → running`
(explicit recovery), with `Unlocked → Spawning → Locked` progress.
The adapter checks the original granted profile/storage and live family, rejects
regression within or between frames, and never joins from a wait marker. Only a
stable locked running session with the exact family PID counts toward the two
samples. Query deadlines, startup/sample limits and the original lease are not
reset; the sample window is checked again after collection. All preactivation,
post-join and final stop observations remain strict. This preparation does not
establish the cause of either consumed native hold.

## Original stop and independent proof

After a verified session join, normal finish journals one stop request and fences
authority. Only the original owner invokes its already prepared single bounded
`VBoxManage controlvm <UUID> poweroff`. The controller retains containment for
at most four seconds while that known original stop completes and the frontend
family exits naturally. No guest dispatch or new start is possible during that
wait. Already validated family identities retain creation handles through this
finish window, so natural exit is checked without racing final image queries.
New/unproven members, unknown waits and nonzero frontend exit hold. Its separate
watchdog still holds on changed authority, binding, journal,
source, output or process evidence. Startup uncertainty uses immediate family
retirement instead of this normal-finish wait.

The bootstrap, outside the controller job, requires the original owner/stop
ledger and exact command receipt, natural zero frontend exit, empty family/pipes
and dead original PID creation identities. After cleanup, every retained process
must have a final exit code and each pinned frontend must have exited zero; this
also covers a nonzero child exit racing the last finish poll. Access denial is
not a death proof.
Two fresh independent poweroff/unlocked-session observations and the expected
storage/UART/network profile must complete within ten seconds of the stop request.
The preserved source disk is then independently rehashed.

A nonzero, raced, lost or unknown original poweroff result stays held even if
later observation finds no running VM. Job cleanup issues no replacement command.
On controller/bootstrap failure the existing job lifetime contains the frontend
family and the retained independent owner keeps its original lease/one-shot stop.
After closing the controller job, the bootstrap observes that existing owner's
process handle for at most five seconds before exiting. This is a bounded cleanup
observation, not a new signal, stop command, lease extension or acknowledgement.
There is no automatic repair or restoration after a held run.

Success measures only this normal startup/session/stop case. It does not qualify
startup-loss/controller-loss native failure cases, detached/late runtime behavior,
UART/root-session ownership, guest readiness, hardening, isolation or the product
orchestrator. Those remain explicit later gates.
