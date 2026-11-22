"""Standalone serial exchange primitive. Default CLI previews without I/O.

Internal --worker requires a complete hash-bound request on stdin. No login,
password, VM configuration, command generation or automatic replay is provided.
"""

import argparse
import base64
import hashlib
import io
import json
import re
import sys
import time
from pathlib import Path

MAX_REQUEST = 256 * 1024
MAX_CONSOLE = 2 * 1024**2
MAX_DATA = 1024**2
MAX_LINE = 8192
TARGETS = (
    "74129e9c-5a65-44fa-9d35-79d458dc4704",
    "0eceb37e-f216-45ed-817c-7cf2fca3a32a",
)


class Refuse(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Refuse(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def checked(raw, external_sha):
    require(
        len(raw) <= MAX_REQUEST and digest(raw) == external_sha,
        "serial request digest changed",
    )
    request = json.loads(raw)
    require(
        set(request)
        == {
            "format",
            "mode",
            "request_id",
            "target_vm_uuid",
            "pipe",
            "steps",
            "activation_reference",
            "worker_sha256",
            "expires_utc_ns",
            "expires_mono_ns",
        },
        "serial request fields changed",
    )
    require(request["format"] == "mcli1-serial-exchange-v1", "serial format changed")
    require(
        request["worker_sha256"] == digest(Path(__file__).read_bytes()),
        "serial worker changed",
    )
    require(
        isinstance(request["activation_reference"], str)
        and re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", request["activation_reference"]
        ),
        "serial activation is unbound",
    )
    nonce = request["request_id"]
    require(
        isinstance(nonce, str) and re.fullmatch(r"[0-9a-f]{32}", nonce),
        "serial nonce is unbound",
    )
    if request["mode"] == "guest":
        target = request["target_vm_uuid"]
        require(target in TARGETS, "serial target outside fixture")
        require(
            request["pipe"] == "\\\\.\\pipe\\mcli1-maint-" + target,
            "serial target channel changed",
        )
    else:
        require(
            request["mode"] == "local-test" and request["target_vm_uuid"] is None,
            "invalid serial mode",
        )
        require(
            request["pipe"] == "\\\\.\\pipe\\mcli1-serial-test-" + nonce,
            "local test channel changed",
        )
    require(
        all(type(request[k]) is int for k in ("expires_utc_ns", "expires_mono_ns")),
        "serial deadline is unbound",
    )
    steps = request["steps"]
    require(
        isinstance(steps, list) and 1 <= len(steps) <= 128, "serial steps are unbound"
    )
    for number, step in enumerate(steps):
        require(set(step) == {"send", "ack"}, "serial step fields changed")
        line = step["send"]
        require(
            isinstance(line, str)
            and 1 <= len(line) <= 2047
            and all(32 <= ord(c) <= 126 for c in line),
            "serial command is not one bounded printable line",
        )
        require(
            step["ack"] == f"MCLI1_ACK_{nonce}_{number}",
            "serial acknowledgement binding changed",
        )
    return request


def live(request):
    require(
        time.time_ns() < request["expires_utc_ns"]
        and time.monotonic_ns() < request["expires_mono_ns"],
        "serial deadline expired",
    )


def verify_job(request):
    """Reject direct invocation outside this request's kill-on-close job."""
    import ctypes
    from ctypes import wintypes

    require(sys.platform == "win32", "serial worker requires Windows")

    class Limits(ctypes.Structure):
        _fields_ = [
            ("ProcessTime", ctypes.c_int64),
            ("JobTime", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "OpenJobObjectW": (
            [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR],
            wintypes.HANDLE,
        ),
        "GetCurrentProcess": ([], wintypes.HANDLE),
        "IsProcessInJob": (
            [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)],
            wintypes.BOOL,
        ),
        "QueryInformationJobObject": (
            [
                wintypes.HANDLE,
                ctypes.c_int,
                ctypes.c_void_p,
                wintypes.DWORD,
                ctypes.c_void_p,
            ],
            wintypes.BOOL,
        ),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
    }
    for name, (args, result) in signatures.items():
        function = getattr(api, name)
        function.argtypes, function.restype = args, result
    handle = api.OpenJobObjectW(
        0x4, False, "Local\\MCLI1Serial-" + request["request_id"]
    )
    require(bool(handle), "serial worker has no bound job")
    try:
        member, limits = wintypes.BOOL(), Limits()
        require(
            api.IsProcessInJob(api.GetCurrentProcess(), handle, ctypes.byref(member))
            and member.value,
            "serial worker is outside its bound job",
        )
        require(
            api.QueryInformationJobObject(
                handle, 2, ctypes.byref(limits), ctypes.sizeof(limits), None
            ),
            "serial job limits unavailable",
        )
        require(
            limits.LimitFlags & 0x2008 == 0x2008 and limits.ActiveProcessLimit == 1,
            "serial job limits differ",
        )
    finally:
        # Retaining this handle would prevent parent-death kill-on-close.
        require(api.CloseHandle(handle), "serial worker job query handle did not close")


class NamedPipe:
    """Blocking I/O is confined to the externally bounded Windows worker."""

    def __init__(self, name):
        require(sys.platform == "win32", "serial worker requires Windows")
        self.file = io.FileIO(name, "r+")

    def send(self, raw):
        require(
            self.file.write(raw) == len(raw), "partial serial write; delivery unknown"
        )

    def read_available(self):
        import ctypes
        import msvcrt
        from ctypes import wintypes

        api = ctypes.WinDLL("kernel32", use_last_error=True).PeekNamedPipe
        api.argtypes = [
            wintypes.HANDLE,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.c_void_p,
        ]
        api.restype = wintypes.BOOL
        available = wintypes.DWORD()
        if not api(
            msvcrt.get_osfhandle(self.file.fileno()),
            None,
            0,
            None,
            ctypes.byref(available),
            None,
        ):
            raise Refuse("serial pipe closed; reconcile without replay")
        return self.file.read(min(available.value, 4096)) if available.value else b""

    def close(self):
        self.file.close()


def exchange(request, channel):
    nonce = request["request_id"]
    stream_hash = hashlib.sha256()
    total, pending, data, acknowledged = 0, bytearray(), bytearray(), []
    for index, step in enumerate(request["steps"]):
        live(request)
        channel.send((step["send"] + "\r").encode("ascii"))
        matched = False
        while not matched:
            live(request)
            chunk = channel.read_available()
            require(isinstance(chunk, bytes), "serial reader returned invalid bytes")
            total += len(chunk)
            require(total <= MAX_CONSOLE, "serial console output limit")
            stream_hash.update(chunk)
            pending.extend(chunk)
            require(len(pending) <= MAX_LINE + 4096, "serial line output limit")
            while b"\n" in pending:
                line, _, tail = pending.partition(b"\n")
                pending = bytearray(tail)
                require(len(line) <= MAX_LINE, "serial line output limit")
                line = bytes(line).rstrip(b"\r")
                if line.startswith(("MCLI1_ACK_" + nonce + "_").encode()):
                    require(
                        line == step["ack"].encode() and not matched,
                        "duplicate or out-of-order serial acknowledgement",
                    )
                    matched = True
                prefix = f"MCLI1_DATA_{nonce}_{index}:".encode()
                if line.startswith(("MCLI1_DATA_" + nonce + "_").encode()):
                    require(
                        line.startswith(prefix) and not matched,
                        "serial data frame out of order",
                    )
                    data.extend(base64.b64decode(line[len(prefix) :], validate=True))
                    require(len(data) <= MAX_DATA, "serial data output limit")
            require(len(pending) <= MAX_LINE, "serial line output limit")
            if not chunk:
                time.sleep(0.01)
        acknowledged.append(step["ack"])
    return {
        "status": "serial-exchange-reported-not-accepted",
        "request_id": nonce,
        "acknowledged_steps": acknowledged,
        "console_bytes": total,
        "console_sha256": stream_hash.hexdigest(),
        "data_base64": base64.b64encode(data).decode("ascii"),
        "data_sha256": digest(data),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker")
    args = parser.parse_args()
    if args.worker:
        # Parent assigns its non-inheritable Job Object before writing this gate.
        raw = sys.stdin.buffer.readline(MAX_REQUEST + 2)
        require(
            raw.endswith(b"\n") and len(raw) <= MAX_REQUEST + 1,
            "serial worker start gate missing or oversized",
        )
        request = checked(raw[:-1], args.worker)
        live(request)
        verify_job(request)
        channel = NamedPipe(request["pipe"])
        try:
            result = exchange(request, channel)
        finally:
            channel.close()
    else:
        result = {
            "status": "unarmed-preview",
            "native_calls": 0,
            "vm_configuration_available": False,
        }
    sys.stdout.buffer.write(encode(result) + b"\n")
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001 - Never expose console/request bytes in errors.
        # Console/request bytes may contain sensitive material. Never echo them.
        sys.stderr.write("serial worker held; delivery may be uncertain\n")
        sys.exit(2)
