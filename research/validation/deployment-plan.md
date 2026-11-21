# Proposed validation deployment

Status: the first provisioning stage was authorized through the command approval and completed on November 21. `mcli1-validation-01` is powered off with the verified installer attached. OS installation, dependency preparation and executor experiments remain unapproved. The original fixture-construction authorization did not cover these later stages.

## Target and trust boundary

Continue the existing [M1-06 profile](../execution-security-boundary.md#minimum-secure-proof-of-concept): a fresh dedicated disposable Linux VM, with an unprivileged container running the pinned Agent Server local runtime. Give it only metadata-free synthetic source, bounded scratch, read-only payloads, and an explicitly restricted path to the scripted broker. Keep planning, audit/ledger, Git writer, broker policy, fault proxy, supervisor and observer storage outside its control.

The new target is `mcli1-validation-01`, UUID `74129e9c-5a65-44fa-9d35-79d458dc4704`. The existing `ai-dev-test` VM was not selected or modified. Its guest type label and NAT configuration remain inventory observations in [the checkpoint](../../docs/status.md#refreshed-local-preflight), not a qualified isolation profile.

The selected installer is Ubuntu Server 24.04.5 AMD64, `ubuntu-24.04.5-live-server-amd64.iso`, SHA-256 `97f3d7ffb032c3eb3b23d2c8be9cc76e60c2c1f2c0146ba5ba9fe01cafae0fd8`. Its 4,080,486,400 downloaded bytes matched [Canonical's published checksum](https://releases.ubuntu.com/24.04/SHA256SUMS), reviewed November 21. The directory heading inconsistently names 26.10; selection binds the actual filename/digest. Local detection emitted Ubuntu Server 24.04.5 metadata but exited 1 with `E_NOTIMPL` from `DetectIsoOS()`, so its `IsInstallSupported=on` field is not a successful unattended-install qualification. Resolve that failure or use a separately reviewed installation method. Ubuntu lists standard support for 24.04 LTS through May 2029 in its [maintenance schedule](https://ubuntu.com/security/esm).

The first provisioning stage is now concrete in [provisioning-plan.json](provisioning-plan.json) and [New-ValidationVm.ps1](New-ValidationVm.ps1). It creates only a new, powered-off VM with the checksum-verified installer attached: 2 vCPUs, 4096 MiB RAM, a dynamically allocated 32 GiB installation disk, and all eight NICs disabled. Clipboard transfers, drag-and-drop, USB, audio and remote display are disabled. The 32 GiB disk is for image preparation; it does not implement the later 8 GiB runtime-write limit. OS installation, dependency retrieval, image hardening, networking and experiments remain subsequent stages. No existing VM is reused or modified.

The script defaults to a plan-only JSON preview. An apply invocation requires `-Apply -ApprovalReference <decision>`, and downloading the roughly 3.8 GiB ISO additionally requires `-DownloadIso`. It confines output paths to this workspace, rejects existing VM identities/directories and path reparse points, checks the installed hypervisor version and ISO hash, and records the powered-off configuration. No automatic cleanup or overwrite follows a partial failure. Review the retained state before taking another action.

The PowerShell parser, plan-only invocation and approved apply command succeeded. The initial host script-policy denial was handled through an approved process-local execution-policy override, without changing system policy. The apply stage passed its 40 GiB free-space check, verified the installer hash, created the VM and recorded its configuration in `.local/validation/vms/mcli1-validation-01/provisioning-receipt.json`. A separate receipt check confirmed poweroff, two CPUs, 4096 MiB and eight disabled NICs. Installer automation compatibility remains unqualified.

Read-only inventory found VirtualBox `7.2.22r175245`, an existing host-only adapter at `192.168.56.1/24` with DHCP disabled, and an internal network named `intnet`. No network was created or reconfigured. Free-space enumeration returned no usable value in the sandbox; the apply stage's host-side check established at least 40 GiB before download/allocation. Host-only enumeration initially failed because VirtualBox tried to refresh its configuration; approved enumeration outside the sandbox succeeded.

This is a Windows-hosted candidate profile, which needs its own qualification under M1-06. [Oracle's networking documentation](https://docs.oracle.com/en/virtualization/virtualbox/7.2/user/networkingdetails.html) says NAT can reach host loopback, host-only connects the guest to the host, and internal networking excludes host applications. Neither ordinary NAT nor an unfiltered host-only adapter establishes the required boundary. Keep NICs disabled until an external enforcement point and management transport are separately reviewed and tested. The CLI settings follow [Oracle's 7.2 command reference](https://docs.oracle.com/en/virtualization/virtualbox/7.2/user/vboxmanage.html).

| Boundary | Concrete preparation requirement | Qualification before dependent cases |
| --- | --- | --- |
| VM/container | 2 guest vCPUs, 4 GiB RAM; non-root container capped at 1 CPU, 2 GiB, 128 tasks, no extra swap; bounded disks/inodes. Disable host shares, inherited volumes, clipboard, drag-and-drop, management access and unnecessary devices. | Record effective hypervisor, UID/GID, mount, namespace, capability, cgroup and storage settings. Measure resource ceilings and all #12 denial groups plus the allowed edit. |
| Network | One frozen literal broker destination; no forwarding to real models; no public egress, DNS leakage or alternate broker routes. Local preparation services bind loopback only. | Design the VM-to-broker path and host-side enforcement explicitly; a loopback service alone is not a guest network boundary. Record allowed exchange, forbidden listeners, positive controls and enforcement counters for IPv4/IPv6. |
| Authority and stop | Separate external supervisor with a persisted absolute lease of at most ten minutes, immediate fencing on pause/cancel, forced stop within ten seconds, no workspace reuse before stop/reap. | Validate host clock mapping, service survival across coordinator failure, VM start identity, stop/reap observation and late-writer challenge. Prepared lease code has not been qualified against VirtualBox. |
| Evidence | External marker and process/syscall observers, native HTTP/WebSocket capture, bounded diagnostics, sanitized canary scan and sealed source extraction from a stopped disk. | Establish independent positive controls, retained event pages and raw IDs, no tool-writable authoritative store, exact hashes and cleanup receipts. |
| Toolchain | Existing proposed GSD 1.21.0, OpenHands 1.62.0, LiteLLM 1.105.1, Node 22.16.0 and Git 2.51.0; Python 3.12+ with exact runtime to freeze. | Approve the installation/image preparation plan, pin artifacts and locks, record effective versions, verify startup and actual tool schemas, and collect a real GSD export. Workstation versions do not substitute for these pins. |

The full [M1-10 limits](../two-task-validation-fixture.md#proposed-numeric-thresholds) remain proposed, including storage, per-role token and simulated-money limits, scenario-specific correction budgets and retention. Approval of code preparation does not approve those numeric run limits.

## Review packet to complete

The bundle's manifest freezes source, checks, policy proposals, payloads, patches, Git objects and harness code. Save its printed SHA-256 externally. Generate a deployment template using `python -m research.validation profile BUNDLE` and store it outside the frozen bundle.

The remaining packet needs the target UUID and start identity, OS/kernel/hypervisor/runtime versions, image and binary hashes, network/mount/controller snapshots, actual raw GSD export and normalized comparison, deployed prompt/tool schema bytes, exact Chat request/response transcripts, observer topology and control results, and supervisor installation/stop recovery plan. Every required blank remains a blocker; placeholder hashes must not be treated as evidence.

No product architecture decision is made here. The experiment still evaluates the existing proposed ownership boundaries and can finish with a safe hold. An approved local-only result cannot establish provider billing finality, agent review quality, or production recovery.

## Next review

1. Prepare and approve offline OS installation, accounting for the failed unattended-detection command. Keep NICs disabled and record the installed OS/kernel and storage identity.
2. Review dependency/image preparation and the external network boundary before connecting or running executor code. Final deployment approval and #12/#13/#11 experiments follow their frozen inputs and effective-control evidence.

Do not merge PR #25 with an automatic closure of #11 unless the unfinished measurements are explicitly preserved in tracking. The preparation work supplies assets and tested local mechanisms; it does not satisfy #11–#14 by itself.
