# Storage runtime review before new admission writes

Status: **Source finding and read-only measurement, November 24, 2026.** No
runtime, dependency, database mode, schema or VM was changed.

Installed Python reports **3.13.17**, with bundled SQLite **3.50.4**. Both the
offline admission ledger and the consumed run's original-owner journal report
WAL mode. Read-only `integrity_check` returns `ok` and `foreign_key_check` returns
no rows for both. Their database bytes remained identical during inspection;
source-byte archives and the exact SQLite source ID are retained in
[evidence](coordinator-storage-evidence.json). The guard admission still has
`state: held` and `active: 1`; original authority is fenced and stop remains
`possible-send` with a null receipt.

## Primary-source finding

SQLite's [WAL-reset advisory](https://www.sqlite.org/wal.html#walreset), page last
updated August 25, 2026 and reviewed November 24, describes a rare corruption
race involving concurrent connections, writes and checkpoints. It lists fixes
in 3.51.3 and later, and backports 3.44.6 and 3.50.7. The installed 3.50.4 falls
inside the documented affected range. This is a source-based applicability
finding, not a reproduced failure or a diagnosis of earlier `SQLITE_BUSY` events.
Passing integrity checks establish the current check result only.

## Required next preparation

Before new native admission writes or product persistence qualification, select
an exact patched Python/SQLite distribution, record its artifacts and SQLite
source ID, and verify that the chosen build includes the upstream fix. A numeric
minimum alone is insufficient for separately maintained release branches. Prepare
the dependency/runtime plan before requesting installation. Do not replace the
host Python or upgrade any existing fixture image implicitly.

Use the selected runtime first on scratch copies and a new product store. Verify
transaction behavior, concurrent admission, crash/reopen, backup/readback and
migration compatibility. Keep the original journals and archived bytes. Any
actual ledger migration needs a concrete reviewed plan, stopped writers and
verified backup, and must preserve the held outcome. An integrity check or a
runtime upgrade never grants a retry or releases the guard reservation.

This finding adds a prerequisite; it does not invalidate retained observations
or turn 608 passing harness checks into proof of patched storage. Host power-loss
durability and a hostile host remain outside those measurements.

## Preinstalled candidate and compatibility result

Further read-only inventory found an existing **Python 3.15.2** installation at
`C:\Python315\python.exe`. It reports SQLite **3.53.4** and source ID
`2026-07-24 19:02:57 bf7c7f30031888f4e796e429ab3978879485813aaca6f641c7b33e4e09459bcc`,
matching the [official 3.53.4 release](https://www.sqlite.org/releaselog/3_53_4.html).
No installation was needed. This does not change any existing grant's executable
binding or adopt a new product runtime.

The first unchanged-source cohort ran 608 tests: 589 passed, 14 skipped, two
failures and three errors. Five whole-binder cases replayed the historical
stopped-refresh-03 profile while reading the real guard configuration, which the
approved native fault had since changed. They correctly held before reaching
their intended barriers. This did not establish a Python-version failure.

The fixture now uses separate scratch copies of the frozen guard/executor
configuration and NVRAM in both bootstrap and worker. Existing source/backup
disk pins and actual read locks remain. Existing scratch files are never
overwritten to repair drift. A new negative case confirms the real preactivation
check still refuses changed scratch metadata before owner activation. No
production admission code, retry policy or deadline changed.

All six focused Windows Python binder cases passed. The subsequent frozen full
cohort ran **609 tests: 594 passed, 14 skipped, one error**. Its controller-loss
case held before resume: the retained trace records `possible-resume`,
`start-begin-failed`, SQLite BUSY code 5, no open transaction and no retry. The
exact competing writer/timing is unproven. **Complete compatibility qualification
remains open**; the focused pass does not replace that failed cohort. Thirteen
skips are platform limitations and one is optional PyYAML absent in this
interpreter. No dependency was installed to suppress that skip.

Both real journals retained their byte hashes and passing read-only integrity
results; the old stop/admission remain held. [Candidate evidence](patched-runtime-evidence.json)
preserves both full cohorts, source snapshots, runtime binary hashes and the
startup diagnostic. The next technical check is the known-BEGIN-non-entry
startup hold; no native replay or increased transaction/deadline allowance is
authorized by this measurement.

## Controlled startup-entry check

A subsequent real SQLite connection held `BEGIN IMMEDIATE` at the
`possible-resume` gate. The existing connection raised BUSY code 5 before entering
the transaction. The controlled test proves that frontend resume does not occur,
the journal stays `intent` with no process binding, authority is fenced, original
lease clocks stay unchanged and a second launch is refused. Family/VM/owner facts
are synthetic; this adds no physical containment claim. Four focused startup
diagnostics passed under Python 3.15.2 / SQLite 3.53.4 with retained observations
and source snapshots. See [controlled evidence](startup-entry-lock-evidence.json).

This reproduces the observed branch under a known competing connection. It does
not identify the writer in the earlier full run. No production behavior or
waiting/retry/deadline allowance changed. The last complete cohort remains failed
(609 tests, 594 passed, 14 skipped, one error); the current tree collects 610
tests after the additional negative case and has not had a complete rerun.
Both actual held journals retain their measured byte hashes. Decisions 0007/0008
still require the developer's response before their dependent work can begin.
