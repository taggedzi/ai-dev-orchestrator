# ai-dev-orchestrator

A research-stage project for a self-hostable system that coordinates AI agents across software development, from product discovery through release preparation. The developer owns scope, major architecture decisions, significant exceptions, and production releases.

The project prioritizes correct, maintainable software and total cost per accepted result, including retries and review. Execution speed is secondary.

## Current status

**Resume with [the agent handoff](docs/HANDOFF.md).** The product core, JSON CLI and authenticated loopback API/dashboard now persist projects, plans, approvals, attempts and recovery holds. **26 core/web tests pass**; the earlier retained CLI smoke made 21 subprocess calls. [CLI usage](docs/product-cli.md), [web usage](docs/product-web.md) and [web evidence](docs/implementation/product-web-evidence.json). The 19 approved web dependencies are installed in a project-local environment; [installation evidence](docs/implementation/web-install-evidence.json) verifies hashes and unchanged base packages. Browser tests use a separate lasting dependency, Playwright 1.64.1, in [requirements/browser-qa.in](requirements/browser-qa.in). Browser usability remains unverified because Computer Use could not confidently determine the URL. Execution is scripted development only; real coding, independent acceptance and live integrations remain open. The full product is incomplete.

The [trusted Git intake](docs/product-source.md) connects to [durable admission](docs/product-intake.md), [candidate evidence](docs/product-verification.md) and [integration staging/regressions](docs/product-integration.md), with exact approved bindings and stale/conflicting evidence holds. **87 product tests pass**, including process faults, real private merge/CAS controls and explicit migration from schemas 1–3 to 4. [Current evidence](docs/implementation/product-integration-evidence.json). Check/review/regression outcomes remain scripted; qualified execution, guarded milestone promotion and acceptance remain open. It never promotes a milestone or releases a dependent task.

The approved [same-boot session](research/validation/maintenance-session-plan.md), [broker ceiling](research/validation/broker-ceiling-plan.md) and [owner-bound frontend startup](research/validation/frontend-start-plan.md) are locally prepared. The earlier frozen [Python 3.13 regression](research/validation/offline-approval-evidence.json) passed 595 of 608 tests with 13 platform skips. A later preinstalled patched-runtime [candidate check](research/validation/patched-runtime-evidence.json) ran **609 tests: 594 passed, 14 skipped, one startup-BEGIN BUSY error**. Compatibility remains unqualified; production code and the held journals are unchanged.

The latest [approved guard run measured joined-controller-loss containment](research/validation/guard-controller-loss-evidence.json): one disconnected boot, two accepted Running observations and deliberate controller exit 29. The job emptied and independent inactive-session observations completed in **2.668 seconds**. The original owner's sole stop exited 1, so shutdown and the active target reservation remain held. Guard is Aborted/unlocked; executor is poweroff/unlocked. Both disks, guard NVRAM and executor files are unchanged; only guard abort/time metadata changed. No retry or further native authority remains.

Earlier [review 10](research/validation/guard-startup-normal-stop-evidence.json) measured the normal startup/session/stop case. The later fault result does not accept Aborted as successful shutdown. Startup-loss/late/detached cases, readiness, installation, hardening and isolation/executor qualification remain open. The new product CLI is runnable for planning and development state exercises; autonomous coding is not implemented yet.

**Resume here:** [Project status and next work](docs/status.md) and the [completion audit](docs/completion-audit.md). The full lifecycle goal remains open. The [planning freeze](research/validation/gsd-freeze-evidence.json) records the measured GSD fixture input. Decision 0008 permits product implementation alongside native qualification; dependent live execution still waits for its applicable gates.

The developer approved [the complete product delivery plan](docs/decisions/0008-product-implementation-boundary.md) while live execution remains gated, and [explicit held-guard recovery preparation](docs/decisions/0007-held-guard-successor.md). The [approval record](docs/decisions/0007-0008-approval.json) preserves both scopes. A [storage-runtime review](research/validation/coordinator-storage-plan.md) identified a patched-SQLite prerequisite; current journal integrity checks pass and no runtime or journal was changed.

The original live controller-loss review expired unarmed. The approved [offline-review model](research/validation/offline-approval-plan.md) separates human review from later one-use process/lease binding. Its inert artifact was separately approved and consumed by the latest run. Reviewed recovery provenance and held-reservation settlement must precede any later native activation. The [developer workflow assessment](docs/developer-experience-walkthrough.md) records remaining product gaps.

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
