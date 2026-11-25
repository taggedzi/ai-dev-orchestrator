"""Guard-only initial-Aborted preparation records; no execution authority.

The concrete prior attempt is fixed by decision 0005. Ordinary callers cannot
opt into arbitrary offline states or relabel a historical poweroff backup.
"""

import hashlib
import json
import re

from .fixture import canonical
from .store import Hold

FORMAT = "mcli1-initial-aborted-context-v3"
LATEST_REVIEW = "fba9d14f0b7cadd70786674b730b34c8375fbba60c1d9b4886d725b9df86d77f"
LATEST_ROOT = ".local/validation/guard-startup-review-07"
LATEST_PARENT_SHA256 = (
    "0bff309b8928c81a74771cb1c0724187d640a099f87dc6baefb84015d7eba668"
)
LATEST_PARENT_CONTEXT = ".local/validation/initial-aborted-capture-04/recovery.json"
INTERVENING_REVIEW = "680a7aa23fe6efcd1db67344d1271e4e32b71e08f62e47736cbe8e8712dbefd0"
INTERVENING_ROOT = ".local/validation/guard-startup-review-05"
PARENT_CONTEXT_SHA256 = (
    "65e6e54ff8b939c66f547f6b3b7156895fb7fce4bc046237dbda97939466266a"
)
PARENT_CONTEXT = ".local/validation/initial-aborted-capture-03/recovery.json"
GUARD_VM = "0eceb37e-f216-45ed-817c-7cf2fca3a32a"
GUARD_DISK = "a8f47315-d330-4b28-bbb0-6a721b4c6251"
PRIOR_REVIEW = "98fa65d7365578352207992992a1d25ab8cf37dbf918d17e5f75aefd5c53ae6e"
PRIOR_ROOT = ".local/validation/guard-startup-review-04"
PRIOR_ARTIFACTS = {
    "review.json",
    "approval.json",
    "qualification.terminal.json",
    "owner/frontend.start.intent.json",
    "owner/frontend.resume.intent.json",
    "owner/frontend.terminal.json",
    "owner/controller.outcome.json",
    "owner/owner.sealed.json",
    "owner/owner.terminal.json",
    "independent-startup-inspection.json",
    "postfiles/receipt.json",
    "stop/poweroff.intent.json",
    "stop/process.result.json",
    "stop/stderr.bin",
    "stop/stdout.bin",
}
HISTORICAL_FILES = {
    "disk": {
        "state": "file",
        "bytes": 2625634304,
        "sha256": "a8a6024499644999738f089546096e93174a336c003f2d1ae841214c2fe22c43",
    },
    "configuration": {
        "state": "file",
        "bytes": 2373,
        "sha256": "29cc658e3183b4bccec8a59e2a9ab41f5ba1e9358fdd9048339ec3cbedccd340",
    },
    "nvram": {"state": "absent"},
}
FILES = {
    **HISTORICAL_FILES,
    "configuration": {
        "state": "file",
        "bytes": 2373,
        "sha256": "91c25dbe0e2281892a1cceeef07abc9c8a80d1595b12f1c7e403c1d2edbe17aa",
    },
}
INTERVENING_ARTIFACTS = PRIOR_ARTIFACTS | {
    "owner/frontend.stderr.bin",
    "parent/recovery.json",
}
LATEST_ARTIFACTS = INTERVENING_ARTIFACTS | {
    "owner/frontend.session.receipt.json",
    "running/session_raw.stdout",
    "running/machine_first.stdout",
    "running/machine.stdout",
    "running/medium.stdout",
}


def require(value, message):
    if not value:
        raise Hold(message)


def hash_value(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value)


def checked(value):
    """Validate/freeze record data; fresh prior-process/file checks are separate."""
    require(type(value) is dict, "recovery context is not an object")
    value = json.loads(canonical(value))
    require(
        set(value)
        == {
            "format",
            "role",
            "target_vm_uuid",
            "source_disk_uuid",
            "initial_state",
            "session_state",
            "session_pid",
            "prior",
            "intervening",
            "latest",
            "files",
            "first_observation",
            "last_observation",
            "completed_utc_ns",
            "sources",
            "VM_mutations",
            "VM_started",
            "native_boot_authorized",
        }
        and value["format"] == FORMAT
        and value["role"] == "guard"
        and value["target_vm_uuid"] == GUARD_VM
        and value["source_disk_uuid"] == GUARD_DISK
        and value["initial_state"] == "aborted"
        and value["session_state"] == "Unlocked"
        and type(value["session_pid"]) is int
        and value["session_pid"] == 0
        and type(value["VM_mutations"]) is int
        and value["VM_mutations"] == 0
        and value["VM_started"] is False
        and value["native_boot_authorized"] is False,
        "guard recovery format/target/state differs",
    )
    require(value["files"] == FILES, "guard recovery file baseline differs")
    checked_intervening(value["intervening"])
    checked_latest(value["latest"])
    prior = value["prior"]
    require(
        type(prior) is dict
        and set(prior)
        == {
            "review_sha256",
            "owner_nonce",
            "artifacts",
            "processes",
            "stop_child_pid",
            "stop_exit",
            "frontend_job_active_processes",
            "stop_job_active_processes",
        }
        and prior["review_sha256"] == PRIOR_REVIEW
        and type(prior["owner_nonce"]) is str
        and re.fullmatch(r"[0-9a-f]{32}", prior["owner_nonce"])
        and type(prior["artifacts"]) is dict
        and set(prior["artifacts"]) == PRIOR_ARTIFACTS
        and prior["artifacts"]["review.json"] == PRIOR_REVIEW
        and all(hash_value(v) for v in prior["artifacts"].values()),
        "recovery prior attempt/artifact binding differs",
    )
    require(
        type(prior["processes"]) is dict
        and set(prior["processes"]) == {"bootstrap", "controller", "owner", "frontend"},
        "recovery prior process identities differ",
    )
    for process in prior["processes"].values():
        require(
            type(process) is dict
            and set(process) == {"pid", "created_filetime", "image"}
            and type(process["pid"]) is int
            and 0 < process["pid"] < 2**32
            and type(process["created_filetime"]) is int
            and process["created_filetime"] > 0
            and type(process["image"]) is str
            and 0 < len(process["image"]) <= 32768
            and "\x00" not in process["image"],
            "recovery prior process identity is unbound",
        )
    require(
        len({p["pid"] for p in prior["processes"].values()}) == 4
        and type(prior["stop_child_pid"]) is int
        and 0 < prior["stop_child_pid"] < 2**32
        and type(prior["stop_exit"]) is int
        and prior["stop_exit"] == 1
        and type(prior["frontend_job_active_processes"]) is int
        and prior["frontend_job_active_processes"] == 0
        and type(prior["stop_job_active_processes"]) is int
        and prior["stop_job_active_processes"] == 0,
        "recovery prior failure/cleanup facts differ",
    )
    for observation in (value["first_observation"], value["last_observation"]):
        require(
            type(observation) is dict
            and set(observation)
            == {"observed_mono_ns", "machine_sha256", "medium_sha256", "session_sha256"}
            and type(observation["observed_mono_ns"]) is int
            and observation["observed_mono_ns"] > 0
            and all(
                hash_value(observation[k])
                for k in ("machine_sha256", "medium_sha256", "session_sha256")
            ),
            "recovery observation provenance differs",
        )
    first, last = value["first_observation"], value["last_observation"]
    require(
        last["observed_mono_ns"] > first["observed_mono_ns"]
        and all(
            first[k] == last[k]
            for k in ("machine_sha256", "medium_sha256", "session_sha256")
        )
        and type(value["completed_utc_ns"]) is int
        and value["completed_utc_ns"] > 0
        and type(value["sources"]) is dict
        and value["sources"]
        and all(type(k) is str and hash_value(v) for k, v in value["sources"].items()),
        "recovery bracketing observations/source provenance differ",
    )
    return value


def _checked_followup(value, *, latest):
    review = LATEST_REVIEW if latest else INTERVENING_REVIEW
    parent = LATEST_PARENT_SHA256 if latest else PARENT_CONTEXT_SHA256
    artifacts = LATEST_ARTIFACTS if latest else INTERVENING_ARTIFACTS
    extra = (
        {
            "joined_process",
            "join_receipt_sha256",
            "frontend_ledger_state",
            "frontend_ledger_receipt_sha",
        }
        if latest
        else set()
    )
    require(
        type(value) is dict
        and set(value)
        == {
            "review_sha256",
            "owner_nonce",
            "artifacts",
            "processes",
            "stop_child_pid",
            "stop_exit",
            "frontend_job_active_processes",
            "stop_job_active_processes",
            "parent_context_sha256",
            "family",
        }
        | extra,
        "intervening recovery attempt is missing or unbound",
    )
    require(
        value["review_sha256"] == review
        and value["parent_context_sha256"] == parent
        and type(value["owner_nonce"]) is str
        and re.fullmatch(r"[0-9a-f]{32}", value["owner_nonce"])
        and type(value["artifacts"]) is dict
        and set(value["artifacts"]) == artifacts
        and value["artifacts"]["review.json"] == review
        and value["artifacts"]["parent/recovery.json"] == parent
        and all(hash_value(v) for v in value["artifacts"].values()),
        "intervening review/parent/artifact binding differs",
    )
    processes, family = value["processes"], value["family"]
    require(
        type(processes) is dict
        and set(processes) == {"bootstrap", "controller", "owner", "frontend"}
        and type(family) is list
        and 1 <= len(family) <= 6,
        "intervening process/family inventory differs",
    )
    fields = {"pid", "created_filetime", "image"}
    require(
        all(type(p) is dict and set(p) == fields for p in processes.values())
        and all(type(p) is dict and set(p) == fields | {"exit_code"} for p in family),
        "intervening creation identity shape differs",
    )
    for process in [*processes.values(), *family]:
        require(
            type(process["pid"]) is int
            and 0 < process["pid"] < 2**32
            and type(process["created_filetime"]) is int
            and process["created_filetime"] > 0
            and type(process["image"]) is str
            and 0 < len(process["image"]) <= 32768
            and "\x00" not in process["image"],
            "intervening creation identity differs",
        )
    require(
        len({p["pid"] for p in processes.values()}) == 4
        and len({p["pid"] for p in family}) == len(family)
        and all(
            (
                (
                    p["exit_code"] is None
                    or type(p["exit_code"]) is int
                    and p["exit_code"] == 2
                )
                if latest
                else type(p["exit_code"]) is int and p["exit_code"] in {0, 1}
            )
            for p in family
        )
        and {**processes["frontend"], "exit_code": 2 if latest else 1} in family
        and type(value["stop_child_pid"]) is int
        and 0 < value["stop_child_pid"] < 2**32
        and type(value["stop_exit"]) is int
        and value["stop_exit"] == 1
        and type(value["frontend_job_active_processes"]) is int
        and value["frontend_job_active_processes"] == 0
        and type(value["stop_job_active_processes"]) is int
        and value["stop_job_active_processes"] == 0,
        "intervening failure/cleanup facts differ",
    )
    if latest:
        require(
            type(value["joined_process"]) is dict
            and value["joined_process"].get("image") == processes["frontend"]["image"]
            and any(
                {k: p[k] for k in fields} == value["joined_process"] for p in family
            )
            and value["join_receipt_sha256"]
            == value["artifacts"]["owner/frontend.session.receipt.json"]
            and value["frontend_ledger_state"] == "resumed"
            and value["frontend_ledger_receipt_sha"] is None,
            "latest orphan join receipt cannot become accepted authority",
        )
    return value


def checked_intervening(value):
    return _checked_followup(value, latest=False)


def checked_latest(value):
    return _checked_followup(value, latest=True)


def context_sha256(value):
    return hashlib.sha256(canonical(checked(value))).hexdigest()
