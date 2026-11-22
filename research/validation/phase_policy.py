"""Trusted frozen-turn token limits for the local scripted fixture broker."""

import re

from .bundle import load_json
from .fixture import POLICY
from .store import Hold

TOKEN_CAPS = {
    "edit": (12000, 6000),
    "correction": (12000, 2000),
    "finish": (6000, 1000),
    "review": (6000, 3000),
}
INPUT_MICRO_USD_PER_TOKEN = 10
OUTPUT_MICRO_USD_PER_TOKEN = 20


def validate_turn(admission):
    """Validate trusted transcript declarations; this does not attest their counts."""
    required = {
        "task",
        "attempt",
        "role",
        "input_tokens",
        "response_tokens",
        "counter_evidence_sha256",
    }
    if not isinstance(admission, dict) or set(admission) != required:
        raise ValueError("missing or extra frozen phase-admission fields")
    if (
        admission["task"] not in ("T-01", "T-02")
        or admission["role"] not in TOKEN_CAPS
        or not isinstance(admission["attempt"], str)
        or not 1 <= len(admission["attempt"]) <= 128
        or not isinstance(admission["counter_evidence_sha256"], str)
        or not re.fullmatch("[0-9a-f]{64}", admission["counter_evidence_sha256"])
    ):
        raise ValueError(
            "invalid frozen task, attempt, role or counter evidence digest"
        )
    input_cap, output_cap = TOKEN_CAPS[admission["role"]]
    for name, cap in (("input_tokens", input_cap), ("response_tokens", output_cap)):
        if type(admission[name]) is not int or not 0 < admission[name] <= cap:
            raise ValueError("invalid or over-cap frozen token measurement")
    bound = (
        input_cap * INPUT_MICRO_USD_PER_TOKEN + output_cap * OUTPUT_MICRO_USD_PER_TOKEN
    )
    if bound != POLICY["limits"][admission["role"]]:
        raise ValueError("phase token envelope differs from the fixture money policy")
    return bound


def admit_request(raw, request_sha256, admission):
    """Use exact-request-bound frozen measurements; never trust an executor role."""
    import hashlib

    bound = validate_turn(admission)
    if hashlib.sha256(raw).hexdigest() != request_sha256:
        raise Hold("request differs from the frozen count binding")
    payload = load_json(raw)
    if not isinstance(payload, dict) or set(payload) - {
        "model",
        "messages",
        "max_completion_tokens",
        "tools",
        "stream",
        "stream_options",
    }:
        raise Hold("unapproved Chat fields")
    if payload.get("model") != POLICY["model"] or not isinstance(
        payload.get("messages"), list
    ):
        raise Hold("unexpected model or messages")
    if not payload["messages"] or any(
        not isinstance(message, dict)
        or message.get("role") not in ("system", "user", "assistant", "tool")
        for message in payload["messages"]
    ):
        raise Hold("unexpected Chat message role")
    if "stream" in payload and type(payload["stream"]) is not bool:
        raise Hold("invalid stream option")
    if "stream_options" in payload and (
        payload.get("stream") is not True
        or not isinstance(payload["stream_options"], dict)
        or set(payload["stream_options"]) != {"include_usage"}
        or payload["stream_options"]["include_usage"] is not True
    ):
        raise Hold("unapproved stream options")
    requested = payload.get("max_completion_tokens")
    input_cap, output_cap = TOKEN_CAPS[admission["role"]]
    if type(requested) is not int or not 0 < requested <= output_cap:
        raise Hold("requested output exceeds trusted phase cap or has no bound")
    if admission["response_tokens"] > requested:
        raise Hold("frozen scripted response exceeds requested output")
    return {
        **admission,
        "request_sha256": request_sha256,
        "bound": bound,
        "input_cap": input_cap,
        "output_cap": output_cap,
        "requested_output_tokens": requested,
    }
