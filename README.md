# AIsnip

A Windows-focused screen snip and annotation tool for sending marked-up screenshots to an AI chat.

## Features

- Assign a global shortcut by clicking keys on an on-screen keyboard.
- Assign a separate hold shortcut for window selection.
- Assign a separate shortcut for full-screen snapshots.
- Use keyboard keys or mouse buttons, including middle/right and side buttons, for shortcuts.
- Selected shortcut keys and mouse buttons stay highlighted in the shortcut picker.
- The shortcut picker shows a top-view mouse drawing with clickable left, right, wheel, X1, and X2 buttons.
- AIsnip warns when a selected shortcut may conflict with a common Windows shortcut.
- Snip a screen region, capture the whole screen, or pick a window.
- Hold the window shortcut, such as `f8`, to highlight the window under the cursor and capture it on release.
- Draw arrows, notation bubbles, rectangles, circles/ellipses, and lines.
- Click with the bubble tool to type a note and create an auto-sized callout with a tail pointing at the clicked spot.
- Hover annotations to highlight them, click to select, drag to move, and drag handles to reshape. Press `Delete` to remove the selected item, press `Ctrl+Z` to undo, and double-click a bubble to edit its text.
- Change item color and increase/decrease item size.
- Minimize to the system tray and keep listening for the shortcut in the background.
- Optionally run AIsnip when Windows starts.
- Press **Done** to flatten the annotation and copy it to the clipboard.

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pythonw aisnip.py
```

You can also launch it with `run_aisnip.bat` or `run_aisnip.ps1` to avoid a console window.

## Build EXE

```powershell
python -m PyInstaller --noconfirm --clean --onefile --windowed --name AIsnip --add-data "assets;assets" aisnip.py
```

The built executable is written to `dist\AIsnip.exe`.

## Startup

Enable **Run AIsnip when Windows starts** in the app. This creates a per-user startup entry and launches with `pythonw.exe` so no console window appears.

## Shortcut Notes

The default snip shortcut is `shift+mouse:right`. Use **Choose Keys** in the app to select modifier keys and a main key from the on-screen keyboard.

The default hold-to-select-window shortcut is `shift+mouse:left`. Press and hold it to highlight the window under the cursor, then release it to capture that window for notation.

The default full-screen snapshot shortcut is `shift+mouse:middle`. Press it once to capture the whole screen and open it for notation.

Use the shortcuts this way:

- **Snip Region Shortcut**: press once, then drag over the area of the screen you want to capture.
- **Select Window Shortcut**: press and hold, move the cursor over the target window, then release. AIsnip brings that window to the front and captures it for notation.
- **Full Screen Snapshot Shortcut**: press once to capture the whole screen.

Supported shortcut examples:

- `ctrl+shift+s`
- `alt+shift+a`
- `f8`
- `mouse:x1`
- `ctrl+mouse:middle`

For the "hold to highlight a window" workflow, use **Choose Hold Key**. `f8` is recommended because it is easy to hold without interfering with typing.
