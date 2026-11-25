# Trusted candidate intake foundation

`coordinator/source.py` now constructs real Git blobs, trees and single-parent
candidate commits in a **new, coordinator-owned bare repository**.
`coordinator/evidence.py` stores bounded artifacts by SHA-256 with verified
readback and atomic publication that never replaces an existing artifact.
These are internal building blocks for P2, not an acceptance command or a live
executor adapter. [Durable intake](product-intake.md) now connects them to the
product's approved attempts and immutable review packets. The CLI/web service do
not expose trusted source-controller mutation commands; authenticated status can
inspect their records.

[Integration staging](product-integration.md) adds private intent/proposal refs,
clean merge construction and a validation-only CAS primitive. Its product
regression gate binds the exact staged subject. A private milestone ref CAS can
record one scripted promotion; `live_eligible` stays false.

## Current contract

`Snapshot` accepts a map of literal paths to immutable `SourceFile(data, mode)`
values. The trusted intake controller must obtain these bytes after independently
proving source/runtime quiescence. Candidate code and archive metadata never
select a host path to read. No agent repository/config, hook, filter, network,
checkout, source test or candidate command runs in this module.

Paths must be NFC, relative and portable across the initial Windows/Linux
deployment profiles. Intake refuses Git metadata names, traversal, Windows
devices/streams, special files, case aliases and file/directory conflicts.
Only regular-file modes 100644/100755 are supported. The safety limits are 2,000
files, 8 MiB per file, 32 MiB per snapshot and 128 path components. Existing Git
content is validated on read as well. Symlinks, submodules, unusual nonportable
names and larger inputs require an explicitly extended intake policy; they are
not silently converted or dropped.

`TrustedRepository.create()` refuses an existing destination. It creates its own
local SHA-1 object repository and empty hooks directory. It does not import or
clone an existing Git database, fetch source or change this project's Git refs.
The managed metadata and evidence root must be protected from executor/reviewer
access by the qualified deployment; the library cannot protect them from another
process with the same owner's filesystem access. Current storage uses SHA-1 Git
OIDs plus SHA-256 source/artifact manifests; SHA-256 Git repositories are not yet
implemented or qualified by this increment.

`baseline()` records a source snapshot under a private baseline ref. `seal()`
compares the candidate with its exact input commit, rejects any changed path
outside the explicit literal allowlist, and binds plan/task digests, attempt and
authority generation into the candidate commit message. Only one candidate can
occupy an attempt's private ref. Changed content or bindings require a new
attempt. Identical re-delivery reconciles that same direct ref; a conflicting or
symbolic ref holds. Creating a candidate does not update any milestone ref,
write a task acceptance or release a dependent task.

Git receives a controlled environment, explicit managed directory and fixed
intake attribution/date for deterministic reconstruction. It ignores external
configuration and replacement refs; repository config drift, alternates, shallow
history or nonempty hooks directory refuse before an operation. Source bytes go
through `hash-object --no-filters`; `.gitattributes` is source data. Git commit
timestamps are **not event times**: the eventual coordinator ledger owns observed
timestamps and authority. A timeout or uncertain Git result is a hold to inspect,
not proof that no object/ref was written.

## Measured and remaining work

Twelve focused tests use actual scratch Git repositories and artifact files.
They cover path/type/scope refusal, exact binary/CRLF bytes, modes, controlled
environment, changed config/alternates, private-ref collisions, changed candidate
bindings and immutable input. One real child process exits 29 after its private
ref update; reopening reconciles one existing candidate without replacement.
This is process-crash evidence, not a host-power-loss durability claim.

P2 now has durable candidate-operation admission and frozen review packets in
the versioned product store, with a trusted local controller identity and read-only
ref reconciliation. [Check/reviewer records](product-verification.md) now enforce
exact bindings and applicability for scripted development evidence. Scripted
promotion and acceptance reconciliation are measured. It still needs
authenticated remote producer integration before live use. Real candidate
execution waits for qualified isolation; native stop/intake proof is not supplied
by a Python snapshot object. Independent reviewer quality and actual source
acceptance remain unmeasured. No generic “accept task” endpoint should bypass
these requirements.

## Primary-source references

The Git operations follow the upstream documentation for
[`hash-object`](https://git-scm.com/docs/git-hash-object),
[`mktree`](https://git-scm.com/docs/git-mktree),
[`commit-tree`](https://git-scm.com/docs/git-commit-tree) and
[`update-ref`](https://git-scm.com/docs/git-update-ref).
Source review establishes command semantics; the retained tests establish only
the behaviors exercised on the recorded installed Git version. The complete
contract remains [revision-bound verification](../research/verification-integration.md)
and [P2's delivery acceptance](product-delivery-plan.md).
