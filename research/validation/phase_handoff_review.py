"""Preparation-only output-ceiling candidate; never called by the broker."""

import hashlib
import json

from .bundle import load_json
from .fixture import POLICY
from .phase_policy import TOKEN_CAPS
from .store import Hold


def preview_output_ceiling(raw, role, raw_sha256, effective_sha256):
    """Reproduce an independently frozen target body without issuing a grant."""
    if hashlib.sha256(raw).hexdigest() != raw_sha256:
        raise Hold("candidate input differs from the frozen raw request")
    if role not in TOKEN_CAPS:
        raise Hold("unknown trusted phase")
    payload = load_json(raw)
    if (
        not isinstance(payload, dict)
        or payload.get("model") != POLICY["model"]
        or set(payload)
        - {
            "messages",
            "model",
            "max_completion_tokens",
            "tools",
            "stream",
            "stream_options",
        }
    ):
        raise Hold("candidate contains unapproved Chat fields")
    requested = payload.get("max_completion_tokens")
    if type(requested) is not int or not 0 < requested <= TOKEN_CAPS["edit"][1]:
        raise Hold("candidate lacks a valid output limit within the frozen SDK ceiling")
    bounded = min(requested, TOKEN_CAPS[role][1])
    if bounded == requested:
        effective = raw
    else:
        payload["max_completion_tokens"] = bounded
        # Preserve native key/array order and every content string. Do not sort.
        effective = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        ).encode()
    if hashlib.sha256(effective).hexdigest() != effective_sha256:
        raise Hold("candidate differs from the independently frozen effective request")
    return effective
