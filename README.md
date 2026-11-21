# ai-dev-orchestrator

A research-stage project for a self-hostable system that coordinates AI agents across software development, from product discovery through release preparation. The developer owns scope, major architecture decisions, significant exceptions, and production releases.

The project prioritizes correct, maintainable software and total cost per accepted result, including retries and review. Execution speed is secondary.

## Current status

Research designs M1-01 through M1-10 have been merged. M1-11's recovery preflight is on the current branch in [PR #25](https://github.com/taggedzi/ai-dev-orchestrator/pull/25), checked open November 21. The [synthetic fixture and local harness](research/validation/README.md) include a real pinned GSD export and five negative import controls. A pinned Agent Server image now builds and starts offline under a non-root/read-only preparation profile. The earlier Ubuntu VM diagnostic completed one unattended two-CPU boot and ACPI shutdown with x2APIC disabled. Final-target readiness, hardening and isolation/executor qualification remain open. There is no runnable orchestrator or approved implementation stack yet.

**Resume here:** [Project status and next work](docs/status.md). Freeze the narrow conversation/API policy, external network and guest-readiness/hardening prerequisites for M1-12 isolation testing. The [planning freeze](research/validation/gsd-freeze-evidence.json) records the measured GSD input.

[Offline image preparation](research/validation/image-build-plan.md) has produced a retained, hash-bound image with measured versions and startup checks. The advertised tool catalog is broader than the fixture grant, so a startup pass does not establish isolation or dispatch approval.

The [two-tool request and local admission checks](research/validation/control-policy-plan.md) now have SDK model/schema evidence. The developer selected a [separate trusted guard VM](docs/decisions/0001-validation-network-boundary.md) for network-enforcement preparation; exact provisioning and M1-12 qualification remain next.

- [Project vision](docs/vision.md)
- [Initial requirements and proof of concept](docs/requirements.md)
- [Exploratory architecture and risks](docs/architecture.md)
- Research plans for [OpenHands](research/openhands.md), [GSD Core](research/gsd-core.md), and [model routing](research/model-routing.md)
- [Two-task validation fixture](research/two-task-validation-fixture.md) and [executor recovery preflight](research/executor-cancellation-recovery.md)
- [Agent guidelines](AGENTS.md)

The current recommendation remains Conditional until the frozen fixture is approved and measured. See the status note for the remaining gates and proposed preparation scope.
