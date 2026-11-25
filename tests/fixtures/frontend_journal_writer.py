"""Scratch-only independent SQLite writer; no VM or guest operation."""

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

root = Path(sys.argv[1])
db = sqlite3.connect(root / "owner.sqlite", isolation_level=None)
try:
    db.execute("BEGIN IMMEDIATE")
    with (root / "journal-writer.ready.json").open("x") as stream:
        json.dump({"pid": os.getpid()}, stream)
    end = time.monotonic() + 4
    while not (root / "journal-writer.release").exists():
        if time.monotonic() >= end:
            raise RuntimeError("scratch writer was not released")
        time.sleep(0.005)
finally:
    if db.in_transaction:
        db.execute("ROLLBACK")
    db.close()
