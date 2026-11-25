"""Prepare unarmed guest control payloads; perform no guest or native action."""

import argparse
import json
from pathlib import Path

from . import guest_maintenance_control as control
from . import guest_maintenance_probe as probe
from .maintenance_guest import draft as inspection_draft
from .offline_repo import description, new_root, write_json


def draft(role, spec_sha256):
    return {
        "format": "mcli1-guest-control-v1",
        "run_nonce": None,
        "role": role,
        "program_sha256": control.sha(Path(control.__file__).read_bytes()),
        "probe_sha256": control.PROBE_SHA256,
        "spec_sha256": spec_sha256,
        "observation_sha256": None,
        "stable_observation_sha256": None,
        "plan_sha256": None,
        "dpkg_configuration_sha256": None,
        "host_intent_receipt_sha256": None,
        "approval": {
            key: None
            for key in (
                "boot",
                "transfer",
                "observation",
                "control_changes",
                "backup",
                "dpkg_configuration_review",
            )
        },
        "window": {
            key: None
            for key in (
                "issued_utc_ns",
                "issued_mono_ns",
                "expires_utc_ns",
                "expires_mono_ns",
            )
        },
    }


def prepare(role, output):
    control.require(
        control.sha(Path(probe.__file__).read_bytes()) == control.PROBE_SHA256,
        "frozen inspection source changed",
    )
    spec = inspection_draft(role)
    spec_raw = json.dumps(spec, sort_keys=True, indent=2).encode() + b"\n"
    request = draft(role, control.sha(spec_raw))
    root = new_root(output)
    (root / "inspection-spec.json").write_bytes(spec_raw)
    for source in (Path(control.__file__), Path(probe.__file__)):
        (root / source.name).write_bytes(source.read_bytes())
    raw = control.canonical(request)
    (root / "request.json").write_bytes(raw)
    try:
        control.checked_request(raw, control.sha(raw))
    except control.Refuse as exc:
        refusal = str(exc)
    else:
        raise control.Refuse("unarmed control request unexpectedly accepted")
    review = {
        "status": "unarmed-control-executor-review",
        "role": role,
        "request": description(root / "request.json"),
        "refusal": refusal,
        "sources": {
            p.name: description(root / p.name)
            for p in (Path(control.__file__), Path(probe.__file__))
        },
        "spec": description(root / "inspection-spec.json"),
        "baseline_observation_collected": False,
        "native_calls": 0,
        "mutations": 0,
        "apply_entry_available_but_unarmed": True,
        "installation_available": False,
        "guest_state_directory": control.STATE,
        "still_required": [
            "Actual VM/disk/backup/root-session and original outside-VM lease admission",
            "Scoped boot/transfer/observation/control-change and dpkg-configuration review approvals",
            "Retained actual inspection, exact regenerated plan, source/input hashes and host durable intent",
            "Original-authority-bound guest clock window; host monotonic timestamps cannot be copied into it",
            "Independent fencing/VM stop/reap and approved native target measurement",
            "Mounted media/member, space, effective APT/replay and final installation admission checks",
        ],
    }
    write_json(root / "review.json", review)
    return review


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role", choices=("guard", "executor"), default="guard")
    parser.add_argument("--prepare")
    args = parser.parse_args()
    result = (
        prepare(args.role, args.prepare)
        if args.prepare
        else {
            "status": "unarmed-preview",
            "request": draft(args.role, None),
            "native_calls": 0,
            "mutations": 0,
        }
    )
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
