"""Metadata probe to run inside the existing pinned image, not on the host."""

import json
import sys


def main():
    from openhands.sdk import LLM, Agent
    from openhands.sdk.context import AgentContext
    from openhands.sdk.conversation.request import StartConversationRequest
    from openhands.sdk.workspace import LocalWorkspace
    from openhands.tools.file_editor import FileEditorAction, FileEditorTool
    from openhands.tools.terminal import TerminalAction, TerminalTool

    raw = json.load(sys.stdin)
    expected_classes = [
        (StartConversationRequest, raw),
        (Agent, raw["agent"]),
        (LLM, raw["agent"]["llm"]),
        (AgentContext, raw["agent"]["agent_context"]),
        (LocalWorkspace, raw["workspace"]),
    ]
    for cls, value in expected_classes:
        unknown = set(value) - set(cls.model_fields) - {"kind"}
        if unknown:
            raise ValueError(
                "SDK ignores unknown fields on "
                + cls.__name__
                + ": "
                + ",".join(sorted(unknown))
            )
    request = StartConversationRequest.model_validate(raw)
    agent = request.agent
    if (
        [tool.name for tool in agent.tools] != [TerminalTool.name, FileEditorTool.name]
        or agent.include_default_tools
        or agent.mcp_config
        or request.client_tools
        or request.tool_module_qualnames
        or request.agent_definitions
        or request.hook_config is not None
        or request.plugins
        or request.autotitle
        or agent.llm.num_retries != 0
        or agent.llm.fallback_strategy is not None
        or agent.agent_context.load_public_skills
        or agent.agent_context.load_project_skills
        or agent.agent_context.load_user_skills
        or agent.agent_context.load_memory
    ):
        raise ValueError("SDK request normalization widened the expected profile")
    output = {
        "format": "mcli1-sdk-control-schema-probe-v1",
        "request_model_validation": True,
        "supplied_fields_recognized": True,
        "tool_specs": [tool.model_dump(mode="json") for tool in agent.tools],
        "include_default_tools": agent.include_default_tools,
        "broker_url": agent.llm.base_url,
        "model": agent.llm.model,
        "max_input_tokens": agent.llm.max_input_tokens,
        "max_output_tokens": agent.llm.max_output_tokens,
        "native_tool_calling": agent.llm.native_tool_calling,
        "terminal_action_schema": TerminalAction.model_json_schema(),
        "file_editor_action_schema": FileEditorAction.model_json_schema(),
        "request_schema": StartConversationRequest.model_json_schema(),
        "classification": "Read-only model/schema validation; no conversation, tool executor, task or inference was started. Final resolved tool inventory and per-role wire/token fitting remain open.",
    }
    print(json.dumps(output, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
