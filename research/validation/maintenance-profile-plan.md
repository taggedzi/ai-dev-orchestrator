# Stopped maintenance profile review

Status: **Applied under separate developer approval on November 22, 2026, and
independently reobserved.** Both targets remain powered off/disconnected. No boot,
guest command, package installation or network activation occurred.

[maintenance_profile.py](maintenance_profile.py) prepares only the settings needed
for the existing maintenance adapter. The default preview makes no native calls.
Applying requires an exact plan hash and separate configuration approval. It does
not boot a VM, enable a NIC, attach media, install packages or change host settings.

The source disks and configuration files now have verified, unattached byte-copy
backups. The guard's original NVRAM absence and the executor's existing firmware
file are recorded explicitly. Backup files preserve their original disk UUIDs;
they must never be registered or attached. Restoration is a separate manual,
stopped-VM action, not an automatic error path.

## Exact changes

| Target | Operations |
| --- | --- |
| `mcli1-guard-01`, `0eceb37e-f216-45ed-817c-7cf2fca3a32a` | Expand the existing SATA controller from one port to four. Enable UART 1 at `0x3F8`, IRQ 4, as a host-pipe server at `\\.\pipe\mcli1-maint-0eceb37e-f216-45ed-817c-7cf2fca3a32a`. |
| `mcli1-validation-01`, `74129e9c-5a65-44fa-9d35-79d458dc4704` | Disable x2APIC and re-enable ordinary APIC last, preserving the earlier diagnostic's intended profile. Enable the equivalent target-specific UART 1 server pipe. Its four SATA ports stay unchanged. |

Both targets must remain powered off with eight disabled NICs. CPU/RAM, base disk
identity/hash, firmware, disk-only boot and sharing controls remain bound.

## Admission, execution and failure

Before any change, the program rehashes the backup files, checks the exact current
configuration and full live disk hash, and obtains a fresh stopped/disconnected
native inventory. A retained per-role intent directory blocks replay even when
another output path is supplied. Each command has its own flushed intent and
suspended-process source/intent gate before resume. The installed VBoxManage
path/digest is fixed; arguments have no caller-selected commands or shell.

The existing four-second process primitive bounds output and reaps the command's
Windows job. The live disk is held under a read-sharing lock throughout the
setting changes. Before subsequent commands and at the end, fresh inventory and
hash checks must agree. Final admission uses the existing four-port/UART parser
and boot-policy fields; NVRAM must remain exactly as backed up. A nonzero result,
missing acknowledgement, drift or interrupted write retains partial state with
no completed report or automatic retry/restore.

These checks do not qualify native startup, inherited guest identity/accounts,
root-console ownership, ten-second stopping, installation or isolation. The
controller must still obtain separate boot/run authority after the startup path
and its external owner are concrete.

## Local checks

Ten synthetic mutation checks pass, using real scratch-file backups and injected
VM inventories/command results. They cover exact guard postconditions, approval
and scope refusal, changed/missing backups, running state, lost/nonzero command
results, intent tampering, drift, unexpected NVRAM creation and executor APIC
ordering. No selected VM setting was changed by these tests.

The frozen role plans are retained under
`.local/validation/maintenance-profile-review-01`. The developer approved the exact
guard plan `962e01aa8f264bbc8f86f60af6ae908bf1a3e8f2dc794a3fbb6bcae7e87fe542`
and executor plan `d2bf6cf5e5ccd05e065e9922b310c8114ca40fae5ae530ecce158e02d692458d`.
All three native commands exited zero with reaped command jobs. Separate read-only
queries confirmed four SATA ports, the fixed UART setting, x2APIC off/APIC on,
poweroff and all eight NICs disabled on both VMs. Full disk hashes and NVRAM state
remain unchanged; live configuration hashes changed as intended.

Current guard configuration hash is
`986cf055dec3732488666adfe7e8715965faac421c9dc9c651eecb411f5c4f7e`;
executor configuration hash is
`5dfe5bc297f585a934bb2090797c365fafcfbd4bb7cbe785c8916f1da7ccf4f2`.
The one-use role intents remain retained. Do not reapply this consumed plan.
[Evidence](maintenance-profile-evidence.json) binds native receipts, independent
observations and the final 368-pass/13-skip regression.
