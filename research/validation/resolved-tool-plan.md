# Native two-tool resolution input check

This preparation check continues the [model/schema probe](control-policy-plan.md). It does not qualify the final executor, issue a task, call a model, or replace the separately approved guard topology. The pending [guard creation review](guard-preparation-plan.md) is unchanged.

## Concrete native scope

Use the existing image `sha256:f242d7a2b69742fde04385231647c54c57396b251ddfd7a5f34095073970e868`, OpenHands SDK/tools 1.62.0 at `504a88cab0fb48ee5226238ad7b8f1d865fa84a8`. Supply only the retained canonical request bytes, SHA-256 `48b5b2f8c8519d80612766a9e1088be2459ca6da9e2396159b091b0dd5d41410`. The literal workspace remains `/workspace/project` and the request has the explicit subprocess terminal/file editor, no default tools and disabled context/extension inputs.

[resolved_tool_probe.py](resolved_tool_probe.py) creates a fresh native ConversationState and calls Agent.init_state. It initializes the real tool backends, including a temporary interactive Bash/PTY session for terminal startup. It emits only the initial SystemPromptEvent. Model completion and tool-action entry points are tripwires: any attempted call increments a counter and raises instead of returning a fake result. No user message, Agent.step, LocalConversation or Agent Server is created. No OS-update archive is installed or executed.

The probe retains the resolved tool names, native model-facing function conversion with security-risk prediction enabled, exact serialized tool JSON/hash, static system prompt and dynamic context. It requires exactly terminal/file_editor and the SDK-added summary/security_risk fields. It then closes the agent and both executors and requires no remaining direct child processes. Host-side observation must confirm the temporary container is gone.

The native container has no network, host mounts or published ports: read-only root, UID/GID 10001, all capabilities dropped, no-new-privileges, one CPU, 2 GiB RAM/no extra swap, 128 PIDs and bounded fresh tmpfs HOME/state/workspace/tmp. Agent telemetry remains denied and the local LiteLLM metadata map is selected. Input and code enter through process stdin/argv; there are no provider credentials.

The reviewed local driver is prepared under `.local/validation/resolved-tools-01/run.py`; its default invocation previews the scope without native calls. Apply requires a separate native command approval. It checks the literal Linux-engine pipe and preexisting Desktop/backend processes. If Desktop is stopped, it may briefly start the installed app, verify the exact already-cached image and run this one named/token-labeled container. It may not pull/build images, install packages, switch engines or alter a VirtualBox VM. A failed/uncertain check holds rather than repeating the action.

Afterward, stop/remove only an object whose image and unique operation label prove ownership. Restore Desktop's stopped state only when this driver started it and no unrelated running container is observed. Preserve raw command results, source/request hashes, counters, prompt/schema bytes and cleanup receipts. Reconcile uncertain native state before any new attempt; an observation timeout is not evidence that the container stopped.

## Why this adds evidence

The pinned [Agent initializer](https://github.com/OpenHands/software-agent-sdk/blob/504a88cab0fb48ee5226238ad7b8f1d865fa84a8/openhands-sdk/openhands/sdk/agent/base.py#L560-L649) resolves tool specifications and can attach skill/vision defaults. The [tool converter](https://github.com/OpenHands/software-agent-sdk/blob/504a88cab0fb48ee5226238ad7b8f1d865fa84a8/openhands-sdk/openhands/sdk/tool/tool.py#L713-L790) adds summary and, for these tools, security-risk fields. Agent.init_state renders a real SystemPromptEvent; its step path later requests that same risk-enabled conversion. The previous action-model schema check did not perform this initialization or conversion.

## Measured initialization result

The third native preparation attempt passed in the existing pinned image: exactly `terminal` and `file_editor`, one SystemPromptEvent, zero inference attempts and zero tool-action attempts. The forced subprocess terminal initialized; one direct child was observed before cleanup (PID 10 in that temporary container's namespace). Both executors closed and the final direct-child set was empty. The container was automatically removed. Desktop was stopped again, and the literal Linux engine pipe stopped responding. No VirtualBox operation, image pull/build, package installation or model/provider call occurred.

The native function conversion is 8,051 UTF-8 bytes, SHA-256 `f970210f7d91edd8f3df5435ba14f3309ccbd70542394e655892728ff31dc5cc`. Its serialized insertion order is preserved in the ignored raw artifact. Both schemas advertise optional `summary` and `security_risk` fields; the risk enum is UNKNOWN/LOW/MEDIUM/HIGH. Required fields remain `command` for terminal and `command`/`path` for file editor. The rendered static prompt is 15,235 bytes and dynamic context 85 bytes. These are measured byte lengths, not token counts or proof of fitting the role caps.

The first two attempts held in host preflight before any probe container was created. The isolated Docker config initially omitted the installed Desktop plugin directory; the second startup lacked standard Windows user-directory variables and never exposed the engine. Native process checks found Desktop/backend absent before the corrected attempt. Revision 03 supplies those host directories, uses synchronous bounded startup, and preserves the same offline container profile and probe source. The container receives only its fixed image/runtime variables and synthetic request. Failed receipts and exact sources remain intact. See [resolved-tool-evidence.json](resolved-tool-evidence.json).

## Limits and next check

This is native Agent/state preparation on Docker Desktop, not the complete LocalConversation constructor or HTTP/wire path. Ambient plugin discovery, effective final-target LSM/network/mount controls, actual Chat request bytes, role token fitting, supervisor/observer/extractor and M1-12/M1-13 measurements remain open. Keep deployment `tool_schema_sha256` unset until the final profile and actual wire schemas are bound. A prepared function-schema digest is not a captured request or dispatch approval.

After this input check, compare the resolved definitions and rendered prompts with final-target observations, complete role/token fitting and freeze the remaining wire/control inputs before approved executor qualification. Do not change historical model-only probe claims or treat metadata initialization as task execution.
