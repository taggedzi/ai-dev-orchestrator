# ai-dev-orchestrator

A research-stage project for a self-hostable system that coordinates AI agents across software development, from product discovery through release preparation. The developer owns scope, major architecture decisions, significant exceptions, and production releases.

The project prioritizes correct, maintainable software and total cost per accepted result, including retries and review. Execution speed is secondary.

## Current status

The approved [same-boot session](research/validation/maintenance-session-plan.md), [broker ceiling](research/validation/broker-ceiling-plan.md) and [owner-bound frontend startup](research/validation/frontend-start-plan.md) are locally prepared. Both VMs have [verified backups](research/validation/stopped-backup-plan.md) and independently checked [stopped maintenance profiles](research/validation/maintenance-profile-plan.md). Final regression passed **396 tests with 13 platform skips**, including 28 new startup checks using Python surrogates and synthetic VM/session facts; Ruff passes. A native session observer, actual startup/readiness, hardening and isolation/executor qualification remain open. There is no runnable orchestrator or approved product implementation stack yet.

**Resume here:** [Project status and next work](docs/status.md) and the [completion audit](docs/completion-audit.md). The full lifecycle goal remains open. The [planning freeze](research/validation/gsd-freeze-evidence.json) records the measured GSD fixture input; native target qualification and the feasibility decision precede product implementation.

[Offline image preparation](research/validation/image-build-plan.md) has produced a retained, hash-bound image with measured versions and startup checks. The advertised tool catalog is broader than the fixture grant, so a startup pass does not establish isolation or dispatch approval.

The [two-tool request and local admission checks](research/validation/control-policy-plan.md) have native model validation and [resolved tool/prompt data](research/validation/resolved-tool-plan.md), with zero task actions or inference. The developer selected a [trusted guard VM](docs/decisions/0001-validation-network-boundary.md) for network enforcement. Its disconnected creation is complete; guest installation/hardening and M1-12 qualification follow separate concrete reviews.

The [offline OS-update set](research/validation/os-update-plan.md) is cached and verified for both guest roles. Installation, firewall-service hardening and final runtime qualification remain separate steps.

- [Project vision](docs/vision.md)
- [Initial requirements and proof of concept](docs/requirements.md)
- [Exploratory architecture and risks](docs/architecture.md)
- Research plans for [OpenHands](research/openhands.md), [GSD Core](research/gsd-core.md), and [model routing](research/model-routing.md)
- [Two-task validation fixture](research/two-task-validation-fixture.md) and [executor recovery preflight](research/executor-cancellation-recovery.md)
- [Agent guidelines](AGENTS.md)

The current recommendation remains Conditional until the frozen fixture is approved and measured. See the status note for the remaining gates and proposed preparation scope.
