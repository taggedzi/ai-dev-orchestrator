# Project status and restart point

Updated November 21, 2026. The active goal is to finish the project, including the vision's lifecycle requirements; the research checkpoint is not that completion. Fixture/harness preparation was committed as `2758406`, VM provisioning as `6adb6f4`, OS installation as `7b4e2ad`, and initial boot diagnostics as `af6cd7c`. The latest corrected two-CPU x2APIC-off trial completed one unattended boot and ACPI shutdown. The installer origin of cloud-init's disable marker is now verified. Repeatability, a prospective readiness policy and runtime qualification remain open. The VM is stopped; dependencies and executor experiments remain gated.

## Where we stopped

M1-01 through M1-10 research designs have been merged. They cover executor interfaces, planning, routing, ownership, isolation, recovery policy, verification, spending, and the [two-task validation fixture](../research/two-task-validation-fixture.md). These documents describe proposed behavior and source findings; they do not establish that an integrated system works.

The restart audit began on `research/m1-11-executor-recovery` at `56cdfe2e2169f742c61f618eccf0ce4b439e03d4`, with a clean working tree. Its [PR #25](https://github.com/taggedzi/ai-dev-orchestrator/pull/25) was open and unmerged at the November 20 check. It adds the [recovery preflight](../research/executor-cancellation-recovery.md) and a [Linux marker probe](../research/fixtures/executor-recovery-probe.py). Every executor runtime case remains Inconclusive. The later fixture commit is local; no push or merge was requested.

The developer [approved the M1-10 design](https://github.com/taggedzi/ai-dev-orchestrator/pull/24#issuecomment-6962022192) while explicitly keeping the recommendation Conditional until the fixture is frozen, approved, and executed. No later approval was found in PR #25 or the issue #11 discussion. On November 20, issues #11–#14 remained open with no comments.

| Work | Current evidence | Next check |
| --- | --- | --- |
| [#11 executor recovery](https://github.com/taggedzi/ai-dev-orchestrator/issues/11) | Source review, preflight, probe and procedures; no runtime measurements | Measure success, cancellation, lost acknowledgements and crash recovery after the applicable isolation and gateway gates pass. |
| [#12 target isolation](https://github.com/taggedzi/ai-dev-orchestrator/issues/12) | Four denial groups and an allowed edit are specified; target unqualified | Freeze the exact deployment, then collect direct probes, positive controls, stop and cleanup evidence. |
| [#13 gateway controls](https://github.com/taggedzi/ai-dev-orchestrator/issues/13) | Local scripted route and spending rules are specified; no verified endpoint | Measure allowed and forbidden routes, identifier joins, interrupted replies and retained unknown-spend holds. |
| [#14 feasibility decision](https://github.com/taggedzi/ai-dev-orchestrator/issues/14) | Depends on #11–#13 | Assess R1–R6 and the developer walkthrough, propose the architecture decision, and record developer approval before implementation planning. |

PR #25 currently includes `Closes #11`, although #11 requires measurements absent from that PR. Before merging, remove that automatic closing reference or explicitly preserve the unfinished measurement work in another tracking issue. No GitHub metadata was changed during this checkpoint.

## Refreshed local preflight

These are measured workstation inventory observations from November 20, separate from the November 17 preflight. No VM, container, executor or inference service was started.

| Read-only check | Observation | Limit |
| --- | --- | --- |
| `Get-Command` | VirtualBox, Docker, uv, Node and Python resolve. `agent-server` and `openhands` do not resolve on PATH. | Other environments and package installations were not searched. CLI presence does not qualify a runtime. |
| `wsl --list --verbose` | Six distributions are listed, all stopped, including `docker-desktop`. | The sandbox initially denied enumeration; the read-only check succeeded outside it. Distribution contents and runtime controls remain unverified. |
| `VBoxManage list vms` and `list runningvms` | Seven VMs are registered, including `ai-dev-test`; no running VMs were listed. | A registered name does not establish intended use or permission to modify it. |
| `VBoxManage showvminfo ai-dev-test --machinereadable` (selected fields) | Powered off; configured for 2 vCPUs and 4096 MiB; guest type label Ubuntu 24.10 (64-bit); NIC 1 NAT, other NICs disabled; clipboard and drag-and-drop disabled; VRDE off; USB on. | This is hypervisor configuration, not a guest OS measurement. Images, actual guest version, sharing, egress enforcement, container limits, observers and cleanup are unqualified. NAT alone does not demonstrate the required destination restrictions. |

The existing `ai-dev-test` VM is a candidate for operator review only. Do not infer that it is disposable. The existing proposal calls for a fresh dedicated Linux VM with an unprivileged container; any reuse or replacement needs an explicit target choice and an exact deployment freeze.

## Proposed next work: prepare the validation fixture

The developer authorized this preparation scope after reviewing the checkpoint. The [fixture and local harness](../research/validation/README.md) now provide reproducible synthetic inputs, independent graders, durable intents and simulated spending, local Chat/fault services, marker collection, and a prepared lease supervisor. The [deployment plan](../research/validation/deployment-plan.md) records the next target review. This remains experiment preparation, separate from implementing the product orchestrator.

| Preparation deliverable | Required content |
| --- | --- |
| Reproducible fixture inputs | M-CLI1 seed, two dependent tasks, raw GSD plans/export, exact Git objects, checks, gold patches, scripted replies, rubric and expected outcomes from M1-10. |
| Trusted experiment harness | Durable operation journal, bounded local Chat service with no forwarding, fault proxy, independent marker/process observers, stop supervisor and sealed evidence collection. Keep any simplified native-only probe claims narrower than coordinator recovery. |
| Target deployment plan | Named disposable target; exact image and tool digests; identities, mounts, network rules, resource limits, evidence retention, stop and cleanup controls. No changes to existing VMs without approval. |
| Frozen review packet | Hash-indexed inputs, scenario permissions, numeric limits, expected assertions and unresolved prerequisites. Obtain run approval only after the required pins and controls are concrete. |

Retain OpenHands SDK/Agent Server v1.62.0 at `504a88cab0fb48ee5226238ad7b8f1d865fa84a8`, LiteLLM 1.105.1, Node 22.16.0 and Git 2.51.0 as the existing experiment's proposed pins. Record any version change and its affected source review and tests rather than silently updating the cohort. See the [manifest requirements](../research/two-task-validation-fixture.md#fixture-manifest-and-retention) for the remaining pins.

Carry forward M1-10's proposed limits for review: 2 guest vCPUs/4 GiB RAM; container 1 CPU/2 GiB and 128 tasks; VM authority at most 10 minutes; forced stop within 10 seconds of fencing; 30 seconds per model call/check; 60 seconds for reconciliation. Storage, retry, simulated-spending and scenario-specific limits remain governed by the full [threshold table](../research/two-task-validation-fixture.md#proposed-numeric-thresholds). These values remain proposals.

Use synthetic inputs, dummy credentials and local scripted inference. Simulated billing can test accounting policy but cannot establish hosted billing behavior, model quality or real cost savings. Fixture construction is authorized. Tool/dependency installation, VM changes, paid inference and sending repository data to a provider still require the applicable explicit authorization under [AGENTS.md](../AGENTS.md).

After authorization and freeze, follow the existing order: validate the trusted harness, qualify #12 isolation, establish minimal #13 route/metering controls, run B0/B1 and the remaining fault cases, then assemble #14 evidence. Keep native resume disabled until the applicable recovery evidence qualifies it.

## Next research check

Freeze the prospective readiness policy and repeated cold-start qualification described in the [stopped-image findings](../research/validation/offline-inspection.md#corrected-trial-result-and-next-check). Earlier boots stalled or needed pause/resume; the last one-CPU trial missed the ACPI shutdown deadline. A read-only copy of that stopped disk established that the installer intentionally created the cloud-init disable marker and Linux handled the power event, reaching its power-off target. It also found the offline network-online wait failure. See the [inspection evidence](../research/validation/offline-inspection-evidence.json); no tools were installed.

The one-variable diagnostic initially failed before guest boot because VirtualBox's x2APIC setter also disabled ordinary APIC. Source review identified the coupling; the corrected command enables ordinary APIC last and verifies the exact profile before starting. The corrected trial completed one unattended two-CPU x2APIC-off boot/shutdown cycle in 234.271 seconds, with no pause/resume or emergency stop. Native poweroff was observed about 8.2 seconds after the ACPI receipt. The [diagnostic evidence](../research/validation/boot-diagnostic-evidence.json) retains the failed native start and the successful cycle separately. This is not yet repeated-start qualification or a proven cause of earlier stalls.

The latest receipt confirms Ubuntu 24.04.5, kernel `6.8.0-139-generic`, Python 3.12.3, UID 1000, ext4 root, loopback only, unchanged 480-row packages, clean package audit and no SSH server. Nine legacy predicates pass; `cloud_init_done` remains false because the known installer marker disables it. Historical verdicts are preserved. The next stage must test a narrowly bound readiness rule for that inspected policy before three consecutive cold-start/ACPI cycles, holding on any failure. Address the disconnected image's network-online wait during later hardening.

The current VDI SHA-256 is `2eb1d9cd009ecfe83381d855137f5cee8c1317739f6209beddd6da8a10955a09`. Native verification confirms poweroff, two vCPUs, 4096 MiB, ordinary APIC and x2APIC restored on, eight disabled NICs and UART off. The existing `ai-dev-test` VM and host virtualization/security configuration were unchanged. Runtime hardening, containment and executor behavior remain unqualified. The [deployment plan](../research/validation/deployment-plan.md) records the remaining controls. Issues #11–#14 and PR #25 were reread November 21 and remain open; PR #25 still contains the premature `Closes #11` reference. No remote changes were made.

The original 220-file review bundle remains unchanged at its recorded digest. This provisioning plan is a later revision, outside that freeze. Actual GSD export, built image/tool digests, deployed schemas, exact Chat transcripts and runtime qualification remain open. Product implementation and major architecture adoption remain gated on the feasibility decision.
