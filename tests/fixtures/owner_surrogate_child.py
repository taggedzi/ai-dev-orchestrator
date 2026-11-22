"""Test-only entry: every intended VBox poweroff is an isolated Python child."""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.validation import maintenance_host as host
from research.validation import maintenance_stop as stop
from research.validation import owner_process as worker
from research.validation import windows_readonly as native

root = None
mode = None


def install_surrogate(value, selected_mode="success"):
    global root, mode
    root, mode = Path(value), selected_mode
    stop.STOPS_ROOT = root / "surrogate-stops"
    stop.executable = lambda _plan: None
    stop._run = surrogate


def surrogate(exe, args, wall, mono, before_resume):
    packet = json.loads((root / "owner.sealed.json").read_bytes())
    if str(exe) != str(stop.VBOX) or args != [
        "controlvm",
        packet["profile"]["target_vm_uuid"],
        "poweroff",
    ]:
        raise AssertionError("unexpected command shape")

    def alive(record):
        try:
            return host.process_identity(record["pid"]) == record
        except (stop.Hold, OSError):
            return False

    call = {
        "owner_pid": os.getpid(),
        "controller_live": alive(packet["controller"]),
        "bootstrap_live": alive(packet["bootstrap"]),
        "monotonic_ns": time.monotonic_ns(),
        "actual_VM_command": False,
    }
    with (root / "surrogate.calls.jsonl").open("a", encoding="utf-8") as output:
        output.write(json.dumps(call, sort_keys=True) + "\n")
        output.flush()
        os.fsync(output.fileno())
    marker = root / "surrogate.effect"
    source = f'from pathlib import Path;Path({str(marker)!r}).write_text("Python surrogate only");print("surrogate-stop")'
    result = native._run(
        sys.executable, ["-I", "-B", "-c", source], wall, mono, before_resume
    )
    if mode == "lost-ack":
        raise stop.Hold("test-only lost surrogate acknowledgement")
    return result


if __name__ == "__main__":
    install_surrogate(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "success")
    worker.worker_main(root)
