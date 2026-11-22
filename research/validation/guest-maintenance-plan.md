# Guest inspection and control-change preparation

The [maintenance admission checkpoint](maintenance-runner-plan.md) now has a
standalone **read-only guest inspection program**, an exact control-change
planner and two unarmed inspection packets. No selected VM was started or
changed. The control-change planner describes operations; it has no execution
backend. This is fixture preparation, not product implementation or installation
authority.

## Prepared payloads

[maintenance_guest.py](maintenance_guest.py) verifies the existing frozen
maintenance inputs and prepares a new directory. Each directory contains only
`guest_maintenance_probe.py`, `spec.json` and `review.json`. Both specs retain
empty nonce, DMI/root/boot identity and boot/observation approval references.
Both refuse with `inspection nonce is unbound` before guest queries.

| Role | Local directory | Raw `spec.json` SHA-256 |
| --- | --- | --- |
| Guard | `.local/validation/guest-maintenance-guard-02` | `0fee827502e4b943c5c46853fa13438f2e4a089e221bf723128b77e33bd54aff` |
| Executor | `.local/validation/guest-maintenance-executor-02` | `c628e7fd3484ae15d522d046bc2c9254a2d4449c52c6529b4264467b10cee3dd` |

Unlike the earlier admission packet's canonical-object digest, these spec
digests bind **raw file bytes**. The standalone program is 21,641 bytes, SHA-256
`9d64f2fdc9f2c0f27d6c7f94ca7d54064717d70c937ad682e8ac888270b2c16b`.
The [evidence](guest-maintenance-evidence.json) records all file identities.
Neither frozen admission packet, the procedure nor the existing ISO was changed.

The host builder previews by default; this command performs no guest query:

```powershell
python -B -m research.validation.maintenance_guest
```

The standalone program also previews by default. Its separately reviewed future
observation entry point is `python3 -B guest_maintenance_probe.py --observe SPEC
--spec-sha256 RAW_DIGEST`, after real identity and approval binding. Hashes detect
changed data, not forged approval references or fabricated native observations.
Preparation permission does not authorize that guest invocation or its transfer.

## What the inspection collects

The program refuses Windows, non-root and WSL targets before native inspection.
It then requires PID 1 systemd, exact DMI/root/boot identities, ext4 root,
loopback only and the original 480-package status hash. Queries collect each
reviewed unit's loaded identity, aliases, active/substate, enablement, fragment
and drop-ins, plus administrator-mask and deb-systemd-helper masked-state
metadata. It also retains policy-rc.d metadata, private-path presence, raw dpkg
configuration text with hashes, empty package audit and recognized package/runtime
processes, plus the actual `_apt` account identity. Changed package status during
inspection holds.

The report is labelled `observed-not-admitted`. It contains a **guest** monotonic
timestamp, which must never be inserted into the host admission frame as a host
timestamp. It deliberately does not provide the full admission observation:
mounted media/member checks, free-space accounting, APT refresh/replay and final
protected socket/group checks remain required.

Native commands are full-vector allowlisted: one explicit-column root findmnt
query, fixed systemctl show properties for validated unit names, and dpkg audit.
No shell is used. Linux pipe reading has a shared proposed 60-second query
deadline, five-second command deadline, 2 MiB output/report ceiling and a bounded
kill/reap path. Cleanup can consume an additional second. Filesystem reads on a
stalled kernel are not a hard wall-clock boundary; the independent host worker
and VM lease remain necessary.

The systemctl manual recommends `show` for machine-readable properties and
describes persistent masks and their limits. See Ubuntu's
[systemctl(1), systemd 255.4](https://manpages.ubuntu.com/manpages/noble/man1/systemctl.1.html).
An administrator symlink alone does not establish the manager's effective loaded
state; existing masks must also report `LoadState=masked` and fragment `/dev/null`.
Upstream's [findmnt manual](https://man7.org/linux/man-pages/man8/findmnt.8.html)
advises explicit output columns rather than relying on its changing default
format. These are documentation observations, separate from native results below.

## What the control-change planner proposes

`control_plan(spec, observation)` refuses changed identity/nonce/baseline, package
or runtime activity, helper mask-state files, conflicting policy/admin files,
unreviewed aliases/drop-ins, failed/transitional units and any pre-existing
private maintenance paths. It preserves an existing matching policy or effective
root-owned administrator mask. Dpkg configuration bytes remain an explicit
review requirement; the planner does not declare them safe.

For a conforming observation it proposes exclusive policy/mask creation, daemon
reload, stopping active timers then sockets then services, and fresh root-owned
private directories/configuration files using the byte-pinned APT preview.
APT list/cache parents are root-owned mode 0755, with mode 0700 `partial`
directories owned by the measured non-root `_apt` account. Configuration and
log directories remain root-only. Root/ordinary-login identities for `_apt`
hold. Actual sandbox access and absence of root fallback still need measurement;
APT itself may adjust staging ownership. Debian's
[APT 3.0.3 acquisition source](https://sources.debian.org/src/apt/3.0.3/apt-pkg/acquire.cc)
shows its partial-directory ownership/mode setup; that source observation is not
qualification of the pinned guest APT build.
Masks precede stops to reduce reactivation races. This ordering has synthetic
conformance evidence only. It does not establish complete service quiescence,
survival across package scripts, or an atomic guest transaction. A future executor
must retain prior/partial state, refuse overwrites, verify the effective outcome
and hold on failure without automatic repair or replay.

## Measured checks

Sixteen focused tests cover identity/WSL refusal, spec/source binding, command and
path injection refusal, ambiguous/duplicate native output, status changes,
existing control conflicts and mask-before-stop ordering. On Linux they also
exercise real pipes with synthetic sleeping/flooding children and confirm
timeout/output rejection and child reaping. Windows skips that POSIX-only case.

On the local **WSL tool host**, four fixed native queries succeeded: root mount,
an existing unit, an absent unit and dpkg audit. The absent unit returned explicit
`not-found`/`inactive` properties with empty fragment/drop-ins. Tool-host versions
are util-linux `2.37.2-4ubuntu3.6`, systemd `249.11-0ubuntu3.23` and dpkg
`1.21.1ubuntu2.6`; these are not the selected guest's versions. All 15 focused
tests initially passed on that host, including the Linux cleanup case. The final
16-test run also passed after the staging-permission correction. Its actual dpkg
status SHA-256 stayed
`82f7835e29b4c8d3aab46e79e5d4719a53e03c9841f3aaa7eb02755740064501`
across each check. This new tool-host observation does not replace earlier
captures or the guest's frozen baseline. Logs, all three Linux test attempts and full
Windows regression results are bound in the evidence file.

The initial role packets remain intact with their earlier 20,591-byte source.
Revision 02 adds `_apt` identity/ownership planning; no earlier artifact was
overwritten. Windows regression ran 185 tests: 183 passed and two platform cases
were skipped. The POSIX case passed in the separate Linux run.

No native full guest inspection, control changes, media mount, package install,
VM stop or source-VDI preservation measurement ran. Process comm-name inspection
is diagnostic; it is not a proof that unknown actors cannot mutate package state.
The program assumes trusted root collectors and does not qualify resistance to
a hostile guest root or filesystem races.

## Next check

Prepare the bounded serial worker and create-only control executor against these
exact payloads, with conservative delivery uncertainty and independent stop
enforcement. Then obtain the applicable target/backup, transfer, boot and control
change approvals before native guest observations. Disconnected guard creation
and the phase-boundary choice remain pending; neither is settled by this stage.
Actual installation, repeated readiness, hardening and M1-11 through M1-14 remain
open.
