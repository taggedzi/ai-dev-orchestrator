# Begin the product while native execution remains gated

Status: **Approved for implementation, November 24, 2026.** The developer
answered “I approve the decisions,” covering Decisions 0007/0008. The exact
proposals and approval are preserved in
the [approval record](0007-0008-approval.json). Product work may now
proceed under the boundaries below; dependent native gates remain open.

Runtime implementation note: the code will support Python 3.13 and later, with
initial persistence checks under the already installed Python 3.15.2 / SQLite
3.53.4. This uses the measured patched runtime without installing or replacing
the host Python. The older harness's unresolved startup hold remains separate.

## Problem and proposed decision

The [completion audit](../completion-audit.md) finds R1-R9 incomplete. The current
repository provides research documents and a validation harness; `coordinator/`
and `integrations/` have no product source. One normal guard startup/stop and one
joined-controller-loss containment case do not deliver the orchestrator.

Approve the product architecture below and implementation of the full
[delivery plan](../product-delivery-plan.md). Begin the durable project,
approval, scheduling, evidence and reporting workflow with local scripted
adapters. In parallel, complete the native qualification needed to enable real
adapters. Product acceptance still requires real executor and provider
integration, the two-task demonstration and all lifecycle requirements.

This explicitly changes the current ordering: allow product implementation
before M1-11/M1-12/M1-13 and the final M1-14 Go decision finish. Keep those issues
open and the disposition Revise. Their effective-control evidence remains a
prerequisite for dependent live execution, not for writing the product's durable
domain code. Do not mark an unqualified adapter ready or silently bypass a gate.
This proposed ordering change requires the developer's decision under
[AGENTS.md](../../AGENTS.md); the existing research approvals do not supply it.

## Concrete component choices

| Responsibility | Proposed implementation and boundary |
| --- | --- |
| Product coordinator | Python 3.13 or later, using an exact patched runtime verified through the storage plan. `coordinator/` owns domain records, scheduling, approval/fencing, recovery, verification, reports and the CLI/API. One active task per milestone initially; no distributed scheduler. |
| Persistent authority | A separate product SQLite database on local storage; one coordinator command writer, explicit short transactions, foreign keys and versioned migrations. Record transitions and pending external-effect intents in the same commit. Keep content-addressed immutable evidence files outside executor access. Existing research journals remain separate. |
| Developer interface | A CLI and FastAPI service with server-rendered HTML and small browser scripts. Use the same application commands for both. First deployment is one developer on one host, loopback-bound; authenticated sessions, CSRF and Host/Origin checks protect mutations. No remote exposure by default. Visual design follows the repository's UI skill when implementation begins. |
| Planning/context | Product project/requirement/context revisions plus guided discovery. Import frozen GSD Core schema-1 snapshots and raw PLAN files at pinned v1.21.0 commit `357508df233ccca0dcf4332b385d6bee9b113da9`. GSD remains an optional read-only import adapter; the coordinator owns approved intent and execution status. |
| Execution | Implement the reviewed OpenHands Agent Server v1.62.0 contract at commit `504a88cab0fb48ee5226238ad7b8f1d865fa84a8` in `integrations/`. Keep it disabled until its exact deployment passes the open gates. Synthetic adapters are labeled development/test mechanisms. Same-conversation automatic resume remains disabled pending qualification. |
| Model access/selection | A coordinator-controlled broker, provider-neutral task/model profiles and explicit eligibility rules. Adapters support a qualified local endpoint, gateway route and direct API route. Requested and resolved identity, raw usage and accounting provenance remain distinct. OpenRouter and local compatible endpoints remain candidates from existing research; no hosted route is activated by this decision. |
| Source and verification | A trusted Git writer owns product-managed refs. Agents receive metadata-free source copies in a qualified disposable runtime. Separate checks and reviewer identities evaluate the exact candidate; promotion uses an expected-old-OID check after integrated regression. Publication and this repository's own Git operations stay with the developer. |
| Self-hosting/release | A reproducible local installation and service/container packaging for the coordinator, protected store and separately managed runner/broker. Prepare release packages, migration/backup instructions, dependency/license inventory and evidence; publication requires separate approval. |

Python is proposed because the reviewed executor SDK and existing validation
contracts use it; this is an engineering choice, not a claim of measured product
performance. SQLite's [documented single-writer model](https://www.sqlite.org/whentouse.html)
fits the proposed host-local writer. [WAL](https://www.sqlite.org/wal.html) is not
a shared-network database. Multiple coordinator hosts or sustained competing
writers would require a new persistence decision. The
[patched-runtime prerequisite](../../research/validation/coordinator-storage-plan.md)
must be resolved before qualifying product persistence.

FastAPI is proposed for a typed HTTP boundary and shared request validation.
Its [version guidance](https://fastapi.tiangolo.com/deployment/versions/) calls
for pinning a tested version and checking upgrades. Exact FastAPI, ASGI server,
template, test and runtime artifacts must be resolved into a reviewed lock before
installation. No new dependency is installed by this proposal. The Python
[transaction documentation](https://docs.python.org/3.13/library/sqlite3.html#transaction-control)
is the reference for selecting explicit connection behavior; do not rely on an
implicit default that changes across Python releases.

## Authority and recovery contract

Persist project/plan revisions, criteria, approvals, task edges, attempts,
external operations, evidence, reviews, integrations, model submissions, budget
postings, interventions and release candidates with stable IDs. Bind every
mutation to its actor, expected record version and current authority generation.
Represent unknown effects and costs explicitly. A reported executor finish,
expired lease or interrupt acknowledgement is insufficient for acceptance.

One durable admission must claim a ready task, its approved input revision,
model profile and budget, then record the planned external operation before
delivery. If delivery becomes ambiguous, reconcile or hold; do not turn a
client request ID into a claim of provider idempotency. Pause fences new
dispatch, model submissions and promotion; the independent original runtime
owner still completes containment. A fresh correction uses a fresh attempt and
conversation. Native settlement remains deployment-specific evidence.

Checks, reviewer findings and integration must bind exact revisions and
criterion/check/rubric versions. Changed content invalidates applicable evidence.
The coordinator persists acceptance only after guarded promotion and regression,
then releases dependents from the accepted integration commit. No agent receives
authoritative Git, planning, credential, evidence-store or budget-ledger writes.

## Full scope and approval boundary

The delivery plan preserves discovery through release preparation, not only the
first demonstration. Scripted tests establish domain behavior, never real model
quality, target isolation, charge finality or product completion. The dashboard
must distinguish prepared, qualified, held, estimated and unknown states.

Approval authorizes product code, documentation, meaningful local tests and
dependency/runtime lock preparation. Local tests may create disposable fixture
repositories and commits; no commit to this repository is included. Dependency
installation, VM/runner changes, native activation, sending repository data to a
provider, paid experiments, remote writes and publication remain separate scopes.
Decision 0007 remains a separate research decision; this product decision cannot
transfer or clear the held guard reservation.

The alternative is to keep all product implementation deferred until the entire
native campaign finishes. That preserves current ordering but leaves every
product workflow unimplemented. The recommended choice allows concrete product
progress while retaining the live execution gates and the full completion test.
