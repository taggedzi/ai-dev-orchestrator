# Developer workflow: current evidence and gaps

Reviewed November 24, 2026 for [M1-14](https://github.com/taggedzi/ai-dev-orchestrator/issues/14).
This is a document/CLI walkthrough of the current research checkout, **not a
product usability trial or a completed lifecycle demonstration**.
[Retained evidence](../research/validation/feasibility-walkthrough-evidence.json)
separates observations from proposed product behavior.

The research entry point, `python -m research.validation --help`,
describes M-CLI1 preparation and inspection. Its subcommands are `build`, `verify`,
`check`, `profile`, `blind`, `supervise`, `report`, `reserve`, `broker` and `proxy`.
They are fixture tools. A new product entry point, `python -m coordinator --help`,
now provides durable project/plan/approval/attempt commands independently of that
harness. [P1 evidence](implementation/p1-core-evidence-02.json) retains 15 passing
tests and a 21-process CLI smoke. Execution/model/cost outcomes are scripted;
an authenticated loopback API/dashboard now provides the same planning controls,
with [26 passing core/web tests](implementation/product-web-evidence.json).
Its [usage and remaining limits](product-web.md) include incomplete browser QA:
Computer Use could not confidently determine the URL. Real coding and revision
acceptance remain unimplemented. The full
[requirements](requirements.md) remain open.

| Interaction | Developer action for the intended product | What can be inspected today | Gap and next acceptance check |
| --- | --- | --- | --- |
| Initiate a project | Describe the goal and constraints, then inspect the captured requirements | CLI and local dashboard capture/version project requirements/context and reopen the same store | Browser usability and guided discovery remain open. Demonstrate discovery producing approved context through the full workflow. R1/R8 remain incomplete. |
| Approve a plan | Review one exact milestone, dependency graph, task criteria and limits | Product plan validation, exact-digest approval, version checks and dependency-gated scripted admission | No real coding milestone or independently accepted revision. T2 remains blocked after a scripted T1 candidate. R1/R7 remain incomplete. |
| Monitor progress and cost | Inspect current work, accepted work, blockers, known charges and unresolved exposure | Dashboard plan/task state, status documents, fixture journals and synthetic accounting reports | Cost/failure views and measured task/retry/review totals remain open. Demonstrate current identities, durable status and known/estimated/unknown costs across a complete milestone. R6/R8 remain incomplete. |
| Pause or redirect | Stop new authority, inspect outstanding effects, then explicitly approve changed work | CLI/web pause/recovery/revision fences; authenticated HTTP boundary tests; sender-process crash test; retained late/conflicting observations | Browser usability, live runtime containment, promotion and complete redirect workflow remain unqualified. An interrupt ACK alone is insufficient. R5/R7 remain incomplete. |
| Review completed work | Inspect the exact candidate, automated checks, independent review and integration result | Gold/rejection fixtures, revision-bound checks and one native normal guard startup/stop case | No autonomous implementation/reviewer/integration chain. Demonstrate separate review for the candidate, invalidation after edits, guarded integration and integrated regression before dependency release. R3/R4 remain incomplete. |
| Prepare a release | Inspect a verified candidate and release evidence, then decide publication | Repository documents and research artifacts | No product release candidate/package or lifecycle release workflow. Demonstrate release preparation against accepted requirements; publication stays separately approved. R8 remains incomplete. |

## Observed intervention burden

The retained audit lists exactly five unarmed expiries: startup reviews 03, 06,
08 and 09, and controller-loss review 01. Their terminal records report zero VM
boots, and none has an approval file. This is a count of those named artifacts,
not a total count of developer interventions or an estimate of all project cost.

The historical initial-run review included live process identities and an immutable
600-second lease. Waiting for a human consumes that lease; an expired review
cannot reuse its approval or process session. The latest loss review closed with
all three suspended processes independently retired and no VM start/stop.
The successful normal case does not resolve this interaction cost.

[Approved decision 0006](decisions/0006-review-before-native-lease.md) addresses
initial activation review by separating an inert input artifact from later
single-use process/lease binding. Its
[implementation/checks](../research/validation/offline-approval-evidence.json) now
pass with inert review, durable consumption and actual Windows Python binding.
The developer then separately approved its exact inert controller-loss artifact.
The [native run](../research/validation/guard-controller-loss-evidence.json) reached
the approved fault and measured containment in 2.668 seconds. Its original stop
failed and the target reservation remains held. Initial human review consumed no
live lease; protected hashing preceded the original lease construction. This
single measurement does not establish a product approval/recovery workflow.
No armed lease was extended, and running-guest inspection review remains inside
its original lease. Other product controls remain missing.

## Feasibility disposition

**Revise remains the evidence-based checkpoint.** The pinned candidates remain
OpenHands SDK/Agent Server v1.62.0 at
`504a88cab0fb48ee5226238ad7b8f1d865fa84a8`, GSD Core v1.21.0 at
`357508df233ccca0dcf4332b385d6bee9b113da9` through a frozen read-only planning
import, a trusted coordinator/Git writer, and a controlled model boundary. These
are the existing [executor](../research/openhands.md),
[planning](../research/gsd-core.md) and [routing](../research/model-routing.md)
research candidates, not a newly adopted product stack or a claim about today's
latest upstream versions. Product language, persistence and deployment selection
remain unresolved in the [draft architecture](architecture.md).

GitHub issues #11–#14 remain open as of the retained November 24 read-only check.
PR #25 still says `Closes #11` while describing runtime cases as Inconclusive;
no remote write or merge was made. A final M1-14 proposal still needs the remaining
native executor/isolation/gateway evidence, final component choices and the
developer's decision before implementation planning. This walkthrough addresses
one assessment deliverable; it does not close M1-14 or shrink the full project
goal to the research harness. See the [completion audit](completion-audit.md).

[Decision 0008](decisions/0008-product-implementation-boundary.md) now approves
concrete product components and a full R1-R9 delivery plan, with an explicit
ordering change to begin implementation while live execution remains gated.
The developer approved it and Decision 0007. Product implementation is authorized;
no product source was written before the requested [handoff](HANDOFF.md).
The later [runtime candidate check](../research/validation/patched-runtime-evidence.json)
also retains one unresolved startup-BEGIN hold, rather than reporting a full
passing regression. No proposal or focused test pass closes a missing product gate.
