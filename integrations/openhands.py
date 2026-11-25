"""Pinned OpenHands boundary; live deployment and automatic resume are disabled."""

PRODUCT = "OpenHands Agent Server"
VERSION = "1.62.0"
COMMIT = "504a88cab0fb48ee5226238ad7b8f1d865fa84a8"

LIVE_DISPATCH_REFUSAL = (
    "OpenHands Agent Server dispatch is disabled; no live adapter is qualified"
)


class LiveDispatchRefused(RuntimeError):
    """A live operation was refused locally before any external effect."""

    def __init__(self, refusal):
        super().__init__(LIVE_DISPATCH_REFUSAL)
        self.refusal = refusal


class ScriptedResultRefused(ValueError):
    """A development double cannot impersonate a live adapter or capability."""


class OpenHandsClient:
    """The reviewed live client contract, disabled before every operation."""

    def dispatch(self, operation, **payload):
        del payload
        reason = (
            "same-conversation automatic resume is disabled"
            if operation in ("attach", "resume")
            else "no live adapter is qualified"
        )
        raise LiveDispatchRefused(
            {
                "refused": True,
                "operation": operation,
                "adapter": "openhands",
                "reason": reason,
                "live_eligible": False,
            }
        )


def scripted_result(caller, outcome, **payload):
    """Return a simulated receipt without executing or persisting anything."""

    if type(caller) is not str or caller != "scripted":
        raise ScriptedResultRefused(
            "only the scripted development adapter can produce a scripted result"
        )
    if type(outcome) is not str or outcome not in ("candidate", "failed"):
        raise ScriptedResultRefused("scripted outcome must be candidate or failed")
    capabilities = payload.get("capabilities")
    enables_capability = (
        payload.get("live_eligible") is True
        or payload.get("task_acceptance") is True
        or (
            isinstance(capabilities, dict)
            and capabilities.get("task_acceptance") is True
        )
    )
    if enables_capability:
        raise ScriptedResultRefused(
            "scripted result cannot enable live eligibility or task acceptance"
        )
    return {
        "outcome": outcome,
        "simulated": True,
        "adapter": "scripted",
        "label": "scripted-development",
        "live_eligible": False,
        "task_acceptance": False,
        "resolved_model": "scripted/model-v1",
        "resolved_provider": "scripted-local",
        "cost_kind": "simulated",
        "cost": 0,
    }
