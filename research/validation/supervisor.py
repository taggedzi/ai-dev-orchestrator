"""Prepared external lease watcher. Target stop/reap still needs qualification."""

import time

from .driver import stop_vm
from .store import Hold


class LeaseSupervisor:
    """Persist the first deadline; restart cannot silently extend the lease."""

    def __init__(self, store, profile, now_ns=None, monotonic_ns=None):
        self.store = store
        self.profile = profile
        now = time.time_ns() if now_ns is None else now_ns
        monotonic = time.monotonic_ns() if monotonic_ns is None else monotonic_ns
        target = profile["target_vm_uuid"]
        expiry = profile["lease_expires_utc_ns"]
        if type(expiry) is not int:
            raise Hold("missing absolute lease deadline")
        with store.transaction():
            store.db.execute(
                "CREATE TABLE IF NOT EXISTS lease (singleton INTEGER PRIMARY KEY CHECK(singleton=1), target TEXT, armed_ns INTEGER, expires_ns INTEGER, armed_mono_ns INTEGER, expires_mono_ns INTEGER, state TEXT)"
            )
            row = store.db.execute("SELECT * FROM lease").fetchone()
            if row:
                if row["target"] != target or row["expires_ns"] != expiry:
                    raise Hold("lease binding changed across restart")
            else:
                if not now < expiry <= now + 600 * 10**9:
                    raise Hold("lease must expire within ten minutes")
                store.db.execute(
                    "INSERT INTO lease VALUES(1,?,?,?,?,?,'armed')",
                    (target, now, expiry, monotonic, monotonic + expiry - now),
                )
                store._event(
                    "lease-armed", {"target": target, "expires_utc_ns": expiry}
                )

    def poll(self, now_ns=None, stopper=None, monotonic_ns=None):
        now = time.time_ns() if now_ns is None else now_ns
        monotonic = time.monotonic_ns() if monotonic_ns is None else monotonic_ns
        with self.store.transaction():
            row = self.store.db.execute("SELECT * FROM lease").fetchone()
            authority = self.store.db.execute("SELECT * FROM authority").fetchone()
            if row["state"] == "stop-command-returned":
                return True
            if row["state"] == "stopping":
                raise Hold(
                    "stop result unknown after restart; independent supervisor reconciliation required"
                )
            if (
                row["armed_ns"] <= now < row["expires_ns"]
                and row["armed_mono_ns"] <= monotonic < row["expires_mono_ns"]
                and authority["active"]
            ):
                return False
            self.store.db.execute("UPDATE lease SET state='stopping'")
            self.store._event(
                "lease-stop-intent", {"target": row["target"], "observed_utc_ns": now}
            )
        # Persist the stop intent before calling the host, even if this process dies.
        (stopper or stop_vm)(self.store, self.profile)
        with self.store.transaction():
            self.store.db.execute("UPDATE lease SET state='stop-command-returned'")
            self.store._event(
                "lease-stop-returned",
                {"target": row["target"], "independent_reap_required": True},
            )
        return True

    def watch(self):
        while not self.poll():
            time.sleep(0.05)
