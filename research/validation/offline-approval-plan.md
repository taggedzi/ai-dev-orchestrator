# Initial approval before the native lease

Status: **Decision 0006 preparation implemented and verified.** The developer
approved implementation, Python surrogate tests and read-only checks on November
24, 2026. This gives no native-run or product implementation authority.
[Evidence](offline-approval-evidence.json) retains the tested source cohort,
actual Windows Python cases and actual read-only preflight.

**Latest native result:** separate exact approval consumed the inert review below
once. One guard boot reached two accepted Running samples; deliberate controller
exit 29 was contained in 2.668 seconds. The original stop exited 1, so the admission
and target reservation remain held. Guard is Aborted/unlocked; executor is
poweroff/unlocked. Both disks, guard NVRAM and executor files are unchanged.
[Native evidence](guard-controller-loss-evidence.json) records this narrower
containment result, not successful shutdown or further run authority.

## Inert review and explicit activation

`python -m research.validation.offline_startup prepare --case controller-loss
--output <new direct child of .local/validation>` creates an immutable review
artifact only: zero native calls, processes, jobs or leases. The normal case is
also supported. Initial-Aborted recovery and executor startup keep their existing
paths; this preparation does not extend them.

The artifact binds its ID, fixed guard/disk, exact command/image/environment,
sources, backup/current profile/preserved executor receipts, named case/faults,
permitted writes, one boot, one original stop, timing limits and future output
path. Its distinct approval format is `mcli1-offline-guard-native-approval-v1`.
Preparation approval and old live-review approvals cannot enter this path.
Initial human review has no live countdown because no execution authority exists.

An explicit `activate --review <artifact> --sha256 <exact digest> --approval
<exact approval file>` command follows separate native approval. Writing an
approval file alone starts nothing. Actual PID creation identities, jobs and
absolute lease clocks become verified outputs of the trusted binder. A
digest/reference is not hostile-host authentication; existing trust/ACL limits remain.

## Consumption, protected preparation and binding

The fixed `.local/validation/offline-guard-admissions.sqlite` consumes the artifact
before preflight/process allocation. One active-target reservation prevents two
approved artifacts preparing the same guard concurrently. Restart, another output
path, failed preflight or lost consumption/arming acknowledgement cannot allocate
another session under that artifact. Uncertain native actions are never replayed.

After initial read-only preflight, a bounded Python worker in the existing
controller job hashes current guard files, all unattached backup files and all
preserved executor files. It holds read-sharing handles throughout preparation.
Its 600-second unarmed preparation budget is not another VM lifetime: no original
owner or execution lease exists during hashing. The same process later becomes
the controller, avoiding a transfer gap between processes.

Verified worker readiness, unchanged locked identities and another fresh native
stopped-profile observation precede original-owner construction. The immutable
wall/monotonic lease begins there, before seal/resume/start, at most 600 seconds.
A distinct runtime binding/input hash must match the one armed ledger row. The
worker borrows its measured handles once; the existing final suspended gate
checks and releases them before the sole frontend resume. Expensive hashing is
not repeated inside the short start grant. Startup/heartbeat/stop bounds remain fixed.

The original owner remains the only poweroff issuer. Revocation serializes with
arming in the admission ledger and fences the original Store afterward. Neither
revocation nor cleanup adds a replacement VM command.

## Holds and settlement

Physical containment precedes admission reporting. Failed/interrupted/unknown
admission remains consumed. Proven fully retired unarmed failure can release
the target reservation for a separately approved new artifact; it cannot reuse
the old artifact. Native uncertainty/controller loss retains the held reservation.
No generic reset, takeover, automatic retry or restore is supplied.

Unknown owner activation/readiness is not a confirmed stop. Zero or one original
stop may have occurred after a lost acknowledgement; neither is replaced or
accepted without proof. Normal acceptance still requires the original successful
command, natural zero frontend exits, empty jobs/pipes and independent poweroff.
Aborted is not successful shutdown. Decision 0003's running-guest review still
consumes its original armed lease.

Startup BEGIN/body/COMMIT phases now retain error/code diagnostics without
changing retry behavior or clocks. Existing bounded known-BEGIN-non-entry waiting
for join/stop-request remains unchanged. A developing normal Python case held on
SQLite locking without its exact phase retained; diagnostics do not reconstruct
it. Complete frozen regression passed, including known stop-request BEGIN BUSY
handled within the existing budget and only one original stop. Contention-free
startup is not claimed.

## Verification and current native decision

Full regression: **608 tests, 595 passed, 13 platform skips**, no failures/errors
or source drift; Ruff passes. Five actual Windows Python cases cover normal
binding/finish, controller loss, revocation before arming, lost owner activation
acknowledgement and revocation after arming. VM observations are synthetic replay;
all poweroffs are Python surrogates. Test leases were 30 seconds. Direct checks
also cover the immutable 600-second maximum and long human delay.

Actual read-only preflight separately verified nine protected files and both
stopped/unlocked/disconnected native profiles. The inert controller-loss artifact
is `.local/validation/offline-guard-review-01/review.json`, SHA-256:

`0925de6acf1a400301d84abf1177a0596f811ff142597e3e74ddc52c4f13a788`

At preparation time its approval and activation output were absent. The developer
then approved this exact artifact and explicitly requested execution. It is now
consumed; runtime binding SHA-256 is
`280de430cee4d69e60c76cc44022c180b52c71fa7fcf843fef0def3526c85dca`.
The original stop remains `possible-send` with no command receipt, and admission
is `held`/active. No replay, reservation release or restart is authorized. A later
run requires reviewed recovery provenance and settlement semantics first;
poweroff-only admission refuses the current Aborted guard.

This run qualifies only the named joined-controller-loss containment case.
No setting change, guest command, installation, networking or restore ran.
Isolation, executor recovery and product requirements remain unqualified.
Kernel/filesystem stalls, physical power loss and hostile-host guarantees remain
outside these measurements.
