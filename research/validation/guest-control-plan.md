# Guest control executor preparation

The [guest inspection/planning stage](guest-maintenance-plan.md) now has a
standalone executor for **maintenance controls only**, plus unarmed guard and
executor review packets. It creates reviewed policy/masks/private configuration,
reloads systemd and stops reviewed actors. It cannot install packages, remove
controls, restore partial state or reboot. No root apply or selected VM action
ran in this checkpoint. Product implementation remains gated.

## Prepared payloads and authority

| Role | Local directory | Raw request SHA-256 |
| --- | --- | --- |
| Guard | `.local/validation/guest-control-guard-01` | `05ccb998c529b719875a53e2126a719c083d96a76b94bdca4f3a624134ecf930` |
| Executor | `.local/validation/guest-control-executor-01` | `370df893707086fa7d538e1a749e257e5374472b9d1cfd9312409c629965ca96` |

Each directory contains exactly five files: request, inspection spec, review,
control source and unchanged inspection source. Both requests refuse with
`control approval is unbound`. No observation file was invented: actual reviewed
observation, regenerated plan, host-intent receipt, scoped approvals and guest
clock window remain unbound. These are review artifacts, not activation packets.

[maintenance_control.py](maintenance_control.py) defaults to a host preview;
`--prepare NEW_DIRECTORY` creates artifacts only. The 26,530-byte standalone
[guest_maintenance_control.py](guest_maintenance_control.py) is SHA-256
`29654753377e0100db2677c50a242565f1e98f01770e50ae6ee7fed5ddeb591e`.
It loads only the separately protected, fixed-digest inspection source
`9d64f2fdc9f2c0f27d6c7f94ca7d54064717d70c937ad682e8ac888270b2c16b`.
Full identities and receipts are in the [evidence](guest-control-evidence.json).

The standalone default also previews. A future separately authorized `--apply`
entry point requires a new protected packet under
`/run/mcli1-control-<nonce>`, an external raw request digest, actual observation
and all bound approvals/inputs. There is no alternate-root CLI. It rejects
Windows, non-root and WSL targets before mutation. Preparation permission grants
no permission to transfer or invoke that entry point in a guest. Hashes and
reference strings check consistency; the trusted controller must authenticate
actual authority and bind VM/disk/backup/root-session identities.

## Fresh admission and time bounds

The executor validates root-owned private packet storage, source/spec/input
hashes, nonce/role, dpkg-configuration review and a proposed **at most 60-second
guest window**. Both wall and guest-monotonic clocks must remain between the
original issue/expiry values. A controller must derive this window from the
original outside-VM authority; copying host monotonic timestamps into guest fields
is invalid. No VM lease is armed, extended or renewed here.

It runs the pinned read-only inspection again before creating control state.
Every stable field must match the reviewed observation; only the collector's
guest completion timestamp is excluded from that comparison. Changed unit
state, aliases/drop-ins, package/runtime activity, configuration or target holds.
The exact control plan is regenerated from those facts and must match its
external review digest. The fresh inspection must be no more than five seconds
old when admitted. This is source-enforced logic with synthetic gate checks;
native admission on either selected VM remains unmeasured.

## Exclusive operations and retained partial state

Filesystem operations walk directory file descriptors with `O_NOFOLLOW`, reject
unsafe owner/writable ancestors and noncanonical paths, and create leaves
exclusively. Files are checked for ownership, type and single-link identity;
bytes/modes are verified after creation. Administrator masks can link only to
`/dev/null`. Existing conflicting paths are never overwritten, renamed, removed
or repaired. Partial new files remain on failure.

Linux documents exclusive creation and directory-relative operations in
[open(2)](https://man7.org/linux/man-pages/man2/open.2.html). The code fsyncs new
files and parent directories: [fsync(2)](https://man7.org/linux/man-pages/man2/fsync.2.html)
distinguishes data flushing from directory-entry persistence. Those are source
expectations; this stage does not qualify physical-power-loss durability.

Before policy/mask/service changes, the executor exclusively creates the
persistent `/var/lib/mcli1-maintenance-control` directory. An existing directory,
even empty after a crash, refuses another attempt. It retains request/spec,
reviewed and fresh observations, exact plan, a lock and a hash-chained append-only
event journal. The lock uses nonblocking advisory
[flock(2)](https://man7.org/linux/man-pages/man2/flock.2.html). It coordinates this
executor; it is not an APT/dpkg lock or a boundary against other root actors.

Every action has a flushed intent before I/O and a reported result afterward.
Journal time counts against the original window. If logging fails after a
mutation, the earlier intent and permanent marker remain; later actions stop.
No automatic retry, rollback, cleanup or repair path exists. The host must retain
its own possible-send intent and independently stop/reconcile the VM on an
uncertain outcome.

The only mutating command vectors are daemon-reload and stopping names in the
reviewed mask set. Timers/sockets precede services, after persistent masks.
Commands use no shell, a proposed five-second limit, 64 KiB capture ceiling and
process-group kill/reap. Nonzero exits, warnings, timeout or excess output hold
after retaining available results. Killing a systemctl client does not cancel a
job already sent to PID 1. Ubuntu's
[systemctl manual, systemd 255.4](https://manpages.ubuntu.com/manpages/noble/man1/systemctl.1.html)
describes these operations; actual target stop/reload behavior is unqualified.

After all actions, another pinned inspection must show effective inactive masks,
unchanged helper-state constraints, exact policy, unchanged package/audit/runtime
and dpkg configuration, exact created file/directory metadata and the reviewed
APT staging account. A passing report still requires independent VM stop and
does not authorize installation. Media/member verification, free-space
accounting, live APT configuration/refresh/replay and final install admission
remain separate gates.

## Measured local evidence

All **18 focused checks passed on the WSL tool host**, Python 3.10.12, UID 1000.
Twelve cover request/time/fresh-state admission, intent/report ordering, interrupted
journals, command refusal and postconditions with synthetic data. Six use real
POSIX operations in temporary directories or synthetic child processes. They
measure exclusive file/mask behavior, symlink/unsafe-ancestor/path/hardlink refusal,
partial-write retention, persistent journal/replay refusal, command output/time
bounds and child reaping. They do not execute a root control workflow or real
systemctl command. Test fixtures are removed only by test cleanup; production
partial-state removal is not implemented.

The tool-host package-status SHA-256 stayed
`82f7835e29b4c8d3aab46e79e5d4719a53e03c9841f3aaa7eb02755740064501`
across that run. This is not the guest's frozen baseline or a new guest
measurement. Windows regression ran **221 tests: 213 passed, eight skipped**.
Six new skips are the POSIX cases passed separately above; the other two are
existing platform cases. Exact logs, source hashes and counts are retained.

No VM, root apply, real service command, package/tool installation, media mount,
provider call or upload ran. Descriptor checks assume trusted guest root and do
not establish protection against hostile root, bind mounts or namespace changes.
Kernel-stalled I/O is not a hard wall-clock guarantee. Independent original VM
authority, stop/reap and final-target qualification remain necessary. Frozen
probe, serial, admission, proposal and architecture inputs were not changed.

## Next check

Prepare the identity-gated serial command sequence that transfers and invokes
these exact inspection/control payloads, then bind it to original host authority,
revocation and independent stop observation. Actual guest transfer, boot and
control changes require their applicable explicit approvals. Disconnected guard
creation and the phase-boundary selection remain pending. Installation, repeated
readiness, final isolation/routing/recovery and feasibility are still open.
