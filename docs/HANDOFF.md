# Agent handoff — held-guard successor preparation

Updated November 24, 2026. **The full product is incomplete.** The developer resumed
the original R1–R9 objective after the earlier goal pause. Decision 0007 preparation
is measured. A real reservation transfer or VM boot is still not authorized.
**New agent: start with [NEXT_AGENT.md](NEXT_AGENT.md).**
Continue the entire [vision](vision.md) and [R1–R9 delivery plan](product-delivery-plan.md).
Keep this file and [status](status.md) accurate at each meaningful stopping point.

## Resume here

Decision 0007 preparation now has scratch-ledger tests, Python surrogates, a fresh
read-only inventory and one unattached backup. The production admission row stays
held/active=1. Scripted P2 acceptance is measured, and scripted P3 model policy
and cost is measured: schema 7, eligibility, broker permits, call identities,
cumulative limits, a protected review allowance, and known/estimated/pending/unknown
reports. The product-web venv rerun count is in [status](status.md). Keep live
eligibility off. Do not start a provider call. P4 execution waits on the
qualification lane. Browser QA remains open until URL observation works; do
not restart a server merely to poll that failure. Leave the real held-guard
transfer and any VM boot for a later exact review. Aborted is not a successful
stop. Do not clear the held admission. The goal definition is in
[NEXT_AGENT.md](NEXT_AGENT.md).

Measured preparation used Python 3.15.2 / SQLite 3.53.4:

- `tests.test_held_successor`: 15 passed. Non-native `tests.test_offline_startup`
  classes: 26 passed. Ruff check of the successor files passed.
- `NativeBindingTests` on CPython 3.15 reached controller qualification and then
  recorded `OperationalError: database is locked` for the normal binding case.
  The venv launcher also makes that test's process identity differ. Do not treat
  that class as passing.
- Capture `.local/validation/held-successor-capture-01`, evidence
  `research/validation/held-successor-evidence.json`. Status
  `held-successor-capture-reported-not-boot-authority`. `transferred` is false.
  Context SHA-256 `f6767a56f310c73bdab1482962a44167cb51b47de02afbcd43d232eee17eded8`.
  Guard was aborted/unlocked/PID-zero before and after the copy. Executor was
  poweroff/unlocked/PID-zero before and after. Copied disk, configuration and
  NVRAM match the pinned fault hashes below.
- The immutable snapshot row is still `ccc16a8440524bda84e57fdcd90055e7`,
  held/active=1/revoked=0, `user_version` 0, with no continuations table.
  Production ledger and owner hashes below are unchanged. Both WAL files are 0 bytes.
- The first inventory hit the four-second query bound while VBoxSVC cold-started.
  That attempt copied nothing. The warm retry completed. VBoxSVC pid 24848,
  started 2026-11-24 18:32:36 local, was running after that query. No VBoxManage
  or VBoxHeadless process remained then. A later check, after the mapping slice,
  found no VBoxSVC, VBoxManage, or VBoxHeadless process. After the promotion
  slice, Get-Process for those three names again listed none.

No fresh approval is needed for the remaining product implementation and local
scratch tests. The developer approved Decisions **0007 and 0008**, recorded in
[the approval proof](decisions/0007-0008-approval.json). Decision 0008 covers the
full product implementation, local tests and scratch fixture commits. It does
not authorize commits to this repository, deployment, live models or native work.
Decision 0007 preparation is measured. A real held-reservation transfer or boot
needs an exact review.

The exact web dependency installation is also approved and completed. Read
[its approval](implementation/web-install-approval.json) and
[measured evidence](implementation/web-install-evidence.json); do not ask again.
No unapproved dependency may be added under that approval.

## Implemented product and measured results

`coordinator/` is independent product code with no research imports:

- Core: versioned project/context/requirements, validated dependency plans,
  exact-digest approval, task attempts and absolute caps, durable prepared and
  possible-send operations, pause/revision/recovery fencing, late/conflicting
  observations and ordered audit events. One unsettled attempt per milestone.
- Store: schema v7 SQLite on local storage, explicit transactions, WAL/FULL/FKs,
  command ACK-loss deduplication bound to actor/role/intent. Backup archives and
  copied/moved databases refuse business writes through the primary-path gate.
  Explicit offline migration from schemas 1–6 captures a verified archive before DDL,
  refuses source drift and rolls back failed schema changes. Ordinary startup
  refuses a mismatched user_version. Do not migrate the retained evidence database.
  Archive restore/path rebinding and power-loss durability remain open.
- CLI: JSON application commands with the local OS-user identity. Commands remain
  init, migrate, project, plan, task, scripted, status, and backup. Promotion is
  a Python integration path, not a CLI command. Status `capabilities.task_acceptance`
  stays false. Dependent tasks release only through the serialized promotion below.
- Web: FastAPI API uses those same commands and a server-owned developer identity.
  Loopback-only 127.0.0.1, exact Host/Origin, bounded strict JSON, session/CSRF,
  HttpOnly/SameSite Strict cookies and local assets. Dashboard code supports
  create/revise, plan import/exact approval, task state and pause/resume/recover.
  See [web usage](product-web.md). This is not remote/TLS or production deployment.
- Source: `source.py` validates immutable bounded byte maps and constructs real
  blobs, trees and single-parent candidates in new managed bare repositories.
  It refuses unsafe paths/types/aliases, out-of-scope edits, config/alternates
  drift and conflicting/symbolic private refs. One candidate per attempt; an
  identical re-delivery reconciles the same ref. `evidence.py` publishes artifacts
  by SHA-256 without replacing existing bytes. See [the source contract](product-source.md).
  `intake.py` now connects these to the product ledger: one immutable source
  intent per approved attempt, committed possible-send before Git, producer/
  repository bindings, exact commit/source observation and frozen review packets.
  Slow Git/file work stays outside SQLite write transactions; admission rechecks
  current authority. Reconciliation only reads an existing private ref, never
  calls seal or creates a missing effect. Pause/revision fences intakes and late
  observations remain held. Local composition supplies the trusted service
  principal; no remote controller-authentication endpoint is exposed yet.
  See [the protocol and migration](product-intake.md). No native stop proof or task release.
- Verification: `verification.py` adds exact developer policy approval, complete
  check definitions/cases and environment bindings, assigned producer roles,
  durable prepared/possible-send operations and immutable observations. Review
  admission waits for all check passes and binds a new packet to those receipt
  digests, rubric and fresh session. Coverage gaps, wrong bindings, changed
  context/artifacts and late/conflicting receipts cannot qualify. A conflict
  fences project authority. Fresh `gate()` rechecks objects and evidence.
  All profiles/results are scripted development only: a green candidate gate can report
  development readiness for integration, and live eligibility stays false. Verification
  does not promote or release a dependent task. No test or model execution exists.
  Principals are trusted local composition, not a deployed remote authentication
  boundary. [Protocol](product-verification.md). Status now includes operation records.
  New scripted dispatches record implementation actor/context in contract v2;
  old unknown-identity candidates cannot qualify reviewer independence. Migration
  never invents retrospective identities or new native permission.
- Integration: `integration.py` admits one immutable proposal per intake from
  the fresh candidate gate, commits possible-send before private Git staging,
  stores the exact stage/packet and reconciles existing refs without replay.
  Developer-approved regression profiles and assigned producers bind receipts to
  proposal/head/integrated OIDs, source, policy/environment and generation.
  Failed/incomplete/stale or conflicting regressions cannot qualify; conflicts
  fence the project. Before/after source artifacts are checked as well as Git.
  Source staging supports clean ordered two-parent merges, conflict/scope refusal
  and a separate retained intent object even for direct I=C. Schema 5 adds one
  `integration_head_mappings` row per attempt. A developer authorization binds
  the attempt, previous expected head, new head, and authority generation.
  `prepare` refuses a missing, stale, different, or consumed mapping.
  `begin` consumes a matching mapping once with possible-send. Staging then uses
  that head as its base. Schema 6 adds integrated evidence and one promotion row.
  Distinct integrated commits need fresh checks and a separate review on that
  OID. `I = C` can become promotion-ready from candidate evidence plus
  regressions. `begin_promotion()` commits possible-send, then a private
  milestone ref CAS and one database transaction record the commit, one
  acceptance, and `attempts.settled=1`. Project generation is not bumped.
  Missing or old refs hold without replay. A second reconcile does not write the
  ref again. Task 2's input is the accepted revision. The promotion result may
  set `task_accepted` true; status `capabilities.task_acceptance` and
  `live_eligible` stay false. Real execution stays false.
  `update_validation_ref()` exercises CAS only under the private validation
  namespace; it is not a product promotion or an acceptance grant.
  [Integration protocol](product-integration.md).
- Model policy: `model_policy.py` records one scripted policy per milestone, one
  eligibility assignment per attempt role, and one permit per submission id.
  Unavailable routes, fallbacks, and submission replay are denied. The protected
  review allowance cannot be spent by implementation. Unknown and estimated
  usage keep their reservations; a known amount settles only that amount. Pause
  does not release a reserved permit. Reports separate known, estimated, pending,
  and unknown units. No provider call and no live route.
  [Model policy](product-model-policy.md).

Latest retained product cohort: **87 tests passed, no skips/errors/failures**
(15 core + 11 HTTP + 12 Git/artifact + 17 intake/migration + 16 verification +
16 integration), under Python 3.15.2 / SQLite 3.53.4 /
Git 2.56.1.windows.1. Ruff, formatting and whitespace checks passed.
The tests include actual child-process exits 29 before and after a private ref
update; recovery holds missing effects and reconciles an existing candidate
without replay. They also cover competing dispatches, pause/revision, changed
refs/artifacts, preflight authority races, backup drift and migration rollback.
The retained smoke joins real plan approval, attempt, intake admission, scoped
Git bytes, immutable review packet and durable status; T2 remains blocked. It
also runs the new migration through the CLI. Integrity/FKs and Git fsck pass.
The latest smoke additionally joins approved check/review profiles, real operation
records and immutable scripted receipts under distinct local service identities.
Its candidate gate is green for development only; live eligibility/acceptance
remain false and T2 is still blocked. New tests cover reviewer rejection after
green checks, wrong producers/contexts, missing coverage, receipt conflicts,
artifact/ref changes, session reuse and process exit after verification dispatch.
Migration from v2 preserves a held intake and unknown implementation identity.
The new integration cases include actual direct/clean-merge/conflict staging,
expected-head guards, child-process death after stage and validation-ref writes,
read-only recovery, competing admissions, regression conflict/rejection, lost
prepare acknowledgements and missing original source artifacts. A v3 migration
case preserves possible-send verification without creating stage authority.
The retained smoke includes separate private merge/CAS controls and the full
scripted regression join; its application milestone head remains at baseline.
No candidate code executes. No host-power-loss or independent-review-quality
claim follows from process-death or scripted source tests.

[Current evidence](implementation/product-integration-evidence.json) and raw artifacts:
`.local/validation/product-integration-01/`. This includes source snapshots, unittest
log, intake/check/review/staging/regression smoke, private Git merge/CAS controls,
migration CLI result and managed repository/artifact store.
The prior [verification evidence](implementation/product-verification-evidence.json)
retains 70 tests and its original candidate verification smoke.
The [prior intake cohort](implementation/product-intake-evidence.json) retains
53 tests and its original intake/migration results.
The earlier [source cohort](implementation/product-source-evidence.json) retains
38 tests and its original primitive Git smoke; those source/document pins are historical.
Earlier [web cohort](implementation/product-web-evidence.json) retains 26 tests;
earlier [core cohort](implementation/p1-core-evidence-02.json) retains 15 tests and
21 actual CLI subprocess calls. Their old source hashes remain historical.
Do not run an old current-source verifier and “fix” it by rewriting those hashes.

All 19 approved wheels are installed in `.local/product-web-venv`; every installed
RECORD hash, version, original wheel and base executable hash verifies, `pip check`
passes and base Python still has only pip 26.2.2. The original approved plan and
preinstall manifest are preserved; do not rewrite them as postinstall evidence.
Starlette's TestClient deprecates its working HTTPX adapter. The warning is retained;
HTTPX2 was not installed. Manrope/OFL provenance is in `web_assets/font-source.json`.

Browser host was unavailable. Native browser selection then stopped because
Computer Use could not confidently determine the browser URL. No UI actions
were performed. Temporary synthetic server PID 23088 / port 8876 / exec 3864 was
command-line verified and terminated with taskkill after Ctrl-C/Stop-Process did
not settle it; exec 3864 ended with exit 1. Cleanup proof:
`.local/validation/web-browser-01/cleanup-result.json`. Browser QA remains open.

## Runtime and verification

Use `.local/product-web-venv/Scripts/python.exe` for product/web checks. It is
Python 3.15.2 / SQLite 3.53.4. Existing `C:/Python315/python.exe` is the same patched
base and can run dependency-free core work. Bare `python` selects Python 3.13.17 /
SQLite 3.50.4, affected by WAL-reset; do not use it for new authority writes.
SQLite source ID:
`2026-07-24 19:02:57 bf7c7f30031888f4e796e429ab3978879485813aaca6f641c7b33e4e09459bcc`.

```powershell
git status --short
.local/product-web-venv/Scripts/python.exe -m unittest tests.test_coordinator tests.test_coordinator_web tests.test_coordinator_source tests.test_coordinator_intake tests.test_coordinator_verification tests.test_coordinator_integration -v
ruff check coordinator tests/test_coordinator.py tests/test_coordinator_web.py tests/test_coordinator_source.py tests/test_coordinator_intake.py tests/test_coordinator_verification.py tests/test_coordinator_integration.py
ruff format --check coordinator tests/test_coordinator.py tests/test_coordinator_web.py tests/test_coordinator_source.py tests/test_coordinator_intake.py tests/test_coordinator_verification.py tests/test_coordinator_integration.py
python .local/validation/verify-product-integration-01.py
```

The file-only verifier can use bare Python: it does not access authority databases.
Do not casually rerun the expensive old research full suite. Its last complete
patched cohort remains **609 tests: 594 passed, 14 skipped, one startup-BEGIN BUSY
error**. Four focused actual-SQLite lock diagnostics subsequently passed with
synthetic VM facts. The earlier writer/timing remains unknown; the failed complete
research result is not repaired by passing product tests. The historical verifier
is `.local/validation/verify-tested-recovery-sources.py` (90 old snapshots).

## Native state and authority — untouched

Latest consumed native review SHA:
`0925de6acf1a400301d84abf1177a0596f811ff142597e3e74ddc52c4f13a788`.
Root `.local/validation/offline-guard-run-ccc16a8440524bda84e57fdcd90055e7`;
binding `280de430cee4d69e60c76cc44022c180b52c71fa7fcf843fef0def3526c85dca`.
One disconnected guard boot accepted two Running samples (PID 33132), then
controller exit 29 was contained in 2.668 seconds. Original sole stop exited 1,
still possible-send/no receipt. **Aborted never counts as successful shutdown.**

Last guard UUID `0eceb37e-f216-45ed-817c-7cf2fca3a32a` was Aborted/unlocked/PID-zero;
executor `74129e9c-5a65-44fa-9d35-79d458dc4704` was poweroff/unlocked/PID-zero;
NICs disabled. Latest run preserved disks, guard NVRAM and executor files; guard
abort/time metadata changed to `6388740c34b3ce72b8d66f384a66c82d36fe9b8385a519998b7083ab07e29046`.
A later read-only inventory and unattached copy is recorded in
`.local/validation/held-successor-capture-01` and
[successor evidence](../research/validation/held-successor-evidence.json).
It does not transfer the reservation or accept the Aborted stop.

Actual admission row `ccc16a8440524bda84e57fdcd90055e7` remains **held/active=1**;
original authority is fenced. No reset/delete, clearing/releasing exclusion,
replay of old owner/stop, direct ledger bypass or `finish(settled=True)`.
Old stopped-refresh-03/backup-guard-02 predates this fault; recovery V3/capture06
cannot admit current state. Decision 0007 preparation tests and the unattached
capture are recorded; the real transfer remains unapproved.
Unarmed successor failure must preserve inherited exclusion. Native evidence:
`research/validation/guard-controller-loss-evidence.json`.

Both real journals remained byte-identical during the latest retained run:

- `.local/validation/offline-guard-admissions.sqlite`:
  `f1eac66681934fd294c73efeb580ebc102b64e6586a17a13bdd7a1bec488260a`
- Original owner `owner/owner.sqlite` under the run root above:
  `24bab655c096ee1fa16b4f4bed2d04a76a167eee93de7e0fd21c54cefade0313`

## Workspace and evidence continuity

Workspace `E:\Home\Documents\Programming\ai-dev-orchestrator`; branch
`research/m1-11-executor-recovery`; HEAD `e609dbce6af8f3f845ea8226bf2648fbe245197c`.
Preserve the many dirty/untracked files and `.local` artifacts. HEAD alone is
insufficient for another agent. No agent commit/push/release was made. No subagent
delegation is authorized. Use graph tools first for code discovery.

**No live task handle remains.** The schema-7 product-web venv suite
`9e9e7f5e-c9fb-4a0d-a1d6-ca647bb418f6` ended with exit 0 (109 tests, 0 skips).
The schema-6 suite `b3815b81-3df9-47d6-bde7-d058ca879851` ended with exit 0
(100 tests, 0 skips).
The focused integration and intake run
`call-827b4159-63b3-4083-b423-410138c5a562-114` ended 0 (46 tests).
The retained 87-test run exec 91255 ended with exit 0;
focused integration execs 98712/98285 ended 0. Prior full 80477 ended 0;
focused verification execs 4158/16074 and baseline 14580 ended 0. Prior full 9279 ended 0;
focused intake exec 66200 and prior full product exec 4364 also ended 0.
Older native 64990 ended 0; research 70775/66588 ended 1; focused 95869 ended 0;
installation 46627 ended 0; CLI smoke 69200 ended 0; synthetic web 3864 ended 1.
There is no browser task, test server or subagent to resume. Revalidate external
state before any separately authorized native action.

Historical mappings are immutable:
`historical-source-resolution-01.json` (31 entries),
`handoff-2026-11-24-01/historical-document-resolutions.json` (4),
`p1-core-01/prior-document-resolutions.json`, `p1-core-02/prior-document-resolutions.json`,
and `web-checkpoint-01/prior-document-resolutions.json` (9 prior core document pins),
all below `.local/validation/`. This turn's superseded documents, including the
previous mixed handoff, are retained under `product-source-01/prior-documents/`
and `prior-documents.json`. Never rewrite old results to match current sources.

Current prior-document resolutions are in
`.local/validation/product-integration-01/prior-document-resolutions.json`; they resolve
the old 70-test checkpoint's document pins without changing historical evidence.
The earlier `product-verification-01/prior-document-resolutions.json` resolves
the 53-test checkpoint.
The earlier `product-intake-01/prior-document-resolutions.json` still resolves the
38-test checkpoint. Preserve both.
Existing schema-v1 examples/archives are historical; do not migrate retained
evidence stores merely to try new code. Use a new scratch instance instead.

Remaining full scope: deployed
runner/reviewer authentication and actual qualified verification, live model
routes, qualified P4 integrations, real P5 two-task milestone, P6 discovery/lifecycle/
self-hosting/release preparation. Installations, native changes/activation,
provider-data/paid experiments, remote writes and publication retain separate
approval gates. The developer requested pausing for handoff; the 87-test increment
is not completion. Handoff document changes preserve prior pins through
`.local/validation/agent-handoff-2026-11-24-02/prior-document-resolutions.json`;
use `python .local/validation/verify-agent-handoff-02.py` for this pickup checkpoint.
