# Explicit initial-Aborted recovery preparation

Latest checkpoint, November 24: a subsequent separately approved
[controller-loss run](guard-controller-loss-evidence.json) left guard Aborted
and the admission/stop held. [Decision 0007](../../docs/decisions/0007-held-guard-successor.md)
proposes complete new provenance and explicit future reservation transfer.
It is unapproved; context V3 and captures below remain historical and cannot
admit the latest state. No real ledger change or new activation is authorized.

[Decision 0005](../../docs/decisions/0005-initial-aborted-recovery.md) authorizes
implementation, Python tests, read-only inventory and unattached backup capture.
It authorizes no native boot, restore, setting edit, guest command or network.

The later separately approved [review 10](guard-startup-normal-stop-evidence.json)
successfully used capture 06/context V3 for one guard boot from Aborted and the
original owner's normal stop. Both VMs were then off/unlocked; guard NVRAM was
created and shutdown metadata changed. Capture 06 is retained history and cannot
be relabeled as the current profile. Earlier failed stops remain held. No new
activation is authorized by this result or by preparation.

## Separate typed inputs

[recovery_records.py](recovery_records.py) fixes this preparation to the guard and
consumed native review `98fa65d7365578352207992992a1d25ab8cf37dbf918d17e5f75aefd5c53ae6e`.
It binds the old identities, held/nonzero stop, exact current file baseline and
bracketing aborted/unlocked observations. These records confer no execution
authority. [process_proof.py](process_proof.py) proves retirement by Windows
creation identity; a live process, access denial or unreadable identity holds.

Historical context version 2 additionally required exact consumed
review `680a7aa23fe6efcd1db67344d1271e4e32b71e08f62e47736cbe8e8712dbefd0`,
its failed original stop, every retained frontend/helper creation, unchanged
post-run backing files and its historical parent context hash. Both attempts are
freshly reconciled during capture and admission. Version-1 context bytes remain
retained historical evidence; they are not silently upgraded or reusable for
admission. This adds mandatory provenance within the approved guard-only model;
it changes no allowed initial state, stop acceptance, native authority or deadline.

Current context version 3 also requires consumed review 07,
`fba9d14f0b7cadd70786674b730b34c8375fbba60c1d9b4886d725b9df86d77f`.
Its running observation and orphan receipt must remain unaccepted, the ledger
must remain `resumed` with no receipt hash, and every retained creation must be
freshly proven retired. A historical null leaf exit is not a death proof. The
exact new guard configuration hash is
`91c25dbe0e2281892a1cceeef07abc9c8a80d1595b12f1c7e403c1d2edbe17aa`.
Versions 1/2 stay retained history; current admission cannot relabel them.

The new backup receipt is version 3 and states `source_machine_state: aborted`,
`source_session_state: Unlocked` and PID zero. It has no `source_poweroff` field.
Version-2 receipts retain their original meaning and require their normal path.
Neither format is implicitly relabeled. The new current-profile record also
names its initial state and exact recovery-context/backup hashes.

## Read-only capture

The default command is inert:

```powershell
python -m research.validation.initial_aborted preview
```

The separately approved preparation permits this capture into a new directory:

```powershell
python -m research.validation.initial_aborted capture --output .local/validation/initial-aborted-capture-06
```

Capture reads the fixed prior artifacts and rechecks all original process
creations. It requires the exact current guard configuration, explicit absent
NVRAM, disk/VM identities, disabled transports, a created base medium and no saved
execution state. Both VMs are observed before and after copying: guard
aborted/unlocked, executor poweroff/unlocked. Native inventory runs outside
write-excluding file locks. Guard files and all preserved executor backing files
are held under Windows read-sharing locks while copied/hashed, then reacquired
and fully rehashed after final inventory before publication. Identities must
also match the original handles. The guard's
new byte-copy files are exclusive, flushed, read back and compared with source.
They retain their disk UUID and must never be registered or attached.

The source and backup paths/identities must differ. The original executor disk,
configuration and NVRAM hashes must match. Changed bytes, drift, late firmware,
unknown process state, partial output or a changed source cohort leaves the new
directory held. No existing directory is reused. Offline recovery copying now
allows 600 seconds in its copy loop, based on the observed 1.22-GB partial copy
at the earlier 120-second limit. This occurs without any owner, VM authority or
native lease. Native admission/startup/sample/stop bounds are unchanged. The
copy budget does not bound arbitrary kernel/filesystem stalls.

Only complete capture can publish `preparation.receipt.json`. Loading for native
review checks that marker and all context/receipt/profile metadata. Native
admission independently rehashes the backup and current target files again.

## Separate review and native gate

`startup_qualification preflight-recovery` performs only read-only checks and
creates no owner/controller. `prepare-recovery` loads the fixed complete capture,
then creates a fresh suspended controller/owner review. Its distinct format and
policy disclose initial `aborted` state and the context hash. `--capture-root`
selects a completed workspace capture explicitly, so a held directory is never
overwritten or reused. Its directory and exact input hashes are part of the
live review. Ordinary review/preflight reject that option. A matching separate
human approval must arrive within the original 600-second lease and reserve.

Only the distinct frontend recovery grant can bind version 3 and admit this
initial state. Ordinary grants still require poweroff and reject recovery fields
or backup bindings. Before resume, the exact recovery profile and a created,
unlocked medium must match. Initial progress is limited to
`aborted → starting → running`; waiting never joins or dispatches. The later
stable locked running PID must belong to the pinned live frontend family.

Normal stop acceptance is unchanged. It still requires the new original owner's
single successful command, natural family exit and two independent
poweroff/unlocked observations within the existing deadline. An abort after join,
failed/lost acknowledgement, backward transition or expired authority holds.
No old stop, lease, owner or review is reused. New success would not repair the
consumed failed stop or qualify the outstanding native failure cases.

## Verification status

The first actual capture's initial read-only query exceeded its four-second
deadline before any copy or owner/controller activation. The directory remains
partial. A follow-up comparison passed before, during and after file locks,
about 0.35 seconds each; it does not isolate the initial timeout's cause. Later
ordering keeps inventory outside those locks and revalidates bytes afterward.
No deadline or VM permission was relaxed.
The second actual capture completed its initial inventories, then reached
1,221,591,040 bytes before the file-copy loop limit. It published no context,
completed backup or preparation marker. That partial directory is retained.
Only the offline copy allowance changed afterward, as described above; the
four-second query limit and all native-operation limits remain unchanged.

Focused record, scratch-copy, admission and actual Windows Python-family checks
pass. VM facts in tests are synthetic; the process jobs and surrogate stop are
real. Final regression ran 515 checks: 502 passed, 13 platform skips, no failures
or errors. An earlier full cohort had two conservative normal-finish holds from
process-exit image-query races; it remains retained as failed evidence. Normal
finish now uses retained creation handles for previously validated family members,
with strict refusal for new/unproven members, unknown waits and nonzero frontend
exit. Startup/running monitoring and original-stop acceptance remain strict.

Actual capture 03 completed under the 600-second offline copy allowance. It
published typed context, backup and current-profile receipts. A separate process
rehashed the independent backup and both VMs' backing files, then freshly observed
guard aborted/unlocked/PID-zero and executor poweroff/unlocked/PID-zero. The
read-only recovery preflight also passed without creating an owner/controller or
issuing a native start/stop. See [the retained evidence](initial-aborted-evidence.json).
A later [final-exit cohort](frontend-final-exit-evidence.json) adds one check that
rejects a nonzero retained frontend exit after cleanup: 516 tests, 503 passed,
13 platform skips, no failures/errors. Read-only preflight passed again under
that source cohort. A fresh exact native review and timely approval are the next gate.

The separately approved review 05 then held at the session lock and is consumed.
The [COM-only startup repair and current provenance](startup-session-probe-evidence.json)
pass 533 tests (520 passed, 13 platform skips), actual offline COM-only observation,
fresh capture 04, separate-process readback 02 and read-only preflight 03. Current
capture 04 binds both consumed attempts. Any subsequent native activation still
needs its own exact review and timely approval.

Review 07 subsequently used capture 04 and reached Running, but its join journal
held on SQLite locking. It is consumed. Both disks remain unchanged; guard
configuration timestamp metadata changed to
`91c25dbe0e2281892a1cceeef07abc9c8a80d1595b12f1c7e403c1d2edbe17aa`.
See [new native evidence](guard-startup-journal-hold-evidence.json). Capture
04/context V2 are historical; their configuration binding no longer matches the
guard. Updated provenance must include this attempt, its failed stop, every
retained creation and the new exact profile before any fresh capture/review.
Product implementation, guest readiness, UART,
installation, isolation and full lifecycle qualification remain open.
