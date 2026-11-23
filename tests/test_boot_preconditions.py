"""Boot preparation reports only; synthetic VM facts and Python surrogate stops."""

import contextlib
import copy
import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from research.validation import boot_preconditions as boot
from research.validation import maintenance_host as host
from research.validation import owner_process as worker
from research.validation.store import Hold, Store
from research.validation.supervisor import LeaseSupervisor
from research.validation.transfer_commands import canonical, digest
from tests.test_maintenance_host import inventory, receipts
from tests.test_owner_launch import NativeOwnerFixture


def grant_for(root, packet):
    grant = boot.draft(packet["role"])
    grant.update(run_nonce=uuid4().hex, generation=1)
    grant["approval"] = {k: "test:synthetic-only" for k in grant["approval"]}
    grant["target"].update(
        disk_uuid=(
            boot.transfer.EXECUTOR_DISK
            if packet["role"] == "executor"
            else str(uuid4())
        ),
        dmi_uuid=str(uuid4()),
    )
    grant["owner"].update(
        root=str(root),
        launch_sha256=digest((root / "owner.sealed.json").read_bytes()),
        ready_sha256=digest((root / "owner.ready.json").read_bytes()),
        binding_sha256=packet["profile"]["bounded_stop"]["plan"][
            "owner_binding_sha256"
        ],
    )
    grant["caller"] = {"role": "bootstrap", "process": dict(packet["bootstrap"])}
    grant["backup"].update(
        source_disk_uuid=grant["target"]["disk_uuid"],
        disk_uuid=str(uuid4()),
        disk_sha256="a" * 64,
        configuration_sha256="b" * 64,
        nvram_sha256="c" * 64,
    )
    grant["disk_evidence"]["pre_boot_disk_sha256"] = "d" * 64
    now, mono = time.time_ns(), time.monotonic_ns()
    grant["window"] = {
        "issued_utc_ns": now,
        "issued_mono_ns": mono,
        "expires_utc_ns": now + 3 * 10**9,
        "expires_mono_ns": mono + 3 * 10**9,
    }
    return grant, receipts(grant)


def snapshot(grant):
    machine, medium = inventory(grant, state="poweroff")
    machine += (
        "\n".join(
            f"{json.dumps(k)}={json.dumps(v)}" for k, v in boot.BOOT_FIELDS.items()
        ).encode()
        + b"\n"
    )
    return {
        "observed_mono_ns": time.monotonic_ns(),
        "machine": machine,
        "medium": medium,
    }


class PreparedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.store = Store(self.root / "owner.sqlite")
        self.addCleanup(self.store.close)
        nonce = uuid4().hex
        profile = {
            "target_vm_uuid": boot.transfer.SLOTS["guard"][0],
            "lease_expires_utc_ns": time.time_ns() + 60 * 10**9,
        }
        supervisor = LeaseSupervisor(self.store, profile)
        self.processes = {
            role: {
                "pid": pid,
                "created_filetime": 1,
                "image": r"C:\synthetic\python.exe",
            }
            for role, pid in (
                ("owner", 9999991),
                ("controller", 9999992),
                ("bootstrap", os.getpid()),
            )
        }
        with patch.object(
            host.os, "getpid", return_value=self.processes["owner"]["pid"]
        ):
            original = host.RegisteredOwner(
                supervisor, nonce, identity=lambda _: self.processes["owner"]
            )
        binding = json.loads(original.binding)
        plan = worker.stop.draft("guard")
        plan.update(
            owner_nonce=nonce,
            process=self.processes["owner"],
            lease=binding["lease"],
            owner_binding_sha256=digest(original.binding),
            approval={"native_stop": "test:synthetic-only"},
        )
        profile.update(
            vboxmanage=str(worker.stop.VBOX),
            bounded_stop={"plan": plan, "sha256": digest(canonical(plan))},
        )
        self.packet = {
            "format": "mcli1-independent-owner-v1",
            "role": "guard",
            "owner_nonce": nonce,
            "owner_job": "Local\\MCLI1Owner-" + nonce,
            "controller_job": "Local\\MCLI1Controller-" + nonce,
            **self.processes,
            "root": worker.root_identity(self.root),
            "lease": binding["lease"],
            "profile": profile,
            "approval": {"owner_start": "test:synthetic-only"},
            "sources": dict(worker.SOURCE_EPOCH),
        }
        raw = canonical(self.packet)
        (self.root / "owner.sealed.json").write_bytes(raw)
        pulse = self.store.db.execute(
            "SELECT observed_mono_ns FROM maintenance_owner"
        ).fetchone()[0]
        ready = {
            "format": "mcli1-owner-ready-v1",
            "launch_sha256": digest(raw),
            "owner": self.processes["owner"],
            "lease": binding["lease"],
            "owner_binding_sha256": digest(original.binding),
            "stop_plan_sha256": digest(canonical(plan)),
            "controller_job_separate": True,
            "owner_job_retained": True,
            "observed_mono_ns": pulse,
            "VM_start_authorized": False,
        }
        (self.root / "owner.ready.json").write_bytes(canonical(ready))
        self.grant, self.receipts = grant_for(self.root, self.packet)
        self.identities = {v["pid"]: v for v in self.processes.values()}
        self.probes = 0

    def probe(self):
        self.assertFalse(self.store.db.in_transaction)
        self.probes += 1
        return snapshot(self.grant)

    def gate(self, probe=None):
        return boot.BootPreconditions(
            self.store,
            probe or self.probe,
            identity=self.identities.__getitem__,
            jobs=lambda _: None,
        )

    def record(self, gate=None):
        raw = canonical(self.grant)
        return (gate or self.gate()).record(raw, digest(raw), *self.receipts)

    def live(self):
        return boot.owner_live(
            self.store, self.grant, self.identities.__getitem__, lambda _: None
        )[0]

    def test_report_requires_two_stopped_observations_and_never_grants_native_dispatch(
        self,
    ):
        result = self.record()
        self.assertEqual(self.probes, 2)
        self.assertFalse(result["native_dispatch_permit"])
        self.assertFalse(result["VM_started"])
        self.assertEqual(result["provider_start_task_settlement"], "unqualified")
        row = self.store.db.execute("SELECT * FROM boot_preconditions").fetchone()
        self.assertEqual(row["state"], "preconditions-reported")
        self.assertEqual(row["receipt_sha"], digest(canonical(result)))
        self.assertEqual(self.live()["lease"], self.packet["lease"])
        self.store.audit()

    def test_unarmed_preview_prepares_frozen_reviews_without_native_calls(self):
        output = self.root / "review"

        # Production outputs are restricted to .local/validation. Keep this
        # unit fixture in its disposable root without weakening that boundary.
        def new_root(path):
            path.mkdir()
            return path

        with patch.object(boot, "new_root", new_root):
            review = boot.prepare("executor", output)
        self.assertFalse(review["native_dispatch_permit"])
        self.assertEqual(review["native_calls"], 0)
        for name, path in boot.SOURCES.items():
            self.assertEqual((output / name).read_bytes(), path.read_bytes())
        with self.assertRaisesRegex(Hold, "review is unbound"):
            raw = canonical(boot.draft("guard"))
            boot.checked(raw, digest(raw))
        with (
            patch.object(sys, "argv", ["boot_preconditions"]),
            contextlib.redirect_stdout(io.StringIO()) as out,
        ):
            boot.main()
        self.assertFalse(json.loads(out.getvalue())["native_dispatch_permit"])

    def test_wrong_digest_source_or_oversized_packet_refuses_before_probe(self):
        raw = canonical(self.grant)
        with self.assertRaisesRegex(Hold, "digest differs"):
            self.gate().record(raw, "0" * 64, *self.receipts)
        self.grant["sources"]["boot_preconditions.py"] = "0" * 64
        with self.assertRaisesRegex(Hold, "source cohort"):
            self.record()
        large = b" " * 65537
        with self.assertRaises(Hold):
            boot.checked(large, digest(large))
        self.assertEqual(self.probes, 0)

    def test_changed_source_on_disk_refuses_even_with_matching_import_epoch(self):
        drift = self.root / "drift.py"
        drift.write_text("changed source")
        with (
            patch.dict(boot.SOURCES, {"boot_preconditions.py": drift}),
            self.assertRaisesRegex(Hold, "source cohort"),
        ):
            self.record()
        self.assertEqual(self.probes, 0)

    def test_backup_must_be_independent_and_all_hashes_bound(self):
        for path, value in (
            (["backup", "disk_uuid"], self.grant["target"]["disk_uuid"]),
            (["backup", "source_disk_uuid"], str(uuid4())),
            (["backup", "nvram_sha256"], None),
            (["disk_evidence", "pre_boot_disk_sha256"], None),
        ):
            altered = copy.deepcopy(self.grant)
            altered[path[0]][path[1]] = value
            raw = canonical(altered)
            with self.subTest(path=path), self.assertRaises(Hold):
                boot.checked(raw, digest(raw))

    def test_changed_receipt_refuses_before_observation_or_intent(self):
        for n in range(3):
            altered = list(self.receipts)
            altered[n] += b" "
            raw = canonical(self.grant)
            with self.subTest(receipt=n), self.assertRaises(Hold):
                self.gate().record(raw, digest(raw), *altered)
        self.assertEqual(self.probes, 0)
        self.assertFalse((self.root / "boot.preconditions.intent.json").exists())

    def test_missing_or_changed_ready_file_refuses(self):
        path = self.root / "owner.ready.json"
        raw = path.read_bytes()
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.record()
        path.write_bytes(raw + b" ")
        with self.assertRaisesRegex(Hold, "launch/ready bytes"):
            self.record()
        self.assertEqual(self.probes, 0)

    def test_reused_owner_controller_or_caller_pid_refuses(self):
        for role in self.processes:
            pid = self.processes[role]["pid"]
            original = self.identities[pid]
            self.identities[pid] = {**original, "created_filetime": 2}
            with self.subTest(role=role), self.assertRaisesRegex(Hold, "PID identity"):
                self.record()
            self.identities[pid] = original
        self.assertEqual(self.probes, 0)

    def test_wrong_store_or_copied_old_ready_cannot_supply_original_authority(self):
        other = Store(self.root / "other.sqlite")
        self.addCleanup(other.close)
        with self.assertRaisesRegex(Hold, "original owner Store"):
            boot.owner_live(
                other, self.grant, self.identities.__getitem__, lambda _: None
            )
        self.store.db.execute(
            "UPDATE maintenance_owner SET observed_mono_ns=?",
            (time.monotonic_ns() - 6 * 10**9,),
        )
        with self.assertRaisesRegex(Hold, "pulse/lease is stale"):
            self.record()
        self.assertEqual(self.probes, 0)

    def test_original_lease_owner_row_and_generation_are_exact(self):
        for sql, undo in (
            (
                "UPDATE lease SET expires_ns=expires_ns+1",
                "UPDATE lease SET expires_ns=expires_ns-1",
            ),
            ("UPDATE lease SET state='stopping'", "UPDATE lease SET state='armed'"),
            (
                "UPDATE maintenance_owner SET state='stop-returned'",
                "UPDATE maintenance_owner SET state='watching'",
            ),
            ("UPDATE authority SET generation=2", "UPDATE authority SET generation=1"),
            ("UPDATE authority SET active=0", "UPDATE authority SET active=1"),
        ):
            self.store.db.execute(sql)
            with (
                self.subTest(sql=sql),
                self.assertRaisesRegex(Hold, "ledger is fenced"),
            ):
                self.record()
            self.store.db.execute(undo)
        self.assertEqual(self.probes, 0)

    def test_expired_window_or_consumed_stop_reserve_refuses(self):
        original = copy.deepcopy(self.grant["window"])
        for delta, message in ((-20, "window expired"), (50, "stop reserve")):
            self.grant["window"] = {k: v + delta * 10**9 for k, v in original.items()}
            if delta > 0:
                # Keep issuance live; only the end invades the independent stop reserve.
                self.grant["window"] = {
                    k: v + (50 * 10**9 if k.startswith("expires") else 40 * 10**9)
                    for k, v in original.items()
                }
                with (
                    patch.object(
                        boot.time,
                        "time_ns",
                        return_value=original["issued_utc_ns"] + 41 * 10**9,
                    ),
                    patch.object(
                        boot.time,
                        "monotonic_ns",
                        return_value=original["issued_mono_ns"] + 41 * 10**9,
                    ),
                ):
                    self.store.db.execute(
                        "UPDATE maintenance_owner SET observed_mono_ns=?",
                        (time.monotonic_ns(),),
                    )
                    with self.assertRaisesRegex(Hold, message):
                        self.record()
            else:
                with self.assertRaisesRegex(Hold, message):
                    self.record()
        self.assertEqual(self.probes, 0)

    def test_nic_disk_uart_firmware_and_running_state_drift_refuse(self):
        valid = snapshot(self.grant)
        changes = (
            (b'"nic1"="none"', b'"nic1"="nat"'),
            (self.grant["target"]["disk_uuid"].encode(), str(uuid4()).encode()),
            (b'uartmode1="server,', b'uartmode1="client,'),
            (b'"boot2"="none"', b'"boot2"="dvd"'),
            (b'"VMState"="poweroff"', b'"VMState"="running"'),
        )
        for old, new in changes:
            changed = {**valid, "machine": valid["machine"].replace(old, new)}
            with self.subTest(change=old), self.assertRaises(Hold):
                boot.stopped_snapshot(self.grant, changed)
        valid["observed_mono_ns"] -= 6 * 10**9
        with self.assertRaisesRegex(Hold, "observation is stale"):
            boot.stopped_snapshot(self.grant, valid)

    def test_second_observation_drift_fences_and_retains_intent(self):
        def changed():
            result = self.probe()
            if self.probes == 2:
                result["machine"] += b'"name"="changed-between-reads"\n'
            return result

        with self.assertRaisesRegex(Hold, "between observations"):
            self.record(self.gate(changed))
        self.assertEqual(
            self.store.db.execute("SELECT active FROM authority").fetchone()[0], 0
        )
        self.assertEqual(
            self.store.db.execute("SELECT state FROM boot_preconditions").fetchone()[0],
            "intent",
        )
        self.assertFalse((self.root / "boot.preconditions.receipt.json").exists())

    def test_first_observation_failure_fences_original_authority(self):
        def failed():
            raise TimeoutError("test:stopped-state query timed out")

        with self.assertRaisesRegex(TimeoutError, "query timed out"):
            self.record(self.gate(failed))
        self.assertEqual(
            self.store.db.execute("SELECT active FROM authority").fetchone()[0], 0
        )
        self.assertFalse((self.root / "boot.preconditions.receipt.json").exists())

    def test_fence_during_probe_is_seen_by_second_owner_check(self):
        def fenced():
            result = self.probe()
            if self.probes == 2:
                self.store.fence("test:authority-lost-between-reads")
            return result

        with self.assertRaisesRegex(Hold, "ledger is fenced"):
            self.record(self.gate(fenced))
        self.assertFalse((self.root / "boot.preconditions.receipt.json").exists())

    def test_lost_journal_receipt_retains_non_authorizing_file_and_refuses_replay(self):
        event = self.store._event

        def fail(kind, payload):
            if kind == "boot-preconditions-reported":
                raise OSError("test:lost receipt commit")
            return event(kind, payload)

        with (
            patch.object(self.store, "_event", fail),
            self.assertRaisesRegex(OSError, "lost receipt"),
        ):
            self.record()
        receipt = json.loads(
            (self.root / "boot.preconditions.receipt.json").read_bytes()
        )
        self.assertFalse(receipt["native_dispatch_permit"])
        self.assertEqual(
            self.store.db.execute("SELECT state FROM boot_preconditions").fetchone()[0],
            "intent",
        )
        with self.assertRaises(Hold):
            self.record()

    def test_partial_intent_write_fences_even_before_journal_insert(self):
        write = worker.stop.write_once

        def fail(path, raw):
            write(path, raw)
            raise OSError("test:intent flush acknowledgement lost")

        with patch.object(worker.stop, "write_once", fail), self.assertRaises(OSError):
            self.record()
        self.assertTrue((self.root / "boot.preconditions.intent.json").exists())
        self.assertEqual(
            self.store.db.execute("SELECT active FROM authority").fetchone()[0], 0
        )

    def test_retained_files_block_replay_even_after_journal_row_deletion(self):
        self.record()
        self.store.db.execute("DELETE FROM boot_preconditions")
        with self.assertRaises(FileExistsError):
            self.record()
        self.assertEqual(
            self.store.db.execute("SELECT active FROM authority").fetchone()[0], 0
        )

    def test_stop_started_after_report_file_before_commit_refuses(self):
        publish = worker.publish

        def stop_after_publish(path, raw):
            publish(path, raw)
            self.store.db.execute("UPDATE lease SET state='stopping'")

        with (
            patch.object(worker, "publish", stop_after_publish),
            self.assertRaisesRegex(Hold, "ledger is fenced"),
        ):
            self.record()
        self.assertEqual(
            self.store.db.execute("SELECT state FROM boot_preconditions").fetchone()[0],
            "intent",
        )
        self.assertFalse(
            json.loads((self.root / "boot.preconditions.receipt.json").read_bytes())[
                "native_dispatch_permit"
            ]
        )

    def test_owner_pulse_rollback_after_report_file_cannot_commit(self):
        publish = worker.publish

        def rollback_after_publish(path, raw):
            publish(path, raw)
            self.store.db.execute(
                "UPDATE maintenance_owner SET observed_mono_ns=?",
                (self.packet["lease"]["armed_mono_ns"],),
            )

        with (
            patch.object(worker, "publish", rollback_after_publish),
            self.assertRaisesRegex(Hold, "pulse/lease is stale"),
        ):
            self.record()
        self.assertEqual(
            self.store.db.execute("SELECT state FROM boot_preconditions").fetchone()[0],
            "intent",
        )
        self.assertEqual(
            self.store.db.execute("SELECT active FROM authority").fetchone()[0], 0
        )


@unittest.skipUnless(sys.platform == "win32", "Windows native owner/job proof")
class NativeBootTests(NativeOwnerFixture, unittest.TestCase):
    def prepared(self):
        self.pending(seconds=25)
        self.seal()
        packet = json.loads((self.owner.root / "owner.sealed.json").read_bytes())
        self.grant, self.receipts = grant_for(self.owner.root, packet)
        self.store = Store(self.owner.root / "owner.sqlite")
        self.addCleanup(self.store.close)
        return boot.BootPreconditions(self.store, lambda: snapshot(self.grant))

    def record(self, gate):
        raw = canonical(self.grant)
        return gate.record(raw, digest(raw), *self.receipts)

    def test_native_job_and_live_owner_proof_yields_report_only(self):
        gate = self.prepared()
        self.owner.close()
        result = self.record(gate)
        self.assertFalse(result["native_dispatch_permit"])
        self.assertTrue(self.alive(self.owner_identity))
        self.assertFalse((self.owner.root / "surrogate.calls.jsonl").exists())

    def test_probe_failure_triggers_original_owner_surrogate_stop_once(self):
        gate = self.prepared()

        def failed():
            raise TimeoutError("test:startup observation failed")

        gate.probe = failed
        with self.assertRaisesRegex(TimeoutError, "startup observation failed"):
            self.record(gate)
        result = self.terminal()
        self.assertEqual(
            result["status"],
            "original-owner-stop-command-returned-not-poweroff-acceptance",
        )
        calls = (self.owner.root / "surrogate.calls.jsonl").read_text().splitlines()
        self.assertEqual(len(calls), 1)

    def test_missing_ready_cannot_be_replaced_by_live_owner_alone(self):
        gate = self.prepared()
        ready = self.owner.root / "owner.ready.json"
        raw = ready.read_bytes()
        ready.unlink()
        with self.assertRaises(FileNotFoundError):
            self.record(gate)
        ready.write_bytes(raw)
        self.assertFalse((self.owner.root / "boot.preconditions.intent.json").exists())

    def test_controller_job_loss_and_old_ready_cannot_admit_boot(self):
        gate = self.prepared()
        self.controller_job.close()
        self.terminal()
        with self.assertRaises(Hold):
            self.record(gate)
        self.assertFalse((self.owner.root / "boot.preconditions.intent.json").exists())

    def test_original_fence_refuses_while_original_ready_file_remains(self):
        gate = self.prepared()
        self.store.fence("test:original-owner-authority-lost")
        with self.assertRaises(Hold):
            self.record(gate)
        self.terminal()
        self.assertTrue((self.owner.root / "owner.ready.json").exists())
        self.assertFalse((self.owner.root / "boot.preconditions.intent.json").exists())


if __name__ == "__main__":
    unittest.main()
