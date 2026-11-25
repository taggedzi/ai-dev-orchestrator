"""Decision 0006 conformance; native activation is never used by these tests."""

import shutil
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from research.validation import offline_startup as offline
from research.validation import startup_qualification as q
from research.validation.store import Hold
from research.validation.transfer_commands import canonical, digest


class OfflineFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / ".local/validation").mkdir(parents=True)
        self.ledger = self.root / "admissions.sqlite"
        self.inputs = {
            name: {"path": str(self.root / (name + ".json")), "sha256": digest(b"{}")}
            for name in ("backup", "profile", "preservation")
        }
        for name in self.inputs:
            (self.root / (name + ".json")).write_bytes(b"{}")
        self.addCleanup(patch.stopall)
        patch.object(offline, "ROOT", self.root).start()
        patch.object(offline, "LEDGER", self.ledger).start()
        patch.object(offline, "fixed_inputs", return_value=self.inputs).start()
        patch.object(q.start.backup, "safe", lambda path: Path(path).resolve()).start()
        self.review = offline.draft()
        self.raw = canonical(self.review)
        self.sha = digest(self.raw)
        self.approval = {
            "format": offline.APPROVAL_FORMAT,
            "review_sha256": self.sha,
            "reference": "test:Python-only-offline",
            "approved_utc_ns": time.time_ns(),
        }
        self.approval_raw = canonical(self.approval)

    def write_review(self):
        self.raw = canonical(self.review)
        self.sha = digest(self.raw)
        self.approval["review_sha256"] = self.sha
        self.approval_raw = canonical(self.approval)


class ReviewTests(OfflineFixture):
    def test_prepare_has_no_process_job_lease_or_native_call(self):
        output = self.root / "review"
        output.mkdir()
        with (
            patch.object(q, "new_root", return_value=output),
            patch.object(
                q.launch, "PendingOwner", side_effect=AssertionError("allocated owner")
            ),
            patch.object(
                q.launch,
                "SuspendedChild",
                side_effect=AssertionError("allocated process"),
            ),
            patch.object(
                q.start.frontend,
                "ControllerJob",
                side_effect=AssertionError("allocated job"),
            ),
            patch.object(
                q, "preactivation_probe", side_effect=AssertionError("native query")
            ),
        ):
            result = offline.prepare(output)
        self.assertEqual(result["native_calls"], 0)
        artifact = q.start.host.object_bytes((output / "review.json").read_bytes())
        self.assertNotIn("original_lease", artifact)
        self.assertEqual(artifact["leases_allocated"], 0)
        self.assertFalse(self.ledger.exists())

    def test_days_of_human_delay_do_not_allocate_or_renew_a_lease(self):
        self.review["created_utc_ns"] -= 3 * 86400 * 10**9
        self.write_review()
        checked, _ = offline.approved(self.raw, self.sha, self.approval_raw)
        self.assertEqual(checked["policy"]["original_lease_ns"], 600 * 10**9)
        self.assertNotIn("original_lease", checked)
        self.assertFalse(self.ledger.exists())

    def test_changed_policy_target_output_or_source_is_not_the_reviewed_action(self):
        changes = (
            {"target_vm_uuid": "foreign"},
            {"activation_output_relative": ".local/validation/other"},
            {"policy": {**self.review["policy"], "original_lease_ns": 601 * 10**9}},
            {"policy": {**self.review["policy"], "VM_boots": True}},
            {"sources": {}},
            {"inputs": {}},
        )
        for change in changes:
            raw = canonical({**self.review, **change})
            approval = canonical({**self.approval, "review_sha256": digest(raw)})
            with self.subTest(change=change), self.assertRaises(Hold):
                offline.approved(raw, digest(raw), approval)

    def test_preparation_or_old_live_approval_cannot_authorize_static_activation(self):
        for kind in (
            "decision-0006-preparation",
            "mcli1-one-guard-startup-approval-v1",
        ):
            with self.subTest(kind=kind), self.assertRaises(Hold):
                offline.approved(
                    self.raw, self.sha, canonical({**self.approval, "format": kind})
                )
        with (
            patch.object(q, "fixed_inputs", return_value=self.inputs),
            self.assertRaises(Hold),
        ):
            q.approved_review(self.raw, self.sha, self.approval_raw)

    def test_foreign_digest_future_approval_or_extra_approval_fields_refuse(self):
        for changes in (
            {"review_sha256": "0" * 64},
            {"approved_utc_ns": True},
            {"approved_utc_ns": time.time_ns() + 86400 * 10**9},
            {"extra": "permission"},
        ):
            with self.subTest(changes=changes), self.assertRaises(Hold):
                offline.approved(
                    self.raw, self.sha, canonical({**self.approval, **changes})
                )

    def test_missing_native_approval_cli_never_constructs_runtime(self):
        path = self.root / "review.json"
        path.write_bytes(self.raw)
        with (
            patch.object(
                sys,
                "argv",
                ["offline", "activate", "--review", str(path), "--sha256", self.sha],
            ),
            patch.object(offline, "activate") as activate,
            self.assertRaises(Hold),
        ):
            offline.main()
        activate.assert_not_called()

    def test_readonly_preflight_never_creates_admission_owner_or_lease(self):
        output = self.root / "preflight"
        output.mkdir()
        inputs = SimpleNamespace(
            close=Mock(),
            ready=lambda: {
                "controller": {"pid": 1},
                "VM_boots": 0,
                "leases_allocated": 0,
            },
        )
        with (
            patch.object(q, "new_root", return_value=output),
            patch.object(q, "preactivation_probe") as probe,
            patch.object(offline, "PreparedInputs", return_value=inputs),
            patch.object(
                offline, "Admissions", side_effect=AssertionError("consumed admission")
            ),
            patch.object(
                q.launch, "PendingOwner", side_effect=AssertionError("created owner")
            ),
        ):
            result = offline.preflight(self.raw, self.sha, output)
        self.assertEqual(probe.call_count, 2)
        inputs.close.assert_called_once()
        self.assertEqual(result["VM_boots"], 0)
        self.assertFalse(result["native_boot_authorized"])


class AdmissionTests(OfflineFixture):
    def consume(self, db):
        db.consume(self.review, self.sha, digest(self.approval_raw))

    def test_consumption_survives_reopen_and_alternate_output_cannot_replay(self):
        with closing(offline.Admissions()) as db:
            self.consume(db)
        with closing(offline.Admissions(create=False)) as db:
            with self.assertRaisesRegex(Hold, "consumed"):
                self.consume(db)
            row = db.row(self.review["review_id"])
            self.assertEqual(row["output"], self.review["activation_output_relative"])
            self.assertEqual(row["active"], 1)

    def test_competing_consumers_have_one_winner(self):
        with closing(offline.Admissions()):
            pass

        def consume():
            try:
                with closing(offline.Admissions(create=False)) as db:
                    self.consume(db)
                return True
            except (Hold, sqlite3.Error):
                return False

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _n: consume(), range(2)))
        self.assertEqual(sum(results), 1)

    def test_target_reservation_blocks_a_second_distinct_approved_artifact(self):
        with closing(offline.Admissions()) as db:
            self.consume(db)
            other = offline.draft()
            with self.assertRaises(sqlite3.IntegrityError):
                db.consume(other, digest(canonical(other)), "b" * 64)

    def test_preexisting_revocation_prevents_consumption(self):
        with closing(offline.Admissions()) as db:
            db.revoke(self.review, self.sha)
            with self.assertRaisesRegex(Hold, "revoked"):
                self.consume(db)

    def test_revocation_before_arm_prevents_owner_activation(self):
        with closing(offline.Admissions()) as db:
            self.consume(db)
            db.constructed(self.review, self.sha, digest(self.approval_raw), "b" * 64)
            db.revoke(self.review, self.sha)
            with (
                self.assertRaisesRegex(Hold, "revoked"),
                db.arm(self.review, self.sha, digest(self.approval_raw)),
            ):
                self.fail("entered owner activation after revocation")

    def test_arm_then_revocation_keeps_single_binding_and_fences_consent(self):
        with closing(offline.Admissions()) as db:
            self.consume(db)
            db.constructed(self.review, self.sha, digest(self.approval_raw), "b" * 64)
            with db.arm(self.review, self.sha, digest(self.approval_raw)):
                db.input_ready(self.review["review_id"], "c" * 64)
            db.revoke(self.review, self.sha)
            with self.assertRaises(Hold):
                db.live(self.review, self.sha, digest(self.approval_raw))
            self.assertEqual(db.row(self.review["review_id"])["binding_sha"], "b" * 64)

    def test_lost_consumption_commit_ack_never_allows_a_second_session(self):
        with closing(offline.Admissions()) as db:
            connection = db.db

            class LostAck:
                def execute(self, sql, *args):
                    result = connection.execute(sql, *args)
                    if sql == "COMMIT":
                        raise OSError("lost commit acknowledgement")
                    return result

                @property
                def in_transaction(self):
                    return connection.in_transaction

                def close(self):
                    connection.close()

            db.db = LostAck()
            with self.assertRaises(OSError):
                self.consume(db)
        with closing(offline.Admissions(create=False)) as db, self.assertRaises(Hold):
            self.consume(db)

    def test_settlement_releases_target_but_never_the_consumed_artifact(self):
        with closing(offline.Admissions()) as db:
            self.consume(db)
            db.finish(self.review["review_id"], settled=True)
            with self.assertRaises(Hold):
                self.consume(db)
            other = offline.draft()
            db.consume(other, digest(canonical(other)), "b" * 64)

    def test_known_unarmed_failure_can_release_target_without_reusing_approval(self):
        with closing(offline.Admissions()) as db:
            self.consume(db)
            db.finish(self.review["review_id"], settled=False, release_unarmed=True)
            self.assertEqual(db.row(self.review["review_id"])["state"], "held")
            with self.assertRaises(Hold):
                self.consume(db)

    def test_lost_arm_commit_ack_preserves_one_consumed_armed_binding(self):
        with closing(offline.Admissions()) as db:
            self.consume(db)
            db.constructed(self.review, self.sha, digest(self.approval_raw), "b" * 64)
            connection = db.db

            class LostAck:
                def execute(self, sql, *args):
                    value = connection.execute(sql, *args)
                    if sql == "COMMIT":
                        raise OSError("lost arm acknowledgement")
                    return value

                def __getattr__(self, key):
                    return getattr(connection, key)

            db.db = LostAck()
            with (
                self.assertRaises(OSError),
                db.arm(self.review, self.sha, digest(self.approval_raw)),
            ):
                db.input_ready(self.review["review_id"], "c" * 64)
        with closing(offline.Admissions(create=False)) as db:
            row = db.row(self.review["review_id"])
            self.assertEqual(
                (row["state"], row["input_sha"], row["active"]), ("armed", "c" * 64, 1)
            )
            with self.assertRaises(Hold):
                self.consume(db)

    def test_post_arm_revocation_fences_the_actual_existing_store_without_vm_command(
        self,
    ):
        output = self.root / self.review["activation_output_relative"] / "owner"
        output.mkdir(parents=True)
        with closing(q.Store(output / "owner.sqlite")) as store:
            self.assertEqual(
                store.db.execute("SELECT active FROM authority").fetchone()[0], 1
            )
        with closing(offline.Admissions()) as db:
            self.consume(db)
            db.constructed(self.review, self.sha, digest(self.approval_raw), "b" * 64)
            with db.arm(self.review, self.sha, digest(self.approval_raw)):
                db.input_ready(self.review["review_id"], "c" * 64)
        result = offline.revoke(self.raw, self.sha)
        self.assertEqual(result["native_commands"], 0)
        with closing(q.Store(output / "owner.sqlite")) as store:
            self.assertEqual(
                store.db.execute("SELECT active FROM authority").fetchone()[0], 0
            )


class UnarmedActivationTests(OfflineFixture):
    def setUp(self):
        super().setUp()
        self.calls = []

        def new_root(path):
            path = Path(path)
            path.mkdir(exist_ok=False)
            return path

        patch.object(q, "new_root", new_root).start()
        self.runtime = SimpleNamespace(
            job=Mock(side_effect=AssertionError("allocated job")),
            controller=Mock(side_effect=AssertionError("allocated controller")),
            owner=Mock(side_effect=AssertionError("allocated owner")),
        )

    def test_failed_readonly_preflight_is_consumed_before_any_process_or_lease(self):
        def preflight(_root, _review):
            with closing(offline.Admissions(create=False)) as db:
                self.assertEqual(db.row(self.review["review_id"])["state"], "consumed")
            raise Hold("read-only preflight failed")

        with (
            patch.object(q, "preactivation_probe", preflight),
            self.assertRaisesRegex(Hold, "preflight failed"),
        ):
            offline.activate(
                self.raw, self.sha, self.approval_raw, runtime=self.runtime
            )
        self.runtime.job.assert_not_called()
        self.runtime.owner.assert_not_called()
        with closing(offline.Admissions(create=False)) as db:
            row = db.row(self.review["review_id"])
            self.assertEqual((row["state"], row["active"]), ("held", 0))
        with self.assertRaisesRegex(Hold, "consumed"):
            offline.activate(
                self.raw, self.sha, self.approval_raw, runtime=self.runtime
            )

    def test_output_collision_is_consumed_and_existing_artifacts_are_untouched(self):
        output = self.root / self.review["activation_output_relative"]
        output.mkdir()
        marker = output / "existing"
        marker.write_bytes(b"keep")
        with self.assertRaises(FileExistsError):
            offline.activate(
                self.raw, self.sha, self.approval_raw, runtime=self.runtime
            )
        self.assertEqual(marker.read_bytes(), b"keep")
        self.assertFalse((output / "qualification.terminal.json").exists())
        self.runtime.job.assert_not_called()

    def test_revocation_during_preflight_prevents_process_allocation(self):
        def preflight(_root, _review):
            with closing(offline.Admissions(create=False)) as db:
                db.revoke(self.review, self.sha)

        with (
            patch.object(q, "preactivation_probe", preflight),
            self.assertRaisesRegex(Hold, "revoked"),
        ):
            offline.activate(
                self.raw, self.sha, self.approval_raw, runtime=self.runtime
            )
        self.runtime.job.assert_not_called()


class BindingTests(OfflineFixture):
    def pending(self, seconds=600):
        now, mono = time.time_ns(), time.monotonic_ns()
        lease = {
            "armed_ns": now,
            "armed_mono_ns": mono,
            "expires_ns": now + seconds * 10**9,
            "expires_mono_ns": mono + seconds * 10**9,
            "target": q.target_uuid(),
        }
        return SimpleNamespace(
            lease=lease,
            proposal={"lease": lease},
            controller={"pid": 1},
            bootstrap={"pid": 2},
            owner={"pid": 3},
        )

    def test_runtime_lease_is_constructed_after_human_delay_and_never_expanded(self):
        self.review["created_utc_ns"] -= 86400 * 10**9
        before = time.time_ns()
        pending = self.pending()
        bound = offline.binding_for(
            self.review, self.sha, digest(self.approval_raw), pending
        )
        self.assertGreaterEqual(bound["original_lease"]["armed_ns"], before)
        self.assertEqual(
            bound["original_lease"]["expires_ns"] - bound["original_lease"]["armed_ns"],
            600 * 10**9,
        )
        self.assertEqual(pending.lease, bound["original_lease"])

    def test_expired_expanded_or_foreign_lease_is_refused_before_owner_arm(self):
        for pending in (self.pending(seconds=601), self.pending(seconds=0)):
            with self.assertRaises(Hold):
                offline.binding_for(
                    self.review, self.sha, digest(self.approval_raw), pending
                )
        pending = self.pending()
        pending.lease["target"] = "foreign"
        with self.assertRaises(Hold):
            offline.binding_for(
                self.review, self.sha, digest(self.approval_raw), pending
            )

    def test_only_the_one_exact_armed_runtime_binding_is_accepted(self):
        bound = offline.binding_for(
            self.review, self.sha, digest(self.approval_raw), self.pending()
        )
        root = self.root / self.review["activation_output_relative"]
        root.mkdir()
        (root / "static.review.json").write_bytes(self.raw)
        with closing(offline.Admissions()) as db:
            db.consume(self.review, self.sha, digest(self.approval_raw))
            db.constructed(
                self.review,
                self.sha,
                digest(self.approval_raw),
                digest(canonical(bound)),
            )
            with db.arm(self.review, self.sha, digest(self.approval_raw)):
                db.input_ready(self.review["review_id"], "d" * 64)
            with (
                patch.object(
                    q.start.host, "process_identity", lambda pid: {"pid": pid}
                ),
                patch.object(offline.os, "getpid", return_value=1),
            ):
                raw = canonical(bound)
                self.assertEqual(
                    offline.checked_binding(raw, digest(raw), self.approval_raw)[0],
                    bound,
                )
                for change in (
                    {"case": "controller-loss"},
                    {"controller": {"pid": 999}},
                    {"native_boot_authorized": True},
                    {"sources": {}},
                ):
                    changed = {**bound, **change}
                    raw = canonical(changed)
                    db.db.execute(
                        "UPDATE admissions SET binding_sha=? WHERE review_id=?",
                        (digest(raw), self.review["review_id"]),
                    )
                    with self.subTest(change=change), self.assertRaises(Hold):
                        offline.checked_binding(raw, digest(raw), self.approval_raw)


@unittest.skipUnless(sys.platform == "win32", "Windows file sharing required")
class LockHandoffTests(OfflineFixture):
    def test_same_locked_handles_survive_preparation_and_are_released_at_gate(self):
        path = self.root / "original.bin"
        path.write_bytes(b"locked original")
        locks = offline.PreparedInputs.__new__(offline.PreparedInputs)
        locks.stack, locks.absent, locks.files = ExitStack(), [], []
        self.addCleanup(locks.close)
        locks.used, locks.binding, locks.values, locks.profile = (
            False,
            {},
            {"backup": b"backup"},
            {"profile": "exact"},
        )
        locks.hold(
            path,
            {
                "state": "file",
                "bytes": path.stat().st_size,
                "sha256": digest(path.read_bytes()),
            },
        )
        with self.assertRaises(OSError), path.open("wb"):
            pass
        grant = {"boot": {"role": "guard", "backup": {}}}
        self.assertIs(locks.use(grant, b"backup", locks.profile), locks)
        with self.assertRaises(OSError), path.open("wb"):
            pass
        with self.assertRaises(Hold):
            locks.use(grant, b"backup", locks.profile)
        locks.close()
        path.write_bytes(b"released only after final gate")

    def test_changed_profile_or_backup_cannot_borrow_prepared_handles(self):
        locks = offline.PreparedInputs.__new__(offline.PreparedInputs)
        locks.used, locks.binding, locks.values, locks.profile = (
            False,
            {},
            {"backup": b"backup"},
            {"profile": "exact"},
        )
        locks.check = Mock()
        for backup, profile in ((b"foreign", locks.profile), (b"backup", {})):
            with self.assertRaises(Hold):
                locks.use({"boot": {"role": "guard", "backup": {}}}, backup, profile)
        locks.check.assert_not_called()


@unittest.skipUnless(sys.platform == "win32", "Windows process/job binding required")
class NativeBindingTests(unittest.TestCase):
    """Whole binder with real read locks/jobs and Python-only runtime/stop."""

    artifact_root = None

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            prefix="offline-python-", dir=offline.DIRECTORY
        )
        self.addCleanup(self.temp.cleanup)
        self.ledger = Path(self.temp.name) / "admissions.sqlite"
        self.run = None
        self.addCleanup(self.collect_and_cleanup)

    def collect_and_cleanup(self):
        if self.run is not None and self.run.exists():
            if self.artifact_root is not None:
                destination = Path(self.artifact_root) / self._testMethodName
                destination.mkdir(parents=True)
                shutil.copytree(self.run, destination / "run")
                shutil.copytree(Path(self.temp.name), destination / "admission")
            resolved = self.run.resolve()
            self.assertEqual(resolved.parent, offline.DIRECTORY.resolve())
            self.assertTrue(resolved.name.startswith("offline-guard-run-"))
            shutil.rmtree(resolved)

    def run_case(
        self,
        case,
        *,
        revoke_before_owner=False,
        lose_seal_ack=False,
        revoke_after_arm=False,
        drift_metadata=False,
    ):
        from tests.fixtures.offline_startup_controller import python_surrogates

        fixtures = Path(__file__).parent / "fixtures"
        provisional_id = uuid4().hex
        provisional_root = offline.ROOT / offline.run_relative(provisional_id)
        original_child = q.launch.SuspendedChild
        test = self

        class Runtime(offline.NativeRuntime):
            @staticmethod
            def controller(root, sha, job):
                if revoke_after_arm:
                    (root / "test.pause-before-native").write_bytes(
                        b"Python test barrier only"
                    )
                return original_child(
                    [
                        "-I",
                        "-B",
                        str(fixtures / "offline_startup_controller.py"),
                        str(root),
                        sha,
                        str(test.ledger),
                    ],
                    job,
                )

            @staticmethod
            def owner(root, ident, controller):
                if revoke_before_owner:
                    with closing(offline.Admissions(create=False)) as db:
                        db.revoke(test.review, digest(canonical(test.review)))

                def owner_child(args, job):
                    assert (
                        args[:3] == ["-I", "-B", "-c"]
                        and "owner_process import worker_main" in args[3]
                    )
                    prelude = f"import runpy;runpy.run_path({str(fixtures / 'owner_surrogate_child.py')!r})['install_surrogate']({str(root / 'owner')!r},'success')\n"
                    return original_child([*args[:3], prelude + args[3]], job)

                with patch.object(q.launch, "SuspendedChild", owner_child):
                    pending = q.launch.PendingOwner(
                        root / "owner",
                        "guard",
                        ident,
                        q.start.host.process_identity(controller.pid),
                        time.time_ns() + 30 * 10**9,
                        "test:offline-Python-only-owner",
                    )
                if lose_seal_ack:
                    original_seal = pending.seal

                    def lost_seal(*args):
                        original_seal(*args)
                        raise Hold("test-only lost original owner seal acknowledgement")

                    pending.seal = lost_seal
                return pending

        with python_surrogates(provisional_root, self.ledger):
            self.review = offline.draft(case)
            self.review["review_id"] = provisional_id
            self.review["activation_output_relative"] = offline.run_relative(
                provisional_id
            )
            self.review["created_utc_ns"] -= 86400 * 10**9
            self.run = provisional_root
            raw = canonical(self.review)
            approval = canonical(
                {
                    "format": offline.APPROVAL_FORMAT,
                    "review_sha256": digest(raw),
                    "reference": "test:whole-offline-Python-only",
                    "approved_utc_ns": time.time_ns(),
                }
            )
            stop = threading.Event()
            errors = []

            def revoke_when_armed():
                while not stop.wait(0.01):
                    if (self.run / "test.armed-barrier.json").exists():
                        try:
                            offline.revoke(raw, digest(raw))
                        except Exception as error:  # noqa: BLE001 -- report the test thread's failed revocation
                            errors.append(error)
                        return

            thread = (
                threading.Thread(target=revoke_when_armed) if revoke_after_arm else None
            )
            if thread is not None:
                thread.start()
            try:
                if drift_metadata:
                    q.start.backup.source_paths("guard")["configuration"].write_bytes(
                        b"test-only drift of frozen scratch metadata"
                    )
                result = offline.activate(raw, digest(raw), approval, runtime=Runtime())
            finally:
                stop.set()
                if thread is not None:
                    thread.join(timeout=8)
                    self.assertFalse(thread.is_alive())
                    self.assertEqual(errors, [])
        return result

    def test_real_python_binding_starts_lease_after_preparation_and_stops_once(self):
        result = self.run_case("normal")
        self.assertEqual(
            result["status"], "one-native-start-session-and-normal-stop-measured"
        )
        ready = q.start.host.object_bytes(
            (self.run / "preparation.ready.json").read_bytes()
        )
        bound = q.start.host.object_bytes((self.run / "review.json").read_bytes())
        self.assertLess(
            ready["prepared_mono_ns"], bound["original_lease"]["armed_mono_ns"]
        )
        self.assertLessEqual(
            bound["original_lease"]["expires_ns"] - bound["original_lease"]["armed_ns"],
            600 * 10**9,
        )
        calls = (self.run / "owner/surrogate.calls.jsonl").read_text().splitlines()
        self.assertEqual(len(calls), 1)
        self.assertFalse(
            q.start.host.object_bytes(calls[0].encode())["actual_VM_command"]
        )
        with closing(offline.Admissions(self.ledger, create=False)) as db:
            self.assertEqual(
                (
                    db.row(self.review["review_id"])["state"],
                    db.row(self.review["review_id"])["active"],
                ),
                ("finished", 0),
            )
        self.assertTrue(q.process_retired(bound["controller"]))
        self.assertTrue(q.process_retired(bound["owner"]))

    def test_frozen_scratch_metadata_drift_still_refuses_before_owner_activation(self):
        with self.assertRaisesRegex(Hold, "current configuration/firmware changed"):
            self.run_case("normal", drift_metadata=True)
        self.assertFalse((self.run / "owner.activation.intent.json").exists())
        self.assertFalse((self.run / "owner/frontend.start.intent.json").exists())
        self.assertFalse((self.run / "owner/surrogate.calls.jsonl").exists())

    def test_real_python_controller_loss_keeps_stop_held_and_target_reserved(self):
        result = self.run_case("controller-loss")
        self.assertTrue(result["controller_loss_case_measured"])
        self.assertFalse(result["original_stop_accepted"])
        self.assertFalse(result["native_settlement_qualified"])
        with closing(offline.Admissions(self.ledger, create=False)) as db:
            row = db.row(self.review["review_id"])
            self.assertEqual((row["state"], row["active"]), ("held", 1))

    def test_real_python_revocation_during_binding_never_arms_owner_or_frontend(self):
        with self.assertRaises(Hold):
            self.run_case("normal", revoke_before_owner=True)
        self.assertFalse((self.run / "owner.activation.intent.json").exists())
        self.assertFalse((self.run / "owner/frontend.start.intent.json").exists())
        self.assertFalse((self.run / "owner/surrogate.calls.jsonl").exists())
        with closing(offline.Admissions(self.ledger, create=False)) as db:
            self.assertEqual(db.row(self.review["review_id"])["revoked"], 1)

    def test_real_python_lost_owner_seal_ack_holds_and_never_reconstructs_session(self):
        with self.assertRaisesRegex(Hold, "lost original owner seal"):
            self.run_case("normal", lose_seal_ack=True)
        self.assertFalse((self.run / "owner/frontend.start.intent.json").exists())
        calls = self.run / "owner/surrogate.calls.jsonl"
        # Readiness was never acknowledged. Zero or one original stop may have
        # happened; neither is accepted or replaced after this lost result.
        self.assertLessEqual(
            len(calls.read_text().splitlines()) if calls.exists() else 0, 1
        )
        terminal = q.start.host.object_bytes(
            (self.run / "qualification.terminal.json").read_bytes()
        )
        self.assertFalse(terminal["native_settlement_qualified"])
        with closing(offline.Admissions(self.ledger, create=False)) as db:
            self.assertEqual(
                (
                    db.row(self.review["review_id"])["state"],
                    db.row(self.review["review_id"])["active"],
                ),
                ("held", 1),
            )

    def test_real_python_post_arm_revocation_contains_worker_and_original_owner_stops_once(
        self,
    ):
        with self.assertRaises(Hold):
            self.run_case("normal", revoke_after_arm=True)
        self.assertFalse((self.run / "owner/frontend.start.intent.json").exists())
        self.assertEqual(
            len((self.run / "owner/surrogate.calls.jsonl").read_text().splitlines()), 1
        )
        with closing(offline.Admissions(self.ledger, create=False)) as db:
            self.assertEqual(db.row(self.review["review_id"])["revoked"], 1)
