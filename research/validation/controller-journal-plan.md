# Controller journal contention preparation

Status: **Preparation verified; native activation remains separately gated.**
The separately approved [native review 10](guard-startup-normal-stop-evidence.json)
subsequently committed one binding before publishing its receipt, accepted two
running samples and completed the original single stop successfully. No BUSY was
observed in that native run; controlled contention tests remain separate evidence.
Only the normal startup/session/stop case is qualified, and no further native
authority remains. The preparation history below retains its original scope.
The [consumed native run](guard-startup-journal-hold-evidence.json) reached Running
and identified its frontend PID, then failed while recording the join. Its
receipt file did not have a committed database binding. The exact old transaction
statement and competing writer were not retained and are not reconstructed.

## Measured reproduction and correction

A real second SQLite connection reproduced `SQLITE_BUSY`, a receipt file and an
in-memory join while the old ledger stayed `resumed`. SQLite's
[transaction documentation](https://www.sqlite.org/lang_transaction.html) explains
that `BEGIN IMMEDIATE` can fail when another writer is active; COMMIT has distinct
error semantics. Python exposes the low-level transaction state through
[`Connection.in_transaction`](https://docs.python.org/3.13/library/sqlite3.html).
The measured runtime uses Python 3.13.17 and SQLite 3.50.4.

The private controller now waits only for ordinary `SQLITE_BUSY` at BEGIN when no
transaction opened. The budget is one second, at most sixteen entry attempts,
under the unchanged original lease, startup/heartbeat/observation bounds and stop
reserve. Every new entry attempt rechecks authority, source/family identity and
absence of an original native stop intent/record. The SQLite busy timeout is
temporarily capped at 50 ms and restored afterward. This is a loop budget, not a
claim that kernel/filesystem stalls are interruptible or hard real-time bounded.

The transaction body and COMMIT are never replayed. Unknown/extended error codes,
open or uncertain transactions, rollback uncertainty, lost commit acknowledgement,
revocation, expiry and publication failure still hold. The same narrow entry wait
covers the joined controller's original-owner stop-request journal; it issues no
VM command and cannot duplicate the original owner's one-shot command.

A successful database commit now precedes exclusive receipt publication, which
precedes accepting the in-memory join. Failure after commit still holds and
fences authority; neither a receipt nor a database row alone establishes an
accepted run. Bounded phase/error-code traces are retained after physical
containment and fencing, so diagnostic publication cannot delay containment.

## Verification and fresh recovery inputs

Final regression ran **556 tests: 543 passed, 13 platform skips**, with no
failures/errors. Fifteen new SQLite controls cover short/long writer locks,
revocation/expiry, body/COMMIT failures, lost acknowledgement, unsupported codes,
publication failure and existing stop evidence. An actual Windows controller,
original owner and three Python frontend processes also survived an independent
writer process, committed one join and completed one original-owner surrogate
stop. Their VM facts remain synthetic. See [retained evidence](controller-journal-evidence.json).

Context version 3 binds the recovery-history anchors in reviews 04, 05 and 07,
their failed original stops, every retained creation and the latest orphan
receipt as unaccepted evidence. A historical null leaf exit never proves death;
fresh independent retirement proof remains mandatory. The new exact guard
configuration hash is
`91c25dbe0e2281892a1cceeef07abc9c8a80d1595b12f1c7e403c1d2edbe17aa`.
Older contexts remain historical and cannot be relabeled for admission. Ordinary
poweroff admission and final poweroff acceptance are unchanged.

Capture 05 hit the unchanged four-second query bound before copying. Its partial
directory is retained; a fresh observation passed, but the timeout's cause is
unisolated. New unattached capture 06, independent readback 03 and read-only
preflight 04 passed without VM activation or setting changes.

The separately approved [review 10](guard-startup-normal-stop-evidence.json)
subsequently consumed capture 06 and passed the normal startup/session/stop case.
That capture now predates guard NVRAM/poweroff metadata. No review, command, lease
or context is replayed. Native failure cases, guest readiness and the product
remain open; another activation needs current bindings and its own exact approval.
