# Measured stopped file backups

[stopped_backup.py](stopped_backup.py) now creates exclusive, unattached byte-copy
backups of the two preparation VMs. It performs fixed read-only native inventory
queries and ordinary local file copies. It contains no VM start, mutation,
registration, attachment, mount or restore command. Default CLI is preview only.

## Explicit versioned binding

The new `mcli1-file-backup-binding-v2` records a unique backup identifier, original
disk UUID, physical byte length/hash, configuration hash and an explicit NVRAM
file/absence record. The copied VDI retains its original UUID and bytes. It is an
independent file, **not a second registered medium**; never attach/register it.
Restoration requires a separately reviewed stopped-VM action. Recovery bootability
and protection against physical loss of this host disk have not been measured.

The guard's NVRAM is `{"state":"absent"}`. Absence cannot carry an invented hash
or zero-byte file descriptor. The executor's NVRAM is a real 540,672-byte file,
SHA-256 `cdfcb7d4b7eb19f0a4d990481704fbd02f81272e6f32d0651ed4a726546ce521`.
Existing version-1 clone-style backup bindings keep their original semantics.
Boot/transfer schema and receipt checks explicitly opt into version 2; old packets
are not rewritten or armed.

## Capture and verification

Exact source bytes, raw stopped/disconnected machine/medium inventory and current
source code are frozen before capture. Source disk/configuration/NVRAM handles
stay open with Windows read-sharing only throughout copying and final checks.
Single-link regular files and unchanged file identities are required. Destination
files are exclusive, flushed and independently read back; the source is rehashed
again. Missing NVRAM is rechecked for unexpected appearance. Raw before/after
queries are retained before the complete receipt is published.

Microsoft's [CreateFileW reference](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)
documents sharing conflicts, non-inheritable default handles and reparse behavior.
Native scratch tests measured denied write, replacement and deletion while the
read handle remained open. This is not a hostile-host path-race, kernel-stall or
physical power-loss guarantee. Host ACLs and deployment qualification remain open.

Failed/partial capture preserves its new output directory and intent; it neither
publishes a completed receipt nor reuses the directory. The 120-second copy loop
budget and byte bounds do not establish a hard bound on filesystem/kernel stalls.
No source cleanup or automatic restoration is supplied.

## Measured artifacts

| Role | Local backup | Receipt SHA-256 |
| --- | --- | --- |
| Guard | `.local/validation/stopped-backup-guard-01` | `c16629a52d55229edd3f66c2afb3c99af231451379ae26814668421837e4715f` |
| Executor | `.local/validation/stopped-backup-executor-01` | `c727a10b2fcc3cc4d83be32943b46f28895a8005dd5da4ccf4381a1d0eceb44a` |

Each VDI is 2,625,634,304 bytes. Their hashes remain, respectively,
`a8a6024499644999738f089546096e93174a336c003f2d1ae841214c2fe22c43` and
`2eb1d9cd009ecfe83381d855137f5cee8c1317739f6209beddd6da8a10955a09`.
A separate process rehashed every backup and every original after capture released
its handles. All matched, including explicit guard NVRAM absence.

Eleven new tests pass: actual scratch copies/readback and Windows share locks,
with injected VM inventory. Negative cases include drift, partial copies,
unexpected firmware creation, hard links, aliasing and format changes. The native
captures are separate evidence from those synthetic VM facts. See
[stopped-backup-evidence.json](stopped-backup-evidence.json).

The later approved [stopped profile changes](maintenance-profile-plan.md) changed
the live configuration files intentionally. These backups retain the earlier
configuration, not a claim that the current files still match those old hashes.
Guest disks and NVRAM remain unchanged. A boot adapter must freshly verify these
backup files and the separately approved current target profile before starting.
