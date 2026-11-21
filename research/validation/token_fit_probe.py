"""Count retained preparation inputs inside the pinned image without inference."""

import hashlib
import json
import sys

INPUT_HASHES = {
    "request": "48b5b2f8c8519d80612766a9e1088be2459ca6da9e2396159b091b0dd5d41410",
    "static_system_prompt": "ec7656c1a1975904653d8cba87e41ae5d493d110ce1607b6d8b5476e254b6d3a",
    "dynamic_context": "77a5ca9923c3a8e07774d9acb1544197cf362a20fb0991a3215a61c5f48422a0",
    "native_tool_json": "f970210f7d91edd8f3df5435ba14f3309ccbd70542394e655892728ff31dc5cc",
}
ROLE_CAPS = {
    "initial_edit": 12000,
    "correction_edit": 12000,
    "finish": 6000,
    "review": 6000,
}


def validate_inputs(value):
    if set(value) != set(INPUT_HASHES):
        raise ValueError("unexpected preparation input fields")
    for name, expected in INPUT_HASHES.items():
        if hashlib.sha256(value[name].encode()).hexdigest() != expected:
            raise ValueError(f"changed retained input: {name}")


def validate_observation(value):
    if (
        value["format"] != "mcli1-token-fit-probe-v1"
        or value["input_sha256"] != INPUT_HASHES
        or value["inference_attempts"] != 0
        or value["native_tool_calling"] is not True
        or value["mock_tool_calls"] is not False
        or value["token_counter_disabled"] is not False
        or value["error"] is not None
    ):
        raise ValueError("invalid token measurement or changed counting path")
    counts = value["counts"]
    for name in ("sdk_messages_only", "litellm_messages_only", "litellm_with_tools"):
        if type(counts[name]) is not int or counts[name] <= 0:
            raise ValueError(
                "zero, missing or non-integer count is a failed measurement"
            )
    if counts["sdk_messages_only"] != counts["litellm_messages_only"]:
        raise ValueError("SDK and underlying message counters disagree")
    if counts["litellm_with_tools"] <= counts["litellm_messages_only"]:
        raise ValueError("tools did not add measured input tokens")
    if value["role_prefix_headroom"] != {
        role: cap - counts["litellm_with_tools"] for role, cap in ROLE_CAPS.items()
    }:
        raise ValueError("incorrect role prefix headroom")


def main():
    from contextlib import ExitStack
    from unittest.mock import patch

    import litellm
    from openhands.sdk import LLM
    from openhands.sdk.llm.message import Message, TextContent

    inputs = json.loads(sys.stdin.buffer.read())
    validate_inputs(inputs)
    attempts = 0

    def deny_inference(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        raise RuntimeError("inference is prohibited in this preparation probe")

    observation = {
        "format": "mcli1-token-fit-probe-v1",
        "classification": "Local counter estimate of retained system prompt and native tool definitions only; no user/history, Chat wire, provider billing or full role-fit qualification",
        "input_sha256": INPUT_HASHES,
        "counts": {},
        "error": None,
    }
    with ExitStack() as guards:
        guards.enter_context(patch.object(LLM, "completion", new=deny_inference))
        guards.enter_context(patch.object(LLM, "acompletion", new=deny_inference))
        try:
            config = json.loads(inputs["request"])["agent"]["llm"]
            llm = LLM.model_validate(config)
            messages = [
                Message(
                    role="system",
                    content=[
                        TextContent(text=inputs["static_system_prompt"]),
                        TextContent(text=inputs["dynamic_context"]),
                    ],
                )
            ]
            tools = json.loads(inputs["native_tool_json"])
            observation["model"] = llm.model
            observation["native_tool_calling"] = llm.native_tool_calling
            observation["mock_tool_calls"] = llm.should_mock_tool_calls(tools)
            formatted = llm.format_messages_for_llm(messages)
            encoded = json.dumps(
                formatted, ensure_ascii=False, separators=(",", ":")
            ).encode()
            observation["formatted_messages_sha256"] = hashlib.sha256(
                encoded
            ).hexdigest()
            observation["formatted_messages_bytes"] = len(encoded)
            observation["counts"]["sdk_messages_only"] = llm.get_token_count(messages)
            for name, definitions in (
                ("litellm_messages_only", None),
                ("litellm_with_tools", tools),
            ):
                observation["counts"][name] = litellm.token_counter(
                    model=llm.model,
                    messages=formatted,
                    tools=definitions,
                    custom_tokenizer=llm._tokenizer,
                )
            from litellm.litellm_core_utils.token_counter import (
                openai_tokenizer_encoding_name,
            )

            observation["encoding_name"] = openai_tokenizer_encoding_name(llm.model)
            observation["custom_tokenizer_present"] = llm._tokenizer is not None
            observation["token_counter_disabled"] = bool(litellm.disable_token_counter)
            observation["role_prefix_headroom"] = {
                role: cap - observation["counts"]["litellm_with_tools"]
                for role, cap in ROLE_CAPS.items()
            }
        except Exception as exc:  # noqa: BLE001 -- retain native failure before holding
            observation["error"] = f"{type(exc).__name__}: {exc}"
    observation["inference_attempts"] = attempts
    print(json.dumps(observation, sort_keys=True, separators=(",", ":")), flush=True)
    validate_observation(observation)


if __name__ == "__main__":
    main()
