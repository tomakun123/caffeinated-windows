import sys
import ctypes
from ctypes import wintypes

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

HWND_BROADCAST  = 0xFFFF
WM_SYSCOMMAND   = 0x0112
SC_MONITORPOWER = 0xF170

def _is_windows() -> bool:
    return sys.platform.startswith("win")

if _is_windows():
    _user32 = ctypes.windll.user32
    # Without explicit argtypes ctypes passes HWND as a 32-bit int, so a value
    # like -1 becomes 0xFFFFFFFF instead of HWND_BROADCAST (0xFFFF) on x64.
    _user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _user32.SendMessageW.restype  = ctypes.c_ssize_t

    class _LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    _user32.GetLastInputInfo.argtypes = [ctypes.POINTER(_LASTINPUTINFO)]
    _user32.GetLastInputInfo.restype  = wintypes.BOOL

def set_awake(keep_display_on: bool) -> None:
    """
    Prevent the system from sleeping.
    If keep_display_on=True, also prevent the display from sleeping.
    """
    if not _is_windows():
        raise RuntimeError("keepawake is only supported on Windows.")

    flags = ES_CONTINUOUS | ES_SYSTEM_REQUIRED
    if keep_display_on:
        flags |= ES_DISPLAY_REQUIRED

    # Returns previous execution state (ignored here)
    ctypes.windll.kernel32.SetThreadExecutionState(flags)

def clear_awake() -> None:
    """
    Clear the awake request and return control to normal power management.
    """
    if not _is_windows():
        return
    ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)

def turn_off_display() -> None:
    """
    Turn off the monitor immediately. Any mouse move or keypress wakes it.
    Note: if ES_DISPLAY_REQUIRED is active Windows may re-light it on next
    input — that is expected and correct behaviour.
    """
    if not _is_windows():
        return
    # lParam 2 = power off
    _user32.SendMessageW(HWND_BROADCAST, WM_SYSCOMMAND, SC_MONITORPOWER, 2)

def last_input_tick() -> int:
    """
    Tick count (ms since boot) of the last user keyboard/mouse input.
    Used to detect that the user is back after the display was turned off.
    """
    if not _is_windows():
        return 0
    info = _LASTINPUTINFO(cbSize=ctypes.sizeof(_LASTINPUTINFO))
    if not _user32.GetLastInputInfo(ctypes.byref(info)):
        return 0
    return int(info.dwTime)
