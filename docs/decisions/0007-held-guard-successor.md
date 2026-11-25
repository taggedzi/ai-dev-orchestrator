# A separately authorized successor to a held guard run

Status: **Preparation measured, November 24, 2026. Real transfer and boot are not approved.**
The developer answered “I approve the decisions,” covering Decisions 0007/0008.
The exact proposals and approval are preserved in
the [approval record](0007-0008-approval.json). This approves preparation
only; the actual held reservation remains unchanged.
This decision concerns research preparation only. It grants no native boot,
reservation change, restore, guest command, installation or networking.

## Concrete problem

The separately approved offline review
`0925de6acf1a400301d84abf1177a0596f811ff142597e3e74ddc52c4f13a788`
was consumed once. Its runtime binding is
`280de430cee4d69e60c76cc44022c180b52c71fa7fcf843fef0def3526c85dca`.
The [native evidence](../../research/validation/guard-controller-loss-evidence.json)
proves the named controller-loss containment case. Original stop exit 1 remains
`possible-send`, without a command receipt. All original and retained creations
retired. Guard is Aborted/unlocked/PID-zero; executor remains poweroff/unlocked.
Both disks, guard NVRAM and executor files are unchanged. Guard configuration is
now SHA-256 `6388740c34b3ce72b8d66f384a66c82d36fe9b8385a519998b7083ab07e29046`.

Source review finds two distinct closed gates. `Admissions.finish(settled=False)`
retains the active reservation, and `consume()` cannot admit a second active
guard. The ordinary offline path also requires poweroff. Existing recovery
context V3 binds reviews 04/05/07 and predates both normal review 10 and this
offline fault. Reusing that context or going around the ledger would omit effects
and authority. [Decision 0005](0005-initial-aborted-recovery.md) permits explicit
Aborted recovery preparation; [Decision 0006](0006-review-before-native-lease.md)
does not extend its offline path to that initial state or settle held admissions.

## Proposed preparation

Prepare one explicit guard-only recovery path with an inert review and a
separately approved successor reservation transfer. Keep ordinary admission
poweroff-only. Keep the prior failed stop and prior review permanently consumed.
Do not add a general allow-Aborted flag, ledger reset or administrative clear.

The new recovery context must bind the exact prior static review, approval,
runtime binding, original lease, committed session receipt, two Running samples,
fault intent, terminal, stop intent/result and missing receipt, authority fence,
all process creations, and held admission row. Include the historical context
used by normal review 10 and that run's successful stop as history; neither
becomes a claim about this failed stop. Require fresh creation-identity retirement
checks and two consistent Aborted/unlocked/PID-zero profile observations around
new capture. Inaccessible processes, saved-state references, changed hardware,
enabled transports or executor drift hold.

Capture a new independent unattached byte-copy of guard disk, configuration and
existing NVRAM. Preserve its disk UUID; never attach/register it. Use a distinct
typed context/profile/backup binding that literally records Aborted and includes
the complete history. Do not relabel old v2 poweroff receipts or old captures.
The unchanged file-lock, identity, rehash and exclusive-output rules still apply.
Copying happens unarmed and issues no VM command.

The inert successor artifact must name one case, the exact fresh inputs, all
source/image pins, the old held-row digest, the target, one new output path and
the proposed transfer. Initial implementation should support only a normal
guard recovery startup/session/stop case. No compound fault campaign or executor
activation is implied. Actual native activation still needs its own exact
approval of that artifact, including the transfer, after preparation is verified.

## Reservation transfer, without accepting the old stop

Prepare a typed continuation record with unique prior and successor admission
IDs and hashes. The production ledger must remain untouched during preparation;
exercise migrations and transactions on scratch copies only.

At a later separately approved activation, one database transaction must compare
the complete expected held prior row, verify its target and inactive old
authority, consume the exact new approval once, insert the immutable continuation
link, set only the old reservation's `active` field to zero, and allocate the
successor's active reservation. The old row's `state` stays `held`; its stop
receipt remains null. This is an explicit transfer of target exclusion to fresh
authority, never successful settlement of the old operation.

The transaction must enforce one successor per prior admission, one active
target, no fork/cycle, and one consumption per new artifact. A mismatch, revoke,
stale history or competing consumer refuses the entire transfer. Process
allocation starts only after confirmed commit and readback. Lost commit
acknowledgement holds; reopening may inspect the outcome but cannot dispatch or
replay it. An uncertain migration also holds without automatic repair.

A successor that fails while unarmed must retain the inherited target hold.
The existing ordinary `release_unarmed` behavior cannot discard that hold.
Only the successor's independently accepted normal stop may release its active
reservation. Its failed/unknown stop retains the reservation and requires a new
reviewed continuation. All ancestors remain held history. No extra original-stop
command, old owner revival, lease renewal, restore or automatic retry is added.

After confirmed transfer and protected unarmed hashing, construct one fresh
original owner and immutable lease of at most 600 seconds. Bind its actual
identities/clocks before the single frontend resume. Initial Aborted may progress
only to Starting and Running under the distinct grant. Startup/sample/heartbeat
bounds, final gates and the original stop reserve remain unchanged. Normal
acceptance still requires a successful original command, natural zero family
exits, empty jobs/pipes and independent poweroff/unlocked proof.

## Preparation checks and runtime prerequisite

Before modifying any real admission ledger, resolve the
[storage-runtime finding](../../research/validation/coordinator-storage-plan.md).
Use a verified patched build for transaction qualification. Current read-only
integrity checks pass; they do not establish absence of a future storage race.
Runtime installation remains separately authorized.

Preparation must demonstrate concurrent competing successors, revoked/stale
approval, changed prior row, missing history/NVRAM, live or inaccessible old
processes, replay, fork/cycle, drift during capture, migration interruption,
lost transaction acknowledgement, revocation before/after arming, inherited
unarmed holds and successful/failed successor stop. Use scratch ledgers and
actual Windows Python jobs/owners/frontends with synthetic VM observations and
Python surrogate stop commands. Assert no native command in every preparation
case and preserve all earlier evidence unchanged.

Record measured read-only capture separately from those synthetic observations.
No preparation result may set the old stop accepted or clear the actual held
reservation. A later native artifact must disclose Aborted as the initial state.

## Decision requested and alternative

Approve implementation, scratch/Python tests, read-only inventory and unattached
backup capture for this preparation only. Any runtime/dependency installation,
real-ledger transfer or native activation remains separately reviewed.

The alternative is to leave the guard held and prepare a separately approved
replacement or restore. Either changes VM/storage state and must preserve the
old evidence. The proposed continuation preserves the existing guard and makes
the authority change explicit. Choosing it is a major decision under
[AGENTS.md](../../AGENTS.md), because it changes target-reservation ownership and
extends the offline review path to an initial Aborted state.
