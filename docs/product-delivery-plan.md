# Delivery plan for the complete orchestrator

Status: **Approved for implementation, November 24, 2026**, through
[Decision 0008](decisions/0008-product-implementation-boundary.md). This plan
preserves [R1-R9](requirements.md) and the entire [vision](vision.md). P1's core
and CLI are implemented with [retained tests/smoke evidence](implementation/p1-core-evidence-02.json).
The authenticated loopback API/dashboard now exists with
[26 passing core/web tests](implementation/product-web-evidence.json) and
[approved local dependencies](implementation/web-install-evidence.json).
Browser tests use the separate pinned project dependency
[requirements/browser-qa.in](../requirements/browser-qa.in) (Playwright 1.64.1).
Browser usability, migration/restore and remaining deliverables still require
their stated acceptance evidence. P2's [trusted Git intake foundation](product-source.md)
now seals private candidates and artifacts. [Durable intake](product-intake.md)
adds approved attempt bindings, immutable review packets, read-only recovery and
an explicit v1-to-v2 migration; [53 product tests pass](implementation/product-intake-evidence.json).
[Candidate verification](product-verification.md) now admits exact policy-bound
check/review records and holds incomplete, conflicting or stale evidence;
[70 product tests pass](implementation/product-verification-evidence.json).
These are scripted outcomes. [Integration staging/regression records](product-integration.md)
now bind the exact staged subject, with [87 passing product tests](implementation/product-integration-evidence.json)
and private Git merge/CAS controls. The scripted P2 acceptance scenario is now
measured on a disposable Git fixture: rejected candidates and reviews cannot
promote, a changed SHA invalidates review, integrated checks bind the promoted
commit, one crash reconciles once, and task 2 starts from that accepted
integration. Real runner/reviewer qualification remains open. Scripted P3 model
policy and cost is measured on a scratch store: denied route, fallback, and
submission replay; a protected review allowance after implementation exhaustion;
unknown usage that keeps its reservation across reopen; and a new submission for
an authorized retry. Real provider behavior is not claimed.
[Model policy](product-model-policy.md). Research qualification continues
alongside implementation.

## First implementation milestone

Deliver a persistent, usable project workflow: initialize a project, capture its
requirements/context, submit and approve an exact dependency plan, schedule only
ready work, show current state, pause/revise it, and recover the same records
after restart. Start with a labeled scripted executor and no external model or
native dispatch. The first task is the versioned domain schema and approval/
transition commands, followed by their CLI. Add the HTTP/dashboard boundary once
its dependencies are separately approved and pinned.

The first acceptance scenario imports a two-task plan, rejects a cycle and an
unapproved edit, approves revision 1, prevents task 2 from starting, persists an
interrupted task-1 attempt, refuses blind redispatch and restores the same hold
after process restart. Scripted success cannot become a native qualification.
This milestone is an increment toward the product, not the final demonstration.

## Delivery sequence and evidence

| Milestone | Product behavior | Acceptance evidence |
| --- | --- | --- |
| P1: projects, authority and durable scheduling | Project/context/requirement versions, dependency plan validation, exact approval, task/attempt state, pause/redirect and restart recovery | CLI and API use the same commands; competing admissions yield one attempt; stale versions/approvals refuse; crash/reopen preserves decisions, holds and dependency blocks. Migration and backup/readback use the selected patched runtime. R1/R5/R7 foundation. |
| P2: source, checks and independent acceptance | Trusted Git intake/sealing, path policy, disposable check boundary, reviewer records, guarded integration and dependency release | Actual disposable Git fixture: rejected candidate cannot promote; changed SHA invalidates review; integrated checks bind the promoted commit; crash after ref update reconciles once; task 2 starts from accepted task-1 integration. Check execution of untrusted code waits for the qualified runtime. R3/R4 foundation. |
| P3: model policy and cost | Eligibility and assignments, broker permits, call identities, cumulative limits, protected review allowance and known/estimated/pending/unknown reports | Boundary tests cover denied route/fallback/replay, cap exhaustion and response loss; uncertainty retains its reservation across restart; each physical authorized retry gets a new submission. Real provider behavior is a separate deployment result. R2/R6 foundation. |
| P4: qualified execution and integrations | Connect the real pinned executor, frozen planning import and qualified local/gateway/direct model profiles | M1-12 denial groups plus positive controls; M1-13 allowed/forbidden/interrupted wire cases; M1-11 success/cancel/lost-ack/crash with independent stop/reap and safe reconciliation or hold. Preserve exact deployed versions and input hashes. R3/R5/R9 integration. |
| P5: autonomous proof of concept | One approved milestone with two dependent implementation tasks, model assignment, bounded recovery, independent review, integration and report | Real isolated edits and observed model traffic; injected recoverable failure with a fresh bounded attempt, rejected candidate/review controls, final integrated regression, total usage/cost/intervention report and explicit unknowns. Every artifact links to the approved plan, attempts and exact revisions. R1-R6 demonstration. |
| P6: lifecycle and release preparation | Guided discovery, persistent context, dashboard decisions/cost/failure views, pause/redirect, self-hosted deployment and release candidate preparation | A fresh operator follows setup/discovery/approval through P5, pauses and redirects active work without stale effects, restarts without losing context, inspects evidence and produces a verified package/release report. Publication remains a developer action. R7-R9 and vision lifecycle acceptance. |

## Qualification lane and dependencies

The held guard's Decision 0007 preparation is measured: scratch tests, Python
surrogates, read-only inventory and an unattached copy. A successor still needs
a patched storage runtime and a later exact native approval before any real
reservation transfer or boot. See
[Decision 0007](decisions/0007-held-guard-successor.md). Product implementation does
not consume that approval. Complete remaining startup-loss/late/detached/failure
coverage where required by the selected host profile, then guest readiness/UART
ownership, installation/hardening, effective isolation, gateway and executor
recovery measurements. Each native change or experiment keeps its concrete scope.
No scripted adapter may fill a missing effective-control field.

P1 and the trusted metadata portions of P2/P3 can be developed before this lane
finishes. Executing candidate code, enabling real executor/model routes and
claiming P4/P5 acceptance depend on its applicable gates. An unqualified paid
route stays unavailable. Local/gateway/direct support each needs an observed
allowed request, identity/usage evidence and failure/hold behavior on the actual
profile. Paid/provider-data experiments require their own approved scope and
budget. Subscription-authenticated access is assessed against the actual terms
and supported interface; unsupported access is explicitly unavailable.

## Completion traceability

| Requirement | Final authoritative proof |
| --- | --- |
| R1 | Approved versioned P5 plan; admission/dependency trace; task 2's input equals accepted task-1 integration. |
| R2 | Each implementation/review task's eligibility decision, requested configuration and observed resolved identities, with missing fields labeled. |
| R3 | Qualified target's controls and independent allowed/denied probes; real scoped task edits, candidate revisions and test records. |
| R4 | Separate reviewer/context and mandatory checks for each exact candidate; guarded integrated revision and passing regression before release of dependents. |
| R5 | Durable attempts/decisions/holds across crash; one injected recoverable failure within its limit; exhausted/uncertain outcomes visibly escalated without blind replay. |
| R6 | Auditable milestone totals across implementation, failed/corrective work and review; reconciled amounts separated from estimates/pending/unknown exposure and intervention counts. |
| R7 | Working approval, pause and redirect controls tested during execution; stale authority cannot dispatch, spend or promote; scope/architecture/exception/publication decisions remain gated. |
| R8 | Discovery produces durable project requirements/context; dashboard shows progress/cost/failures/pending decisions; verified release candidate artifacts and evidence can be prepared. |
| R9 | Repeatable self-hosted setup/backup/restart; observed qualified local, gateway and direct API integrations; documented subscription-access assessment and supported limitations. |

Completion also requires a clean-install walkthrough, backup/restore verification
on a disposable instance, reproducible dependency/license inventory, documented
configuration and recovery procedures, appropriate automated checks, and a
requirement-by-requirement audit of the actual release candidate. Unit tests,
manifests or a green scripted run cannot substitute for the broader evidence.
The [completion audit](completion-audit.md) remains the current finding until
these observations exist. No product release or remote publication is authorized
by an implementation decision.
