# Initial requirements

These draft requirements translate the [vision](vision.md) into observable outcomes. The scope column separates the first demonstration from later lifecycle coverage.

| ID | Requirement and acceptance evidence | Scope |
| --- | --- | --- |
| R1 | Given a developer-approved milestone, persist a dependency-ordered plan with task-level acceptance criteria. Start only tasks whose dependencies are satisfied. | Proof of concept |
| R2 | Select an eligible model for each task and record the decision, requested configuration, and actual model/provider when reported. Keep task definitions usable across providers. | Proof of concept |
| R3 | Run each implementation task in an isolated workspace with explicit permissions. Record the resulting revision and test outputs. | Proof of concept |
| R4 | Require automated checks and a reviewer separate from the implementation run. Tie both to the revision being accepted. Integrate only after checks pass, then rerun relevant regression tests on the integrated revision. | Proof of concept |
| R5 | Persist attempts, status, decisions, and blockers. Demonstrate recovery from an injected failure within a retry limit and show how exhausted retries or uncertain results surface for human review. | Proof of concept |
| R6 | Report milestone progress, verification results, intervention, usage, and total cost across implementation, retries, and review. Mark missing or estimated figures explicitly. | Proof of concept |
| R7 | Let the developer pause and redirect execution. Gate scope changes, major architecture changes, significant exceptions, and release publication on developer approval. | Lifecycle |
| R8 | Support interactive discovery, durable project context, and preparation of release artifacts and evidence. Show progress, costs, failures, and pending decisions in a dashboard. | Lifecycle |
| R9 | Support self-hosted operation and local, gateway, and direct API models. Evaluate subscription-authenticated agents for compatible, permitted access. | Lifecycle |

## Proof of concept

Use a small fixture repository and one approved milestone with at least two dependent tasks. Run it through planning, model selection, isolated implementation, testing, independent review, integration, and a developer report. Inject one recoverable failure and record the resulting attempts, actions, and cost. Capture the approved plan, revisions, checks, review decisions, and observed or estimated usage so the run can be audited.

Record correctness and maintainability, interventions per accepted milestone, total cost, and recovery behavior. Track elapsed time as a secondary measure. Choose the fixture, review rubric, and numeric limits before any run.
