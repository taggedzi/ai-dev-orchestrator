# Durable candidate intake

`CandidateIntake` in `coordinator/intake.py` connects
[trusted source intake](product-source.md) to the product database. It freezes
approved intent, source manifests and review inputs, and records uncertain Git
effects across process loss. It currently accepts **scripted development attempts
only**. It does not qualify native stop/isolation, execute checks or reviews,
promote a milestone, accept a task or release dependent work.

## Ownership and sequence

Trusted local composition supplies a `Coordinator` with a service principal,
managed `TrustedRepository` and protected `EvidenceStore`. The principal is a
configured controller identity, not a credential supplied by an agent or browser.
There is no remote controller-authentication endpoint yet. A developer principal
cannot instantiate this controller; the normal developer CLI/API controls remain
separate. The authenticated status API can inspect candidate intake records.

`prepare()` requires a current awaiting-verification attempt, returned scripted
candidate outcome, current authority generation and requirements, exact approved
plan and unchanged input head. It obtains the task's literal path scope from
that approval. Git reads and artifact I/O occur outside the SQLite write
transaction; authority is checked again at admission. The committed record binds
the repository, project/requirement revision and context, approval, plan/task
digests, attempt/version, generation, input revision and immutable source digest.
One attempt cannot acquire a different source intent after preparation.

`begin()` commits possible-send and a send timestamp before `run()` writes any
Git objects/ref. Competing database connections admit at most one dispatch.
Calling `run()` again refuses. The controller verifies the resulting direct ref,
commit bytes/hash, single parent, fixed intake attribution, exact message and
source bytes. It saves an immutable review packet and observation before marking
the candidate sealed under current authority. Identical observations deduplicate.

After interruption, `reconcile()` only observes an existing candidate ref. It
never calls `seal()` or creates a missing ref. A missing or mismatched effect
holds the intake for inspection; no blind replay follows. A prepared intake with
no committed send timestamp cannot be legitimized by reconciliation. Pause or
requirements revision fences prepared, in-flight and sealed intakes. Late valid
observations are retained as held; resume cannot revive their old generation.
The original sealed receipt remains historical after a conflicting ref is found.

The review packet includes the frozen contract, candidate identity and before/
after source manifests whose bytes are available by SHA-256 in the artifact
store. It excludes implementer conclusions and initially has empty check/review
results. No pass is inferred from packet creation. [Check/review records and
applicability](product-verification.md) now extend this packet with an approved
policy and exact receipt joins. Deployed producer authentication and guarded
promotion/acceptance remain open.

## Schema migration

New stores use schema **7**. Ordinary startup refuses older schemas; it never
upgrades implicitly. For an existing primary v1 through v6 product store:

1. Stop all old coordinator/CLI writers. Preserve the primary at its recorded
   path. Old binaries are not a supported concurrent maintenance participant.
2. Run the explicit migration with a new backup destination:

```powershell
.local/product-web-venv/Scripts/python.exe -m coordinator --db .local/orchestrator/state.sqlite migrate --backup .local/orchestrator/pre-v7-archive.sqlite
```

Migration checks the application ID, schema, WAL mode, integrity, foreign keys,
archive flag and primary-path binding. It creates and verifies a consistent
archive before transactional DDL. An existing backup file refuses without
replacement. A source commit during capture causes refusal; DDL errors roll back
the schema and retain the backup. Copied/moved stores and archives cannot migrate
into new authority. A successful migration preserves existing project state and
holds. A repeat command on the current schema refuses; inspect the schema/result rather
than assuming a failed acknowledgement means migration did not commit.

The pre-migration archive retains its original schema, marked mutation-disabled. Current
`Store` refuses to open that old schema; read-only SQLite inspection was tested.
Migration tests establish these measured Windows/patched-SQLite cases, not
power-loss durability or a complete self-hosted restore qualification.

## Archive restore

`backup` checkpoints the new archive and returns the SHA-256 of that file.
Restore is a separate command from migration:

```powershell
.local/product-web-venv/Scripts/python.exe -m coordinator restore ARCHIVE DESTINATION --digest SHA256
```

The command checks that digest, then the application id, current schema, WAL
mode, archive flag, integrity, and foreign keys. It writes those same bytes to
a new path and rebinds `primary_path` only on that new primary. The archive
stays `archive=1`. A copied store keeps the path recorded in its own file and
remains a non-writer. A digest mismatch, a change between the two reads, or a
failed check deletes any partial destination. Do not flip `meta` by hand.
Current-schema archives only: an older migration archive still needs the
explicit migration of its primary, not a restore into the current schema.
This command does not qualify host power-loss durability.

## Evidence

[The original intake evidence](implementation/product-intake-evidence.json) records **53
passing product tests**, zero skips, plus a real product/Git/artifact smoke and
CLI migration. Fifteen new tests cover exact packets, actor/source substitution,
competing admissions, authority changes during slow preflight, process exits
before/after the ref write, missing/ref-changed effects, pause and revision,
backup drift and DDL rollback. No source command, provider call or VM action runs.
The [verification cohort](implementation/product-verification-evidence.json)
retains 70 product tests and migration from v1/v2 to schema 3. The
[current integration cohort](implementation/product-integration-evidence.json)
retains 87 tests and migration from v1/v2/v3 to schema 4. The older failed
research full suite and open browser QA remain separate.
