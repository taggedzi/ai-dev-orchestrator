# Exploratory architecture

This is a draft of responsibilities and boundaries for the [initial requirements](requirements.md). Technology choices depend on research evidence and developer approval.

| Responsibility | Proposed boundary |
| --- | --- |
| Planning and project context | Maintain requirements, dependencies, acceptance criteria, and approval references. Evaluate GSD Core artifacts and workflows as candidates. |
| Lifecycle coordination | Advance approved work, enforce limits and approval gates, and reconcile interrupted attempts. Keep milestone decisions independent of execution and model vendors. |
| Agent execution | Accept a task, workspace, permissions, and model assignment. Return run status, artifact and revision references, and usage when available. Evaluate OpenHands here. |
| Model selection | Choose an eligible model based on task needs and policy. Record the requested model and resolved model/provider separately so gateway fallbacks remain visible. |
| Verification and integration | Check the candidate revision, collect independent review results, integrate accepted changes, and run regression checks on the integrated revision. |

## Starting assumptions to test

- Start with sequential execution within one milestone. Add concurrency when evidence shows a need.
- Give each record one authoritative owner. The proposed split is versioned planning artifacts for approved intent and a durable execution record for attempts, evidence, and interventions. Compare storage options after reviewing upstream state and recovery capabilities.
- Evaluate Git worktrees for source isolation and a restricted runtime for process, credential, and network isolation. Carry task and attempt IDs across boundaries to connect revisions, costs, and verification evidence.
- Compare a simple task-level routing policy with a fixed-model baseline. Evaluate gateways and adaptive routing where they can preserve privacy, budget, and evidence requirements.

## Open questions and risks

| Question or risk | Evidence needed |
| --- | --- |
| Can a self-hosted executor recover or reconcile a run after interruption? Retrying blindly could repeat side effects or charges. | Find restart, cancellation, event replay, and attempt lookup contracts. Later test a crash after an external action but before its result is recorded. |
| Who owns planning state and Git writes? Overlapping writers could corrupt project history. | Trace GSD Core workflow writes and commit hooks. Find a supported handoff with a single writer per record. |
| Can isolated runs enforce permissions on the target host? | Compare credential injection, workspace mounts, network controls, and cleanup. Later test attempts to access files or services outside the sandbox. |
| Can routing enforce privacy and budgets through fallbacks? Usage can be delayed or incomplete. | Trace provider identity, retries, fallback controls, and billing visibility. Decide how to handle unknown costs before authorizing a run. |
| What counts as independent review, and how do corrections affect accepted evidence? | Define reviewer context and a rubric. Test whether revision changes invalidate stale checks and reviews. |
| Which integrations are supportable over time? | Record license, self-hosting prerequisites, supported automation interfaces, and applicable terms for each version and access mode. |

Implementation language, persistence technology, runtime isolation, and deployment remain open.
