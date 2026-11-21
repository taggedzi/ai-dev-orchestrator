# Proposed validation deployment

Status: prepared for review, not authorized to provision or run. Fixture and local harness construction were authorized in the November 20 conversation. That approval did not select a target, authorize installation, or approve an executor experiment.

## Target and trust boundary

Continue the existing [M1-06 profile](../execution-security-boundary.md#minimum-secure-proof-of-concept): a fresh dedicated disposable Linux VM, with an unprivileged container running the pinned Agent Server local runtime. Give it only metadata-free synthetic source, bounded scratch, read-only payloads, and an explicitly restricted path to the scripted broker. Keep planning, audit/ledger, Git writer, broker policy, fault proxy, supervisor and observer storage outside its control.

The proposed fresh target can be named `mcli1-validation-01`; its actual UUID is assigned only during authorized provisioning. The stopped `ai-dev-test` VM is an alternative for operator review, and is not assumed disposable. Its guest type label and NAT configuration are inventory observations in [the checkpoint](../../docs/status.md#refreshed-local-preflight), not a qualified isolation profile. Do not modify, replace, start or delete it as part of fixture preparation.

Guest OS/image selection remains open. Before provisioning, choose the exact distribution/release and patched image, verify upstream checksums and capture its digest, and review hypervisor/runtime compatibility. No OS image, container image or dependency has been downloaded for this preparation.

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

1. Select the disposable target and approve its concrete provisioning/dependency plan.
2. After its artifacts and effective controls are frozen, review the deployment packet and authorize the applicable #12/#13 preflights and later #11 cases.

Do not merge PR #25 with an automatic closure of #11 unless the unfinished measurements are explicitly preserved in tracking. The preparation work supplies assets and tested local mechanisms; it does not satisfy #11–#14 by itself.
