import base64
import copy
import ctypes
import io
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from ctypes import wintypes
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from research.validation import maintenance_serial as serial
from research.validation import maintenance_serial_worker as worker
from research.validation.store import Hold, Store


def request(seconds=3, send="PING"):
    nonce = uuid4().hex
    return {
        "format": "mcli1-serial-exchange-v1",
        "mode": "local-test",
        "request_id": nonce,
        "target_vm_uuid": None,
        "pipe": "\\\\.\\pipe\\mcli1-serial-test-" + nonce,
        "steps": [{"send": send, "ack": f"MCLI1_ACK_{nonce}_0"}],
        "activation_reference": "test:local-serial-only",
        "worker_sha256": worker.digest(Path(worker.__file__).read_bytes()),
        "expires_utc_ns": time.time_ns() + int(seconds * 10**9),
        "expires_mono_ns": time.monotonic_ns() + int(seconds * 10**9),
    }


class Channel:
    def __init__(self, chunks):
        self.chunks, self.sent = list(chunks), []

    def send(self, raw):
        self.sent.append(raw)

    def read_available(self):
        if not self.chunks:
            raise OSError("synthetic closed channel")
        return self.chunks.pop(0)


class SerialProtocolTests(unittest.TestCase):
    def setUp(self):
        self.request = request()

    def test_complete_request_binds_worker_digest_channel_and_exact_bytes(self):
        raw = worker.encode(self.request)
        self.assertEqual(worker.checked(raw, worker.digest(raw)), self.request)
        with self.assertRaises(worker.Refuse):
            worker.checked(raw + b" ", worker.digest(raw))
        for key, value in [
            ("worker_sha256", "0" * 64),
            ("pipe", r"\\.\pipe\unrelated"),
            ("activation_reference", None),
            ("expires_mono_ns", True),
        ]:
            altered = copy.deepcopy(self.request)
            altered[key] = value
            raw = worker.encode(altered)
            with self.subTest(key=key), self.assertRaises(worker.Refuse):
                worker.checked(raw, worker.digest(raw))

    def test_unarmed_guest_draft_has_no_native_activation(self):
        for role in ("guard", "executor"):
            raw = worker.encode(serial.draft(role))
            with (
                self.subTest(role=role),
                self.assertRaisesRegex(worker.Refuse, "activation"),
            ):
                worker.checked(raw, worker.digest(raw))

    def test_printable_bounded_lines_and_ack_order_cannot_be_changed(self):
        for line in ("one\ntwo", "bad\x00line", "x" * 2048, "café"):
            value = copy.deepcopy(self.request)
            value["steps"][0]["send"] = line
            raw = worker.encode(value)
            with self.subTest(line_length=len(line)), self.assertRaises(worker.Refuse):
                worker.checked(raw, worker.digest(raw))

    def test_console_echo_cannot_acknowledge_and_data_is_hash_bound(self):
        nonce, ack = self.request["request_id"], self.request["steps"][0]["ack"]
        data = b'{"status":"synthetic"}'
        channel = Channel(
            [
                ("echo '" + ack + "'\r\n").encode(),
                f"MCLI1_DATA_{nonce}_0:".encode()
                + base64.b64encode(data)
                + b"\r\n"
                + ack.encode()
                + b"\r\nroot# ",
            ]
        )
        result = worker.exchange(self.request, channel)
        self.assertEqual(channel.sent, [b"PING\r"])
        self.assertEqual(base64.b64decode(result["data_base64"]), data)
        self.assertEqual(result["data_sha256"], worker.digest(data))
        self.assertEqual(result["status"], "serial-exchange-reported-not-accepted")

    def test_duplicate_out_of_order_and_oversized_output_hold_without_replay(self):
        nonce, ack = self.request["request_id"], self.request["steps"][0]["ack"]
        for raw in [
            (ack + "\n" + ack + "\n").encode(),
            f"MCLI1_ACK_{nonce}_1\n".encode(),
            b"x" * (worker.MAX_LINE + 4097),
        ]:
            channel = Channel([raw])
            with self.subTest(size=len(raw)), self.assertRaises(worker.Refuse):
                worker.exchange(self.request, channel)
            self.assertEqual(channel.sent, [b"PING\r"])

    def test_lost_ack_sends_once_and_does_not_retry(self):
        channel = Channel([])
        with self.assertRaises(OSError):
            worker.exchange(self.request, channel)
        self.assertEqual(channel.sent, [b"PING\r"])

    def test_expired_request_never_writes_to_channel(self):
        self.request["expires_mono_ns"] = time.monotonic_ns() - 1
        channel = Channel([])
        with self.assertRaisesRegex(worker.Refuse, "deadline"):
            worker.exchange(self.request, channel)
        self.assertEqual(channel.sent, [])

    def test_durable_intent_survives_reopen_and_rejects_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "serial.sqlite"
            store = Store(path)
            raw = worker.encode(self.request)
            sha = worker.digest(raw)
            proof = serial.persist_intent(store, raw, sha, 1)
            store.close()
            reopened = Store(path)
            try:
                self.assertEqual(proof["request_sha256"], sha)
                self.assertEqual(
                    reopened.db.execute("SELECT state FROM operations").fetchone()[
                        "state"
                    ],
                    "possible-send",
                )
                with self.assertRaises(Hold):
                    serial.persist_intent(reopened, raw, sha, 1)
            finally:
                reopened.close()

    def test_ephemeral_journal_and_default_cli_cannot_activate_transport(self):
        store = Store(":memory:")
        try:
            raw = worker.encode(self.request)
            with self.assertRaises(Hold):
                serial.persist_intent(store, raw, worker.digest(raw), 1)
        finally:
            store.close()
        result = subprocess.run(
            [sys.executable, "-B", str(Path(worker.__file__))],
            capture_output=True,
            timeout=5,
            check=True,
        )
        self.assertEqual(json.loads(result.stdout)["native_calls"], 0)


class PipeServer:
    """Local synthetic peer; no hypervisor or guest is accessed."""

    def __init__(self, name, handler):
        self.name = name
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        definitions = {
            "CreateNamedPipeW": (
                [
                    wintypes.LPCWSTR,
                    wintypes.DWORD,
                    wintypes.DWORD,
                    wintypes.DWORD,
                    wintypes.DWORD,
                    wintypes.DWORD,
                    wintypes.DWORD,
                    ctypes.c_void_p,
                ],
                wintypes.HANDLE,
            ),
            "ConnectNamedPipe": ([wintypes.HANDLE, ctypes.c_void_p], wintypes.BOOL),
            "ReadFile": (
                [
                    wintypes.HANDLE,
                    ctypes.c_void_p,
                    wintypes.DWORD,
                    ctypes.POINTER(wintypes.DWORD),
                    ctypes.c_void_p,
                ],
                wintypes.BOOL,
            ),
            "WriteFile": (
                [
                    wintypes.HANDLE,
                    ctypes.c_void_p,
                    wintypes.DWORD,
                    ctypes.POINTER(wintypes.DWORD),
                    ctypes.c_void_p,
                ],
                wintypes.BOOL,
            ),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        }
        for function, (args, result) in definitions.items():
            api = getattr(self.api, function)
            api.argtypes, api.restype = args, result
        self.handle = self.api.CreateNamedPipeW(
            name, 0x3 | 0x80000, 0x8, 1, 256, 256, 0, None
        )
        if self.handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        self.release, self.connected = threading.Event(), threading.Event()
        self.errors = []

        def serve():
            try:
                if (
                    not self.api.ConnectNamedPipe(self.handle, None)
                    and ctypes.get_last_error() != 535
                ):
                    raise ctypes.WinError(ctypes.get_last_error())
                self.connected.set()
                handler(self)
            except OSError as exc:
                self.errors.append(exc)
            finally:
                self.api.CloseHandle(self.handle)

        self.thread = threading.Thread(target=serve, daemon=True)
        self.thread.start()

    def read(self):
        buf, size = ctypes.create_string_buffer(4096), wintypes.DWORD()
        if not self.api.ReadFile(self.handle, buf, len(buf), ctypes.byref(size), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return buf.raw[: size.value]

    def write(self, raw):
        size = wintypes.DWORD()
        if not self.api.WriteFile(self.handle, raw, len(raw), ctypes.byref(size), None):
            raise ctypes.WinError(ctypes.get_last_error())
        if size.value != len(raw):
            raise OSError("synthetic peer partial write")

    def close(self):
        self.release.set()
        if not self.connected.is_set():
            # Wake a test peer whose client refused before connecting.
            try:
                with io.FileIO(self.name, "r+"):
                    pass
            except OSError:
                pass
        self.thread.join(timeout=3)
        if self.thread.is_alive():
            raise AssertionError("synthetic peer not reaped")


@unittest.skipUnless(sys.platform == "win32", "Windows native serial/job checks")
class NativeSerialTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.store = Store(Path(self.folder.name) / "serial.sqlite")
        self.addCleanup(self.store.close)

    def run_request(self, value, cancelled=None):
        raw = worker.encode(value)
        sha = worker.digest(raw)
        return serial.run_journaled(self.store, raw, sha, 1, cancelled)

    def test_real_local_pipe_receipt_and_durable_uncertainty(self):
        value = request()
        ack = value["steps"][0]["ack"]

        def handle(server):
            self.assertEqual(server.read(), b"PING\r")
            server.write((ack + "\r\n").encode())
            server.release.wait(5)

        peer = PipeServer(value["pipe"], handle)
        self.addCleanup(peer.close)
        result = self.run_request(value)
        self.assertEqual(result["job_active_processes"], 0)
        self.assertEqual(
            self.store.db.execute("SELECT state FROM operations").fetchone()["state"],
            "possible-send",
        )
        with self.assertRaises(Hold):
            self.run_request(value)

    def test_unanswered_pipe_deadline_reaps_worker_and_retains_intent(self):
        value = request(1)
        peer = PipeServer(value["pipe"], lambda s: (s.read(), s.release.wait(5)))
        self.addCleanup(peer.close)
        start = time.monotonic()
        with self.assertRaises(worker.Refuse):
            self.run_request(value)
        self.assertLess(time.monotonic() - start, 4)
        self.assertTrue(peer.connected.is_set())
        self.assertEqual(
            self.store.db.execute("SELECT active FROM authority").fetchone()["active"],
            0,
        )
        self.assertEqual(
            self.store.db.execute("SELECT state FROM operations").fetchone()["state"],
            "possible-send",
        )

    def test_revocation_stops_worker_with_original_deadline_unchanged(self):
        value = request(5)
        cancelled = threading.Event()

        def handle(server):
            server.read()
            cancelled.set()
            server.release.wait(5)

        peer = PipeServer(value["pipe"], handle)
        self.addCleanup(peer.close)
        deadline = value["expires_mono_ns"]
        with self.assertRaisesRegex(worker.Refuse, "revoked"):
            self.run_request(value, cancelled)
        self.assertEqual(value["expires_mono_ns"], deadline)

    def test_failed_assignment_reaps_unstarted_worker_without_channel_io(self):
        value = request()
        with (
            patch.object(
                serial.KillJob,
                "assign",
                side_effect=OSError("synthetic assignment failure"),
            ),
            self.assertRaises(OSError),
        ):
            self.run_request(value)
        self.assertEqual(
            self.store.db.execute("SELECT state FROM operations").fetchone()["state"],
            "possible-send",
        )

    def test_parent_output_limit_reaps_a_faulty_worker(self):
        value = request()
        original = subprocess.Popen
        code = "import sys; sys.stdin.buffer.readline(); sys.stdout.buffer.write(b'x'*(3*1024**2)); sys.stdout.buffer.flush()"

        def faulty(_argv, **kwargs):
            return original([sys.executable, "-I", "-B", "-c", code], **kwargs)

        with (
            patch.object(serial.subprocess, "Popen", side_effect=faulty),
            self.assertRaises(worker.Refuse),
        ):
            self.run_request(value)

    def test_parent_rejects_corrupt_result_digest_and_fences(self):
        value = request()
        original = subprocess.Popen
        code = (
            "import json,sys; r=json.loads(sys.stdin.buffer.readline()); "
            "print(json.dumps({'status':'serial-exchange-reported-not-accepted','request_id':r['request_id'],'acknowledged_steps':[s['ack'] for s in r['steps']],'console_bytes':0,'console_sha256':'0'*64,'data_base64':'cGF5bG9hZA==','data_sha256':'0'*64}))"
        )

        def faulty(_argv, **kwargs):
            return original([sys.executable, "-I", "-B", "-c", code], **kwargs)

        with (
            patch.object(serial.subprocess, "Popen", side_effect=faulty),
            self.assertRaisesRegex(worker.Refuse, "data digest"),
        ):
            self.run_request(value)
        self.assertEqual(
            self.store.db.execute("SELECT active FROM authority").fetchone()["active"],
            0,
        )

    def test_job_termination_cancels_a_kernel_blocked_pipe_write(self):
        value = request(5)
        peer = PipeServer(value["pipe"], lambda s: s.release.wait(5))
        self.addCleanup(peer.close)
        code = "import sys,io; sys.stdin.readline(); p=io.FileIO(sys.argv[1],'r+'); print('WRITE_ENTERED',flush=True); p.write(b'x'*(8*1024**2)); print('WRITE_RETURNED',flush=True)"
        child = subprocess.Popen(
            [sys.executable, "-I", "-B", "-c", code, value["pipe"]],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        job = serial.KillJob()
        try:
            job.assign(child)
            child.stdin.write(b"go\n")
            child.stdin.flush()
            self.assertEqual(child.stdout.readline(), b"WRITE_ENTERED\r\n")
            time.sleep(0.1)
            self.assertIsNone(child.poll())
            job.terminate()
            child.wait(timeout=2)
            self.assertEqual(job.active(), 0)
            self.assertNotIn(b"WRITE_RETURNED", child.stdout.read())
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=2)
            job.close()
            for pipe in (child.stdin, child.stdout, child.stderr):
                pipe.close()

    def test_job_kills_worker_when_parent_process_dies(self):
        ready = Path(self.folder.name) / "parent-ready.json"
        root = Path(serial.__file__).resolve().parents[2]
        code = (
            "import json,pathlib,subprocess,sys,time; "
            f"sys.path.insert(0,{str(root)!r}); "
            "from research.validation.maintenance_serial import KillJob; "
            "child=subprocess.Popen([sys.executable,'-B','-c','import sys,time; sys.stdin.readline(); time.sleep(30)'],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
            "job=KillJob(); job.assign(child); child.stdin.write(b'go\\n'); child.stdin.flush(); "
            f"pathlib.Path({str(ready)!r}).write_text(json.dumps({{'worker_pid':child.pid}})); "
            "time.sleep(30)"
        )
        parent = subprocess.Popen(
            [sys.executable, "-B", "-c", code],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.OpenProcess.argtypes, api.OpenProcess.restype = (
            [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD],
            wintypes.HANDLE,
        )
        api.WaitForSingleObject.argtypes, api.WaitForSingleObject.restype = (
            [wintypes.HANDLE, wintypes.DWORD],
            wintypes.DWORD,
        )
        api.TerminateProcess.argtypes, api.TerminateProcess.restype = (
            [wintypes.HANDLE, wintypes.UINT],
            wintypes.BOOL,
        )
        api.CloseHandle.argtypes, api.CloseHandle.restype = (
            [wintypes.HANDLE],
            wintypes.BOOL,
        )
        handle = None
        try:
            deadline = time.monotonic() + 3
            while (
                not ready.exists()
                and parent.poll() is None
                and time.monotonic() < deadline
            ):
                time.sleep(0.01)
            self.assertTrue(ready.exists())
            pid = json.loads(ready.read_bytes())["worker_pid"]
            handle = api.OpenProcess(0x100000 | 0x1000 | 0x1, False, pid)
            self.assertTrue(handle)
            self.assertEqual(api.WaitForSingleObject(handle, 0), 258)
            parent.kill()
            parent.wait(timeout=2)
            self.assertEqual(api.WaitForSingleObject(handle, 2000), 0)
        finally:
            if parent.poll() is None:
                parent.kill()
                parent.wait(timeout=2)
            if handle:
                if api.WaitForSingleObject(handle, 0) == 258:
                    api.TerminateProcess(handle, 2)
                    api.WaitForSingleObject(handle, 2000)
                api.CloseHandle(handle)
            parent.stderr.close()

    def test_worker_requires_its_exact_configured_job(self):
        value = request()
        with self.assertRaisesRegex(worker.Refuse, "no bound job"):
            worker.verify_job(value)
        job = serial.KillJob("Local\\MCLI1Serial-" + value["request_id"])
        try:
            with self.assertRaisesRegex(worker.Refuse, "outside its bound job"):
                worker.verify_job(value)
            with self.assertRaisesRegex(worker.Refuse, "already exists"):
                serial.KillJob("Local\\MCLI1Serial-" + value["request_id"])
        finally:
            job.close()


if __name__ == "__main__":
    unittest.main()
