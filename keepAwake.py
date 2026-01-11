import sys
import ctypes

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

def _is_windows() -> bool:
    return sys.platform.startswith("win")

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
