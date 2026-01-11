import sys
import time
import threading
from dataclasses import dataclass
from typing import Optional

import pystray
from pystray import MenuItem as Item
from PIL import Image, ImageDraw

from keepAwake import set_awake, clear_awake

APP_NAME = "Caffeinated (Win)"


@dataclass
class State:
    enabled: bool = False
    keep_display_on: bool = False
    # timer_end is epoch seconds, or None for indefinite
    timer_end: Optional[float] = None


def make_icon_image(size: int = 64) -> Image.Image:
    """
    Simple coffee-cup-ish icon drawn with Pillow.
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # cup
    margin = size // 6
    cup_w = size - 2 * margin
    cup_h = size // 2
    cup_x0 = margin
    cup_y0 = size // 3
    cup_x1 = cup_x0 + cup_w
    cup_y1 = cup_y0 + cup_h

    d.rounded_rectangle([cup_x0, cup_y0, cup_x1, cup_y1], radius=8, fill=(30, 30, 30, 255))
    # coffee
    d.rounded_rectangle([cup_x0 + 6, cup_y0 + 8, cup_x1 - 6, cup_y0 + cup_h // 2], radius=6, fill=(120, 70, 25, 255))
    # saucer
    d.ellipse([cup_x0 + 4, cup_y1 - 6, cup_x1 - 4, cup_y1 + 10], fill=(30, 30, 30, 255))
    # handle
    hx0 = cup_x1 - 8
    hy0 = cup_y0 + cup_h // 4
    hx1 = cup_x1 + margin // 2
    hy1 = cup_y0 + cup_h // 2 + cup_h // 6
    d.ellipse([hx0, hy0, hx1, hy1], outline=(30, 30, 30, 255), width=6)

    # steam
    for i in range(3):
        x = cup_x0 + (i + 1) * cup_w // 4
        d.arc([x - 8, cup_y0 - 22, x + 8, cup_y0 - 2], start=200, end=340, fill=(30, 30, 30, 180), width=3)

    return img


class CaffeinatedTrayApp:
    def __init__(self):
        self.state = State()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

        self.icon = pystray.Icon(
            name=APP_NAME,
            icon=make_icon_image(),
            title=APP_NAME,
            menu=self._build_menu(),
        )

        # background loop to refresh execution state + tooltip + timers
        self._thread = threading.Thread(target=self._heartbeat_loop, daemon=True)

    def _build_menu(self):
        return pystray.Menu(
            Item(lambda item: "✅ Stop" if self.state.enabled else "☕ Start", self.toggle_enabled, default=True),
            Item("Keep screen on", self.toggle_keep_display, checked=lambda _: self.state.keep_display_on),
            pystray.Menu.SEPARATOR,
            Item("Timer: 30 minutes", lambda: self.start_timer(30)),
            Item("Timer: 60 minutes", lambda: self.start_timer(60)),
            Item("Timer: 120 minutes", lambda: self.start_timer(120)),
            Item("Timer: Indefinite", self.clear_timer),
            pystray.Menu.SEPARATOR,
            Item("Quit", self.quit_app),
        )

    def run(self):
        if not sys.platform.startswith("win"):
            print("This tray app is intended for Windows. Exiting.")
            return

        self._thread.start()
        self.icon.run()

    def _set_enabled(self, enabled: bool):
        with self._lock:
            self.state.enabled = enabled
            if not enabled:
                self.state.timer_end = None

        self._apply_power_state()
        self.icon.update_menu()

    def toggle_enabled(self, icon=None, item=None):
        with self._lock:
            new_val = not self.state.enabled
        self._set_enabled(new_val)

    def toggle_keep_display(self, icon=None, item=None):
        with self._lock:
            self.state.keep_display_on = not self.state.keep_display_on
        if self.state.enabled:
            self._apply_power_state()
        self.icon.update_menu()

    def start_timer(self, minutes: int):
        end = time.time() + minutes * 60
        with self._lock:
            self.state.enabled = True
            self.state.timer_end = end
        self._apply_power_state()
        self.icon.update_menu()

    def clear_timer(self, icon=None, item=None):
        with self._lock:
            if self.state.enabled:
                self.state.timer_end = None
        self.icon.update_menu()

    def _apply_power_state(self):
        """
        Apply the current requested execution state to Windows.
        """
        with self._lock:
            enabled = self.state.enabled
            keep_display = self.state.keep_display_on

        try:
            if enabled:
                set_awake(keep_display_on=keep_display)
            else:
                clear_awake()
        except Exception as e:
            # If anything goes wrong, fail safe.
            try:
                clear_awake()
            except Exception:
                pass
            self._show_message("Error", f"Failed to set keep-awake state:\n{e}")

    def _tooltip_text(self) -> str:
        with self._lock:
            enabled = self.state.enabled
            keep_display = self.state.keep_display_on
            timer_end = self.state.timer_end

        if not enabled:
            return f"{APP_NAME}\nStatus: OFF"

        line2 = "Status: ON (sleep blocked)"
        line3 = f"Display: {'ON' if keep_display else 'can sleep'}"

        if timer_end is None:
            return f"{APP_NAME}\n{line2}\n{line3}\nTimer: Indefinite"

        remaining = max(0, int(timer_end - time.time()))
        mm, ss = divmod(remaining, 60)
        hh, mm = divmod(mm, 60)
        if hh > 0:
            t = f"{hh:d}:{mm:02d}:{ss:02d}"
        else:
            t = f"{mm:d}:{ss:02d}"
        return f"{APP_NAME}\n{line2}\n{line3}\nTimer: {t} remaining"

    def _heartbeat_loop(self):
        """
        Re-assert the execution state periodically (safe practice),
        update tooltip, and enforce timers.
        """
        while not self._stop_event.is_set():
            with self._lock:
                enabled = self.state.enabled
                timer_end = self.state.timer_end

            # enforce timer
            if enabled and timer_end is not None and time.time() >= timer_end:
                self._set_enabled(False)
                self._show_message("Timer finished", "Keep-awake turned OFF.")

            # re-assert keep-awake every ~20s while enabled
            if enabled:
                self._apply_power_state()

            # tooltip update
            try:
                self.icon.title = self._tooltip_text()
            except Exception:
                pass

            time.sleep(20)

    def _show_message(self, title: str, message: str):
        # pystray supports notifications on some setups; if not, ignore.
        try:
            self.icon.notify(message, title)
        except Exception:
            pass

    def quit_app(self, icon=None, item=None):
        self._stop_event.set()
        try:
            clear_awake()
        except Exception:
            pass
        self.icon.stop()


if __name__ == "__main__":
    CaffeinatedTrayApp().run()
