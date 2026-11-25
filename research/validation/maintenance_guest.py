"""Prepare an unarmed standalone guest inspection and control-change review.

No VM boot, transport, file attachment or guest action is performed.
"""

import argparse
import json
from pathlib import Path

from . import guest_maintenance_probe as probe
from .maintenance_runner import LOCAL, load_policy
from .offline_repo import description, new_root, write_json

PRIVATE_PATHS = [
    "/run/mcli1-maintenance",
    "/run/mcli1-maintenance/apt",
    "/run/mcli1-maintenance/apt/apt.conf.d",
    "/run/mcli1-maintenance/apt/preferences.d",
    "/run/mcli1-maintenance/apt/sources.list.d",
    "/run/mcli1-maintenance/apt/trusted.gpg.d",
    "/var/lib/mcli1-maintenance",
    "/var/lib/mcli1-maintenance/apt",
    "/var/lib/mcli1-maintenance/apt/lists",
    "/var/lib/mcli1-maintenance/apt/lists/partial",
    "/var/cache/mcli1-maintenance",
    "/var/cache/mcli1-maintenance/archives",
    "/var/cache/mcli1-maintenance/archives/partial",
    "/var/log/mcli1-maintenance",
]


def draft(role):
    planned = load_policy()["proposal"]
    probe.require(role in planned["roles"], "unknown guest role")
    config = LOCAL / "maintenance-config-01"
    return {
        "format": probe.FORMAT,
        "role": role,
        "run_nonce": None,
        "target": {"dmi_uuid": None, "root_fs_uuid": None, "boot_id": None},
        "approval": {"boot": None, "observation": None},
        "program_sha256": probe.sha(Path(probe.__file__).read_bytes()),
        "proposal_sha256": probe.PROPOSAL,
        "masks": planned["common_admin_masks_proposal"]
        + planned["roles"][role]["additional_admin_masks"],
        "policy": {
            "path": "/usr/sbin/policy-rc.d",
            "content": planned["policy_rc_d_proposal"]["content"],
            "mode": 0o755,
        },
        "private_paths": PRIVATE_PATHS,
        "config_files": {
            "/run/mcli1-maintenance/apt.config": (config / "apt.config")
            .read_bytes()
            .decode(),
            "/run/mcli1-maintenance/apt/sources.list": (config / "sources.list")
            .read_bytes()
            .decode(),
            "/run/mcli1-maintenance/apt/apt.conf": "",
            "/run/mcli1-maintenance/apt/preferences": "",
        },
    }


def prepare(role, output):
    spec = draft(role)
    root = new_root(output)
    (root / "guest_maintenance_probe.py").write_bytes(Path(probe.__file__).read_bytes())
    write_json(root / "spec.json", spec)
    raw = (root / "spec.json").read_bytes()
    try:
        probe.checked_spec(raw, probe.sha(raw))
    except probe.Refuse as exc:
        refusal = str(exc)
    else:
        raise probe.Refuse("unarmed guest spec unexpectedly accepted")
    review = {
        "status": "unarmed-inspection-and-control-review",
        "role": role,
        "spec": description(root / "spec.json"),
        "program": description(root / "guest_maintenance_probe.py"),
        "admission_refusal": refusal,
        "native_queries": 0,
        "mutations": 0,
        "transport_available": False,
        "control_change_executor_available": False,
        "installation_authority": None,
        "guest_observation_limits": {
            "total_seconds": 60,
            "per_command_seconds": 5,
            "report_and_command_bytes": probe.MAX_BYTES,
        },
        "host_transport_requirements": [
            "Bind approved VM/disk/backup and original external lease before enabling the approved serial channel",
            "Perform console I/O in a bounded worker outside the VM; never block or renew the supervisor",
            "Verify root and live DMI/root/boot identity before transferring into an exclusively created root-owned directory",
            "Hash-bind complete payload/spec and acknowledge each bounded transfer chunk; lost acknowledgement holds without replay",
            "Use host receive timestamps; never copy guest monotonic values into host freshness fields",
            "Fence and independently confirm stop on timeout, oversized output, changed identity or uncertain delivery",
        ],
        "before_install_still_required": [
            "Review actual unit aliases/overrides and dpkg configuration bytes from the selected target",
            "Separate authority and qualified create-only control-change execution with retained prior/partial state",
            "Recheck quiescence/effective masks/helper state and protected runtime/socket/group restrictions",
            "Mounted ISO/member verification, filesystem space accounting and actual APT configuration/replay checks",
            "Full host admission bindings and explicit package-installation approval",
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
            "spec": draft(args.role),
            "native_queries": 0,
            "mutations": 0,
        }
    )
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
