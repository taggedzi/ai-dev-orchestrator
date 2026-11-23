# Same-boot maintenance session preparation

The developer approved [decision 0003](../../docs/decisions/0003-maintenance-same-boot-review.md)
for session-model preparation on November 22. [maintenance_session.py](maintenance_session.py)
now connects inspection, exact review and controls through the existing transfer
controller. It has no native activation CLI and does not grant boot, installation
or network authority.

## Session ownership and phase admission

One session uses the original owner's exact `owner.sqlite`, sealed launch,
controller process identity, owner binding and immutable wall/monotonic lease.
Review expiry is fixed at construction and leaves the original stop reserve.
Neither review nor a new phase renews that lease. A second constructor refuses
an existing session; restarting cannot restore its control path.

An inspection succeeds only after both serial exchanges return with the worker
reaped and the source-bound transport cleanup complete. Its raw outer response,
canonical inspection observation and exact proposed action list are retained in
the session row and audit events. The inspection worker and its authority sampler
close before entering review. A separate read-only sampler then monitors the
original target/owner. Sampling failure, controller/PID drift, stale owner pulse,
source changes or expiry fence the same original authority without requiring
another conversation turn. The existing original owner issues the stop.

`awaiting-review` preserves the original VM lifetime authority but grants no guest
dispatch. The Store checks this distinction atomically with serial intent. A
standalone controller cannot use a session Store. During a phase, only that phase's
identity/upload IDs are eligible. Their nonce derivation now includes inspection
versus controls, so the two phases have four distinct durable operation IDs while
the guest observation remains bound to the same session nonce and boot ID.

Controls require the exact approved grant, retained observation hash, action-list
hash, target, owner, original lease and source cohort. The new phase cannot extend
review expiry. The review sampler must close before dispatch. Approval and
revocation serialize through the same SQLite authority; a changed, late, replayed
or interrupted approval cannot start controls. The existing guest control program
still performs its fresh inspection and compares stable facts/actions, excluding
only its documented guest timestamp.

After controls, the existing original-owner stop ledger and independent host
poweroff observation are both required. The host adapter now understands the
session's exact phase stop intent. Standalone stops still require their original
grant. Results remain reports rather than installation or task acceptance.

## Measured checks

All **15 session checks** passed. Fourteen use synthetic guest/owner/query facts,
including a complete handoff through the real host-adapter parser and stop
observer with injected raw inventories. They cover no-dispatch review, expiry,
changed boot/lease/PID/approval, replay, lost inspection acknowledgement,
interrupted journal writes and a revocation race.

One Windows check uses the actual independent owner process and stop loop. An
unanswered review fences the original Store and yields exactly one Python
surrogate stop, retaining the original lease. Guest/query facts and the test's
caller-to-controller identity mapping are injected; this does not qualify native
session caller admission or a real VM stop.

The final full regression passed **352 tests: 339 passed, 13 platform skips**.
Ruff passes. [Evidence](maintenance-session-evidence.json) retains the exact source
cohort, log, skipped-test identities and native-process artifacts. The unarmed
session review is `.local/validation/same-boot-review-01/session-review.json`.

## Remaining activation work

No selected target has run this session. Authenticate approval issuers and protect
the root console against other host processes; an approval string/hash is only a
consistency binding. Qualify genuine backup/preboot receipts, native caller/job
admission, startup settlement, running UART collection and the complete original
stop deadline. Evidence capture remains bounded to the host adapter's 256 samples;
exhaustion holds rather than extending the review.

Earlier stop, host, owner and transfer packets retain their historical source
cohorts. They were not rewritten or armed. Prepare successor grants against this
cohort before activation. Expired or rejected review leaves a stopped/uncertain
session for manual reconciliation; it never authorizes a resumed phase.
