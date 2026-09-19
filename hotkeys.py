"""
Global hotkeys via RegisterHotKey (pure ctypes, no extra dependencies).

Chord model: a *leader* combo (e.g. Ctrl+/) is registered permanently. When it
fires, each action key (e.g. q / d / c) is registered *unmodified* for a short
window, so the next keypress is swallowed system-wide and mapped to an action.
After the window expires (or a key is pressed) the action keys are released and
typing q/d/c elsewhere behaves normally again.
"""
from __future__ import annotations
import ctypes
import sys
import threading
from ctypes import wintypes
from typing import Callable, Optional

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WM_HOTKEY, WM_TIMER, WM_QUIT, WM_APP = 0x0312, 0x0113, 0x0012, 0x8000
WM_REBIND = WM_APP + 1
ERROR_HOTKEY_ALREADY_REGISTERED = 1409

LEADER_ID      = 1
ACTION_ID_BASE = 10
CHORD_MS       = 1500

_MOD_NAMES = {"ctrl": MOD_CONTROL, "control": MOD_CONTROL, "alt": MOD_ALT,
              "shift": MOD_SHIFT, "win": MOD_WIN, "super": MOD_WIN}
_MOD_LABEL = [(MOD_CONTROL, "Ctrl"), (MOD_ALT, "Alt"), (MOD_SHIFT, "Shift"), (MOD_WIN, "Win")]

_is_win = sys.platform.startswith("win")
if _is_win:
    _user32   = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32
    _user32.RegisterHotKey.argtypes     = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    _user32.UnregisterHotKey.argtypes   = [wintypes.HWND, ctypes.c_int]
    _user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _user32.SetTimer.argtypes   = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
    _user32.SetTimer.restype    = ctypes.c_size_t
    _user32.KillTimer.argtypes  = [wintypes.HWND, ctypes.c_size_t]
    _user32.GetMessageW.argtypes  = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    _user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
    _user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
    _user32.VkKeyScanW.restype  = ctypes.c_short
    _user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
    _user32.MapVirtualKeyW.restype  = wintypes.UINT


# ── Key string helpers ───────────────────────────────────────────────────────

def key_to_vk(key: str) -> Optional[int]:
    """'q', '/', 'f5' -> virtual-key code, or None if unsupported."""
    key = key.strip().lower()
    if not key:
        return None
    if len(key) >= 2 and key[0] == "f" and key[1:].isdigit() and 1 <= int(key[1:]) <= 12:
        return 0x70 + int(key[1:]) - 1
    if len(key) == 1 and key.isprintable() and not key.isspace():
        if not _is_win:
            return ord(key.upper())
        r = _user32.VkKeyScanW(key)
        return None if r == -1 else r & 0xFF
    return None


def vk_to_key(vk: int) -> Optional[str]:
    """Virtual-key code -> key string ('q', '/', 'f5') or None. Ignores the char
    translation so Ctrl+K yields 'k' rather than a control character."""
    if 0x70 <= vk <= 0x7B:
        return f"f{vk - 0x70 + 1}"
    if not _is_win:
        return None
    ch = _user32.MapVirtualKeyW(vk, 2) & 0xFFFF     # MAPVK_VK_TO_CHAR
    if ch and chr(ch).isprintable() and not chr(ch).isspace():
        return chr(ch).lower()
    return None


def is_valid_key(key: str) -> bool:
    return key_to_vk(key) is not None


def split_combo(combo: str) -> tuple[list[str], str]:
    """'ctrl+alt+/' -> (['ctrl','alt'], '/').  'ctrl++' -> (['ctrl'], '+')."""
    combo = combo.strip().lower()
    if combo.endswith("+"):
        return [p for p in combo[:-1].split("+") if p], "+"
    parts = combo.split("+")
    return [p for p in parts[:-1] if p], parts[-1]


def parse_combo(combo: str) -> Optional[tuple[int, int]]:
    """'ctrl+alt+/' -> (mod_flags, vk). Requires >=1 modifier. None if invalid."""
    mods_s, key = split_combo(combo)
    if not mods_s:
        return None
    mods = 0
    for m in mods_s:
        if m not in _MOD_NAMES:
            return None
        mods |= _MOD_NAMES[m]
    vk = key_to_vk(key)
    if vk is None:
        return None
    return mods, vk


def format_key(key: str) -> str:
    key = key.strip()
    return key.upper() if key else "—"


def format_combo(combo: str) -> str:
    """'ctrl+/' -> 'Ctrl + /' for display."""
    parsed = parse_combo(combo)
    if parsed is None:
        return combo or "—"
    mods, _ = parsed
    _, key = split_combo(combo)
    labels = [lbl for flag, lbl in _MOD_LABEL if mods & flag]
    return " + ".join(labels + [format_key(key)])


# ── Hotkey thread ────────────────────────────────────────────────────────────

class HotkeyThread(threading.Thread):
    """
    Owns RegisterHotKey/GetMessage (both are thread-affine).

    get_bindings() -> (leader: str, actions: dict[name, key])   read on (re)bind
    on_action(name)                                             called from this thread
    on_status(msg | None)                                       leader conflict / ok
    """

    def __init__(self, get_bindings: Callable[[], tuple[str, dict[str, str]]],
                 on_action: Callable[[str], None],
                 on_status: Callable[[Optional[str]], None]):
        super().__init__(daemon=True, name="hotkeys")
        self._get_bindings = get_bindings
        self._on_action    = on_action
        self._on_status    = on_status
        self._tid          = 0
        self._ready        = threading.Event()
        self._armed_ids: dict[int, str] = {}
        self._timer        = 0
        self._leader_ok    = False

    # ── public (any thread) ────────────────────────────────────────────────

    def rebind(self) -> None:
        if _is_win and self._ready.wait(2) and self._tid:
            _user32.PostThreadMessageW(self._tid, WM_REBIND, 0, 0)

    def stop(self) -> None:
        if _is_win and self._ready.wait(2) and self._tid:
            _user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)

    # ── thread body ────────────────────────────────────────────────────────

    def run(self) -> None:
        if not _is_win:
            return
        self._tid = _kernel32.GetCurrentThreadId()
        msg = wintypes.MSG()
        _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)   # force-create the message queue
        self._ready.set()
        self._register_leader()
        try:
            while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    self._on_hotkey(int(msg.wParam))
                elif msg.message == WM_TIMER:
                    self._disarm()
                elif msg.message == WM_REBIND:
                    self._disarm()
                    self._unregister_leader()
                    self._register_leader()
        finally:
            self._disarm()
            self._unregister_leader()

    def _register_leader(self) -> None:
        leader, _ = self._get_bindings()
        parsed = parse_combo(leader) if leader else None
        if parsed is None:
            self._leader_ok = False
            self._on_status(None if not leader else f"Invalid prefix: {leader}")
            return
        mods, vk = parsed
        ok = _user32.RegisterHotKey(None, LEADER_ID, mods | MOD_NOREPEAT, vk)
        self._leader_ok = bool(ok)
        if ok:
            self._on_status(None)
        else:
            err = _kernel32.GetLastError()
            self._on_status("Prefix is already in use by another app"
                            if err == ERROR_HOTKEY_ALREADY_REGISTERED
                            else f"Could not register prefix (error {err})")

    def _unregister_leader(self) -> None:
        if self._leader_ok:
            _user32.UnregisterHotKey(None, LEADER_ID)
            self._leader_ok = False

    def _on_hotkey(self, hid: int) -> None:
        if hid == LEADER_ID:
            self._arm()
        elif hid in self._armed_ids:
            name = self._armed_ids[hid]
            self._disarm()
            self._on_action(name)

    def _arm(self) -> None:
        self._disarm()
        _, actions = self._get_bindings()
        for i, (name, key) in enumerate(actions.items()):
            vk = key_to_vk(key)
            if vk is None:
                continue
            hid = ACTION_ID_BASE + i
            if _user32.RegisterHotKey(None, hid, MOD_NOREPEAT, vk):
                self._armed_ids[hid] = name
        self._timer = _user32.SetTimer(None, 0, CHORD_MS, None)

    def _disarm(self) -> None:
        for hid in self._armed_ids:
            _user32.UnregisterHotKey(None, hid)
        self._armed_ids.clear()
        if self._timer:
            _user32.KillTimer(None, self._timer)
            self._timer = 0
