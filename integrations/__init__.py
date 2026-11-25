"""Disabled execution integrations and explicitly labeled development doubles."""

from .openhands import (
    COMMIT,
    LIVE_DISPATCH_REFUSAL,
    PRODUCT,
    VERSION,
    LiveDispatchRefused,
    OpenHandsClient,
    ScriptedResultRefused,
    scripted_result,
)

__all__ = [
    "COMMIT",
    "LIVE_DISPATCH_REFUSAL",
    "PRODUCT",
    "VERSION",
    "LiveDispatchRefused",
    "OpenHandsClient",
    "ScriptedResultRefused",
    "scripted_result",
]
