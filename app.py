"""
Caffeinated (Win) — keep your Windows PC awake.
Main window + system tray. Settings persist between sessions.
"""
from __future__ import annotations
import sys, json, os, time, threading, winreg
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional
import tkinter as tk
from tkinter import messagebox
import pystray
from pystray import MenuItem as Item
from PIL import ImageTk

from keepAwake import set_awake, clear_awake, turn_off_display, last_input_tick
from logo import make_logo
from hotkeys import HotkeyThread, parse_combo, is_valid_key, vk_to_key, format_combo, format_key

APP_NAME    = "Caffeinated (Win)"
APP_REG_KEY = "CaffeinatedWin"
CONFIG_DIR  = Path(os.environ.get("APPDATA", Path.home())) / "caffeinated-windows"
CONFIG_FILE = CONFIG_DIR / "settings.json"

BG, PANEL, TEXT, MUTED  = "#1a1a2e", "#22223a", "#f0f0f8", "#a8a8c0"
ACCENT, TRACK           = "#e8a87c", "#2e2e4a"
GREEN, RED              = "#4db87a", "#c94f4f"
WIN_W, WIN_H            = 370, 860

HOTKEY_ACTIONS = [("quit", "Quit"), ("display_off", "Turn off display"), ("toggle", "Toggle caffeination")]
DEFAULT_LEADER  = "ctrl+/"
DEFAULT_HOTKEYS = {"quit": "q", "display_off": "d", "toggle": "c"}


# ── Settings ────────────────────────────────────────────────────────────────

@dataclass
class Settings:
    auto_start:      bool      = False
    keep_display_on: bool      = False
    start_on_boot:   bool      = False
    custom_timers:   list[int] = field(default_factory=lambda: [30, 60, 120])
    hotkey_leader:   str       = DEFAULT_LEADER      # global chord prefix; "" disables
    hotkeys:         dict      = field(default_factory=lambda: dict(DEFAULT_HOTKEYS))

    def save(self) -> None:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        except OSError:
            pass

    @classmethod
    def load(cls) -> "Settings":
        if not CONFIG_FILE.exists():
            return cls()
        try:
            d = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            timers = [int(t) for t in d.get("custom_timers", [30, 60, 120])
                      if isinstance(t, (int, float)) and 1 <= t <= 1440]
            leader = d.get("hotkey_leader", DEFAULT_LEADER)
            if not isinstance(leader, str) or (leader and parse_combo(leader) is None):
                leader = DEFAULT_LEADER
            raw_hk  = d.get("hotkeys", {}) if isinstance(d.get("hotkeys"), dict) else {}
            hotkeys = dict(DEFAULT_HOTKEYS)
            for name in hotkeys:
                k = raw_hk.get(name)
                if isinstance(k, str) and is_valid_key(k):
                    hotkeys[name] = k.strip().lower()
            # duplicate keys fall back to defaults
            if len(set(hotkeys.values())) != len(hotkeys):
                hotkeys = dict(DEFAULT_HOTKEYS)
            return cls(
                auto_start      = bool(d.get("auto_start", False)),
                keep_display_on = bool(d.get("keep_display_on", False)),
                start_on_boot   = bool(d.get("start_on_boot", False)),
                custom_timers   = timers or [30, 60, 120],
                hotkey_leader   = leader,
                hotkeys         = hotkeys,
            )
        except (json.JSONDecodeError, OSError, ValueError, TypeError):
            return cls()


# ── Helpers ─────────────────────────────────────────────────────────────────

def _pythonw() -> str:
    p = Path(sys.executable).parent / "pythonw.exe"
    return str(p) if p.exists() else sys.executable


def set_boot_startup(enabled: bool) -> None:
    reg_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    value    = f'"{_pythonw()}" "{Path(__file__).resolve()}"'
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path, 0, winreg.KEY_SET_VALUE) as k:
            if enabled:
                winreg.SetValueEx(k, APP_REG_KEY, 0, winreg.REG_SZ, value)
            else:
                try:    winreg.DeleteValue(k, APP_REG_KEY)
                except FileNotFoundError: pass
    except OSError:
        pass


# Tk event.state modifier bits (Windows)
TK_SHIFT, TK_CTRL, TK_ALT = 0x0001, 0x0004, 0x20000


def _event_key(event) -> Optional[str]:
    """Tk key event → normalised key string ('q', '/', 'f5') or None if unsupported.
    Uses the Windows virtual-key code so Ctrl+K gives 'k', not a control char."""
    key = vk_to_key(int(event.keycode)) if event.keycode else None
    if key is None:
        ch = event.char
        if len(ch) == 1 and ch.isprintable() and not ch.isspace():
            key = ch.lower()
    return key


# ── Preset editor dialog ─────────────────────────────────────────────────────

class PresetEditor(tk.Toplevel):
    def __init__(self, parent: tk.Misc, app: "CaffeinatedApp"):
        super().__init__(parent)
        self.app = app
        self.title(f"{APP_NAME} — Timer presets")
        self.configure(bg=PANEL); self.resizable(False, False)
        self.transient(parent); self.grab_set()

        tk.Label(self, text="Timer presets", font=("Segoe UI",11,"bold"), bg=PANEL, fg=TEXT).pack(anchor="w", padx=16, pady=(14,4))
        tk.Label(self, text="One duration (minutes) per line. Up to 5 values.",
                 font=("Segoe UI",9), bg=PANEL, fg=MUTED).pack(anchor="w", padx=16, pady=(0,8))

        self._txt = tk.Text(self, width=18, height=6, font=("Segoe UI",11),
                            bg=BG, fg=TEXT, insertbackground=TEXT, relief=tk.FLAT, bd=4, pady=4)
        self._txt.pack(padx=16, pady=(0,12))
        self._txt.insert("1.0", "\n".join(str(t) for t in app.settings.custom_timers))

        brow = tk.Frame(self, bg=PANEL); brow.pack(fill="x", padx=16, pady=(0,14))
        tk.Button(brow, text="Cancel", command=self.destroy,
                  font=("Segoe UI",9), bg=BG, fg=TEXT, relief=tk.FLAT, padx=12, pady=6, cursor="hand2").pack(side="right")
        tk.Button(brow, text="Save", command=self._save,
                  font=("Segoe UI",9,"bold"), bg=ACCENT, fg="#1a1a2e",
                  activebackground="#f0bc9a", relief=tk.FLAT, padx=12, pady=6, cursor="hand2").pack(side="right", padx=(0,8))
        self.bind("<Escape>", lambda _: self.destroy())

        self.update_idletasks()
        px = parent.winfo_rootx() + (parent.winfo_width()  - self.winfo_width())  // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{max(0,px)}+{max(0,py)}")

    def _save(self):
        timers = []
        for ln in self._txt.get("1.0", tk.END).strip().splitlines():
            ln = ln.strip()
            if not ln: continue
            try:
                v = int(ln)
                if 1 <= v <= 1440: timers.append(v)
            except ValueError: pass
        if not timers:
            messagebox.showwarning(APP_NAME, "Enter at least one valid duration (1–1440).", parent=self); return
        self.app.settings.custom_timers = timers[:5]
        self.app.settings.save()
        self.app._rebuild_preset_buttons()
        self.destroy()


# ── Main app ─────────────────────────────────────────────────────────────────

class CaffeinatedApp:
    def __init__(self):
        self.settings     = Settings.load()
        self._lock        = threading.Lock()
        self._stop        = threading.Event()
        self.enabled      = False
        self.keep_display = self.settings.keep_display_on
        self.timer_end:   Optional[float] = None
        self._reaffirm_at = 0.0
        # set while the display was turned off on purpose: drop ES_DISPLAY_REQUIRED
        # until the user touches the machine again, so the heartbeat can't re-light it
        self._display_suppressed = False
        self._display_off_tick   = 0
        self._capturing: Optional[str] = None   # hotkey field currently waiting for a key

        self._build_gui()
        self._build_tray()
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()
        self._hotkeys = HotkeyThread(
            get_bindings=lambda: (self.settings.hotkey_leader, dict(self.settings.hotkeys)),
            on_action=lambda name: self.root.after(0, self._run_action, name),
            on_status=lambda msg: self.root.after(0, self._set_hotkey_status, msg),
        )
        self._hotkeys.start()

        if self.settings.auto_start:
            self._set_enabled(True)
        self._tick()

    # ── GUI ────────────────────────────────────────────────────────────────

    def _build_gui(self):
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.root.geometry(f"{WIN_W}x{WIN_H}")
        self.root.protocol("WM_DELETE_WINDOW", lambda: self.root.withdraw())

        # Header
        hdr = tk.Frame(self.root, bg=BG, padx=16, pady=12); hdr.pack(fill="x")
        self._icon_img  = None
        self._icon_lbl  = tk.Label(hdr, bg=BG)
        self._icon_lbl.pack(side="left", padx=(0, 8))
        tk.Label(hdr, text=APP_NAME, font=("Segoe UI",13,"bold"), bg=BG, fg=TEXT).pack(side="left")

        # Status pill
        pill_frame = tk.Frame(self.root, bg=BG); pill_frame.pack(pady=(0, 8))
        self._pill = tk.Canvas(pill_frame, width=160, height=32, bg=BG, highlightthickness=0)
        self._pill.pack()

        # Big toggle
        self._toggle_btn = tk.Button(
            self.root, text="Start Caffeination", command=self._on_toggle,
            font=("Segoe UI",11,"bold"), bg=ACCENT, fg="#1a1a2e",
            activebackground="#f0bc9a", activeforeground="#1a1a2e",
            relief=tk.FLAT, padx=20, pady=10, cursor="hand2", width=24,
        )
        self._toggle_btn.pack(pady=(0, 14))

        # ── Display card ───────────────────────────────────────────────────
        disp = tk.Frame(self.root, bg=PANEL, padx=16, pady=10); disp.pack(fill="x", padx=16, pady=(0, 10))
        self._display_var = tk.BooleanVar(value=self.keep_display)
        tk.Checkbutton(
            disp, text="Keep display on (prevent screen sleep)",
            variable=self._display_var, command=self._on_display_toggle,
            font=("Segoe UI",10), bg=PANEL, fg=TEXT,
            selectcolor=BG, activebackground=PANEL, activeforeground=TEXT,
        ).pack(anchor="w")
        tk.Button(
            disp, text="Turn off display now", command=self._do_turn_off_display,
            font=("Segoe UI",9), bg=BG, fg=MUTED, activebackground=TRACK,
            relief=tk.FLAT, padx=8, pady=4, cursor="hand2",
        ).pack(anchor="w", pady=(6, 0))

        # ── Timer card ─────────────────────────────────────────────────────
        tc = tk.Frame(self.root, bg=PANEL, padx=16, pady=12); tc.pack(fill="x", padx=16, pady=(0, 10))
        tk.Label(tc, text="TIMER", font=("Segoe UI",8,"bold"), bg=PANEL, fg=MUTED).pack(anchor="w", pady=(0,6))
        self._timer_lbl = tk.Label(tc, text="—", font=("Segoe UI",24,"bold"), bg=PANEL, fg=TEXT)
        self._timer_lbl.pack(anchor="w")
        self._preset_frame = tk.Frame(tc, bg=PANEL); self._preset_frame.pack(anchor="w", pady=(8,0))
        self._rebuild_preset_buttons()
        # custom row
        cr = tk.Frame(tc, bg=PANEL); cr.pack(anchor="w", pady=(6,0))
        tk.Label(cr, text="Custom:", font=("Segoe UI",9), bg=PANEL, fg=MUTED).pack(side="left")
        self._custom_var = tk.StringVar()
        tk.Entry(cr, textvariable=self._custom_var, width=5,
                 font=("Segoe UI",10), bg=BG, fg=TEXT, insertbackground=TEXT, relief=tk.FLAT, bd=4
                 ).pack(side="left", padx=(6,4))
        tk.Label(cr, text="min", font=("Segoe UI",9), bg=PANEL, fg=MUTED).pack(side="left")
        tk.Button(cr, text="Set",   command=self._on_custom_timer,
                  font=("Segoe UI",9), bg=BG, fg=TEXT, activebackground=TRACK,
                  relief=tk.FLAT, padx=8, pady=3, cursor="hand2").pack(side="left", padx=(6,0))
        tk.Button(cr, text="Clear", command=self._on_clear_timer,
                  font=("Segoe UI",9), bg=BG, fg=MUTED, activebackground=TRACK,
                  relief=tk.FLAT, padx=8, pady=3, cursor="hand2").pack(side="left", padx=(4,0))

        # ── Settings card ──────────────────────────────────────────────────
        sc = tk.Frame(self.root, bg=PANEL, padx=16, pady=12); sc.pack(fill="x", padx=16, pady=(0, 16))
        tk.Label(sc, text="SETTINGS", font=("Segoe UI",8,"bold"), bg=PANEL, fg=MUTED).pack(anchor="w", pady=(0,6))

        self._auto_start_var = tk.BooleanVar(value=self.settings.auto_start)
        tk.Checkbutton(
            sc, text="Auto-start caffeination on launch",
            variable=self._auto_start_var, command=self._on_auto_start_toggle,
            font=("Segoe UI",9), bg=PANEL, fg=TEXT,
            selectcolor=BG, activebackground=PANEL, activeforeground=TEXT,
        ).pack(anchor="w")

        self._boot_var = tk.BooleanVar(value=self.settings.start_on_boot)
        tk.Checkbutton(
            sc, text="Launch app at Windows startup",
            variable=self._boot_var, command=self._on_boot_toggle,
            font=("Segoe UI",9), bg=PANEL, fg=TEXT,
            selectcolor=BG, activebackground=PANEL, activeforeground=TEXT,
        ).pack(anchor="w", pady=(4,0))

        tk.Button(sc, text="Edit timer presets…", command=lambda: PresetEditor(self.root, self),
                  font=("Segoe UI",9), bg=BG, fg=TEXT, activebackground=TRACK,
                  relief=tk.FLAT, padx=8, pady=4, cursor="hand2").pack(anchor="w", pady=(10,0))

        # ── Hotkeys card ───────────────────────────────────────────────────
        hk = tk.Frame(self.root, bg=PANEL, padx=16, pady=12); hk.pack(fill="x", padx=16, pady=(0, 16))
        tk.Label(hk, text="HOTKEYS", font=("Segoe UI",8,"bold"), bg=PANEL, fg=MUTED).pack(anchor="w", pady=(0,6))
        self._hk_btns: dict[str, tk.Button] = {}
        for name, label in [("leader", "Global prefix")] + HOTKEY_ACTIONS:
            r = tk.Frame(hk, bg=PANEL); r.pack(fill="x", pady=(0,4))
            tk.Label(r, text=label, font=("Segoe UI",9), bg=PANEL, fg=TEXT, width=18, anchor="w").pack(side="left")
            b = tk.Button(r, command=lambda n=name: self._begin_capture(n),
                          font=("Segoe UI",9), bg=BG, fg=TEXT, activebackground=TRACK,
                          relief=tk.FLAT, padx=8, pady=3, cursor="hand2", width=12)
            b.pack(side="left")
            self._hk_btns[name] = b
        tk.Label(hk, text="Prefix, then the action key — works from any app.\n"
                          "With this window focused the action key works alone.",
                 font=("Segoe UI",8), bg=PANEL, fg=MUTED, justify="left").pack(anchor="w", pady=(4,0))
        self._hk_status = tk.Label(hk, text="", font=("Segoe UI",8), bg=PANEL, fg=RED, justify="left")
        self._hk_status.pack(anchor="w")
        self._refresh_hotkey_labels()

        self.root.bind_all("<KeyPress>", self._on_keypress)
        self._refresh_ui()

    def _rebuild_preset_buttons(self):
        for w in self._preset_frame.winfo_children(): w.destroy()
        for m in self.settings.custom_timers:
            tk.Button(self._preset_frame, text=f"{m}m", command=lambda v=m: self._start_timer(v),
                      font=("Segoe UI",9), bg=BG, fg=TEXT, activebackground=TRACK,
                      relief=tk.FLAT, padx=10, pady=4, cursor="hand2").pack(side="left", padx=(0,4))
        tk.Button(self._preset_frame, text="∞", command=self._on_clear_timer,
                  font=("Segoe UI",11), bg=BG, fg=MUTED, activebackground=TRACK,
                  relief=tk.FLAT, padx=10, pady=4, cursor="hand2").pack(side="left")

    def _refresh_ui(self):
        color = GREEN if self.enabled else RED
        self._pill.delete("all")
        self._pill.create_oval(6, 6, 26, 26, fill=color, outline="")
        self._pill.create_text(34, 16, text="ACTIVE" if self.enabled else "INACTIVE",
                               anchor="w", fill=color, font=("Segoe UI",10,"bold"))
        self._toggle_btn.config(
            text="Stop Caffeination" if self.enabled else "Start Caffeination",
            bg=RED if self.enabled else ACCENT,
            activebackground="#e06060" if self.enabled else "#f0bc9a",
        )
        self._display_var.set(self.keep_display)
        # timer display
        with self._lock:
            te = self.timer_end
        if te is None:
            self._timer_lbl.config(text="Indefinite" if self.enabled else "—")
        else:
            rem = max(0, int(te - time.time()))
            mm, ss = divmod(rem, 60); hh, mm = divmod(mm, 60)
            self._timer_lbl.config(text=f"{hh}:{mm:02d}:{ss:02d}" if hh else f"{mm}:{ss:02d}")

    def _tick(self):
        """1-second UI refresh + timer expiry check (main thread)."""
        self._refresh_ui()
        with self._lock:
            enabled, te = self.enabled, self.timer_end
        if enabled and te is not None and time.time() >= te:
            self._set_enabled(False)
            messagebox.showinfo(APP_NAME, "Timer finished — caffeination stopped.")
        self.root.after(1000, self._tick)

    # ── GUI handlers ───────────────────────────────────────────────────────

    def _on_toggle(self):
        self._set_enabled(not self.enabled)

    def _on_display_toggle(self):
        self.keep_display = self._display_var.get()
        self._resume_display_flag()
        self.settings.keep_display_on = self.keep_display
        self.settings.save()
        if self.enabled: self._apply_power_state()
        self._update_tray()

    def _on_custom_timer(self):
        raw = self._custom_var.get().strip()
        try:   mins = int(raw)
        except ValueError:
            messagebox.showwarning(APP_NAME, "Enter a whole number of minutes.", parent=self.root); return
        if not 1 <= mins <= 1440:
            messagebox.showwarning(APP_NAME, "Duration must be 1–1440 minutes.", parent=self.root); return
        self._start_timer(mins)

    def _on_clear_timer(self):
        with self._lock: self.timer_end = None
        if not self.enabled: self._set_enabled(True)
        self._refresh_ui(); self._update_tray()

    def _do_turn_off_display(self):
        """Blank the monitor (main thread). Shared by button, tray item and hotkey."""
        if self.keep_display:
            # drop ES_DISPLAY_REQUIRED until the user returns, else Windows re-lights the screen
            with self._lock:
                self._display_suppressed = True
                self._display_off_tick   = last_input_tick()
            if self.enabled: self._apply_power_state()
        # 800 ms delay so the click/key release doesn't immediately re-wake the display
        self.root.after(800, turn_off_display)

    def _resume_display_flag(self):
        with self._lock:
            self._display_suppressed = False

    # ── Hotkeys ────────────────────────────────────────────────────────────

    def _run_action(self, name: str):
        if   name == "quit":        self._quit()
        elif name == "display_off": self._do_turn_off_display()
        elif name == "toggle":      self._set_enabled(not self.enabled)

    def _on_keypress(self, event):
        """Plain action keys while the window is focused (no prefix needed)."""
        if self._capturing is not None:
            return self._on_capture_key(event)
        if isinstance(event.widget, (tk.Entry, tk.Text)):
            return
        if event.state & (TK_CTRL | TK_ALT):
            return
        key = _event_key(event)
        if key is None:
            return
        for name, k in self.settings.hotkeys.items():
            if k == key:
                self._run_action(name); return "break"

    def _refresh_hotkey_labels(self):
        self._hk_btns["leader"].config(
            text=format_combo(self.settings.hotkey_leader) if self.settings.hotkey_leader else "(disabled)")
        for name, _ in HOTKEY_ACTIONS:
            self._hk_btns[name].config(text=format_key(self.settings.hotkeys.get(name, "")))

    def _begin_capture(self, name: str):
        if self._capturing is not None:
            self._end_capture()
        self._capturing = name
        self._hk_btns[name].config(text="Press keys…", fg=ACCENT)
        self.root.focus_set()

    def _end_capture(self):
        if self._capturing is not None:
            self._hk_btns[self._capturing].config(fg=TEXT)
        self._capturing = None
        self._refresh_hotkey_labels()

    def _on_capture_key(self, event):
        name = self._capturing
        if event.keysym in ("Control_L","Control_R","Alt_L","Alt_R","Shift_L","Shift_R","Win_L","Win_R"):
            return "break"                       # wait for the non-modifier key
        if event.keysym == "Escape":
            self._end_capture(); return "break"
        key = _event_key(event)
        if key is None:
            messagebox.showwarning(APP_NAME, "Use a letter, digit, punctuation key or F1–F12.", parent=self.root)
            self._end_capture(); return "break"
        if name == "leader":
            mods = [m for flag, m in ((TK_CTRL,"ctrl"), (TK_ALT,"alt"), (TK_SHIFT,"shift")) if event.state & flag]
            if not mods:
                messagebox.showwarning(APP_NAME, "The global prefix needs a modifier (Ctrl, Alt or Shift),\n"
                                                 "otherwise it would hijack that key in every app.", parent=self.root)
                self._end_capture(); return "break"
            self.settings.hotkey_leader = "+".join(mods + [key])
        else:
            if any(k == key and n != name for n, k in self.settings.hotkeys.items()):
                messagebox.showwarning(APP_NAME, f"'{format_key(key)}' is already used by another action.", parent=self.root)
                self._end_capture(); return "break"
            self.settings.hotkeys[name] = key
        self.settings.save()
        self._end_capture()
        self._hotkeys.rebind()
        return "break"

    def _set_hotkey_status(self, msg: Optional[str]):
        self._hk_status.config(text=msg or "")

    def _on_auto_start_toggle(self):
        self.settings.auto_start = self._auto_start_var.get()
        self.settings.save()

    def _on_boot_toggle(self):
        self.settings.start_on_boot = self._boot_var.get()
        self.settings.save()
        set_boot_startup(self.settings.start_on_boot)

    # ── Core state ─────────────────────────────────────────────────────────

    def _set_enabled(self, enabled: bool):
        with self._lock:
            self.enabled = enabled
            if not enabled: self.timer_end = None
        self._apply_power_state()
        self._refresh_ui()
        self._update_tray()

    def _start_timer(self, minutes: int):
        with self._lock:
            self.enabled   = True
            self.timer_end = time.time() + minutes * 60
        self._apply_power_state()
        self._refresh_ui()
        self._update_tray()

    def _apply_power_state(self):
        try:
            if self.enabled: set_awake(keep_display_on=self.keep_display and not self._display_suppressed)
            else:            clear_awake()
        except Exception as e:
            try: clear_awake()
            except Exception: pass
            messagebox.showwarning(APP_NAME, f"Failed to set keep-awake state:\n{e}")

    # ── Tray ───────────────────────────────────────────────────────────────

    def _build_tray(self):
        self._tray = pystray.Icon(
            name=APP_NAME, icon=make_logo(64), title=APP_NAME,
            menu=pystray.Menu(
                Item("Open", self._tray_open, default=True),
                Item(lambda i: "✅ Stop" if self.enabled else "☕ Start", self._tray_toggle),
                Item("Keep screen on", self._tray_toggle_display, checked=lambda _: self.keep_display),
                Item("Turn off display", lambda *_: self.root.after(0, self._do_turn_off_display)),
                pystray.Menu.SEPARATOR,
                Item("Quit", self._quit),
            ),
        )

    def _update_tray(self):
        try: self._tray.update_menu()
        except Exception: pass

    def _tray_open(self, *_):
        self.root.after(0, self.root.deiconify)

    def _tray_toggle(self, *_):
        self.root.after(0, lambda: self._set_enabled(not self.enabled))

    def _tray_toggle_display(self, *_):
        def _do():
            self.keep_display = not self.keep_display
            self._resume_display_flag()
            self._display_var.set(self.keep_display)
            self.settings.keep_display_on = self.keep_display
            self.settings.save()
            if self.enabled: self._apply_power_state()
            self._update_tray()
        self.root.after(0, _do)

    def _tooltip(self) -> str:
        with self._lock:
            en, kd, te = self.enabled, self.keep_display, self.timer_end
        if not en: return f"{APP_NAME}\nStatus: OFF"
        disp = "display ON" if kd else "display can sleep"
        if te is None: return f"{APP_NAME}\nON · {disp} · indefinite"
        rem = max(0, int(te - time.time()))
        mm, ss = divmod(rem, 60); hh, mm = divmod(mm, 60)
        t = f"{hh}:{mm:02d}:{ss:02d}" if hh else f"{mm}:{ss:02d}"
        return f"{APP_NAME}\nON · {disp} · {t} remaining"

    # ── Heartbeat (background thread — power state only) ───────────────────

    def _heartbeat_loop(self):
        """Re-assert (or clear) SetThreadExecutionState every 20 s from this thread.
        SetThreadExecutionState is per-thread, so this thread must explicitly clear
        its own flag when the user stops — the main thread's clear_awake() call alone
        is not enough."""
        while not self._stop.is_set():
            with self._lock:
                if self._display_suppressed and last_input_tick() != self._display_off_tick:
                    self._display_suppressed = False   # user is back — display flag resumes
                en = self.enabled
                kd = self.keep_display and not self._display_suppressed
            try:
                if en: set_awake(keep_display_on=kd)
                else:  clear_awake()
            except Exception: pass
            try: self._tray.title = self._tooltip()
            except Exception: pass
            self._stop.wait(20)

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def _quit(self, *_):
        self._stop.set()
        try: self._hotkeys.stop()
        except Exception: pass
        try: clear_awake()
        except Exception: pass
        self._tray.stop()
        self.root.after(0, self.root.destroy)

    def run(self):
        if not sys.platform.startswith("win"):
            print("Windows only. Exiting."); return

        photos = [ImageTk.PhotoImage(make_logo(sz)) for sz in (16, 32, 48, 64, 128, 256)]
        self.root.iconphoto(True, *photos); self.root._icon_photos = photos
        self._icon_img = ImageTk.PhotoImage(make_logo(32))
        self._icon_lbl.config(image=self._icon_img)

        threading.Thread(target=self._tray.run, daemon=True).start()
        self.root.mainloop()


if __name__ == "__main__":
    CaffeinatedApp().run()
