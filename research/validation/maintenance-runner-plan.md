# Maintenance admission and unarmed host preview

The [maintenance procedure](maintenance-procedure.md) now has a fixture-only
admission core and unarmed review packets for both VM roles. These are preparation
artifacts. No native transport, guest preparation program or apply CLI exists;
no VM, package or service was changed in this checkpoint.

## Prepared artifacts

[maintenance_runner.py](maintenance_runner.py) checks the existing frozen
procedure, original 480-package status, configuration profile and data ISO. Its
CLI previews by default. `--role guard --prepare NEW_DIRECTORY` creates a packet,
source snapshot and preview without creating a journal or dispatch marker.

| Role | Local directory | Missing bindings | Canonical packet SHA-256 |
| --- | --- | --- | --- |
| Guard | `.local/validation/maintenance-control-guard-01` | 27 | `378b8ea8d31c048e9fd70e6918d170339f7b28daf33075e9a1b8c43b20597c68` |
| Executor | `.local/validation/maintenance-control-executor-01` | 26 | `99ba25ac4fb4de0f2d484ee2e5a38e8e7783f50e6a88070fc4fa3cd029f411c4` |

Both packets refuse with `maintenance packet remains unbound`. Empty fields
include scoped approval references, independently verified backup and source
preservation receipts, actual boot/root/media identities, guest preflight program
hash, supervisor owner and original deadlines. Guard disk identity is also empty.
Preparation approval supplies none of these execution permissions.

The packet SHA above hashes the parsed object's canonical JSON, as used by
admission. It differs from the hash of the formatted `packet.json` file. Both
identities, source snapshots and preview hashes are recorded in the
[evidence](maintenance-runner-evidence.json). Hashes bind bytes; they do not
authenticate approvals or establish that observations are true.

## Admission and handoff contract

The API requires an existing durable Store and armed outside-VM lease, plus a
trusted live-supervisor probe. It cannot arm or renew a lease. Admission requires
the exact role, VM/resources/storage, eight disabled NICs, no shared folders,
Linux guest root with matching DMI/root/boot identities, loopback only, unchanged
baseline and clean package audit. It also checks the approved optical identity,
read-only `iso9660` mount with `nosuid,nodev,noexec`, complete 142-file verification,
APT dump, free space, policy-rc.d, persistent masks and helper state, and absence
of package/snap/protected-runtime activity or Docker socket authority.

Original wall and monotonic authority is at most 600 seconds. Admission needs at
least 250 seconds remaining and observations/live-owner evidence at most five
seconds old. The ticket expires with that evidence or the remaining-budget
boundary, whichever comes first. Lock wait and file/SQLite commit time count;
invocation cannot refresh the ticket.

Before returning a ticket, admission exclusively creates and fsyncs
`dispatch.intent.json`, then commits `possible-send` intent in SQLite. The
separate marker remains after an interrupted transaction or deleted database
rows. Concurrent admissions, reused nonces and unresolved mutations hold. The
marker is never automatically removed. This tests conservative process-level
recovery; physical power-loss durability and hostile filesystem interference
have not been qualified.

`invoke(ticket, sender)` accepts an injected callback, with no native adapter
provided. It rechecks durable intent, exact arguments, authority, supervisor and
ticket freshness, then commits `transport-entered` before calling the sender.
A lost acknowledgement fences authority and never retries. Even a returned
acknowledgement leaves the mutation uncertain. A future adapter must bound the
callback's runtime and output independently; this Python API cannot interrupt
an arbitrary blocked callback.

`record_result` requires the exact complete installed version map (496 executor
or 489 guard rows), clean audit/configuration state, surviving controls and a
separate stop receipt for the bound VM/storage. Unit completion must be within
original authority; stop must satisfy the proposed ten-second bound. Accepted
reports fence further authority and are labelled
`postconditions-and-stop-reported`, with native qualification still required.
A zero unit exit or transport acknowledgement alone cannot satisfy this gate.

## Proposed guest command: source evidence only

The generated argument vector uses `systemd-run --wait`, `Type=exec`, root,
`RuntimeMaxSec=210s`, `TimeoutStopSec=10s`, control-group termination and no
restart. It sets literal argument handling and no password interaction. These
options are documented by Ubuntu's systemd 255.4 manual; they have not been
executed on the selected VM. See [systemd-run(1)](https://manpages.ubuntu.com/manpages/noble/man1/systemd-run.1.html).

Standard input is null; stdout appends to a root-owned private log and stderr
inherits it. The proposed environment removes the reviewed conflicting dpkg/ucf
variables and sets the frozen maintenance values. Ubuntu documents these service
properties in [systemd.exec(5)](https://manpages.ubuntu.com/manpages/noble/man5/systemd.exec.5.html).
The command ends with the role's exact pinned APT install vector. There is no
generic upgrade, removal permission or force-yes option. Service survival through
PID 1 reexec, console loss, timeout and shutdown still needs native measurement.

## Measured local checks and limits

Thirteen focused tests use synthetic observations, fake clocks and injected
callbacks with real file-backed SQLite, including a two-connection race. They
cover unbound packets, altered target/media/backup facts, stale observations,
lost supervisor ownership, immutable deadlines, durable handoff before callback,
lost acknowledgements, changed commands, marker survival, incomplete version
maps and missing/late stop evidence. These are fixture conformance checks, not
measurements of guest enforcement. Full regression results and retained log
identities are in the evidence file.

Trusted native observation collection, approval verification, bounded transport
and independent stop/reap remain absent. An admission refusal does not itself
stop a running VM; the external supervisor must enforce its original deadline
and fencing. No current VM state, source-VDI preservation or installed guest
package state was freshly measured here. Earlier evidence remains historical.
The data ISO and frozen proposal were not changed.

## Next check

Prepare the guest create-only controls/observation payload and bounded host
transport review, then bind them to the actual backup/target and independently
qualified supervisor. Creation, attachment, boot and installation each still
require their applicable explicit approvals. Disconnected guard creation and
the [phase-boundary choice](../../docs/decisions/0002-fixture-phase-output-boundary.md)
remain pending. Final M1-11 through M1-14 runtime evidence and product
implementation remain open.
