"""Read-only Windows PID-creation retirement proof shared by host checks."""

import ctypes
import sys
from ctypes import wintypes

from .windows_readonly import require


def retired(record):
    """Access denial or an unreadable identity is never a proof of retirement."""
    require(sys.platform == "win32", "native process retirement proof requires Windows")
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes, api.OpenProcess.restype = (
        [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD],
        wintypes.HANDLE,
    )
    api.WaitForSingleObject.argtypes, api.WaitForSingleObject.restype = (
        [wintypes.HANDLE, wintypes.DWORD],
        wintypes.DWORD,
    )
    api.GetProcessTimes.argtypes, api.GetProcessTimes.restype = (
        [wintypes.HANDLE, *([ctypes.c_void_p] * 4)],
        wintypes.BOOL,
    )
    api.CloseHandle.argtypes, api.CloseHandle.restype = [wintypes.HANDLE], wintypes.BOOL
    handle = api.OpenProcess(0x1000 | 0x100000, False, record["pid"])
    if not handle:
        require(
            ctypes.get_last_error() == 87, "process retirement could not be observed"
        )
        return True
    try:
        status = api.WaitForSingleObject(handle, 0)
        require(status in {0, 0x102}, "process retirement wait failed")
        if status == 0:
            return True
        stamps = [ctypes.c_uint64() for _ in range(4)]
        require(
            api.GetProcessTimes(handle, *[ctypes.byref(s) for s in stamps]),
            "process retirement identity unavailable",
        )
        return stamps[0].value != record["created_filetime"]
    finally:
        require(api.CloseHandle(handle), "process retirement handle did not close")
