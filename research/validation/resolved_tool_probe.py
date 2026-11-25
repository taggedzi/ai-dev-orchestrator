"""Run only in the pinned preparation image; initialize tools without actions."""

import hashlib
import json
import sys
from pathlib import Path

REQUEST_SHA256 = "48b5b2f8c8519d80612766a9e1088be2459ca6da9e2396159b091b0dd5d41410"


def validate_observation(value):
    if (
        value["format"] != "mcli1-resolved-tool-probe-v1"
        or value["request_sha256"] != REQUEST_SHA256
        or value["working_dir"] != "/workspace/project"
        or value["resolved_names"] != ["terminal", "file_editor"]
        or value["inference_attempts"] != 0
        or value["action_attempts"] != 0
        or value["event_types"] != ["SystemPromptEvent"]
        or value["children_after_cleanup"]
        or value["executors_closed"] != ["terminal", "file_editor"]
    ):
        raise ValueError("tool resolution widened the profile or did not clean up")
    tools = json.loads(value["native_tool_json"])
    if [tool["function"]["name"] for tool in tools] != value["resolved_names"]:
        raise ValueError("serialized tool identities differ from resolved tools")
    for tool in tools:
        if tool["type"] != "function" or not tool["function"]["description"]:
            raise ValueError("missing native function description")
        properties = tool["function"]["parameters"]["properties"]
        if not {"summary", "security_risk"} <= set(properties):
            raise ValueError("missing SDK-added model-facing fields")
    raw = value["native_tool_json"].encode()
    if hashlib.sha256(raw).hexdigest() != value["native_tool_json_sha256"]:
        raise ValueError("native tool serialization digest mismatch")
    return tools


def child_pids():
    result = set()
    for path in Path("/proc/self/task").glob("*/children"):
        try:
            result.update(map(int, path.read_text().split()))
        except FileNotFoundError:
            continue
    return sorted(result)


def main():
    from contextlib import ExitStack
    from unittest.mock import patch

    from openhands.sdk import LLM
    from openhands.sdk.conversation.request import StartConversationRequest
    from openhands.sdk.conversation.state import ConversationState
    from openhands.sdk.event import SystemPromptEvent
    from openhands.tools.file_editor import FileEditorTool
    from openhands.tools.file_editor.impl import FileEditorExecutor
    from openhands.tools.terminal import TerminalTool
    from openhands.tools.terminal.impl import TerminalExecutor

    raw = sys.stdin.buffer.read()
    if hashlib.sha256(raw).hexdigest() != REQUEST_SHA256:
        raise ValueError("probe accepts only the retained canonical request")
    attempts = {"inference": 0, "action": 0}

    def deny_inference(*args, **kwargs):
        attempts["inference"] += 1
        raise RuntimeError("inference is prohibited in this preparation probe")

    def deny_action(*args, **kwargs):
        attempts["action"] += 1
        raise RuntimeError("tool actions are prohibited in this preparation probe")

    if child_pids():
        raise ValueError("unexpected preexisting child process")
    closed = []
    with ExitStack() as guards:
        guards.enter_context(patch.object(LLM, "completion", new=deny_inference))
        guards.enter_context(patch.object(LLM, "acompletion", new=deny_inference))
        guards.enter_context(
            patch.object(TerminalExecutor, "__call__", new=deny_action)
        )
        guards.enter_context(
            patch.object(FileEditorExecutor, "__call__", new=deny_action)
        )
        request = StartConversationRequest.model_validate_json(raw)
        agent = request.agent
        if [tool.name for tool in agent.tools] != [
            TerminalTool.name,
            FileEditorTool.name,
        ]:
            raise ValueError("unexpected native request tools")
        state = ConversationState.create(
            id=request.conversation_id,
            agent=agent,
            workspace=request.workspace,
            persistence_dir="/state/probe",
            max_iterations=request.max_iterations,
            stuck_detection=request.stuck_detection,
        )
        try:
            if len(state.events):
                raise ValueError("fresh probe unexpectedly resumed state")
            with state:
                agent.init_state(state, on_event=state.append_event)
            tools = list(agent.tools_map.values())
            if [tool.name for tool in tools] != ["terminal", "file_editor"]:
                raise ValueError("resolved tool set differs from the fixture grant")
            events = list(state.events)
            if len(events) != 1 or not isinstance(events[0], SystemPromptEvent):
                raise ValueError("initialization produced non-system events")
            event = events[0]
            tool_json = json.dumps(
                [
                    tool.to_openai_tool(add_security_risk_prediction=True)
                    for tool in tools
                ],
                ensure_ascii=False,
                separators=(",", ":"),
            )
            observation = {
                "format": "mcli1-resolved-tool-probe-v1",
                "classification": "Native Agent/ConversationState initialization and model-facing tool conversion only; no LocalConversation/Agent Server transport, actual Chat request or final-target qualification",
                "request_sha256": REQUEST_SHA256,
                "resolved_names": [tool.name for tool in tools],
                "event_types": [type(item).__name__ for item in events],
                "native_tool_json": tool_json,
                "native_tool_json_sha256": hashlib.sha256(
                    tool_json.encode()
                ).hexdigest(),
                "static_system_prompt": event.system_prompt.text,
                "dynamic_context": event.dynamic_context.text
                if event.dynamic_context
                else None,
                "working_dir": state.workspace.working_dir,
                "terminal_backend": type(tools[0].as_executable().executor).__name__,
                "inference_attempts": attempts["inference"],
                "action_attempts": attempts["action"],
                "children_before_cleanup": child_pids(),
            }
        finally:
            try:
                agent.close()
            finally:
                for name, tool in getattr(agent, "_tools", {}).items():
                    tool.as_executable().executor.close()
                    closed.append(name)
    observation["inference_attempts"] = attempts["inference"]
    observation["action_attempts"] = attempts["action"]
    observation["executors_closed"] = closed
    observation["children_after_cleanup"] = child_pids()
    validate_observation(observation)
    print(json.dumps(observation, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
