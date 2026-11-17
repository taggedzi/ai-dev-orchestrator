# OpenHands research plan

**Question.** Can OpenHands serve as a replaceable, self-hosted executor for an approved development task?

1. Review the [SDK repository](https://github.com/OpenHands/software-agent-sdk) and [official documentation](https://docs.openhands.dev/). Pin a release or commit and map the supported local and remote execution interfaces. Trace a task from workspace creation and model configuration through status, cancellation, resumption, and cleanup.
2. Fill in a capability matrix with columns for API or source location, observed behavior, unknowns, and later test. Cover sandbox permissions, credential and network controls, events and artifacts, usage and cost, cancellation, restart recovery, host prerequisites, and licensing.

**Exit evidence.** Produce a lifecycle table and a candidate handoff contract for the coordinator. Identify who owns retries and which failures leave an unknown outcome. Record a recommendation to proceed with a later spike, keep investigating, or compare another executor.

**Later experiment.** On a fixture repository, exercise a successful run, cancellation, and interruption during execution. Compare the observed state, workspace changes, and usage before and after resumption.
