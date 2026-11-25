# Completion audit

Reviewed November 24, 2026 against [the vision](vision.md),
[requirements](requirements.md), [architecture](architecture.md), current sources
and retained run evidence. The objective is the complete development orchestrator.
The research harness is an intermediate deliverable. **The project is incomplete.**

The [developer workflow assessment](developer-experience-walkthrough.md) now
maps project initiation/approval, monitoring, pause/redirect, acceptance and
release preparation to current evidence and explicit gaps. It is a document/CLI
walkthrough, not product usability or lifecycle acceptance. The first native
controller-loss review expired unarmed. After approved and verified
[Decision 0006](decisions/0006-review-before-native-lease.md) preparation, separate
exact approval consumed its inert artifact once. The
[native fault](../research/validation/guard-controller-loss-evidence.json) measured
joined-controller-loss containment in 2.668 seconds, with original stop exit 1
and an active held target reservation. Aborted is not accepted shutdown.
Other native failure cases and product requirements remain open.

The [full product delivery plan](product-delivery-plan.md) and
[Decision 0008](decisions/0008-product-implementation-boundary.md) now record
approved components and all R1-R9 acceptance evidence. The developer approved
beginning product implementation alongside native qualification, without enabling
unqualified execution. [Decision 0007](decisions/0007-held-guard-successor.md)
preparation is now measured on scratch ledgers and an unattached copy. That
capture is not a reservation transfer, native boot, or completed requirement. Both
approvals are recorded in [the approval record](decisions/0007-0008-approval.json).
No product requirement is completed by these decisions. After the requested
handoff the user resumed implementation; [HANDOFF.md](HANDOFF.md) gives the
current product state and next API/P2 actions.
The [storage review](../research/validation/coordinator-storage-plan.md) also adds
a patched-runtime prerequisite. Current read-only integrity checks pass and the
held journals remain unchanged.

The tree now contains the product core/CLI and authenticated loopback web
workspace under `coordinator/`;
`integrations/` remains empty. [P1 evidence](implementation/p1-core-evidence-02.json)
records 15 passing product tests and a 21-process CLI smoke. Requirements remain
drafts. The later [web evidence](implementation/product-web-evidence.json) records
26 passing core/web tests; the [installed environment](implementation/web-install-evidence.json)
has 19 verified packages and unchanged base Python packages. Browser usability
could not be verified because URL observation failed. The
[trusted Git intake](product-source.md) now has actual scratch-object/ref and
artifact checks, including a child-process crash. These implement foundations;
real isolated coding and revision-bound independent acceptance remain open.
The later [durable intake cohort](implementation/product-intake-evidence.json)
retains 53 passing tests, real candidate admission/Git/packet effects and an
explicit offline v1-to-v2 CLI migration. Candidate effects and review packets are
bound to the approved attempt, with read-only reconciliation and revoked-authority
holds. Check execution, independent review and guarded promotion/acceptance remain
unimplemented; source preparation does not complete R3/R4 or the full milestone.
The [verification cohort](implementation/product-verification-evidence.json) now
adds exact policy-bound check/review operations, separate local producer roles,
coverage checks and a fresh candidate gate, with 70 passing product tests. These
are explicitly scripted observations; live eligibility/task acceptance remain
false. Actual isolated checks, independent reviewer quality, authenticated deployed
producers, integrated regressions and guarded promotion remain unqualified or
unimplemented. This does not complete R4 or the autonomous milestone.
The [integration cohort](implementation/product-integration-evidence.json) adds
durable private staging and exact-subject regression records, 87 passing product
tests and actual private merge/CAS controls. The application milestone head stays
unchanged and dependent task 2 stays blocked. Authorized diverged-head mapping
is measured and does not by itself promote. Fresh integrated checks/review and
one serialized promotion are now measured on scratch Git fixtures. `live_eligible`
stays false, and real isolated execution remains open. None of
these scripted records qualifies real isolated checks, reviewer quality or a
complete autonomous milestone.
Live-adapter adoption and acceptance remain subject to the open qualification gates.

## Product requirements

| Requirement | Evidence required for completion | Current evidence and finding |
| --- | --- | --- |
| R1: approved dependency plan and task acceptance criteria | Product plan persistence, approved inputs and scheduler trace proving dependent tasks cannot start early | Product core/CLI persists validated plans and exact approvals, atomically admits attempts and blocks unaccepted dependencies. Tests and a real CLI smoke exercise these gates with scripted outcomes. No real two-task product milestone. Incomplete. |
| R2: eligible model selection and assignment records | Task-specific eligibility/selection, requested/actual provider/model and reusable task definitions in a product run | Proposed routing research and synthetic scripted model policies. No measured product assignment/selection. Incomplete. |
| R3: isolated implementation and revision/test records | Final-target denial probes plus allowed edits; isolated task run tied to revision and check outputs | Offline preparation image, disconnected VMs and local harness checks. Final isolation/executor target unqualified; no native two-task implementation trace. Incomplete. |
| R4: independent revision-bound review/integration | Automated checks and separate reviewer for the exact candidate; accepted integration followed by regression | Synthetic gold/rejection corpus and local graders. No qualified independent reviewer, product acceptance or autonomous integration trace. Incomplete. |
| R5: persistent attempts, bounded recovery and escalation | Product interruption/recovery run, retry exhaustion/uncertainty surfaced accurately and durable status/decision records | Product scratch-store tests cover sender-process exit after durable intent, restart holds, fencing, late receipts and attempt exhaustion. CLI recovery is development-only; real executor effects/recovery and complete milestone behavior remain unqualified. Incomplete. |
| R6: progress, intervention, usage and total cost | Auditable product milestone report including implementation/retry/review cost and explicit unknowns | Fixture simulated accounting and reports. No accepted autonomous milestone or real usage/cost/intervention report. Incomplete. |
| R7: developer pause/redirect and approvals | Working product controls and durable scope/architecture/exception/release authority checks | CLI and authenticated loopback API/dashboard share exact approval and developer-only pause/resume/revision controls. HTTP boundary tests pass; browser usability, live runtime control and complete scope/exception/release workflow remain unqualified. Incomplete. |
| R8: discovery/context/release preparation/dashboard | Demonstrated discovery conversation, durable context, prepared release artifacts/evidence and a working status/cost/decision dashboard | The local planning dashboard captures project context and shows plans/task states. Browser verification, guided discovery, cost/failure views and product release preparation remain open. Incomplete. |
| R9: self-hosting and local/gateway/direct models | Repeatable product deployment and verified provider integrations; subscription access assessment with compatible terms | Product components are approved under Decision 0008; candidate integrations and pinned source findings exist. No implemented or qualified product integrations. Incomplete. |

## Vision lifecycle and demonstration

All seven named lifecycle stages remain required. Discovery/interview, approved
product architecture, roadmap/scheduler, agent execution, independent verification,
integration and release preparation need an integrated product workflow. Fixture
planning and gold checks do not establish that chain.

The proof of concept still requires one approved milestone with at least two
dependent tasks, task-specific model selection, isolated edits, testing,
independent review, integration and developer reporting. An injected recoverable
failure, bounded attempts and cost/intervention accounting must be included.
There is no complete measured run satisfying that demonstration.

## Research gates and named deliverables

| Gate or deliverable | Authoritative evidence needed | Current state |
| --- | --- | --- |
| Reproducible fixture/GSD export | Frozen bytes, pinned upstream inputs, native export/import controls | Prepared; retained native export and five negative controls. This is fixture conformance, not product R1 completion. |
| Trusted harness and original stop authority | Complete native startup/identity/expiry/failure/stop/reap workflow under exact grants | Review 10 measured normal startup/session/stop with independent poweroff proof in 2.597 seconds. The later exact offline review measured joined-controller-loss containment in 2.668 seconds; its original stop failed and remains held. Startup-loss/late/detached and other failure cases remain unqualified. |
| Target deployment and guard | Exact target identities, current disk/configuration/backup bindings, approved installation/hardening and effective controls | Guard creation/backups/stopped profiles, normal startup/stop and joined-controller-loss containment are measured. Guard is now Aborted/unlocked; executor remains poweroff/unlocked. Disks, NVRAM and executor files were preserved by the latest run; guard abort/time metadata changed. Recovery provenance and reservation settlement need review before another activation. Guest readiness, installation/hardening and effective isolation remain open. |
| Broker phase ceiling and wire/count freeze | Trusted raw/effective policy, qualified full input/response counts, actual Agent traffic and deployed route/stream behavior | Optional preparation mode and refusal/restart/interruption tests pass. Body comparisons reproduce retained prepared captures; actual run/count/service qualification remains open. |
| M1-12 / issue #12 isolation | All denial groups, live positive controls, allowed edit and stop/cleanup on the final profile | Specified, not measured on a qualified target. Incomplete. |
| M1-13 / issue #13 gateway | Allowed/forbidden routes, identity joins, interrupted replies and unknown-spend holds on deployed gateway | Local conformance/simulated spending only. Incomplete. |
| M1-11 / issue #11 executor recovery | Success/cancellation/lost acknowledgement/crash measurements with independent evidence | Preflight/probe/source review only. Runtime cases remain Inconclusive. |
| M1-14 / issue #14 feasibility and architecture | R1-R6 evidence assessment, developer walkthrough and explicit architecture approval | Native evidence gates remain open. Decision 0008 explicitly approves product implementation alongside qualification; it does not close this issue or establish final Go. |
| Frozen run authorization | Exact final input/control digests and scoped run approval | Local unarmed successor reviews exist. None authorizes a native executor run. |
| Release artifacts/publication | Verified product candidate, docs/package/release evidence; explicit publication approval | No product release candidate. Publication stays with the developer. |

The later [approved guard recovery attempt](../research/validation/guard-startup-lock-hold-evidence.json)
failed at VirtualBox's session lock and accepted no running sample. Its original
stop also failed. All reviewed identities retired and all backing files remain
unchanged. Startup observation locking is a source-supported candidate cause;
native startup/stop and recovery qualification remain Inconclusive.

The later [corrected native attempt](../research/validation/guard-startup-journal-hold-evidence.json)
reached Running and identified the exact frontend session PID. SQLite locking
prevented the durable join, so no running samples or successful stop were
accepted. All processes retired, disks stayed unchanged and only guard timestamp
metadata changed. This adds running-observation evidence; full qualification
remains Inconclusive.

The subsequent separately approved [review 10](../research/validation/guard-startup-normal-stop-evidence.json)
completed one normal guard startup/session/stop case, with a committed exact PID
binding, two accepted samples, original stop exit 0, natural zero family exits
and independent poweroff proof in 2.597 seconds. Both VMs were then off/unlocked;
disks/executor files are preserved. Guard NVRAM and shutdown metadata changed
during the authorized boot. This does not repair historical failed stops or
qualify native loss/failure cases, guest readiness, executor recovery or any
missing product requirement. No new native authority remains.

A read-only GitHub review on November 24 again found issues
[#11](https://github.com/taggedzi/ai-dev-orchestrator/issues/11),
[#12](https://github.com/taggedzi/ai-dev-orchestrator/issues/12),
[#13](https://github.com/taggedzi/ai-dev-orchestrator/issues/13) and
[#14](https://github.com/taggedzi/ai-dev-orchestrator/issues/14) open.
[PR #25](https://github.com/taggedzi/ai-dev-orchestrator/pull/25) is open with head
`e609dbc` and still says `Closes #11` despite inconclusive runtime cases. Its
description must not erase unfinished measurements at merge time. No remote write
was made. The retained snapshot is
`.local/validation/remote-milestone-review-2026-11-24.json`.

The [joined-controller-loss preparation](../research/validation/controller-loss-preparation-evidence.json)
adds an explicit fault review, actual Windows Python job-loss checks and a fresh
ordinary stopped backup/profile/readback/preflight. It grants no native fault
run, restart or normal-stop acceptance for abnormal termination. Native failure
cases and all missing product requirements remain open.

Separate exact approval subsequently authorized the
[native joined-controller-loss run](../research/validation/guard-controller-loss-evidence.json).
One boot and two accepted Running samples preceded controller exit 29. The job
emptied, all original/family identities retired, and two independent
Aborted/unlocked/PID-zero observations completed in 2.668 seconds. Original stop
exit 1 remains `possible-send` without a command receipt; the admission and target
reservation stay held. Both disks, guard NVRAM and executor files are unchanged;
only guard abort/time metadata changed. This is a narrower containment measurement,
not successful shutdown, recovery permission or completion of a product requirement.

The earlier frozen Python 3.13 cohort ran **608 tests: 595 passed, 13 platform skips**,
with no failures/errors and Ruff passing. The later
[patched-runtime candidate](../research/validation/patched-runtime-evidence.json)
ran **609 tests: 594 passed, 14 skipped, one error**. Its controller-loss case
held before resume on a known-BEGIN-non-entry SQLite BUSY; runtime compatibility
is not qualified. The test fixture's historical metadata coupling was corrected
and a drift negative case added; production code and real journals are unchanged.
Approved initial-Aborted recovery now
has typed admission records, actual unattached backup capture, separate-process
readback and read-only preflight; it grants no native activation. See
[the recovery evidence](../research/validation/initial-aborted-evidence.json),
[final exit checks](../research/validation/frontend-final-exit-evidence.json),
[COM-only startup preparation](../research/validation/startup-session-probe-evidence.json),
[controller journal correction](../research/validation/controller-journal-evidence.json),
[offline-review binding](../research/validation/offline-approval-evidence.json),
[the restart point](status.md) and linked evidence for exactly
what those checks cover. They do not prove completion of any missing product
requirement. Keep the full goal active through the remaining qualification,
developer feasibility decision, implementation and release preparation.

A later [controlled startup-entry check](../research/validation/startup-entry-lock-evidence.json)
adds one real-SQLite negative case and four passing focused diagnostics. At the
known pre-resume writer lock, the current code holds/fences without resume or
replay and keeps the lease clocks. VM/family facts are synthetic. This narrows the
failure branch but does not identify the earlier writer, repair the full failed
cohort, approve either pending decision or complete a product requirement. The
current tree collects 610 tests; no complete passing rerun is claimed.
