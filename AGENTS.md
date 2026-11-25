# Agent guidelines

- Read [the vision](docs/vision.md) and inspect the working tree before editing. Preserve existing content and user changes. Treat [requirements](docs/requirements.md) and [architecture](docs/architecture.md) as drafts.
- Read [the handoff](docs/HANDOFF.md) when resuming. Before every meaningful stopping point, update it and the status checkpoint with actual progress, approvals and remaining limits, verification and known failures, live handles (or confirmed terminal state), and the next one or two concrete actions. Leave enough evidence for another agent to continue without this conversation; do not repeat approvals already recorded.
- Keep work in the research phase until the developer authorizes implementation. Ask before installing tools or dependencies, running paid experiments, or sending repository data to a provider.
- Prefer the codebase knowledge graph for code discovery when source exists. Use direct file reads for documents and configuration.
- Use primary sources. Record upstream versions or commit IDs, evidence, unknowns, and the next check. Mark observations from source review separately from results measured in a run.
- Keep provider-specific details at integration boundaries. Add abstractions only when a concrete need calls for them. Record proposed architectural decisions in `docs/decisions/` and seek developer approval for major decisions.
- Verify changed files and report outstanding questions. Leave Git commits, pushes, and release publication to the developer unless explicitly requested.
- Keep updates short and technically precise. When the developer needs to act, give at most two next steps at a time.
