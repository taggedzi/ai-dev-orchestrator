# Offline first-boot verification

Prepared November 21, 2026 after the developer requested continuation from commit `7b4e2ad`. The target is only `mcli1-validation-01`, UUID `74129e9c-5a65-44fa-9d35-79d458dc4704`, with VDI `e832fc9c-23cc-40a8-8e66-fa0c624b8bd9`. This is image preparation, not an executor experiment or architecture adoption.

## Scope and checks

Before boot, compare the powered-off installed VDI to the recorded installation SHA-256. Require the expected single HDD, two vCPUs, 4096 MiB, no shared folders, and eight disabled NICs. Detach any populated DVD drives and select disk-only boot. The current DVD drive is already empty. Do not format, reinstall, install dependencies or enable networking.

Temporarily connect UART 1 to a uniquely named Windows named pipe. Log in using only the new VM's `fixture` credential from ignored local preparation storage. The probe runs as that user, with no sudo, SSH or Guest Additions. Transfer the small, versioned `boot_receipt.py` source in bounded chunks into a temporary guest file; load and remove that file before execution. The serial log is retained only after redacting the complete disposable credential across capture boundaries.

Record the running kernel, Ubuntu release, architecture, Python version, account UID, boot ID, root mount, interfaces, package audit/inventory, cloud-init completion and SSH-server package status. Require the installed kernel, UID 1000, an ext4 root, only loopback, unchanged package inventory, completed cloud-init and no SSH server. Fail checks for a live-installer root, unexpected kernel/account, enabled networking, or missing/ambiguous receipt.

Request ACPI shutdown after collecting the receipt, confirm poweroff, then disable the temporary UART. Retain a new stopped-image SHA-256 because first boot normally changes the disk. Use a ten-minute monotonic deadline for the check and at most sixty seconds for orderly shutdown. On failure, stop this target and retain a hold rather than restarting or reformatting it. These preparation deadlines are not qualification of a supervisor that survives a host-process failure.

The bootstrap credential remains in ignored local storage for later preparation. Removing or replacing that account and cleaning installation/credential artifacts remain image-hardening work before untrusted agents run. This stage does not test containment or model/executor behavior.

## Implementation and verification

Two two-vCPU attempts stalled before the login prompt (150-second and 360-second waits). Both ended with journaled poweroff and a terminated VBoxHeadless process. The second display capture froze at initramfs driver loading. The host log confirms NEM fallback because direct VT-x was unavailable. This is an observed boot stall, not just missing serial authentication.

A separately reviewed diagnostic trial changes only this VM from two vCPUs to one. RAM, graphics, disk, kernel and all disabled NICs stay unchanged. [VirtualBox issue #799](https://github.com/VirtualBox/virtualbox/issues/799) reports NEM/Hyper-V CPU-count boot hangs, including a Linux driver-loading stall; [issue #861](https://github.com/VirtualBox/virtualbox/issues/861) describes Linux boot/RCU stalls with the same kernel family. These reports motivate a test, not a confirmed diagnosis of this host. Do not disable host Hyper-V, change Windows security settings or downgrade software as part of this trial.

Each continuation requires its prior stopped-disk hash, matching sanitized capture, original installation reference and intact audit chain. The CPU diagnostic additionally binds the prior checkpoint and explicitly requires `--single-cpu-diagnostic`. The first one-CPU trial reached the login shell and transferred the probe after one separately approved pause/resume pair. Its host parser then mistook a partial serial read for a complete receipt. The correction requires a newline-terminated frame; a regression test checks every truncation inside a receipt. One additional protocol-correction retry requires the completed login/transfer audit phase and the prior two-checkpoint chain. These are bounded reviewed continuations, not an automatic restart loop. A one-CPU success establishes only that observed preparation profile, leaving the proposed two-CPU runtime profile unqualified.

The pause/resume workaround is an intervention, not evidence of unattended boot reliability. Record any use with the result. An invocation against `first-boot-04` failed during preflight because reconciliation hashing was still in progress; it did not start the VM. The corrected invocation uses a fresh `first-boot-04b` output directory.

`first_boot.py` uses the existing native command journal and installed-image guards. The original cleanup path could fence authority and then inadvertently block its own poweroff through the ordinary mutation gate. Emergency stop now uses a target-specific, independently logged path, including when a prior start acknowledgement is uncertain. A regression test covers that case without starting a real VM.

The console uses [VirtualBox's documented serial pipe mode](https://docs.oracle.com/en/virtualization/virtualbox/7.2/user/vboxmanage.html) and Windows [`PeekNamedPipe`](https://learn.microsoft.com/en-us/windows/win32/api/namedpipeapi/nf-namedpipeapi-peeknamedpipe) to read available bytes without an unbounded console read. The named pipe is a temporary preparation channel, not a network/control boundary qualified for executor work. Source documentation was reviewed November 21; measured outcomes are retained separately from these documentation observations.

The default command is a plan-only preview:

```powershell
python -m research.validation.first_boot
```

The scoped execution command is:

```powershell
python -m research.validation.first_boot --apply --approval "<approval reference>" --output .local/validation/first-boot-01
```

The output directory must be new. Failed runs retain their journal and sanitized console capture. A boot failure or image-hash mismatch requires reconciliation before any subsequent attempt. Existing installation evidence refers to its execution-time sources in commit `7b4e2ad`; the later emergency-stop repair does not rewrite that history.

## Startup follow-up before dependency preparation

Measured outcomes are summarized in [first-boot-evidence.json](first-boot-evidence.json). Local raw evidence remains under ignored `.local/validation/` directories; the tracked summary contains their hashes, not the disposable password or full logs.

| Attempt | Profile and intervention | Observed outcome |
| --- | --- | --- |
| `first-boot-01` | Two CPUs; no intervention | No login within 150 seconds; emergency stop confirmed. |
| `first-boot-02` | Two CPUs; no intervention | No login within 360 seconds; display stalled at initramfs driver loading; emergency stop confirmed. |
| `first-boot-03` | One CPU; one pause/resume pair | Login and probe transfer succeeded; host parser consumed an incomplete receipt; emergency stop confirmed. Exact pause command output was not retained, so intervention success is inferred from subsequent state/progress. |
| `first-boot-04` | Preflight only | Reconciliation file was not yet available; no start intent or VM mutation occurred. |
| `first-boot-04b` | One CPU; one pause/resume pair, both command exits recorded as zero | Complete token-bound receipt; nine of ten predicates passed. ACPI request exited zero, but poweroff was not observed within 60 seconds. Emergency stop and VBoxHeadless termination confirmed. |

The final receipt reports Ubuntu 24.04.5, kernel `6.8.0-139-generic`, Python 3.12.3, UID 1000, ext4 disk root, only loopback, 480 unchanged package rows, a clean `dpkg --audit`, no installed SSH server and cgroup v2 availability. It is a guest-reported observation, not independent containment evidence. The cloud-init predicate failed because its status was `disabled`, with `disabled-by-marker-file`, exit zero and no reported errors. [Cloud-init's versioned status documentation](https://docs.cloud-init.io/en/24.2/howto/status.html) associates that code with `/etc/cloud/cloud-init.disabled`; the marker's origin has not been inspected. Disabled status is not proof of a failed initialization. Do not change the acceptance rule after a run merely to turn it green.

The final run's receipt was recovered from its sanitized serial capture after the shutdown failure, validated against its journal token and retained separately. The later harness revision now persists the parsed receipt/verdict before requesting ACPI shutdown. The evidence distinguishes the execution-time source snapshot from this later source revision. No successful overall boot/shutdown result was written for the failed trial.

After confirming poweroff, preparation restored two CPUs and disabled/disconnected UART 1. All NICs remain off. The stopped VDI hash is `0eda722dc1150b9f21f3ad3db0616c9def7ad4f6a5c1a020362527b460ef275e`. This hash follows several interrupted boots and does not describe a cleanly shut-down qualified image. The bootstrap credential remains local for later hardening. This preparation does not qualify the external supervisor's ten-second stop guarantee.

The next research check is a repeatable unattended start and ACPI shutdown on a frozen VM profile. Preserve this installed disk and the failed-run evidence. A shell reached after an intervention is useful diagnosis but does not satisfy that check. Do not add toolchain dependencies or run executor cases on this unresolved baseline.

Review a minimal reproduction against the upstream NEM reports using this exact hypervisor, kernel, firmware and host backend. Also inspect the cloud-init disable marker and power-button handling before revising their readiness checks. Bind any proposed diagnostic to a stopped-image hash, name the single changed variable and retain both success and failure controls. A successful profile then needs repeated cold starts without pause/resume, a full token-bound receipt and orderly shutdown before runtime-hardening preparation continues. No repeat count or compatibility conclusion has been qualified by these trials.

Keep host Hyper-V, WSL and Windows security settings unchanged. A new VM profile, replacement backend, tool installation or host-level change needs a concrete separately reviewed plan. No upstream issue or repository data has been submitted externally by this work.
