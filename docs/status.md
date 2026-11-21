# Project status and restart point

Updated November 21, 2026. The developer requested a commit and continuation. Fixture/harness preparation was committed as `2758406`, VM provisioning as `6adb6f4`, and the separately approved offline OS installation has now completed. First boot, dependency installation, product implementation and executor experiments remain separate work.

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

## Next developer action

Prepare an offline first-boot verification for `mcli1-validation-01`. The separately approved [OS installation stage](../research/validation/os-install-plan.md) completed in 298.515 seconds and powered off. It installed Ubuntu Server 24.04.5 amd64 with kernel file `vmlinuz-6.8.0-139-generic`, 480 package rows and operator UID 1000; all NICs remained disabled. Standalone detection's `E_NOTIMPL` did not block the measured native install path. The installed target was inspected from the installer; a boot of that installed system, runtime hardening and executor behavior have not yet been verified. The [deployment plan](../research/validation/deployment-plan.md) records the remaining host, network and storage checks.

The original 220-file review bundle remains unchanged at its recorded digest. This provisioning plan is a later revision, outside that freeze. Actual GSD export, built image/tool digests, deployed schemas, exact Chat transcripts and runtime qualification remain open. Product implementation and major architecture adoption remain gated on the feasibility decision.
