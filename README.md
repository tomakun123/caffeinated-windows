<img src="screenshots/logo.png" width="96" align="right" alt="CaffeinatedWin logo">

# CaffeinatedWin ☕ (Windows)

CaffeinatedWin is a lightweight Windows tray app that prevents your PC from sleeping — inspired by macOS caffeinate

## Features
- Runs in the system tray
- Prevents system sleep
- Optional “keep display on”
- Timer mode (30 / 60 / 120 minutes)
- "Turn off display" button
- Hotkeys: global chord (default `Ctrl+/` then `Q` quit / `D` display off / `C` toggle), plain keys when the window is focused; all rebindable
- Optional run at startup
- Clean exit restores normal sleep behavior

## Screenshots
![Tray Menu](screenshots/tray.png)
![Wizard Setup](screenshots/wizardSetup.png)

## Installation
1. Download the latest installer from **Releases**
2. Run `CaffeinatedWin-Setup.exe`
3. Launch from Start Menu or Desktop

## Notes
- No admin rights required
- No background services
- Uses native Windows power APIs

## FAQ

**Does this install a background service?**  
No. It runs only as a tray app.

**Does it require admin privileges?**  
No.

**Is my data collected?**  
No. The app does not collect or transmit any data.

**What happens when I quit or uninstall?**  
Normal sleep behavior is fully restored.


## What's new in 1.1.0
- Settings are saved between sessions (auto-start, keep display on, launch at Windows startup) — fixes #1
- Fixed "Turn off display" (it silently did nothing on 64-bit builds)
- Hotkeys: global chord `Ctrl+/` then `Q` (quit) / `D` (display off) / `C` (toggle); plain keys when the window is focused; all rebindable from the new Hotkeys card
- New logo everywhere (tray, window, taskbar, installer)

## License
MIT
