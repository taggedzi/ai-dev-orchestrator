"""Capture native HTTP serialization at a rejecting mock transport, without tasks."""

import hashlib
import json
import sys

ROLE_LIMITS = {"initial_edit": (12000, 6000), "finish_projection": (6000, 1000)}


def prepare_inputs(bundle, retained_root, expected_manifest_sha256):
    """Bind preparation-only messages to an existing frozen fixture packet."""
    from pathlib import Path

    from .bundle import canonical, verify
    from .token_fit_probe import INPUT_HASHES, validate_inputs

    bundle, retained_root = Path(bundle), Path(retained_root)
    manifest = verify(bundle, expected_manifest_sha256)
    filenames = {
        "request": "request.json",
        "static_system_prompt": "static-system-prompt.txt",
        "dynamic_context": "dynamic-context.txt",
        "native_tool_json": "native-tools.json",
    }
    retained = {
        key: (retained_root / name).read_text(encoding="utf-8")
        for key, name in filenames.items()
    }
    validate_inputs(retained)
    tasks = json.loads((bundle / "planning/expected-plan.json").read_bytes())["tasks"]
    if [task["id"] for task in tasks] != ["T-01", "T-02"]:
        raise ValueError("unexpected frozen task identities")
    cases = []
    for index, task in enumerate(tasks, 1):
        template = (bundle / f"prompts/{task['id']}.txt").read_text(encoding="utf-8")
        base = manifest["objects"]["S0" if index == 1 else "C1"]["oid"]
        operation = f"12345678-1234-4234-8234-{index:012d}"
        task_digest = hashlib.sha256(canonical(task)).hexdigest()
        cases.append(
            {
                "task": task["id"],
                "base_oid": base,
                "operation": operation,
                "task_sha256": task_digest,
                "template_sha256": hashlib.sha256(template.encode()).hexdigest(),
                "user_prompt": template.format(
                    input_oid=base, message_op=operation, task_digest=task_digest
                ),
                "dispatch_approved": False,
            }
        )
    return {
        "retained": retained,
        "retained_sha256": INPUT_HASHES,
        "cases": cases,
        "fixture_manifest_sha256": expected_manifest_sha256,
    }


def assess_request(raw, phase, counted_input):
    """Assess observed fields; an over-cap request is evidence, never an approval."""
    value = json.loads(raw)
    if (
        value["model"] != "fixture/model-v1"
        or [t["function"]["name"] for t in value["tools"]]
        != ["terminal", "file_editor"]
        or type(counted_input) is not int
        or counted_input <= 0
    ):
        raise ValueError("unexpected route, tools or token count")
    expected_roles = ["system", "user"]
    if phase == "finish_projection":
        expected_roles += ["assistant", "tool"]
    if [m["role"] for m in value["messages"]] != expected_roles:
        raise ValueError("unexpected message roles")
    outputs = [value[k] for k in ("max_tokens", "max_completion_tokens") if k in value]
    if len(outputs) != 1 or type(outputs[0]) is not int or outputs[0] <= 0:
        raise ValueError("missing, duplicate or invalid output bound")
    input_cap, output_cap = ROLE_LIMITS[phase]
    return {
        "input_tokens_estimated": counted_input,
        "input_cap": input_cap,
        "input_within_cap": counted_input <= input_cap,
        "requested_output_tokens": outputs[0],
        "output_cap": output_cap,
        "output_within_cap": outputs[0] <= output_cap,
        "dispatch_approved": False,
    }


def validate_observation(value):
    if (
        value["format"] != "mcli1-wire-input-probe-v1"
        or value["unexpected_transport_attempts"] != 0
        or value["socket_connect_attempts"] != 0
        or value["executor_instances"] != 0
        or len(value["cases"]) != 4
    ):
        raise ValueError("unexpected transport or probe scope")
    expected = [(task, phase) for task in ("T-01", "T-02") for phase in ROLE_LIMITS]
    for row, identity in zip(value["cases"], expected, strict=True):
        raw = row["wire_utf8"].encode()
        if (
            (row["task"], row["phase"]) != identity
            or row["http_attempts"] != 1
            or row["sdk_response_returned"]
            or not row["sdk_error_type"]
            or hashlib.sha256(raw).hexdigest() != row["wire_sha256"]
            or row["sdk_input_tokens"] != row["wire_input_tokens"]
            or row["assessment"]
            != assess_request(raw, row["phase"], row["wire_input_tokens"])
        ):
            raise ValueError("invalid native request observation")


def main():
    import socket
    from contextlib import ExitStack
    from unittest.mock import patch

    import httpx
    import litellm
    from openhands.sdk import LLM
    from openhands.sdk.llm.message import Message, MessageToolCall, TextContent
    from openhands.tools.file_editor.definition import FileEditorAction, FileEditorTool
    from openhands.tools.terminal.definition import TerminalAction, TerminalTool

    inputs = json.loads(sys.stdin.buffer.read())
    retained = inputs["retained"]
    # The host also binds the entire payload to its external SHA-256.
    for name, expected in inputs["retained_sha256"].items():
        if hashlib.sha256(retained[name].encode()).hexdigest() != expected:
            raise ValueError("changed retained input")
    config = json.loads(retained["request"])["agent"]["llm"]
    native = json.loads(retained["native_tool_json"])
    tools = [
        cls(description=definition["function"]["description"], action_type=action)
        for cls, action, definition in zip(
            (TerminalTool, FileEditorTool),
            (TerminalAction, FileEditorAction),
            native,
            strict=True,
        )
    ]
    if any(t.executor is not None for t in tools):
        raise ValueError("metadata tools unexpectedly have executors")
    converted = [t.to_openai_tool(add_security_risk_prediction=True) for t in tools]
    if (
        json.dumps(converted, ensure_ascii=False, separators=(",", ":"))
        != retained["native_tool_json"]
    ):
        raise ValueError(
            "metadata tool conversion differs from initialized native tools"
        )
    system = Message(
        role="system",
        content=[
            TextContent(text=retained[k])
            for k in ("static_system_prompt", "dynamic_context")
        ],
    )
    observation = {
        "format": "mcli1-wire-input-probe-v1",
        "classification": "Native SDK/LiteLLM HTTP serialization at a rejecting mock transport; prepared task inputs and synthetic finish projections, no Agent step, socket exchange, task execution, model response or final-target qualification",
        "unexpected_transport_attempts": 0,
        "socket_connect_attempts": 0,
        "executor_instances": 0,
        "cases": [],
    }
    captures = []

    def reject_http(client, request, **kwargs):
        if (
            str(request.url) != "http://127.0.0.1:18080/v1/chat/completions"
            or request.method != "POST"
            or request.headers.get("authorization") != "Bearer fixture-dummy"
        ):
            observation["unexpected_transport_attempts"] += 1
            raise RuntimeError("unexpected HTTP transport")
        captures.append(request.read())
        return httpx.Response(
            403,
            json={
                "error": {
                    "message": "preparation capture only",
                    "type": "permission_error",
                    "code": "fixture_preparation_denied",
                }
            },
            request=request,
        )

    def reject_socket(*args, **kwargs):
        observation["socket_connect_attempts"] += 1
        raise RuntimeError("all socket connections are prohibited")

    async def reject_async(*args, **kwargs):
        observation["unexpected_transport_attempts"] += 1
        raise RuntimeError("async transport is prohibited")

    with ExitStack() as guards:
        guards.enter_context(patch.object(httpx.Client, "send", new=reject_http))
        guards.enter_context(patch.object(httpx.AsyncClient, "send", new=reject_async))
        guards.enter_context(patch.object(socket.socket, "connect", new=reject_socket))
        guards.enter_context(
            patch.object(socket.socket, "connect_ex", new=reject_socket)
        )
        for case in inputs["cases"]:
            messages = [system, Message(role="user", content=case["user_prompt"])]
            for phase in ROLE_LIMITS:
                if phase == "finish_projection":
                    messages += [
                        Message(
                            role="assistant",
                            tool_calls=[
                                MessageToolCall(
                                    id="call_preparation_only",
                                    name="terminal",
                                    arguments=json.dumps(
                                        {
                                            "command": f"python3 -I /fixture/payloads/{case['task']}.py"
                                        }
                                    ),
                                    origin="completion",
                                )
                            ],
                        ),
                        Message(
                            role="tool",
                            tool_call_id="call_preparation_only",
                            name="terminal",
                            content="Preparation-only placeholder: payload not executed.\n",
                        ),
                    ]
                llm = LLM.model_validate(config)
                before = len(captures)
                row = {
                    "task": case["task"],
                    "phase": phase,
                    "sdk_response_returned": False,
                }
                try:
                    llm.completion(
                        messages, tools=tools, add_security_risk_prediction=True
                    )
                    row["sdk_response_returned"] = True
                except Exception as exc:  # noqa: BLE001 -- capture denial type, never fake success
                    row["sdk_error_type"] = type(exc).__name__
                row["http_attempts"] = len(captures) - before
                if row["http_attempts"] != 1:
                    raise ValueError("expected exactly one captured denied request")
                raw = captures[-1]
                wire = json.loads(raw)
                row["wire_utf8"] = raw.decode()
                row["wire_sha256"] = hashlib.sha256(raw).hexdigest()
                row["sdk_input_tokens"] = llm.get_token_count(
                    messages, tools, add_security_risk_prediction=True
                )
                row["wire_input_tokens"] = litellm.token_counter(
                    model=llm.model,
                    messages=wire["messages"],
                    tools=wire["tools"],
                    custom_tokenizer=llm._tokenizer,
                )
                row["assessment"] = assess_request(raw, phase, row["wire_input_tokens"])
                observation["cases"].append(row)
    print(json.dumps(observation, sort_keys=True, separators=(",", ":")), flush=True)
    validate_observation(observation)


if __name__ == "__main__":
    main()
