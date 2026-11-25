"""Python-only three-process stand-in for a hardened frontend process family."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

root, stage = Path(sys.argv[1]), int(sys.argv[2])
(root / f"family-{stage}.json").write_text(json.dumps({"pid": os.getpid()}))
if stage < 2:
    child = subprocess.Popen(
        [sys.executable, "-I", "-B", __file__, str(root), str(stage + 1)],
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
        close_fds=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    sys.exit(child.wait(timeout=15))
end = time.monotonic() + 12
while (
    not (root / "family.finish").exists()
    and not (
        (root / "allow.surrogate.stop").exists()
        and (root / "surrogate.effect").exists()
    )
    and time.monotonic() < end
):
    time.sleep(0.01)
