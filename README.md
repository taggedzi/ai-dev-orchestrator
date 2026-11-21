# ai-dev-orchestrator

A research-stage project for a self-hostable system that coordinates AI agents across software development, from product discovery through release preparation. The developer owns scope, major architecture decisions, significant exceptions, and production releases.

The project prioritizes correct, maintainable software and total cost per accepted result, including retries and review. Execution speed is secondary.

## Current status

Research designs M1-01 through M1-10 have been merged. M1-11's executor recovery preflight is on the current branch in [open PR #25](https://github.com/taggedzi/ai-dev-orchestrator/pull/25). A [synthetic fixture and local test harness](research/validation/README.md) are prepared, and the candidate VM now has Ubuntu Server installed offline. First boot, containment and executor validation remain open. There is no runnable orchestrator or approved implementation stack yet.

**Resume here:** [Project status and next work](docs/status.md). The next gate is target selection and deployment qualification for isolation, gateway, and recovery measurements.

- [Project vision](docs/vision.md)
- [Initial requirements and proof of concept](docs/requirements.md)
- [Exploratory architecture and risks](docs/architecture.md)
- Research plans for [OpenHands](research/openhands.md), [GSD Core](research/gsd-core.md), and [model routing](research/model-routing.md)
- [Two-task validation fixture](research/two-task-validation-fixture.md) and [executor recovery preflight](research/executor-cancellation-recovery.md)
- [Agent guidelines](AGENTS.md)

The current recommendation remains Conditional until the frozen fixture is approved and measured. See the status note for the remaining gates and proposed preparation scope.
