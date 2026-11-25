"""Test-only outside bootstrap; only the explicit Python surrogate can stop."""

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.validation import owner_launch as launch
from research.validation import owner_process as worker
from research.validation.maintenance_host import process_identity
from research.validation.maintenance_serial import KillJob
from research.validation.transfer_commands import canonical, digest

root = Path(sys.argv[1])
nonce = sys.argv[2]
controller_job = KillJob("Local\\MCLI1Controller-" + nonce)
controller = launch.SuspendedChild(
    ["-I", "-B", "-c", "import time;time.sleep(30)"], controller_job
)
controller.resume()
original = launch.SuspendedChild


def surrogate_child(args, job):
    prelude = f"import runpy;runpy.run_path({str(Path(__file__).with_name('owner_surrogate_child.py'))!r})['install_surrogate']({str(root)!r})\n"
    return original([*args[:3], prelude + args[3]], job)


with patch.object(launch, "SuspendedChild", surrogate_child):
    owner = launch.PendingOwner(
        root,
        "guard",
        nonce,
        process_identity(controller.pid),
        time.time_ns() + 20 * 10**9,
        "test:process-only",
    )
plan = json.loads(canonical(owner.proposal))
plan["approval"]["native_stop"] = "test:surrogate-only"
owner.seal(canonical(plan), digest(canonical(plan)), "test:surrogate-owner-start")
ready = owner.ready()
worker.stop.write_once(
    root / "bootstrap.observed.json",
    canonical(
        {
            "bootstrap_pid": os.getpid(),
            "controller_pid": controller.pid,
            "owner": ready["owner"],
            "owner_ready": True,
        }
    ),
)
# This abrupt exit closes the controller's last kill-job handle. The owner must
# continue in its independently retained job after both processes disappear.
os._exit(0)
