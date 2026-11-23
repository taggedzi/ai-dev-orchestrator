"""Private, original-owner-bound direct frontend preparation.

The CLI only prints an unarmed draft. Native execution requires a separately
reviewed exact grant. Preparation tests replace the private process and file
boundaries with Python surrogates; they establish no VirtualBox settlement proof.
"""

import ctypes
import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from contextlib import ExitStack
from pathlib import Path

from . import boot_preconditions as boot
from . import frontend_process as frontend
from . import maintenance_host as host
from . import owner_process as owner
from . import stopped_backup as backup
from .maintenance_serial import ExtendedLimits, KillJob
from .transfer_commands import canonical, digest
from .windows_readonly import require

SOURCES = {
    **boot.SOURCES,
    **backup.SOURCES,
    "frontend_start.py": Path(__file__),
    "frontend_process.py": Path(frontend.__file__),
    "native_session.py": Path(__file__).with_name("native_session.py"),
    "maintenance_serial.py": Path(KillJob.__init__.__code__.co_filename),
}
SOURCE_EPOCH = {n: digest(p.read_bytes()) for n, p in SOURCES.items()}
RESERVE_NS = 10 * 10**9
STARTUP_NS = 15 * 10**9


def draft(role="guard"):
    return {
        "format": "mcli1-direct-frontend-start-v1",
        "boot": boot.draft(role),
        "profile_receipt_sha256": None,
        "executable": {
            "path": str(frontend.HEADLESS),
            "sha256": frontend.HEADLESS_SHA256,
        },
        "environment_sha256": None,
        "limits": {"frontend": 3, "family": 6, "controller": 12},
        "startup_ns": STARTUP_NS,
        "stop_reserve_ns": RESERVE_NS,
        "approval": {"native_run": None},
        "sources": dict(SOURCE_EPOCH),
    }


def checked(raw, sha):
    require(type(raw) is bytes and digest(raw) == sha, "frontend grant digest differs")
    grant = host.object_bytes(raw)
    require(
        set(grant) == set(draft())
        and grant["format"] == "mcli1-direct-frontend-start-v1",
        "frontend grant format differs",
    )
    b = boot.checked(canonical(grant["boot"]), digest(canonical(grant["boot"])))
    require(
        b["caller"]["role"] == "controller", "frontend caller must be the controller"
    )
    require(
        b["backup"].get("format") == backup.records.BINDING_FORMAT,
        "frontend start requires the explicit file-backup binding",
    )
    require(
        grant["executable"] == draft()["executable"]
        and grant["limits"] == draft()["limits"]
        and type(grant["startup_ns"]) is int
        and grant["startup_ns"] == STARTUP_NS
        and type(grant["stop_reserve_ns"]) is int
        and grant["stop_reserve_ns"] == RESERVE_NS,
        "frontend executable/limits differ",
    )
    require(
        set(grant["approval"]) == {"native_run"}
        and isinstance(grant["approval"]["native_run"], str)
        and 0 < len(grant["approval"]["native_run"]) <= 256,
        "separate native run approval is unbound",
    )
    for key in ("environment_sha256", "profile_receipt_sha256"):
        require(
            isinstance(grant[key], str) and re.fullmatch(r"[0-9a-f]{64}", grant[key]),
            "frontend input digest is unbound",
        )
    require(
        grant["sources"]
        == SOURCE_EPOCH
        == {n: digest(p.read_bytes()) for n, p in SOURCES.items()},
        "frontend source cohort changed",
    )
    return grant


def image_environment(grant):
    require(
        not os.environ.get("VBOX_USER_HOME")
        and digest(frontend.HEADLESS.read_bytes()) == grant["executable"]["sha256"]
        and digest(canonical(frontend.frontend_environment()))
        == grant["environment_sha256"],
        "frontend image/environment changed",
    )


def controller_limits(packet):
    """Check the actual caller's already established outer job, without changing it."""
    api = owner.job_api()
    job = api.OpenJobObjectW(0x4, False, packet["controller_job"])
    require(job, "frontend controller job is unavailable")
    try:
        require(
            owner.member(api, os.getpid(), job),
            "frontend caller is outside controller job",
        )
        limits = ExtendedLimits()
        KillJob.check(
            api.QueryInformationJobObject(
                job, 9, ctypes.byref(limits), ctypes.sizeof(limits), None
            )
        )
        require(
            limits.BasicLimitInformation.LimitFlags == 0x2008
            and limits.BasicLimitInformation.ActiveProcessLimit
            == frontend.CONTROLLER_LIMIT,
            "frontend controller job limits differ",
        )
    finally:
        KillJob.check(api.CloseHandle(job))


def profile_binding(grant, raw):
    require(
        type(raw) is bytes and digest(raw) == grant["profile_receipt_sha256"],
        "frontend profile receipt differs",
    )
    profile = host.object_bytes(raw)
    b = grant["boot"]
    require(
        profile["status"] == "stopped-maintenance-profile-reported-not-boot-authority"
        and profile["role"] == b["role"]
        and profile["target_vm_uuid"] == b["target"]["vm_uuid"]
        and profile["source_disk_uuid"] == b["target"]["disk_uuid"]
        and profile["backup_receipt_sha256"] == b["backup"]["receipt_sha256"]
        and profile["disk_sha256"] == b["disk_evidence"]["pre_boot_disk_sha256"]
        and profile["nvram"] == b["backup"]["nvram"]
        and profile["VM_started"] is False
        and profile["native_boot_authorized"] is False
        and profile["network_enabled"] is False,
        "frontend profile/backup/target binding differs",
    )
    return profile


class _InputLocks:
    """Retain the measured original files until the final suspended resume gate.

    Releasing these locks allows VBox to open the disk and update configuration.
    The final read-only stopped observation and identities are checked first.
    This is not a hypervisor-wide configuration lock or a native qualification.
    """

    def __init__(self, grant, backup_raw, profile):
        self.stack = ExitStack()
        self.absent = []
        self.files = []
        try:
            b = grant["boot"]
            require(
                backup.verify_files(backup_raw, digest(backup_raw)) == b["backup"],
                "fresh backup verification differs",
            )
            paths = backup.source_paths(b["role"])
            expectations = {
                "disk": {
                    "state": "file",
                    "bytes": b["backup"]["disk_bytes"],
                    "sha256": profile["disk_sha256"],
                },
                "configuration": profile["configuration"],
                "nvram": profile["nvram"],
            }
            for name, expected in expectations.items():
                self.hold(paths[name], expected)
            if b["role"] == "guard":
                source = backup.source_paths("executor")["disk"]
                self.hold(
                    source,
                    {
                        "state": "file",
                        "bytes": b["backup"]["disk_bytes"],
                        "sha256": host.SOURCE_DISK_SHA,
                    },
                )
            self.check()
        except BaseException:
            self.close()
            raise

    def hold(self, path, expected):
        if expected == {"state": "absent"}:
            require(not path.exists(), "frontend expected absent file exists")
            self.absent.append(path)
            return
        stream = self.stack.enter_context(backup.locked_source(path))
        info = os.fstat(stream.fileno())
        require(
            expected
            == {
                "state": "file",
                "bytes": info.st_size,
                "sha256": hashlib.file_digest(stream, "sha256").hexdigest(),
            },
            "frontend original file bytes changed",
        )
        self.files.append((path, stream, backup.file_identity(info), info.st_size))

    def check(self):
        require(
            all(not p.exists() for p in self.absent),
            "frontend absent firmware file appeared",
        )
        for path, stream, identity, size in self.files:
            require(
                backup.file_identity(path.stat())
                == identity
                == backup.file_identity(os.fstat(stream.fileno()))
                and os.fstat(stream.fileno()).st_size == size,
                "frontend locked source identity changed",
            )

    def close(self):
        self.stack.close()


class _PreparedStart:
    """Private trusted adapter. No arbitrary executable/argv or stop command API.

    Keep the instance alive through the whole boot/session and always retire it.
    Its independent watchdog does not depend on the runtime observer returning.
    Guest dispatch and original stop acceptance remain separate control paths.
    """

    def __init__(self, store, probe):
        self.store, self.probe = store, probe
        self.family = self.grant = self.packet = self.terminal = None
        self.lock = threading.RLock()
        self.done = threading.Event()
        self.thread = None
        self.joined = None
        self.last_observation = 0
        self.owner_stop = None

    def start(self, raw, sha, backup_raw, preboot, preservation, profile_raw):
        require(self.grant is None, "frontend adapter is one use")
        self.grant, self.raw, self.sha = checked(raw, sha), raw, sha
        b = self.grant["boot"]
        host.receipt_pins(b, backup_raw, preboot, preservation)
        profile = profile_binding(self.grant, profile_raw)
        self.packet, _ = boot.owner_live(self.store, b)
        controller_limits(self.packet)
        self.root = Path(b["owner"]["root"])
        try:
            # Original-file hashing is inside the bounded admission window. A
            # slow filesystem must obtain a new reviewed attempt, never renewal.
            with ExitStack() as stack:
                inputs = _InputLocks(self.grant, backup_raw, profile)
                stack.callback(inputs.close)
                first = boot.stopped_snapshot(b, self.probe())
                require(
                    first["machine_sha256"] == profile["machine_sha256"]
                    and first["medium_sha256"] == profile["medium_sha256"],
                    "frontend current stopped profile differs",
                )
                image_environment(self.grant)
                boot.owner_live(self.store, b)
                intent = canonical(
                    {
                        "grant_sha256": sha,
                        "run_nonce": b["run_nonce"],
                        "original_lease": self.packet["lease"],
                        "profile_receipt_sha256": self.grant["profile_receipt_sha256"],
                        "first_observation": first,
                    }
                )
                owner.stop.write_once(self.root / "frontend.start.intent.json", intent)
                with self.store.transaction():
                    self.store.db.execute(
                        "CREATE TABLE IF NOT EXISTS frontend_start (singleton INTEGER PRIMARY KEY CHECK(singleton=1), grant_sha TEXT, state TEXT, process BLOB, receipt_sha TEXT)"
                    )
                    require(
                        self.store.db.execute("SELECT 1 FROM frontend_start").fetchone()
                        is None,
                        "frontend start already attempted; no replay",
                    )
                    self.store.db.execute(
                        "INSERT INTO frontend_start VALUES(1,?,'intent',NULL,NULL)",
                        (sha,),
                    )
                    self.store._event("frontend-start-intent", {"grant_sha256": sha})
                self.family = frontend._FrontendProcess(
                    frontend.HEADLESS,
                    ["--startvm", b["target"]["vm_uuid"], "--vrde", "off"],
                )

                def gate(identity):
                    final = boot.stopped_snapshot(b, self.probe())
                    require(
                        final["machine_sha256"] == first["machine_sha256"]
                        and final["medium_sha256"] == first["medium_sha256"],
                        "frontend stopped profile changed before resume",
                    )
                    checked(raw, sha)
                    image_environment(self.grant)
                    boot.owner_live(self.store, b)
                    controller_limits(self.packet)
                    inputs.check()
                    owner.stop.write_once(
                        self.root / "frontend.resume.intent.json",
                        canonical({"grant_sha256": sha, "process": identity}),
                    )
                    with self.store.transaction():
                        row = self.store.db.execute(
                            "SELECT * FROM frontend_start"
                        ).fetchone()
                        require(
                            row["state"] == "intent" and row["grant_sha"] == sha,
                            "frontend resume journal changed",
                        )
                        boot.live_window(b)
                        boot.ledger_live(
                            self.store.db,
                            b,
                            self.packet,
                            host.object_bytes(
                                owner.read_packet(self.root / "owner.ready.json")
                            )["observed_mono_ns"],
                        )
                        self.store.db.execute(
                            "UPDATE frontend_start SET state='possible-resume',process=?",
                            (canonical(identity),),
                        )
                        self.store._event(
                            "frontend-possible-resume", {"process": identity}
                        )
                    inputs.close()

                self.started_utc, self.started_mono = (
                    time.time_ns(),
                    time.monotonic_ns(),
                )
                self.family.resume(gate)
                self.thread = threading.Thread(
                    target=self._watch, name="frontend-authority-watch", daemon=True
                )
                self.thread.start()
                # If resume acknowledgement is lost, possible-resume is already
                # durable. Cleanup/fencing follows; no second resume or starter.
                with self.store.transaction():
                    row = self.store.db.execute(
                        "SELECT * FROM frontend_start"
                    ).fetchone()
                    require(
                        row["state"] == "possible-resume" and row["grant_sha"] == sha,
                        "frontend resume acknowledgement journal changed",
                    )
                    boot.ledger_live(
                        self.store.db,
                        b,
                        self.packet,
                        host.object_bytes(
                            owner.read_packet(self.root / "owner.ready.json")
                        )["observed_mono_ns"],
                    )
                    self.store.db.execute("UPDATE frontend_start SET state='resumed'")
                    self.store._event(
                        "frontend-resumed", {"process": self.family.identity}
                    )
            return {
                "status": "frontend-resumed-awaiting-session-identity",
                "process": self.family.identity,
                "guest_ready": False,
            }
        except BaseException:
            self.retire("start admission/resume incomplete")
            raise

    def _live(self):
        require(self.terminal is None and not self.done.is_set(), "frontend is retired")
        checked(self.raw, self.sha)
        packet, _ = boot.watch_owner(self.store, self.grant["boot"])
        require(packet == self.packet, "frontend original owner packet changed")
        controller_limits(packet)
        lease = packet["lease"]
        now, mono = time.time_ns(), time.monotonic_ns()
        require(
            now < lease["expires_ns"] - RESERVE_NS
            and mono < lease["expires_mono_ns"] - RESERVE_NS,
            "frontend original stop reserve reached",
        )
        if self.joined is None:
            require(
                0 <= now - self.started_utc < STARTUP_NS
                and 0 <= mono - self.started_mono < STARTUP_NS,
                "frontend session identity startup timed out",
            )
        else:
            require(
                0 <= mono - self.last_observation <= 5 * 10**9,
                "frontend runtime observation heartbeat is stale",
            )
        db = sqlite3.connect(
            (self.root / "owner.sqlite").resolve().as_uri() + "?mode=ro",
            uri=True,
            timeout=0.05,
        )
        db.row_factory = sqlite3.Row
        try:
            row = db.execute("SELECT * FROM frontend_start").fetchone()
            require(
                row is not None
                and row["grant_sha"] == self.sha
                and row["state"] in {"possible-resume", "resumed", "session-bound"}
                and row["process"] == canonical(self.family.identity),
                "frontend running journal was lost or changed",
            )
        finally:
            db.close()
        require(
            not self.family.fault.is_set(), "frontend output overflow/collector fault"
        )
        require(
            self.family.poll() is None,
            "frontend root exited before original stop acceptance",
        )
        members = self.family.members()
        require(self.family.identity in members, "frontend root identity left family")
        if self.joined is not None:
            require(self.joined in members, "frontend session process left family")
        return members

    def _watch(self):
        while not self.done.wait(0.05):
            try:
                with self.lock:
                    if self.owner_stop is None:
                        self._live()
                    elif self._stopping():
                        self.retire("original stop returned and frontend family exited")
                        return
            except BaseException as error:  # noqa: BLE001 -- every watchdog failure requires containment
                self.retire("authority/family watchdog: " + str(error)[:256])
                return

    def request_owner_stop(self):
        """End a joined session through its original owner, within four seconds.

        This sends only the existing durable authority fence. It issues no VM
        command and accepts no stop result. Startup uncertainty uses retire()
        immediately, rather than this optional bounded normal-finish path.
        """
        with self.lock:
            try:
                self._live()
                require(
                    self.joined is not None and self.owner_stop is None,
                    "normal stop requires a joined session and is one use",
                )
                self.owner_stop = {
                    "issued_utc_ns": time.time_ns(),
                    "issued_mono_ns": time.monotonic_ns(),
                    "grant_sha256": self.sha,
                    "process": self.joined,
                }
                owner.stop.write_once(
                    self.root / "frontend.owner-stop.intent.json",
                    canonical(self.owner_stop),
                )
                with self.store.transaction():
                    b = self.grant["boot"]
                    boot.ledger_live(
                        self.store.db,
                        b,
                        self.packet,
                        host.object_bytes(
                            owner.read_packet(self.root / "owner.ready.json")
                        )["observed_mono_ns"],
                    )
                    row = self.store.db.execute(
                        "SELECT * FROM frontend_start"
                    ).fetchone()
                    require(
                        row["state"] == "session-bound"
                        and row["grant_sha"] == self.sha,
                        "normal finish journal changed",
                    )
                    self.store.db.execute(
                        "UPDATE frontend_start SET state='owner-stop-requested'"
                    )
                    self.store.db.execute(
                        "UPDATE authority SET active=0,generation=generation+1"
                    )
                    self.store._event(
                        "frontend-original-owner-stop-requested", self.owner_stop
                    )
                return dict(self.owner_stop)
            except BaseException:
                self.retire("normal original-owner stop request incomplete")
                raise

    def _stopping(self):
        """Retain containment while a known bounded original stop is in flight."""
        require(self.terminal is None and not self.done.is_set(), "frontend is retired")
        checked(self.raw, self.sha)
        now, mono = time.time_ns(), time.monotonic_ns()
        require(
            0 <= now - self.owner_stop["issued_utc_ns"] < 4 * 10**9
            and 0 <= mono - self.owner_stop["issued_mono_ns"] < 4 * 10**9,
            "original-owner finish window expired",
        )
        require(
            now < self.packet["lease"]["expires_ns"]
            and mono < self.packet["lease"]["expires_mono_ns"],
            "original lease ended during finish",
        )
        controller_limits(self.packet)
        require(
            owner.read_packet(self.root / "owner.sealed.json")
            == canonical(self.packet),
            "original owner packet changed during finish",
        )
        db = sqlite3.connect(
            (self.root / "owner.sqlite").resolve().as_uri() + "?mode=ro",
            uri=True,
            timeout=0.05,
        )
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN")
            lease = db.execute("SELECT * FROM lease").fetchone()
            registered = db.execute("SELECT * FROM maintenance_owner").fetchone()
            authority = db.execute("SELECT * FROM authority").fetchone()
            row = db.execute("SELECT * FROM frontend_start").fetchone()
            request = db.execute(
                "SELECT * FROM audit WHERE kind='frontend-original-owner-stop-requested'"
            ).fetchall()
            require(
                len(request) == 1
                and request[0]["payload"] == canonical(self.owner_stop),
                "original finish request audit changed",
            )
            fences = db.execute(
                "SELECT payload FROM audit WHERE seq>? AND kind='authority-fenced'",
                (request[0]["seq"],),
            ).fetchall()
            require(
                len(fences) <= 1
                and all(
                    r["payload"] == canonical({"reason": "VM stop requested"})
                    for r in fences
                ),
                "unexpected authority fence during normal finish",
            )
            require(
                {k: lease[k] for k in host.OWNER_KEYS} == self.packet["lease"]
                and registered["binding"]
                == canonical(
                    {
                        "format": "mcli1-original-owner-v1",
                        "owner_nonce": self.packet["owner_nonce"],
                        "lease": self.packet["lease"],
                        "process": self.packet["owner"],
                    }
                ),
                "original stop owner/lease binding changed",
            )
            require(
                authority["active"] == 0
                and authority["generation"]
                == self.grant["boot"]["generation"] + 1 + len(fences)
                and row["state"] == "owner-stop-requested"
                and row["grant_sha"] == self.sha
                and row["process"] == canonical(self.family.identity),
                "original finish authority/journal changed",
            )
            require(
                lease["state"] in {"armed", "stopping", "stop-command-returned"}
                and registered["state"] in {"watching", "stop-returned"},
                "original finish ledger is unknown",
            )
            returned = (
                lease["state"] == "stop-command-returned"
                and registered["state"] == "stop-returned"
            )
            if not returned:
                require(
                    host.process_identity(self.packet["owner"]["pid"])
                    == self.packet["owner"],
                    "original owner disappeared before stop returned",
                )
                boot.kernel_jobs(self.packet)
        finally:
            db.rollback()
            db.close()
        require(
            not self.family.fault.is_set(), "frontend output fault during normal finish"
        )
        self.family.members()  # All surviving descendants/helpers remain pinned.
        code = self.family.poll()
        require(
            code is None or code == 0, "frontend exited nonzero during normal finish"
        )
        if (self.root / "owner.terminal.json").exists():
            require(
                host.object_bytes(owner.read_packet(self.root / "owner.terminal.json"))[
                    "status"
                ]
                == "original-owner-stop-command-returned-not-poweroff-acceptance",
                "original stop acknowledgement is held",
            )
        return returned and code == 0 and self.family.job.active() == 0

    def observe(self, frame):
        """Join a trusted, bounded read-only VM/session observation to the family.

        The observer must bracket sessionPID with Locked sessionState reads.
        Source review alone does not qualify an actual installed-build observer.
        """
        with self.lock:
            try:
                members = self._live()
                b = self.grant["boot"]
                stamp = frame["observed_mono_ns"]
                require(
                    type(stamp) is int
                    and max(self.started_mono, self.last_observation)
                    < stamp
                    <= time.monotonic_ns()
                    and time.monotonic_ns() - stamp <= 5 * 10**9,
                    "frontend runtime observation is stale/reordered",
                )
                fields = host.machine_fields(frame["machine"])
                state = fields["VMState"]
                expected = boot.transfer.expected_host(b)
                expected["state"] = state
                require(
                    host.machine_profile(frame["machine"]) == expected
                    and fields["hardwareuuid"] == b["target"]["dmi_uuid"]
                    and all(fields.get(k) == v for k, v in boot.BOOT_FIELDS.items()),
                    "frontend runtime target/profile changed",
                )
                host.check_medium(frame["medium"], frame["machine"], b)
                session = frame["session"]
                require(
                    set(session) == {"vm_uuid", "state_before", "state_after", "pid"}
                    and session["vm_uuid"] == b["target"]["vm_uuid"]
                    and type(session["pid"]) is int,
                    "frontend session observation differs",
                )
                if state == "running":
                    require(
                        session["state_before"] == session["state_after"] == "Locked"
                        and session["pid"] > 0,
                        "frontend session PID is not valid under a locked session",
                    )
                    matches = [
                        p
                        for p in members
                        if p["pid"] == session["pid"]
                        and Path(p["image"]).resolve() == frontend.HEADLESS.resolve()
                    ]
                    require(
                        len(matches) == 1
                        and (self.joined is None or self.joined == matches[0]),
                        "VM session PID is outside the exact frontend family or changed",
                    )
                    if self.joined is None:
                        self.joined = matches[0]
                        self.last_observation = stamp
                        receipt = canonical(
                            {
                                "status": "runtime-session-bound-not-guest-ready",
                                "grant_sha256": self.sha,
                                "process": self.joined,
                                "original_lease": self.packet["lease"],
                                "guest_ready": False,
                                "native_settlement_qualified": False,
                            }
                        )
                        self._live()
                        owner.publish(
                            self.root / "frontend.session.receipt.json", receipt
                        )
                        with self.store.transaction():
                            boot.ledger_live(
                                self.store.db,
                                b,
                                self.packet,
                                host.object_bytes(
                                    owner.read_packet(self.root / "owner.ready.json")
                                )["observed_mono_ns"],
                            )
                            self.store.db.execute(
                                "UPDATE frontend_start SET state='session-bound',receipt_sha=? WHERE state='resumed' AND grant_sha=?",
                                (digest(receipt), self.sha),
                            )
                            require(
                                self.store.db.execute("SELECT changes()").fetchone()[0]
                                == 1,
                                "frontend session journal changed",
                            )
                            self.store._event(
                                "frontend-session-bound",
                                {"receipt_sha256": digest(receipt)},
                            )
                else:
                    require(
                        self.joined is None and state in {"poweroff", "starting"},
                        "frontend runtime stopped/changed before original stop acceptance",
                    )
                    require(
                        session["state_before"] == session["state_after"]
                        and session["state_before"] in {"Unlocked", "Locked"}
                        and session["pid"] >= 0,
                        "frontend startup session transition is uncertain",
                    )
                    if session["state_before"] == "Locked":
                        require(
                            any(
                                p["pid"] == session["pid"]
                                and Path(p["image"]).resolve()
                                == frontend.HEADLESS.resolve()
                                for p in members
                            ),
                            "startup session PID is outside frontend family",
                        )
                self._live()
                self.last_observation = stamp
                return {
                    "status": "runtime-session-bound-not-guest-ready"
                    if self.joined
                    else "awaiting-session-identity",
                    "guest_ready": False,
                }
            except BaseException:
                self.retire("runtime observation incomplete or conflicting")
                raise

    def retire(self, reason="controller requested retirement"):
        with self.lock:
            if self.terminal is not None:
                return self.terminal
            self.done.set()
            errors, cleanup = [], None
            if self.family is not None:
                try:
                    cleanup = self.family.retire()
                except Exception as error:  # noqa: BLE001 -- retain unknown cleanup, still fence
                    errors.append("cleanup:" + type(error).__name__)
            # A locked/broken journal must not delay physical containment.
            try:
                self.store.fence(reason)
            except Exception as error:  # noqa: BLE001 -- cleanup already attempted, record journal failure
                errors.append("fence:" + type(error).__name__)
            self.terminal = {
                "status": "frontend-retired-awaiting-independent-stop-review"
                if not errors
                else "frontend-retirement-held",
                "reason": reason,
                "grant_sha256": getattr(self, "sha", None),
                "cleanup": cleanup,
                "errors": errors,
                "original_stop_accepted": False,
                "VM_poweroff_proven": False,
                "native_settlement_qualified": False,
            }
            if hasattr(self, "root"):
                try:
                    owner.publish(
                        self.root / "frontend.terminal.json", canonical(self.terminal)
                    )
                except Exception as error:  # noqa: BLE001 -- terminal publication failure remains held
                    self.terminal["errors"].append("receipt:" + type(error).__name__)
                    self.terminal["status"] = "frontend-retirement-held"
            return self.terminal

    def close(self):
        result = self.retire()
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout=2)
            require(
                not self.thread.is_alive(), "frontend authority watchdog did not retire"
            )
        return result


if __name__ == "__main__":
    print(
        json.dumps(
            {
                "status": "unarmed-direct-frontend-draft",
                "native_calls": 0,
                "grant": draft(),
            },
            indent=2,
            sort_keys=True,
        )
    )
